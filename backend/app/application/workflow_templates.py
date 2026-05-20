"""Workflow templates — pre-baked DAG skeletons users can pick when
creating an issue, instead of always letting the orchestrator LLM decide.

Each template specifies a name, description, intent rationale, and a list
of `role_key` slots in dispatch order. At materialization time we resolve
each role_key against the built-in Agent table to populate `agent_id`,
then hand the result to `materialize_graph_from_dag`.

Adding a new template is a single dict — no DB changes needed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence


@dataclass(frozen=True)
class WorkflowTemplate:
    id: str
    name: str
    description: str
    intent: str
    # Roles in dispatch order. Adjacent roles get a sequence edge between them.
    role_order: tuple[str, ...]
    # Per-role title override; falls back to agent.name when missing.
    titles: dict[str, str] = field(default_factory=dict)
    # Phase 1 — non-linear shapes. Each entry is a (from_role, to_role)
    # pair the materializer should turn into a parallel-fanout edge that
    # *overrides* the default sequence chain. Used by `feature_parallel`
    # to fork engineer into engineer_frontend + engineer_backend and then
    # join back to QA.
    #   parallel_edges = (("architect", "engineer_frontend"),
    #                     ("architect", "engineer_backend"),
    #                     ("engineer_frontend", "qa"),
    #                     ("engineer_backend", "qa"))
    # When set, default `prev → curr` sequence edges are skipped for any
    # adjacency already covered by an explicit edge here.
    parallel_edges: tuple[tuple[str, str], ...] = ()


TEMPLATES: tuple[WorkflowTemplate, ...] = (
    WorkflowTemplate(
        id="feature",
        name="New feature",
        description="Full 4-stage pipeline: PRD → design → implement → QA",
        intent="feature",
        role_order=("product_manager", "architect", "engineer", "qa"),
        titles={
            "product_manager": "Draft PRD",
            "architect": "Design system",
            "engineer": "Implement",
            "qa": "Verify",
        },
    ),
    WorkflowTemplate(
        id="bugfix",
        name="Bug fix",
        description="Skip heavy PRD/design — PM clarifies repro, Engineer fixes, QA validates",
        intent="bug",
        role_order=("product_manager", "engineer", "qa"),
        titles={
            "product_manager": "Capture bug repro",
            "engineer": "Fix bug",
            "qa": "Regression verify",
        },
    ),
    WorkflowTemplate(
        id="hotfix",
        name="Hotfix",
        description="Production-down emergency: jump straight to Engineer + QA",
        intent="hotfix",
        role_order=("engineer", "qa"),
        titles={
            "engineer": "Hotfix patch",
            "qa": "Smoke verify",
        },
    ),
    WorkflowTemplate(
        id="refactor",
        name="Refactor",
        description="Architect drafts approach, Engineer implements — no fresh PRD",
        intent="refactor",
        role_order=("architect", "engineer"),
        titles={
            "architect": "Refactor strategy",
            "engineer": "Apply refactor",
        },
    ),
    WorkflowTemplate(
        id="docs",
        name="Docs / cleanup",
        description="README/typo/comment work — Engineer alone, no architecture",
        intent="docs_only",
        role_order=("engineer",),
        titles={
            "engineer": "Docs update",
        },
    ),
    WorkflowTemplate(
        id="feature_parallel",
        name="Feature (parallel FE+BE)",
        description=(
            "Like 'New feature' but Engineer is split into Frontend + Backend "
            "specialists running in parallel after Architect. QA joins both."
        ),
        intent="feature",
        role_order=(
            "product_manager",
            "architect",
            "engineer_frontend",
            "engineer_backend",
            "qa",
        ),
        titles={
            "product_manager": "Draft PRD",
            "architect": "Design system",
            "engineer_frontend": "Frontend implementation",
            "engineer_backend": "Backend implementation",
            "qa": "Verify",
        },
        # Override the default sequence chain to fork after architect and
        # join back at QA. The chain edges that would otherwise be added
        # for the same adjacencies are skipped by template_to_dag.
        parallel_edges=(
            ("architect", "engineer_frontend"),
            ("architect", "engineer_backend"),
            ("engineer_frontend", "qa"),
            ("engineer_backend", "qa"),
        ),
    ),
)


def list_template_summaries() -> list[dict]:
    """Cheap representation for the UI dropdown — no agent resolution."""
    return [
        {
            "id": t.id,
            "name": t.name,
            "description": t.description,
            "intent": t.intent,
            "role_order": list(t.role_order),
        }
        for t in TEMPLATES
    ]


def get_template(template_id: str) -> WorkflowTemplate | None:
    for t in TEMPLATES:
        if t.id == template_id:
            return t
    return None


def template_to_dag(template: WorkflowTemplate, agents: Sequence) -> dict | None:
    """Materialize a template into a DAG dict suitable for
    materialize_graph_from_dag. Returns None if any required role isn't
    registered as an agent.
    """
    agents_by_role = {a.role_key: a for a in agents}
    nodes = []
    for role_key in template.role_order:
        agent = agents_by_role.get(role_key)
        if agent is None:
            return None
        nodes.append({
            "node_key": role_key,
            "agent_id": agent.id,
            "role_key": role_key,
            "title": template.titles.get(role_key) or agent.name,
        })
    # Build explicit parallel-fanout edges first so we can skip default
    # sequence edges that cover the same adjacencies (avoids duplicate edges
    # between the same pair).
    explicit = {
        (a, b): {
            "from_node_key": a,
            "to_node_key": b,
            "edge_type": "parallel-fanout",
        }
        for a, b in template.parallel_edges
    }
    node_keys = {n["node_key"] for n in nodes}
    explicit_edges = [
        e for (a, b), e in explicit.items()
        if a in node_keys and b in node_keys
    ]
    # If a node has an explicit incoming edge, drop its default sequence
    # edge from the prior role_order entry — the explicit fan-out replaces
    # the linear adjacency.
    explicit_incoming = {e["to_node_key"] for e in explicit_edges}
    sequence_edges = [
        {
            "from_node_key": prev["node_key"],
            "to_node_key": curr["node_key"],
            "edge_type": "sequence",
        }
        for prev, curr in zip(nodes, nodes[1:])
        if curr["node_key"] not in explicit_incoming
    ]
    edges = sequence_edges + explicit_edges
    return {
        "meta": {
            "intent": template.intent,
            "rationale": f"Materialized from template '{template.id}': {template.description}",
            "created_by": f"template:{template.id}",
        },
        "nodes": nodes,
        "edges": edges,
    }
