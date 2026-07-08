from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from app.domain.models import Agent, CodexIssue

_VALID_EDGE_TYPES = {
    "sequence",
    "parallel-fanout",
    "refine-loop",
    "retry-on-fail",
    "conditional",
    "critique-loop",
}


class WorkflowOrchestratorStore(Protocol):
    async def list_agents(
        self,
        workspace_id: str | None = None,
        role_key: str | None = None,
    ) -> list[Agent]: ...


def _mapping_list(value: object, *, field: str) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        raise ValueError(f"dag.{field} must be a list")
    items: list[Mapping[str, object]] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise ValueError(f"dag.{field}[{index}] must be an object")
        items.append(item)
    return items


def validate_dag(dag: Mapping[str, object], allowed_agent_ids: set[str]) -> None:
    nodes = _mapping_list(dag.get("nodes"), field="nodes")
    edges = _mapping_list(dag.get("edges", []), field="edges")
    if not nodes:
        raise ValueError("dag.nodes must contain at least one node")

    node_keys: set[str] = set()
    for index, node in enumerate(nodes):
        node_key = node.get("node_key")
        agent_id = node.get("agent_id")
        if not isinstance(node_key, str) or not node_key.strip():
            raise ValueError(f"dag.nodes[{index}].node_key is required")
        if node_key in node_keys:
            raise ValueError(f"duplicate node_key: {node_key}")
        node_keys.add(node_key)
        if not isinstance(agent_id, str) or agent_id not in allowed_agent_ids:
            raise ValueError(f"dag.nodes[{index}].agent_id is unknown")

    outgoing: dict[str, list[str]] = {node_key: [] for node_key in node_keys}
    for index, edge in enumerate(edges):
        from_node_key = edge.get("from_node_key")
        to_node_key = edge.get("to_node_key")
        edge_type = edge.get("edge_type", "sequence")
        if not isinstance(from_node_key, str) or from_node_key not in node_keys:
            raise ValueError(f"dag.edges[{index}].from_node_key is unknown")
        if not isinstance(to_node_key, str) or to_node_key not in node_keys:
            raise ValueError(f"dag.edges[{index}].to_node_key is unknown")
        if from_node_key == to_node_key:
            raise ValueError(f"dag.edges[{index}] cannot point a node to itself")
        if not isinstance(edge_type, str) or edge_type not in _VALID_EDGE_TYPES:
            raise ValueError(f"dag.edges[{index}].edge_type is invalid")
        outgoing[from_node_key].append(to_node_key)

    visited: set[str] = set()
    active: set[str] = set()

    def visit(node_key: str) -> None:
        if node_key in active:
            raise ValueError("dag contains a cycle")
        if node_key in visited:
            return
        active.add(node_key)
        for child in outgoing[node_key]:
            visit(child)
        active.remove(node_key)
        visited.add(node_key)

    for node_key in node_keys:
        visit(node_key)


class WorkflowOrchestrator:
    def __init__(self, store: WorkflowOrchestratorStore, llm_runner: object | None = None) -> None:
        self.store = store
        self.llm_runner = llm_runner

    async def propose_graph(self, issue: CodexIssue, *, use_llm: bool = True) -> dict[str, object]:
        agents = await self.store.list_agents(workspace_id=None)
        by_role = {agent.role_key: agent for agent in agents}
        role_order = ["product_manager", "architect", "engineer", "qa"]
        selected = [by_role[role] for role in role_order if role in by_role]
        if not selected:
            selected = agents[:1]
        if not selected:
            raise ValueError("No agents are available to build a workflow graph")

        nodes = [
            {
                "node_key": agent.role_key,
                "agent_id": agent.id,
                "title": agent.name,
            }
            for agent in selected
        ]
        edges = [
            {
                "from_node_key": selected[index].role_key,
                "to_node_key": selected[index + 1].role_key,
                "edge_type": "sequence",
            }
            for index in range(len(selected) - 1)
        ]
        return {
            "nodes": nodes,
            "edges": edges,
            "meta": {
                "issue_id": issue.id,
                "strategy": "llm_requested" if use_llm and self.llm_runner is not None else "heuristic",
            },
        }
