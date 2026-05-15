"""Top-level "brain" that proposes a DAG for an issue.

This is the Orchestrator Meta-Agent from the plan. The MVP path (used in
tests / when LLM is unavailable) is a deterministic heuristic that inspects
the issue title/description and picks a subset of built-in agents. PR6 wires
a real LLM call through this same surface plus a replan() entry point.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Iterable

from app.domain.models import Agent, CodexIssue


# Stable canonical 4-phase preset, used as fallback when LLM is unavailable
# AND the heuristic can't classify the issue confidently.
_FULL_FOUR_PHASE_NODE_ORDER = ["product_manager", "architect", "engineer", "qa"]

# Heuristic intent classifier keyword sets. Order matters — first match wins.
_INTENT_KEYWORDS: list[tuple[str, list[str]]] = [
    ("docs_only", [
        "doc", "docs", "readme", "comment", "typo", "rename ",
        "文档", "注释", "拼写", "排版",
    ]),
    ("hotfix", [
        "hotfix", "hot fix", "regression", "production bug", "p0", "p1 ",
        "线上 bug", "紧急修复", "热修复",
    ]),
    ("bug", [
        "bug", "fix ", "fix:", "error", "crash", "broken",
        "修复", "修一下", "报错", "异常",
    ]),
    ("refactor", [
        "refactor", "cleanup", "rename", "restructure",
        "重构", "整理", "清理",
    ]),
    ("feature", [
        "feature", "feat:", "add ", "implement", "support",
        "新增", "新建", "实现", "支持",
    ]),
]


@dataclass
class _ProposedNode:
    node_key: str
    agent_id: str
    role_key: str
    title: str


@dataclass
class _ProposedEdge:
    from_node_key: str
    to_node_key: str
    edge_type: str = "sequence"


def _classify_intent(issue: CodexIssue) -> str:
    haystack = f"{issue.title or ''}\n{issue.description or ''}".lower()
    for intent, keywords in _INTENT_KEYWORDS:
        for kw in keywords:
            if kw in haystack:
                return intent
    return "feature"


def _agent_by_role(agents: Iterable[Agent], role_key: str) -> Agent | None:
    return next((a for a in agents if a.role_key == role_key), None)


def _node_order_for_intent(intent: str) -> list[str]:
    """Which built-in roles to invoke and in what order, before any custom agents."""
    if intent == "docs_only":
        # README/typo: PM optional but skip arch/QA entirely.
        return ["product_manager", "engineer"]
    if intent == "hotfix":
        # Hotfix: skip the full PRD/arch handshake and dive into engineer + QA.
        return ["engineer", "qa"]
    if intent == "bug":
        # Bug: needs engineer + QA verification, but architecture is usually fixed.
        return ["product_manager", "engineer", "qa"]
    if intent == "refactor":
        # Refactor: architect + engineer (no fresh PRD, no QA acceptance).
        return ["architect", "engineer"]
    # feature: full pipeline.
    return list(_FULL_FOUR_PHASE_NODE_ORDER)


def _build_proposal(
    intent: str,
    agents_by_role: dict[str, Agent],
) -> tuple[list[_ProposedNode], list[_ProposedEdge]]:
    order = _node_order_for_intent(intent)
    nodes: list[_ProposedNode] = []
    for role_key in order:
        agent = agents_by_role.get(role_key)
        if agent is None:
            # Skip silently when the registry doesn't have this builtin — the
            # caller can re-seed and retry.
            continue
        nodes.append(
            _ProposedNode(
                node_key=role_key,
                agent_id=agent.id,
                role_key=role_key,
                title=agent.name,
            )
        )
    edges: list[_ProposedEdge] = []
    for prev, curr in zip(nodes, nodes[1:]):
        edges.append(_ProposedEdge(from_node_key=prev.node_key, to_node_key=curr.node_key))
    return nodes, edges


def _serialize_dag(
    intent: str,
    nodes: list[_ProposedNode],
    edges: list[_ProposedEdge],
    rationale: str,
) -> dict:
    return {
        "meta": {
            "intent": intent,
            "rationale": rationale,
            "created_by": "orchestrator",
        },
        "nodes": [
            {
                "node_key": n.node_key,
                "agent_id": n.agent_id,
                "role_key": n.role_key,
                "title": n.title,
            }
            for n in nodes
        ],
        "edges": [
            {
                "from_node_key": e.from_node_key,
                "to_node_key": e.to_node_key,
                "edge_type": e.edge_type,
            }
            for e in edges
        ],
    }


def _topo_sort(nodes: list[dict], edges: list[dict]) -> list[str] | None:
    """Return a topological order of node_keys, or None if a cycle exists.

    Refine-loop edges are ignored — they are documented back-edges and don't
    block scheduling.
    """
    node_keys = [n["node_key"] for n in nodes]
    incoming: dict[str, set[str]] = {k: set() for k in node_keys}
    for e in edges:
        if e.get("edge_type") == "refine-loop":
            continue
        if e["to_node_key"] in incoming and e["from_node_key"] in node_keys:
            incoming[e["to_node_key"]].add(e["from_node_key"])
    order: list[str] = []
    pending = [k for k, deps in incoming.items() if not deps]
    while pending:
        k = pending.pop(0)
        order.append(k)
        for downstream, deps in incoming.items():
            if k in deps:
                deps.discard(k)
                if not deps and downstream not in order and downstream not in pending:
                    pending.append(downstream)
    if len(order) != len(node_keys):
        return None
    return order


def validate_dag(dag: dict, agent_ids: set[str]) -> None:
    """Raise ValueError if the DAG is structurally invalid."""
    if not isinstance(dag, dict):
        raise ValueError("DAG must be an object")
    nodes = dag.get("nodes") or []
    edges = dag.get("edges") or []
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise ValueError("nodes and edges must be arrays")
    if not nodes:
        raise ValueError("DAG must contain at least one node")
    keys: set[str] = set()
    for n in nodes:
        if not isinstance(n, dict):
            raise ValueError("each node must be an object")
        nk = n.get("node_key")
        if not isinstance(nk, str) or not nk:
            raise ValueError("node_key is required")
        if nk in keys:
            raise ValueError(f"duplicate node_key '{nk}'")
        keys.add(nk)
        if n.get("agent_id") not in agent_ids:
            raise ValueError(f"node '{nk}' references unknown agent_id '{n.get('agent_id')}'")
    for e in edges:
        if not isinstance(e, dict):
            raise ValueError("each edge must be an object")
        if e.get("from_node_key") not in keys or e.get("to_node_key") not in keys:
            raise ValueError(f"edge references unknown node_key: {e}")
    if _topo_sort(nodes, edges) is None:
        raise ValueError("DAG has a cycle (refine-loop back-edges are exempt; other cycles are not)")


class WorkflowOrchestrator:
    """Proposes (and later, replans) a DAG given an issue.

    The "brain" has two tiers:
      1. If a real LLM is reachable via the runtime catalog (and propose_graph
         is called with use_llm=True / env WORKFLOW_ORCHESTRATOR_LLM=true),
         we send a prompt and ask for a strict-JSON DAG.
      2. Otherwise (offline, tests, LLM error) we fall back to the deterministic
         keyword-based heuristic in this file.

    The heuristic is also the safety net: any LLM output that fails to parse
    or validate is silently swapped for a heuristic plan so callers always
    get a usable DAG.
    """

    def __init__(self, store=None, llm_runner=None) -> None:
        self.store = store
        self.llm_runner = llm_runner  # Optional callable(prompt) -> awaitable(str JSON)

    async def _list_available_agents(self) -> list[Agent]:
        if self.store is None:
            return []
        return await self.store.list_agents(workspace_id=None)

    async def propose_graph(
        self,
        issue: CodexIssue,
        agents: list[Agent] | None = None,
        *,
        use_llm: bool | None = None,
    ) -> dict:
        if agents is None:
            agents = await self._list_available_agents()
        if not agents:
            raise ValueError("no agents available — built-in agents may not be seeded")

        # 1. Try the LLM path when wired/enabled.
        import os
        should_llm = use_llm if use_llm is not None else os.getenv("WORKFLOW_ORCHESTRATOR_LLM", "").lower() == "true"
        if should_llm and self.llm_runner is not None:
            try:
                dag = await self._llm_propose(issue, agents)
                if dag is not None:
                    return dag
            except Exception as exc:  # noqa: BLE001
                # Any LLM failure → fall through to heuristic.
                import logging
                logging.getLogger(__name__).warning("LLM orchestrator failed, using heuristic: %s", exc)

        # 2. Heuristic fallback.
        return self._heuristic_propose(issue, agents)

    def _heuristic_propose(self, issue: CodexIssue, agents: list[Agent]) -> dict:
        agents_by_role = {a.role_key: a for a in agents}
        intent = _classify_intent(issue)
        nodes, edges = _build_proposal(intent, agents_by_role)
        if not nodes:
            raise ValueError("no agents matched the heuristic — registry may be missing builtins")
        rationale = _rationale_for_intent(intent, [n.role_key for n in nodes])
        dag = _serialize_dag(intent, nodes, edges, rationale)
        validate_dag(dag, {a.id for a in agents})
        return dag

    async def _llm_propose(self, issue: CodexIssue, agents: list[Agent]) -> dict | None:
        """Ask an LLM to propose a DAG. Returns None if output can't be parsed
        or validated (caller falls back to heuristic)."""
        prompt = _build_llm_prompt(issue, agents)
        raw = await self.llm_runner(prompt)
        if not raw:
            return None
        # Tolerate leading/trailing prose and markdown code fences.
        import re
        m = re.search(r"\{(?:[^{}]|(?:\{[^{}]*\}))*\}", raw, re.DOTALL)
        if not m:
            return None
        try:
            dag = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
        # Normalize: ensure meta + edge_type defaults exist.
        dag.setdefault("meta", {})
        dag["meta"].setdefault("created_by", "orchestrator_llm")
        for e in dag.get("edges", []):
            e.setdefault("edge_type", "sequence")
        try:
            validate_dag(dag, {a.id for a in agents})
        except ValueError:
            return None
        return dag

    async def replan(
        self,
        graph,
        completed_node,
        trigger_reason: str,
        agents: list[Agent] | None = None,
    ) -> dict:
        """Hybrid-brain replanner.

        PR6 heuristic version: looks at the completed node's role and the
        full issue context to decide whether to suggest adding/removing nodes.
        Real LLM dispatch can replace this body without changing the surface.

        Returns a diff:
            {
                "added_nodes": [...],
                "removed_node_keys": [...],
                "added_edges": [...],
                "removed_edge_ids": [...],
                "rationale": str
            }
        Guarantees `removed_node_keys` never contains a `done` node.
        """
        if agents is None:
            agents = await self._list_available_agents()
        agents_by_role = {a.role_key: a for a in agents}
        done_keys = {n.node_key for n in graph.nodes if n.status == "done"}
        added_nodes: list[dict] = []
        added_edges: list[dict] = []
        removed_node_keys: list[str] = []
        rationale_parts: list[str] = []

        if completed_node.node_key == "product_manager" and trigger_reason == "node_done":
            # After PRD lands, the orchestrator considers whether the work
            # is heavier than initially scoped — heuristic: if there's no
            # architect node downstream yet, propose inserting one when the
            # graph already has engineer (i.e., we previously assumed bug/docs).
            has_arch = any(n.node_key == "architect" for n in graph.nodes)
            has_eng = any(n.node_key == "engineer" for n in graph.nodes)
            if not has_arch and has_eng and "architect" in agents_by_role:
                arch_agent = agents_by_role["architect"]
                added_nodes.append({
                    "node_key": "architect",
                    "agent_id": arch_agent.id,
                    "role_key": "architect",
                    "title": arch_agent.name,
                })
                added_edges.append({
                    "from_node_key": "product_manager",
                    "to_node_key": "architect",
                    "edge_type": "sequence",
                })
                added_edges.append({
                    "from_node_key": "architect",
                    "to_node_key": "engineer",
                    "edge_type": "sequence",
                })
                rationale_parts.append("PM produced a PRD that looks system-level; inserting architect.")
        elif completed_node.node_key == "architect" and trigger_reason == "node_done":
            # Heuristic: many architectures benefit from a security pass alongside QA.
            # Only suggest if a security_reviewer agent is registered and not already in the graph.
            existing_keys = {n.node_key for n in graph.nodes}
            if "security_reviewer" in agents_by_role and "security_reviewer" not in existing_keys:
                sec_agent = agents_by_role["security_reviewer"]
                added_nodes.append({
                    "node_key": "security_reviewer",
                    "agent_id": sec_agent.id,
                    "role_key": "security_reviewer",
                    "title": sec_agent.name,
                })
                added_edges.append({
                    "from_node_key": "engineer",
                    "to_node_key": "security_reviewer",
                    "edge_type": "parallel-fanout",
                })
                rationale_parts.append("Architecture changes detected; suggesting a parallel security review.")
        elif completed_node.node_key == "qa" and trigger_reason == "node_failed":
            # QA failed — propose a refine-loop edge back to engineer.
            already_loop = any(
                e.edge_type == "refine-loop"
                and e.from_node_key == "qa"
                and e.to_node_key == "engineer"
                for e in graph.edges
            )
            if not already_loop and any(n.node_key == "engineer" for n in graph.nodes):
                added_edges.append({
                    "from_node_key": "qa",
                    "to_node_key": "engineer",
                    "edge_type": "refine-loop",
                    "condition_expr": None,
                })
                rationale_parts.append("QA failed; adding a refine-loop edge back to engineer for rework.")

        # Safety: never propose removing a node that has already completed.
        removed_node_keys = [k for k in removed_node_keys if k not in done_keys]

        return {
            "added_nodes": added_nodes,
            "added_edges": added_edges,
            "removed_node_keys": removed_node_keys,
            "removed_edge_ids": [],
            "rationale": " ".join(rationale_parts) or "No structural changes needed.",
            "has_changes": bool(added_nodes or added_edges or removed_node_keys),
        }


_RATIONALES = {
    "docs_only": "Heuristic: docs/typo edit — skip architecture and QA, only PM scoping + engineer.",
    "hotfix": "Heuristic: hotfix/regression — skip PRD + architecture, jump to engineer + QA.",
    "bug": "Heuristic: bug fix — PM clarifies repro, engineer fixes, QA validates.",
    "refactor": "Heuristic: refactor — architect drafts approach, engineer implements; QA optional.",
    "feature": "Heuristic: new feature — full PM → architect → engineer → QA pipeline.",
}


def _rationale_for_intent(intent: str, role_keys: list[str]) -> str:
    base = _RATIONALES.get(intent, _RATIONALES["feature"])
    return f"{base} Selected agents: {', '.join(role_keys)}."


def _build_llm_prompt(issue: CodexIssue, agents: list[Agent]) -> str:
    """Render the system+user prompt used to ask an LLM for a DAG."""
    agent_lines = []
    for a in agents:
        agent_lines.append(
            f"- id={a.id} role_key={a.role_key} name={a.name}"
            + (f" description={a.description}" if a.description else "")
        )
    catalog = "\n".join(agent_lines) if agent_lines else "(no agents available)"
    return (
        "You are a software workflow orchestrator. Given an issue and a list of available agents, "
        "produce a DAG describing which agents should run and in what order. Output STRICT JSON only.\n\n"
        "Schema:\n"
        "{\n"
        '  "meta": { "intent": str, "rationale": str },\n'
        '  "nodes": [ { "node_key": str, "agent_id": str, "role_key": str, "title": str } ],\n'
        '  "edges": [ { "from_node_key": str, "to_node_key": str, "edge_type": "sequence"|"parallel-fanout"|"refine-loop"|"conditional" } ]\n'
        "}\n\n"
        "Rules:\n"
        " - Use only agent_id values from the catalog below.\n"
        " - node_key should equal role_key when possible.\n"
        " - Reject cycles except for refine-loop edges (which are explicitly back-edges).\n"
        " - Skip unnecessary nodes for trivial issues (typos, docs-only, hotfixes).\n\n"
        f"Issue title: {issue.title or ''}\n"
        f"Issue description: {issue.description or ''}\n\n"
        f"Available agents:\n{catalog}\n\n"
        "Return ONLY the JSON object, no commentary."
    )


# Re-exports for tests
__all__ = ["WorkflowOrchestrator", "validate_dag"]
