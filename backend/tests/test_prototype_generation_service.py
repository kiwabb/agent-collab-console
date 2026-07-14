from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path

import pytest

from app.adapters.async_sqlite_store import AsyncSQLiteStore
from app.application.prototype_artifact_generator import (
    PrototypeArtifactActivity,
    PrototypeArtifactError,
    PrototypeArtifactManifest,
    PrototypeArtifactRequest,
    PrototypeArtifactResult,
)
from app.application.prototype_generation_service import (
    PrototypeGenerationError,
    PrototypeGenerationService,
)
from app.application.prototype_version_artifacts import PrototypeVersionArtifactError
from app.domain.models import (
    Project,
    Prototype,
    PrototypeVersion,
)
from app.domain.project_evidence import ProjectSurfaceManifest
from app.domain.prototype_generation import (
    GenerationItemPhase,
    GenerationItemStatus,
    GenerationRunStatus,
    PrototypeGenerationRun,
    PrototypeGenerationRunFreezeResult,
    PrototypeGenerationRunItem,
)
from app.domain.prototype_plan import PrototypePlan, PrototypePlanItem

ARTIFACT_HTML = "<!DOCTYPE html><html><body><h1>VideoNote</h1></body></html>"


def _artifact_result(
    request: PrototypeArtifactRequest,
    *,
    html: str = ARTIFACT_HTML,
) -> PrototypeArtifactResult:
    return PrototypeArtifactResult(
        task_id="prototype-ui-task-1",
        execution_process_id="execution-process-1",
        html=html,
        manifest=PrototypeArtifactManifest(
            schema_version="prototype-artifact/v1",
            artifact_path=f".agent-collab/prototype-staging/{request.run_item_id}/index.html",
            sha256="sha256:" + "0" * 64,
            byte_size=len(html.encode()),
        ),
    )


class _Evidence:
    def __init__(self, fingerprint: str) -> None:
        self.fingerprint = fingerprint

    def scan_project(self, _project: Project) -> ProjectSurfaceManifest:
        return ProjectSurfaceManifest(
            repository_root="/repo",
            repository_fingerprint=self.fingerprint,
            packages=(),
            candidates=(),
            diagnostics=(),
        )


class _BarrierEvidence(_Evidence):
    def __init__(self, fingerprint: str, barrier: threading.Barrier) -> None:
        super().__init__(fingerprint)
        self.barrier = barrier

    def scan_project(self, project: Project) -> ProjectSurfaceManifest:
        self.barrier.wait(timeout=5)
        return super().scan_project(project)


class _ArtifactGenerator:
    def __init__(self) -> None:
        self.available_checks = 0
        self.requests: list[PrototypeArtifactRequest] = []

    async def ensure_available(self) -> None:
        self.available_checks += 1

    async def generate(
        self,
        request: PrototypeArtifactRequest,
        *,
        activity_callback: Callable[[PrototypeArtifactActivity], Awaitable[None]] | None = None,
    ) -> PrototypeArtifactResult:
        self.requests.append(request)
        now = datetime.now()
        if activity_callback is not None:
            await activity_callback(
                PrototypeArtifactActivity(
                    phase="preparing",
                    task_id=None,
                    execution_process_id=None,
                    output_chars=None,
                    last_event_at=None,
                    occurred_at=now,
                )
            )
            await activity_callback(
                PrototypeArtifactActivity(
                    phase="running",
                    task_id="prototype-ui-task-1",
                    execution_process_id="execution-process-1",
                    output_chars=4_096,
                    last_event_at=now,
                    occurred_at=now,
                )
            )
            await activity_callback(
                PrototypeArtifactActivity(
                    phase="validating",
                    task_id="prototype-ui-task-1",
                    execution_process_id="execution-process-1",
                    output_chars=len(ARTIFACT_HTML),
                    last_event_at=now,
                    occurred_at=now,
                )
            )
        return _artifact_result(request)


class _UnavailableArtifactGenerator(_ArtifactGenerator):
    async def ensure_available(self) -> None:
        self.available_checks += 1
        raise PrototypeArtifactError("Claude UI engineer is unavailable")


class _FailingArtifactGenerator(_ArtifactGenerator):
    async def generate(
        self,
        request: PrototypeArtifactRequest,
        *,
        activity_callback: Callable[[PrototypeArtifactActivity], Awaitable[None]] | None = None,
    ) -> PrototypeArtifactResult:
        del activity_callback
        self.requests.append(request)
        raise PrototypeArtifactError("artifact generation failed before completion")


class _BlockingArtifactGenerator(_ArtifactGenerator):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def generate(
        self,
        request: PrototypeArtifactRequest,
        *,
        activity_callback: Callable[[PrototypeArtifactActivity], Awaitable[None]] | None = None,
    ) -> PrototypeArtifactResult:
        self.requests.append(request)
        now = datetime.now()
        if activity_callback is not None:
            await activity_callback(
                PrototypeArtifactActivity(
                    phase="running",
                    task_id="prototype-ui-task-1",
                    execution_process_id="execution-process-1",
                    output_chars=0,
                    last_event_at=now,
                    occurred_at=now,
                )
            )
        self.started.set()
        await self.release.wait()
        return _artifact_result(request)


class _RealtimeArtifactGenerator(_ArtifactGenerator):
    def __init__(self) -> None:
        super().__init__()
        self.activity_persisted = asyncio.Event()
        self.release = asyncio.Event()

    async def generate(
        self,
        request: PrototypeArtifactRequest,
        *,
        activity_callback: Callable[[PrototypeArtifactActivity], Awaitable[None]] | None = None,
    ) -> PrototypeArtifactResult:
        self.requests.append(request)
        now = datetime.now()
        if activity_callback is not None:
            await activity_callback(
                PrototypeArtifactActivity(
                    phase="running",
                    task_id="prototype-ui-task-1",
                    execution_process_id="execution-process-1",
                    output_chars=2_048,
                    last_event_at=now,
                    occurred_at=now,
                )
            )
        self.activity_persisted.set()
        await self.release.wait()
        return _artifact_result(request)


class _CountedArtifactGenerator(_ArtifactGenerator):
    def __init__(self, *, successes: int) -> None:
        super().__init__()
        self.successes = successes
        self.calls = 0

    async def generate(
        self,
        request: PrototypeArtifactRequest,
        *,
        activity_callback: Callable[[PrototypeArtifactActivity], Awaitable[None]] | None = None,
    ) -> PrototypeArtifactResult:
        call_index = self.calls
        self.calls += 1
        if call_index >= self.successes:
            self.requests.append(request)
            raise PrototypeArtifactError("generation failed")
        return await super().generate(request, activity_callback=activity_callback)


class _WorkerGateStore(AsyncSQLiteStore):
    def __init__(self, db_path: Path) -> None:
        super().__init__(db_path)
        self.block_next_worker_load = False
        self.worker_load_started = asyncio.Event()
        self.worker_release = asyncio.Event()
        self._worker_load_claimed = False

    async def load_prototype_generation_run(
        self, run_id: str
    ) -> tuple[PrototypeGenerationRun, list[PrototypeGenerationRunItem]] | None:
        if self.block_next_worker_load and not self._worker_load_claimed:
            self._worker_load_claimed = True
            self.worker_load_started.set()
            await self.worker_release.wait()
        return await super().load_prototype_generation_run(run_id)


class _TerminalSignalStore(AsyncSQLiteStore):
    def __init__(self, db_path: Path, terminal: asyncio.Event) -> None:
        super().__init__(db_path)
        self.terminal = terminal

    async def update_prototype_generation_run(
        self,
        run_id: str,
        *,
        status: GenerationRunStatus,
        error_message: str | None = None,
    ) -> None:
        await super().update_prototype_generation_run(
            run_id,
            status=status,
            error_message=error_message,
        )
        if status in {"completed", "partial", "failed", "interrupted"}:
            self.terminal.set()


class _FreezeAfterTerminalStore(AsyncSQLiteStore):
    def __init__(self, db_path: Path, terminal: asyncio.Event) -> None:
        super().__init__(db_path)
        self.terminal = terminal

    async def freeze_prototype_generation_run(
        self,
        run: PrototypeGenerationRun,
        run_items: list[PrototypeGenerationRunItem],
        prototypes: list[Prototype],
        plan_items: list[PrototypePlanItem],
        seed_briefs: dict[str, str],
        *,
        reuse_terminal_run: bool = False,
    ) -> PrototypeGenerationRunFreezeResult:
        await asyncio.wait_for(self.terminal.wait(), timeout=2)
        return await super().freeze_prototype_generation_run(
            run,
            run_items,
            prototypes,
            plan_items,
            seed_briefs,
            reuse_terminal_run=reuse_terminal_run,
        )


class _CommitThenRaiseStore(AsyncSQLiteStore):
    def __init__(self, db_path: Path) -> None:
        super().__init__(db_path)
        self.committed_version_id: str | None = None

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
    ) -> PrototypeVersion:
        persisted = await super().complete_prototype_generation_item(
            run_id,
            item_id,
            version,
            source_hash=source_hash,
            source_meta_json=source_meta_json,
            output_chars=output_chars,
            last_event_at=last_event_at,
            status_message=status_message,
            task_id=task_id,
            execution_process_id=execution_process_id,
        )
        self.committed_version_id = persisted.id
        raise RuntimeError("completion acknowledgement was lost after commit")


class _FailFirstFailurePersistenceStore(AsyncSQLiteStore):
    def __init__(self, db_path: Path) -> None:
        super().__init__(db_path)
        self.failure_persistence_attempts = 0

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
    ) -> None:
        if status == "failed":
            self.failure_persistence_attempts += 1
            if self.failure_persistence_attempts == 1:
                raise RuntimeError("failure persistence acknowledgement was lost")
        await super().update_prototype_generation_item(
            run_id,
            item_id,
            status=status,
            phase=phase,
            output_chars=output_chars,
            last_event_at=last_event_at,
            status_message=status_message,
            task_id=task_id,
            execution_process_id=execution_process_id,
            error_message=error_message,
            attempt=attempt,
        )


def _item(plan_id: str, item_id: str, *, selected: bool = True) -> PrototypePlanItem:
    now = datetime.now()
    return PrototypePlanItem(
        id=item_id,
        plan_id=plan_id,
        candidate_id=f"candidate-{item_id}",
        package_root="frontend",
        surface_kind="web",
        route_patterns=[f"/{item_id}"],
        primary_source_path="src/Page.tsx",
        source_paths=["src/Page.tsx"],
        layout_paths=[],
        title=item_id,
        summary="summary",
        brief="restore this page",
        states=["default"],
        evidence_ids=[],
        evidence=[],
        confidence="high",
        action="create",
        selected=selected,
        source_hash="sha256:item",
        created_at=now,
        updated_at=now,
    )


def test_restore_seed_follows_persisted_output_locale() -> None:
    item = _item("plan-1", "item-1")
    item.brief = "依据项目证据还原当前页面。"
    chinese_plan = PrototypePlan(
        id="plan-1",
        project_id="project-1",
        status="ready",
        repository_fingerprint="sha256:repo",
        project_context={
            "product_summary": "视频笔记工作区",
            "audience": "视频创作者",
            "visual_language": "紧凑的工作界面",
            "shared_layout": "固定导航布局",
        },
        output_locale="zh-CN",
    )
    english_plan = PrototypePlan(
        id="plan-2",
        project_id="project-1",
        status="ready",
        repository_fingerprint="sha256:repo",
        project_context={
            "product_summary": "Video note workspace",
            "audience": "Video creators",
            "visual_language": "Dense operational interface",
            "shared_layout": "Persistent navigation shell",
        },
        output_locale="en-US",
    )

    chinese_seed = PrototypeGenerationService._restore_seed(chinese_plan, item)
    english_seed = PrototypeGenerationService._restore_seed(english_plan, item)

    assert "项目上下文:" in chinese_seed
    assert "统一要求: 按当前实现原样还原, 不做重新设计。" in chinese_seed
    assert "页面说明: 依据项目证据还原当前页面。" in chinese_seed
    assert "Project context:" in english_seed
    assert (
        "Shared instruction: Restore the current implementation without redesign." in english_seed
    )


@pytest.mark.asyncio
async def test_generation_is_stale_safe_and_fail_closed(tmp_path: Path) -> None:
    store = AsyncSQLiteStore(tmp_path / "generation.db")
    await store._init_db()
    try:
        project = Project(id="project-1", name="demo", repo_path=str(tmp_path))
        await store.save_project(project)
        plan = PrototypePlan(
            id="plan-1",
            project_id=project.id,
            status="ready",
            repository_fingerprint="sha256:old",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        item = _item(plan.id, "item-1")
        await store.save_prototype_plan_with_items(plan, [item])
        service = PrototypeGenerationService(
            store=store,
            evidence_service=_Evidence("sha256:new"),
            governance_gate=lambda _count: _allow(),
        )
        with pytest.raises(PrototypeGenerationError, match="stale"):
            await service.create_run(plan.id)
    finally:
        await store.close()


async def _allow() -> None:
    return None


@pytest.mark.asyncio
async def test_project_generation_requires_claude_artifact_generator(tmp_path: Path) -> None:
    store = AsyncSQLiteStore(tmp_path / "requires-claude.db")
    await store._init_db()
    try:
        project = Project(id="project-1", name="demo", repo_path=str(tmp_path))
        await store.save_project(project)
        plan = PrototypePlan(
            id="plan-1",
            project_id=project.id,
            status="ready",
            repository_fingerprint="sha256:repo",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        await store.save_prototype_plan_with_items(plan, [_item(plan.id, "item-1")])
        service = PrototypeGenerationService(
            store=store,
            evidence_service=_Evidence("sha256:repo"),
            governance_gate=lambda _count: _allow(),
        )

        with pytest.raises(PrototypeGenerationError, match="requires the Claude UI engineer"):
            await service.create_run(plan.id)

        assert await store.list_prototypes(project.id) == []
        assert await store.load_latest_prototype_generation_run_for_plan(plan.id) is None
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_project_generation_does_not_fallback_when_claude_is_unavailable(
    tmp_path: Path,
) -> None:
    store = AsyncSQLiteStore(tmp_path / "claude-unavailable.db")
    await store._init_db()
    try:
        project = Project(id="project-1", name="demo", repo_path=str(tmp_path))
        await store.save_project(project)
        plan = PrototypePlan(
            id="plan-1",
            project_id=project.id,
            status="ready",
            repository_fingerprint="sha256:repo",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        await store.save_prototype_plan_with_items(plan, [_item(plan.id, "item-1")])
        artifact_generator = _UnavailableArtifactGenerator()
        service = PrototypeGenerationService(
            store=store,
            evidence_service=_Evidence("sha256:repo"),
            governance_gate=lambda _count: _allow(),
            artifact_generator=artifact_generator,
        )

        with pytest.raises(PrototypeGenerationError, match="Claude UI engineer is unavailable"):
            await service.create_run(plan.id)

        assert artifact_generator.available_checks == 1
        assert artifact_generator.requests == []
        assert await store.list_prototypes(project.id) == []
        assert await store.load_latest_prototype_generation_run_for_plan(plan.id) is None
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_generation_freezes_source_seed_once(tmp_path: Path) -> None:
    store = AsyncSQLiteStore(tmp_path / "generation.db")
    await store._init_db()
    try:
        project = Project(id="project-1", name="demo", repo_path=str(tmp_path))
        await store.save_project(project)
        plan = PrototypePlan(
            id="plan-1",
            project_id=project.id,
            status="ready",
            repository_fingerprint="sha256:repo",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        item = _item(plan.id, "item-1")
        await store.save_prototype_plan_with_items(plan, [item])
        artifact_generator = _ArtifactGenerator()
        service = PrototypeGenerationService(
            store=store,
            evidence_service=_Evidence("sha256:repo"),
            governance_gate=lambda _count: _allow(),
            artifact_generator=artifact_generator,
        )
        run = await service.create_run(plan.id)
        assert run.total == 1
        loaded = await store.load_prototype_generation_run(run.id)
        assert loaded is not None
        assert loaded[1][0].prototype_id is not None
        assert len(await store.list_prototypes(project.id)) == 1
        if service._tasks:
            await asyncio.gather(*list(service._tasks))
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_generation_uses_ui_engineer_artifact_and_persists_correlation(
    tmp_path: Path,
) -> None:
    store = AsyncSQLiteStore(tmp_path / "artifact-generation.db")
    service: PrototypeGenerationService | None = None
    await store._init_db()
    try:
        project = Project(id="project-1", name="VideoNote", repo_path=str(tmp_path))
        await store.save_project(project)
        plan = PrototypePlan(
            id="plan-artifact",
            project_id=project.id,
            status="ready",
            repository_fingerprint="sha256:repo",
            project_context={
                "product_summary": "视频笔记工作台",
                "audience": "内容创作者",
                "visual_language": "紧凑的桌面工具",
                "shared_layout": "左侧导航",
            },
            global_instruction="严格还原, 不做优化",
            output_locale="zh-CN",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        item = _item(plan.id, "item-artifact")
        item.layout_paths = ["src/Layout.tsx"]
        item.evidence = [{"path": "src/theme.css"}]
        navigation_item = _item(plan.id, "settings-model", selected=False)
        navigation_item.route_patterns = ["/settings/model", "/settings/model/:id"]
        await store.save_prototype_plan_with_items(plan, [item, navigation_item])
        artifact_generator = _ArtifactGenerator()
        service = PrototypeGenerationService(
            store=store,
            evidence_service=_Evidence("sha256:repo"),
            governance_gate=lambda _count: _allow(),
            artifact_generator=artifact_generator,
        )

        run = await service.create_run(plan.id)
        await asyncio.gather(*list(service._tasks))

        loaded = await store.load_prototype_generation_run(run.id)
        assert loaded is not None
        finished, run_items = loaded
        assert finished.status == "completed"
        assert finished.processed == finished.succeeded == 1
        assert artifact_generator.available_checks == 1
        assert len(artifact_generator.requests) == 1
        request = artifact_generator.requests[0]
        assert request.source_paths == (
            "src/Page.tsx",
            "src/Layout.tsx",
            "src/theme.css",
        )
        assert request.target_routes == ("/item-artifact",)
        assert "/settings/model" not in request.target_routes
        assert not hasattr(request, "brief")
        assert run_items[0].task_id == "prototype-ui-task-1"
        assert run_items[0].execution_process_id == "execution-process-1"
        assert run_items[0].output_chars == 4_096
        assert run_items[0].version_no == 1

        prototypes = await store.list_prototypes(project.id)
        assert len(prototypes) == 1
        version = await store.load_prototype_version(prototypes[0].id, 1)
        assert version is not None
        assert version.html == ARTIFACT_HTML
        assert version.instruction == run_items[0].seed_brief
        assert version.disk_path is not None
        assert Path(version.disk_path).is_relative_to(tmp_path / "prototypes")
        assert Path(version.disk_path).read_text(encoding="utf-8") == ARTIFACT_HTML
    finally:
        if service is not None and service._tasks:
            await asyncio.gather(*list(service._tasks), return_exceptions=True)
        await store.close()


@pytest.mark.asyncio
async def test_project_generation_disk_write_failure_is_not_committed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = AsyncSQLiteStore(tmp_path / "artifact-write-failure.db")
    service: PrototypeGenerationService | None = None
    await store._init_db()
    try:
        project = Project(id="project-1", name="VideoNote", repo_path=str(tmp_path))
        await store.save_project(project)
        plan = PrototypePlan(
            id="plan-artifact-write-failure",
            project_id=project.id,
            status="ready",
            repository_fingerprint="sha256:repo",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        item = _item(plan.id, "item-artifact-write-failure")
        await store.save_prototype_plan_with_items(plan, [item])

        def fail_write(_project: Project, _version: PrototypeVersion) -> PrototypeVersion:
            raise PrototypeVersionArtifactError("prototype version file could not be written")

        monkeypatch.setattr(
            "app.application.prototype_generation_service.write_project_version",
            fail_write,
        )
        service = PrototypeGenerationService(
            store=store,
            evidence_service=_Evidence("sha256:repo"),
            governance_gate=lambda _count: _allow(),
            artifact_generator=_ArtifactGenerator(),
        )

        run = await service.create_run(plan.id)
        await asyncio.gather(*list(service._tasks))

        loaded = await store.load_prototype_generation_run(run.id)
        prototypes = await store.list_prototypes(project.id)
        assert loaded is not None
        assert loaded[0].status == "failed"
        assert loaded[1][0].status == "failed"
        assert "could not be written" in (loaded[1][0].error_message or "")
        assert len(prototypes) == 1
        assert prototypes[0].source_hash is None
        assert prototypes[0].current_version == 0
        assert await store.load_prototype_version(prototypes[0].id, 1) is None
    finally:
        if service is not None and service._tasks:
            await asyncio.gather(*list(service._tasks), return_exceptions=True)
        await store.close()


@pytest.mark.asyncio
async def test_generation_reconciles_completion_that_committed_before_store_raised(
    tmp_path: Path,
) -> None:
    store = _CommitThenRaiseStore(tmp_path / "completion-indeterminate.db")
    await store._init_db()
    try:
        project = Project(id="project-1", name="VideoNote", repo_path=str(tmp_path))
        await store.save_project(project)
        plan = PrototypePlan(
            id="plan-completion-indeterminate",
            project_id=project.id,
            status="ready",
            repository_fingerprint="sha256:repo",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        await store.save_prototype_plan_with_items(plan, [_item(plan.id, "item-1")])
        service = PrototypeGenerationService(
            store=store,
            evidence_service=_Evidence("sha256:repo"),
            governance_gate=lambda _count: _allow(),
            artifact_generator=_ArtifactGenerator(),
        )

        run = await service.create_run(plan.id)
        await asyncio.gather(*list(service._tasks))

        loaded = await store.load_prototype_generation_run(run.id)
        assert loaded is not None
        finished, run_items = loaded
        assert finished.status == "completed"
        assert finished.processed == finished.succeeded == 1
        assert finished.failed == finished.running == finished.pending == 0
        assert run_items[0].status == "done"
        assert run_items[0].version_no == 1
        assert run_items[0].prototype_id is not None
        persisted_version = await store.load_prototype_version(
            run_items[0].prototype_id,
            run_items[0].version_no,
        )
        assert persisted_version is not None
        assert persisted_version.id == store.committed_version_id
        versions = await store.list_prototype_versions(run_items[0].prototype_id)
        assert [version.version_no for version in versions] == [0, 1]
        assert sum(version.id == store.committed_version_id for version in versions) == 1
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_generation_supervisor_recovers_when_first_failure_write_raises(
    tmp_path: Path,
) -> None:
    store = _FailFirstFailurePersistenceStore(tmp_path / "failure-reconciliation.db")
    await store._init_db()
    try:
        project = Project(id="project-1", name="VideoNote", repo_path=str(tmp_path))
        await store.save_project(project)
        plan = PrototypePlan(
            id="plan-failure-reconciliation",
            project_id=project.id,
            status="ready",
            repository_fingerprint="sha256:repo",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        await store.save_prototype_plan_with_items(plan, [_item(plan.id, "item-1")])
        service = PrototypeGenerationService(
            store=store,
            evidence_service=_Evidence("sha256:repo"),
            governance_gate=lambda _count: _allow(),
            artifact_generator=_FailingArtifactGenerator(),
        )

        run = await service.create_run(plan.id)
        await asyncio.gather(*list(service._tasks))

        loaded = await store.load_prototype_generation_run(run.id)
        assert loaded is not None
        finished, run_items = loaded
        assert store.failure_persistence_attempts == 2
        assert finished.status == "failed"
        assert finished.processed == finished.failed == 1
        assert finished.succeeded == finished.running == finished.pending == 0
        assert run_items[0].status == "failed"
        assert run_items[0].phase == "failed"
        assert "failed before completion" in (run_items[0].error_message or "")
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_artifact_generation_uses_seed_frozen_before_plan_edits(tmp_path: Path) -> None:
    store = _WorkerGateStore(tmp_path / "artifact-frozen-seed.db")
    service: PrototypeGenerationService | None = None
    await store._init_db()
    try:
        project = Project(id="project-1", name="VideoNote", repo_path=str(tmp_path))
        await store.save_project(project)
        plan = PrototypePlan(
            id="plan-frozen-artifact",
            project_id=project.id,
            status="ready",
            repository_fingerprint="sha256:repo",
            project_context={
                "product_summary": "原始项目上下文",
                "audience": "原始受众",
                "visual_language": "原始视觉语言",
                "shared_layout": "原始共享布局",
            },
            global_instruction="原始统一要求",
            output_locale="zh-CN",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        item = _item(plan.id, "item-frozen-artifact")
        item.brief = "原始页面说明"
        expected_seed = PrototypeGenerationService._restore_seed(plan, item)
        await store.save_prototype_plan_with_items(plan, [item])
        artifact_generator = _ArtifactGenerator()
        service = PrototypeGenerationService(
            store=store,
            evidence_service=_Evidence("sha256:repo"),
            governance_gate=lambda _count: _allow(),
            artifact_generator=artifact_generator,
        )
        store.block_next_worker_load = True

        run = await service.create_run(plan.id)
        await asyncio.wait_for(store.worker_load_started.wait(), timeout=2)
        loaded_plan = await store.load_prototype_plan(plan.id)
        assert loaded_plan is not None
        edited_plan, edited_items = loaded_plan
        edited_plan.global_instruction = "编辑后的统一要求"
        edited_plan.project_context["product_summary"] = "编辑后的项目上下文"
        edited_items[0].brief = "编辑后的页面说明"
        edited_plan.updated_at = datetime.now()
        edited_items[0].updated_at = edited_plan.updated_at
        await store.save_prototype_plan_with_items(edited_plan, edited_items)

        store.worker_release.set()
        await asyncio.gather(*list(service._tasks))

        assert len(artifact_generator.requests) == 1
        assert not hasattr(artifact_generator.requests[0], "brief")
        loaded_run = await store.load_prototype_generation_run(run.id)
        assert loaded_run is not None
        assert loaded_run[1][0].seed_brief == expected_seed
        prototype_id = loaded_run[1][0].prototype_id
        assert prototype_id is not None
        version = await store.load_prototype_version(prototype_id, 1)
        assert version is not None
        assert version.instruction == expected_seed
    finally:
        store.worker_release.set()
        if service is not None and service._tasks:
            await asyncio.gather(*list(service._tasks), return_exceptions=True)
        await store.close()


@pytest.mark.asyncio
async def test_artifact_generation_ignores_cross_plan_v0_seed_overwrite(tmp_path: Path) -> None:
    store = _WorkerGateStore(tmp_path / "artifact-frozen-seed.db")
    service: PrototypeGenerationService | None = None
    await store._init_db()
    try:
        project = Project(id="project-1", name="VideoNote", repo_path=str(tmp_path))
        await store.save_project(project)
        now = datetime.now()
        first_plan = PrototypePlan(
            id="plan-first",
            project_id=project.id,
            status="ready",
            repository_fingerprint="sha256:repo",
            global_instruction="FIRST_FROZEN_SEED",
            output_locale="en-US",
            created_at=now,
            updated_at=now,
        )
        first_item = _item(first_plan.id, "item-first")
        first_item.brief = "Restore the first reviewed page."
        first_seed = PrototypeGenerationService._restore_seed(first_plan, first_item)
        await store.save_prototype_plan_with_items(first_plan, [first_item])
        artifact_generator = _ArtifactGenerator()
        service = PrototypeGenerationService(
            store=store,
            evidence_service=_Evidence("sha256:repo"),
            governance_gate=lambda _count: _allow(),
            artifact_generator=artifact_generator,
        )
        store.block_next_worker_load = True

        first_run = await service.create_run(first_plan.id)
        await asyncio.wait_for(store.worker_load_started.wait(), timeout=2)
        first_loaded = await store.load_prototype_generation_run(first_run.id)
        assert first_loaded is not None
        prototype_id = first_loaded[1][0].prototype_id
        assert prototype_id is not None

        second_plan = PrototypePlan(
            id="plan-second",
            project_id=project.id,
            status="ready",
            repository_fingerprint="sha256:repo",
            global_instruction="SECOND_FROZEN_SEED",
            output_locale="en-US",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        second_item = _item(second_plan.id, "item-second")
        second_item.candidate_id = first_item.candidate_id
        second_item.brief = "Restore the second reviewed page."
        second_seed = PrototypeGenerationService._restore_seed(second_plan, second_item)
        await store.save_prototype_plan_with_items(second_plan, [second_item])
        await service.create_run(second_plan.id)

        overwritten_v0 = await store.load_prototype_version(prototype_id, 0)
        assert overwritten_v0 is not None
        assert overwritten_v0.instruction == second_seed
        store.worker_release.set()
        await asyncio.gather(*list(service._tasks))

        versions = await store.list_prototype_versions(prototype_id)
        assert {version.instruction for version in versions if version.version_no > 0} == {
            first_seed,
            second_seed,
        }
    finally:
        store.worker_release.set()
        if service is not None and service._tasks:
            await asyncio.gather(*list(service._tasks), return_exceptions=True)
        await store.close()


@pytest.mark.asyncio
async def test_concurrent_generation_requests_return_one_persisted_run(tmp_path: Path) -> None:
    db_path = tmp_path / "generation.db"
    first_store = AsyncSQLiteStore(db_path)
    second_store = AsyncSQLiteStore(db_path)
    await first_store._init_db()
    await second_store._init_db()
    blocker = _BlockingArtifactGenerator()
    services: list[PrototypeGenerationService] = []
    try:
        project = Project(id="project-1", name="demo", repo_path=str(tmp_path))
        await first_store.save_project(project)
        plan = PrototypePlan(
            id="plan-1",
            project_id=project.id,
            status="ready",
            repository_fingerprint="sha256:repo",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        await first_store.save_prototype_plan_with_items(plan, [_item(plan.id, "item-1")])
        barrier = threading.Barrier(2)
        first_service = PrototypeGenerationService(
            store=first_store,
            evidence_service=_BarrierEvidence("sha256:repo", barrier),
            governance_gate=lambda _count: _allow(),
            artifact_generator=blocker,
        )
        second_service = PrototypeGenerationService(
            store=second_store,
            evidence_service=_BarrierEvidence("sha256:repo", barrier),
            governance_gate=lambda _count: _allow(),
            artifact_generator=blocker,
        )
        services = [first_service, second_service]

        first, second = await asyncio.gather(
            first_service.create_run(plan.id),
            second_service.create_run(plan.id),
        )
        await asyncio.wait_for(blocker.started.wait(), timeout=2)

        assert first.id == second.id
        assert await first_store.load_prototype_generation_run(first.id) is not None
        assert len(await first_store.list_prototypes(project.id)) == 1
        assert sum(len(service._tasks) for service in services) == 1
    finally:
        blocker.release.set()
        tasks = [task for service in services for task in service._tasks]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await first_store.close()
        await second_store.close()


@pytest.mark.asyncio
async def test_concurrent_generate_reuses_run_that_finishes_before_second_freeze(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "instant-generation.db"
    terminal = asyncio.Event()
    first_store = _TerminalSignalStore(db_path, terminal)
    second_store = _FreezeAfterTerminalStore(db_path, terminal)
    await first_store._init_db()
    await second_store._init_db()
    services: list[PrototypeGenerationService] = []
    try:
        project = Project(id="project-1", name="demo", repo_path=str(tmp_path))
        await first_store.save_project(project)
        plan = PrototypePlan(
            id="plan-instant",
            project_id=project.id,
            status="ready",
            repository_fingerprint="sha256:repo",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        await first_store.save_prototype_plan_with_items(plan, [_item(plan.id, "item-1")])
        barrier = threading.Barrier(2)
        first_service = PrototypeGenerationService(
            store=first_store,
            evidence_service=_BarrierEvidence("sha256:repo", barrier),
            governance_gate=lambda _count: _allow(),
            artifact_generator=_ArtifactGenerator(),
        )
        second_service = PrototypeGenerationService(
            store=second_store,
            evidence_service=_BarrierEvidence("sha256:repo", barrier),
            governance_gate=lambda _count: _allow(),
            artifact_generator=_ArtifactGenerator(),
        )
        services = [first_service, second_service]

        first, second = await asyncio.gather(
            first_service.create_run(plan.id),
            second_service.create_run(plan.id),
        )
        tasks = [task for service in services for task in service._tasks]
        if tasks:
            await asyncio.gather(*tasks)

        assert first.id == second.id
        loaded = await first_store.load_prototype_generation_run(first.id)
        assert loaded is not None
        assert loaded[0].status == "completed"
        connection = await first_store._get_conn()
        async with connection.execute(
            "SELECT COUNT(*) FROM prototype_generation_runs WHERE plan_id = ?",
            (plan.id,),
        ) as cursor:
            row = await cursor.fetchone()
        assert row is not None
        assert row[0] == 1
        assert len(await first_store.list_prototypes(project.id)) == 1
    finally:
        terminal.set()
        tasks = [task for service in services for task in service._tasks]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await first_store.close()
        await second_store.close()


@pytest.mark.asyncio
async def test_create_run_after_terminal_run_uses_current_selection(tmp_path: Path) -> None:
    store = AsyncSQLiteStore(tmp_path / "repeat-generation.db")
    await store._init_db()
    try:
        project = Project(id="project-1", name="demo", repo_path=str(tmp_path))
        await store.save_project(project)
        plan = PrototypePlan(
            id="plan-repeat",
            project_id=project.id,
            status="ready",
            repository_fingerprint="sha256:repo",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        first_item = _item(plan.id, "first")
        second_item = _item(plan.id, "second", selected=False)
        await store.save_prototype_plan_with_items(plan, [first_item, second_item])
        service = PrototypeGenerationService(
            store=store,
            evidence_service=_Evidence("sha256:repo"),
            governance_gate=lambda _count: _allow(),
            artifact_generator=_ArtifactGenerator(),
        )

        first_run = await service.create_run(plan.id)
        await asyncio.gather(*list(service._tasks))
        await store.update_prototype_plan_selection(
            plan.id,
            (first_item.id, second_item.id),
            selected=False,
            updated_at=datetime.now(),
        )
        await store.update_prototype_plan_selection(
            plan.id,
            (second_item.id,),
            selected=True,
            updated_at=datetime.now(),
        )

        second_run = await service.create_run(plan.id)
        await asyncio.gather(*list(service._tasks))
        loaded = await store.load_prototype_generation_run(second_run.id)

        assert second_run.id != first_run.id
        assert loaded is not None
        assert [item.plan_item_id for item in loaded[1]] == [second_item.id]
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_concurrent_run_completion_allocates_distinct_versions(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "version-allocation.db"
    first_store = AsyncSQLiteStore(db_path)
    second_store = AsyncSQLiteStore(db_path)
    await first_store._init_db()
    await second_store._init_db()
    try:
        now = datetime.now()
        project = Project(id="project-1", name="demo", repo_path=str(tmp_path))
        await first_store.save_project(project)
        prototype = Prototype(
            id="prototype-shared",
            project_id=project.id,
            title="Shared page",
            framework="html",
            current_version=0,
            source_kind="code",
            source_ref="candidate-shared",
            created_at=now,
            updated_at=now,
        )
        plans: list[tuple[PrototypePlan, PrototypePlanItem]] = []
        for suffix in ("one", "two"):
            plan = PrototypePlan(
                id=f"plan-{suffix}",
                project_id=project.id,
                status="ready",
                repository_fingerprint="sha256:repo",
                created_at=now,
                updated_at=now,
            )
            plan_item = _item(plan.id, f"item-{suffix}")
            plan_item.prototype_id = prototype.id
            await first_store.save_prototype_plan_with_items(plan, [plan_item])
            plans.append((plan, plan_item))

        frozen: list[tuple[PrototypeGenerationRun, PrototypeGenerationRunItem]] = []
        for suffix, (plan, plan_item) in zip(("one", "two"), plans, strict=True):
            run = PrototypeGenerationRun(
                id=f"run-{suffix}",
                plan_id=plan.id,
                project_id=project.id,
                status="queued",
                repository_fingerprint=plan.repository_fingerprint,
                total=1,
                pending=1,
                created_at=now,
                updated_at=now,
            )
            run_item = PrototypeGenerationRunItem(
                id=f"run-item-{suffix}",
                run_id=run.id,
                plan_item_id=plan_item.id,
                prototype_id=prototype.id,
                status="pending",
                title=plan_item.title,
                created_at=now,
                updated_at=now,
            )
            result = await first_store.freeze_prototype_generation_run(
                run,
                [run_item],
                [prototype],
                [plan_item],
                {prototype.id: f"seed-{suffix}"},
            )
            assert result.created is True
            await first_store.update_prototype_generation_item(
                run.id,
                run_item.id,
                status="generating",
            )
            frozen.append((run, run_item))

        first_candidate = PrototypeVersion(
            id="version-one",
            prototype_id=prototype.id,
            version_no=1,
            instruction="first",
            html="<!DOCTYPE html><html><body>first</body></html>",
            disk_path="/predicted/version-one/index.html",
            created_at=now,
        )
        second_candidate = PrototypeVersion(
            id="version-two",
            prototype_id=prototype.id,
            version_no=1,
            instruction="second",
            html="<!DOCTYPE html><html><body>second</body></html>",
            disk_path="/predicted/version-two/index.html",
            created_at=now,
        )
        first_result, second_result = await asyncio.gather(
            first_store.complete_prototype_generation_item(
                frozen[0][0].id,
                frozen[0][1].id,
                first_candidate,
                source_hash="sha256:first",
                source_meta_json='{"source":"first"}',
            ),
            second_store.complete_prototype_generation_item(
                frozen[1][0].id,
                frozen[1][1].id,
                second_candidate,
                source_hash="sha256:second",
                source_meta_json='{"source":"second"}',
            ),
        )

        assert {first_result.version_no, second_result.version_no} == {1, 2}
        assert first_result.disk_path == first_candidate.disk_path
        assert second_result.disk_path == second_candidate.disk_path
        versions = await first_store.list_prototype_versions(prototype.id)
        positive_versions = [version for version in versions if version.version_no > 0]
        assert [version.version_no for version in positive_versions] == [1, 2]
        assert {version.html for version in positive_versions} == {
            first_candidate.html,
            second_candidate.html,
        }
        reloaded = await first_store.load_prototype(prototype.id)
        assert reloaded is not None
        assert reloaded.current_version == 2
        first_run = await first_store.load_prototype_generation_run(frozen[0][0].id)
        second_run = await first_store.load_prototype_generation_run(frozen[1][0].id)
        assert first_run is not None
        assert second_run is not None
        assert first_run[1][0].version_no == first_result.version_no
        assert second_run[1][0].version_no == second_result.version_no

        before_failed_completion = await first_store.load_prototype(prototype.id)
        assert before_failed_completion is not None
        with pytest.raises(RuntimeError, match="generation item is not generating"):
            await first_store.complete_prototype_generation_item(
                frozen[0][0].id,
                frozen[0][1].id,
                PrototypeVersion(
                    id="must-roll-back",
                    prototype_id=prototype.id,
                    version_no=3,
                    instruction="must roll back",
                    html="<!DOCTYPE html><html><body>rollback</body></html>",
                    created_at=now,
                ),
                source_hash="sha256:must-not-advance",
                source_meta_json='{"source":"must-not-advance"}',
            )
        after_failed_completion = await first_store.load_prototype(prototype.id)
        assert after_failed_completion is not None
        assert after_failed_completion.current_version == 2
        assert after_failed_completion.source_hash == before_failed_completion.source_hash
        assert await first_store.load_prototype_version(prototype.id, 3) is None
    finally:
        await first_store.close()
        await second_store.close()


@pytest.mark.asyncio
async def test_artifact_generation_failure_does_not_advance_source_hash(
    tmp_path: Path,
) -> None:
    store = AsyncSQLiteStore(tmp_path / "generation.db")
    await store._init_db()
    try:
        project = Project(id="project-1", name="demo", repo_path=str(tmp_path))
        await store.save_project(project)
        plan = PrototypePlan(
            id="plan-1",
            project_id=project.id,
            status="ready",
            repository_fingerprint="sha256:repo",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        await store.save_prototype_plan_with_items(plan, [_item(plan.id, "item-1")])
        service = PrototypeGenerationService(
            store=store,
            evidence_service=_Evidence("sha256:repo"),
            governance_gate=lambda _count: _allow(),
            artifact_generator=_FailingArtifactGenerator(),
        )

        run = await service.create_run(plan.id)
        await asyncio.gather(*list(service._tasks))
        loaded = await store.load_prototype_generation_run(run.id)
        prototypes = await store.list_prototypes(project.id)

        assert loaded is not None
        assert loaded[0].status == "failed"
        assert loaded[1][0].status == "failed"
        assert "failed before completion" in (loaded[1][0].error_message or "")
        assert prototypes[0].source_hash is None
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_generation_persists_realtime_activity_without_html_deltas(
    tmp_path: Path,
) -> None:
    store = AsyncSQLiteStore(tmp_path / "generation.db")
    await store._init_db()
    try:
        project = Project(id="project-1", name="demo", repo_path=str(tmp_path))
        await store.save_project(project)
        plan = PrototypePlan(
            id="plan-1",
            project_id=project.id,
            status="ready",
            repository_fingerprint="sha256:repo",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        await store.save_prototype_plan_with_items(plan, [_item(plan.id, "item-1")])
        artifact_generator = _RealtimeArtifactGenerator()
        service = PrototypeGenerationService(
            store=store,
            evidence_service=_Evidence("sha256:repo"),
            governance_gate=lambda _count: _allow(),
            artifact_generator=artifact_generator,
        )

        run = await service.create_run(plan.id)
        await asyncio.wait_for(artifact_generator.activity_persisted.wait(), timeout=2)
        active = await store.load_prototype_generation_run(run.id)

        assert active is not None
        active_run, active_items = active
        assert active_run.processed == 0
        assert active_run.succeeded == 0
        assert active_run.failed == 0
        assert active_run.running == 1
        assert active_run.pending == 0
        assert active_run.started_at is not None
        assert active_run.completed_at is None
        assert active_items[0].phase == "streaming"
        assert active_items[0].output_chars == 2_048
        assert active_items[0].last_event_at is not None
        assert active_items[0].status_message == "正在生成页面"
        assert active_items[0].task_id == "prototype-ui-task-1"
        assert active_items[0].execution_process_id == "execution-process-1"

        artifact_generator.release.set()
        await asyncio.gather(*list(service._tasks))
        finished = await store.load_prototype_generation_run(run.id)

        assert finished is not None
        finished_run, finished_items = finished
        assert finished_run.status == "completed"
        assert finished_run.processed == 1
        assert finished_run.succeeded == 1
        assert finished_run.completed == 1
        assert finished_run.failed == 0
        assert finished_run.running == 0
        assert finished_run.pending == 0
        assert finished_run.completed_at is not None
        assert finished_items[0].phase == "completed"
        assert finished_items[0].output_chars == 2_048
        assert finished_items[0].status_message == "页面生成完成"
        assert finished_items[0].task_id == "prototype-ui-task-1"
        assert finished_items[0].execution_process_id == "execution-process-1"
        assert finished_items[0].completed_at is not None
        assert "x" * 32 not in str(finished_run.to_dict(finished_items))
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_terminal_progress_counts_failures_as_processed(tmp_path: Path) -> None:
    store = AsyncSQLiteStore(tmp_path / "generation.db")
    await store._init_db()
    try:
        project = Project(id="project-1", name="demo", repo_path=str(tmp_path))
        await store.save_project(project)
        plan = PrototypePlan(
            id="plan-1",
            project_id=project.id,
            status="ready",
            repository_fingerprint="sha256:repo",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        items = [_item(plan.id, f"item-{index}") for index in range(13)]
        await store.save_prototype_plan_with_items(plan, items)
        service = PrototypeGenerationService(
            store=store,
            evidence_service=_Evidence("sha256:repo"),
            governance_gate=lambda _count: _allow(),
            artifact_generator=_CountedArtifactGenerator(successes=8),
        )

        run = await service.create_run(plan.id)
        await asyncio.gather(*list(service._tasks))
        loaded = await store.load_prototype_generation_run(run.id)

        assert loaded is not None
        finished, run_items = loaded
        assert finished.status == "partial"
        assert finished.total == 13
        assert finished.processed == 13
        assert finished.succeeded == 8
        assert finished.completed == 8
        assert finished.failed == 5
        assert finished.running == 0
        assert finished.pending == 0
        assert sum(item.status == "done" for item in run_items) == 8
        assert sum(item.status == "failed" for item in run_items) == 5
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_restart_marks_active_items_processed_and_interrupted(tmp_path: Path) -> None:
    store = AsyncSQLiteStore(tmp_path / "generation.db")
    await store._init_db()
    try:
        project = Project(id="project-1", name="demo", repo_path=str(tmp_path))
        await store.save_project(project)
        plan = PrototypePlan(
            id="plan-1",
            project_id=project.id,
            status="ready",
            repository_fingerprint="sha256:repo",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        await store.save_prototype_plan_with_items(plan, [_item(plan.id, "item-1")])
        artifact_generator = _BlockingArtifactGenerator()
        service = PrototypeGenerationService(
            store=store,
            evidence_service=_Evidence("sha256:repo"),
            governance_gate=lambda _count: _allow(),
            artifact_generator=artifact_generator,
        )

        run = await service.create_run(plan.id)
        await asyncio.wait_for(artifact_generator.started.wait(), timeout=2)
        interrupted = await store.interrupt_active_prototype_generation_runs()
        tasks = list(service._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        loaded = await store.load_prototype_generation_run(run.id)

        assert interrupted == 1
        assert loaded is not None
        interrupted_run, interrupted_items = loaded
        assert interrupted_run.status == "interrupted"
        assert interrupted_run.processed == 1
        assert interrupted_run.succeeded == 0
        assert interrupted_run.failed == 1
        assert interrupted_run.running == 0
        assert interrupted_run.pending == 0
        assert interrupted_run.completed_at is not None
        assert interrupted_items[0].status == "interrupted"
        assert interrupted_items[0].phase == "interrupted"
        assert interrupted_items[0].last_event_at is not None
        assert interrupted_items[0].completed_at is not None
        assert interrupted_items[0].status_message == "生成已中断"
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_restart_normalizes_stale_item_after_run_was_already_interrupted(
    tmp_path: Path,
) -> None:
    store = AsyncSQLiteStore(tmp_path / "generation-stale-item.db")
    await store._init_db()
    try:
        project = Project(id="project-1", name="demo", repo_path=str(tmp_path))
        await store.save_project(project)
        plan = PrototypePlan(
            id="plan-1",
            project_id=project.id,
            status="ready",
            repository_fingerprint="sha256:repo",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        await store.save_prototype_plan_with_items(plan, [_item(plan.id, "item-1")])
        artifact_generator = _BlockingArtifactGenerator()
        service = PrototypeGenerationService(
            store=store,
            evidence_service=_Evidence("sha256:repo"),
            governance_gate=lambda _count: _allow(),
            artifact_generator=artifact_generator,
        )

        run = await service.create_run(plan.id)
        await asyncio.wait_for(artifact_generator.started.wait(), timeout=2)
        await store.update_prototype_generation_run(run.id, status="interrupted")
        tasks = list(service._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

        # Simulate a boot after the run status was persisted but before its
        # generating item was reconciled.
        assert await store.interrupt_active_prototype_generation_runs() == 0
        loaded = await store.load_prototype_generation_run(run.id)

        assert loaded is not None
        recovered_run, recovered_items = loaded
        assert recovered_run.status == "interrupted"
        assert recovered_run.processed == 1
        assert recovered_run.failed == 1
        assert recovered_items[0].status == "interrupted"
        assert recovered_items[0].phase == "interrupted"
        assert recovered_items[0].status_message == "生成已中断"
        assert recovered_items[0].error_message == "后端重启时页面仍在生成, 任务已中断"
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_v5_migration_removes_skipped_items_from_failed_count(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "generation-v5.db"
    store = AsyncSQLiteStore(db_path)
    migrated_store: AsyncSQLiteStore | None = None
    await store._init_db()
    blocker = _BlockingArtifactGenerator()
    service: PrototypeGenerationService | None = None
    try:
        project = Project(id="project-1", name="demo", repo_path=str(tmp_path))
        await store.save_project(project)
        plan = PrototypePlan(
            id="plan-1",
            project_id=project.id,
            status="ready",
            repository_fingerprint="sha256:repo",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        plan_item = _item(plan.id, "item-1")
        plan_item.evidence = [
            {
                "evidence_id": "evidence--item-1",
                "path": "src/Page.tsx",
                "start_line": 1,
                "end_line": 2,
                "kind": "page-source",
                "detail": "page source",
                "content": "source",
            }
        ]
        plan_item.evidence_ids = ["evidence--item-1"]
        await store.save_prototype_plan_with_items(plan, [plan_item])
        service = PrototypeGenerationService(
            store=store,
            evidence_service=_Evidence("sha256:repo"),
            governance_gate=lambda _count: _allow(),
            artifact_generator=blocker,
        )
        run = await service.create_run(plan.id)
        await asyncio.wait_for(blocker.started.wait(), timeout=2)
        tasks = list(service._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

        loaded = await store.load_prototype_generation_run(run.id)
        assert loaded is not None
        await store.update_prototype_generation_item(
            run.id,
            loaded[1][0].id,
            status="skipped",
            phase="skipped",
        )
        skipped = await store.load_prototype_generation_run(run.id)
        assert skipped is not None
        assert skipped[0].processed == 1
        assert skipped[0].failed == 0

        connection = await store._get_conn()
        await connection.execute(
            "UPDATE prototype_generation_runs SET failed = 1 WHERE id = ?",
            (run.id,),
        )
        await connection.execute("UPDATE schema_version SET version = 5 WHERE id = 1")
        await connection.commit()
        await store.close()

        migrated_store = AsyncSQLiteStore(db_path)
        await migrated_store._init_db()
        migrated = await migrated_store.load_prototype_generation_run(run.id)
        assert migrated is not None
        assert migrated[0].processed == 1
        assert migrated[0].failed == 0
        migrated_connection = await migrated_store._get_conn()
        cursor = await migrated_connection.execute(
            "SELECT version FROM schema_version WHERE id = 1"
        )
        schema_version = await cursor.fetchone()
        assert schema_version is not None
        assert schema_version[0] == 11
    finally:
        blocker.release.set()
        if service is not None:
            tasks = list(service._tasks)
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
        await store.close()
        if migrated_store is not None:
            await migrated_store.close()


@pytest.mark.asyncio
async def test_v7_migration_restores_failed_item_seed_before_retry(tmp_path: Path) -> None:
    db_path = tmp_path / "generation-seed-v6.db"
    store = AsyncSQLiteStore(db_path)
    migrated_store: AsyncSQLiteStore | None = None
    first_service: PrototypeGenerationService | None = None
    retry_service: PrototypeGenerationService | None = None
    await store._init_db()
    try:
        project = Project(id="project-1", name="VideoNote", repo_path=str(tmp_path))
        await store.save_project(project)
        plan = PrototypePlan(
            id="plan-seed-v6",
            project_id=project.id,
            status="ready",
            repository_fingerprint="sha256:repo",
            global_instruction="Keep the reviewed restore baseline.",
            output_locale="en-US",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        plan_item = _item(plan.id, "item-seed-v6")
        plan_item.evidence = [
            {
                "evidence_id": "evidence--seed-v6",
                "path": "src/Page.tsx",
                "start_line": 1,
                "end_line": 2,
                "kind": "page-source",
                "detail": "page source",
                "content": "source",
            }
        ]
        plan_item.evidence_ids = ["evidence--seed-v6"]
        expected_seed = PrototypeGenerationService._restore_seed(plan, plan_item)
        await store.save_prototype_plan_with_items(plan, [plan_item])
        first_service = PrototypeGenerationService(
            store=store,
            evidence_service=_Evidence("sha256:repo"),
            governance_gate=lambda _count: _allow(),
            artifact_generator=_FailingArtifactGenerator(),
        )

        failed_run = await first_service.create_run(plan.id)
        await asyncio.gather(*list(first_service._tasks))
        failed = await store.load_prototype_generation_run(failed_run.id)
        assert failed is not None
        assert failed[1][0].status == "failed"
        assert failed[1][0].seed_brief == expected_seed

        connection = await store._get_conn()
        await connection.execute(
            "UPDATE prototype_generation_run_items SET seed_brief = '' WHERE id = ?",
            (failed[1][0].id,),
        )
        await connection.execute("UPDATE schema_version SET version = 6 WHERE id = 1")
        await connection.commit()
        await store.close()

        migrated_store = AsyncSQLiteStore(db_path)
        migrated = await migrated_store.load_prototype_generation_run(failed_run.id)
        assert migrated is not None
        assert migrated[1][0].seed_brief == expected_seed

        artifact_generator = _ArtifactGenerator()
        retry_service = PrototypeGenerationService(
            store=migrated_store,
            evidence_service=_Evidence("sha256:repo"),
            governance_gate=lambda _count: _allow(),
            artifact_generator=artifact_generator,
        )
        retried_run = await retry_service.retry(plan.id, failed_run.id)
        await asyncio.gather(*list(retry_service._tasks))
        retried = await migrated_store.load_prototype_generation_run(retried_run.id)
        assert retried is not None
        assert retried_run.id != failed_run.id
        assert retried[0].status == "completed"
        retry_items = retried[1]
        assert retry_items[0].prototype_id is not None
        version = await migrated_store.load_prototype_version(
            retry_items[0].prototype_id,
            retry_items[0].version_no or 0,
        )
        assert version is not None
        assert version.instruction == expected_seed
    finally:
        if first_service is not None and first_service._tasks:
            await asyncio.gather(*list(first_service._tasks), return_exceptions=True)
        if retry_service is not None and retry_service._tasks:
            await asyncio.gather(*list(retry_service._tasks), return_exceptions=True)
        await store.close()
        if migrated_store is not None:
            await migrated_store.close()
