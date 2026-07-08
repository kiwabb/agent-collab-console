"""Seed built-in agents into the database.

PR1 keeps execution semantics unchanged: built-in agents store a marker
template (`[builtin:<role_key>]`). The runtime continues to dispatch via
RoleWorkflowService for these roles. Later PRs will read the template
directly when the WORKFLOW_DAG_ENABLED flag flips on.
"""

from __future__ import annotations  # noqa: I001

from datetime import datetime
from typing import Protocol
from uuid import uuid4

from app.application.agent_catalog.catalog import AgentCatalog, SPECIALIST_PREFIX
from app.domain.models import Agent


class AgentSeedStore(Protocol):
    async def list_agents(self, *, workspace_id: str | None = None) -> list[Agent]: ...

    async def save_agent(self, agent: Agent) -> None: ...


# (role_key, name, description, artifact_subdir, persist_kind,
#  triggers_replan_on_done, triggers_replan_on_fail)
_BUILTIN_SPECS: list[tuple[str, str, str, str, str, bool, bool]] = [
    (
        "product_manager",
        "Product Manager",
        "Drafts the PRD / requirements document for an issue.",
        "pm",
        "product_manager",
        True,  # replan after PM done — requirements may shift the rest of the graph
        False,
    ),
    (
        "architect",
        "Architect",
        "Designs system architecture and produces the implementation plan.",
        "architect",
        "architect",
        True,  # replan after architect done — may surface need for security/perf reviewers
        False,
    ),
    (
        "engineer",
        "Engineer",
        "Implements one slice of the architect's plan.",
        "engineer",
        "engineer",
        False,  # engineer completing does not normally reshape the DAG
        False,
    ),
    # Phase 1 — parallel engineer specialists. Same prompt template +
    # persist_kind as `engineer`; the role_key only changes how the
    # scheduler routes work and which artifact subdir is used so two
    # specialists can run in parallel without overwriting each other.
    (
        "engineer_frontend",
        "Frontend Engineer",
        "Implements the frontend slice (UI / client code) of the plan.",
        "engineer_frontend",
        "engineer",
        False,
        False,
    ),
    (
        "engineer_backend",
        "Backend Engineer",
        "Implements the backend slice (API / server code) of the plan.",
        "engineer_backend",
        "engineer",
        False,
        False,
    ),
    (
        "qa",
        "QA",
        "Validates the implementation against the PRD and architect's plan.",
        "qa",
        "qa",
        False,
        True,  # QA failed → replan can decide whether to loop back to engineer or architect
    ),
    (
        "operations_engineer",
        "Operations Engineer",
        "Performs setup and startup validation for local project scripts.",
        "operations_engineer",
        "operations",
        False,
        False,
    ),
]


async def seed_builtin_agents(store: AgentSeedStore | None) -> int:
    """Ensure built-in agents exist. Returns count of newly created."""
    if store is None:
        return 0
    existing = {a.role_key for a in await store.list_agents(workspace_id=None)}
    created = 0
    now = datetime.now()
    for role_key, name, description, subdir, persist_kind, on_done, on_fail in _BUILTIN_SPECS:
        if role_key in existing:
            continue
        agent = Agent(
            id=str(uuid4()),
            workspace_id=None,
            name=name,
            role_key=role_key,
            description=description,
            system_prompt_template=f"[builtin:{role_key}]",
            input_schema=[],
            output_schema={},
            artifact_subdir=subdir,
            persist_kind=persist_kind,
            agent_tier="managed",
            triggers_replan_on_done=on_done,
            triggers_replan_on_fail=on_fail,
            is_builtin=True,
            created_at=now,
            updated_at=now,
        )
        await store.save_agent(agent)
        created += 1
    catalog = AgentCatalog()
    existing = {a.role_key for a in await store.list_agents(workspace_id=None)}
    for definition in catalog.list_available_agents():
        role_key = f"{SPECIALIST_PREFIX}{definition.role_key}"
        if role_key in existing:
            continue
        agent = Agent(
            id=str(uuid4()),
            workspace_id=None,
            name=definition.display_name,
            role_key=role_key,
            description=definition.prompt_template,
            system_prompt_template=f"[specialist:{definition.role_key}]",
            input_schema=[],
            output_schema=definition.output_schema,
            default_executor="claude",
            artifact_subdir=f"specialists/{definition.role_key}",
            persist_kind="specialist",
            agent_tier="specialist",
            is_builtin=True,
            created_at=now,
            updated_at=now,
        )
        await store.save_agent(agent)
        created += 1
    return created
