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
    # Use refine-loop edges separately via `extra_edges` for cycles.
    role_order: tuple[str, ...]
    # Per-role title override; falls back to agent.name when missing.
    titles: dict[str, str] = field(default_factory=dict)


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
    edges = [
        {
            "from_node_key": prev["node_key"],
            "to_node_key": curr["node_key"],
            "edge_type": "sequence",
        }
        for prev, curr in zip(nodes, nodes[1:])
    ]
    return {
        "meta": {
            "intent": template.intent,
            "rationale": f"Materialized from template '{template.id}': {template.description}",
            "created_by": f"template:{template.id}",
        },
        "nodes": nodes,
        "edges": edges,
    }
