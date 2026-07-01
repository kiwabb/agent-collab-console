import asyncio
import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from app.adapters.async_sqlite_store import AsyncSQLiteStore
from app.domain.models import CodexTask, Project, ProjectConductorState  # noqa: F401


def _run(coro):
    return asyncio.run(coro)


def _project(tmp_path: Path) -> Project:
    repo = tmp_path / "repo"
    notes_dir = repo / ".agent-collab"
    notes_dir.mkdir(parents=True)
    (notes_dir / "team_notes.md").write_text("# Team Notes\n", encoding="utf-8")
    return Project(
        id="project-7",
        name="Phase7Test",
        repo_path=str(repo),
        default_branch="main",
        created_at=datetime.now(),
    )


def _task(
    issue_id: str, status: str, role: str = "engineer", task_kind: str = "initial"
) -> CodexTask:
    return CodexTask(
        id=str(uuid4()),
        session_id="session-1",
        issue_id=issue_id,
        title=f"Task by {role}",
        prompt="Do the work",
        role=role,
        status=status,
        result="Summary of work done." if status in ("done", "completed") else None,
        result_json=json.dumps({"key": "value"}) if status == "done" else None,
        task_kind=task_kind,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


def test_codex_issue_subagent_results_returns_only_terminal_tasks(monkeypatch, tmp_path: Path):
    import app.interfaces.api as api_module
    from app.interfaces.api import codex_issue_subagent_results

    async def run():
        store = AsyncSQLiteStore(tmp_path / "console.db")
        monkeypatch.setattr(api_module, "codex_store", store)

        issue_id = "issue-phase7-1"
        # Save tasks with varying statuses
        done_task = _task(issue_id, "done", role="engineer")
        failed_task = _task(issue_id, "failed", role="qa")
        pending_task = _task(issue_id, "pending", role="product_manager")
        in_progress_task = _task(issue_id, "in_progress", role="architect")

        for t in [done_task, failed_task, pending_task, in_progress_task]:
            await store.save_codex_task(t)

        result = await codex_issue_subagent_results(issue_id)
        await store.close()
        return result

    result = _run(run())
    assert isinstance(result, list)
    assert len(result) == 2
    statuses = {r["status"] for r in result}
    assert statuses == {"done", "failed"}
    roles = {r["role"] for r in result}
    assert roles == {"engineer", "qa"}


def test_codex_issue_subagent_results_artifact_json_parsed(monkeypatch, tmp_path: Path):
    import app.interfaces.api as api_module
    from app.interfaces.api import codex_issue_subagent_results

    async def run():
        store = AsyncSQLiteStore(tmp_path / "console.db")
        monkeypatch.setattr(api_module, "codex_store", store)

        issue_id = "issue-phase7-2"
        done_task = _task(issue_id, "done", role="engineer")
        await store.save_codex_task(done_task)

        result = await codex_issue_subagent_results(issue_id)
        await store.close()
        return result

    result = _run(run())
    assert len(result) == 1
    assert result[0]["artifact_json"] == {"key": "value"}
    assert result[0]["summary"] == "Summary of work done."
    assert result[0]["task_kind"] == "initial"


def test_codex_issue_subagent_results_empty_for_no_terminal_tasks(monkeypatch, tmp_path: Path):
    import app.interfaces.api as api_module
    from app.interfaces.api import codex_issue_subagent_results

    async def run():
        store = AsyncSQLiteStore(tmp_path / "console.db")
        monkeypatch.setattr(api_module, "codex_store", store)

        issue_id = "issue-phase7-3"
        t = _task(issue_id, "pending")
        await store.save_codex_task(t)

        result = await codex_issue_subagent_results(issue_id)
        await store.close()
        return result

    result = _run(run())
    assert result == []


def test_codex_issue_agent_mesh_returns_list(monkeypatch, tmp_path: Path):
    import app.interfaces.api as api_module
    from app.interfaces.api import codex_issue_agent_mesh

    async def run():
        store = AsyncSQLiteStore(tmp_path / "console.db")
        monkeypatch.setattr(api_module, "codex_store", store)

        issue_id = "issue-phase7-4"
        result = await codex_issue_agent_mesh(issue_id)
        await store.close()
        return result

    result = _run(run())
    # With no messages, should return empty list (store has list_agent_messages)
    assert isinstance(result, list)


def test_codex_project_conductor_message_appends_to_hot_thread(monkeypatch, tmp_path: Path):
    import app.interfaces.api as api_module
    from app.interfaces.api import (
        ProjectConductorMessageRequest,
        codex_project_conductor_message,
    )

    async def run():
        store = AsyncSQLiteStore(tmp_path / "console.db")
        monkeypatch.setattr(api_module, "codex_store", store)
        project = _project(tmp_path)
        await store.save_project(project)

        response = await codex_project_conductor_message(
            project.id,
            ProjectConductorMessageRequest(message="Hello from user"),
        )
        state = await store.load_project_conductor_state(project.id)
        await store.close()
        return response, state

    response, state = _run(run())
    assert response == {"status": "ok"}
    assert state is not None
    hot = json.loads(state.hot_thread_json)
    assert len(hot) >= 1
    last = hot[-1]
    assert last["role"] == "user"
    assert "Hello from user" in last["content"]
