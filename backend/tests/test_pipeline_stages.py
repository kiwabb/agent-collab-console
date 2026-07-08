"""Tests for GET /api/codex/issues/{id}/pipeline-stages."""

import json  # noqa: I001
from datetime import datetime, timedelta  # noqa: F401

import pytest

from app.domain.models import (
    Agent,
    CodexIssue,
    WorkflowEdge,
    WorkflowGraph,
    WorkflowNode,
)
import app.interfaces.api as api_module


class _StoreStub:
    def __init__(
        self,
        issue: CodexIssue,
        graph: WorkflowGraph | None = None,
        agents: list[Agent] | None = None,
    ):
        self.issue = issue
        self.graph = graph
        self.agents = agents or []

    async def load_codex_issue(self, issue_id: str):
        return self.issue if issue_id == self.issue.id else None

    async def load_workflow_graph_for_issue(self, issue_id: str):
        return self.graph if (self.graph and issue_id == self.issue.id) else None

    async def list_agents(self, workspace_id: str | None = None, role_key=None):
        return list(self.agents)


def _issue(tmp_path):
    now = datetime.now()
    return CodexIssue(
        id="issue-ps-1",
        session_id="ws-1",
        title="Add /api/echo",
        current_phase="requirements",
        status="open",
        git_worktree_path=str(tmp_path),
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_pipeline_stages_returns_four_stages_when_no_graph(monkeypatch, tmp_path):
    issue = _issue(tmp_path)
    monkeypatch.setattr(api_module, "codex_store", _StoreStub(issue))

    result = await api_module.get_issue_pipeline_stages(issue.id)

    assert [s["role"] for s in result["stages"]] == [
        "product_manager",
        "architect",
        "engineer",
        "qa",
    ]
    assert [s["label"] for s in result["stages"]] == [
        "PM",
        "Architect",
        "Engineer",
        "QA",
    ]
    assert all(s["status"] == "pending" for s in result["stages"])
    assert result["started_at"] is None
    assert result["completed_at"] is None
    assert result["total_duration_seconds"] is None


@pytest.mark.asyncio
async def test_pipeline_stages_extracts_pm_acceptance_count(monkeypatch, tmp_path):
    issue = _issue(tmp_path)
    pm_dir = tmp_path / "issues" / issue.id / "pm"
    pm_dir.mkdir(parents=True)
    (pm_dir / "prd.json").write_text(
        json.dumps(
            {
                "acceptance_criteria": ["ac1", "ac2", "ac3"],
                "goals": ["g1", "g2"],
                "requirements": ["r1"],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(api_module, "codex_store", _StoreStub(issue))

    result = await api_module.get_issue_pipeline_stages(issue.id)
    pm = result["stages"][0]
    assert pm["summary"] is not None
    assert pm["foot"] is not None
    assert "3 acceptance criteria" in pm["summary"]
    assert "2 goals" in pm["foot"]
    assert "1 reqs" in pm["foot"]


@pytest.mark.asyncio
async def test_pipeline_stages_aggregates_graph_nodes_by_role(monkeypatch, tmp_path):
    issue = _issue(tmp_path)
    t0 = datetime(2026, 5, 18, 19, 30)
    t1 = datetime(2026, 5, 18, 19, 34)
    t2 = datetime(2026, 5, 18, 19, 38)  # noqa: F841

    pm_agent = Agent(
        id="agent-pm",
        name="PM",
        role_key="product_manager",
        system_prompt_template="",
    )
    arch_agent = Agent(
        id="agent-arch",
        name="Architect",
        role_key="architect",
        system_prompt_template="",
    )
    graph = WorkflowGraph(
        id="g1",
        issue_id=issue.id,
        dag_json="{}",
        nodes=[
            WorkflowNode(
                id="n1",
                graph_id="g1",
                node_key="pm",
                agent_id="agent-pm",
                status="done",
                task_id="task-pm",
                started_at=t0,
                completed_at=t1,
            ),
            WorkflowNode(
                id="n2",
                graph_id="g1",
                node_key="arch",
                agent_id="agent-arch",
                status="running",
                task_id="task-arch",
                started_at=t1,
            ),
        ],
        edges=[
            WorkflowEdge(
                id="e1",
                graph_id="g1",
                from_node_key="pm",
                to_node_key="arch",
            )
        ],
    )

    monkeypatch.setattr(
        api_module,
        "codex_store",
        _StoreStub(issue, graph=graph, agents=[pm_agent, arch_agent]),
    )

    result = await api_module.get_issue_pipeline_stages(issue.id)
    by_role = {s["role"]: s for s in result["stages"]}
    assert by_role["product_manager"]["status"] == "done"
    assert by_role["product_manager"]["task_id"] == "task-pm"
    assert by_role["product_manager"]["duration_seconds"] == 240
    assert by_role["architect"]["status"] == "running"
    assert by_role["engineer"]["status"] == "pending"
    assert by_role["qa"]["status"] == "pending"
    assert result["started_at"] is not None
    # Not all done → no total
    assert result["total_duration_seconds"] is None


# ----------------------------------------------------------------------------
# GET /api/codex/issues/{id}/activity
# ----------------------------------------------------------------------------


class _ActivityStoreStub:
    def __init__(self, issue: CodexIssue, tasks: list[dict], audit: list[dict] | None = None):
        self.issue = issue
        self.tasks = tasks
        self.audit = audit or []

    async def load_codex_issue(self, issue_id: str):
        return self.issue if issue_id == self.issue.id else None

    async def list_codex_tasks(self, issue_id: str | None = None, **kwargs):
        return list(self.tasks)

    async def list_project_audit(self, project_id: str, limit: int = 200):
        return list(self.audit)


@pytest.mark.asyncio
async def test_activity_includes_creation_and_task_lifecycle(monkeypatch, tmp_path):
    issue = _issue(tmp_path)
    tasks = [
        {
            "id": "t1",
            "role": "product_manager",
            "title": "draft prd",
            "status": "done",
            "created_at": "2026-05-18T10:00:00",
            "updated_at": "2026-05-18T10:05:00",
        },
        {
            "id": "t2",
            "role": "qa",
            "title": "run tests",
            "status": "failed",
            "created_at": "2026-05-18T10:30:00",
            "updated_at": "2026-05-18T10:35:00",
        },
    ]
    monkeypatch.setattr(api_module, "codex_store", _ActivityStoreStub(issue, tasks))
    result = await api_module.get_issue_activity(issue.id)
    types = [e["type"] for e in result["events"]]
    assert "issue_created" in types
    assert "task_started" in types
    assert "task_done" in types
    assert "task_failed" in types
    # Sorted ascending
    timestamps = [e["timestamp"] for e in result["events"]]
    assert timestamps == sorted(timestamps)


@pytest.mark.asyncio
async def test_activity_limit_keeps_newest(monkeypatch, tmp_path):
    issue = _issue(tmp_path)
    issue.created_at = datetime(2026, 5, 18, 9, 0)
    tasks = [
        {
            "id": f"t{i}",
            "role": "engineer",
            "title": f"step {i}",
            "status": "done",
            "created_at": f"2026-05-18T{10 + i:02d}:00:00",
            "updated_at": f"2026-05-18T{10 + i:02d}:05:00",
        }
        for i in range(5)
    ]
    monkeypatch.setattr(api_module, "codex_store", _ActivityStoreStub(issue, tasks))
    result = await api_module.get_issue_activity(issue.id, limit=3)
    assert len(result["events"]) == 3


# ----------------------------------------------------------------------------
# GET /api/codex/issues/{id}/graph-stats
# ----------------------------------------------------------------------------


class _GraphStatsStoreStub:
    def __init__(self, issue, graph=None, agents=None, tasks=None, log_events=None):
        self.issue = issue
        self.graph = graph
        self.agents = agents or []
        self.tasks = {t.id: t for t in (tasks or [])}
        self.log_events = log_events or []

    async def load_workflow_graph_for_issue(self, issue_id):
        return self.graph

    async def list_agents(self, workspace_id=None, role_key=None):
        return list(self.agents)

    async def load_codex_task(self, task_id):
        return self.tasks.get(task_id)

    async def load_log_events(self, session_id=None, task_id=None, limit=5000):
        return [type("E", (), {"content": c})() for c in self.log_events]


@pytest.mark.asyncio
async def test_graph_stats_aggregates_tokens(monkeypatch, tmp_path):
    issue = _issue(tmp_path)
    pm_agent = Agent(
        id="agent-pm", name="PM", role_key="product_manager", system_prompt_template=""
    )
    graph = WorkflowGraph(
        id="g1",
        issue_id=issue.id,
        dag_json="{}",
        nodes=[
            WorkflowNode(
                id="n1",
                graph_id="g1",
                node_key="pm",
                agent_id="agent-pm",
                status="done",
                task_id="task-pm",
                started_at=datetime(2026, 5, 18, 10, 0),
                completed_at=datetime(2026, 5, 18, 10, 2),
            ),
        ],
        edges=[],
    )

    class _T:
        id = "task-pm"
        session_id = "ws-1"
        created_at = datetime(2026, 5, 18, 10, 0)
        updated_at = datetime(2026, 5, 18, 10, 2)

    log_events = [
        json.dumps(
            {
                "id": "msg-1",
                "message": {"id": "msg-1", "usage": {"input_tokens": 100, "output_tokens": 50}},
            }
        ),
    ]
    monkeypatch.setattr(
        api_module,
        "codex_store",
        _GraphStatsStoreStub(
            issue, graph=graph, agents=[pm_agent], tasks=[_T()], log_events=log_events
        ),
    )
    result = await api_module.get_issue_graph_stats(issue.id)
    pm = result["nodes"]["pm"]
    assert pm["tokens"] is not None
    assert pm["tokens"]["input"] == 100
    assert pm["tokens"]["output"] == 50
    assert pm["duration_seconds"] == 120
    assert pm["est_cost_usd"] is not None
    assert "conductor" in result


@pytest.mark.asyncio
async def test_graph_stats_returns_empty_shell_when_no_graph(monkeypatch, tmp_path):
    issue = _issue(tmp_path)
    monkeypatch.setattr(api_module, "codex_store", _GraphStatsStoreStub(issue, graph=None))
    result = await api_module.get_issue_graph_stats(issue.id)
    assert result["nodes"] == {}
    assert result["conductor"]["role_key"] == "conductor"


# ----------------------------------------------------------------------------
# GET /api/codex/issues/{id}/artifacts/download
# ----------------------------------------------------------------------------


class _ZipStoreStub:
    def __init__(self, issue, artifacts):
        self.issue = issue
        self.artifacts = artifacts
        self.workspace = type("W", (), {"cwd": str(issue.git_worktree_path)})()

    async def load_codex_issue(self, issue_id):
        return self.issue if issue_id == self.issue.id else None

    async def load_codex_workspace(self, session_id):
        return self.workspace

    async def list_artifacts(self, issue_id):
        return list(self.artifacts)

    async def save_artifact(self, row):
        # No-op for the test
        return None


@pytest.mark.asyncio
async def test_artifacts_zip_streams_files(monkeypatch, tmp_path):
    import zipfile  # noqa: I001
    import io

    issue = _issue(tmp_path)
    pm_dir = tmp_path / "issues" / issue.id / "pm"
    pm_dir.mkdir(parents=True)
    f1 = pm_dir / "prd.md"
    f1.write_text("# PRD\nhello", encoding="utf-8")
    artifacts = [
        {
            "id": f"{issue.id}:prd.md",
            "issue_id": issue.id,
            "task_id": "t1",
            "name": "prd.md",
            "path": str(f1),
            "kind": "pm",
            "created_at": "2026-05-18T10:00:00",
        }
    ]
    monkeypatch.setattr(api_module, "codex_store", _ZipStoreStub(issue, artifacts))

    async def _no_scan(*args, **kwargs):
        return artifacts

    monkeypatch.setattr(api_module, "_scan_and_backfill_artifacts", _no_scan)
    response = await api_module.download_issue_artifacts_zip(issue.id)
    # FastAPI Response body
    body = getattr(response, "body", None)
    assert body, "expected non-empty zip body"
    zf = zipfile.ZipFile(io.BytesIO(body))
    names = zf.namelist()
    assert any(n.endswith("prd.md") for n in names)
