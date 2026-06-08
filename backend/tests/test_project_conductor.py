import asyncio
import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from app.adapters.async_sqlite_store import AsyncSQLiteStore
import app.application.project_conductor as project_conductor_module
from app.application.github_pr_followup import GitHubPRFollowupResult, GitHubPRFollowupSummary
from app.application.project_conductor import ProjectConductor
from app.domain.models import ConductorTask, Project, ProjectConductorState, ProjectMemoryEmbedding


def _run(coro):
    return asyncio.run(coro)


def _project(tmp_path: Path) -> Project:
    repo = tmp_path / "repo"
    notes_dir = repo / ".agent-collab"
    notes_dir.mkdir(parents=True)
    (notes_dir / "team_notes.md").write_text(
        "# Team Notes\n\nPinned: keep API contracts stable.\n",
        encoding="utf-8",
    )
    return Project(
        id="project-1",
        name="Demo",
        repo_path=str(repo),
        default_branch="main",
        created_at=datetime.now(),
    )


def test_async_store_persists_project_conductor_state_and_memory(tmp_path: Path):
    async def run():
        store = AsyncSQLiteStore(tmp_path / "console.db")
        state = ProjectConductorState(
            project_id="project-1",
            hot_thread_json='[{"role":"user","content":"hello"}]',
            warm_summaries_json='[{"summary":"old issue"}]',
            pinned_text="Pinned constitution",
            hot_tokens=8,
            warm_tokens=12,
            total_tasks_handled=2,
            last_compaction_at=datetime(2026, 5, 21, 9, 0, 0),
        )
        memory = ProjectMemoryEmbedding(
            id="mem-1",
            project_id="project-1",
            source_kind="warm_summary",
            source_id="summary-1",
            summary_text="auth token regression root cause",
            vector_json="[1,2,3]",
            created_at=datetime(2026, 5, 21, 9, 5, 0),
        )

        await store.save_project_conductor_state(state)
        await store.save_project_memory_embedding(memory)

        loaded_state = await store.load_project_conductor_state("project-1")
        loaded_memory = await store.list_project_memory_embeddings("project-1")
        await store.close()

        assert loaded_state == state
        assert loaded_memory == [memory]

    _run(run())


def test_project_conductor_compacts_hot_to_warm_and_warm_to_cold(tmp_path: Path):
    async def run():
        store = AsyncSQLiteStore(tmp_path / "console.db")
        project = _project(tmp_path)
        await store.save_project(project)
        conductor = ProjectConductor(
            project_id=project.id,
            store=store,
            hot_token_limit=10,
            warm_token_limit=12,
        )

        await conductor.append_hot_event(
            role="subagent",
            content="auth token failure repeated across login sessions and refresh token handling",
            issue_id="issue-1",
        )
        state = await store.load_project_conductor_state(project.id)
        warm = json.loads(state.warm_summaries_json)
        cold = await store.list_project_memory_embeddings(project.id)
        await store.close()

        assert state.hot_thread_json == "[]"
        assert warm == []
        assert len(cold) == 1
        assert "auth token failure" in cold[0].summary_text

    _run(run())


def test_project_conductor_answer_uses_pinned_warm_and_cold_memory(tmp_path: Path):
    async def run():
        store = AsyncSQLiteStore(tmp_path / "console.db")
        project = _project(tmp_path)
        await store.save_project(project)
        await store.save_project_conductor_state(
            ProjectConductorState(
                project_id=project.id,
                pinned_text="Pinned: keep API contracts stable.",
                warm_summaries_json=json.dumps([
                    {"summary": "Recent issues failed because QA caught missing migrations."}
                ]),
                warm_tokens=10,
            )
        )
        await store.save_project_memory_embedding(
            ProjectMemoryEmbedding(
                id="mem-1",
                project_id=project.id,
                source_kind="issue_summary",
                source_id="issue-old",
                summary_text="Old auth issue: token refresh and login permissions failed together.",
                vector_json="[]",
                created_at=datetime.now(),
            )
        )
        conductor = ProjectConductor(project_id=project.id, store=store)
        task = ConductorTask(
            id=str(uuid4()),
            project_id=project.id,
            task_kind="ad_hoc",
            payload={"question": "What auth token risks should we remember?"},
        )

        result = await conductor.handle_task(task)
        state = await store.load_project_conductor_state(project.id)
        await store.close()

        assert result["status"] == "done"
        assert "Pinned: keep API contracts stable." in result["answer"]
        assert "missing migrations" in result["answer"]
        assert "token refresh" in result["answer"]
        assert state.total_tasks_handled == 1

    _run(run())


def test_project_conductor_scheduled_review_runs_pr_followup_sweep(monkeypatch, tmp_path: Path):
    async def run():
        store = AsyncSQLiteStore(tmp_path / "scheduled-review.db")
        project = _project(tmp_path)
        await store.save_project(project)
        calls: list[dict[str, object]] = []

        async def sweep_project_github_prs(project_id, *, store, event_bus, run_subprocess, auto_merge=False):
            calls.append(
                {
                    "project_id": project_id,
                    "store": store,
                    "event_bus": event_bus,
                    "run_subprocess": run_subprocess,
                    "auto_merge": auto_merge,
                }
            )
            return GitHubPRFollowupSummary(
                project_id=project_id,
                results=[GitHubPRFollowupResult(issue_id="issue-1", status="merged")],
            )

        monkeypatch.setattr(
            project_conductor_module,
            "sweep_project_github_prs",
            sweep_project_github_prs,
            raising=False,
        )
        monkeypatch.setattr(project_conductor_module, "_run_subprocess", object(), raising=False)

        conductor = ProjectConductor(project_id=project.id, store=store, event_bus="events")
        task = ConductorTask(
            id=str(uuid4()),
            project_id=project.id,
            task_kind="scheduled_review",
            payload={},
        )

        result = await conductor.handle_task(task)
        loaded_task = await store.load_conductor_task(task.id)
        state = await store.load_project_conductor_state(project.id)
        hot = json.loads(state.hot_thread_json)
        await store.close()
        return result, loaded_task, hot, calls

    result, loaded_task, hot, calls = _run(run())

    assert len(calls) == 1
    assert calls[0]["project_id"] == "project-1"
    assert calls[0]["auto_merge"] is True
    assert result["status"] == "done"
    assert result["github_pr_followup"]["counts"] == {"merged": 1}
    assert loaded_task.status == "done"
    assert json.loads(loaded_task.result_json)["github_pr_followup"]["counts"] == {"merged": 1}
    assert hot[-1]["github_pr_followup"]["counts"] == {"merged": 1}


def test_project_conductor_scheduled_review_reports_pr_followup_failure(monkeypatch, tmp_path: Path):
    async def run():
        store = AsyncSQLiteStore(tmp_path / "scheduled-review-failure.db")
        project = _project(tmp_path)
        await store.save_project(project)

        async def sweep_project_github_prs(project_id, *, store, event_bus, run_subprocess, auto_merge=False):
            raise RuntimeError("gh auth expired")

        monkeypatch.setattr(
            project_conductor_module,
            "sweep_project_github_prs",
            sweep_project_github_prs,
            raising=False,
        )
        monkeypatch.setattr(project_conductor_module, "_run_subprocess", object(), raising=False)

        conductor = ProjectConductor(project_id=project.id, store=store, event_bus=None)
        task = ConductorTask(
            id=str(uuid4()),
            project_id=project.id,
            task_kind="scheduled_review",
            payload={},
        )

        result = await conductor.handle_task(task)
        loaded_task = await store.load_conductor_task(task.id)
        await store.close()
        return result, loaded_task

    result, loaded_task = _run(run())

    assert result["status"] == "done"
    assert result["github_pr_followup"] == {
        "status": "failed",
        "error": "gh auth expired",
    }
    assert loaded_task.status == "done"
    assert json.loads(loaded_task.result_json)["github_pr_followup"]["status"] == "failed"


def test_project_conductor_api_exposes_state_and_ask(monkeypatch, tmp_path: Path):
    import app.interfaces.api as api_module
    from app.interfaces.api import (
        ProjectConductorAskRequest,
        codex_project_conductor_ask,
        codex_project_conductor_state,
    )

    async def run():
        store = AsyncSQLiteStore(tmp_path / "api-console.db")
        monkeypatch.setattr(api_module, "codex_store", store)
        project = _project(tmp_path)
        await store.save_project(project)
        await store.save_project_conductor_state(
            ProjectConductorState(
                project_id=project.id,
                pinned_text="Pinned: preserve event stream contracts.",
                warm_summaries_json=json.dumps([
                    {"summary": "Recent failures came from stale conductor context."}
                ]),
                warm_tokens=8,
            )
        )
        state_payload = await codex_project_conductor_state(project.id)
        ask_payload = await codex_project_conductor_ask(
            project.id,
            ProjectConductorAskRequest(question="What should we watch next?"),
        )
        await store.close()
        return state_payload, ask_payload

    state_payload, ask_payload = _run(run())
    assert state_payload["pinned_text"] == "Pinned: preserve event stream contracts."
    assert "stale conductor context" in ask_payload["answer"]


def test_project_conductor_start_loop_api_uses_deterministic_checkpoint_without_llm(monkeypatch, tmp_path: Path):
    import app.interfaces.api as api_module
    from app.interfaces.api import (
        ProjectConductorStartLoopRequest,
        codex_project_conductor_start_loop,
    )

    async def run():
        store = AsyncSQLiteStore(tmp_path / "loop-api-console.db")
        monkeypatch.setattr(api_module, "codex_store", store)
        monkeypatch.setattr(api_module, "event_bus", None)
        project = _project(tmp_path)
        await store.save_project(project)

        payload = await codex_project_conductor_start_loop(
            project.id,
            ProjectConductorStartLoopRequest(prompt="Inspect current project risk."),
        )
        state = await store.load_project_conductor_state(project.id)
        hot = json.loads(state.hot_thread_json)
        await store.close()
        return payload, hot

    payload, hot = _run(run())
    assert payload["status"] == "done"
    assert payload["tool_events"][0]["name"] == "finalize_task"
    assert "deterministic checkpoint" in payload["answer"]
    assert hot[-1]["kind"] == "loop"
