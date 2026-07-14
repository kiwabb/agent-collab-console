from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

import pytest

from app.adapters.async_sqlite_store import AsyncSQLiteStore
from app.application.llm_runner import LLMOutputTokenLimitError
from app.application.prototype_planning_mcp import PrototypePlanningMcpService
from app.application.prototype_planning_service import PrototypePlanError, PrototypePlanService
from app.domain.models import Project, Prototype, PrototypeVersion
from app.domain.project_evidence import (
    EvidenceLocation,
    PackageSurface,
    ProjectSurfaceManifest,
    PrototypeCandidate,
)
from app.domain.prototype_plan import (
    PlanAction,
    PlanOutputLocale,
    PrototypePlan,
    PrototypePlanItem,
    PrototypePlanSelectionUpdate,
)


def _manifest() -> ProjectSurfaceManifest:
    candidate = PrototypeCandidate(
        candidate_id="candidate-home",
        title="Home",
        route_patterns=("/",),
        surface_kind="web",
        package_root="frontend",
        framework_hint="react-router",
        primary_source_path="frontend/src/App.tsx",
        source_paths=("frontend/src/App.tsx",),
        layout_paths=(),
        evidence=(
            EvidenceLocation(
                "frontend/src/App.tsx",
                10,
                12,
                "react-router-route",
                "Home -> /",
                confidence="high",
            ),
        ),
        confidence="high",
        source_hash="sha256:home",
    )
    return ProjectSurfaceManifest(
        repository_root="/tmp/project",
        packages=(
            PackageSurface(
                package_root="frontend",
                manifest_path="frontend/package.json",
                name="frontend",
                framework_signals=("react-router",),
                surface_kind="web",
                support="supported",
            ),
        ),
        candidates=(candidate,),
        repository_fingerprint="sha256:repo",
    )


def _english_context() -> dict[str, str]:
    return {
        "product_summary": "A focused video workspace",
        "audience": "Video editors",
        "visual_language": "A dense professional interface",
        "shared_layout": "A persistent navigation shell",
    }


def _chinese_context() -> dict[str, str]:
    return {
        "product_summary": "专注的视频笔记工作区",
        "audience": "视频创作者和编辑",
        "visual_language": "紧凑而专业的界面",
        "shared_layout": "包含固定导航的共享布局",
    }


def test_planning_prompt_uses_a_source_index_not_embedded_source_excerpts() -> None:
    manifest = _manifest()
    candidate = manifest.candidates[0]
    evidence = candidate.evidence[0]
    manifest = ProjectSurfaceManifest(
        repository_root=manifest.repository_root,
        packages=manifest.packages,
        candidates=(
            PrototypeCandidate(
                candidate_id=candidate.candidate_id,
                title=candidate.title,
                route_patterns=candidate.route_patterns,
                surface_kind=candidate.surface_kind,
                package_root=candidate.package_root,
                framework_hint=candidate.framework_hint,
                primary_source_path=candidate.primary_source_path,
                source_paths=candidate.source_paths,
                layout_paths=candidate.layout_paths,
                evidence=(
                    EvidenceLocation(
                        evidence.path,
                        evidence.start_line,
                        evidence.end_line,
                        evidence.kind,
                        evidence.detail,
                        content="x" * 200_000,
                        confidence=evidence.confidence,
                    ),
                ),
                confidence=candidate.confidence,
                source_hash=candidate.source_hash,
            ),
        ),
        repository_fingerprint=manifest.repository_fingerprint,
    )
    store = _MemoryStore()
    service = PrototypePlanService(store=store)
    plan = PrototypePlan(
        id="plan-1",
        project_id="p1",
        status="queued",
        repository_fingerprint=manifest.repository_fingerprint,
        output_locale="en-US",
    )

    prompt = service._build_prompt(store.project, plan, manifest)

    assert "Read the real project source" in prompt
    assert "source map, not source content" in prompt
    assert "return the page checklist derived from that code" in prompt
    assert '"evidence_id"' in prompt
    assert '"path": "frontend/src/App.tsx"' in prompt
    assert '"content"' not in prompt
    assert len(prompt) < 10_000


def test_plan_diagnostics_follow_output_locale_with_package_prefix() -> None:
    source = (
        "VideoMemo_extension: browser extension surface is detected but not supported in MVP",
    )

    assert PrototypePlanService._localized_diagnostics("zh-CN", source) == [
        "VideoMemo_extension: 检测到浏览器扩展界面, 当前版本暂不支持"
    ]
    assert PrototypePlanService._localized_diagnostics("en-US", source) == list(source)


class _MemoryStore:
    def __init__(self) -> None:
        self.project = Project(id="p1", name="Demo", repo_path="/tmp/project")
        self.prototypes: list[Prototype] = []
        self.plans: dict[str, tuple[PrototypePlan, list[PrototypePlanItem]]] = {}
        self.progress_history: list[tuple[int, int]] = []

    async def load_project(self, project_id: str) -> Project | None:
        return self.project if project_id == self.project.id else None

    async def list_prototypes(self, project_id: str) -> list[Prototype]:
        return self.prototypes

    async def load_prototype_version(
        self, prototype_id: str, version_no: int
    ) -> PrototypeVersion | None:
        return None

    async def save_prototype_plan_with_items(
        self, plan: PrototypePlan, items: list[PrototypePlanItem]
    ) -> None:
        self.plans[plan.id] = (plan, items)
        self.progress_history.append((plan.analysis_completed, plan.analysis_total))

    async def upsert_prototype_plan_item(
        self, plan: PrototypePlan, item: PrototypePlanItem
    ) -> None:
        _, items = self.plans[plan.id]
        self.plans[plan.id] = (
            plan,
            [*filter(lambda entry: entry.candidate_id != item.candidate_id, items), item],
        )
        self.progress_history.append((plan.analysis_completed, plan.analysis_total))

    async def load_prototype_plan(
        self, plan_id: str
    ) -> tuple[PrototypePlan, list[PrototypePlanItem]] | None:
        return self.plans.get(plan_id)

    async def load_prototype_plan_by_item(
        self, item_id: str
    ) -> tuple[PrototypePlan, list[PrototypePlanItem]] | None:
        for plan, items in self.plans.values():
            if any(item.id == item_id for item in items):
                return plan, items
        return None

    async def load_latest_prototype_plan_for_project(
        self, project_id: str
    ) -> tuple[PrototypePlan, list[PrototypePlanItem]] | None:
        matches = [value for value in self.plans.values() if value[0].project_id == project_id]
        return matches[-1] if matches else None

    async def update_prototype_plan_selection(
        self,
        plan_id: str,
        item_ids: tuple[str, ...],
        *,
        selected: bool,
        updated_at: datetime,
    ) -> PrototypePlanSelectionUpdate:
        loaded = self.plans.get(plan_id)
        if loaded is None:
            return PrototypePlanSelectionUpdate(status="plan_not_found")
        plan, items = loaded
        if plan.status not in {"ready", "stale"}:
            return PrototypePlanSelectionUpdate(status="not_editable")
        items_by_id = {item.id: item for item in items}
        missing = tuple(sorted(set(item_ids) - items_by_id.keys()))
        if missing:
            return PrototypePlanSelectionUpdate(status="item_not_found", item_ids=missing)
        ineligible = tuple(
            sorted(
                item_id
                for item_id in item_ids
                if items_by_id[item_id].action not in {"create", "update"}
            )
        )
        if ineligible:
            return PrototypePlanSelectionUpdate(status="ineligible", item_ids=ineligible)
        for item_id in item_ids:
            items_by_id[item_id].selected = selected
            items_by_id[item_id].updated_at = updated_at
        plan.updated_at = updated_at
        return PrototypePlanSelectionUpdate(status="updated", item_ids=item_ids)


@pytest.mark.asyncio
async def test_mcp_registers_pages_incrementally_and_requires_route_listing() -> None:
    store = _MemoryStore()
    service = PrototypePlanService(store=store, evidence_service=_Evidence())
    manifest = _manifest()
    plan = PrototypePlan(
        id="plan-mcp",
        project_id="p1",
        status="analyzing",
        repository_fingerprint=manifest.repository_fingerprint,
        output_locale="zh-CN",
        analysis_phase="planning",
        analysis_total=1,
    )
    await store.save_prototype_plan_with_items(plan, [])
    mcp = PrototypePlanningMcpService(service)
    session = mcp.open_session(project=store.project, plan_id=plan.id, manifest=manifest)

    status, tools_response = await mcp.handle(
        token=session.token,
        payload={"jsonrpc": "2.0", "id": 0, "method": "tools/list"},
    )
    assert status == 200
    assert tools_response is not None
    tools_result = tools_response["result"]
    assert isinstance(tools_result, dict)
    tools = tools_result["tools"]
    assert isinstance(tools, list)
    register_tool = next(tool for tool in tools if tool["name"] == "register_prototype_page")
    assert "states" not in register_tool["inputSchema"]["required"]

    status, listed = await mcp.handle(
        token=session.token,
        payload={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "list_discovered_pages", "arguments": {}},
        },
    )
    assert status == 200
    assert listed is not None
    result = listed["result"]
    assert isinstance(result, dict)
    content = result["content"]
    assert isinstance(content, list)
    compact_manifest = json.loads(content[0]["text"])
    assert "content" not in compact_manifest["pages"][0]

    candidate = manifest.candidates[0]
    status, registered = await mcp.handle(
        token=session.token,
        payload={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "register_prototype_page",
                "arguments": {
                    "candidate_id": candidate.candidate_id,
                    "title": "VideoNote 首页",
                    "summary": "展示视频笔记工作区首页.",
                    "brief": "按照当前源码还原首页.",
                    "evidence_ids": [candidate.evidence[0].evidence_id],
                },
            },
        },
    )
    assert status == 200
    assert registered is not None
    registered_result = registered["result"]
    assert isinstance(registered_result, dict)
    assert registered_result["isError"] is False, registered_result
    live_plan, live_items = await service.get_plan(plan.id)
    assert live_plan.analysis_completed == 1
    assert live_items[0].states == list(candidate.states)
    assert live_items[0].review_status == "provisional"

    status, finalized = await mcp.handle(
        token=session.token,
        payload={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "finalize_prototype_inventory",
                "arguments": {"project_context": _chinese_context()},
            },
        },
    )
    assert status == 200
    assert finalized is not None
    completed, completed_items = await service.get_plan(plan.id)
    assert completed.status == "ready"
    assert completed_items[0].review_status == "confirmed"

    mcp.close_session(session)
    status, _ = await mcp.handle(
        token=session.token,
        payload={"jsonrpc": "2.0", "id": 4, "method": "tools/list"},
    )
    assert status == 401


@pytest.mark.asyncio
async def test_mcp_keeps_valid_non_static_page_pending_confirmation(tmp_path: Path) -> None:
    source = tmp_path / "src" / "Feature.tsx"
    source.parent.mkdir()
    source.write_text(
        "export function Feature() { return <main>Feature</main>; }\n", encoding="utf-8"
    )
    store = _MemoryStore()
    store.project = Project(id="p1", name="Demo", repo_path=str(tmp_path))
    service = PrototypePlanService(store=store, evidence_service=_Evidence())
    manifest = _manifest()
    plan = PrototypePlan(
        id="plan-extra",
        project_id="p1",
        status="analyzing",
        repository_fingerprint=manifest.repository_fingerprint,
        output_locale="en-US",
        analysis_phase="planning",
        analysis_total=1,
    )
    await store.save_prototype_plan_with_items(plan, [])
    mcp = PrototypePlanningMcpService(service)
    session = mcp.open_session(project=store.project, plan_id=plan.id, manifest=manifest)

    status, invalid_response = await mcp.handle(
        token=session.token,
        payload={
            "jsonrpc": "2.0",
            "id": 0,
            "method": "tools/call",
            "params": {
                "name": "register_prototype_page",
                "arguments": {
                    "title": "Feature",
                    "summary": "Shows an experimental feature page.",
                    "brief": "Restore the feature page.",
                    "states": ["default"],
                    "evidence_ids": [],
                    "source_paths": ["src/Feature.tsx"],
                    "route_patterns": ["/feature"],
                    "evidence": [
                        {
                            "path": "src/Feature.tsx",
                            "start_line": 1,
                            "end_line": 2,
                            "detail": "Feature component",
                        }
                    ],
                },
            },
        },
    )
    assert status == 200
    assert invalid_response is not None
    invalid_result = invalid_response["result"]
    assert isinstance(invalid_result, dict)
    assert invalid_result["isError"] is True
    assert "outside the source file" in invalid_result["content"][0]["text"]

    status, response = await mcp.handle(
        token=session.token,
        payload={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "register_prototype_page",
                "arguments": {
                    "title": "Feature",
                    "summary": "Shows an experimental feature page.",
                    "brief": "Restore the feature page.",
                    "states": ["default"],
                    "evidence_ids": [],
                    "source_paths": ["src/Feature.tsx"],
                    "route_patterns": ["/feature"],
                    "evidence": [
                        {
                            "path": "src/Feature.tsx",
                            "start_line": 1,
                            "end_line": 1,
                            "detail": "Feature component",
                        }
                    ],
                },
            },
        },
    )

    assert status == 200
    assert response is not None
    _, items = await service.get_plan(plan.id)
    assert items[0].discovery_origin == "claude"
    assert items[0].review_status == "needs_confirmation"
    assert items[0].selected is False


@pytest.mark.asyncio
async def test_mcp_completion_is_not_overwritten_by_outer_analysis_snapshot() -> None:
    store = _MemoryStore()
    manifest = _manifest()

    class _Mcp:
        def open_session(
            self, *, project: Project, plan_id: str, manifest: ProjectSurfaceManifest
        ) -> object:
            return object()

        def close_session(self, session: object) -> None:
            return None

    class _McpPlanService(PrototypePlanService):
        async def _plan_with_mcp(
            self,
            _project: Project,
            active_plan: PrototypePlan,
            _manifest: ProjectSurfaceManifest,
        ) -> None:
            active_plan.status = "ready"
            active_plan.analysis_phase = "complete"
            active_plan.analysis_completed = len(manifest.candidates)
            active_plan.analysis_total = len(manifest.candidates)
            active_plan.project_context = _chinese_context()
            active_plan.updated_at = datetime.now()
            await store.save_prototype_plan_with_items(active_plan, [])

    service = _McpPlanService(
        store=store,
        evidence_service=_Evidence(),
        ui_engineer=_UIEngineer('{"project_context":{},"items":[]}'),
        mcp_service=_Mcp(),
    )
    plan = await service.create_plan("p1")
    completed, _ = await service.wait_for_analysis(plan.id)

    assert completed.status == "ready"
    assert completed.analysis_phase == "complete"
    assert completed.analysis_completed == completed.analysis_total == 1


class _Evidence:
    def scan_project(self, project: Project) -> ProjectSurfaceManifest:
        return _manifest()


class _UIEngineer:
    def __init__(self, result: str) -> None:
        self.result = result
        self.calls: list[tuple[str, str, tuple[str, ...]]] = []

    async def plan(
        self,
        *,
        project: Project,
        plan_id: str,
        prompt: str,
        source_paths: tuple[str, ...],
        activity_callback=None,
        mcp_config: str | None = None,
    ) -> str:
        self.calls.append((project.id, plan_id, source_paths))
        assert "prototype UI engineer" in prompt
        assert "States are stable machine identifiers" in prompt
        return self.result


class _ChangingEvidence:
    def __init__(self) -> None:
        self.calls = 0

    def scan_project(self, project: Project) -> ProjectSurfaceManifest:
        self.calls += 1
        manifest = _manifest()
        return ProjectSurfaceManifest(
            repository_root=manifest.repository_root,
            packages=manifest.packages,
            candidates=manifest.candidates,
            repository_fingerprint=f"sha256:repo-{self.calls}",
        )


@pytest.mark.asyncio
async def test_plan_analysis_persists_restore_brief_and_item_selection() -> None:
    store = _MemoryStore()

    async def llm(prompt: str) -> str:
        assert "mode" in prompt
        return json.dumps(
            {
                "project_context": _chinese_context(),
                "items": [
                    {
                        "candidate_id": "candidate-home",
                        "title": "VideoNote 首页基线",
                        "summary": "展示主要视频工作区.",
                        "brief": "将当前首页还原为单文件 HTML 原型.",
                        "states": ["default", "empty"],
                        "evidence_ids": [_manifest().candidates[0].evidence[0].evidence_id],
                    }
                ],
            }
        )

    service = PrototypePlanService(store=store, evidence_service=_Evidence(), llm_runner=llm)
    plan = await service.create_plan("p1")
    assert plan.status == "queued"
    finished, items = await service.wait_for_analysis(plan.id)

    assert finished.status == "ready"
    assert finished.project_context == _chinese_context()
    assert len(items) == 1
    assert items[0].selected is True
    assert items[0].action == "create"
    assert items[0].brief.startswith("将当前")
    assert items[0].evidence[0]["kind"] == "react-router-route"
    assert items[0].evidence[0]["confidence"] == "high"
    assert items[0].evidence[0]["diagnostic"] is None


@pytest.mark.asyncio
async def test_plan_analysis_prefers_ui_engineer_and_keeps_states_as_identifiers() -> None:
    store = _MemoryStore()
    evidence_id = _manifest().candidates[0].evidence[0].evidence_id
    ui_engineer = _UIEngineer(
        json.dumps(
            {
                "project_context": _chinese_context(),
                "items": [
                    {
                        "candidate_id": "candidate-home",
                        "title": "VideoNote 首页基线",
                        "summary": "展示主要视频工作区.",
                        "brief": "按照项目源码还原当前首页.",
                        "states": ["default", "loading", "empty", "error", "collections-:id"],
                        "evidence_ids": [evidence_id],
                    }
                ],
            },
            ensure_ascii=False,
        )
    )

    async def unexpected_http_runner(_prompt: str) -> str:
        raise AssertionError("direct HTTP planner must not run when the UI engineer is configured")

    service = PrototypePlanService(
        store=store,
        evidence_service=_Evidence(),
        ui_engineer=ui_engineer,
        llm_runner=unexpected_http_runner,
    )
    plan = await service.create_plan("p1", output_locale="zh-CN")
    finished, items = await service.wait_for_analysis(plan.id)

    assert finished.status == "ready"
    assert items[0].states == ["default", "loading", "empty", "error", "collections-:id"]
    assert ui_engineer.calls == [
        (
            "p1",
            plan.id,
            ("frontend/package.json", "frontend/src/App.tsx"),
        )
    ]


@pytest.mark.asyncio
async def test_plan_analysis_batches_large_candidate_sets() -> None:
    base = _manifest()
    candidates = tuple(
        PrototypeCandidate(
            candidate_id=f"candidate-{index}",
            title=f"Page {index}",
            route_patterns=(f"/page-{index}",),
            surface_kind="web",
            package_root="frontend",
            framework_hint="react-router",
            primary_source_path=f"frontend/src/Page{index}.tsx",
            source_paths=(f"frontend/src/Page{index}.tsx",),
            layout_paths=(),
            evidence=(
                EvidenceLocation(
                    f"frontend/src/Page{index}.tsx",
                    1,
                    3,
                    "react-router-route",
                    f"Page {index}",
                ),
            ),
            confidence="high",
            source_hash=f"sha256:page-{index}",
        )
        for index in range(7)
    )
    manifest = ProjectSurfaceManifest(
        repository_root=base.repository_root,
        packages=base.packages,
        candidates=candidates,
        repository_fingerprint=base.repository_fingerprint,
    )

    class _BatchEvidence:
        def scan_project(self, project: Project) -> ProjectSurfaceManifest:
            return manifest

    calls: list[list[int]] = []

    async def llm(prompt: str) -> str:
        indexes = [index for index in range(7) if f'"candidate_id": "candidate-{index}"' in prompt]
        calls.append(indexes)
        context = (
            {"product_summary": "Batched app", "audience": "Editors"}
            if indexes[0] == 0
            else {"visual_language": "Dense workspace", "shared_layout": "Sidebar shell"}
        )
        return json.dumps(
            {
                "project_context": context,
                "items": [
                    {
                        "candidate_id": f"candidate-{index}",
                        "title": f"Page {index}",
                        "summary": f"Summary {index}",
                        "brief": f"Restore page {index}.",
                        "states": ["default"],
                        "evidence_ids": [candidates[index].evidence[0].evidence_id],
                    }
                    for index in indexes
                ],
            }
        )

    store = _MemoryStore()
    service = PrototypePlanService(
        store=store,
        evidence_service=_BatchEvidence(),
        llm_runner=llm,
    )
    plan = await service.create_plan("p1", output_locale="en-US")
    finished, items = await service.wait_for_analysis(plan.id)

    assert finished.status == "ready"
    assert calls == [list(range(6)), [6]]
    assert len(items) == 7
    assert finished.project_context == {
        "product_summary": "Batched app",
        "audience": "Editors",
        "visual_language": "Dense workspace",
        "shared_layout": "Sidebar shell",
    }


@pytest.mark.asyncio
async def test_max_token_batch_recursively_splits_and_persists_bounded_progress() -> None:
    base = _manifest()
    candidates = tuple(
        PrototypeCandidate(
            candidate_id=f"candidate-{index}",
            title=f"Page {index}",
            route_patterns=(f"/page-{index}",),
            surface_kind="web",
            package_root="frontend",
            framework_hint="react-router",
            primary_source_path=f"frontend/src/Page{index}.tsx",
            source_paths=(f"frontend/src/Page{index}.tsx",),
            layout_paths=(),
            evidence=(
                EvidenceLocation(
                    f"frontend/src/Page{index}.tsx",
                    1,
                    3,
                    "react-router-route",
                    f"Page {index}",
                ),
            ),
            confidence="high",
            source_hash=f"sha256:page-{index}",
        )
        for index in range(4)
    )
    manifest = ProjectSurfaceManifest(
        repository_root=base.repository_root,
        packages=base.packages,
        candidates=candidates,
        repository_fingerprint=base.repository_fingerprint,
    )

    class _SplitEvidence:
        def scan_project(self, project: Project) -> ProjectSurfaceManifest:
            return manifest

    calls: list[list[int]] = []

    async def llm(prompt: str) -> str:
        indexes = [index for index in range(4) if f'"candidate_id": "candidate-{index}"' in prompt]
        calls.append(indexes)
        if len(indexes) > 2:
            raise LLMOutputTokenLimitError("truncated")
        return json.dumps(
            {
                "project_context": _english_context(),
                "items": [
                    {
                        "candidate_id": f"candidate-{index}",
                        "title": f"Page {index}",
                        "summary": f"Summary {index}",
                        "brief": f"Restore page {index}.",
                        "states": ["default"],
                        "evidence_ids": [candidates[index].evidence[0].evidence_id],
                    }
                    for index in indexes
                ],
            }
        )

    store = _MemoryStore()
    service = PrototypePlanService(
        store=store,
        evidence_service=_SplitEvidence(),
        llm_runner=llm,
    )
    plan = await service.create_plan("p1", output_locale="en-US")
    finished, items = await service.wait_for_analysis(plan.id)

    assert finished.status == "ready"
    assert calls == [list(range(4)), [0, 1], [2, 3]]
    assert len(items) == 4
    assert (finished.analysis_completed, finished.analysis_total) == (2, 2)
    assert (0, 2) in store.progress_history
    assert all(completed <= total for completed, total in store.progress_history)


@pytest.mark.asyncio
async def test_single_candidate_max_token_failure_is_explicit() -> None:
    store = _MemoryStore()

    async def llm(_prompt: str) -> str:
        raise LLMOutputTokenLimitError("truncated")

    service = PrototypePlanService(store=store, evidence_service=_Evidence(), llm_runner=llm)
    plan = await service.create_plan("p1", output_locale="en-US")
    finished, items = await service.wait_for_analysis(plan.id)

    assert finished.status == "analysis_failed"
    assert finished.error_message == "prototype planning reached the token limit for a single page"
    assert items == []


@pytest.mark.asyncio
async def test_invalid_planner_output_fails_closed_and_streams_terminal_snapshot() -> None:
    store = _MemoryStore()

    async def llm(prompt: str) -> str:
        return "not json"

    service = PrototypePlanService(store=store, evidence_service=_Evidence(), llm_runner=llm)
    plan = await service.create_plan("p1", output_locale="en-US")
    finished, items = await service.wait_for_analysis(plan.id)

    assert finished.status == "analysis_failed"
    assert finished.error_message == "prototype planning runtime returned invalid JSON"
    assert items == []
    events = [event async for event in service.stream_events(plan.id)]
    data = events[-1]["data"]
    assert isinstance(data, dict)
    assert data["status"] == "analysis_failed"


@pytest.mark.asyncio
async def test_planner_repairs_minimax_unescaped_jsx_quote_before_schema_validation() -> None:
    store = _MemoryStore()
    evidence_id = _manifest().candidates[0].evidence[0].evidence_id

    async def llm(prompt: str) -> str:
        return (
            '{"project_context":' + json.dumps(_english_context()) + ',"items":[{'
            '"candidate_id":"candidate-home",'
            '"title":"Home","summary":"Summary",'
            '"brief":"Render <Loader className=\\"h-6 text-neutral-400" /> safely.",'
            '"states":["default"],'
            f'"evidence_ids":["{evidence_id}"]'
            "}]}"
        )

    service = PrototypePlanService(store=store, evidence_service=_Evidence(), llm_runner=llm)
    plan = await service.create_plan("p1", output_locale="en-US")
    finished, items = await service.wait_for_analysis(plan.id)

    assert finished.status == "ready"
    assert len(items) == 1
    assert items[0].brief.startswith("Render <Loader")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "variant",
    [
        "fence",
        "prose",
        "truncated",
        "missing_array_closer",
        "open_string_truncated",
        "nested_open_string_truncated",
        "multiple",
    ],
)
async def test_planner_repair_rejects_non_single_or_incomplete_json_envelopes(
    variant: str,
) -> None:
    store = _MemoryStore()
    evidence_id = _manifest().candidates[0].evidence[0].evidence_id
    valid = json.dumps(
        {
            "project_context": _english_context(),
            "items": [
                {
                    "candidate_id": "candidate-home",
                    "title": "Home",
                    "summary": "Summary",
                    "brief": "Restore home.",
                    "states": ["default"],
                    "evidence_ids": [evidence_id],
                }
            ],
        }
    )
    raw_by_variant = {
        "fence": f"```json\n{valid}\n```",
        "prose": f"Model result:\n{valid}",
        "truncated": valid[:-1],
        "missing_array_closer": valid[:-2] + "}",
        "open_string_truncated": (
            '{"project_context":'
            + json.dumps(_english_context())
            + ',"items":[{"candidate_id":"candidate-home","title":"Home",'
            '"summary":"Summary","states":["default"],'
            f'"evidence_ids":["{evidence_id}"],"brief":"truncated }}'
        ),
        "nested_open_string_truncated": (
            '{"project_context":{"product_summary":"truncated nested object }'
        ),
        "multiple": valid + valid,
    }

    async def llm(_prompt: str) -> str:
        return raw_by_variant[variant]

    service = PrototypePlanService(store=store, evidence_service=_Evidence(), llm_runner=llm)
    plan = await service.create_plan("p1", output_locale="en-US")
    finished, items = await service.wait_for_analysis(plan.id)

    assert finished.status == "analysis_failed"
    assert finished.error_message == "prototype planning runtime returned invalid JSON"
    assert items == []


@pytest.mark.asyncio
async def test_planner_rejects_duplicate_evidence_ids_before_persistence() -> None:
    store = _MemoryStore()
    evidence_id = _manifest().candidates[0].evidence[0].evidence_id

    async def llm(_prompt: str) -> str:
        return json.dumps(
            {
                "project_context": _english_context(),
                "items": [
                    {
                        "candidate_id": "candidate-home",
                        "title": "Home",
                        "summary": "Summary",
                        "brief": "Restore home.",
                        "states": ["default"],
                        "evidence_ids": [evidence_id, evidence_id],
                    }
                ],
            }
        )

    service = PrototypePlanService(store=store, evidence_service=_Evidence(), llm_runner=llm)
    plan = await service.create_plan("p1", output_locale="en-US")
    finished, items = await service.wait_for_analysis(plan.id)

    assert finished.status == "analysis_failed"
    assert finished.error_message == (
        "prototype planning result did not match the required schema: items.0.evidence_ids"
    )
    assert items == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("locale", "context", "title", "summary", "brief", "states", "error_fragment"),
    [
        (
            "zh-CN",
            _english_context(),
            "Home",
            "Home summary",
            "Restore home.",
            ["default"],
            "未遵循 zh-CN",
        ),
        (
            "en-US",
            _chinese_context(),
            "首页",
            "首页摘要",
            "还原首页.",
            ["default"],
            "did not follow the en-US",
        ),
    ],
)
async def test_planner_rejects_model_copy_in_the_wrong_locale(
    locale: PlanOutputLocale,
    context: dict[str, str],
    title: str,
    summary: str,
    brief: str,
    states: list[str],
    error_fragment: str,
) -> None:
    store = _MemoryStore()

    async def llm(_prompt: str) -> str:
        return json.dumps(
            {
                "project_context": context,
                "items": [
                    {
                        "candidate_id": "candidate-home",
                        "title": title,
                        "summary": summary,
                        "brief": brief,
                        "states": states,
                        "evidence_ids": [_manifest().candidates[0].evidence[0].evidence_id],
                    }
                ],
            },
            ensure_ascii=False,
        )

    service = PrototypePlanService(store=store, evidence_service=_Evidence(), llm_runner=llm)
    plan = await service.create_plan("p1", output_locale=locale)
    finished, items = await service.wait_for_analysis(plan.id)

    assert finished.status == "analysis_failed"
    assert error_fragment in (finished.error_message or "")
    assert items == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("locale", "title", "valid_context", "valid_summary", "valid_brief", "valid_states"),
    [
        (
            "zh-CN",
            "Restore the current page 页面",
            _chinese_context(),
            "展示当前页面内容.",
            "按照项目源码还原当前页面.",
            ["default"],
        ),
        (
            "zh-CN",
            "THIS IS ENGLISH 中",
            _chinese_context(),
            "展示当前页面内容.",
            "按照项目源码还原当前页面.",
            ["default"],
        ),
        (
            "en-US",
            "VideoNote 首页还原工作区",
            _english_context(),
            "Show the current page content.",
            "Restore the current page from project source.",
            ["default"],
        ),
    ],
)
async def test_planner_rejects_dominant_wrong_language_with_one_target_signal(
    locale: PlanOutputLocale,
    title: str,
    valid_context: dict[str, str],
    valid_summary: str,
    valid_brief: str,
    valid_states: list[str],
) -> None:
    store = _MemoryStore()

    async def llm(_prompt: str) -> str:
        return json.dumps(
            {
                "project_context": valid_context,
                "items": [
                    {
                        "candidate_id": "candidate-home",
                        "title": title,
                        "summary": valid_summary,
                        "brief": valid_brief,
                        "states": valid_states,
                        "evidence_ids": [_manifest().candidates[0].evidence[0].evidence_id],
                    }
                ],
            },
            ensure_ascii=False,
        )

    service = PrototypePlanService(store=store, evidence_service=_Evidence(), llm_runner=llm)
    plan = await service.create_plan("p1", output_locale=locale)
    finished, items = await service.wait_for_analysis(plan.id)

    assert finished.status == "analysis_failed"
    assert "candidate-home.title" in (finished.error_message or "")
    assert items == []


@pytest.mark.asyncio
async def test_zh_planner_requires_each_title_and_all_context_fields() -> None:
    evidence_id = _manifest().candidates[0].evidence[0].evidence_id

    async def run(payload: dict[str, object]) -> PrototypePlan:
        store = _MemoryStore()

        async def llm(_prompt: str) -> str:
            return json.dumps(payload, ensure_ascii=False)

        service = PrototypePlanService(store=store, evidence_service=_Evidence(), llm_runner=llm)
        plan = await service.create_plan("p1")
        finished, _ = await service.wait_for_analysis(plan.id)
        return finished

    english_title = await run(
        {
            "project_context": _chinese_context(),
            "items": [
                {
                    "candidate_id": "candidate-home",
                    "title": "VideoNote Home",
                    "summary": "展示首页内容.",
                    "brief": "按照项目源码还原首页.",
                    "states": ["default"],
                    "evidence_ids": [evidence_id],
                }
            ],
        }
    )
    partial_context = await run(
        {
            "project_context": {"product_summary": "视频工作区"},
            "items": [
                {
                    "candidate_id": "candidate-home",
                    "title": "VideoNote 首页",
                    "summary": "展示首页内容.",
                    "brief": "按照项目源码还原首页.",
                    "states": ["default"],
                    "evidence_ids": [evidence_id],
                }
            ],
        }
    )

    assert english_title.status == "analysis_failed"
    assert "candidate-home.title" in (english_title.error_message or "")
    assert partial_context.status == "analysis_failed"
    assert "project_context.audience" in (partial_context.error_message or "")


@pytest.mark.asyncio
async def test_plan_item_patch_persists_user_edits() -> None:
    store = _MemoryStore()

    async def llm(prompt: str) -> str:
        return json.dumps(
            {
                "project_context": _english_context(),
                "items": [
                    {
                        "candidate_id": "candidate-home",
                        "title": "Home",
                        "summary": "Summary",
                        "brief": "Restore home.",
                        "states": ["default"],
                        "evidence_ids": [_manifest().candidates[0].evidence[0].evidence_id],
                    }
                ],
            }
        )

    service = PrototypePlanService(store=store, evidence_service=_Evidence(), llm_runner=llm)
    plan = await service.create_plan("p1", output_locale="en-US")
    _, items = await service.wait_for_analysis(plan.id)
    updated_plan, updated_items = await service.patch_item(
        items[0].id,
        title="Edited Home",
        brief="Restore home with the user's approved copy.",
        selected=False,
    )

    assert updated_plan.status == "ready"
    assert updated_items[0].title == "Edited Home"
    assert updated_items[0].selected is False


@pytest.mark.asyncio
async def test_async_store_round_trips_plan_and_items(tmp_path: Path) -> None:
    store = AsyncSQLiteStore(tmp_path / "plans.db")
    project = Project(id="p1", name="Demo", repo_path=str(tmp_path))
    await store.save_project(project)
    plan = PrototypePlan(
        id="plan-1",
        project_id="p1",
        status="ready",
        repository_fingerprint="sha256:repo",
        project_context={
            "product_summary": "demo",
            "audience": "",
            "visual_language": "",
            "shared_layout": "",
        },
        global_instruction="restore",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    item = PrototypePlanItem(
        id="item-1",
        plan_id="plan-1",
        candidate_id="candidate-home",
        package_root="frontend",
        surface_kind="web",
        route_patterns=["/"],
        primary_source_path="frontend/src/App.tsx",
        source_paths=["frontend/src/App.tsx"],
        layout_paths=[],
        title="Home",
        summary="Summary",
        brief="Restore home.",
        states=["default"],
        evidence_ids=["evidence--home"],
        evidence=[
            {
                "evidence_id": "evidence--home",
                "kind": "page-source",
                "path": "frontend/src/App.tsx",
                "start_line": 1,
                "end_line": 1,
                "detail": "bounded source evidence",
                "content": "export default function App() {}",
                "confidence": "high",
                "diagnostic": None,
            }
        ],
        confidence="high",
        action="create",
        selected=True,
        source_hash="sha256:home",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    await store.save_prototype_plan_with_items(plan, [item])
    loaded = await store.load_prototype_plan("plan-1")
    by_item = await store.load_prototype_plan_by_item("item-1")
    await store.close()

    assert loaded is not None
    assert loaded[0].project_context["product_summary"] == "demo"
    assert loaded[1][0].evidence[0]["path"] == "frontend/src/App.tsx"
    assert by_item is not None
    assert by_item[1][0].id == "item-1"


@pytest.mark.asyncio
async def test_v7_migration_backfills_only_missing_legacy_evidence_references(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "plan-evidence-v6.db"
    store = AsyncSQLiteStore(db_path)
    migrated_store: AsyncSQLiteStore | None = None
    try:
        project = Project(id="p1", name="Demo", repo_path=str(tmp_path))
        await store.save_project(project)
        now = datetime.now()
        plan = PrototypePlan(
            id="plan-v6",
            project_id=project.id,
            status="ready",
            repository_fingerprint="sha256:repo",
            created_at=now,
            updated_at=now,
        )
        evidence = [
            {
                "evidence_id": "evidence--one",
                "path": "src/App.tsx",
                "start_line": 1,
                "end_line": 2,
                "kind": "page-source",
                "detail": "first",
                "content": "first",
            },
            {
                "evidence_id": "evidence--two",
                "path": "src/App.tsx",
                "start_line": 3,
                "end_line": 4,
                "kind": "page-source",
                "detail": "second",
                "content": "second",
            },
        ]

        def legacy_item(
            item_id: str,
            action: PlanAction,
            evidence_ids: list[str],
        ) -> PrototypePlanItem:
            return PrototypePlanItem(
                id=item_id,
                plan_id=plan.id,
                candidate_id=f"candidate-{item_id}",
                package_root="frontend",
                surface_kind="web",
                route_patterns=[f"/{item_id}"],
                primary_source_path="src/App.tsx",
                source_paths=["src/App.tsx"],
                layout_paths=[],
                title=item_id,
                summary="Summary",
                brief="Restore page.",
                states=["default"],
                evidence_ids=evidence_ids,
                evidence=evidence,
                confidence="high",
                action=action,
                selected=action in {"create", "update"},
                source_hash=f"sha256:{item_id}",
                created_at=now,
                updated_at=now,
            )

        await store.save_prototype_plan_with_items(
            plan,
            [
                legacy_item("create", "create", []),
                legacy_item("update", "update", ["evidence--two"]),
                legacy_item("unchanged", "unchanged", []),
                legacy_item("missing", "missing", ["evidence--one"]),
            ],
        )
        connection = await store._get_conn()
        await connection.execute("UPDATE schema_version SET version = 6 WHERE id = 1")
        await connection.commit()
        await store.close()

        migrated_store = AsyncSQLiteStore(db_path)
        loaded = await migrated_store.load_prototype_plan(plan.id)
        assert loaded is not None
        by_id = {item.id: item for item in loaded[1]}
        assert by_id["create"].evidence_ids == ["evidence--one", "evidence--two"]
        assert by_id["update"].evidence_ids == ["evidence--two"]
        assert by_id["unchanged"].evidence_ids == ["evidence--one", "evidence--two"]
        assert by_id["missing"].evidence_ids == []
        serialized_evidence = by_id["create"]._serialized_evidence()
        assert serialized_evidence[0]["confidence"] == "high"
        assert serialized_evidence[0]["diagnostic"] is None
        migrated_connection = await migrated_store._get_conn()
        version_row = await (
            await migrated_connection.execute("SELECT version FROM schema_version WHERE id = 1")
        ).fetchone()
        assert version_row is not None
        assert version_row[0] == 11
    finally:
        await store.close()
        if migrated_store is not None:
            await migrated_store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("raw_evidence", ["{not-json", "[]"])
async def test_v7_migration_rejects_malformed_or_empty_generatable_evidence(
    tmp_path: Path,
    raw_evidence: str,
) -> None:
    db_path = tmp_path / f"invalid-evidence-{len(raw_evidence)}.db"
    store = AsyncSQLiteStore(db_path)
    migrated_store: AsyncSQLiteStore | None = None
    try:
        project = Project(id="p1", name="Demo", repo_path=str(tmp_path))
        await store.save_project(project)
        now = datetime.now()
        plan = PrototypePlan(
            id="plan-invalid-v6",
            project_id=project.id,
            status="ready",
            repository_fingerprint="sha256:repo",
            created_at=now,
            updated_at=now,
        )
        item = PrototypePlanItem(
            id="item-invalid-v6",
            plan_id=plan.id,
            candidate_id="candidate-invalid",
            package_root="frontend",
            surface_kind="web",
            route_patterns=["/invalid"],
            primary_source_path="src/App.tsx",
            source_paths=["src/App.tsx"],
            layout_paths=[],
            title="Invalid",
            summary="Invalid",
            brief="Invalid",
            states=["default"],
            evidence_ids=[],
            evidence=[],
            confidence="high",
            action="create",
            selected=True,
            source_hash="sha256:invalid",
            created_at=now,
            updated_at=now,
        )
        await store.save_prototype_plan_with_items(plan, [item])
        connection = await store._get_conn()
        await connection.execute(
            "UPDATE prototype_plan_items SET evidence_json = ? WHERE id = ?",
            (raw_evidence, item.id),
        )
        await connection.execute("UPDATE schema_version SET version = 6 WHERE id = 1")
        await connection.commit()
        await store.close()

        migrated_store = AsyncSQLiteStore(db_path)
        with pytest.raises((json.JSONDecodeError, ValueError)):
            await migrated_store._init_db()
    finally:
        await store.close()
        if migrated_store is not None:
            await migrated_store.close()


@pytest.mark.asyncio
async def test_bulk_selection_is_atomic_and_concurrent_groups_do_not_overwrite(
    tmp_path: Path,
) -> None:
    store = AsyncSQLiteStore(tmp_path / "selection.db")
    project = Project(id="p1", name="Demo", repo_path=str(tmp_path))
    await store.save_project(project)
    now = datetime.now()
    plan = PrototypePlan(
        id="plan-selection",
        project_id=project.id,
        status="ready",
        repository_fingerprint="sha256:repo",
        created_at=now,
        updated_at=now,
    )

    def item(item_id: str, action: PlanAction) -> PrototypePlanItem:
        return PrototypePlanItem(
            id=item_id,
            plan_id=plan.id,
            candidate_id=f"candidate-{item_id}",
            package_root="frontend",
            surface_kind="web",
            route_patterns=[f"/{item_id}"],
            primary_source_path=f"frontend/{item_id}.tsx",
            source_paths=[f"frontend/{item_id}.tsx"],
            layout_paths=[],
            title=item_id,
            summary="Summary",
            brief="Restore the page.",
            states=["default"],
            evidence_ids=[],
            evidence=[],
            confidence="high",
            action=action,
            selected=True,
            source_hash=f"sha256:{item_id}",
            created_at=now,
            updated_at=now,
        )

    items = [item("item-a", "create"), item("item-b", "update"), item("item-c", "missing")]
    await store.save_prototype_plan_with_items(plan, items)
    service = PrototypePlanService(store=store, evidence_service=_Evidence())

    await asyncio.gather(
        service.patch_selection(plan.id, item_ids=["item-a"], selected=False),
        service.patch_selection(plan.id, item_ids=["item-b"], selected=False),
    )
    _, updated = await service.get_plan(plan.id)
    selected_by_id = {candidate.id: candidate.selected for candidate in updated}
    assert selected_by_id == {"item-a": False, "item-b": False, "item-c": True}

    with pytest.raises(
        PrototypePlanError,
        match="not eligible for generation: item-c",
    ):
        await service.patch_selection(
            plan.id,
            item_ids=["item-a", "item-c"],
            selected=True,
        )
    _, rejected = await service.get_plan(plan.id)
    rejected_by_id = {candidate.id: candidate.selected for candidate in rejected}
    assert rejected_by_id == selected_by_id
    await store.close()


@pytest.mark.asyncio
async def test_existing_source_hash_maps_to_unchanged_and_changed_to_update() -> None:
    store = _MemoryStore()
    store.prototypes = [
        Prototype(
            id="existing",
            project_id="p1",
            title="Home",
            framework="html",
            current_version=1,
            source_kind="code",
            source_ref="candidate-home",
            source_hash="sha256:home",
        )
    ]

    async def llm(_prompt: str) -> str:
        return json.dumps(
            {
                "project_context": _english_context(),
                "items": [
                    {
                        "candidate_id": "candidate-home",
                        "title": "Home",
                        "summary": "Summary",
                        "brief": "Restore home.",
                        "states": ["default"],
                        "evidence_ids": [_manifest().candidates[0].evidence[0].evidence_id],
                    }
                ],
            }
        )

    service = PrototypePlanService(store=store, evidence_service=_Evidence(), llm_runner=llm)
    plan = await service.create_plan("p1", output_locale="en-US")
    _, items = await service.wait_for_analysis(plan.id)
    assert items[0].action == "unchanged"
    assert items[0].selected is False


@pytest.mark.asyncio
async def test_synthetic_missing_item_uses_plan_output_locale() -> None:
    store = _MemoryStore()
    store.prototypes = [
        Prototype(
            id="missing-prototype",
            project_id="p1",
            title="旧版详情页",
            framework="html",
            current_version=1,
            source_kind="code",
            source_ref="candidate-removed",
            source_hash="sha256:removed",
        )
    ]

    async def llm(_prompt: str) -> str:
        return json.dumps(
            {
                "project_context": _chinese_context(),
                "items": [
                    {
                        "candidate_id": "candidate-home",
                        "title": "VideoNote 首页",
                        "summary": "展示首页内容.",
                        "brief": "按照项目源码还原首页.",
                        "states": ["default"],
                        "evidence_ids": [_manifest().candidates[0].evidence[0].evidence_id],
                    }
                ],
            },
            ensure_ascii=False,
        )

    service = PrototypePlanService(store=store, evidence_service=_Evidence(), llm_runner=llm)
    plan = await service.create_plan("p1")
    finished, items = await service.wait_for_analysis(plan.id)
    missing = next(item for item in items if item.action == "missing")

    assert finished.status == "ready"
    assert missing.summary == "此前生成的源码页面已不在当前项目中."
    assert missing.states == ["缺失"]


@pytest.mark.asyncio
async def test_planner_rejects_unknown_evidence_ids() -> None:
    store = _MemoryStore()

    async def llm(_prompt: str) -> str:
        return json.dumps(
            {
                "project_context": _english_context(),
                "items": [
                    {
                        "candidate_id": "candidate-home",
                        "title": "Home",
                        "summary": "Summary",
                        "brief": "Restore home.",
                        "states": ["default"],
                        "evidence_ids": ["evidence--unknown"],
                    }
                ],
            }
        )

    service = PrototypePlanService(store=store, evidence_service=_Evidence(), llm_runner=llm)
    plan = await service.create_plan("p1", output_locale="en-US")
    finished, _ = await service.wait_for_analysis(plan.id)

    assert finished.status == "analysis_failed"
    assert "unknown evidence IDs" in (finished.error_message or "")


@pytest.mark.asyncio
async def test_analysis_marks_plan_stale_when_repository_changes_during_llm() -> None:
    store = _MemoryStore()

    async def llm(_prompt: str) -> str:
        return json.dumps(
            {
                "project_context": _english_context(),
                "items": [
                    {
                        "candidate_id": "candidate-home",
                        "title": "Home",
                        "summary": "Summary",
                        "brief": "Restore home.",
                        "states": ["default"],
                        "evidence_ids": [_manifest().candidates[0].evidence[0].evidence_id],
                    }
                ],
            }
        )

    service = PrototypePlanService(
        store=store,
        evidence_service=_ChangingEvidence(),
        llm_runner=llm,
    )
    plan = await service.create_plan("p1", output_locale="en-US")
    finished, _ = await service.wait_for_analysis(plan.id)

    assert finished.status == "stale"
    assert finished.error_message == "project evidence changed during analysis"


@pytest.mark.asyncio
async def test_zh_analysis_persists_localized_stale_error_and_diagnostic() -> None:
    store = _MemoryStore()

    async def llm(_prompt: str) -> str:
        return json.dumps(
            {
                "project_context": _chinese_context(),
                "items": [
                    {
                        "candidate_id": "candidate-home",
                        "title": "VideoNote 首页",
                        "summary": "展示首页内容.",
                        "brief": "按照项目源码还原首页.",
                        "states": ["default"],
                        "evidence_ids": [_manifest().candidates[0].evidence[0].evidence_id],
                    }
                ],
            },
            ensure_ascii=False,
        )

    service = PrototypePlanService(
        store=store,
        evidence_service=_ChangingEvidence(),
        llm_runner=llm,
    )
    plan = await service.create_plan("p1")
    finished, _ = await service.wait_for_analysis(plan.id)

    assert finished.status == "stale"
    assert finished.error_message == "分析期间项目证据发生变化"
    assert finished.diagnostics[-1] == "分析期间项目证据发生变化, 请重新分析"


@pytest.mark.asyncio
async def test_empty_instruction_reuses_latest_saved_instruction() -> None:
    store = _MemoryStore()
    previous = PrototypePlan(
        id="previous",
        project_id="p1",
        status="analysis_failed",
        repository_fingerprint="sha256:old",
        global_instruction="keep the existing navigation",
    )
    store.plans[previous.id] = (previous, [])

    async def llm(_prompt: str) -> str:
        return "not json"

    service = PrototypePlanService(store=store, evidence_service=_Evidence(), llm_runner=llm)
    plan = await service.create_plan("p1")

    assert plan.global_instruction == "keep the existing navigation"


@pytest.mark.asyncio
async def test_restart_recovery_localizes_interrupted_plan_errors(tmp_path: Path) -> None:
    store = AsyncSQLiteStore(tmp_path / "planning-recovery.db")
    await store._init_db()
    try:
        project = Project(id="p1", name="VideoNote", repo_path=str(tmp_path))
        await store.save_project(project)
        now = datetime.now()
        chinese_plan = PrototypePlan(
            id="plan-zh",
            project_id=project.id,
            status="queued",
            repository_fingerprint="pending",
            output_locale="zh-CN",
            created_at=now,
            updated_at=now,
        )
        english_plan = PrototypePlan(
            id="plan-en",
            project_id=project.id,
            status="analyzing",
            repository_fingerprint="sha256:repo",
            output_locale="en-US",
            created_at=now,
            updated_at=now,
        )
        await store.save_prototype_plan_with_items(chinese_plan, [])
        await store.save_prototype_plan_with_items(english_plan, [])

        assert await store.interrupt_active_prototype_plans() == 2
        recovered_zh = await store.load_prototype_plan(chinese_plan.id)
        recovered_en = await store.load_prototype_plan(english_plan.id)

        assert recovered_zh is not None
        assert recovered_zh[0].status == "interrupted"
        assert recovered_zh[0].error_message == "后端重启时项目分析仍在运行, 任务已中断"
        assert recovered_en is not None
        assert recovered_en[0].status == "interrupted"
        assert (
            recovered_en[0].error_message == "Backend restarted while project analysis was running"
        )
    finally:
        await store.close()
