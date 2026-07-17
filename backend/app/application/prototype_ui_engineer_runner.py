from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Literal, Protocol
from uuid import uuid4

from app.adapters.prototype_object_store import canonical_json_bytes
from app.application import timeouts
from app.application.codex_task_runner import (
    CodexTaskExecutionTerminalEvidence,
    CodexTaskWireInputEvidence,
    ExecutionTerminalCallback,
    WireInputReadyCallback,
)
from app.application.runtime_catalog_service import (
    RuntimeCatalogService,
    RuntimeCatalogStore,
    RuntimeCatalogValidationError,
)
from app.application.task_statuses import is_task_success_status
from app.application.worktree_manager import WorktreeError
from app.domain.models import CodexSession, CodexTask, ExecutionProcess, LogEvent, Project
from app.domain.structured_prototype_generation import PrototypeGenerationSourceSnapshot

logger = logging.getLogger(__name__)

PrototypeUiEngineerPhase = Literal["running"]
_CLAUDE_ADAPTER_VERSION = "claude-process-runtime/v1"


class PrototypeUiEngineerRunnerError(RuntimeError):
    """A Claude UI engineer execution failure safe to surface to its caller."""


class PrototypeUiEngineerInstrumentationError(PrototypeUiEngineerRunnerError):
    """Caller-owned durable instrumentation refused the next runtime effect."""


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


@dataclass(frozen=True, slots=True)
class PrototypeUiEngineerRuntimeProfile:
    runtime_profile_id: str
    runtime_profile_hash: str
    executor: str
    runtime_binary: str
    runtime_binary_hash: str
    adapter_config_hash: str
    executor_adapter_version: str


@dataclass(frozen=True, slots=True)
class PrototypeUiEngineerTaskCreatedEvidence:
    task: CodexTask
    task_id: str
    workspace_id: str
    worktree_path: str
    repository_root: str
    worktree_path_contained: Literal[True]
    worktree_base_commit: str
    source_snapshot_ref: str | None
    source_fingerprint: str | None
    runtime_profile: PrototypeUiEngineerRuntimeProfile


@dataclass(frozen=True, slots=True)
class PrototypeUiEngineerProcessStartedEvidence:
    task: CodexTask
    process: ExecutionProcess


PrototypeUiEngineerInstrumentationEvidence = (
    PrototypeUiEngineerTaskCreatedEvidence
    | CodexTaskWireInputEvidence
    | PrototypeUiEngineerProcessStartedEvidence
    | CodexTaskExecutionTerminalEvidence
)


PrototypeUiEngineerActivityCallback = Callable[[PrototypeUiEngineerActivity], Awaitable[None]]
PrototypeUiEngineerPreparedCallback = Callable[[Path, str], Awaitable[None]]
PrototypeUiEngineerReleaseCallback = Callable[[], Awaitable[None]]
PrototypeUiEngineerCompletionCallback = Callable[[Path, str, str], Awaitable[None]]
PrototypeUiEngineerTaskCreatedCallback = Callable[
    [PrototypeUiEngineerTaskCreatedEvidence], Awaitable[None]
]
PrototypeUiEngineerInstrumentationCallback = Callable[
    [PrototypeUiEngineerInstrumentationEvidence], Awaitable[None]
]
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
        wire_input_ready_callback: WireInputReadyCallback | None = None,
        execution_terminal_callback: ExecutionTerminalCallback | None = None,
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
        source_snapshot: PrototypeGenerationSourceSnapshot | None = None,
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
        source_snapshot: PrototypeGenerationSourceSnapshot | None = None,
        activity_callback: PrototypeUiEngineerActivityCallback | None = None,
        prepared_callback: PrototypeUiEngineerPreparedCallback | None = None,
        release_callback: PrototypeUiEngineerReleaseCallback | None = None,
        completion_callback: PrototypeUiEngineerCompletionCallback | None = None,
        task_created_callback: PrototypeUiEngineerTaskCreatedCallback | None = None,
        instrumentation_callback: PrototypeUiEngineerInstrumentationCallback | None = None,
        mcp_config: str | None = None,
    ) -> PrototypeUiEngineerScopedTaskResult:
        generation_task = task_kind in {
            "generation_blueprint",
            "generation_foundation",
            "generation_page",
        }
        if generation_task and prepared_callback is None:
            raise PrototypeUiEngineerRunnerError(
                "prototype generation requires a prepared repository scope callback"
            )
        if generation_task and release_callback is None:
            raise PrototypeUiEngineerRunnerError(
                "prototype generation requires a repository scope release callback"
            )
        if generation_task and task_created_callback is None and instrumentation_callback is None:
            raise PrototypeUiEngineerRunnerError(
                "prototype generation requires a durable instrumentation callback"
            )
        command_args = self._restricted_claude_args(task_kind, mcp_config)
        runtime_profile = self._runtime_profile(task_kind, mcp_config, command_args)
        await self.ensure_available()
        workspace = await self._ensure_workspace(project)
        prepared = False
        try:
            (
                branch,
                worktree_path,
                base_revision,
            ) = await self.worktree_manager.prepare_prototype_ui_engineer_worktree(
                project,
                scope_id,
                source_paths=source_paths,
                source_snapshot=source_snapshot,
            )
            prepared = True
            baseline_head = await self.worktree_manager.git.head_commit(worktree_path)
            if (
                source_snapshot is not None
                and baseline_head != source_snapshot.worktree_base_commit
            ):
                raise PrototypeUiEngineerRunnerError(
                    "prototype generation worktree does not match its frozen commit"
                )
            baseline_status = await self.worktree_manager.git.status_porcelain(worktree_path)
            baseline_diff = await self.worktree_manager.git.worktree_diff(
                worktree_path,
                base_revision,
            )
            baseline_sources = self._source_path_snapshot(Path(worktree_path), source_paths)
            if prepared_callback is not None:
                try:
                    await prepared_callback(Path(worktree_path), task_id)
                except Exception as exc:  # Task-scoped MCP preparation boundary.
                    raise PrototypeUiEngineerRunnerError(
                        "prototype UI engineer repository scope binding failed"
                    ) from exc

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
            resolved_worktree = Path(worktree_path).resolve(strict=True)
            if not resolved_worktree.is_dir():
                raise PrototypeUiEngineerRunnerError(
                    "prototype UI engineer repository root is not a directory"
                )
            if task.workspace_path != worktree_path or task.git_worktree_path != worktree_path:
                raise PrototypeUiEngineerRunnerError(
                    "prototype UI engineer task repository identity is inconsistent"
                )
            task_worktree = Path(worktree_path).resolve(strict=True)
            if not task_worktree.is_relative_to(resolved_worktree):
                raise PrototypeUiEngineerRunnerError(
                    "prototype UI engineer task escaped its repository root"
                )
            task_created_evidence = PrototypeUiEngineerTaskCreatedEvidence(
                task=task,
                task_id=task.id,
                workspace_id=workspace.id,
                worktree_path=str(task_worktree),
                repository_root=str(resolved_worktree),
                worktree_path_contained=True,
                worktree_base_commit=base_revision,
                source_snapshot_ref=(
                    source_snapshot.source_snapshot_ref if source_snapshot is not None else None
                ),
                source_fingerprint=(
                    source_snapshot.source_fingerprint if source_snapshot is not None else None
                ),
                runtime_profile=runtime_profile,
            )
            await self._emit_task_created(task_created_callback, task_created_evidence)
            await self._emit_instrumentation(
                instrumentation_callback,
                task_created_evidence,
            )
            process = await self._run_task_with_activity(
                task,
                activity_callback,
                instrumentation_callback,
                command_args_override=command_args,
            )
            finished_task = await self.store.load_codex_task(task.id)
            if finished_task is None:
                raise PrototypeUiEngineerRunnerError("prototype UI engineer task disappeared")
            if not is_task_success_status(finished_task.status):
                detail = (finished_task.result or "task did not complete").strip()
                raise PrototypeUiEngineerRunnerError(f"prototype UI engineer task failed: {detail}")
            if finished_task.last_execution_process_id != process.id:
                raise PrototypeUiEngineerRunnerError(
                    "prototype UI engineer process correlation is inconsistent"
                )
            result = (finished_task.result or "").strip()
            if completion_callback is None and not result:
                raise PrototypeUiEngineerRunnerError(
                    "prototype UI engineer task returned no result"
                )
            await self._assert_no_source_edits(
                source_paths=source_paths,
                worktree_path=worktree_path,
                base_revision=base_revision,
                baseline_head=baseline_head,
                baseline_status=baseline_status,
                baseline_diff=baseline_diff,
                baseline_sources=baseline_sources,
            )
            if completion_callback is not None:
                await completion_callback(Path(worktree_path), task.id, process.id)
            return PrototypeUiEngineerScopedTaskResult(
                task_id=task.id,
                execution_process_id=process.id,
                assistant_result=result,
            )
        finally:
            if prepared:
                release_failure: BaseException | None = None
                if release_callback is not None:
                    try:
                        await self._run_release_callback(release_callback)
                    except asyncio.CancelledError as exc:
                        release_failure = exc
                    except Exception as exc:  # Task-scoped MCP release boundary.
                        release_failure = exc
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
                if release_failure is not None:
                    raise release_failure

    @staticmethod
    async def _run_release_callback(callback: PrototypeUiEngineerReleaseCallback) -> None:
        release_task = asyncio.ensure_future(callback())
        try:
            await asyncio.shield(release_task)
        except asyncio.CancelledError as cancelled:
            while not release_task.done():
                try:
                    await asyncio.shield(release_task)
                except asyncio.CancelledError:
                    continue
            if not release_task.cancelled():
                release_task.result()
            raise cancelled

    @staticmethod
    def _restricted_claude_args(task_kind: str, mcp_config: str | None) -> list[str]:
        if mcp_config is None:
            raise PrototypeUiEngineerRunnerError(
                "prototype UI engineer requires a scoped MCP configuration"
            )
        if task_kind in {
            "generation_blueprint",
            "generation_foundation",
            "generation_page",
        }:
            built_in_tools = [""]
            allowed_tools = ["mcp__structured-prototype-generation__*"]
        elif task_kind == "conversation_edit":
            built_in_tools = [""]
            allowed_tools = ["mcp__structured-prototype-ai__*"]
        else:
            raise PrototypeUiEngineerRunnerError(
                "prototype UI engineer task kind has no restricted runtime profile"
            )
        args = [
            "--bare",
            "--setting-sources",
            "",
            "--disable-slash-commands",
            "--no-session-persistence",
            "--no-chrome",
            "--tools",
            *built_in_tools,
            "--allowedTools",
            *allowed_tools,
            "--mcp-config",
            mcp_config,
            "--strict-mcp-config",
        ]
        return args

    @staticmethod
    def _runtime_profile(
        task_kind: str,
        mcp_config: str | None,
        command_args: list[str],
    ) -> PrototypeUiEngineerRuntimeProfile:
        if mcp_config is None:
            raise PrototypeUiEngineerRunnerError(
                "prototype UI engineer requires a scoped MCP configuration"
            )
        claude_command = timeouts.claude_cmd().split()
        if not claude_command:
            raise PrototypeUiEngineerRunnerError(
                "prototype UI engineer Claude binary configuration is empty"
            )
        mcp_config_hash = "sha256:" + hashlib.sha256(mcp_config.encode("utf-8")).hexdigest()
        safe_args: list[str] = []
        redact_next = False
        for argument in command_args:
            if redact_next:
                safe_args.append(mcp_config_hash)
                redact_next = False
                continue
            safe_args.append(argument)
            redact_next = argument == "--mcp-config"
        if redact_next:
            raise PrototypeUiEngineerRunnerError(
                "prototype UI engineer MCP adapter configuration is incomplete"
            )
        binary_hash = "sha256:" + hashlib.sha256(canonical_json_bytes(claude_command)).hexdigest()
        adapter_config_hash = (
            "sha256:"
            + hashlib.sha256(
                canonical_json_bytes(
                    {
                        "adapterVersion": _CLAUDE_ADAPTER_VERSION,
                        "commandArgs": safe_args,
                        "mcpConfigHash": mcp_config_hash,
                    }
                )
            ).hexdigest()
        )
        runtime_profile_id = f"prototype-ui-engineer/{task_kind}/v1"
        profile_args = [
            "<scoped-mcp-config>" if argument == mcp_config else argument
            for argument in command_args
        ]
        runtime_profile_hash = (
            "sha256:"
            + hashlib.sha256(
                canonical_json_bytes(
                    {
                        "runtimeProfileId": runtime_profile_id,
                        "executor": "claude",
                        "runtimeBinaryHash": binary_hash,
                        "commandArgs": profile_args,
                        "executorAdapterVersion": _CLAUDE_ADAPTER_VERSION,
                    }
                )
            ).hexdigest()
        )
        return PrototypeUiEngineerRuntimeProfile(
            runtime_profile_id=runtime_profile_id,
            runtime_profile_hash=runtime_profile_hash,
            executor="claude",
            runtime_binary=claude_command[0],
            runtime_binary_hash=binary_hash,
            adapter_config_hash=adapter_config_hash,
            executor_adapter_version=_CLAUDE_ADAPTER_VERSION,
        )

    @classmethod
    def describe_runtime_profile(cls, task_kind: str) -> PrototypeUiEngineerRuntimeProfile:
        marker = "<scoped-generation-mcp-config>"
        command_args = cls._restricted_claude_args(task_kind, marker)
        return cls._runtime_profile(task_kind, marker, command_args)

    async def ensure_available(self) -> None:
        if not timeouts.codex_launch_enabled():
            raise PrototypeUiEngineerRunnerError("prototype UI engineer runtime launch is disabled")
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
        instrumentation_callback: PrototypeUiEngineerInstrumentationCallback | None,
        command_args_override: list[str] | None,
    ) -> ExecutionProcess:
        execution_process_id: str | None = None

        async def execution_started(
            started_task: CodexTask,
            process: ExecutionProcess,
        ) -> None:
            nonlocal execution_process_id
            execution_process_id = process.id
            await self._emit_instrumentation(
                instrumentation_callback,
                PrototypeUiEngineerProcessStartedEvidence(
                    task=started_task,
                    process=process,
                ),
            )
            await self._emit_activity(
                callback,
                task_id=started_task.id,
                execution_process_id=process.id,
                output_chars=0,
                last_event_at=datetime.now(),
            )

        async def wire_input_ready(evidence: CodexTaskWireInputEvidence) -> None:
            await self._emit_instrumentation(instrumentation_callback, evidence)

        async def execution_terminal(evidence: CodexTaskExecutionTerminalEvidence) -> None:
            await self._emit_instrumentation(instrumentation_callback, evidence)

        runner_task = asyncio.create_task(
            self.task_runner.start_task_run(
                task,
                wait_for_completion=True,
                execution_started_callback=execution_started,
                wire_input_ready_callback=wire_input_ready,
                execution_terminal_callback=execution_terminal,
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
        except PrototypeUiEngineerInstrumentationError:
            raise
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
            raise PrototypeUiEngineerRunnerError("prototype UI engineer modified project source")

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
                raise PrototypeUiEngineerRunnerError("prototype source path contains a symlink")
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
                    occurred_at=datetime.now(UTC),
                )
            )
        except Exception as exc:  # Caller persistence boundary.
            raise PrototypeUiEngineerRunnerError(
                "prototype UI engineer activity persistence failed"
            ) from exc

    @staticmethod
    async def _emit_instrumentation(
        callback: PrototypeUiEngineerInstrumentationCallback | None,
        evidence: PrototypeUiEngineerInstrumentationEvidence,
    ) -> None:
        if callback is None:
            return
        try:
            await callback(evidence)
        except Exception as exc:  # Caller-owned durable persistence boundary.
            raise PrototypeUiEngineerInstrumentationError(
                "prototype UI engineer instrumentation persistence failed"
            ) from exc

    @staticmethod
    async def _emit_task_created(
        callback: PrototypeUiEngineerTaskCreatedCallback | None,
        evidence: PrototypeUiEngineerTaskCreatedEvidence,
    ) -> None:
        if callback is None:
            return
        try:
            await callback(evidence)
        except Exception as exc:  # Caller-owned durable persistence boundary.
            raise PrototypeUiEngineerInstrumentationError(
                "prototype UI engineer task-created persistence failed"
            ) from exc
