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
async def test_lifespan_recovers_structured_prototype_operations_after_owned_workflows(
    monkeypatch,
):
    import app.bootstrap as bootstrap_module

    calls: list[str] = []

    class StructuredService:
        async def recover_interrupted_publications(self) -> int:
            calls.append("publication")
            return 1

        async def recover_pending_project_prototype_deletions(self) -> int:
            calls.append("deletion")
            return 1

        async def recover_interrupted_non_generation_operations(self) -> int:
            calls.append("ordinary_operations")
            return 1

    class AiService:
        async def recover_interrupted_runs(self) -> int:
            calls.append("ai")
            return 1

    class GenerationService:
        async def recover_interrupted_jobs(self) -> int:
            calls.append("generation")
            return 1

    monkeypatch.setattr(bootstrap_module, "async_store", None)
    monkeypatch.setattr(bootstrap_module, "codex_process_manager", _AwaitableProcessManager())
    monkeypatch.setattr(bootstrap_module, "structured_prototype_store", None)
    monkeypatch.setattr(bootstrap_module, "external_prototype_agent_store", None)
    monkeypatch.setattr(bootstrap_module, "structured_prototype_service", StructuredService())
    monkeypatch.setattr(bootstrap_module, "structured_prototype_ai_service", AiService())
    monkeypatch.setattr(
        bootstrap_module,
        "structured_prototype_generation_service",
        GenerationService(),
    )

    async with lifespan(FastAPI()):
        pass

    assert calls == ["publication", "ai", "generation", "deletion", "ordinary_operations"]


@pytest.mark.asyncio
async def test_lifespan_aborts_when_generation_recovery_service_is_unavailable(
    monkeypatch,
):
    import app.bootstrap as bootstrap_module
    from app.application.structured_prototype_generation_service import (
        StructuredPrototypeGenerationServiceError,
    )

    calls: list[str] = []

    class StructuredService:
        async def recover_interrupted_publications(self) -> int:
            calls.append("publication")
            return 0

        async def recover_interrupted_non_generation_operations(self) -> int:
            calls.append("ordinary_operations")
            return 0

    monkeypatch.setattr(bootstrap_module, "async_store", None)
    monkeypatch.setattr(bootstrap_module, "codex_process_manager", _AwaitableProcessManager())
    monkeypatch.setattr(bootstrap_module, "structured_prototype_store", object())
    monkeypatch.setattr(bootstrap_module, "external_prototype_agent_store", None)
    monkeypatch.setattr(bootstrap_module, "structured_prototype_service", StructuredService())
    monkeypatch.setattr(bootstrap_module, "structured_prototype_ai_service", None)
    monkeypatch.setattr(bootstrap_module, "structured_prototype_generation_service", None)

    with pytest.raises(StructuredPrototypeGenerationServiceError) as exc_info:
        async with lifespan(FastAPI()):
            pass

    assert exc_info.value.code == "generation_recovery_unavailable"
    assert calls == ["publication"]


@pytest.mark.asyncio
async def test_lifespan_aborts_when_structured_prototype_operation_recovery_fails(
    monkeypatch,
):
    import app.bootstrap as bootstrap_module
    from app.application.structured_prototype_service import StructuredPrototypeServiceError

    calls: list[str] = []

    class StructuredService:
        async def recover_interrupted_publications(self) -> int:
            calls.append("publication")
            return 0

        async def recover_pending_project_prototype_deletions(self) -> int:
            calls.append("deletion")
            return 0

        async def recover_interrupted_non_generation_operations(self) -> int:
            calls.append("ordinary_operations")
            raise StructuredPrototypeServiceError(
                "operation_recovery_corrupt",
                "active operation ledger is corrupt",
            )

    monkeypatch.setattr(bootstrap_module, "async_store", None)
    monkeypatch.setattr(bootstrap_module, "codex_process_manager", _AwaitableProcessManager())
    monkeypatch.setattr(bootstrap_module, "structured_prototype_store", None)
    monkeypatch.setattr(bootstrap_module, "external_prototype_agent_store", None)
    monkeypatch.setattr(bootstrap_module, "structured_prototype_service", StructuredService())
    monkeypatch.setattr(bootstrap_module, "structured_prototype_ai_service", None)
    monkeypatch.setattr(bootstrap_module, "structured_prototype_generation_service", None)

    with pytest.raises(StructuredPrototypeServiceError) as exc_info:
        async with lifespan(FastAPI()):
            pass

    assert exc_info.value.code == "operation_recovery_corrupt"
    assert calls == ["publication", "deletion", "ordinary_operations"]


@pytest.mark.asyncio
async def test_lifespan_aborts_when_structured_prototype_deletion_recovery_is_corrupt(
    monkeypatch,
):
    import app.bootstrap as bootstrap_module
    from app.application.structured_prototype_service import StructuredPrototypeServiceError

    calls: list[str] = []

    class StructuredService:
        async def recover_interrupted_publications(self) -> int:
            calls.append("publication")
            return 0

        async def recover_pending_project_prototype_deletions(self) -> int:
            calls.append("deletion")
            raise StructuredPrototypeServiceError(
                "operation_observability_corrupt",
                "active deletion ledger is corrupt",
            )

        async def recover_interrupted_non_generation_operations(self) -> int:
            calls.append("ordinary_operations")
            return 0

    monkeypatch.setattr(bootstrap_module, "async_store", None)
    monkeypatch.setattr(bootstrap_module, "codex_process_manager", _AwaitableProcessManager())
    monkeypatch.setattr(bootstrap_module, "structured_prototype_store", None)
    monkeypatch.setattr(bootstrap_module, "external_prototype_agent_store", None)
    monkeypatch.setattr(bootstrap_module, "structured_prototype_service", StructuredService())
    monkeypatch.setattr(bootstrap_module, "structured_prototype_ai_service", None)
    monkeypatch.setattr(bootstrap_module, "structured_prototype_generation_service", None)

    with pytest.raises(StructuredPrototypeServiceError) as exc_info:
        async with lifespan(FastAPI()):
            pass

    assert exc_info.value.code == "operation_observability_corrupt"
    assert calls == ["publication", "deletion"]


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
