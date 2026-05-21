"""Workflow DAG scheduler.

Owns the lifecycle of a WorkflowGraph once started: detects which nodes are
ready (deps satisfied), dispatches them as CodexTasks via the existing
task runner, watches for completion via the event bus, and walks the graph
forward until done.

PR3 ships a minimal vertical slice — sequence/parallel-fanout edges are
honored; refine-loop and retry-on-fail land in PR6 alongside the Replanner.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime
from uuid import uuid4

from app.application.agent_catalog.catalog import (
    CUSTOM_PREFIX,
    SPECIALIST_PREFIX,
    AgentCatalog,
    AgentDefinition,
)
from app.domain.models import (
    Agent,
    AgentMessage,
    CodexIssue,
    CodexTask,
    WorkflowEdge,
    WorkflowGraph,
    WorkflowNode,
)

logger = logging.getLogger(__name__)


class WorkflowSchedulerError(RuntimeError):
    pass


class WorkflowScheduler:
    """Dispatches DAG nodes for a single issue.

    Construction is cheap; the scheduler is driven by on_task_completed callbacks
    and the Conductor loop (run_issue_conductor_loop) which dispatches agents directly.
    """

    def __init__(self, store, task_dispatcher=None, event_bus=None) -> None:
        self.store = store
        self._task_dispatcher = task_dispatcher  # callable(task) -> awaitable, optional
        self._event_bus = event_bus

    async def _emit_node_event(self, node: WorkflowNode, issue: CodexIssue | None) -> None:
        """Best-effort emit of workflow_node_updated so the frontend DAG/
        IssueDetail can refetch immediately on transitions (pending→running,
        running→done/failed, qa-rework→pending) instead of waiting for the
        next poll cycle."""
        if self._event_bus is None or issue is None:
            return
        try:
            await self._event_bus.append({
                "type": "workflow_node_updated",
                "issue_id": issue.id,
                "session_id": issue.session_id,
                "node_id": node.id,
                "node_key": node.node_key,
                "status": node.status,
                "task_id": node.task_id,
            })
        except Exception as exc:  # noqa: BLE001
            logger.debug("workflow_node_updated emit failed: %s", exc)

    # --- Public API ---

    async def on_task_completed(self, task: CodexTask) -> None:
        """Hook called by the task runner / event handler once a task ends.

        Looks up the workflow_node for the task, updates its status, then:
          1. consider retry-on-fail edges (auto-retry without user input)
          2. handle QA-fail → Engineer auto-rework (no user prompt; bounded
             by engineer.max_retries)
          3. consider replan triggers (suspend graph, surface diff to user)
          4. fall through to a regular settle pass
        """
        if not getattr(task, "workflow_node_id", None):
            return
        node = await self.store.find_node_by_task_id(task.id)
        if node is None:
            return
        terminal = self._task_status_to_node_status(task.status)
        if terminal is None:
            return
        await self.store.update_workflow_node(
            node.id,
            status=terminal,
            completed_at=datetime.now(),
        )
        node.status = terminal
        graph = await self.store.load_workflow_graph(node.graph_id)
        if graph is None:
            return
        # Notify subscribers of the node transition so the DAG / IssueDetail
        # views update in the same tick as task_status — without this, the
        # graph still ticks via polling.
        issue_for_event = None
        try:
            issue_for_event = await self.store.load_codex_issue(graph.issue_id)
            await self._emit_node_event(node, issue_for_event)
        except Exception:  # noqa: BLE001
            pass

        # Signal TaskCompletionRegistry so Conductor's dispatch_subagent tool can unblock
        from app.application.task_completion_registry import TaskCompletionRegistry
        reg = TaskCompletionRegistry.get()
        if reg.is_registered(task.id):
            from app.application.subagent_result_builder import build_subagent_result
            try:
                subagent_result = build_subagent_result(
                    task=task,
                    node=node,
                    doc=getattr(task, "_subagent_doc", None),
                )
                reg.signal(task.id, {
                    "task_id": task.id,
                    "role": task.role,
                    "status": task.status,
                    "summary": subagent_result.summary,
                    "artifact_json": subagent_result.artifact_json,
                    "files_changed": subagent_result.files_changed,
                    "qa_commands": subagent_result.qa_commands,
                    "clarification_question": subagent_result.clarification_question,
                })
            except Exception as exc:  # noqa: BLE001
                reg.signal(task.id, {"task_id": task.id, "role": task.role, "status": task.status, "summary": task.result or ""})

        # Phase 4: Specialist mesh handling. If this task is a specialist_child,
        # resume the parent after collecting the specialist's result.
        if task.task_kind == "specialist_child" and task.status == "done":
            if await self._maybe_resume_from_specialist(task, graph):
                return

        # Finalize the graph if all nodes are terminal.
        await self._maybe_finalize(graph)

        # Record project memory if graph is done.
        latest_graph = await self.store.load_workflow_graph(graph.id)
        if latest_graph is not None:
            await self._record_project_memory(latest_graph)
            await self._maybe_advance_phase(latest_graph)

    async def _maybe_resume_from_specialist(
        self, specialist_child_task: CodexTask, graph: WorkflowGraph
    ) -> bool:
        """Phase 4: Handle specialist child task completion and parent resumption.

        When a specialist child task completes successfully, inject its result
        into the parent task's review_comment and reset the parent to pending
        so it can re-run with the specialist findings.

        Returns True if parent was resumed (caller should not continue to scheduler logic).
        """
        if specialist_child_task.task_kind != "specialist_child":
            return False
        if specialist_child_task.status != "done":
            return False

        parent = await self.store.load_codex_task(specialist_child_task.parent_task_id)
        if parent is None:
            logger.warning(
                "Specialist child %s has no parent task",
                specialist_child_task.id,
            )
            return False

        now = datetime.now()

        # Build specialist result summary from the task result
        # The specialist's raw result is already in specialist_child_task.result
        specialist_summary = specialist_child_task.result or "(no result)"
        if len(specialist_summary) > 1000:
            specialist_summary = specialist_summary[:1000] + "\n... (truncated)"

        # Inject specialist result into parent's review_comment
        continuation = (
            f"[SPECIALIST RESULT from {specialist_child_task.role}]\n\n"
            f"{specialist_summary}\n\n"
            f"Incorporate the above specialist findings into your next output."
        )
        if parent.review_comment:
            parent.review_comment = parent.review_comment + "\n\n" + continuation
        else:
            parent.review_comment = continuation

        # Reset parent to pending so the scheduler will re-dispatch it
        parent.status = "pending"
        parent.updated_at = now
        await self.store.save_codex_task(parent)

        # Record specialist result as AgentMessage for the collab feed
        try:
            msg = AgentMessage(
                id=str(uuid4()),
                issue_id=parent.issue_id,
                graph_id=graph.id if graph else "",
                from_node_key=specialist_child_task.role,
                to_node_key=parent.role,
                message_type="specialist_result",
                body=specialist_summary[:500],
                created_at=now,
            )
            await self.store.save_agent_message(msg)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Failed to record specialist result message: %s", exc)

        # Emit events for real-time updates
        try:
            await self._event_bus.append({
                "type": "specialist_completed",
                "parent_task_id": parent.id,
                "child_task_id": specialist_child_task.id,
                "specialist_role": specialist_child_task.role,
            })
            await self._event_bus.append({
                "type": "task_status",
                "task_id": parent.id,
                "session_id": parent.session_id,
                "status": parent.status,
            })
        except Exception:  # noqa: BLE001
            pass

        # Re-dispatch the parent node now that it is reset to pending.
        try:
            parent_node = await self.store.find_node_by_task_id(parent.id)
            if parent_node is not None:
                parent_issue = await self.store.load_codex_issue(parent.issue_id)
                all_agents = await self.store.list_agents(workspace_id=None)
                agents_by_id = {a.id: a for a in all_agents}
                await self.store.update_workflow_node(parent_node.id, status="pending")
                await self._dispatch_node(parent_node, parent_issue, agents_by_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to re-dispatch parent after specialist: %s", exc)

        return True

    async def _ensure_catalog_agent(self, definition: AgentDefinition) -> Agent:
        if definition.role_key.startswith(CUSTOM_PREFIX):
            role_key = definition.role_key
            tier = "custom"
            artifact_role = definition.role_key
            system_prompt = definition.prompt_template
            is_builtin = False
        else:
            role_key = f"{SPECIALIST_PREFIX}{definition.role_key}"
            tier = "specialist"
            artifact_role = definition.role_key
            system_prompt = f"[specialist:{definition.role_key}]"
            is_builtin = True

        existing = await self.store.list_agents(workspace_id=None, role_key=role_key)
        if existing:
            return existing[0]

        now = datetime.now()
        agent = Agent(
            id=f"agent-{role_key.replace(':', '-')}",
            workspace_id=None,
            name=definition.display_name,
            role_key=role_key,
            description=definition.prompt_template,
            system_prompt_template=system_prompt,
            output_schema=definition.output_schema,
            default_executor="claude",
            artifact_subdir=f"specialists/{artifact_role}",
            persist_kind="specialist",
            agent_tier=tier,
            is_builtin=is_builtin,
            created_at=now,
            updated_at=now,
        )
        await self.store.save_agent(agent)
        return agent

    @staticmethod
    def _unique_node_key(base: str, existing: set[str]) -> str:
        if base not in existing:
            return base
        index = 1
        while f"{base}_{index}" in existing:
            index += 1
        return f"{base}_{index}"

    # --- Internal helpers ---

    async def _require_graph(self, graph_id: str) -> WorkflowGraph:
        graph = await self.store.load_workflow_graph(graph_id)
        if graph is None:
            raise WorkflowSchedulerError(f"Workflow graph {graph_id} not found")
        return graph

    def _compute_node_status(
        self,
        node: WorkflowNode,
        incoming_edges: list[WorkflowEdge],
        nodes_by_key: dict[str, WorkflowNode],
    ) -> str | None:
        if node.status in {"running", "done", "failed", "skipped"}:
            return None
        # Only sequence and parallel-fanout edges gate readiness. Refine-loop
        # back-edges are explicitly *not* dependencies — they exist to allow
        # rework cycles without breaking topo order.
        gating = [e for e in incoming_edges if e.edge_type in {"sequence", "parallel-fanout"}]
        if not gating:
            return "ready"
        all_done = all(
            (parent := nodes_by_key.get(e.from_node_key)) is not None
            and parent.status == "done"
            for e in gating
        )
        return "ready" if all_done else "blocked"

    def _task_status_to_node_status(self, task_status: str) -> str | None:
        if task_status == "done":
            return "done"
        if task_status in {"failed", "error"}:
            return "failed"
        return None

    async def _dispatch_node(
        self,
        node: WorkflowNode,
        issue: CodexIssue,
        agents_by_id: dict[str, Agent],
    ) -> None:
        agent = agents_by_id.get(node.agent_id)
        if agent is None:
            logger.warning("Workflow node %s references missing agent %s — skipping", node.id, node.agent_id)
            await self.store.update_workflow_node(node.id, status="skipped")
            return

        prompt = node.prompt_override or self._render_prompt_template(agent, issue, node)
        # `[builtin:<role>]` is a placeholder telling the runtime to defer to
        # RoleWorkflowService — but downstream prompt builders use
        # `task.prompt` as the *user_requirement* line. Substitute the real
        # issue title + description so PM/Architect/Engineer/QA see actual
        # context, not the literal `[builtin:engineer]` string.
        if isinstance(prompt, str) and prompt.startswith("[builtin:"):
            issue_body = (issue.description or "").strip()
            if issue.title and issue_body:
                prompt = f"{issue.title}\n\n{issue_body}"
            else:
                prompt = issue.title or issue_body or prompt

        # Engineer rework: when this is a retry caused by an upstream QA
        # failure, surface the most recent QA report on disk as feedback so
        # the engineer prompt builder includes it under "REWORK REQUIRED".
        # Fallback: when QA didn't fail (e.g. human rejected a passing run),
        # use issue.review_comment so the user's note still reaches engineer.
        # Also covers multi-instance engineer nodes like `engineer#0`, `engineer#1`
        # and Phase-1 parallel roles like `engineer_frontend`, `engineer_backend`.
        is_engineer_role = agent.role_key == "engineer" or node.node_key.startswith("engineer")
        review_comment = None
        if is_engineer_role and node.retries > 0 and issue.git_worktree_path:
            review_comment = self._read_latest_qa_failure_summary(
                issue.git_worktree_path, issue.id
            )
            if not review_comment and getattr(issue, "review_comment", None):
                review_comment = issue.review_comment
        if agent.role_key == "architect" and getattr(issue, "review_comment", None):
            review_comment = issue.review_comment

        # Inherit worktree/git state from the issue so the runner can locate
        # artifacts. Falls back to None when the issue has no worktree yet
        # (tests, ephemeral issues) — the runner should tolerate that.
        # Built-in role workflows treat `task.title` as the user-facing issue
        # title (it ends up in PRD `issue_title` and engineer `issue_title`
        # fields). When the node title is a generic role tag, prefer the
        # actual issue title so artifacts capture the real intent.
        managed_role = agent.role_key in {"product_manager", "architect", "engineer", "qa"}
        effective_title = (
            issue.title
            if (managed_role and issue.title)
            else (node.title or agent.name)
        )

        # For multi-instance same-role nodes (e.g. engineer#0, engineer#1) and
        # Phase-1 parallel roles (engineer_frontend, engineer_backend), use the
        # node_key as task.role so artifact subdirectory isolation works
        # automatically — EngineerWorkflow uses role.startswith("engineer") to
        # determine the subdir, and the node_key encodes the instance identity.
        # Single-role nodes keep the canonical agent.role_key for back-compat.
        effective_role = (
            node.node_key
            if (node.node_key != agent.role_key and node.node_key.startswith(agent.role_key))
            else agent.role_key
        )

        # Phase 4: multi-instance engineer nodes carry a subtask scope in their
        # title (set by the orchestrator from subtask_split). Prepend the scope
        # to the prompt so the engineer knows which workstream to tackle.
        if "#" in node.node_key and is_engineer_role and node.title and node.title not in (prompt or ""):
            scope_prefix = f"[SUBTASK SCOPE: {node.title}]\n\n"
            prompt = scope_prefix + (prompt or "")

        task = CodexTask(
            id=str(uuid4()),
            session_id=issue.session_id,
            project_id=issue.project_id,
            issue_id=issue.id,
            phase=agent.role_key,  # Free-form tag now; kept for backward compat with old kanban
            title=effective_title,
            prompt=prompt,
            role=effective_role,
            executor=agent.default_executor or "codex",
            provider=agent.default_provider,
            model=agent.default_model,
            status="pending",
            workspace_path=issue.git_worktree_path,
            git_branch=issue.git_branch,
            git_base_branch=issue.git_base_branch,
            git_worktree_path=issue.git_worktree_path,
            workflow_node_id=node.id,
            review_comment=review_comment,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        await self.store.save_codex_task(task)
        # Broadcast the new task to connected clients so the RunDetail / task
        # list updates immediately on stage transitions (e.g. architect→engineer).
        # Without this, the frontend only learns about the task when the runner
        # finally pushes a task_status patch and forces a manual refresh.
        if self._event_bus is not None:
            try:
                from app.application.task_serialization import serialize_task_payload
                await self._event_bus.append({
                    "type": "task_created",
                    "task": serialize_task_payload(task),
                })
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Failed to emit task_created for workflow node %s: %s",
                    node.node_key,
                    exc,
                )
        if agent.role_key == "architect" and getattr(issue, "review_comment", None):
            issue.review_comment = None
            issue.updated_at = datetime.now()
            await self.store.save_codex_issue(issue)
        await self.store.update_workflow_node(
            node.id,
            status="running",
            task_id=task.id,
            started_at=datetime.now(),
        )
        node.status = "running"
        node.task_id = task.id
        await self._emit_node_event(node, issue)
        if self._task_dispatcher is not None:
            # Best-effort: the dispatcher may be synchronous (test fakes) or
            # async (production task_runner). If it raises, surface the
            # failure on the node so the rest of the graph isn't stuck.
            try:
                result = self._task_dispatcher(task)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:  # noqa: BLE001
                logger.warning("Workflow dispatcher failed for node %s: %s", node.node_key, exc)
                await self.store.update_workflow_node(
                    node.id,
                    status="failed",
                    completed_at=datetime.now(),
                )

    def _read_latest_qa_failure_summary(
        self, workspace_path: str, issue_id: str
    ) -> str | None:
        """Return a short summary of the QA report on disk if it indicates a
        failure, formatted as actionable feedback for the engineer."""
        try:
            from pathlib import Path
            qa_plan_path = Path(workspace_path) / "issues" / issue_id / "qa" / "qa_plan.json"
            qa_report_path = Path(workspace_path) / "issues" / issue_id / "qa" / "qa_report.md"
            if not qa_plan_path.exists():
                return None
            plan = json.loads(qa_plan_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            logger.debug("Failed to read QA artifacts for rework feedback: %s", exc)
            return None

        status = plan.get("status", "unknown")
        if status not in {"failed", "needs_follow_up"}:
            # Engineer is being re-fired but QA didn't actually fail —
            # nothing useful to feed forward.
            return None

        bugs = plan.get("bugs_found") or []
        gaps = plan.get("test_gaps") or []
        risks = plan.get("risks") or []
        commands = plan.get("commands_run") or []
        recommendation = plan.get("final_recommendation") or ""

        def bullets(items):
            return [f"  - {x}" for x in items] if items else ["  (none reported)"]

        lines = [
            f"QA marked the previous engineer pass as **{status}**. You must address each item below before the next QA run.",
            "",
        ]
        if recommendation:
            lines.extend([f"Final recommendation: {recommendation}", ""])
        lines.append("Bugs found:")
        lines.extend(bullets(bugs))
        lines.extend(["", "Test gaps / framework notes:"])
        lines.extend(bullets(gaps))
        lines.extend(["", "Risks:"])
        lines.extend(bullets(risks))
        lines.extend(["", "Commands actually run by QA (with exit codes):"])
        lines.extend(bullets(commands))
        if qa_report_path.exists():
            lines.extend([
                "",
                f"Full QA report on disk: {qa_report_path.relative_to(workspace_path)}",
            ])
        return "\n".join(line for line in lines if line is not None)

    def _render_prompt_template(self, agent: Agent, issue: CodexIssue, node: WorkflowNode) -> str:
        """Render a system-prompt template with simple field substitution.

        Built-in agents store the marker `[builtin:<role>]`. For those we hand
        back a placeholder string — the runtime falls back to RoleWorkflowService
        for the actual prompt. Custom agents get real interpolation.
        """
        template = agent.system_prompt_template or ""
        if template.startswith("[builtin:"):
            return template  # runtime hook will substitute via RoleWorkflowService
        return (
            template
            .replace("{issue_title}", issue.title or "")
            .replace("{issue_description}", issue.description or "")
            .replace("{role_key}", agent.role_key)
            .replace("{node_key}", node.node_key)
        )

    async def _maybe_finalize(self, graph: WorkflowGraph) -> None:
        latest = await self.store.load_workflow_graph(graph.id)
        if latest is None:
            return
        statuses = {n.status for n in latest.nodes}
        previous_status = latest.status
        terminal_now = False
        new_issue_status: str | None = None
        if statuses and statuses <= {"done", "skipped"}:
            if latest.status != "done":
                latest.status = "done"
                await self.store.save_workflow_graph(latest)
                terminal_now = True
            new_issue_status = "completed"
        elif "failed" in statuses and not any(s in {"pending", "blocked", "ready", "running"} for s in statuses):
            if latest.status != "failed":
                latest.status = "failed"
                await self.store.save_workflow_graph(latest)
                terminal_now = True
            new_issue_status = "failed"

        # Sync the issue's top-level status with the graph terminal state so
        # the issue list chip flips from "排队中"/"运行中" to "完成"/"失败"
        # once all nodes settle. Without this, the issue stays at the last
        # transient status (e.g. "open" → 排队中) even though the work is done.
        if new_issue_status is not None:
            issue = await self.store.load_codex_issue(latest.issue_id)
            if issue is not None and issue.status != new_issue_status:
                # Never overwrite an in-flight human gate — those resolve via
                # explicit endpoints (approve-plan, qa-review), not the scheduler.
                # awaiting_merge is also a terminal-ish state the user moves out
                # of by clicking Merge Back.
                if issue.status not in {"awaiting_approval", "awaiting_review", "awaiting_merge"}:
                    issue.status = new_issue_status
                    issue.updated_at = datetime.now()
                    await self.store.save_codex_issue(issue)
                    if self._event_bus is not None:
                        try:
                            await self._event_bus.append({
                                "type": "issue_updated",
                                "issue_id": issue.id,
                                "session_id": issue.session_id,
                                "status": issue.status,
                            })
                        except Exception:  # noqa: BLE001
                            pass

        # Auto-advance the issue's `current_phase` when all nodes whose
        # agent role matches a known phase have completed. This keeps the
        # issue header's phase chip in sync with the DAG progress without
        # the UI having to know the role→phase mapping.
        await self._maybe_advance_phase(latest)

        # Sink lessons into the project's team_notes.md the FIRST time the
        # graph lands terminal. Best-effort — never blocks the graph.
        if terminal_now and previous_status not in {"done", "failed"}:
            await self._record_project_memory(latest)

    async def _record_project_memory(self, graph: WorkflowGraph) -> None:
        try:
            from app.application.project_memory_service import project_memory
            issue = await self.store.load_codex_issue(graph.issue_id)
            if issue is None:
                return
            project_repo_path = None
            if issue.project_id:
                load_project = getattr(self.store, "load_project", None)
                if callable(load_project):
                    proj = await load_project(issue.project_id)
                    if proj is not None:
                        project_repo_path = proj.repo_path
            project_memory.record_issue_completion(
                project_repo_path,
                issue_id=issue.id,
                issue_title=issue.title or issue.id,
                worktree_path=issue.git_worktree_path,
                graph_status=graph.status,
            )
            # Knowledge stack: rebuild team_notes_state for this project so
            # newly-appended blocks become visible in the Team Notes UI and
            # any orphaned state rows are pruned.
            try:
                from app.application.team_notes_service import team_notes
                if issue.project_id and project_repo_path:
                    md = team_notes.read_markdown(project_repo_path)
                    parsed = team_notes.parse_blocks(md)
                    state = await team_notes._load_state(self.store, issue.project_id)
                    parsed_ids = {b.block_id for b in parsed}
                    # Ensure every parsed block has a row (default: not deleted, not pinned)
                    for b in parsed:
                        if b.block_id not in state:
                            await team_notes._upsert_state(
                                self.store, issue.project_id, b.block_id,
                            )
                    # Drop state rows whose block no longer exists on disk
                    for stale_id in set(state.keys()) - parsed_ids:
                        try:
                            conn = await self.store._get_conn()
                            await conn.execute(
                                "DELETE FROM team_notes_state WHERE project_id = ? AND block_id = ?",
                                (issue.project_id, stale_id),
                            )
                            await conn.commit()
                        except Exception:  # noqa: BLE001
                            pass
            except Exception as exc:  # noqa: BLE001
                logger.debug("team_notes_state reconcile skipped: %s", exc)
            # S3c: auto-distill team_notes.md once it accumulates past
            # DISTILL_TRIGGER_BLOCKS raw issue entries. Reuses the
            # orchestrator LLM runner so we share the runtime catalog
            # config. Best-effort — distillation failures are silent.
            try:
                import os
                if os.getenv("WORKFLOW_ORCHESTRATOR_LLM", "").lower() != "false":
                    from app.application.llm_runner import build_llm_runner
                    from app.bootstrap import codex_store as _store  # local import to avoid cycles
                    catalog_service = None
                    try:
                        from app.bootstrap import (
                            get_runtime_catalog_service as _get_catalog_service,
                        )
                        catalog_service = _get_catalog_service()
                    except (ImportError, AttributeError):
                        # Older bootstrap shape — try the api layer's resolver.
                        try:
                            from app.interfaces.api import _get_runtime_catalog_service as _api_get
                            catalog_service = _api_get()
                        except Exception:  # noqa: BLE001
                            catalog_service = None
                    if catalog_service is not None:
                        runner = build_llm_runner(catalog_service)
                        await project_memory.maybe_distill(project_repo_path, runner)
            except Exception as exc:  # noqa: BLE001
                logger.debug("project memory distill skipped: %s", exc)
        except Exception as exc:  # noqa: BLE001
            logger.warning("project memory append failed for graph %s: %s", graph.id, exc)

    # Role → phase the issue advances *into* once every node of that role
    # completes successfully. E.g. once all `product_manager` nodes are done,
    # we transition the issue into the `architecture` phase.
    _ROLE_TO_NEXT_PHASE = {
        "product_manager": "architecture",
        "architect": "development",
        "engineer": "testing",
        "qa": "done",
    }

    async def _maybe_advance_phase(self, graph: WorkflowGraph) -> None:
        if graph is None:
            return
        issue = await self.store.load_codex_issue(graph.issue_id)
        if issue is None:
            return
        agents_by_id = {a.id: a for a in await self.store.list_agents(workspace_id=None)}
        # Group nodes by role.
        from collections import defaultdict
        statuses_by_role: dict[str, set[str]] = defaultdict(set)
        for node in graph.nodes:
            agent = agents_by_id.get(node.agent_id)
            role = (agent.role_key if agent else None) or node.node_key
            statuses_by_role[role].add(node.status)
        # Walk roles in the canonical order and pick the *latest* fully-
        # completed role's next phase as the target. This handles non-linear
        # DAGs (e.g. multiple architects) and ensures we only step forward.
        target_phase = None
        for role in ("product_manager", "architect", "engineer", "qa"):
            statuses = statuses_by_role.get(role)
            if statuses and statuses <= {"done", "skipped"}:
                target_phase = self._ROLE_TO_NEXT_PHASE.get(role)
        if target_phase is None or target_phase == issue.current_phase:
            return
        # Only step forward in the canonical phase order; never regress.
        order = ["requirements", "architecture", "development", "testing", "done"]
        try:
            cur_idx = order.index(issue.current_phase or "requirements")
            tgt_idx = order.index(target_phase)
        except ValueError:
            return
        if tgt_idx <= cur_idx:
            return
        issue.current_phase = target_phase
        issue.updated_at = datetime.now()
        await self.store.save_codex_issue(issue)
        if self._event_bus is not None:
            try:
                await self._event_bus.append({
                    "type": "issue_updated",
                    "issue_id": issue.id,
                    "session_id": issue.session_id,
                    "current_phase": issue.current_phase,
                })
            except Exception:  # noqa: BLE001
                pass


