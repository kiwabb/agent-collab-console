from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Literal, Protocol
from uuid import uuid4

from app.application import timeouts
from app.application.runtime_catalog_service import (
    RuntimeCatalogService,
    RuntimeCatalogStore,
    RuntimeCatalogValidationError,
)
from app.application.task_statuses import is_task_success_status
from app.application.worktree_manager import WorktreeError
from app.domain.models import CodexSession, CodexTask, ExecutionProcess, LogEvent, Project

logger = logging.getLogger(__name__)

PrototypeUiEngineerPhase = Literal["running"]


class PrototypeUiEngineerRunnerError(RuntimeError):
    """A Claude UI engineer execution failure safe to surface to its caller."""


@dataclass(frozen=True)
class PrototypeUiEngineerActivity:
    phase: PrototypeUiEngineerPhase
    task_id: str | None
    execution_process_id: str | None
    output_chars: int | None
    last_event_at: datetime | None
    occurred_at: datetime


@dataclass(frozen=True)
class PrototypeUiEngineerScopedTaskResult:
    task_id: str
    execution_process_id: str
    assistant_result: str


PrototypeUiEngineerActivityCallback = Callable[
    [PrototypeUiEngineerActivity], Awaitable[None]
]
PrototypeUiEngineerCompletionCallback = Callable[[Path, str, str], Awaitable[None]]
ClaudeAvailabilityProbe = Callable[[], bool]


class PrototypeUiEngineerStore(RuntimeCatalogStore, Protocol):
    async def load_codex_workspace(self, workspace_id: str) -> CodexSession | None: ...

    async def save_codex_workspace(self, workspace: CodexSession) -> None: ...

    async def list_codex_workspaces(
        self,
        project_id: str | None = None,
    ) -> list[dict[str, object]]: ...

    async def save_codex_task(self, task: CodexTask) -> None: ...

    async def load_codex_task(self, task_id: str) -> CodexTask | None: ...

    async def load_log_events(
        self,
        session_id: str,
        task_id: str | None = None,
        execution_process_id: str | None = None,
        limit: int = 1000,
        reverse: bool = False,
    ) -> list[LogEvent]: ...


class PrototypeUiEngineerTaskRunner(Protocol):
    async def start_task_run(
        self,
        task: CodexTask,
        *,
        wait_for_completion: bool = False,
        execution_started_callback: Callable[[CodexTask, ExecutionProcess], Awaitable[None]]
        | None = None,
        command_args_override: list[str] | None = None,
    ) -> ExecutionProcess: ...


class PrototypeUiEngineerGitInspector(Protocol):
    async def status_porcelain(self, worktree_path: str | Path) -> str: ...

    async def worktree_diff(self, worktree_path: str | Path, base_branch: str) -> str: ...

    async def head_commit(self, worktree_path: str | Path) -> str: ...


class PrototypeUiEngineerWorktreeManager(Protocol):
    @property
    def git(self) -> PrototypeUiEngineerGitInspector: ...

    async def prepare_prototype_ui_engineer_worktree(
        self,
        project: Project,
        scope_id: str,
        *,
        source_paths: tuple[str, ...] = (),
    ) -> tuple[str, str, str]: ...

    async def cleanup_prototype_ui_engineer_worktree(
        self,
        project: Project,
        scope_id: str,
    ) -> None: ...


class PrototypeUiEngineerRunner:
    """Run one Claude Code UI engineer task inside an isolated worktree."""

    def __init__(
        self,
        *,
        store: PrototypeUiEngineerStore,
        task_runner: PrototypeUiEngineerTaskRunner,
        worktree_manager: PrototypeUiEngineerWorktreeManager,
        claude_availability_probe: ClaudeAvailabilityProbe,
    ) -> None:
        self.store = store
        self.task_runner = task_runner
        self.worktree_manager = worktree_manager
        self.claude_availability_probe = claude_availability_probe
        self._workspace_locks: dict[str, asyncio.Lock] = {}

    async def execute_scoped_task(
        self,
        *,
        project: Project,
        scope_id: str,
        prompt: str,
        source_paths: tuple[str, ...],
        phase: str,
        task_kind: str,
        task_title: str,
        task_id: str,
        activity_callback: PrototypeUiEngineerActivityCallback | None = None,
        completion_callback: PrototypeUiEngineerCompletionCallback | None = None,
        mcp_config: str | None = None,
    ) -> PrototypeUiEngineerScopedTaskResult:
        await self.ensure_available()
        workspace = await self._ensure_workspace(project)
        prepared = False
        try:
            branch, worktree_path, base_revision = (
                await self.worktree_manager.prepare_prototype_ui_engineer_worktree(
                    project,
                    scope_id,
                    source_paths=source_paths,
                )
            )
            prepared = True
            baseline_head = await self.worktree_manager.git.head_commit(worktree_path)
            baseline_status = await self.worktree_manager.git.status_porcelain(worktree_path)
            baseline_diff = await self.worktree_manager.git.worktree_diff(
                worktree_path,
                base_revision,
            )
            baseline_sources = self._source_path_snapshot(Path(worktree_path), source_paths)

            now = datetime.now()
            task = CodexTask(
                id=task_id,
                session_id=workspace.id,
                project_id=project.id,
                phase=phase,
                title=task_title,
                prompt=prompt,
                role="prototype_ui_engineer",
                executor="claude",
                provider=None,
                model=None,
                status="pending",
                task_kind=task_kind,
                workspace_path=worktree_path,
                git_branch=branch,
                git_base_branch=base_revision,
                git_worktree_path=worktree_path,
                created_at=now,
                updated_at=now,
            )
            await self.store.save_codex_task(task)
            process = await self._run_task_with_activity(
                task,
                activity_callback,
                command_args_override=(
                    ["--mcp-config", mcp_config, "--strict-mcp-config"] if mcp_config else None
                ),
            )
            finished_task = await self.store.load_codex_task(task.id)
            if finished_task is None:
                raise PrototypeUiEngineerRunnerError("prototype UI engineer task disappeared")
            if not is_task_success_status(finished_task.status):
                detail = (finished_task.result or "task did not complete").strip()
                raise PrototypeUiEngineerRunnerError(
                    f"prototype UI engineer task failed: {detail}"
                )
            if finished_task.last_execution_process_id != process.id:
                raise PrototypeUiEngineerRunnerError(
                    "prototype UI engineer process correlation is inconsistent"
                )
            result = (finished_task.result or "").strip()
            if not result:
                raise PrototypeUiEngineerRunnerError(
                    "prototype UI engineer task returned no result"
                )
            if completion_callback is not None:
                await completion_callback(Path(worktree_path), task.id, process.id)
            await self._assert_no_source_edits(
                source_paths=source_paths,
                worktree_path=worktree_path,
                base_revision=base_revision,
                baseline_head=baseline_head,
                baseline_status=baseline_status,
                baseline_diff=baseline_diff,
                baseline_sources=baseline_sources,
            )
            return PrototypeUiEngineerScopedTaskResult(
                task_id=task.id,
                execution_process_id=process.id,
                assistant_result=result,
            )
        finally:
            if prepared:
                try:
                    await self.worktree_manager.cleanup_prototype_ui_engineer_worktree(
                        project,
                        scope_id,
                    )
                except (OSError, WorktreeError):
                    logger.warning(
                        "prototype UI engineer worktree cleanup failed: scope_id=%s",
                        scope_id,
                        exc_info=True,
                    )

    async def ensure_available(self) -> None:
        if not timeouts.codex_launch_enabled():
            raise PrototypeUiEngineerRunnerError(
                "prototype UI engineer runtime launch is disabled"
            )
        service = RuntimeCatalogService(self.store)
        try:
            catalog = await service.load_catalog()
        except Exception as exc:  # Runtime catalog persistence boundary.
            raise PrototypeUiEngineerRunnerError(
                "prototype UI engineer runtime catalog is unavailable"
            ) from exc
        executor = next((item for item in catalog.executors if item.id == "claude"), None)
        if executor is None or not executor.enabled or executor.executor_type != "claude":
            raise PrototypeUiEngineerRunnerError(
                "prototype UI engineer requires an enabled Claude executor"
            )
        try:
            resolved = service.resolve_effective_config(catalog, "claude")
        except RuntimeCatalogValidationError as exc:
            raise PrototypeUiEngineerRunnerError(
                "prototype UI engineer Claude runtime is not configured"
            ) from exc
        if resolved[0] != "claude" or resolved[4] != "claude":
            raise PrototypeUiEngineerRunnerError(
                "prototype UI engineer resolved to a non-Claude executor"
            )
        try:
            available = await asyncio.to_thread(self.claude_availability_probe)
        except Exception as exc:  # Existing runtime availability probe boundary.
            raise PrototypeUiEngineerRunnerError(
                "prototype UI engineer Claude CLI availability could not be checked"
            ) from exc
        if not available:
            raise PrototypeUiEngineerRunnerError(
                "prototype UI engineer requires an available Claude CLI command"
            )

    async def _ensure_workspace(self, project: Project) -> CodexSession:
        lock = self._workspace_locks.setdefault(project.id, asyncio.Lock())
        async with lock:
            summaries = await self.store.list_codex_workspaces(project_id=project.id)
            for summary in summaries:
                existing_id = summary.get("id")
                if not isinstance(existing_id, str):
                    continue
                existing = await self.store.load_codex_workspace(existing_id)
                if existing is not None and existing.project_id == project.id:
                    return existing

            now = datetime.now()
            workspace = CodexSession(
                id=f"prototype-workspace-{uuid4().hex}",
                title=f"{project.name} prototypes",
                cwd=project.repo_path,
                project_id=project.id,
                status="idle",
                created_at=now,
                last_active_at=now,
                messages=[],
            )
            await self.store.save_codex_workspace(workspace)
            return workspace

    async def _run_task_with_activity(
        self,
        task: CodexTask,
        callback: PrototypeUiEngineerActivityCallback | None,
        command_args_override: list[str] | None,
    ) -> ExecutionProcess:
        execution_process_id: str | None = None

        async def execution_started(
            started_task: CodexTask,
            process: ExecutionProcess,
        ) -> None:
            nonlocal execution_process_id
            execution_process_id = process.id
            await self._emit_activity(
                callback,
                task_id=started_task.id,
                execution_process_id=process.id,
                output_chars=0,
                last_event_at=datetime.now(),
            )

        runner_task = asyncio.create_task(
            self.task_runner.start_task_run(
                task,
                wait_for_completion=True,
                execution_started_callback=execution_started,
                command_args_override=command_args_override,
            )
        )
        activity_failure: PrototypeUiEngineerRunnerError | None = None
        last_output_chars = -1
        try:
            while not runner_task.done():
                done, _ = await asyncio.wait({runner_task}, timeout=1.0)
                if done or callback is None or execution_process_id is None:
                    continue
                if activity_failure is not None:
                    continue
                try:
                    logs = await self.store.load_log_events(
                        task.session_id,
                        task_id=task.id,
                        execution_process_id=execution_process_id,
                        limit=5000,
                    )
                    stdout_logs = [event for event in logs if event.stream == "stdout"]
                    output_chars = sum(len(event.content) for event in stdout_logs)
                    last_event_at = max(
                        (event.created_at for event in stdout_logs if event.created_at is not None),
                        default=datetime.now(),
                    )
                    if output_chars != last_output_chars:
                        await self._emit_activity(
                            callback,
                            task_id=task.id,
                            execution_process_id=execution_process_id,
                            output_chars=output_chars,
                            last_event_at=last_event_at,
                        )
                        last_output_chars = output_chars
                except PrototypeUiEngineerRunnerError as exc:
                    activity_failure = exc
                except Exception as exc:  # External log-store boundary; fail after task cleanup.
                    logger.exception(
                        "prototype UI engineer activity read failed: task_id=%s process_id=%s",
                        task.id,
                        execution_process_id,
                    )
                    activity_failure = PrototypeUiEngineerRunnerError(
                        f"prototype UI engineer activity could not be read: {exc}"
                    )
        except asyncio.CancelledError:
            while not runner_task.done():
                try:
                    await asyncio.shield(runner_task)
                except asyncio.CancelledError:
                    continue
            with suppress(Exception):
                await runner_task
            raise
        try:
            process = await runner_task
        except Exception as exc:  # Codex task runner boundary.
            raise PrototypeUiEngineerRunnerError(
                f"prototype UI engineer runtime failed: {exc}"
            ) from exc
        if activity_failure is not None:
            raise activity_failure
        return process

    async def _assert_no_source_edits(
        self,
        *,
        source_paths: tuple[str, ...],
        worktree_path: str,
        base_revision: str,
        baseline_head: str,
        baseline_status: str,
        baseline_diff: str,
        baseline_sources: dict[str, str | None],
    ) -> None:
        current_head = await self.worktree_manager.git.head_commit(worktree_path)
        current_status = await self.worktree_manager.git.status_porcelain(worktree_path)
        current_diff = await self.worktree_manager.git.worktree_diff(
            worktree_path,
            base_revision,
        )
        current_sources = self._source_path_snapshot(Path(worktree_path), source_paths)
        if (
            current_head != baseline_head
            or current_status != baseline_status
            or current_diff != baseline_diff
            or current_sources != baseline_sources
        ):
            raise PrototypeUiEngineerRunnerError(
                "prototype UI engineer modified project source"
            )

    @staticmethod
    def _source_path_snapshot(
        worktree: Path,
        source_paths: tuple[str, ...],
    ) -> dict[str, str | None]:
        root = worktree.resolve()
        snapshot: dict[str, str | None] = {}
        for relative_text in source_paths:
            relative = PurePosixPath(relative_text)
            if relative.is_absolute() or ".." in relative.parts or "\\" in relative_text:
                raise PrototypeUiEngineerRunnerError("prototype source path is unsafe")
            path = root.joinpath(*relative.parts)
            if path.is_symlink():
                raise PrototypeUiEngineerRunnerError(
                    "prototype source path contains a symlink"
                )
            if not path.exists():
                snapshot[relative_text] = None
                continue
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(root) or not resolved.is_file():
                raise PrototypeUiEngineerRunnerError(
                    "prototype source path is outside the worktree"
                )
            snapshot[relative_text] = hashlib.sha256(resolved.read_bytes()).hexdigest()
        return snapshot

    @staticmethod
    async def _emit_activity(
        callback: PrototypeUiEngineerActivityCallback | None,
        *,
        task_id: str,
        execution_process_id: str,
        output_chars: int,
        last_event_at: datetime,
    ) -> None:
        if callback is None:
            return
        try:
            await callback(
                PrototypeUiEngineerActivity(
                    phase="running",
                    task_id=task_id,
                    execution_process_id=execution_process_id,
                    output_chars=output_chars,
                    last_event_at=last_event_at,
                    occurred_at=datetime.now(),
                )
            )
        except Exception as exc:  # Caller persistence boundary.
            raise PrototypeUiEngineerRunnerError(
                "prototype UI engineer activity persistence failed"
            ) from exc
