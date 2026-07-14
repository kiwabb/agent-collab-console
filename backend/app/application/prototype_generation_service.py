from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime
from typing import Protocol
from uuid import uuid4

from app.application.audit.recorders import record_event
from app.application.project_evidence_service import ProjectEvidenceError, ProjectEvidenceService
from app.application.prototype_artifact_generator import (
    PrototypeArtifactActivity,
    PrototypeArtifactActivityCallback,
    PrototypeArtifactError,
    PrototypeArtifactRequest,
    PrototypeArtifactResult,
)
from app.application.prototype_version_artifacts import write_project_version
from app.domain.models import Project, Prototype, PrototypeVersion
from app.domain.project_evidence import ProjectSurfaceManifest
from app.domain.prototype_generation import (
    GenerationItemPhase,
    GenerationItemStatus,
    GenerationRunStatus,
    PrototypeGenerationRun,
    PrototypeGenerationRunFreezeResult,
    PrototypeGenerationRunItem,
)
from app.domain.prototype_plan import PlanOutputLocale, PrototypePlan, PrototypePlanItem

logger = logging.getLogger(__name__)


class PrototypeGenerationError(RuntimeError):
    """Expected generation gate or persistence error."""


class GenerationStore(Protocol):
    async def load_project(self, project_id: str) -> Project | None: ...
    async def list_prototypes(self, project_id: str) -> list[Prototype]: ...
    async def load_prototype_plan(
        self, plan_id: str
    ) -> tuple[PrototypePlan, list[PrototypePlanItem]] | None: ...
    async def load_prototype_generation_run(
        self, run_id: str
    ) -> tuple[PrototypeGenerationRun, list[PrototypeGenerationRunItem]] | None: ...
    async def find_active_prototype_generation_run(
        self, plan_id: str
    ) -> PrototypeGenerationRun | None: ...
    async def load_latest_prototype_generation_run_for_plan(
        self, plan_id: str
    ) -> tuple[PrototypeGenerationRun, list[PrototypeGenerationRunItem]] | None: ...
    async def freeze_prototype_generation_run(
        self,
        run: PrototypeGenerationRun,
        run_items: list[PrototypeGenerationRunItem],
        prototypes: list[Prototype],
        plan_items: list[PrototypePlanItem],
        seed_briefs: dict[str, str],
        *,
        reuse_terminal_run: bool = False,
    ) -> PrototypeGenerationRunFreezeResult: ...
    async def update_prototype_generation_item(
        self,
        run_id: str,
        item_id: str,
        *,
        status: GenerationItemStatus,
        phase: GenerationItemPhase | None = None,
        output_chars: int | None = None,
        last_event_at: datetime | None = None,
        status_message: str | None = None,
        task_id: str | None = None,
        execution_process_id: str | None = None,
        error_message: str | None = None,
        attempt: int | None = None,
    ) -> None: ...
    async def update_prototype_generation_run(
        self,
        run_id: str,
        *,
        status: GenerationRunStatus,
        error_message: str | None = None,
    ) -> None: ...
    async def complete_prototype_generation_item(
        self,
        run_id: str,
        item_id: str,
        version: PrototypeVersion,
        *,
        source_hash: str,
        source_meta_json: str,
        output_chars: int | None = None,
        last_event_at: datetime | None = None,
        status_message: str = "",
        task_id: str | None = None,
        execution_process_id: str | None = None,
    ) -> PrototypeVersion: ...
    async def load_prototype_version(
        self, prototype_id: str, version_no: int
    ) -> PrototypeVersion | None: ...


class EvidenceScanner(Protocol):
    def scan_project(self, project: Project) -> ProjectSurfaceManifest: ...


GovernanceGate = Callable[[int], Awaitable[None]]


class PrototypeArtifactGeneratorLike(Protocol):
    async def ensure_available(self) -> None: ...

    async def generate(
        self,
        request: PrototypeArtifactRequest,
        *,
        activity_callback: PrototypeArtifactActivityCallback | None = None,
    ) -> PrototypeArtifactResult: ...


class PrototypeGenerationService:
    TERMINAL_STATUSES = frozenset({"completed", "partial", "failed", "interrupted"})

    def __init__(
        self,
        *,
        store: GenerationStore,
        evidence_service: EvidenceScanner | None = None,
        governance_gate: GovernanceGate | None = None,
        artifact_generator: PrototypeArtifactGeneratorLike | None = None,
        concurrency: int = 2,
        global_concurrency: int = 2,
    ) -> None:
        self.store = store
        self.evidence_service = evidence_service or ProjectEvidenceService()
        self.governance_gate = governance_gate
        self.artifact_generator = artifact_generator
        self.concurrency = max(1, min(concurrency, 2))
        self._global_semaphore = asyncio.Semaphore(max(1, global_concurrency))
        self._tasks: set[asyncio.Task[None]] = set()
        self._plan_locks: dict[str, asyncio.Lock] = {}

    async def create_run(
        self,
        plan_id: str,
        *,
        expected_updated_at: str | None = None,
    ) -> PrototypeGenerationRun:
        lock = self._plan_locks.setdefault(plan_id, asyncio.Lock())
        async with lock:
            latest = await self.store.load_latest_prototype_generation_run_for_plan(plan_id)
            if latest is not None and latest[0].status in {"queued", "running"}:
                return latest[0]
            return await self._create_run(
                plan_id,
                expected_updated_at=expected_updated_at,
                item_ids=None,
                # Preserve cross-instance idempotence when two requests begin
                # before either freezes a run. A terminal run that already
                # existed at request start must not block a new generation.
                reuse_terminal_run=latest is None,
            )

    async def _create_run(
        self,
        plan_id: str,
        *,
        expected_updated_at: str | None = None,
        item_ids: set[str] | None,
        reuse_terminal_run: bool,
    ) -> PrototypeGenerationRun:
        loaded = await self.store.load_prototype_plan(plan_id)
        if loaded is None:
            raise PrototypeGenerationError(f"prototype plan not found: {plan_id}")
        plan, items = loaded
        if plan.status != "ready":
            raise PrototypeGenerationError(f"plan is not ready: {plan.status}")
        if (
            expected_updated_at
            and plan.updated_at
            and plan.updated_at.isoformat() != expected_updated_at
        ):
            raise PrototypeGenerationError("prototype plan changed; refresh before generating")
        project = await self.store.load_project(plan.project_id)
        if project is None:
            raise PrototypeGenerationError(f"project not found: {plan.project_id}")
        try:
            manifest = await asyncio.to_thread(self.evidence_service.scan_project, project)
        except ProjectEvidenceError as exc:
            raise PrototypeGenerationError(f"project evidence unavailable: {exc}") from exc
        if manifest.repository_fingerprint != plan.repository_fingerprint:
            raise PrototypeGenerationError("project evidence is stale; analyze the project again")
        selected = [
            item
            for item in items
            if (item.selected if item_ids is None else item.id in item_ids)
            and item.action in {"create", "update"}
            and item.surface_kind != "browser-extension"
        ]
        if not selected:
            raise PrototypeGenerationError("no selected candidates are eligible for generation")
        await self._check_gates(len(selected))
        existing = await self.store.list_prototypes(plan.project_id)
        existing_by_ref = {
            prototype.source_ref: prototype
            for prototype in existing
            if prototype.source_kind == "code" and prototype.source_ref
        }
        now = datetime.now()
        run_id = f"prototype-generation-run-{uuid4().hex}"
        run = PrototypeGenerationRun(
            id=run_id,
            plan_id=plan.id,
            project_id=plan.project_id,
            status="queued",
            repository_fingerprint=plan.repository_fingerprint,
            total=len(selected),
            pending=len(selected),
            created_at=now,
            updated_at=now,
        )
        prototypes: list[Prototype] = []
        run_items: list[PrototypeGenerationRunItem] = []
        seed_briefs: dict[str, str] = {}
        frozen_plan_items: list[PrototypePlanItem] = []
        for item in selected:
            prototype = existing_by_ref.get(item.candidate_id)
            if prototype is None:
                prototype = Prototype(
                    id=str(uuid4()),
                    project_id=plan.project_id,
                    title=item.title,
                    framework="html",
                    current_version=0,
                    source_kind="code",
                    source_ref=item.candidate_id,
                    source_hash=None,
                    source_meta_json=json.dumps(
                        self._source_metadata(plan, item), ensure_ascii=False
                    ),
                    created_at=now,
                    updated_at=now,
                )
            else:
                prototype.title = item.title
                prototype.source_meta_json = json.dumps(
                    self._source_metadata(plan, item), ensure_ascii=False
                )
                prototype.updated_at = now
            prototypes.append(prototype)
            item.prototype_id = prototype.id
            item.updated_at = now
            frozen_plan_items.append(item)
            seed_brief = self._restore_seed(plan, item)
            seed_briefs[prototype.id] = seed_brief
            run_items.append(
                PrototypeGenerationRunItem(
                    id=f"prototype-generation-item-{uuid4().hex}",
                    run_id=run_id,
                    plan_item_id=item.id,
                    prototype_id=prototype.id,
                    status="pending",
                    title=item.title,
                    seed_brief=seed_brief,
                    phase="queued",
                    last_event_at=now,
                    status_message=self._status_message(plan.output_locale, "queued"),
                    created_at=now,
                    updated_at=now,
                )
            )
        try:
            freeze_result = await self.store.freeze_prototype_generation_run(
                run,
                run_items,
                prototypes,
                frozen_plan_items,
                seed_briefs,
                reuse_terminal_run=reuse_terminal_run,
            )
        except Exception as exc:
            raise PrototypeGenerationError(f"could not freeze generation run: {exc}") from exc
        if freeze_result.created:
            task = asyncio.create_task(self._run(freeze_result.run.id))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        return freeze_result.run

    async def retry(self, plan_id: str, run_id: str | None = None) -> PrototypeGenerationRun:
        if run_id is None:
            loaded_plan = await self.store.load_prototype_plan(plan_id)
            if loaded_plan is None:
                raise PrototypeGenerationError(f"prototype plan not found: {plan_id}")
            # The caller should supply a run for deterministic retry; the latest
            # run is discovered from the plan's selected items by the API layer.
            raise PrototypeGenerationError("run_id is required for retry")
        loaded = await self.store.load_prototype_generation_run(run_id)
        if loaded is None or loaded[0].plan_id != plan_id:
            raise PrototypeGenerationError(f"generation run not found: {run_id}")
        failed_item_ids = {
            item.plan_item_id for item in loaded[1] if item.status in {"failed", "interrupted"}
        }
        if not failed_item_ids:
            raise PrototypeGenerationError("generation run has no failed or interrupted items")
        lock = self._plan_locks.setdefault(plan_id, asyncio.Lock())
        async with lock:
            return await self._create_run(
                plan_id,
                item_ids=failed_item_ids,
                reuse_terminal_run=False,
            )

    async def get_run(
        self, run_id: str
    ) -> tuple[PrototypeGenerationRun, list[PrototypeGenerationRunItem]]:
        loaded = await self.store.load_prototype_generation_run(run_id)
        if loaded is None:
            raise PrototypeGenerationError(f"generation run not found: {run_id}")
        return loaded

    async def stream_events(self, run_id: str) -> AsyncIterator[dict[str, object]]:
        while True:
            run, items = await self.get_run(run_id)
            yield {"event": "snapshot", "data": run.to_dict(items)}
            if run.status in self.TERMINAL_STATUSES:
                return
            await asyncio.sleep(0.25)

    async def _check_gates(self, count: int) -> None:
        if self.governance_gate is None:
            raise PrototypeGenerationError("generation governance gates are unavailable")
        try:
            await self.governance_gate(count)
        except Exception as exc:
            logger.error("prototype generation governance gate failed", exc_info=True)
            raise PrototypeGenerationError("generation governance gates are unavailable") from exc
        if self.artifact_generator is None:
            raise PrototypeGenerationError(
                "project prototype generation requires the Claude UI engineer"
            )
        try:
            await self.artifact_generator.ensure_available()
        except PrototypeArtifactError as exc:
            raise PrototypeGenerationError(str(exc)) from exc

    async def _run(self, run_id: str) -> None:
        started = time.monotonic()
        loaded = await self.store.load_prototype_generation_run(run_id)
        if loaded is None:
            return
        run, run_items = loaded
        loaded_plan = await self.store.load_prototype_plan(run.plan_id)
        if loaded_plan is None:
            error_message = "prototype_plan_missing"
            for item in run_items:
                await self.store.update_prototype_generation_item(
                    run_id,
                    item.id,
                    status="failed",
                    phase="failed",
                    last_event_at=datetime.now(),
                    status_message="",
                    error_message=error_message,
                )
            await self.store.update_prototype_generation_run(
                run_id,
                status="failed",
                error_message=error_message,
            )
            return
        plan, plan_items = loaded_plan
        project = await self.store.load_project(run.project_id)
        if project is None:
            error_message = "prototype_project_missing"
            for item in run_items:
                await self.store.update_prototype_generation_item(
                    run_id,
                    item.id,
                    status="failed",
                    phase="failed",
                    last_event_at=datetime.now(),
                    status_message="",
                    error_message=error_message,
                )
            await self.store.update_prototype_generation_run(
                run_id,
                status="failed",
                error_message=error_message,
            )
            return
        plan_items_by_id = {item.id: item for item in plan_items}
        await self.store.update_prototype_generation_run(run_id, status="running")
        semaphore = asyncio.Semaphore(self.concurrency)
        expected_versions: dict[str, PrototypeVersion] = {}
        failure_errors: dict[str, Exception] = {}

        async def one(item: PrototypeGenerationRunItem) -> bool:
            async with semaphore, self._global_semaphore:
                output_chars = 0
                task_id: str | None = None
                execution_process_id: str | None = None
                completion_reconciliation_failed = False
                await self.store.update_prototype_generation_item(
                    run_id,
                    item.id,
                    status="generating",
                    phase="starting",
                    output_chars=0,
                    last_event_at=datetime.now(),
                    status_message=self._status_message(plan.output_locale, "starting"),
                    attempt=item.attempt + 1,
                )
                try:
                    if item.prototype_id is None:
                        raise PrototypeGenerationError("generation item has no prototype seed")
                    plan_item = plan_items_by_id.get(item.plan_item_id)
                    if plan_item is None:
                        raise PrototypeGenerationError(
                            f"prototype plan item disappeared: {item.plan_item_id}"
                        )
                    frozen_seed = item.seed_brief.strip()
                    if not frozen_seed:
                        raise PrototypeGenerationError(
                            "generation item has no frozen prototype seed"
                        )
                    artifact_generator = self.artifact_generator
                    if artifact_generator is None:
                        raise PrototypeGenerationError(
                            "project prototype generation requires the Claude UI engineer"
                        )

                    async def on_artifact_activity(
                        activity: PrototypeArtifactActivity,
                    ) -> None:
                        nonlocal output_chars, task_id, execution_process_id
                        if activity.output_chars is not None:
                            output_chars = max(output_chars, activity.output_chars)
                        if activity.task_id is not None:
                            task_id = activity.task_id
                        if activity.execution_process_id is not None:
                            execution_process_id = activity.execution_process_id
                        mapped_phase = self._artifact_generation_phase(activity)
                        await self.store.update_prototype_generation_item(
                            run_id,
                            item.id,
                            status="generating",
                            phase=mapped_phase,
                            output_chars=output_chars,
                            last_event_at=activity.last_event_at or activity.occurred_at,
                            status_message=self._status_message(
                                plan.output_locale,
                                mapped_phase,
                            ),
                            task_id=task_id,
                            execution_process_id=execution_process_id,
                        )

                    artifact = await artifact_generator.generate(
                        PrototypeArtifactRequest(
                            project=project,
                            run_item_id=item.id,
                            candidate_id=plan_item.candidate_id,
                            source_hash=plan_item.source_hash,
                            title=item.title,
                            output_locale=plan.output_locale,
                            source_paths=self._source_guard_paths(plan_item),
                            target_routes=tuple(plan_item.route_patterns),
                        ),
                        activity_callback=on_artifact_activity,
                    )
                    task_id = artifact.task_id
                    execution_process_id = artifact.execution_process_id
                    output_chars = max(output_chars, len(artifact.html))
                    version = self._version_from_artifact(
                        item.prototype_id,
                        artifact,
                        instruction=frozen_seed,
                    )
                    output_chars = max(output_chars, len(version.html))
                    await self.store.update_prototype_generation_item(
                        run_id,
                        item.id,
                        status="generating",
                        phase="persisting",
                        output_chars=output_chars,
                        last_event_at=datetime.now(),
                        status_message=self._status_message(plan.output_locale, "persisting"),
                    )
                    version = write_project_version(project, version)
                    expected_versions[item.id] = version
                    # Do not unlink on store failure: SQLite commit outcome can be
                    # indeterminate after an I/O error. A later reference-based
                    # cleanup may remove unreferenced immutable files safely.
                    try:
                        await self.store.complete_prototype_generation_item(
                            run_id,
                            item.id,
                            version,
                            source_hash=plan_item.source_hash,
                            source_meta_json=json.dumps(
                                self._source_metadata(plan, plan_item),
                                ensure_ascii=False,
                            ),
                            output_chars=output_chars,
                            last_event_at=datetime.now(),
                            status_message=self._status_message(plan.output_locale, "completed"),
                            task_id=task_id,
                            execution_process_id=execution_process_id,
                        )
                    except Exception:
                        try:
                            completion_persisted = await self._completion_was_persisted(
                                run_id,
                                item.id,
                                version,
                            )
                        except Exception:
                            completion_reconciliation_failed = True
                            logger.exception(
                                "prototype generation completion reconciliation failed: "
                                "run_id=%s item_id=%s version_id=%s",
                                run_id,
                                item.id,
                                version.id,
                            )
                            raise
                        if completion_persisted:
                            logger.warning(
                                "prototype generation completion acknowledged after store error: "
                                "run_id=%s item_id=%s version_id=%s",
                                run_id,
                                item.id,
                                version.id,
                            )
                            return True
                        raise
                    return True
                # One failed external generation must become a persisted item failure
                # without cancelling sibling pages in this background batch.
                except Exception as exc:
                    if completion_reconciliation_failed:
                        raise
                    failure_errors[item.id] = exc
                    logger.exception(
                        "prototype generation item failed: run_id=%s item_id=%s",
                        run_id,
                        item.id,
                    )
                    try:
                        await self.store.update_prototype_generation_item(
                            run_id,
                            item.id,
                            status="failed",
                            phase="failed",
                            output_chars=output_chars,
                            last_event_at=datetime.now(),
                            status_message=self._status_message(plan.output_locale, "failed"),
                            task_id=task_id,
                            execution_process_id=execution_process_id,
                            error_message=str(exc),
                        )
                    except Exception:
                        logger.exception(
                            "prototype generation item failure persistence failed: "
                            "run_id=%s item_id=%s",
                            run_id,
                            item.id,
                        )
                        raise
                    return False

        results = await asyncio.gather(*(one(item) for item in run_items), return_exceptions=True)
        worker_errors = {
            item.id: result
            for item, result in zip(run_items, results, strict=True)
            if isinstance(result, Exception)
        }
        reconciliation_failed = await self._reconcile_generation_items(
            run_id=run_id,
            run_items=run_items,
            output_locale=plan.output_locale,
            expected_versions=expected_versions,
            failure_errors=failure_errors,
            worker_errors=worker_errors,
        )
        final_run, final_items = await self.get_run(run_id)
        completed = sum(item.status == "done" for item in final_items)
        failed = sum(item.status in {"failed", "interrupted", "skipped"} for item in final_items)
        nonterminal = len(final_items) - completed - failed
        if reconciliation_failed or nonterminal:
            status: GenerationRunStatus = "failed"
            run_error = "prototype_generation_reconciliation_failed"
        else:
            status = "completed" if failed == 0 else "partial" if completed else "failed"
            run_error = None
        await self.store.update_prototype_generation_run(
            run_id,
            status=status,
            error_message=run_error,
        )
        final_run, _ = await self.get_run(run_id)
        record_event(
            {
                "type": "prototype_generation_run",
                "payload": {
                    "project_id": run.project_id,
                    "plan_id": run.plan_id,
                    "run_id": run_id,
                    "status": status,
                    "total": final_run.total,
                    "processed": final_run.processed,
                    "succeeded": final_run.succeeded,
                    "failed": final_run.failed,
                    "running": final_run.running,
                    "pending": final_run.pending,
                    "duration_ms": int((time.monotonic() - started) * 1000),
                },
            }
        )

    async def _completion_was_persisted(
        self,
        run_id: str,
        item_id: str,
        expected_version: PrototypeVersion,
    ) -> bool:
        loaded = await self.store.load_prototype_generation_run(run_id)
        if loaded is None:
            return False
        persisted_item = next((item for item in loaded[1] if item.id == item_id), None)
        if persisted_item is None or persisted_item.status != "done":
            return False
        if (
            persisted_item.prototype_id != expected_version.prototype_id
            or persisted_item.version_no is None
        ):
            raise PrototypeGenerationError(
                f"persisted generation completion is inconsistent: {item_id}"
            )
        persisted_version = await self.store.load_prototype_version(
            persisted_item.prototype_id,
            persisted_item.version_no,
        )
        if persisted_version is None or persisted_version.id != expected_version.id:
            raise PrototypeGenerationError(
                f"persisted generation version does not match: {item_id}"
            )
        return True

    async def _reconcile_generation_items(
        self,
        *,
        run_id: str,
        run_items: list[PrototypeGenerationRunItem],
        output_locale: PlanOutputLocale,
        expected_versions: dict[str, PrototypeVersion],
        failure_errors: dict[str, Exception],
        worker_errors: dict[str, Exception],
    ) -> bool:
        loaded = await self.store.load_prototype_generation_run(run_id)
        if loaded is None:
            raise PrototypeGenerationError(f"generation run not found: {run_id}")
        persisted_by_id = {item.id: item for item in loaded[1]}
        reconciliation_failed = False
        for run_item in run_items:
            persisted_item = persisted_by_id.get(run_item.id)
            if persisted_item is None:
                logger.error(
                    "prototype generation item disappeared during reconciliation: "
                    "run_id=%s item_id=%s",
                    run_id,
                    run_item.id,
                )
                reconciliation_failed = True
                continue
            expected_version = expected_versions.get(run_item.id)
            if persisted_item.status == "done":
                if expected_version is not None:
                    try:
                        await self._completion_was_persisted(
                            run_id,
                            run_item.id,
                            expected_version,
                        )
                    except Exception:
                        logger.exception(
                            "prototype generation persisted completion is inconsistent: "
                            "run_id=%s item_id=%s version_id=%s",
                            run_id,
                            run_item.id,
                            expected_version.id,
                        )
                        reconciliation_failed = True
                continue
            if persisted_item.status in {"failed", "interrupted", "skipped"}:
                continue
            if expected_version is not None:
                try:
                    if await self._completion_was_persisted(
                        run_id,
                        run_item.id,
                        expected_version,
                    ):
                        continue
                except Exception:
                    logger.exception(
                        "prototype generation completion could not be reconciled: "
                        "run_id=%s item_id=%s version_id=%s",
                        run_id,
                        run_item.id,
                        expected_version.id,
                    )
                    reconciliation_failed = True
                    continue
            item_error = failure_errors.get(run_item.id)
            if item_error is None:
                item_error = worker_errors.get(run_item.id)
            error_message = (
                str(item_error)
                if item_error is not None
                else "prototype generation worker stopped before terminal persistence"
            )
            try:
                await self.store.update_prototype_generation_item(
                    run_id,
                    run_item.id,
                    status="failed",
                    phase="failed",
                    last_event_at=datetime.now(),
                    status_message=self._status_message(output_locale, "failed"),
                    error_message=error_message,
                )
            except Exception:
                logger.exception(
                    "prototype generation supervisor could not persist item failure: "
                    "run_id=%s item_id=%s",
                    run_id,
                    run_item.id,
                )
                reconciliation_failed = True
        return reconciliation_failed

    @staticmethod
    def _status_message(locale: PlanOutputLocale, phase: GenerationItemPhase) -> str:
        messages: dict[PlanOutputLocale, dict[GenerationItemPhase, str]] = {
            "zh-CN": {
                "queued": "等待生成",
                "starting": "正在启动页面生成",
                "streaming": "正在生成页面",
                "persisting": "正在保存生成结果",
                "completed": "页面生成完成",
                "failed": "页面生成失败",
                "interrupted": "页面生成已中断",
                "skipped": "页面生成已跳过",
            },
            "en-US": {
                "queued": "Waiting to generate",
                "starting": "Starting page generation",
                "streaming": "Generating page",
                "persisting": "Saving generated page",
                "completed": "Page generated",
                "failed": "Page generation failed",
                "interrupted": "Page generation interrupted",
                "skipped": "Page generation skipped",
            },
        }
        return messages[locale][phase]

    @staticmethod
    def _artifact_generation_phase(
        activity: PrototypeArtifactActivity,
    ) -> GenerationItemPhase:
        if activity.phase in {"preparing", "worktree_ready"}:
            return "starting"
        if activity.phase == "running":
            return "streaming"
        return "persisting"

    @staticmethod
    def _source_guard_paths(item: PrototypePlanItem) -> tuple[str, ...]:
        paths = [*item.source_paths, *item.layout_paths]
        for evidence in item.evidence:
            path = evidence.get("path")
            if isinstance(path, str):
                paths.append(path)
        return tuple(dict.fromkeys(paths))

    @staticmethod
    def _version_from_artifact(
        prototype_id: str,
        artifact: PrototypeArtifactResult,
        *,
        instruction: str,
    ) -> PrototypeVersion:
        return PrototypeVersion(
            id=str(uuid4()),
            prototype_id=prototype_id,
            version_no=0,
            instruction=instruction,
            html=artifact.html,
            disk_path=None,
            created_at=datetime.now(),
        )

    @staticmethod
    def _source_metadata(plan: PrototypePlan, item: PrototypePlanItem) -> dict[str, object]:
        return {
            "plan_id": plan.id,
            "candidate_id": item.candidate_id,
            "restore_baseline": True,
            "package_root": item.package_root,
            "surface_kind": item.surface_kind,
            "route_patterns": item.route_patterns,
            "source_paths": item.source_paths,
            "layout_paths": item.layout_paths,
            "evidence": item.evidence,
        }

    @staticmethod
    def _restore_seed(plan: PrototypePlan, item: PrototypePlanItem) -> str:
        context = json.dumps(plan.project_context, ensure_ascii=False, sort_keys=True)
        if plan.output_locale == "zh-CN":
            instruction = plan.global_instruction or "按当前实现原样还原, 不做重新设计。"
            labels = ("项目上下文", "统一要求", "页面说明")
        else:
            instruction = (
                plan.global_instruction or "Restore the current implementation without redesign."
            )
            labels = ("Project context", "Shared instruction", "Page brief")
        return "\n\n".join(
            (
                f"{labels[0]}: {context}",
                f"{labels[1]}: {instruction}",
                f"{labels[2]}: {item.brief}",
            )
        )
