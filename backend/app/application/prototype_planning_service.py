from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime
from typing import Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.application import timeouts
from app.application.audit.recorders import record_event
from app.application.llm_runner import LLMOutputTokenLimitError
from app.application.project_evidence_service import ProjectEvidenceError, ProjectEvidenceService
from app.application.prototype_artifact_generator import (
    PrototypeArtifactActivity,
    PrototypeArtifactActivityCallback,
)
from app.application.tolerant_json import tolerant_json_loads
from app.domain.models import Project, Prototype, PrototypeVersion
from app.domain.project_evidence import ProjectSurfaceManifest, PrototypeCandidate
from app.domain.prototype_plan import (
    PlanAction,
    PlanOutputLocale,
    PrototypePlan,
    PrototypePlanItem,
    PrototypePlanSelectionUpdate,
)
from app.json_safety import parse_json_object

logger = logging.getLogger(__name__)

PlanLLMRunner = Callable[[str], Awaitable[str | None]]
_STATE_ID_RE = re.compile(r"^[a-z][a-z0-9:/._-]*$")
_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_LATIN_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[./:_-][A-Za-z0-9]+)*")
_CODE_CONTEXT_CHARS = frozenset("`/\\._:-<>{}[]()=\"'")
_JSON_STRING_TERMINATORS = frozenset({":", ",", "}", "]"})

_PLANNER_MESSAGES: dict[PlanOutputLocale, dict[str, str]] = {
    "zh-CN": {
        "runtime_unavailable": "原型规划运行时不可用",
        "ui_engineer_failed": "原型 UI 工程师分析失败: {detail}",
        "no_result": "原型规划运行时没有返回结果",
        "invalid_json": "原型规划运行时返回了无效 JSON",
        "invalid_schema": "原型规划结果不符合必需的数据结构: {fields}",
        "invalid_locale": "原型规划结果未遵循 zh-CN 输出语言要求: {fields}",
        "max_tokens": "原型规划输出达到 token 上限, 单个页面仍无法完整返回",
        "prompt_limit": "原型规划证据超过提示词上限 ({actual} > {limit})",
        "coverage": "原型规划结果未完整覆盖候选页面: {details}",
        "unknown_evidence": "原型规划结果引用了未知证据 ID: {details}",
        "evidence_changed": "分析期间项目证据发生变化",
        "evidence_changed_diagnostic": "分析期间项目证据发生变化, 请重新分析",
        "evidence_unavailable": "项目证据扫描失败",
        "analysis_failed": "原型规划分析失败",
    },
    "en-US": {
        "runtime_unavailable": "prototype planning runtime is unavailable",
        "ui_engineer_failed": "prototype UI engineer planning failed: {detail}",
        "no_result": "prototype planning runtime returned no result",
        "invalid_json": "prototype planning runtime returned invalid JSON",
        "invalid_schema": "prototype planning result did not match the required schema: {fields}",
        "invalid_locale": "prototype planning result did not follow the en-US output locale: {fields}",
        "max_tokens": "prototype planning reached the token limit for a single page",
        "prompt_limit": "prototype planning evidence exceeds prompt limit ({actual} > {limit})",
        "coverage": "prototype planning result did not cover candidates: {details}",
        "unknown_evidence": "prototype planning result referenced unknown evidence IDs: {details}",
        "evidence_changed": "project evidence changed during analysis",
        "evidence_changed_diagnostic": "Project changed during analysis; analyze again.",
        "evidence_unavailable": "project evidence scan failed",
        "analysis_failed": "prototype plan analysis failed",
    },
}
_ZH_DIAGNOSTIC_MESSAGES = {
    "package.json is not valid JSON": "package.json 不是有效 JSON",
    "browser extension surface is detected but not supported in MVP": "检测到浏览器扩展界面, 当前版本暂不支持",
    "React package has no supported route declaration; fallback discovery is low confidence": "React 包没有受支持的路由声明, 回退发现结果为低置信度",
    "no supported web framework signal was found": "未识别到受支持的 Web 框架信号",
}


def _planner_message(locale: PlanOutputLocale, key: str, **params: object) -> str:
    return _PLANNER_MESSAGES[locale][key].format(**params)


def _has_locale_signal(text: str, locale: PlanOutputLocale) -> bool:
    cjk_count = len(_CJK_RE.findall(text))
    latin_tokens = list(_LATIN_TOKEN_RE.finditer(text))
    latin_count = len(_LATIN_RE.findall(text))
    if locale == "zh-CN" and cjk_count == 0:
        return False
    if locale == "en-US" and latin_count == 0:
        return False
    if cjk_count == 0 or latin_count == 0:
        return True

    active_latin_tokens = 0
    for match in latin_tokens:
        token = match.group(0)
        before = text[match.start() - 1] if match.start() > 0 else ""
        after = text[match.end()] if match.end() < len(text) else ""
        is_code_or_product = (
            (token.isupper() and len(token) <= 4)
            or (any(char.isupper() for char in token[1:]) and any(char.islower() for char in token))
            or any(char.isdigit() or char in "/._:-" for char in token)
            or before in _CODE_CONTEXT_CHARS
            or after in _CODE_CONTEXT_CHARS
        )
        if not is_code_or_product:
            active_latin_tokens += 1

    # One Latin word carries roughly the semantic weight of two CJK glyphs.
    # A strict inequality rejects ambiguous 50/50 copy instead of guessing.
    latin_units = active_latin_tokens * 2
    if locale == "zh-CN":
        return cjk_count > latin_units
    return latin_units > cjk_count


def _next_non_whitespace(text: str, start: int) -> str | None:
    for char in text[start:]:
        if not char.isspace():
            return char
    return None


def _has_complete_single_object_envelope(raw: str) -> bool:
    stripped = raw.strip()
    if len(stripped) < 2 or stripped[0] != "{" or stripped[-1] != "}":
        return False

    expected_closers: list[str] = []
    in_string = False
    escaped = False
    for index, char in enumerate(stripped):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                next_char = _next_non_whitespace(stripped, index + 1)
                if next_char is None or next_char in _JSON_STRING_TERMINATORS:
                    in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            expected_closers.append("}")
        elif char == "[":
            expected_closers.append("]")
        elif char in {"}", "]"}:
            if not expected_closers or expected_closers.pop() != char:
                return False
            if not expected_closers and index != len(stripped) - 1:
                return False
    return not in_string and not escaped and not expected_closers


class PrototypePlanError(RuntimeError):
    """Expected project-plan error mapped by the HTTP layer."""

    def __init__(
        self,
        message: str,
        *,
        code: Literal["invalid", "not_found", "conflict"] = "invalid",
    ) -> None:
        super().__init__(message)
        self.code = code


class PrototypePlanStore(Protocol):
    async def load_project(self, project_id: str) -> Project | None: ...

    async def list_prototypes(self, project_id: str) -> list[Prototype]: ...

    async def load_prototype_version(
        self, prototype_id: str, version_no: int
    ) -> PrototypeVersion | None: ...

    async def save_prototype_plan_with_items(
        self, plan: PrototypePlan, items: list[PrototypePlanItem]
    ) -> None: ...

    async def upsert_prototype_plan_item(
        self, plan: PrototypePlan, item: PrototypePlanItem
    ) -> None: ...

    async def load_prototype_plan(
        self, plan_id: str
    ) -> tuple[PrototypePlan, list[PrototypePlanItem]] | None: ...

    async def load_prototype_plan_by_item(
        self, item_id: str
    ) -> tuple[PrototypePlan, list[PrototypePlanItem]] | None: ...

    async def load_latest_prototype_plan_for_project(
        self, project_id: str
    ) -> tuple[PrototypePlan, list[PrototypePlanItem]] | None: ...

    async def update_prototype_plan_selection(
        self,
        plan_id: str,
        item_ids: tuple[str, ...],
        *,
        selected: bool,
        updated_at: datetime,
    ) -> PrototypePlanSelectionUpdate: ...


class EvidenceScanner(Protocol):
    def scan_project(self, project: Project) -> ProjectSurfaceManifest: ...


class PrototypePlanningUIEngineer(Protocol):
    async def plan(
        self,
        *,
        project: Project,
        plan_id: str,
        prompt: str,
        source_paths: tuple[str, ...],
        activity_callback: PrototypeArtifactActivityCallback | None = None,
        mcp_config: str | None = None,
    ) -> str | None: ...


class PrototypePlanningMcpProvider(Protocol):
    def open_session(
        self, *, project: Project, plan_id: str, manifest: ProjectSurfaceManifest
    ) -> object: ...

    def close_session(self, session: object) -> None: ...


class _PlannerItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    candidate_id: str
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=2_000)
    brief: str = Field(min_length=1, max_length=12_000)
    states: list[str] = Field(min_length=1, max_length=12)
    evidence_ids: list[str] = Field(min_length=1, max_length=64)

    @field_validator("states")
    @classmethod
    def validate_states(cls, states: list[str]) -> list[str]:
        if any(not state.strip() for state in states):
            raise ValueError("planner states must not be blank")
        if any(_STATE_ID_RE.fullmatch(state) is None for state in states):
            raise ValueError("planner states must be lowercase technical identifiers")
        if len(set(states)) != len(states):
            raise ValueError("planner states must be unique")
        return states

    @field_validator("evidence_ids")
    @classmethod
    def validate_evidence_ids(cls, evidence_ids: list[str]) -> list[str]:
        if any(not evidence_id.strip() for evidence_id in evidence_ids):
            raise ValueError("planner evidence IDs must not be blank")
        if len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("planner evidence IDs must be unique")
        return evidence_ids


class _PlannerProjectContext(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    product_summary: str = Field(default="", max_length=4_000)
    audience: str = Field(default="", max_length=4_000)
    visual_language: str = Field(default="", max_length=4_000)
    shared_layout: str = Field(default="", max_length=4_000)


class _PlannerOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    project_context: _PlannerProjectContext = Field(default_factory=_PlannerProjectContext)
    items: list[_PlannerItem] = Field(min_length=1)


class PrototypePlanService:
    """Persist and asynchronously build reviewable prototype plans."""

    TERMINAL_STATUSES = frozenset({"ready", "analysis_failed", "stale", "interrupted"})
    MAX_PROMPT_CHARS = 1_000_000
    MAX_CANDIDATES_PER_LLM_CALL = 6

    def __init__(
        self,
        *,
        store: PrototypePlanStore,
        evidence_service: EvidenceScanner | None = None,
        ui_engineer: PrototypePlanningUIEngineer | None = None,
        llm_runner: PlanLLMRunner | None = None,
        mcp_service: PrototypePlanningMcpProvider | None = None,
    ) -> None:
        self.store = store
        self.evidence_service = evidence_service or ProjectEvidenceService()
        self.ui_engineer = ui_engineer
        self.llm_runner = llm_runner
        self.mcp_service = mcp_service
        self._tasks: set[asyncio.Task[None]] = set()

    async def create_plan(
        self,
        project_id: str,
        *,
        global_instruction: str = "",
        output_locale: PlanOutputLocale = "zh-CN",
    ) -> PrototypePlan:
        project = await self.store.load_project(project_id)
        if project is None:
            raise PrototypePlanError(f"project not found: {project_id}")
        instruction = global_instruction.strip()
        if not instruction:
            latest = await self.store.load_latest_prototype_plan_for_project(project_id)
            if latest is not None:
                instruction = latest[0].global_instruction
        now = datetime.now()
        plan = PrototypePlan(
            id=f"prototype-plan-{uuid4().hex}",
            project_id=project_id,
            status="queued",
            repository_fingerprint="pending",
            global_instruction=instruction,
            output_locale=output_locale,
            analysis_phase="queued",
            created_at=now,
            updated_at=now,
        )
        await self.store.save_prototype_plan_with_items(plan, [])
        task = asyncio.create_task(self._analyze(plan.id, project))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return plan

    async def retry_analysis(self, plan_id: str) -> PrototypePlan:
        plan, _ = await self.get_plan(plan_id)
        if plan.status not in {"analysis_failed", "stale", "interrupted"}:
            raise PrototypePlanError(f"plan cannot be analyzed again in status {plan.status}")
        return await self.create_plan(
            plan.project_id,
            global_instruction=plan.global_instruction,
            output_locale=plan.output_locale,
        )

    async def get_plan(self, plan_id: str) -> tuple[PrototypePlan, list[PrototypePlanItem]]:
        loaded = await self.store.load_prototype_plan(plan_id)
        if loaded is None:
            raise PrototypePlanError(f"prototype plan not found: {plan_id}")
        return loaded

    async def get_latest_plan_for_project(
        self, project_id: str
    ) -> tuple[PrototypePlan, list[PrototypePlanItem]] | None:
        project = await self.store.load_project(project_id)
        if project is None:
            raise PrototypePlanError(f"project not found: {project_id}")
        return await self.store.load_latest_prototype_plan_for_project(project_id)

    async def patch_plan(
        self,
        plan_id: str,
        *,
        global_instruction: str | None = None,
        project_context: dict[str, str] | None = None,
    ) -> tuple[PrototypePlan, list[PrototypePlanItem]]:
        plan, items = await self.get_plan(plan_id)
        if plan.status not in {"ready", "stale"}:
            raise PrototypePlanError(f"plan is not editable in status {plan.status}")
        if global_instruction is not None:
            plan.global_instruction = global_instruction.strip()
        if project_context is not None:
            plan.project_context = project_context
        plan.updated_at = datetime.now()
        await self.store.save_prototype_plan_with_items(plan, items)
        return plan, items

    async def patch_item(
        self,
        item_id: str,
        *,
        title: str | None = None,
        summary: str | None = None,
        brief: str | None = None,
        states: list[str] | None = None,
        selected: bool | None = None,
    ) -> tuple[PrototypePlan, list[PrototypePlanItem]]:
        plan, items = await self.get_plan_for_item(item_id)
        if plan.status not in {"ready", "stale"}:
            raise PrototypePlanError(f"plan is not editable in status {plan.status}")
        item = next((item for item in items if item.id == item_id), None)
        if item is None:
            raise PrototypePlanError(f"prototype plan item not found: {item_id}")
        if title is not None:
            item.title = title.strip()
        if summary is not None:
            item.summary = summary.strip()
        if brief is not None:
            item.brief = brief.strip()
        if states is not None:
            item.states = [state.strip() for state in states if state.strip()]
        if selected is not None:
            item.selected = selected
        if not item.title or not item.summary or not item.brief or not item.states:
            raise PrototypePlanError("title, summary, brief, and at least one state are required")
        item.updated_at = datetime.now()
        plan.updated_at = datetime.now()
        await self.store.save_prototype_plan_with_items(plan, items)
        return plan, items

    async def patch_selection(
        self,
        plan_id: str,
        *,
        item_ids: list[str],
        selected: bool,
    ) -> tuple[PrototypePlan, list[PrototypePlanItem]]:
        if not item_ids:
            raise PrototypePlanError("at least one prototype plan item is required")
        if any(not item_id.strip() for item_id in item_ids):
            raise PrototypePlanError("prototype plan item IDs must not be blank")
        if len(set(item_ids)) != len(item_ids):
            raise PrototypePlanError("prototype plan item IDs must be unique")

        result = await self.store.update_prototype_plan_selection(
            plan_id,
            tuple(item_ids),
            selected=selected,
            updated_at=datetime.now(),
        )
        if result.status == "plan_not_found":
            raise PrototypePlanError(
                f"prototype plan not found: {plan_id}",
                code="not_found",
            )
        if result.status == "not_editable":
            raise PrototypePlanError(
                "prototype plan selection is not editable",
                code="conflict",
            )
        if result.status == "item_not_found":
            raise PrototypePlanError(
                "prototype plan items not found: " + ", ".join(result.item_ids),
                code="not_found",
            )
        if result.status == "ineligible":
            raise PrototypePlanError(
                "prototype plan items are not eligible for generation: "
                + ", ".join(result.item_ids),
                code="conflict",
            )
        if result.status != "updated":
            raise AssertionError(f"unexpected prototype selection result: {result.status}")
        plan, items = await self.get_plan(plan_id)
        if selected:
            changed = False
            for item in items:
                if item.id in result.item_ids and item.review_status == "needs_confirmation":
                    item.review_status = "confirmed"
                    item.updated_at = datetime.now()
                    changed = True
            if changed:
                plan.updated_at = datetime.now()
                await self.store.save_prototype_plan_with_items(plan, items)
        return plan, items

    async def get_plan_for_item(
        self, item_id: str
    ) -> tuple[PrototypePlan, list[PrototypePlanItem]]:
        loaded = await self.store.load_prototype_plan_by_item(item_id)
        if loaded is None:
            raise PrototypePlanError(f"prototype plan item not found: {item_id}")
        return loaded

    async def register_mcp_item(
        self,
        *,
        plan_id: str,
        manifest: ProjectSurfaceManifest,
        payload: dict[str, object],
        candidate_override: PrototypeCandidate | None = None,
    ) -> PrototypePlanItem:
        """Validate and durably expose one Claude-discovered static candidate."""
        plan, existing_items = await self.get_plan(plan_id)
        if plan.status != "analyzing" or plan.analysis_phase != "planning":
            raise PrototypePlanError("prototype plan is not accepting live discoveries", code="conflict")
        try:
            draft = _PlannerItem.model_validate(payload)
        except ValidationError as exc:
            raise PrototypePlanError(
                _planner_message(
                    plan.output_locale,
                    "invalid_schema",
                    fields=self._validation_error_fields(exc),
                )
            ) from exc
        self._validate_output_locale(
            plan.output_locale,
            _PlannerOutput(items=[draft]),
            require_context=False,
        )
        candidate = candidate_override or next(
            (item for item in manifest.candidates if item.candidate_id == draft.candidate_id), None
        )
        if candidate is None:
            raise PrototypePlanError("Claude discovery has no valid source candidate")
        valid_evidence_ids = {item.evidence_id for item in candidate.evidence}
        if not set(draft.evidence_ids).issubset(valid_evidence_ids):
            raise PrototypePlanError("Claude discovery references unknown evidence IDs")
        previous = next(
            (item for item in existing_items if item.candidate_id == candidate.candidate_id),
            None,
        )
        existing = await self._existing_prototypes(plan.project_id)
        is_static = any(entry.candidate_id == candidate.candidate_id for entry in manifest.candidates)
        now = datetime.now()
        item = PrototypePlanItem(
            id=previous.id if previous is not None else f"prototype-plan-item-{uuid4().hex}",
            plan_id=plan.id,
            candidate_id=candidate.candidate_id,
            package_root=candidate.package_root,
            surface_kind=candidate.surface_kind,
            route_patterns=list(candidate.route_patterns),
            primary_source_path=candidate.primary_source_path,
            source_paths=list(candidate.source_paths),
            layout_paths=list(candidate.layout_paths),
            title=draft.title,
            summary=draft.summary,
            brief=draft.brief,
            states=draft.states,
            evidence_ids=draft.evidence_ids,
            evidence=[
                evidence.to_dict()
                for evidence in candidate.evidence
                if evidence.evidence_id in set(draft.evidence_ids)
            ],
            confidence=candidate.confidence,
            action=self._candidate_action(candidate, existing) if is_static else "create",
            selected=False,
            source_hash=candidate.source_hash,
            discovery_origin="static" if is_static else "claude",
            review_status="provisional" if is_static else "needs_confirmation",
            created_at=previous.created_at if previous is not None else now,
            updated_at=now,
        )
        static_ids = {entry.candidate_id for entry in manifest.candidates}
        plan.analysis_completed = len(
            ({entry.candidate_id for entry in existing_items} | {candidate.candidate_id})
            & static_ids
        )
        plan.updated_at = now
        await self.store.upsert_prototype_plan_item(plan, item)
        return item

    async def finalize_mcp_inventory(
        self,
        *,
        plan_id: str,
        manifest: ProjectSurfaceManifest,
        project_context: dict[str, object],
    ) -> list[str]:
        plan, items = await self.get_plan(plan_id)
        if plan.status != "analyzing" or plan.analysis_phase != "planning":
            raise PrototypePlanError("prototype plan is not accepting finalization", code="conflict")
        try:
            context = _PlannerProjectContext.model_validate(project_context)
        except ValidationError as exc:
            raise PrototypePlanError("prototype project context is invalid") from exc
        context_failures = [
            name
            for name, value in context.model_dump().items()
            if not value or not _has_locale_signal(value, plan.output_locale)
        ]
        if context_failures:
            raise PrototypePlanError(
                _planner_message(
                    plan.output_locale,
                    "invalid_locale",
                    fields=", ".join(f"project_context.{name}" for name in context_failures),
                )
            )
        registered = {item.candidate_id for item in items}
        missing = [item.candidate_id for item in manifest.candidates if item.candidate_id not in registered]
        if missing:
            return missing
        for item in items:
            if item.review_status == "provisional":
                item.review_status = "confirmed"
                item.selected = item.action in {"create", "update"} and item.confidence != "low"
                item.updated_at = datetime.now()
        plan.project_context = context.model_dump()
        plan.status = "ready"
        plan.analysis_phase = "complete"
        plan.analysis_completed = len(items)
        plan.analysis_total = len(manifest.candidates)
        plan.updated_at = datetime.now()
        await self.store.save_prototype_plan_with_items(plan, items)
        return []

    async def stream_events(self, plan_id: str) -> AsyncIterator[dict[str, object]]:
        while True:
            plan, items = await self.get_plan(plan_id)
            yield {"event": "snapshot", "data": plan.to_dict(items)}
            if plan.status in self.TERMINAL_STATUSES:
                return
            await asyncio.sleep(0.2)

    async def _analyze(self, plan_id: str, project: Project) -> None:
        started = time.monotonic()
        try:
            plan, _ = await self.get_plan(plan_id)
            plan.status = "analyzing"
            plan.analysis_phase = "scanning"
            plan.analysis_completed = 0
            plan.analysis_total = 0
            plan.updated_at = datetime.now()
            await self.store.save_prototype_plan_with_items(plan, [])
            manifest = await asyncio.to_thread(self.evidence_service.scan_project, project)
            plan.repository_fingerprint = manifest.repository_fingerprint
            plan.scope = self._scope(manifest)
            plan.analysis_phase = "planning"
            plan.analysis_total = (
                len(manifest.candidates)
                if self.ui_engineer is not None and self.mcp_service is not None
                else max(
                    1,
                    (len(manifest.candidates) + self.MAX_CANDIDATES_PER_LLM_CALL - 1)
                    // self.MAX_CANDIDATES_PER_LLM_CALL,
                )
            )
            await self.store.save_prototype_plan_with_items(plan, [])
            if self.ui_engineer is not None and self.mcp_service is not None:
                await self._plan_with_mcp(project, plan, manifest)
                plan, items = await self.get_plan(plan.id)
                if plan.status != "ready" or plan.analysis_phase != "complete":
                    raise PrototypePlanError("prototype MCP inventory did not reach completion")
                current_manifest = await asyncio.to_thread(self.evidence_service.scan_project, project)
                if current_manifest.repository_fingerprint != manifest.repository_fingerprint:
                    plan.status = "stale"
                    plan.analysis_phase = "stale"
                    plan.error_message = _planner_message(plan.output_locale, "evidence_changed")
                else:
                    plan.diagnostics = self._localized_diagnostics(
                        plan.output_locale,
                        manifest.diagnostics,
                    )
                plan.updated_at = datetime.now()
                await self.store.save_prototype_plan_with_items(plan, items)
                self._record_analysis(plan, len(items), started)
                return
            output = await self._plan_with_ui_analysis(project, plan, manifest)
            plan.analysis_phase = "validating"
            await self.store.save_prototype_plan_with_items(plan, [])
            items = await self._build_items(plan, manifest, output)
            current_manifest = await asyncio.to_thread(self.evidence_service.scan_project, project)
            if current_manifest.repository_fingerprint != manifest.repository_fingerprint:
                plan.status = "stale"
                plan.analysis_phase = "stale"
                plan.error_message = _planner_message(plan.output_locale, "evidence_changed")
                plan.diagnostics = [
                    *self._localized_diagnostics(plan.output_locale, manifest.diagnostics),
                    _planner_message(plan.output_locale, "evidence_changed_diagnostic"),
                ]
                plan.updated_at = datetime.now()
                await self.store.save_prototype_plan_with_items(plan, items)
                self._record_analysis(plan, len(items), started)
                return
            plan.project_context = output.project_context.model_dump()
            plan.status = "ready"
            plan.analysis_phase = "complete"
            plan.analysis_completed = plan.analysis_total
            plan.error_message = None
            plan.diagnostics = self._localized_diagnostics(
                plan.output_locale,
                manifest.diagnostics,
            )
            plan.updated_at = datetime.now()
            await self.store.save_prototype_plan_with_items(plan, items)
            self._record_analysis(plan, len(items), started)
        except ProjectEvidenceError:
            message = await self._mark_failed_with_key(plan_id, "evidence_unavailable")
            self._record_analysis_failure(plan_id, project.id, message, started)
        except PrototypePlanError as exc:
            await self._mark_failed(plan_id, str(exc))
            self._record_analysis_failure(plan_id, project.id, str(exc), started)
        except Exception:
            logger.exception("prototype plan analysis failed: %s", plan_id)
            message = await self._mark_failed_with_key(plan_id, "analysis_failed")
            self._record_analysis_failure(
                plan_id,
                project.id,
                message,
                started,
            )

    async def _plan_with_mcp(
        self, project: Project, plan: PrototypePlan, manifest: ProjectSurfaceManifest
    ) -> None:
        if self.ui_engineer is None or self.mcp_service is None:
            raise AssertionError("prototype planning MCP dependencies disappeared")
        session = self.mcp_service.open_session(project=project, plan_id=plan.id, manifest=manifest)
        claude_config = getattr(session, "claude_config", None)
        if not callable(claude_config):
            self.mcp_service.close_session(session)
            raise PrototypePlanError("prototype planning MCP session is invalid")
        try:
            await self.ui_engineer.plan(
                project=project,
                plan_id=plan.id,
                prompt=self._build_mcp_prompt(project, plan),
                source_paths=self._planning_source_paths(manifest),
                mcp_config=claude_config(timeouts.prototype_planning_mcp_endpoint()),
            )
            completed, _ = await self.get_plan(plan.id)
            if completed.status != "ready" or completed.analysis_phase != "complete":
                raise PrototypePlanError("Claude did not finalize the prototype inventory")
        except RuntimeError as exc:
            raise PrototypePlanError(
                _planner_message(plan.output_locale, "ui_engineer_failed", detail=str(exc))
            ) from exc
        finally:
            self.mcp_service.close_session(session)

    async def _mark_failed(self, plan_id: str, message: str) -> None:
        loaded = await self.store.load_prototype_plan(plan_id)
        if loaded is None:
            logger.error("cannot persist prototype plan failure; plan disappeared: %s", plan_id)
            return
        plan, items = loaded
        plan.status = "analysis_failed"
        plan.analysis_phase = "failed"
        plan.error_message = message
        plan.updated_at = datetime.now()
        await self.store.save_prototype_plan_with_items(plan, items)

    async def _mark_failed_with_key(self, plan_id: str, key: str) -> str:
        loaded = await self.store.load_prototype_plan(plan_id)
        if loaded is None:
            logger.error("cannot persist prototype plan failure; plan disappeared: %s", plan_id)
            return _planner_message("en-US", key)
        plan, items = loaded
        message = _planner_message(plan.output_locale, key)
        plan.status = "analysis_failed"
        plan.analysis_phase = "failed"
        plan.error_message = message
        plan.updated_at = datetime.now()
        await self.store.save_prototype_plan_with_items(plan, items)
        return message

    async def _plan_with_ui_analysis(
        self,
        project: Project,
        plan: PrototypePlan,
        manifest: ProjectSurfaceManifest,
    ) -> _PlannerOutput:
        if self.ui_engineer is None and self.llm_runner is None:
            raise PrototypePlanError(_planner_message(plan.output_locale, "runtime_unavailable"))
        outputs: list[_PlannerOutput] = []
        candidates = manifest.candidates
        for offset in range(0, len(candidates), self.MAX_CANDIDATES_PER_LLM_CALL):
            batch_manifest = ProjectSurfaceManifest(
                repository_root=manifest.repository_root,
                packages=manifest.packages,
                candidates=candidates[offset : offset + self.MAX_CANDIDATES_PER_LLM_CALL],
                diagnostics=manifest.diagnostics,
                repository_fingerprint=manifest.repository_fingerprint,
            )
            outputs.extend(await self._plan_batch_with_split(project, plan, batch_manifest))
        project_context = self._merge_project_context(outputs)
        output = _PlannerOutput(
            project_context=project_context,
            items=[item for output in outputs for item in output.items],
        )
        self._validate_output_locale(plan.output_locale, output, require_context=True)
        return output

    async def _plan_batch_with_split(
        self,
        project: Project,
        plan: PrototypePlan,
        manifest: ProjectSurfaceManifest,
    ) -> list[_PlannerOutput]:
        try:
            output = await self._plan_batch(project, plan, manifest)
        except LLMOutputTokenLimitError as exc:
            if len(manifest.candidates) <= 1:
                raise PrototypePlanError(
                    _planner_message(plan.output_locale, "max_tokens")
                ) from exc
            midpoint = len(manifest.candidates) // 2
            plan.analysis_total += 1
            plan.updated_at = datetime.now()
            await self.store.save_prototype_plan_with_items(plan, [])
            split_outputs: list[_PlannerOutput] = []
            for candidates in (
                manifest.candidates[:midpoint],
                manifest.candidates[midpoint:],
            ):
                split_manifest = ProjectSurfaceManifest(
                    repository_root=manifest.repository_root,
                    packages=manifest.packages,
                    candidates=candidates,
                    diagnostics=manifest.diagnostics,
                    repository_fingerprint=manifest.repository_fingerprint,
                )
                split_outputs.extend(
                    await self._plan_batch_with_split(project, plan, split_manifest)
                )
            return split_outputs
        plan.analysis_completed += 1
        if plan.analysis_completed > plan.analysis_total:
            raise AssertionError("prototype analysis progress exceeded its persisted total")
        plan.updated_at = datetime.now()
        await self.store.save_prototype_plan_with_items(plan, [])
        return [output]

    @staticmethod
    def _merge_project_context(outputs: list[_PlannerOutput]) -> _PlannerProjectContext:
        def first_non_empty(values: list[str]) -> str:
            return next((value.strip() for value in values if value.strip()), "")

        return _PlannerProjectContext(
            product_summary=first_non_empty(
                [output.project_context.product_summary for output in outputs]
            ),
            audience=first_non_empty([output.project_context.audience for output in outputs]),
            visual_language=first_non_empty(
                [output.project_context.visual_language for output in outputs]
            ),
            shared_layout=first_non_empty(
                [output.project_context.shared_layout for output in outputs]
            ),
        )

    async def _plan_batch(
        self,
        project: Project,
        plan: PrototypePlan,
        manifest: ProjectSurfaceManifest,
    ) -> _PlannerOutput:
        if self.ui_engineer is None and self.llm_runner is None:
            raise PrototypePlanError(_planner_message(plan.output_locale, "runtime_unavailable"))
        prompt = self._build_prompt(project, plan, manifest)
        if self.ui_engineer is not None:
            async def persist_activity(activity: PrototypeArtifactActivity) -> None:
                if activity.last_event_at is None:
                    return
                plan.updated_at = activity.last_event_at
                await self.store.save_prototype_plan_with_items(plan, [])

            try:
                raw = await self.ui_engineer.plan(
                    project=project,
                    plan_id=plan.id,
                    prompt=prompt,
                    source_paths=self._planning_source_paths(manifest),
                    activity_callback=persist_activity,
                )
            except RuntimeError as exc:
                raise PrototypePlanError(
                    _planner_message(
                        plan.output_locale,
                        "ui_engineer_failed",
                        detail=str(exc),
                    )
                ) from exc
        else:
            if self.llm_runner is None:
                raise AssertionError("prototype planning runtime disappeared")
            raw = await self.llm_runner(prompt)
        if not raw:
            raise PrototypePlanError(_planner_message(plan.output_locale, "no_result"))
        if not _has_complete_single_object_envelope(raw):
            raise PrototypePlanError(_planner_message(plan.output_locale, "invalid_json"))
        parsed = parse_json_object(raw)
        if parsed is None:
            try:
                repaired = tolerant_json_loads(raw)
            except json.JSONDecodeError as exc:
                raise PrototypePlanError(
                    _planner_message(plan.output_locale, "invalid_json")
                ) from exc
            if not isinstance(repaired, dict):
                raise PrototypePlanError(_planner_message(plan.output_locale, "invalid_json"))
            parsed = repaired
        try:
            output = _PlannerOutput.model_validate(parsed)
        except ValidationError as exc:
            raise PrototypePlanError(
                _planner_message(
                    plan.output_locale,
                    "invalid_schema",
                    fields=self._validation_error_fields(exc),
                )
            ) from exc
        self._validate_output_locale(plan.output_locale, output, require_context=False)
        return output

    @staticmethod
    def _validate_output_locale(
        locale: PlanOutputLocale,
        output: _PlannerOutput,
        *,
        require_context: bool,
    ) -> None:
        failures: list[str] = []
        context = output.project_context
        context_values = (
            ("product_summary", context.product_summary),
            ("audience", context.audience),
            ("visual_language", context.visual_language),
            ("shared_layout", context.shared_layout),
        )
        for field_name, value in context_values:
            if not value:
                if require_context:
                    failures.append(f"project_context.{field_name}")
            elif not _has_locale_signal(value, locale):
                failures.append(f"project_context.{field_name}")

        for item in output.items:
            if not _has_locale_signal(item.title, locale):
                failures.append(f"{item.candidate_id}.title")
            if not _has_locale_signal(item.summary, locale):
                failures.append(f"{item.candidate_id}.summary")
            if not _has_locale_signal(item.brief, locale):
                failures.append(f"{item.candidate_id}.brief")
        if failures:
            raise PrototypePlanError(
                _planner_message(
                    locale,
                    "invalid_locale",
                    fields=", ".join(failures[:12]),
                )
            )

    async def wait_for_analysis(
        self, plan_id: str
    ) -> tuple[PrototypePlan, list[PrototypePlanItem]]:
        while True:
            plan, items = await self.get_plan(plan_id)
            if plan.status in self.TERMINAL_STATUSES:
                return plan, items
            await asyncio.sleep(0.05)

    def _build_prompt(
        self, project: Project, plan: PrototypePlan, manifest: ProjectSurfaceManifest
    ) -> str:
        source_index = json.dumps(
            self._planning_source_index(manifest), ensure_ascii=False, indent=2
        )
        prompt = "\n".join(
            [
                "You are the prototype UI engineer creating a restore-first prototype plan.",
                "Read the real project source in the isolated worktree before writing the plan.",
                "Do not modify project files and do not generate HTML in this planning task.",
                "The repository index below is a source map, not source content. Start with the listed source files and return the page checklist derived from that code.",
                "Do not invent routes or product capabilities. Every item must use a candidate_id and evidence_id from the repository index.",
                "The initial mode is restore: preserve the current information architecture, navigation, layout, and visual signals.",
                "Return JSON only, with no markdown fences or commentary.",
                (
                    "Write all user-facing project context, titles, summaries, and briefs in "
                    + (
                        "Simplified Chinese (zh-CN)."
                        if plan.output_locale == "zh-CN"
                        else "English (en-US)."
                    )
                    + " Keep code identifiers, file paths, and routes unchanged."
                ),
                f"Project: {project.name}",
                f"Optional user instruction: {plan.global_instruction or '(none; infer from evidence)'}",
                "Required JSON shape:",
                '{"project_context":{"product_summary":"...","audience":"...","visual_language":"...","shared_layout":"..."},"items":[{"candidate_id":"...","title":"...","summary":"...","brief":"...","states":["default"],"evidence_ids":["evidence--..."]}]}',
                "All four project_context fields must be non-empty and follow the requested output language.",
                "Every summary and brief must follow that language; preserve product proper nouns in titles, but do not return an entire title batch in another language.",
                "States are stable machine identifiers, not localized copy. Prefer default, loading, empty, error, or success; route-derived identifiers may also use lowercase letters, digits, colon, slash, dot, underscore, and hyphen.",
                "Include exactly one item for every supported candidate_id. Keep candidate_id unchanged.",
                "Each brief must describe a single-file HTML prototype that preserves current structure, with representative empty/loading/error states only when evidence supports them.",
                "Repository index:",
                source_index,
            ]
        )
        if len(prompt) > self.MAX_PROMPT_CHARS:
            raise PrototypePlanError(
                _planner_message(
                    plan.output_locale,
                    "prompt_limit",
                    actual=len(prompt),
                    limit=self.MAX_PROMPT_CHARS,
                )
            )
        return prompt

    @staticmethod
    def _build_mcp_prompt(project: Project, plan: PrototypePlan) -> str:
        return "\n".join(
            (
                "You are the prototype UI engineer creating a restore-first page inventory.",
                "Do not modify project files and do not generate HTML in this task.",
                "First call list_discovered_pages. Then inspect the real source files in the isolated worktree.",
                "For each logical page you understand, call register_prototype_page immediately.",
                "Use only candidate_id and evidence_ids returned by list_discovered_pages.",
                "Write all user-facing titles, summaries, briefs, and project context in "
                + ("Simplified Chinese (zh-CN)." if plan.output_locale == "zh-CN" else "English (en-US)."),
                "After every page is registered, call finalize_prototype_inventory with project_context.",
                "Do not return a planning JSON document. Reply with a short completion acknowledgement only after finalization succeeds.",
                f"Project: {project.name}",
                f"Optional user instruction: {plan.global_instruction or '(none; infer from source)'}",
            )
        )

    @staticmethod
    def _planning_source_index(manifest: ProjectSurfaceManifest) -> dict[str, object]:
        """Describe the files Claude may inspect without duplicating their contents."""
        return {
            "repository_fingerprint": manifest.repository_fingerprint,
            "packages": [
                {
                    "package_root": package.package_root,
                    "manifest_path": package.manifest_path,
                    "framework_signals": list(package.framework_signals),
                    "entry_candidates": list(package.entry_candidates),
                    "style_candidates": list(package.style_candidates),
                }
                for package in manifest.packages
            ],
            "candidates": [
                {
                    "candidate_id": candidate.candidate_id,
                    "route_patterns": list(candidate.route_patterns),
                    "surface_kind": candidate.surface_kind,
                    "framework_hint": candidate.framework_hint,
                    "primary_source_path": candidate.primary_source_path,
                    "source_paths": list(candidate.source_paths),
                    "layout_paths": list(candidate.layout_paths),
                    "evidence": [
                        {
                            "evidence_id": evidence.evidence_id,
                            "path": evidence.path,
                            "start_line": evidence.start_line,
                            "end_line": evidence.end_line,
                            "kind": evidence.kind,
                            "detail": evidence.detail,
                            "confidence": evidence.confidence,
                        }
                        for evidence in candidate.evidence
                    ],
                }
                for candidate in manifest.candidates
            ],
        }

    @staticmethod
    def _planning_source_paths(manifest: ProjectSurfaceManifest) -> tuple[str, ...]:
        paths: set[str] = set()
        for package in manifest.packages:
            paths.add(package.manifest_path)
            paths.update(package.entry_candidates)
            paths.update(package.style_candidates)
        for candidate in manifest.candidates:
            paths.update(candidate.source_paths)
            paths.update(candidate.layout_paths)
            paths.update(evidence.path for evidence in candidate.evidence)
        return tuple(sorted(path for path in paths if path))

    @staticmethod
    def _validation_error_fields(exc: ValidationError) -> str:
        fields = [".".join(str(part) for part in error["loc"]) for error in exc.errors()[:12]]
        return ", ".join(fields) or "unknown"

    async def _build_items(
        self, plan: PrototypePlan, manifest: ProjectSurfaceManifest, output: _PlannerOutput
    ) -> list[PrototypePlanItem]:
        candidates = {candidate.candidate_id: candidate for candidate in manifest.candidates}
        drafts = {item.candidate_id: item for item in output.items}
        missing = sorted(set(candidates) - set(drafts))
        unknown = sorted(set(drafts) - set(candidates))
        if missing or unknown or len(drafts) != len(output.items):
            if plan.output_locale == "zh-CN":
                details = ", ".join(
                    [*(f"缺少 {item}" for item in missing), *(f"未知 {item}" for item in unknown)]
                )
            else:
                details = ", ".join(
                    [
                        *(f"missing {item}" for item in missing),
                        *(f"unknown {item}" for item in unknown),
                    ]
                )
            raise PrototypePlanError(
                _planner_message(plan.output_locale, "coverage", details=details)
            )
        existing = await self._existing_prototypes(plan.project_id)
        items: list[PrototypePlanItem] = []
        now = datetime.now()
        for candidate in sorted(manifest.candidates, key=lambda item: item.candidate_id):
            draft = drafts[candidate.candidate_id]
            valid_evidence_ids = {item.evidence_id for item in candidate.evidence}
            unknown_evidence_ids = sorted(set(draft.evidence_ids) - valid_evidence_ids)
            if unknown_evidence_ids:
                raise PrototypePlanError(
                    _planner_message(
                        plan.output_locale,
                        "unknown_evidence",
                        details=", ".join(unknown_evidence_ids),
                    )
                )
            action = self._candidate_action(candidate, existing)
            items.append(
                PrototypePlanItem(
                    id=f"prototype-plan-item-{uuid4().hex}",
                    plan_id=plan.id,
                    candidate_id=candidate.candidate_id,
                    package_root=candidate.package_root,
                    surface_kind=candidate.surface_kind,
                    route_patterns=list(candidate.route_patterns),
                    primary_source_path=candidate.primary_source_path,
                    source_paths=list(candidate.source_paths),
                    layout_paths=list(candidate.layout_paths),
                    title=draft.title,
                    summary=draft.summary,
                    brief=draft.brief,
                    states=draft.states,
                    evidence_ids=draft.evidence_ids,
                    evidence=[
                        item.to_dict()
                        for item in candidate.evidence
                        if item.evidence_id in set(draft.evidence_ids)
                    ],
                    confidence=candidate.confidence,
                    action=action,
                    selected=candidate.confidence in {"high", "medium"}
                    and action in {"create", "update"},
                    source_hash=candidate.source_hash,
                    created_at=now,
                    updated_at=now,
                )
            )
        discovered_ids = set(candidates)
        for prototype in existing:
            if (
                prototype.source_kind != "code"
                or not prototype.source_ref
                or prototype.source_ref in discovered_ids
            ):
                continue
            seed = await self.store.load_prototype_version(prototype.id, 0)
            brief = seed.instruction if seed and seed.instruction else ""
            items.append(
                PrototypePlanItem(
                    id=f"prototype-plan-item-{uuid4().hex}",
                    plan_id=plan.id,
                    candidate_id=prototype.source_ref,
                    package_root="unknown",
                    surface_kind="unknown",
                    route_patterns=[],
                    primary_source_path=None,
                    source_paths=[],
                    layout_paths=[],
                    title=prototype.title,
                    summary=(
                        "此前生成的源码页面已不在当前项目中."
                        if plan.output_locale == "zh-CN"
                        else "Previously generated source-backed page is no longer present in the repository."
                    ),
                    brief=brief or prototype.title,
                    states=["缺失" if plan.output_locale == "zh-CN" else "missing"],
                    evidence_ids=[],
                    evidence=[],
                    confidence="low",
                    action="missing",
                    selected=False,
                    source_hash=prototype.source_hash or "",
                    prototype_id=prototype.id,
                    created_at=now,
                    updated_at=now,
                )
            )
        return items

    @staticmethod
    def _localized_diagnostics(
        locale: PlanOutputLocale,
        diagnostics: tuple[str, ...],
    ) -> list[str]:
        if locale == "en-US":
            return list(diagnostics)
        localized: list[str] = []
        for diagnostic in diagnostics:
            message = diagnostic
            for source, translated in _ZH_DIAGNOSTIC_MESSAGES.items():
                if diagnostic == source:
                    message = translated
                    break
                suffix = f": {source}"
                if diagnostic.endswith(suffix):
                    message = diagnostic[: -len(source)] + translated
                    break
            localized.append(message)
        return localized

    async def _existing_prototypes(self, project_id: str) -> list[Prototype]:
        return await self.store.list_prototypes(project_id)

    def _candidate_action(
        self, candidate: PrototypeCandidate, existing: list[Prototype]
    ) -> PlanAction:
        for item in existing:
            if item.source_kind != "code" or item.source_ref != candidate.candidate_id:
                continue
            return "unchanged" if item.source_hash == candidate.source_hash else "update"
        if candidate.action == "create":
            return "create"
        if candidate.action == "update":
            return "update"
        if candidate.action == "unchanged":
            return "unchanged"
        if candidate.action == "missing":
            return "missing"
        if candidate.action == "unsupported":
            return "unsupported"
        return "unsupported"

    def _scope(self, manifest: ProjectSurfaceManifest) -> dict[str, object]:
        return {
            "packages": [item.package_root for item in manifest.packages],
            "supported_packages": [
                item.package_root for item in manifest.packages if item.support == "supported"
            ],
            "candidate_count": len(manifest.candidates),
        }

    def _record_analysis(self, plan: PrototypePlan, count: int, started: float) -> None:
        record_event(
            {
                "type": "prototype_plan_analysis",
                "payload": {
                    "project_id": plan.project_id,
                    "plan_id": plan.id,
                    "status": plan.status,
                    "candidate_count": count,
                    "duration_ms": int((time.monotonic() - started) * 1000),
                },
            }
        )

    def _record_analysis_failure(
        self,
        plan_id: str,
        project_id: str,
        error: str,
        started: float,
    ) -> None:
        record_event(
            {
                "type": "prototype_plan_analysis",
                "payload": {
                    "project_id": project_id,
                    "plan_id": plan_id,
                    "status": "analysis_failed",
                    "error": error,
                    "duration_ms": int((time.monotonic() - started) * 1000),
                },
            }
        )
