from datetime import datetime, timedelta
from pathlib import Path

from app.application.subagent_result_builder import build_subagent_result
from app.application.workflow_scheduler import WorkflowScheduler
from app.adapters.async_sqlite_store import AsyncSQLiteStore
from app.adapters.sqlite_store import SQLiteStore
from app.domain.models import Agent, CodexIssue, CodexTask, WorkflowGraph, WorkflowNode


class FakeDoc:
    issue_title = "Add export"
    clarification_question = None
    written_files: list[dict]

    def __init__(self, written_files: list[dict]) -> None:
        self.written_files = written_files

    def model_dump(self) -> dict:
        return {
            "issue_title": self.issue_title,
            "product_goals": ["Export reports"],
            "acceptance_criteria": ["CSV can be downloaded"],
        }


class FakeEngineerDoc:
    changed_files = ["backend/app.py", "frontend/App.tsx"]
    verification_commands = ["pytest"]
    clarification_question = None
    architect_critique = "API contract is missing error responses"
    written_files: list[dict] = []

    def model_dump(self) -> dict:
        return {
            "status": "partial",
            "summary": "Implemented API shell",
            "changed_files": self.changed_files,
        }


class FakeQADoc:
    clarification_question = "Should QA run browser tests too?"
    written_files: list[dict] = []

    def __init__(self) -> None:
        self.execution_results = [
            {"command": "pytest", "exit_code": 0, "duration_s": 1.2},
        ]

    def model_dump(self) -> dict:
        return {
            "status": "passed",
            "commands_run": ["pytest"],
            "bugs_found": [],
        }


class FakeArchitectDoc:
    clarification_question = None
    written_files: list[dict] = []

    def model_dump(self) -> dict:
        return {
            "architecture_summary": "Use a service boundary",
            "development_task_list": ["Build API"],
        }


def _task(role: str, *, task_id: str = "task-x") -> CodexTask:
    return CodexTask(
        id=task_id,
        session_id="session-1",
        issue_id="issue-1",
        title="Issue",
        prompt="Do work",
        role=role,
        status="done",
        result="summary",
    )


def _node(node_key: str) -> WorkflowNode:
    return WorkflowNode(
        id=f"node-{node_key}",
        graph_id="graph-1",
        node_key=node_key,
        agent_id=f"agent-{node_key}",
    )


def test_build_subagent_result_preserves_pm_structured_artifact(tmp_path: Path):
    artifact_path = tmp_path / "issues" / "issue-1" / "pm" / "prd.json"
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text('{"issue_title":"Add export","product_goals":["Export reports"]}', encoding="utf-8")
    markdown_path = artifact_path.with_suffix(".md")
    markdown_path.write_text("# PRD\n\nExport reports", encoding="utf-8")

    task = CodexTask(
        id="task-1",
        session_id="session-1",
        issue_id="issue-1",
        title="Add export",
        prompt="Build CSV export",
        role="product_manager",
        status="done",
        result="PRD generated for Add export.",
        review_comment="human approval",
        created_at=datetime(2026, 1, 1, 12, 0, 0),
        updated_at=datetime(2026, 1, 1, 12, 0, 4),
    )
    node = WorkflowNode(
        id="node-id",
        graph_id="graph-1",
        node_key="pm",
        agent_id="agent-pm",
        retries=1,
        max_retries=3,
    )
    doc = FakeDoc([
        {"name": "pm/prd.json", "path": str(artifact_path), "kind": "product"},
        {"name": "pm/prd.md", "path": str(markdown_path), "kind": "product"},
    ])

    result = build_subagent_result(task=task, node=node, doc=doc)

    assert result.task_id == "task-1"
    assert result.node_key == "pm"
    assert result.role == "product_manager"
    assert result.agent_id == "agent-pm"
    assert result.status == "done"
    assert result.summary == "PRD generated for Add export."
    assert result.artifact_json == {
        "issue_title": "Add export",
        "product_goals": ["Export reports"],
        "acceptance_criteria": ["CSV can be downloaded"],
    }
    assert result.artifact_markdown == "# PRD\n\nExport reports"
    assert result.artifact_paths == [str(artifact_path), str(markdown_path)]
    assert result.duration_s == 4.0
    assert result.retry_count == 1
    assert result.max_retries == 3
    assert result.review_comment_in == "human approval"


def test_build_subagent_result_preserves_architect_artifact_json():
    result = build_subagent_result(
        task=_task("architect"),
        node=_node("architect"),
        doc=FakeArchitectDoc(),
    )

    assert result.artifact_json == {
        "architecture_summary": "Use a service boundary",
        "development_task_list": ["Build API"],
    }


def test_build_subagent_result_preserves_engineer_files_and_critique():
    result = build_subagent_result(
        task=_task("engineer"),
        node=_node("engineer"),
        doc=FakeEngineerDoc(),
    )

    assert result.files_changed == ["backend/app.py", "frontend/App.tsx"]
    assert result.critique == {
        "architect_critique": "API contract is missing error responses",
    }


def test_build_subagent_result_preserves_qa_commands_and_clarification():
    result = build_subagent_result(
        task=_task("qa"),
        node=_node("qa"),
        doc=FakeQADoc(),
    )

    assert result.qa_commands == [
        {"command": "pytest", "exit_code": 0, "duration_s": 1.2},
    ]
    assert result.clarification_question == "Should QA run browser tests too?"


class FakeStore:
    def __init__(self, *, node: WorkflowNode, graph: WorkflowGraph, issue: CodexIssue) -> None:
        self.node = node
        self.graph = graph
        self.issue = issue

    async def find_node_by_task_id(self, task_id: str):
        return self.node

    async def update_workflow_node(self, node_id: str, **updates):
        for key, value in updates.items():
            setattr(self.node, key, value)

    async def load_workflow_graph(self, graph_id: str):
        return self.graph

    async def load_codex_issue(self, issue_id: str):
        return self.issue

    async def save_conductor_decision(self, record):
        pass

    async def list_pending_replans(self, graph_id: str):
        return []

    async def list_workflow_edges(self, graph_id: str):
        return []

    async def list_workflow_nodes(self, graph_id: str):
        return [self.node]

    async def update_workflow_graph(self, graph_id: str, **updates):
        for key, value in updates.items():
            setattr(self.graph, key, value)

    async def save_workflow_graph(self, graph: WorkflowGraph):
        self.graph = graph

    async def save_codex_issue(self, issue: CodexIssue):
        self.issue = issue

    async def list_agents(self, workspace_id=None):
        return [
            Agent(
                id="agent-engineer",
                name="Engineer",
                role_key="engineer",
                system_prompt_template="",
                triggers_replan_on_done=False,
            )
        ]


def test_scheduler_passes_subagent_result_to_conductor(monkeypatch):
    captured = {}

    async def fake_observe(self, *, result, node_status, graph, issue):
        captured["result"] = result
        return {"action": "proceed", "reason": "test"}

    monkeypatch.setattr("app.application.conductor_supervisor.ConductorSupervisor.observe", fake_observe)

    now = datetime(2026, 1, 1, 12, 0, 0)
    task = CodexTask(
        id="task-2",
        session_id="session-1",
        issue_id="issue-1",
        title="Build UI",
        prompt="Build the UI",
        role="engineer",
        status="done",
        result="Implementation report generated.",
        workflow_node_id="node-id",
        created_at=now,
        updated_at=now + timedelta(seconds=8),
    )
    node = WorkflowNode(
        id="node-id",
        graph_id="graph-1",
        node_key="engineer",
        agent_id="agent-engineer",
        task_id=task.id,
        status="running",
    )
    graph = WorkflowGraph(
        id="graph-1",
        issue_id="issue-1",
        status="running",
        dag_json="{}",
        nodes=[node],
        edges=[],
    )
    issue = CodexIssue(id="issue-1", session_id="session-1", title="Build UI")
    task._subagent_doc = FakeDoc([])

    scheduler = WorkflowScheduler(store=FakeStore(node=node, graph=graph, issue=issue))

    import asyncio
    asyncio.run(scheduler.on_task_completed(task))

    assert captured["result"].task_id == "task-2"
    assert captured["result"].artifact_json["issue_title"] == "Add export"
    assert captured["result"].duration_s == 8.0


def test_sqlite_store_persists_raw_task_result_json(tmp_path: Path):
    store = SQLiteStore(tmp_path / "console.db")
    task = CodexTask(
        id="task-json",
        session_id="session-json",
        title="Raw JSON",
        prompt="Return JSON",
        status="done",
        result="summary",
        result_json='{"full": true}',
    )

    store.save_codex_task(task)
    loaded = store.load_codex_task(task.id)

    assert loaded is not None
    assert loaded.result == "summary"
    assert loaded.result_json == '{"full": true}'


def test_async_sqlite_store_persists_raw_task_result_json(tmp_path: Path):
    async def run():
        store = AsyncSQLiteStore(tmp_path / "async-console.db")
        task = CodexTask(
            id="task-json-async",
            session_id="session-json",
            title="Raw JSON",
            prompt="Return JSON",
            status="done",
            result="summary",
            result_json='{"full": true}',
        )

        await store.save_codex_task(task)
        loaded = await store.load_codex_task(task.id)
        await store.close()

        assert loaded is not None
        assert loaded.result == "summary"
        assert loaded.result_json == '{"full": true}'

    import asyncio
    asyncio.run(run())
