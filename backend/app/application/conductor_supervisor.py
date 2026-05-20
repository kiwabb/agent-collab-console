"""ConductorSupervisor — the workflow's "5th agent" that observes every
task completion and decides whether to nudge.

For v0 we run it on EVERY task completion (per user preference to start
maximal, then prune). Each call is bounded:
  - Input: <500 tokens (just the just-completed task summary + graph state)
  - Output: a small JSON {action, reason, note?} ~150 tokens
  - On any failure (timeout, parse error, no catalog), we silently no-op
    so the scheduler keeps working.

Six possible decisions:
  - "proceed"               : nothing to say; scheduler continues as planned
  - "note"                  : Conductor learned something it wants persisted into
                              team_notes.md so future runs benefit. We append it.
  - "escalate"              : something is off; emit a flagged event so the UI can
                              surface a Conductor banner. We do NOT modify flow yet.
  - "insert_node"           : propose inserting a new agent node into the graph
  - "reroute"               : propose re-routing edges in the graph
  - "request_clarification" : ask the user a question before proceeding

We always emit a `conductor_decision` event so the AgentDock dot can
glow regardless of decision shape. This is the visible feedback that
Conductor is alive each round.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any
from uuid import uuid4

from app.domain.models import CodexIssue, CodexTask, WorkflowGraph

logger = logging.getLogger(__name__)

_VALID_ACTIONS = {"proceed", "note", "escalate", "reroute", "insert_node", "request_clarification"}


class ConductorSupervisor:
    """Observe a just-completed task and emit a decision."""

    def __init__(self, store, event_bus) -> None:
        self.store = store
        self._event_bus = event_bus

    async def observe(
        self,
        *,
        task: CodexTask,
        node_status: str,
        graph: WorkflowGraph,
        issue: CodexIssue | None,
    ) -> dict[str, Any] | None:
        """Run one observation pass. Returns the decision dict or None on
        failure. Always best-effort: callers should not depend on it."""
        if os.getenv("CONDUCTOR_ENABLED", "true").lower() != "true":
            return None

        snapshot = self._build_snapshot(task=task, node_status=node_status, graph=graph, issue=issue)

        # Resolve LLM runner. If no catalog / no API key, fall back to a
        # heuristic decision so we still emit *something* every round.
        decision = await self._invoke_llm(snapshot)
        if decision is None:
            decision = self._heuristic_decision(snapshot)

        action = decision.get("action") or "proceed"

        # Build diff payload for graph-mutation actions so the scheduler can act on it.
        diff: dict | None = None
        if action == "insert_node":
            diff = self._build_insert_node_diff(decision, graph, snapshot)
            if diff is not None:
                decision["diff"] = diff
        elif action == "reroute":
            diff = self._build_reroute_diff(decision, graph)
            if diff is not None:
                decision["diff"] = diff

        # Persist decision record.
        issue_id = issue.id if issue else (task.issue_id or "")
        try:
            if issue_id and hasattr(self.store, "save_conductor_decision"):
                from app.domain.models import ConductorDecision
                record = ConductorDecision(
                    id=str(uuid4()),
                    issue_id=issue_id,
                    task_id=task.id,
                    action=action,
                    reason=decision.get("reason"),
                    diff_json=json.dumps(diff, ensure_ascii=False, default=str) if diff is not None else None,
                    applied_at=None,
                    created_at=datetime.now(),
                )
                await self.store.save_conductor_decision(record)
        except Exception as exc:  # noqa: BLE001
            logger.debug("conductor persist decision failed: %s", exc)

        # Emit visible event so frontend AgentDock can glow.
        try:
            if self._event_bus is not None and issue is not None:
                await self._event_bus.append({
                    "type": "conductor_decision",
                    "session_id": issue.session_id,
                    "issue_id": issue.id,
                    "task_id": task.id,
                    "role": task.role,
                    "action": action,
                    "reason": decision.get("reason"),
                    "note": decision.get("note"),
                })
        except Exception as exc:  # noqa: BLE001
            logger.debug("conductor emit failed: %s", exc)

        # Persist team-level learning when Conductor produced a note.
        if action == "note" and decision.get("note") and issue is not None:
            await self._append_team_note(issue, decision["note"])

        return decision

    # ------------------------------------------------------------------
    # Internals

    def _build_snapshot(
        self,
        *,
        task: CodexTask,
        node_status: str,
        graph: WorkflowGraph,
        issue: CodexIssue | None,
    ) -> dict[str, Any]:
        """Construct a compact JSON payload for the LLM. Keep this small."""
        node_statuses = {n.node_key: n.status for n in graph.nodes}
        # Bound task.result to keep prompt small; QA reports can be long.
        result_excerpt = (task.result or "")[:1200]
        # Collect available agent role_keys from graph nodes + common builtin roles.
        graph_roles = list({n.node_key for n in graph.nodes})
        common_roles = ["security_reviewer", "performance_reviewer", "documentation_writer", "code_reviewer"]
        available_agents = sorted(set(graph_roles + common_roles))
        return {
            "issue_id": issue.id if issue else task.issue_id,
            "issue_title": (issue.title if issue else None) or task.title,
            "issue_status": issue.status if issue else None,
            "issue_phase": issue.current_phase if issue else None,
            "completed_role": task.role,
            "completed_status": node_status,
            "task_result_excerpt": result_excerpt,
            "review_comment": task.review_comment,
            "graph_node_statuses": node_statuses,
            "retries": {
                n.node_key: {"used": n.retries, "max": n.max_retries}
                for n in graph.nodes
            },
            "available_agents": available_agents,
        }

    async def _invoke_llm(self, snapshot: dict[str, Any]) -> dict[str, Any] | None:
        try:
            from app.application.llm_runner import build_llm_runner
            try:
                from app.bootstrap import get_runtime_catalog_service
                catalog_service = get_runtime_catalog_service()
            except (ImportError, AttributeError):
                try:
                    from app.interfaces.api import _get_runtime_catalog_service
                    catalog_service = _get_runtime_catalog_service()
                except Exception:  # noqa: BLE001
                    return None
            if catalog_service is None:
                return None
            runner = build_llm_runner(catalog_service)
        except Exception as exc:  # noqa: BLE001
            logger.debug("conductor llm runner build failed: %s", exc)
            return None

        prompt = self._build_prompt(snapshot)
        try:
            raw = await runner(prompt)
        except Exception as exc:  # noqa: BLE001
            logger.debug("conductor LLM call failed: %s", exc)
            return None
        if not raw:
            return None
        return self._parse_decision(raw)

    @staticmethod
    def _build_prompt(snapshot: dict[str, Any]) -> str:
        available_agents = snapshot.get("available_agents", [])
        return (
            "You are Conductor — the workflow orchestrator and 5th agent in a PM/Architect/Engineer/QA team. "
            "You observe each task completion. Your job is to spot cross-cutting issues (tool mismatches, "
            "agents looping on the wrong root cause, ambiguous handoffs) and either let the workflow proceed, "
            "record a durable team learning, flag a problem, or propose a graph mutation.\n\n"
            "Bias HARD toward 'proceed' — only intervene when the situation clearly needs cross-agent insight.\n\n"
            f"Available agent role_keys you may reference: {available_agents}\n\n"
            "Output STRICT JSON, no markdown, exactly one of these shapes:\n"
            '  {"action":"proceed","reason":"<one short sentence>"}\n'
            '  {"action":"note","reason":"<why>","note":"<single-line team_notes.md entry>"}\n'
            '  {"action":"escalate","reason":"<why>","note":"<single-line summary for the user>"}\n'
            '  {"action":"insert_node","reason":"<why>","node_key":"<role from available_agents>","insert_after":"<existing node_key>","title":"<human title>"}\n'
            '  {"action":"reroute","reason":"<why>","from":"<node_key>","to":"<node_key>"}\n'
            '  {"action":"request_clarification","reason":"<why>","note":"<question for user>"}\n\n'
            "Guidance:\n"
            "- action=proceed: everything is normal, no team-level signal.\n"
            "- action=note: ONLY when you've discovered a repo convention or recurring failure pattern future agents should know. "
            "Keep the note <140 chars. Imperative voice. Specific.\n"
            "- action=escalate: ONLY when the workflow is stuck in a loop the team can't break (e.g. same QA exit code 2+ rounds in a row).\n"
            "- action=insert_node: ONLY when a critical role (e.g. security_reviewer) is clearly missing and the issue clearly requires it. "
            "node_key must be from available_agents list. insert_after must be an existing node_key.\n"
            "- action=reroute: ONLY when the current edge ordering is provably wrong (e.g. QA must run before deployment).\n"
            "- action=request_clarification: ONLY when you cannot proceed without a human decision.\n\n"
            "Observation snapshot:\n"
            + json.dumps(snapshot, ensure_ascii=False)
        )

    @staticmethod
    def _parse_decision(raw: str) -> dict[str, Any] | None:
        text = raw.strip()
        # Strip code fences if any sneaked in.
        if text.startswith("```"):
            text = text.strip("`")
            # Drop leading "json" tag if present.
            if text.lower().startswith("json"):
                text = text[4:].strip()
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            # Try to find a JSON object inside.
            try:
                start = text.index("{")
                end = text.rindex("}")
                payload = json.loads(text[start : end + 1])
            except (ValueError, json.JSONDecodeError):
                return None
        if not isinstance(payload, dict):
            return None
        action = payload.get("action")
        if action not in _VALID_ACTIONS:
            return None
        return payload

    @staticmethod
    def _heuristic_decision(snapshot: dict[str, Any]) -> dict[str, Any]:
        """Fallback when no LLM is available. Deterministic, always proceeds,
        but lets us still emit the per-round event so the dock isn't dead."""
        retries = snapshot.get("retries") or {}
        engineer = retries.get("engineer") or {}
        qa = retries.get("qa") or {}
        if (engineer.get("used") or 0) >= 2 or (qa.get("used") or 0) >= 2:
            return {
                "action": "escalate",
                "reason": "Engineer or QA hit the retry budget — manual review recommended.",
                "note": None,
            }
        return {"action": "proceed", "reason": "Heuristic: no LLM configured."}

    @staticmethod
    def _build_insert_node_diff(decision: dict[str, Any], graph: WorkflowGraph, snapshot: dict[str, Any]) -> dict | None:
        """Build an _apply_diff_to_graph-compatible diff for insert_node."""
        node_key = decision.get("node_key")
        insert_after = decision.get("insert_after")
        title = decision.get("title") or node_key
        if not node_key or not insert_after:
            return None

        # Find an agent_id to use: look up from existing graph nodes by role_key match,
        # or fall back to a placeholder so the diff is structurally valid.
        agent_id: str | None = None
        for n in graph.nodes:
            if n.node_key == node_key:
                agent_id = n.agent_id  # reuse if already in graph
                break
        if agent_id is None:
            # Use a sentinel; WorkflowOrchestrator / _apply_diff_to_graph will need
            # the real agent_id resolved before persisting — we signal this via the
            # diff being present so the scheduler can resolve it.
            agent_id = f"__role__{node_key}"

        # Find nodes that insert_after currently points to (downstream of insert_after).
        downstream_keys = [
            e.to_node_key for e in graph.edges
            if e.from_node_key == insert_after and e.edge_type == "sequence"
        ]

        added_edges: list[dict] = [
            {"from_node_key": insert_after, "to_node_key": node_key, "edge_type": "sequence"}
        ]
        for dk in downstream_keys:
            added_edges.append({"from_node_key": node_key, "to_node_key": dk, "edge_type": "sequence"})

        return {
            "added_nodes": [{"node_key": node_key, "agent_id": agent_id, "title": title}],
            "added_edges": added_edges,
            "removed_node_keys": [],
        }

    @staticmethod
    def _build_reroute_diff(decision: dict[str, Any], graph: WorkflowGraph) -> dict | None:
        """Build an _apply_diff_to_graph-compatible diff for reroute."""
        from_key = decision.get("from")
        to_key = decision.get("to")
        if not from_key or not to_key:
            return None
        # Add the new direct edge; leave removal to the user's confirm step.
        return {
            "added_nodes": [],
            "added_edges": [{"from_node_key": from_key, "to_node_key": to_key, "edge_type": "sequence"}],
            "removed_node_keys": [],
        }

    async def _append_team_note(self, issue: CodexIssue, note: str) -> None:
        try:
            if not issue.project_id:
                return
            project = await self.store.load_project(issue.project_id)
            if project is None or not getattr(project, "repo_path", None):
                return
            from pathlib import Path
            path = Path(project.repo_path) / ".agent-collab" / "team_notes.md"
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
            except OSError:
                return
            existing = ""
            if path.exists():
                try:
                    existing = path.read_text(encoding="utf-8")
                except OSError:
                    existing = ""
            # Skip if the exact note line is already there — Conductor can
            # rediscover the same convention across runs.
            stripped_note = note.strip()
            if stripped_note and stripped_note in existing:
                return
            block = f"\n- [Conductor] {stripped_note}\n"
            try:
                path.write_text((existing + block).strip() + "\n", encoding="utf-8")
            except OSError as exc:  # noqa: BLE001
                logger.debug("conductor write team_notes failed: %s", exc)
        except Exception as exc:  # noqa: BLE001
            logger.debug("conductor append_team_note failed: %s", exc)
