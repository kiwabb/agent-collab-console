from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Literal, Protocol
from urllib.parse import urlparse
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.application import timeouts
from app.application.audit.recorders import record_event
from app.application.project_evidence_service import ProjectEvidenceError, ProjectEvidenceService
from app.application.prototype_service import is_complete_html_document
from app.application.runtime_catalog_service import (
    RuntimeCatalogService,
    RuntimeCatalogStore,
    RuntimeCatalogValidationError,
)
from app.application.task_statuses import is_task_success_status
from app.application.worktree_manager import WorktreeError
from app.domain.models import CodexSession, CodexTask, ExecutionProcess, LogEvent, Project
from app.domain.project_evidence import ProjectSurfaceManifest
from app.json_safety import parse_json_object

logger = logging.getLogger(__name__)

PROTOTYPE_ARTIFACT_SCHEMA_VERSION = "prototype-artifact/v1"
PROTOTYPE_ARTIFACT_MANIFEST_MAX_BYTES = 2_048
DEFAULT_ALLOWED_EXTERNAL_ORIGINS = frozenset(
    {
        "https://cdn.tailwindcss.com",
        "https://fonts.googleapis.com",
        "https://fonts.gstatic.com",
    }
)
_RUN_ITEM_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_PROTOTYPE_STAGING_PATH_MARKER = ".agent-collab/prototype-staging/"
_CSS_URL_RE = re.compile(
    r"url\(\s*['\"]?(https?://[^\s\"'<>\)]+)",
    re.IGNORECASE,
)
_SCRIPT_NETWORK_URL_RE = re.compile(
    r"(?:fetch|EventSource|WebSocket)\s*\(\s*['\"](https?://[^\s\"'<>\)]+)",
    re.IGNORECASE,
)
_NON_FETCH_URL_PREFIXES = (
    "http://www.w3.org/1999/xlink",
    "http://www.w3.org/2000/svg",
)
_URL_ATTRIBUTES = frozenset({"action", "formaction", "poster", "src", "srcset"})
_FETCH_HREF_TAGS = frozenset({"base", "link"})

PrototypeArtifactPhase = Literal[
    "preparing",
    "worktree_ready",
    "running",
    "validating",
    "complete",
]


class PrototypeArtifactError(RuntimeError):
    """A generation or artifact-contract failure safe to surface to the run."""


class PrototypeArtifactManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal["prototype-artifact/v1"]
    artifact_path: str
    sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    byte_size: int = Field(gt=0)


@dataclass(frozen=True)
class PrototypeArtifactRequest:
    # Candidate identity and source paths are integrity guards only. Prompt
    # construction accepts explicit agent-facing fields, never this object.
    project: Project
    run_item_id: str
    candidate_id: str
    source_hash: str
    title: str
    workspace_id: str | None = None
    output_locale: str = "zh-CN"
    source_paths: tuple[str, ...] = ()
    target_routes: tuple[str, ...] = ()


@dataclass(frozen=True)
class PrototypeArtifactActivity:
    phase: PrototypeArtifactPhase
    task_id: str | None
    execution_process_id: str | None
    output_chars: int | None
    last_event_at: datetime | None
    occurred_at: datetime


@dataclass(frozen=True)
class PrototypeArtifactResult:
    task_id: str
    execution_process_id: str
    html: str
    manifest: PrototypeArtifactManifest


@dataclass(frozen=True)
class PrototypeScopedTaskResult:
    task_id: str
    execution_process_id: str
    assistant_result: str


@dataclass(frozen=True)
class ValidatedPrototypeArtifact:
    manifest: PrototypeArtifactManifest
    html: str
    path: Path


PrototypeArtifactActivityCallback = Callable[[PrototypeArtifactActivity], Awaitable[None]]
PrototypeScopedTaskCompletionCallback = Callable[[Path, str, str], Awaitable[None]]
ClaudeAvailabilityProbe = Callable[[], bool]


class PrototypeArtifactStore(RuntimeCatalogStore, Protocol):
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


class PrototypeArtifactTaskRunner(Protocol):
    async def start_task_run(
        self,
        task: CodexTask,
        *,
        wait_for_completion: bool = False,
        execution_started_callback: Callable[[CodexTask, ExecutionProcess], Awaitable[None]]
        | None = None,
        command_args_override: list[str] | None = None,
    ) -> ExecutionProcess: ...


class PrototypeArtifactGitInspector(Protocol):
    async def status_porcelain(self, worktree_path: str | Path) -> str: ...

    async def worktree_diff(self, worktree_path: str | Path, base_branch: str) -> str: ...

    async def head_commit(self, worktree_path: str | Path) -> str: ...


class PrototypeArtifactWorktreeManager(Protocol):
    @property
    def git(self) -> PrototypeArtifactGitInspector: ...

    async def prepare_prototype_worktree(
        self,
        project: Project,
        run_item_id: str,
        *,
        source_paths: tuple[str, ...] = (),
    ) -> tuple[str, str, str]: ...

    async def cleanup_prototype_worktree(
        self,
        project: Project,
        run_item_id: str,
    ) -> None: ...


class PrototypeArtifactEvidenceScanner(Protocol):
    def scan_project(self, project: Project) -> ProjectSurfaceManifest: ...


class _HtmlUrlCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.urls: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        normalized_tag = tag.lower()
        for name, value in attrs:
            normalized_name = name.lower()
            if value is None or (
                normalized_name not in _URL_ATTRIBUTES
                and not (normalized_name == "href" and normalized_tag in _FETCH_HREF_TAGS)
            ):
                continue
            if normalized_name == "srcset":
                self.urls.extend(
                    part.strip().split(maxsplit=1)[0] for part in value.split(",") if part.strip()
                )
            else:
                self.urls.append(value.strip())

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self.handle_starttag(tag, attrs)


def prototype_staging_relative_path(run_item_id: str) -> str:
    if not _RUN_ITEM_ID_RE.fullmatch(run_item_id):
        raise PrototypeArtifactError("prototype run item id is not filesystem-safe")
    return f"{_PROTOTYPE_STAGING_PATH_MARKER}{run_item_id}/index.html"


def validate_prototype_artifact(
    *,
    worktree_path: str | Path,
    expected_artifact_path: str,
    manifest_text: str,
    max_bytes: int,
    allowed_external_origins: frozenset[str] = DEFAULT_ALLOWED_EXTERNAL_ORIGINS,
) -> ValidatedPrototypeArtifact:
    """Validate the strict manifest and its staged HTML file."""
    if len(manifest_text.encode("utf-8")) > PROTOTYPE_ARTIFACT_MANIFEST_MAX_BYTES:
        raise PrototypeArtifactError("prototype UI engineer manifest exceeds the size limit")
    payload = parse_json_object(manifest_text)
    if payload is None:
        raise PrototypeArtifactError("prototype UI engineer returned invalid manifest JSON")
    try:
        manifest = PrototypeArtifactManifest.model_validate(payload)
    except ValidationError as exc:
        raise PrototypeArtifactError("prototype UI engineer returned an invalid manifest") from exc

    relative = PurePosixPath(manifest.artifact_path)
    if (
        relative.is_absolute()
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
        or "\\" in manifest.artifact_path
    ):
        raise PrototypeArtifactError("prototype artifact path is unsafe")
    if manifest.artifact_path != expected_artifact_path:
        raise PrototypeArtifactError("prototype artifact path does not match the run staging path")

    root_input = Path(worktree_path)
    if root_input.is_symlink():
        raise PrototypeArtifactError("prototype worktree path is a symlink")
    try:
        root = root_input.resolve(strict=True)
    except OSError as exc:
        raise PrototypeArtifactError("prototype worktree is unavailable") from exc

    candidate = root.joinpath(*relative.parts)
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise PrototypeArtifactError("prototype artifact path contains a symlink")
    try:
        resolved_candidate = candidate.resolve(strict=True)
    except OSError as exc:
        raise PrototypeArtifactError("prototype artifact file is missing") from exc
    if not resolved_candidate.is_relative_to(root) or not resolved_candidate.is_file():
        raise PrototypeArtifactError("prototype artifact is outside its worktree boundary")

    run_directory_entries = list(resolved_candidate.parent.iterdir())
    if run_directory_entries != [resolved_candidate]:
        raise PrototypeArtifactError("prototype staging directory contains unexpected files")

    try:
        raw = resolved_candidate.read_bytes()
    except OSError as exc:
        raise PrototypeArtifactError("prototype artifact could not be read") from exc
    if len(raw) > max_bytes:
        raise PrototypeArtifactError(f"prototype artifact exceeds the {max_bytes}-byte size limit")
    if manifest.byte_size != len(raw):
        raise PrototypeArtifactError("prototype artifact byte size does not match its manifest")
    try:
        html = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise PrototypeArtifactError("prototype artifact is not valid UTF-8") from exc
    if not is_complete_html_document(html):
        raise PrototypeArtifactError("prototype artifact is not a complete HTML document")

    checksum = "sha256:" + hashlib.sha256(raw).hexdigest()
    if manifest.sha256 != checksum:
        raise PrototypeArtifactError("prototype artifact checksum does not match its manifest")
    _validate_external_urls(html, allowed_external_origins)
    return ValidatedPrototypeArtifact(manifest=manifest, html=html, path=resolved_candidate)


def _validate_external_urls(html: str, allowed_origins: frozenset[str]) -> None:
    collector = _HtmlUrlCollector()
    collector.feed(html)
    urls = [
        *collector.urls,
        *_CSS_URL_RE.findall(html),
        *_SCRIPT_NETWORK_URL_RE.findall(html),
    ]
    for raw_url in urls:
        value = raw_url.strip()
        if value.startswith(_NON_FETCH_URL_PREFIXES):
            continue
        if not value or (value.startswith(("#", "/")) and not value.startswith("//")):
            continue
        parsed = urlparse(f"https:{value}" if value.startswith("//") else value)
        scheme = parsed.scheme.lower()
        if not scheme:
            continue
        if scheme in {"mailto", "tel"}:
            continue
        if scheme == "data" and value.lower().startswith("data:image/"):
            continue
        if scheme not in {"http", "https"}:
            raise PrototypeArtifactError(f"prototype artifact uses forbidden URL scheme: {scheme}")
        origin = f"{scheme}://{parsed.netloc.lower()}"
        if origin not in allowed_origins:
            raise PrototypeArtifactError(
                f"prototype artifact uses a non-whitelisted external origin: {origin}"
            )


class PrototypeArtifactGenerator:
    """Run a Claude Code UI engineer and validate its staged HTML artifact."""

    def __init__(
        self,
        *,
        store: PrototypeArtifactStore,
        task_runner: PrototypeArtifactTaskRunner,
        worktree_manager: PrototypeArtifactWorktreeManager,
        claude_availability_probe: ClaudeAvailabilityProbe,
        evidence_scanner: PrototypeArtifactEvidenceScanner | None = None,
        max_artifact_bytes: int | None = None,
        allowed_external_origins: frozenset[str] = DEFAULT_ALLOWED_EXTERNAL_ORIGINS,
    ) -> None:
        self.store = store
        self.task_runner = task_runner
        self.worktree_manager = worktree_manager
        self.claude_availability_probe = claude_availability_probe
        self.evidence_scanner = evidence_scanner or ProjectEvidenceService()
        self.max_artifact_bytes = (
            max_artifact_bytes
            if max_artifact_bytes is not None
            else timeouts.prototype_artifact_max_bytes()
        )
        if self.max_artifact_bytes < 1:
            raise ValueError("max_artifact_bytes must be positive")
        self.allowed_external_origins = allowed_external_origins
        self._workspace_locks: dict[str, asyncio.Lock] = {}

    async def plan(
        self,
        *,
        project: Project,
        plan_id: str,
        prompt: str,
        source_paths: tuple[str, ...],
        activity_callback: PrototypeArtifactActivityCallback | None = None,
        mcp_config: str | None = None,
    ) -> str | None:
        """Run prototype planning through the same isolated Claude UI engineer."""
        result = await self.execute_scoped_task(
            project=project,
            scope_id=plan_id,
            prompt=prompt,
            source_paths=source_paths,
            phase="prototype_planning",
            task_kind="prototype_planning",
            task_title=f"Analyze prototype plan: {project.name}",
            task_id=f"prototype-ui-plan-task-{uuid4().hex}",
            activity_callback=activity_callback,
            mcp_config=mcp_config,
        )
        return result.assistant_result

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
        activity_callback: PrototypeArtifactActivityCallback | None = None,
        completion_callback: PrototypeScopedTaskCompletionCallback | None = None,
        mcp_config: str | None = None,
    ) -> PrototypeScopedTaskResult:
        """Run one fresh Claude task in an isolated prototype worktree."""
        await self.ensure_available()
        workspace = await self._ensure_workspace(project)
        prepared = False
        try:
            (
                branch,
                worktree_path,
                base_revision,
            ) = await self.worktree_manager.prepare_prototype_worktree(
                project,
                scope_id,
                source_paths=source_paths,
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
            execution_process = await self._run_task_with_activity(
                task,
                activity_callback,
                command_args_override=(
                    ["--mcp-config", mcp_config, "--strict-mcp-config"] if mcp_config else None
                ),
            )
            finished_task = await self.store.load_codex_task(task.id)
            if finished_task is None:
                raise PrototypeArtifactError("prototype UI engineer scoped task disappeared")
            if not is_task_success_status(finished_task.status):
                detail = (finished_task.result or "task did not complete").strip()
                raise PrototypeArtifactError(f"prototype UI engineer scoped task failed: {detail}")
            if finished_task.last_execution_process_id != execution_process.id:
                raise PrototypeArtifactError(
                    "prototype UI engineer scoped process correlation is inconsistent"
                )
            result = (finished_task.result or "").strip()
            if not result:
                raise PrototypeArtifactError("prototype UI engineer scoped task returned no result")
            if completion_callback is not None:
                await completion_callback(
                    Path(worktree_path),
                    task.id,
                    execution_process.id,
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
            return PrototypeScopedTaskResult(
                task_id=task.id,
                execution_process_id=execution_process.id,
                assistant_result=result,
            )
        finally:
            if prepared:
                try:
                    await self.worktree_manager.cleanup_prototype_worktree(project, scope_id)
                except (OSError, WorktreeError):
                    logger.warning(
                        "prototype scoped worktree cleanup failed: scope_id=%s",
                        scope_id,
                        exc_info=True,
                    )

    async def generate(
        self,
        request: PrototypeArtifactRequest,
        *,
        activity_callback: PrototypeArtifactActivityCallback | None = None,
    ) -> PrototypeArtifactResult:
        expected_path = prototype_staging_relative_path(request.run_item_id)
        await self._emit_activity(activity_callback, "preparing")
        await self.ensure_available()
        workspace = await self._ensure_workspace(
            request.project,
            workspace_id=request.workspace_id,
        )

        prepared = False
        task: CodexTask | None = None
        execution_process_id: str | None = None
        artifact: ValidatedPrototypeArtifact | None = None
        failure_code = "generation_setup_failed"
        try:
            (
                branch,
                worktree_path,
                base_revision,
            ) = await self.worktree_manager.prepare_prototype_worktree(
                request.project,
                request.run_item_id,
                source_paths=request.source_paths,
            )
            prepared = True
            await self._assert_source_fingerprint(request, worktree_path)
            await self._emit_activity(activity_callback, "worktree_ready")

            baseline_head = await self.worktree_manager.git.head_commit(worktree_path)
            baseline_status = await self.worktree_manager.git.status_porcelain(worktree_path)
            baseline_diff = await self.worktree_manager.git.worktree_diff(
                worktree_path,
                base_revision,
            )
            baseline_sources = self._source_path_snapshot(
                Path(worktree_path),
                request.source_paths,
            )

            now = datetime.now()
            task = CodexTask(
                id=f"prototype-ui-task-{uuid4().hex}",
                session_id=workspace.id,
                project_id=request.project.id,
                phase="prototype_generation",
                title=f"Restore prototype: {request.title}",
                prompt=self._build_prompt(
                    title=request.title,
                    target_routes=request.target_routes,
                    output_locale=request.output_locale,
                    artifact_path=expected_path,
                ),
                role="prototype_ui_engineer",
                executor="claude",
                provider=None,
                model=None,
                status="pending",
                task_kind="prototype_generation",
                workspace_path=worktree_path,
                git_branch=branch,
                git_base_branch=base_revision,
                git_worktree_path=worktree_path,
                created_at=now,
                updated_at=now,
            )
            await self._emit_activity(
                activity_callback,
                "running",
                task_id=task.id,
            )
            await self.store.save_codex_task(task)
            failure_code = "generation_failed"
            execution_process = await self._run_task_with_activity(
                task,
                activity_callback,
            )
            execution_process_id = execution_process.id

            finished_task = await self.store.load_codex_task(task.id)
            if finished_task is None:
                raise PrototypeArtifactError("prototype UI engineer task disappeared")
            if not is_task_success_status(finished_task.status):
                detail = (finished_task.result or "task did not complete").strip()
                raise PrototypeArtifactError(f"prototype UI engineer failed: {detail}")
            if finished_task.last_execution_process_id != execution_process.id:
                raise PrototypeArtifactError(
                    "prototype UI engineer execution process correlation is inconsistent"
                )
            manifest_text = (finished_task.result or "").strip()
            if not manifest_text:
                raise PrototypeArtifactError("prototype UI engineer returned no manifest")
            if manifest_text.startswith("API Error:"):
                raise PrototypeArtifactError(f"prototype UI engineer failed: {manifest_text}")

            failure_code = "artifact_validation_failed"
            await self._emit_activity(
                activity_callback,
                "validating",
                task_id=task.id,
                execution_process_id=execution_process.id,
            )
            artifact = validate_prototype_artifact(
                worktree_path=worktree_path,
                expected_artifact_path=expected_path,
                manifest_text=manifest_text,
                max_bytes=self.max_artifact_bytes,
                allowed_external_origins=self.allowed_external_origins,
            )
            self._remove_staging_artifact(artifact.path, Path(worktree_path))
            failure_code = "source_integrity_failed"
            await self._assert_no_source_edits(
                source_paths=request.source_paths,
                worktree_path=worktree_path,
                base_revision=base_revision,
                baseline_head=baseline_head,
                baseline_status=baseline_status,
                baseline_diff=baseline_diff,
                baseline_sources=baseline_sources,
            )
            failure_code = "completion_notification_failed"
            await self._emit_activity(
                activity_callback,
                "complete",
                task_id=task.id,
                execution_process_id=execution_process.id,
                output_chars=len(artifact.html),
            )
            self._record_artifact_validation(
                task_id=task.id,
                execution_process_id=execution_process.id,
                artifact_path=expected_path,
                sha256=artifact.manifest.sha256,
                byte_size=artifact.manifest.byte_size,
                validation_result="passed",
                error=None,
            )
            return PrototypeArtifactResult(
                task_id=task.id,
                execution_process_id=execution_process.id,
                html=artifact.html,
                manifest=artifact.manifest,
            )
        except asyncio.CancelledError:
            if task is not None:
                self._record_artifact_validation(
                    task_id=task.id,
                    execution_process_id=execution_process_id or task.last_execution_process_id,
                    artifact_path=expected_path,
                    sha256=artifact.manifest.sha256 if artifact is not None else None,
                    byte_size=artifact.manifest.byte_size if artifact is not None else None,
                    validation_result="failed",
                    error="generation_cancelled",
                )
            raise
        except Exception:
            if task is not None:
                self._record_artifact_validation(
                    task_id=task.id,
                    execution_process_id=execution_process_id or task.last_execution_process_id,
                    artifact_path=expected_path,
                    sha256=artifact.manifest.sha256 if artifact is not None else None,
                    byte_size=artifact.manifest.byte_size if artifact is not None else None,
                    validation_result="failed",
                    error=failure_code,
                )
            raise
        finally:
            if prepared:
                try:
                    await self.worktree_manager.cleanup_prototype_worktree(
                        request.project,
                        request.run_item_id,
                    )
                except (OSError, WorktreeError):
                    logger.warning(
                        "prototype worktree cleanup failed: run_item_id=%s",
                        request.run_item_id,
                        exc_info=True,
                    )

    @staticmethod
    def _record_artifact_validation(
        *,
        task_id: str,
        execution_process_id: str | None,
        artifact_path: str,
        sha256: str | None,
        byte_size: int | None,
        validation_result: Literal["passed", "failed"],
        error: str | None,
    ) -> None:
        # Keep this payload as an explicit metadata allowlist. In particular,
        # runtime exceptions can contain prompts, commands, tool output, or HTML.
        record_event(
            {
                "type": "prototype_artifact_validation",
                "payload": {
                    "task_id": task_id,
                    "execution_process_id": execution_process_id,
                    "artifact_path": artifact_path,
                    "sha256": sha256,
                    "byte_size": byte_size,
                    "status": validation_result,
                    "validation_result": validation_result,
                    "error": error,
                },
            }
        )

    async def ensure_available(self) -> None:
        """Fail closed unless Runtime Catalog resolves the Claude executor."""
        if not timeouts.codex_launch_enabled():
            raise PrototypeArtifactError("prototype UI engineer runtime launch is disabled")
        service = RuntimeCatalogService(self.store)
        try:
            catalog = await service.load_catalog()
        except Exception as exc:  # Runtime Catalog persistence boundary.
            raise PrototypeArtifactError(
                "prototype UI engineer runtime catalog is unavailable"
            ) from exc
        executor = next((item for item in catalog.executors if item.id == "claude"), None)
        if executor is None or not executor.enabled or executor.executor_type != "claude":
            raise PrototypeArtifactError(
                "prototype UI engineer requires an enabled Claude executor"
            )
        try:
            resolved = service.resolve_effective_config(catalog, "claude")
        except RuntimeCatalogValidationError as exc:
            raise PrototypeArtifactError(
                "prototype UI engineer Claude runtime is not configured"
            ) from exc
        if resolved[0] != "claude" or resolved[4] != "claude":
            raise PrototypeArtifactError("prototype UI engineer resolved to a non-Claude executor")
        try:
            available = await asyncio.to_thread(self.claude_availability_probe)
        except Exception as exc:  # Existing runtime availability probe boundary.
            raise PrototypeArtifactError(
                "prototype UI engineer Claude CLI availability could not be checked"
            ) from exc
        if not available:
            raise PrototypeArtifactError(
                "prototype UI engineer requires an available Claude CLI command"
            )

    async def _ensure_workspace(
        self,
        project: Project,
        *,
        workspace_id: str | None = None,
    ) -> CodexSession:
        lock = self._workspace_locks.setdefault(project.id, asyncio.Lock())
        async with lock:
            if workspace_id is not None:
                existing = await self.store.load_codex_workspace(workspace_id)
                if existing is not None:
                    if existing.project_id != project.id:
                        raise PrototypeArtifactError(
                            "prototype workspace belongs to a different project"
                        )
                    return existing

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
                id=workspace_id or f"prototype-workspace-{uuid4().hex}",
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
        callback: PrototypeArtifactActivityCallback | None,
        command_args_override: list[str] | None = None,
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
                "running",
                task_id=started_task.id,
                execution_process_id=process.id,
                output_chars=0,
                last_event_at=datetime.now(),
            )

        if command_args_override is not None:
            runner_task = asyncio.create_task(
                self.task_runner.start_task_run(
                    task,
                    wait_for_completion=True,
                    execution_started_callback=execution_started,
                    command_args_override=command_args_override,
                )
            )
        else:
            runner_task = asyncio.create_task(
                self.task_runner.start_task_run(
                    task,
                    wait_for_completion=True,
                    execution_started_callback=execution_started,
                )
            )
        activity_failure: PrototypeArtifactError | None = None
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
                            "running",
                            task_id=task.id,
                            execution_process_id=execution_process_id,
                            output_chars=output_chars,
                            last_event_at=last_event_at,
                        )
                        last_output_chars = output_chars
                except PrototypeArtifactError as exc:
                    activity_failure = exc
                except Exception as exc:  # External log-store boundary; fail after runtime cleanup.
                    logger.exception(
                        "prototype runtime activity read failed: task_id=%s process_id=%s",
                        task.id,
                        execution_process_id,
                    )
                    activity_failure = PrototypeArtifactError(
                        f"prototype runtime activity could not be read: {exc}"
                    )
        except asyncio.CancelledError:
            # Do not let generate() remove the worktree under a live Claude
            # process. The runtime owns termination/timeout and must finish its
            # cleanup before cancellation reaches the generator's finally.
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
        except Exception as exc:
            raise PrototypeArtifactError(f"prototype UI engineer runtime failed: {exc}") from exc
        if activity_failure is not None:
            raise activity_failure
        return process

    async def _assert_source_fingerprint(
        self,
        request: PrototypeArtifactRequest,
        worktree_path: str,
    ) -> None:
        isolated_project = request.project.model_copy(update={"repo_path": worktree_path})
        try:
            manifest = await asyncio.to_thread(
                self.evidence_scanner.scan_project,
                isolated_project,
            )
        except ProjectEvidenceError as exc:
            raise PrototypeArtifactError("isolated prototype source could not be verified") from exc
        candidate = next(
            (item for item in manifest.candidates if item.candidate_id == request.candidate_id),
            None,
        )
        if candidate is not None and candidate.source_hash == request.source_hash:
            return
        if candidate is None:
            snapshot = self._source_path_snapshot(Path(worktree_path), request.source_paths)
            if all(checksum is not None for checksum in snapshot.values()):
                hash_input = "\n".join(f"{path}|{snapshot[path]}" for path in sorted(snapshot))
                source_hash = "sha256:" + hashlib.sha256(hash_input.encode()).hexdigest()
                if source_hash == request.source_hash:
                    return
        if candidate is None or candidate.source_hash != request.source_hash:
            raise PrototypeArtifactError(
                "isolated prototype source fingerprint does not match the reviewed plan"
            )

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
        current_sources = self._source_path_snapshot(
            Path(worktree_path),
            source_paths,
        )
        if (
            current_head != baseline_head
            or current_status != baseline_status
            or current_diff != baseline_diff
            or current_sources != baseline_sources
        ):
            raise PrototypeArtifactError(
                "prototype UI engineer modified project source outside its staging directory"
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
                raise PrototypeArtifactError("prototype source path is unsafe")
            path = root.joinpath(*relative.parts)
            if path.is_symlink():
                raise PrototypeArtifactError("prototype source path contains a symlink")
            if not path.exists():
                snapshot[relative_text] = None
                continue
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(root) or not resolved.is_file():
                raise PrototypeArtifactError("prototype source path is outside the worktree")
            snapshot[relative_text] = hashlib.sha256(resolved.read_bytes()).hexdigest()
        return snapshot

    @staticmethod
    def _remove_staging_artifact(artifact_path: Path, worktree: Path) -> None:
        root = worktree.resolve()
        resolved = artifact_path.resolve(strict=True)
        if not resolved.is_relative_to(root):
            raise PrototypeArtifactError("prototype staging cleanup escaped the worktree")
        try:
            resolved.unlink()
            resolved.parent.rmdir()
        except OSError as exc:
            raise PrototypeArtifactError("prototype staging artifact could not be cleaned") from exc
        for parent in (resolved.parent.parent, resolved.parent.parent.parent):
            with suppress(OSError):
                parent.rmdir()

    @staticmethod
    def _build_prompt(
        *,
        title: str,
        target_routes: tuple[str, ...],
        output_locale: str,
        artifact_path: str,
    ) -> str:
        routes = json.dumps(target_routes, ensure_ascii=False)
        return (
            "You are the prototype UI engineer. Restore the target page from the real project "
            "source in this worktree. Do not redesign or optimize it.\n"
            "Preserve the source page's existing visible copy and language exactly. Use locale "
            f"{output_locale} only for unavoidable new placeholder copy; keep source paths "
            "and source excerpts unchanged.\n"
            f"Page title: {title}\n"
            f"Target routes: {routes}\n\n"
            "Discover the implementation yourself from the repository. Locate the router entries "
            "for the target routes, follow their imports to the rendered page components, and inspect "
            "the shared layout, navigation, styles, design tokens, and assets that affect the page. "
            "Search and read any project files you need; no precomputed source-file list is provided. "
            "Use Glob, Grep, Read, Bash, or other available tools as you judge appropriate.\n"
            "When the restored page contains internal navigation, use the actual route paths you "
            "discover in the project in real anchor href values. For non-anchor navigation controls, "
            "set data-prototype-route to the discovered route path. Do not replace a known internal "
            'route with href="#" or a no-op click handler. Keep external-link labels, but replace '
            'external http/https destinations with href="#" because the sandbox does not allow '
            "external origins.\n\n"
            "Create one complete, "
            "self-contained UTF-8 HTML document with inline CSS and JavaScript. Allowed external "
            "origins are https://cdn.tailwindcss.com, https://fonts.googleapis.com, and "
            "https://fonts.gstatic.com; do not add any other resource origins. Do not modify, format, commit, or create "
            "any project source file. Keep the prototype compact: reproduce layouts, interactions, "
            "and visible states with representative sample rows instead of copying complete source "
            "datasets.\n"
            f"Write the HTML only to {artifact_path}. Use any available tools you judge appropriate "
            "to create, inspect, and revise that file; the backend validates the final artifact rather "
            "than your tool sequence. Leave the completed staged file in place and do not include its "
            "HTML in the final assistant response.\n\n"
            "After writing it, compute its exact byte count and SHA-256 checksum. Your final response "
            f"must be only this compact raw JSON manifest (under "
            f"{PROTOTYPE_ARTIFACT_MANIFEST_MAX_BYTES} UTF-8 bytes), with no markdown and never the HTML:\n"
            '{"schema_version":"prototype-artifact/v1","artifact_path":"'
            + artifact_path
            + '","sha256":"sha256:<64 lowercase hex chars>","byte_size":<integer>}'
        )

    @staticmethod
    async def _emit_activity(
        callback: PrototypeArtifactActivityCallback | None,
        phase: PrototypeArtifactPhase,
        *,
        task_id: str | None = None,
        execution_process_id: str | None = None,
        output_chars: int | None = None,
        last_event_at: datetime | None = None,
    ) -> None:
        if callback is None:
            return
        try:
            await callback(
                PrototypeArtifactActivity(
                    phase=phase,
                    task_id=task_id,
                    execution_process_id=execution_process_id,
                    output_chars=output_chars,
                    last_event_at=last_event_at,
                    occurred_at=datetime.now(),
                )
            )
        except Exception as exc:
            raise PrototypeArtifactError(
                f"prototype activity persistence failed during {phase}"
            ) from exc
