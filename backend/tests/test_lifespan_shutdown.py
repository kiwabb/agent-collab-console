from __future__ import annotations

import pytest

from app.main import lifespan


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

    async with lifespan(None):
        pass

    assert manager.terminated is True
