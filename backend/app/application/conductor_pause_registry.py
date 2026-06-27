from __future__ import annotations

import asyncio
from dataclasses import dataclass, field


@dataclass
class _ConductorControl:
    pause_requested: bool = False
    wake_event: asyncio.Event = field(default_factory=asyncio.Event)
    inflight_llm_task: asyncio.Task | None = None

    def __post_init__(self) -> None:
        self.wake_event.set()


class ConductorPauseRegistry:
    """Process-local runtime controls for active issue conductor loops."""

    _instance: "ConductorPauseRegistry | None" = None  # noqa: UP037

    def __init__(self) -> None:
        self._controls: dict[str, _ConductorControl] = {}
        self._lock = asyncio.Lock()

    @classmethod
    def instance(cls) -> "ConductorPauseRegistry":  # noqa: UP037
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def register(self, conductor_task_id: str) -> None:
        async with self._lock:
            control = self._controls.get(conductor_task_id)
            if control is None:
                control = _ConductorControl()
                self._controls[conductor_task_id] = control
            control.pause_requested = False
            control.wake_event.set()
            control.inflight_llm_task = None

    async def unregister(self, conductor_task_id: str) -> None:
        async with self._lock:
            self._controls.pop(conductor_task_id, None)

    async def set_inflight_llm_task(
        self, conductor_task_id: str, task: asyncio.Task | None
    ) -> None:
        async with self._lock:
            control = self._controls.get(conductor_task_id)
            if control is not None:
                control.inflight_llm_task = task

    async def request_pause(self, conductor_task_id: str) -> bool:
        async with self._lock:
            control = self._controls.get(conductor_task_id)
            if control is None:
                return False
            control.pause_requested = True
            control.wake_event.clear()
            inflight = control.inflight_llm_task
        if inflight is not None and not inflight.done():
            inflight.cancel()
        return True

    async def is_paused(self, conductor_task_id: str) -> bool:
        async with self._lock:
            control = self._controls.get(conductor_task_id)
            return bool(control and control.pause_requested)

    async def wait_if_paused(self, conductor_task_id: str) -> bool:
        while True:
            async with self._lock:
                control = self._controls.get(conductor_task_id)
                if control is None:
                    return False
                if not control.pause_requested:
                    return False
                wake_event = control.wake_event
            await wake_event.wait()

    async def resume(self, conductor_task_id: str) -> bool:
        async with self._lock:
            control = self._controls.get(conductor_task_id)
            if control is None:
                return False
            control.pause_requested = False
            control.wake_event.set()
            return True
