import asyncio  # noqa: I001
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest

from app.adapters.async_sqlite_store import AsyncSQLiteStore
import app.application.project_conductor as project_conductor_module
from app.application.github_pr_followup import GitHubPRFollowupResult, GitHubPRFollowupSummary
from app.application.project_conductor import (
    PROJECT_CONDUCTOR_HOT_EVENT_LIMIT,
    PROJECT_CONDUCTOR_WARM_SUMMARY_LIMIT,
    ProjectConductor,
    ProjectConductorStateError,
)
from app.domain.models import ConductorTask, Project, ProjectConductorState, ProjectMemoryEmbedding


def _run(coro):
    return asyncio.run(coro)


class _EventBus:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    async def append(self, event: dict[str, object]) -> None:
        self.events.append(event)


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
        assert state is not None
        warm = json.loads(state.warm_summaries_json)
        cold = await store.list_project_memory_embeddings(project.id)
        await store.close()

        assert state.hot_thread_json == "[]"
        assert warm == []
        assert len(cold) == 1
        assert "auth token failure" in cold[0].summary_text

    _run(run())


def test_project_conductor_count_overflow_compacts_hot_instead_of_dropping(
    tmp_path: Path,
):
    async def run():
        store = AsyncSQLiteStore(tmp_path / "hot-count-overflow.db")
        project = _project(tmp_path)
        await store.save_project(project)
        await store.save_project_conductor_state(
            ProjectConductorState(
                project_id=project.id,
                hot_thread_json=json.dumps(
                    [
                        {"role": "worker", "content": f"historical-event-{index}"}
                        for index in range(PROJECT_CONDUCTOR_HOT_EVENT_LIMIT)
                    ]
                ),
            )
        )
        conductor = ProjectConductor(project_id=project.id, store=store)

        await conductor.append_hot_event(role="worker", content="newest-event")
        state = await store.load_project_conductor_state(project.id)
        assert state is not None
        hot = json.loads(state.hot_thread_json)
        warm = json.loads(state.warm_summaries_json)
        await store.close()
        return hot, warm

    hot, warm = _run(run())

    assert len(hot) == PROJECT_CONDUCTOR_HOT_EVENT_LIMIT
    assert hot[-1]["content"] == "newest-event"
    assert "historical-event-0" not in [item["content"] for item in hot]
    assert len(warm) == 1
    assert "historical-event-0" in warm[0]["summary"]


def test_project_conductor_count_overflow_compacts_warm_to_cold(tmp_path: Path):
    async def run():
        store = AsyncSQLiteStore(tmp_path / "warm-count-overflow.db")
        project = _project(tmp_path)
        await store.save_project(project)
        await store.save_project_conductor_state(
            ProjectConductorState(
                project_id=project.id,
                warm_summaries_json=json.dumps(
                    [
                        {"id": f"summary-{index}", "summary": f"stage-summary-{index}"}
                        for index in range(PROJECT_CONDUCTOR_WARM_SUMMARY_LIMIT + 1)
                    ]
                ),
            )
        )
        conductor = ProjectConductor(project_id=project.id, store=store)

        state = await conductor.get_or_create_state()
        warm = json.loads(state.warm_summaries_json)
        cold = await store.list_project_memory_embeddings(project.id)
        await store.close()
        return warm, cold

    warm, cold = _run(run())

    assert len(warm) == PROJECT_CONDUCTOR_WARM_SUMMARY_LIMIT
    assert warm[0]["summary"] == "stage-summary-1"
    assert len(cold) == 1
    assert cold[0].summary_text == "stage-summary-0"


def test_project_conductor_answer_uses_pinned_warm_and_cold_memory(tmp_path: Path):
    async def run():
        store = AsyncSQLiteStore(tmp_path / "console.db")
        project = _project(tmp_path)
        await store.save_project(project)
        await store.save_project_conductor_state(
            ProjectConductorState(
                project_id=project.id,
                pinned_text="Pinned: keep API contracts stable.",
                warm_summaries_json=json.dumps(
                    [{"summary": "Recent issues failed because QA caught missing migrations."}]
                ),
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
        assert state is not None
        await store.close()

        assert result["status"] == "done"
        answer = result["answer"]
        assert isinstance(answer, str)
        assert "Pinned: keep API contracts stable." in answer
        assert "missing migrations" in answer
        assert "token refresh" in answer
        assert state.total_tasks_handled == 1

    _run(run())


def test_project_conductor_scheduled_review_runs_pr_followup_sweep(monkeypatch, tmp_path: Path):
    async def run():
        store = AsyncSQLiteStore(tmp_path / "scheduled-review.db")
        project = _project(tmp_path)
        await store.save_project(project)
        calls: list[dict[str, object]] = []

        async def sweep_project_github_prs(
            project_id, *, store, event_bus, run_subprocess, auto_merge=False
        ):
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

        conductor = ProjectConductor(project_id=project.id, store=store, event_bus=_EventBus())
        task = ConductorTask(
            id=str(uuid4()),
            project_id=project.id,
            task_kind="scheduled_review",
            payload={},
        )

        result = await conductor.handle_task(task)
        loaded_task = await store.load_conductor_task(task.id)
        state = await store.load_project_conductor_state(project.id)
        assert state is not None
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


def test_concurrent_project_conductor_writers_retry_without_losing_events(tmp_path: Path):
    async def run():
        store = AsyncSQLiteStore(tmp_path / "concurrent-state.db")
        project = _project(tmp_path)
        await store.save_project(project)
        conductor = ProjectConductor(project_id=project.id, store=store)
        await conductor.get_or_create_state()

        original_load = store.load_project_conductor_state
        first_loads = 0
        both_loaded = asyncio.Event()

        async def synchronized_load(project_id: str):
            nonlocal first_loads
            state = await original_load(project_id)
            if first_loads < 2:
                first_loads += 1
                if first_loads == 2:
                    both_loaded.set()
                await both_loaded.wait()
            return state

        store.load_project_conductor_state = synchronized_load  # type: ignore[method-assign]
        await asyncio.gather(
            conductor.append_hot_event(role="worker", content="first concurrent event"),
            conductor.append_hot_event(role="reviewer", content="second concurrent event"),
        )
        state = await original_load(project.id)
        assert state is not None
        await store.close()
        return state

    state = _run(run())
    hot = json.loads(state.hot_thread_json)

    assert {event["content"] for event in hot} == {
        "first concurrent event",
        "second concurrent event",
    }
    assert state.revision == 3


def test_scheduled_review_does_not_reingest_rendered_project_memory(monkeypatch, tmp_path: Path):
    async def run():
        store = AsyncSQLiteStore(tmp_path / "scheduled-memory.db")
        project = _project(tmp_path)
        await store.save_project(project)
        await store.save_project_conductor_state(
            ProjectConductorState(
                project_id=project.id,
                pinned_text="Pinned: retain this API contract.",
                warm_summaries_json=json.dumps([{"summary": "Private historical summary."}]),
                warm_tokens=8,
            )
        )
        await store.save_project_memory_embedding(
            ProjectMemoryEmbedding(
                id="memory-private",
                project_id=project.id,
                source_kind="engineer_note",
                source_id="note-1",
                summary_text="Private long-term memory.",
                vector_json="[]",
                created_at=datetime.now(),
            )
        )

        async def sweep_project_github_prs(
            project_id, *, store, event_bus, run_subprocess, auto_merge=False
        ):
            return GitHubPRFollowupSummary(project_id=project_id, results=[])

        monkeypatch.setattr(
            project_conductor_module,
            "sweep_project_github_prs",
            sweep_project_github_prs,
        )
        conductor = ProjectConductor(project_id=project.id, store=store)
        task = ConductorTask(
            id="scheduled-no-feedback",
            project_id=project.id,
            task_kind="scheduled_review",
            payload={},
        )

        result = await conductor.handle_task(task)
        state = await store.load_project_conductor_state(project.id)
        assert state is not None
        hot = json.loads(state.hot_thread_json)
        warm = json.loads(state.warm_summaries_json)
        await store.close()
        return result, hot, warm

    result, hot, warm = _run(run())

    assert result["answer"] == "Scheduled project review completed (0 PRs checked)."
    assert "Private historical summary" not in result["answer"]
    assert "Private long-term memory" not in result["answer"]
    assert len(hot) == 1
    assert hot[0]["kind"] == "scheduled_review"
    assert warm == [{"summary": "Private historical summary.", "id": warm[0]["id"]}]


def test_project_conductor_scheduled_review_reports_pr_followup_failure(
    monkeypatch, tmp_path: Path
):
    async def run():
        store = AsyncSQLiteStore(tmp_path / "scheduled-review-failure.db")
        project = _project(tmp_path)
        await store.save_project(project)

        async def sweep_project_github_prs(
            project_id, *, store, event_bus, run_subprocess, auto_merge=False
        ):
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
                hot_thread_json=json.dumps(
                    [{"role": "worker", "content": f"hot event {index}"} for index in range(25)]
                ),
                pinned_text="Pinned: preserve event stream contracts.",
                warm_summaries_json=json.dumps(
                    [{"summary": f"Stage summary {index}"} for index in range(9)]
                ),
                warm_tokens=8,
            )
        )
        for index in range(21):
            await store.save_project_memory_embedding(
                ProjectMemoryEmbedding(
                    id=f"memory-{index:02d}",
                    project_id=project.id,
                    source_kind="issue_summary",
                    source_id=f"issue-{index:02d}",
                    summary_text=f"Historical risk {index}",
                    vector_json="[]",
                    created_at=datetime(2026, 1, 1, 0, 0, index),
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
    assert state_payload["hot_thread_total"] == 25
    assert len(state_payload["hot_thread"]) == 20
    assert state_payload["hot_thread_truncated"] is True
    assert state_payload["warm_summaries_total"] == 9
    assert len(state_payload["warm_summaries"]) == 8
    assert state_payload["warm_summaries_truncated"] is True
    assert len(state_payload["cold_memories"]) == 20
    assert state_payload["cold_memories"][0]["id"] == "memory-20"
    assert state_payload["cold_memories_total"] == 21
    assert state_payload["cold_memories_truncated"] is True
    assert "Stage summary" in ask_payload["answer"]


def test_project_conductor_start_loop_api_uses_deterministic_checkpoint_without_llm(
    monkeypatch, tmp_path: Path
):
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
        assert state is not None
        hot = json.loads(state.hot_thread_json)
        await store.close()
        return payload, hot

    payload, hot = _run(run())
    assert payload["status"] == "done"
    assert payload["turn_count"] == 1
    assert payload["llm"] is None
    assert payload["tool_events"][0] == {
        "id": payload["tool_events"][0]["id"],
        "name": "finalize_task",
        "input": {},
        "result": {"status": "done"},
        "is_error": False,
    }
    assert "deterministic checkpoint" in payload["answer"]
    assert hot[-1]["kind"] == "loop"


def test_project_conductor_rejects_corrupt_persisted_memory(tmp_path: Path):
    async def run():
        store = AsyncSQLiteStore(tmp_path / "corrupt-memory.db")
        await store.save_project_conductor_state(
            ProjectConductorState(project_id="project-1", hot_thread_json="{")
        )
        conductor = ProjectConductor(project_id="project-1", store=store)
        with pytest.raises(
            ProjectConductorStateError, match="hot_thread_json contains invalid JSON"
        ):
            await conductor.get_or_create_state()
        await store.close()

    _run(run())


def test_schema_v16_repairs_only_legacy_recursive_conductor_memory(tmp_path: Path):
    async def initialize(db_path: Path) -> None:
        store = AsyncSQLiteStore(db_path)
        await store._ensure_db()
        await store.close()

    db_path = tmp_path / "legacy-project-conductor.db"
    _run(initialize(db_path))
    legacy_answer = (
        "ProjectConductor context answer.\n\n"
        "Question: Run a scheduled project health review.\n\n"
        "Warm summaries:\n- recursive history"
    )
    recursive_summary = (
        f"user: Run a scheduled project health review. | project_conductor: {legacy_answer}"
    )
    result_json = json.dumps(
        {
            "status": "done",
            "answer": legacy_answer,
            "task_id": "scheduled-legacy",
            "github_pr_followup": {"counts": {"merged": 1}},
        }
    )
    with sqlite3.connect(db_path) as connection:
        connection.execute("UPDATE schema_version SET version = 15 WHERE id = 1")
        connection.execute(
            """INSERT INTO project_conductor_states (
                   project_id, hot_thread_json, warm_summaries_json, pinned_text,
                   hot_tokens, warm_tokens, total_tasks_handled
               ) VALUES (?, ?, ?, '', 999, 999, 7)""",
            (
                "project-1",
                json.dumps(
                    [
                        {"role": "engineer", "content": "Keep this event."},
                        {
                            "role": "project_conductor",
                            "content": legacy_answer,
                            "task_id": "scheduled-legacy",
                        },
                    ]
                ),
                json.dumps(
                    [
                        {"id": "keep-warm", "summary": "Keep this summary."},
                        {"id": "drop-warm", "summary": recursive_summary},
                    ]
                ),
            ),
        )
        connection.execute(
            """INSERT INTO conductor_tasks (
                   id, project_id, task_kind, payload_json, status, result_json,
                   created_at, updated_at
               ) VALUES (?, ?, 'scheduled_review', '{}', 'done', ?, ?, ?)""",
            (
                "scheduled-legacy",
                "project-1",
                result_json,
                "2026-01-01T00:00:00",
                "2026-01-01T00:00:01",
            ),
        )
        connection.executemany(
            """INSERT INTO project_memory_embeddings (
                   id, project_id, source_kind, source_id, summary_text, vector_json, created_at
               ) VALUES (?, 'project-1', ?, ?, ?, '[]', '2026-01-01T00:00:00')""",
            [
                (
                    "drop-cold",
                    "warm_summary",
                    "drop-warm",
                    f"engineer: Keep this context. | {recursive_summary}",
                ),
                (
                    "drop-compacted-cold",
                    "warm_summary",
                    "already-compacted-warm",
                    recursive_summary,
                ),
                ("keep-cold", "engineer_note", "note-1", "Keep this long-term memory."),
                (
                    "keep-recursive-engineer-note",
                    "engineer_note",
                    "note-2",
                    recursive_summary,
                ),
            ],
        )

    async def migrate_and_read():
        store = AsyncSQLiteStore(db_path)
        await store._ensure_db()
        state = await store.load_project_conductor_state("project-1")
        task = await store.load_conductor_task("scheduled-legacy")
        memories = await store.list_project_memory_embeddings("project-1")
        connection = await store._get_conn()
        version = await (
            await connection.execute("SELECT version FROM schema_version WHERE id = 1")
        ).fetchone()
        audits = await (
            await connection.execute(
                """SELECT event FROM project_audit
                   WHERE project_id = ?
                     AND event = 'project_conductor_recursive_memory_repaired'""",
                ("project-1",),
            )
        ).fetchall()
        await store.close()
        return version[0], state, task, memories, [row[0] for row in audits]

    first_read = _run(migrate_and_read())
    version, state, task, memories, audits = first_read

    assert version == 17
    assert state is not None
    assert json.loads(state.hot_thread_json) == [
        {"role": "engineer", "content": "Keep this event."}
    ]
    assert json.loads(state.warm_summaries_json) == [
        {"id": "keep-warm", "summary": "Keep this summary."}
    ]
    assert state.hot_tokens < 999
    assert state.warm_tokens < 999
    assert task is not None
    repaired_result = json.loads(task.result_json)
    assert repaired_result["answer"] == (
        "Scheduled project review completed. Historical recursive context was removed."
    )
    assert repaired_result["github_pr_followup"] == {"counts": {"merged": 1}}
    assert sorted(memory.id for memory in memories) == [
        "keep-cold",
        "keep-recursive-engineer-note",
    ]
    assert audits == ["project_conductor_recursive_memory_repaired"]
    assert _run(migrate_and_read()) == first_read


def test_schema_v16_rejects_non_array_conductor_memory(tmp_path: Path):
    async def initialize(db_path: Path) -> None:
        store = AsyncSQLiteStore(db_path)
        await store._ensure_db()
        await store.close()

    db_path = tmp_path / "non-array-project-conductor.db"
    _run(initialize(db_path))
    with sqlite3.connect(db_path) as connection:
        connection.execute("UPDATE schema_version SET version = 15 WHERE id = 1")
        connection.execute(
            """INSERT INTO project_conductor_states (
                   project_id, hot_thread_json, warm_summaries_json
               ) VALUES ('project-1', '{}', '[]')"""
        )

    async def migrate() -> None:
        store = AsyncSQLiteStore(db_path)
        try:
            with pytest.raises(
                ValueError,
                match="project conductor state JSON is invalid for project project-1",
            ):
                await store._ensure_db()
        finally:
            await store.close()

    _run(migrate())


def test_schema_v16_preserves_legacy_scalar_memory_items(tmp_path: Path):
    async def initialize(db_path: Path) -> None:
        store = AsyncSQLiteStore(db_path)
        await store._ensure_db()
        await store.close()

    db_path = tmp_path / "scalar-project-conductor.db"
    _run(initialize(db_path))
    legacy_answer = (
        "ProjectConductor context answer.\n\nQuestion: Run a scheduled project health review."
    )
    with sqlite3.connect(db_path) as connection:
        connection.execute("UPDATE schema_version SET version = 15 WHERE id = 1")
        connection.execute(
            """INSERT INTO project_conductor_states (
                   project_id, hot_thread_json, warm_summaries_json
               ) VALUES (?, ?, ?)""",
            (
                "project-1",
                json.dumps(
                    [
                        "legacy hot event",
                        9_223_372_036_854_775_808,
                        {
                            "role": "project_conductor",
                            "task_id": "scheduled-scalar",
                            "content": legacy_answer,
                        },
                    ]
                ),
                json.dumps(["legacy warm summary", 9_223_372_036_854_775_809]),
            ),
        )
        connection.execute(
            """INSERT INTO conductor_tasks (
                   id, project_id, task_kind, payload_json, status, result_json
               ) VALUES ('scheduled-scalar', 'project-1', 'scheduled_review', '{}', 'done', ?)""",
            (json.dumps({"status": "done", "answer": legacy_answer}),),
        )

    async def migrate_and_read() -> ProjectConductorState | None:
        store = AsyncSQLiteStore(db_path)
        await store._ensure_db()
        state = await store.load_project_conductor_state("project-1")
        await store.close()
        return state

    state = _run(migrate_and_read())

    assert state is not None
    assert json.loads(state.hot_thread_json) == [
        "legacy hot event",
        9_223_372_036_854_775_808,
    ]
    assert json.loads(state.warm_summaries_json) == [
        "legacy warm summary",
        9_223_372_036_854_775_809,
    ]


def test_schema_v16_does_not_delete_matching_memory_from_clean_projects(tmp_path: Path):
    async def initialize(db_path: Path) -> None:
        store = AsyncSQLiteStore(db_path)
        await store._ensure_db()
        await store.close()

    db_path = tmp_path / "scoped-project-conductor-repair.db"
    _run(initialize(db_path))
    quoted_text = (
        "A legitimate note quotes Run a scheduled project health review. and "
        "ProjectConductor context answer. for migration documentation."
    )
    recursive_answer = (
        "ProjectConductor context answer.\n\nQuestion: Run a scheduled project health review."
    )
    recursive_summary = (
        f"user: Run a scheduled project health review. | project_conductor: {recursive_answer}"
    )
    with sqlite3.connect(db_path) as connection:
        connection.execute("UPDATE schema_version SET version = 15 WHERE id = 1")
        connection.executemany(
            """INSERT INTO project_conductor_states (
                   project_id, hot_thread_json, warm_summaries_json
               ) VALUES (?, '[]', ?)""",
            [
                (
                    "dirty-project",
                    json.dumps(
                        [
                            {
                                "id": "dirty-quote",
                                "summary": (
                                    "engineer: Migration notes quote the old answer "
                                    f"verbatim: {recursive_answer}"
                                ),
                            }
                        ]
                    ),
                ),
                (
                    "clean-project",
                    json.dumps([{"id": "clean-warm", "summary": quoted_text}]),
                ),
            ],
        )
        connection.execute(
            """INSERT INTO conductor_tasks (
                   id, project_id, task_kind, payload_json, status, result_json
               ) VALUES ('dirty-review', 'dirty-project', 'scheduled_review', '{}', 'done', ?)""",
            (json.dumps({"status": "done", "answer": recursive_answer}),),
        )
        connection.executemany(
            """INSERT INTO project_memory_embeddings (
                   id, project_id, source_kind, source_id, summary_text, vector_json
               ) VALUES (?, ?, 'warm_summary', ?, ?, '[]')""",
            [
                ("clean-cold", "clean-project", "clean-warm", recursive_summary),
                (
                    "dirty-quote-cold",
                    "dirty-project",
                    "dirty-quote",
                    f"engineer: Migration documentation quotes {recursive_summary}",
                ),
            ],
        )

    async def migrate_and_read():
        store = AsyncSQLiteStore(db_path)
        await store._ensure_db()
        clean_state = await ProjectConductor(
            project_id="clean-project", store=store
        ).get_or_create_state()
        dirty_state = await ProjectConductor(
            project_id="dirty-project", store=store
        ).get_or_create_state()
        clean_memories = await store.list_project_memory_embeddings("clean-project")
        dirty_memories = await store.list_project_memory_embeddings("dirty-project")
        connection = await store._get_conn()
        clean_audits = await (
            await connection.execute(
                """SELECT COUNT(*) FROM project_audit
                   WHERE project_id = 'clean-project'
                     AND event = 'project_conductor_recursive_memory_repaired'"""
            )
        ).fetchone()
        await store.close()
        return clean_state, dirty_state, clean_memories, dirty_memories, clean_audits[0]

    clean_state, dirty_state, clean_memories, dirty_memories, clean_audit_count = _run(
        migrate_and_read()
    )

    assert clean_state is not None
    assert json.loads(clean_state.warm_summaries_json) == [
        {"id": "clean-warm", "summary": quoted_text}
    ]
    assert dirty_state is not None
    assert json.loads(dirty_state.warm_summaries_json) == [
        {
            "id": "dirty-quote",
            "summary": (
                f"engineer: Migration notes quote the old answer verbatim: {recursive_answer}"
            ),
        }
    ]
    assert [memory.id for memory in clean_memories] == ["clean-cold"]
    assert [memory.id for memory in dirty_memories] == ["dirty-quote-cold"]
    assert clean_audit_count == 0


def test_schema_v17_repairs_prerelease_zero_state_revision(tmp_path: Path):
    async def initialize(db_path: Path) -> None:
        store = AsyncSQLiteStore(db_path)
        await store._ensure_db()
        await store.close()

    db_path = tmp_path / "zero-project-conductor-revision.db"
    _run(initialize(db_path))
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """INSERT INTO project_conductor_states (
                   project_id, hot_thread_json, warm_summaries_json, revision
               ) VALUES ('project-1', '[]', '[]', 0)"""
        )

    async def reopen_and_read() -> ProjectConductorState | None:
        store = AsyncSQLiteStore(db_path)
        await store._ensure_db()
        state = await store.load_project_conductor_state("project-1")
        await store.close()
        return state

    state = _run(reopen_and_read())

    assert state is not None
    assert state.revision == 1


def test_schema_v16_rolls_back_all_repairs_when_a_step_fails(tmp_path: Path):
    async def initialize(db_path: Path) -> None:
        store = AsyncSQLiteStore(db_path)
        await store._ensure_db()
        await store.close()

    db_path = tmp_path / "atomic-project-conductor.db"
    _run(initialize(db_path))
    legacy_answer = (
        "ProjectConductor context answer.\n\n"
        "Question: Run a scheduled project health review.\n\n"
        "Warm summaries:\n- recursive history"
    )
    recursive_summary = (
        f"user: Run a scheduled project health review. | project_conductor: {legacy_answer}"
    )
    with sqlite3.connect(db_path) as connection:
        connection.execute("UPDATE schema_version SET version = 15 WHERE id = 1")
        connection.execute(
            """INSERT INTO project_conductor_states (
                   project_id, hot_thread_json, warm_summaries_json, hot_tokens, warm_tokens
               ) VALUES (?, ?, ?, 999, 999)""",
            (
                "project-1",
                json.dumps(
                    [
                        {
                            "role": "project_conductor",
                            "content": legacy_answer,
                            "task_id": "scheduled-legacy",
                        }
                    ]
                ),
                json.dumps([{"id": "drop-warm", "summary": recursive_summary}]),
            ),
        )
        connection.execute(
            """INSERT INTO conductor_tasks (
                   id, project_id, task_kind, payload_json, status, result_json
               ) VALUES (?, ?, 'scheduled_review', '{}', 'done', ?)""",
            (
                "scheduled-legacy",
                "project-1",
                json.dumps({"status": "done", "answer": legacy_answer}),
            ),
        )
        connection.execute(
            """INSERT INTO project_memory_embeddings (
                   id, project_id, source_kind, source_id, summary_text, vector_json
               ) VALUES ('drop-cold', 'project-1', 'warm_summary',
                         'drop-warm', ?, '[]')""",
            (recursive_summary,),
        )
        connection.execute(
            """CREATE TRIGGER fail_project_conductor_v16_delete
               BEFORE DELETE ON project_memory_embeddings
               BEGIN
                   SELECT RAISE(ABORT, 'forced migration failure');
               END"""
        )

    async def migrate() -> None:
        store = AsyncSQLiteStore(db_path)
        try:
            with pytest.raises(sqlite3.IntegrityError, match="forced migration failure"):
                await store._ensure_db()
        finally:
            await store.close()

    _run(migrate())
    with sqlite3.connect(db_path) as connection:
        version = connection.execute("SELECT version FROM schema_version WHERE id = 1").fetchone()[
            0
        ]
        state_row = connection.execute(
            """SELECT hot_thread_json, warm_summaries_json, hot_tokens, warm_tokens
               FROM project_conductor_states WHERE project_id = 'project-1'"""
        ).fetchone()
        task_result = connection.execute(
            "SELECT result_json FROM conductor_tasks WHERE id = 'scheduled-legacy'"
        ).fetchone()[0]
        audit_count = connection.execute(
            """SELECT COUNT(*) FROM project_audit
               WHERE project_id = 'project-1'
                 AND event = 'project_conductor_recursive_memory_repaired'"""
        ).fetchone()[0]

    assert version == 15
    assert json.loads(state_row[0])[0]["task_id"] == "scheduled-legacy"
    assert json.loads(state_row[1])[0]["id"] == "drop-warm"
    assert state_row[2:] == (999, 999)
    assert json.loads(task_result)["answer"] == legacy_answer
    assert audit_count == 0
