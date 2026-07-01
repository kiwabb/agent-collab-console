from pathlib import Path  # noqa: I001

from app.application.agent_catalog.catalog import AgentCatalog
from app.application.agent_catalog.generic_specialist_workflow import GenericSpecialistWorkflow
from app.application.role_workflow_service import RoleWorkflowService
from app.application.subagent_result_builder import build_subagent_result
from app.application.agent_seed import seed_builtin_agents
from app.adapters.async_sqlite_store import AsyncSQLiteStore
from app.domain.models import Agent, CodexTask  # noqa: F401


def test_catalog_loads_predefined_specialists():
    catalog = AgentCatalog()

    agents = catalog.list_available_agents()
    role_keys = {agent.role_key for agent in agents}

    assert len(agents) == 10
    assert "security_reviewer" in role_keys
    assert "performance_reviewer" in role_keys
    assert catalog.resolve_agent("specialist:security_reviewer").role_key == "security_reviewer"


def test_catalog_registers_custom_agent():
    catalog = AgentCatalog()

    custom = catalog.register_custom(
        name="diagram_drawer",
        prompt="Draw architecture diagrams",
        schema={"type": "object", "properties": {"diagram": {"type": "string"}}},
    )

    assert custom.role_key == "custom:diagram_drawer"
    assert custom.agent_tier == "custom"
    assert (
        catalog.resolve_agent("custom:diagram_drawer").prompt_template
        == "Draw architecture diagrams"
    )


def test_seed_builtin_agents_adds_specialists_with_tier(tmp_path: Path):
    async def run():
        store = AsyncSQLiteStore(tmp_path / "console.db")
        created = await seed_builtin_agents(store)
        agents = await store.list_agents(workspace_id=None)
        await store.close()

        return created, agents

    import asyncio

    created, agents = asyncio.run(run())
    by_role = {agent.role_key: agent for agent in agents}

    assert created >= 10
    assert by_role["product_manager"].agent_tier == "managed"
    assert by_role["specialist:security_reviewer"].agent_tier == "specialist"
    assert by_role["specialist:security_reviewer"].default_executor == "claude"
    assert by_role["specialist:security_reviewer"].persist_kind == "specialist"


def test_generic_specialist_workflow_persists_json_artifact(tmp_path: Path):
    catalog = AgentCatalog()
    workflow = GenericSpecialistWorkflow(catalog)
    task = CodexTask(
        id="task-sec",
        session_id="session-1",
        issue_id="issue-1",
        title="Auth hardening",
        prompt="Review auth",
        role="specialist:security_reviewer",
        status="done",
        result='{"summary":"Looks safe","findings":[{"severity":"low","title":"Add rate limits"}]}',
        workspace_path=str(tmp_path),
    )

    doc = workflow.persist_result(task)

    expected = (
        tmp_path / "issues" / "issue-1" / "specialists" / "security_reviewer" / "task-sec.json"
    )
    assert expected.exists()
    assert doc.role_key == "security_reviewer"
    assert doc.artifact["summary"] == "Looks safe"
    assert doc.written_files == [
        {
            "name": "specialists/security_reviewer/task-sec.json",
            "path": str(expected),
            "kind": "specialist",
        }
    ]
    assert "Specialist security_reviewer report generated" in task.result


def test_role_workflow_service_routes_specialist_result(tmp_path: Path):
    async def run():
        task = CodexTask(
            id="task-role-sec",
            session_id="session-1",
            issue_id="issue-1",
            title="Auth hardening",
            prompt="Review auth",
            role="specialist:security_reviewer",
            status="done",
            result='{"summary":"Review complete"}',
            workspace_path=str(tmp_path),
        )

        doc = await RoleWorkflowService().persist_result(task)
        return task, doc

    import asyncio

    task, doc = asyncio.run(run())

    assert doc.role_key == "security_reviewer"
    assert (
        tmp_path / "issues" / "issue-1" / "specialists" / "security_reviewer" / "task-role-sec.json"
    ).exists()
    assert task.result.startswith("Specialist security_reviewer report generated")


def test_generic_specialist_workflow_persists_custom_agent_artifact(tmp_path: Path):
    workflow = GenericSpecialistWorkflow()
    task = CodexTask(
        id="task-custom",
        session_id="session-1",
        issue_id="issue-1",
        title="Draw diagram",
        prompt="Draw architecture",
        role="custom:diagram_drawer",
        status="done",
        result='{"summary":"Diagram drafted","diagram":"A -> B"}',
        workspace_path=str(tmp_path),
    )

    doc = workflow.persist_result(task)

    expected = (
        tmp_path
        / "issues"
        / "issue-1"
        / "specialists"
        / "custom:diagram_drawer"
        / "task-custom.json"
    )
    assert expected.exists()
    assert doc.role_key == "custom:diagram_drawer"
    assert doc.artifact["diagram"] == "A -> B"


def test_role_workflow_service_treats_specialists_as_prompt_managed():
    service = RoleWorkflowService()

    assert service.is_managed_role("specialist:security_reviewer") is True
    assert service.is_managed_role("custom:diagram_drawer") is True


def test_subagent_result_builder_preserves_specialist_artifact(tmp_path: Path):
    workflow = GenericSpecialistWorkflow(AgentCatalog())
    task = CodexTask(
        id="task-sec-envelope",
        session_id="session-1",
        issue_id="issue-1",
        title="Auth hardening",
        prompt="Review auth",
        role="specialist:security_reviewer",
        status="done",
        result='{"summary":"Specialist says ok"}',
        workspace_path=str(tmp_path),
    )
    doc = workflow.persist_result(task)
    node = __import__("app.domain.models", fromlist=["WorkflowNode"]).WorkflowNode(
        id="node-sec",
        graph_id="graph-1",
        node_key="security_reviewer",
        agent_id="agent-sec",
    )

    result = build_subagent_result(task=task, node=node, doc=doc)

    assert result.artifact_json["artifact"]["summary"] == "Specialist says ok"
    assert result.artifact_paths == [
        str(
            tmp_path
            / "issues"
            / "issue-1"
            / "specialists"
            / "security_reviewer"
            / "task-sec-envelope.json"
        )
    ]
