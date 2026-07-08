from __future__ import annotations

import fastapi.dependencies.utils as fastapi_dependency_utils
import pytest
from fastapi import FastAPI

fastapi_dependency_utils.ensure_multipart_is_installed = lambda: None

from app.main import lifespan  # noqa: E402


class _AwaitableProcessManager:
    def __init__(self) -> None:
        self.terminated = False

    async def terminate_all(self) -> list[str]:
        self.terminated = True
        return ["process-1"]


class _AsyncStore:
    async def list_execution_processes(self) -> list:
        return []

    async def close(self) -> None:
        pass


@pytest.mark.asyncio
async def test_lifespan_awaits_async_process_manager_shutdown(monkeypatch):
    import app.bootstrap as bootstrap_module

    manager = _AwaitableProcessManager()
    monkeypatch.setattr(bootstrap_module, "async_store", _AsyncStore())
    monkeypatch.setattr(bootstrap_module, "codex_process_manager", manager)

    async with lifespan(FastAPI()):
        pass

    assert manager.terminated is True


@pytest.mark.asyncio
async def test_lifespan_recovers_conductors_and_runs_watchdog(monkeypatch):
    import asyncio  # noqa: I001
    import app.bootstrap as bootstrap_module
    import app.application.conductor_recovery as conductor_recovery
    import app.application.project_review_scheduler as project_review_scheduler
    import app.application.self_improvement_proposal_scheduler as self_improvement_proposal_scheduler
    import app.application.stall_watchdog as stall_watchdog

    calls: list[tuple[str, str | None]] = []
    created_tasks: list[str | None] = []
    tasks: list[FakeTask] = []

    class FakeTask:
        def __init__(self, name: str | None) -> None:
            self.name = name
            self.cancelled = False

        def cancel(self) -> None:
            self.cancelled = True

        def __await__(self):
            async def _done():
                return None

            return _done().__await__()

    async def fake_recover(
        store,
        *,
        event_bus=None,
        current_owner=None,
        stale_after_s=None,
        recover_foreign_owner=False,
        auto_restart=False,
        task_dispatcher_fn=None,
    ):
        calls.append(("recover", current_owner))
        assert stale_after_s == 0
        assert recover_foreign_owner is True
        return 1

    async def fake_conductor_watchdog(store, *, event_bus=None, task_dispatcher_fn=None):
        calls.append(("watchdog", None))

    async def fake_stall_watchdog(store, get_process_manager, run_task_with_user_content):
        return None

    async def fake_project_review_scheduler(store, *, event_bus=None):
        return None

    async def fake_self_improvement_proposal_scheduler(store, *, activate_fn, event_bus=None):
        return None

    def fake_create_task(coro, *, name=None, context=None):
        created_tasks.append(name)
        coro.close()
        task = FakeTask(name)
        tasks.append(task)
        return task

    monkeypatch.setattr(bootstrap_module, "async_store", _AsyncStore())
    monkeypatch.setattr(bootstrap_module, "codex_process_manager", _AwaitableProcessManager())
    monkeypatch.setattr(conductor_recovery, "recover_orphaned_conductors", fake_recover)
    monkeypatch.setattr(conductor_recovery, "run_watchdog", fake_conductor_watchdog)
    monkeypatch.setattr(
        project_review_scheduler, "run_project_review_scheduler_loop", fake_project_review_scheduler
    )
    monkeypatch.setattr(
        self_improvement_proposal_scheduler,
        "run_self_improvement_proposal_scheduler_loop",
        fake_self_improvement_proposal_scheduler,
    )
    monkeypatch.setattr(stall_watchdog, "run", fake_stall_watchdog)
    monkeypatch.setattr(asyncio, "create_task", fake_create_task)

    async with lifespan(FastAPI()):
        pass

    assert calls[0][0] == "recover"
    assert calls[0][1]
    assert "conductor-recovery-watchdog" in created_tasks
    assert "project-review-scheduler" in created_tasks
    assert "self-improvement-proposal-scheduler" in created_tasks
    assert any(task.name == "project-review-scheduler" and task.cancelled for task in tasks)
    assert any(
        task.name == "self-improvement-proposal-scheduler" and task.cancelled for task in tasks
    )
