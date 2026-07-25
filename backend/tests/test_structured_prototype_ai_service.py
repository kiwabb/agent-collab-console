from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

import aiosqlite
import pytest
from structured_prototype_fixtures import fixture_id, procurement_document_payload

from app.adapters.prototype_object_store import PrototypeObjectStore
from app.adapters.prototype_render_artifact_store import PrototypeRenderArtifactStore
from app.adapters.prototype_renderer_worker import (
    PrototypeRendererWorker,
    PrototypeRendererWorkerError,
)
from app.adapters.structured_prototype_store import AsyncStructuredPrototypeStore
from app.application.structured_prototype_ai_contracts import (
    PrototypeAiSelectionV1,
    PrototypeAssistantOutcomeEnvelopeV1,
    PrototypeAssistantOutcomeV1,
)
from app.application.structured_prototype_ai_mcp import PrototypeAiSubmissionReceipt
from app.application.structured_prototype_ai_runtime import (
    PrototypeUiEngineerTaskRequest,
    PrototypeUiEngineerTaskResult,
)
from app.application.structured_prototype_ai_service import (
    PrototypeUiEngineerExecution,
    StructuredPrototypeAiService,
    StructuredPrototypeAiServiceError,
)
from app.application.structured_prototype_contracts import (
    DomainCommandBatchV1,
    FreeformNodeV1,
    NewPrototypeDocumentV1,
    PrototypeDocumentV1,
    StackNodeV1,
    TextNodeV1,
    freeform_grid_list_hash,
)
from app.application.structured_prototype_service import (
    PrototypeRendererExecution,
    StructuredPrototypeService,
)
from app.domain.models import Project
from app.domain.structured_prototype import PrototypeRendererWorkerResult

FIXED_NOW = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)

OutcomeBuilder = Callable[
    [PrototypeDocumentV1, str, str],
    PrototypeAssistantOutcomeV1,
]


def _new_document() -> NewPrototypeDocumentV1:
    payload = procurement_document_payload()
    payload.pop("id")
    return NewPrototypeDocumentV1.model_validate(
        payload,
        strict=True,
        by_alias=True,
        by_name=False,
    )


def _new_freeform_document() -> NewPrototypeDocumentV1:
    payload = procurement_document_payload()
    payload.pop("id")
    pages = payload["pages"]
    assert isinstance(pages, list)
    list_page = pages[0]
    assert isinstance(list_page, dict)
    original_root = list_page["root"]
    assert isinstance(original_root, dict)
    children = original_root["children"]
    assert isinstance(children, list)
    for index, child in enumerate(children):
        assert isinstance(child, dict)
        layout_item = child["layoutItem"]
        assert isinstance(layout_item, dict)
        layout_item["position"] = {"x": str(32 + index * 360), "y": "48"}
    root_layout = original_root["layoutItem"]
    assert isinstance(root_layout, dict)
    root_layout["width"] = {"unit": "px", "value": "1200"}
    root_layout["height"] = {"unit": "px", "value": "800"}
    list_page["root"] = {
        "id": original_root["id"],
        "type": "Freeform",
        "name": original_root["name"],
        "visibility": original_root["visibility"],
        "layoutItem": root_layout,
        "responsive": [],
        "children": children,
        "grids": [
            {
                "id": fixture_id("service-move-grid-square"),
                "version": 1,
                "type": "square",
                "visible": True,
                "snapEnabled": True,
                "origin": {"x": "0", "y": "0"},
                "params": {
                    "size": "16",
                    "colorTokenKey": "primary",
                    "opacity": "0.24",
                },
            },
            {
                "id": fixture_id("service-move-grid-columns"),
                "version": 1,
                "type": "columns",
                "visible": True,
                "snapEnabled": True,
                "origin": {"x": "0", "y": "0"},
                "params": {
                    "count": 12,
                    "itemSize": None,
                    "gutter": "8",
                    "margin": "24",
                    "alignment": "stretch",
                    "colorTokenKey": "primary",
                    "opacity": "0.18",
                },
            },
        ],
    }
    return NewPrototypeDocumentV1.model_validate(
        payload,
        strict=True,
        by_alias=True,
        by_name=False,
    )


def _freeform_move_evidence_batch(
    document: PrototypeDocumentV1,
    *,
    draft_id: str,
    base_head_sequence_no: int,
    base_document_hash: str,
    delta_x: Decimal = Decimal("8"),
    delta_y: Decimal = Decimal("4"),
) -> DomainCommandBatchV1:
    root = document.pages[0].root
    assert isinstance(root, FreeformNodeV1)
    selected = root.children[:2]
    selected_ids = {child.id for child in selected}
    commands: list[dict[str, object]] = []
    for index, child in enumerate(selected):
        position = child.layout_item.position
        assert position is not None
        commands.append(
            {
                "kind": "moveNode",
                "node": {"kind": "existing", "nodeId": child.id},
                "targetParent": {"kind": "existing", "nodeId": root.id},
                "targetSlot": None,
                "targetIndex": index,
                "targetPosition": {
                    "x": str(Decimal(position.x) + delta_x),
                    "y": str(Decimal(position.y) + delta_y),
                },
            }
        )
    direct_siblings = []
    for child in root.children:
        if child.id in selected_ids:
            continue
        position = child.layout_item.position
        assert position is not None
        direct_siblings.append(
            {
                "nodeId": child.id,
                "x": position.x,
                "y": position.y,
                "width": "200",
                "height": "320",
            }
        )
    direct_siblings.sort(key=lambda sibling: str(sibling["nodeId"]))
    grids = [grid.model_dump(mode="json", by_alias=True) for grid in root.grids]
    selected_positions = [child.layout_item.position for child in selected]
    assert all(position is not None for position in selected_positions)
    selection_x = min(
        Decimal(position.x) for position in selected_positions if position is not None
    )
    selection_y = min(
        Decimal(position.y) for position in selected_positions if position is not None
    )
    final_x = selection_x + delta_x
    final_y = selection_y + delta_y
    return DomainCommandBatchV1.model_validate(
        {
            "commandContractVersion": 1,
            "summary": "移动自由布局组件组",
            "commands": commands,
            "evidence": {
                "evidenceVersion": 2,
                "kind": "freeformMove",
                "snapSolverVersion": "structured-prototype-freeform-snap/v1",
                "snapSolverSourceHash": "sha256:" + "f" * 64,
                "documentId": document.id,
                "draftId": draft_id,
                "freeformId": root.id,
                "baseHeadSequenceNo": base_head_sequence_no,
                "baseDocumentHash": base_document_hash,
                "selectedNodeIds": sorted(selected_ids),
                "grids": grids,
                "gridListHash": freeform_grid_list_hash(root.grids),
                "gridSnappingEnabled": True,
                "previewScale": "1",
                "clientThreshold": "6",
                "selectionBounds": {
                    "x": str(selection_x),
                    "y": str(selection_y),
                    "width": "960",
                    "height": "320",
                },
                "directSiblings": direct_siblings,
                "containerSize": {"width": "1200", "height": "800"},
                "requestedDelta": {"x": str(delta_x), "y": str(delta_y)},
                "rawPosition": {"x": str(final_x), "y": str(final_y)},
                "finalPosition": {"x": str(final_x), "y": str(final_y)},
                "correction": {"x": "0", "y": "0"},
                "bypassSnapping": True,
                "axisWinners": {"x": "raw", "y": "raw"},
                "candidates": [],
                "terminalReason": "pointerup",
            },
        },
        strict=True,
        by_alias=True,
        by_name=False,
    )


def _document_selection() -> PrototypeAiSelectionV1:
    return PrototypeAiSelectionV1(
        scope="document",
        page_id=None,
        selected_node_ids=[],
        flow_id=None,
        viewport="desktop",
    )


def _flow_rule_new_document() -> NewPrototypeDocumentV1:
    payload = procurement_document_payload()
    rule_id = fixture_id("ai-flow-rule")
    runtime = payload["runtime"]
    assert isinstance(runtime, dict)
    runtime["rules"] = [
        {
            "id": rule_id,
            "key": "submit-to-detail",
            "enabled": True,
            "trigger": {
                "kind": "nodeEvent",
                "nodeId": fixture_id("button-submit"),
                "event": "click",
            },
            "guard": {
                "kind": "roleIs",
                "roleId": fixture_id("role-applicant"),
            },
            "effects": [{"kind": "navigate", "targetPageId": fixture_id("page-detail")}],
            "guardFalseEffects": [],
        }
    ]
    payload["flows"] = [
        {
            "id": fixture_id("ai-flow-projection"),
            "key": "submit-to-detail",
            "ruleId": rule_id,
            "fromNodeId": fixture_id("button-submit"),
            "toPageId": fixture_id("page-detail"),
        }
    ]
    payload.pop("id")
    return NewPrototypeDocumentV1.model_validate(
        payload,
        strict=True,
        by_alias=True,
        by_name=False,
    )


def _runtime_table_new_document() -> NewPrototypeDocumentV1:
    payload = procurement_document_payload()
    pages = payload["pages"]
    assert isinstance(pages, list)
    list_page = pages[0]
    assert isinstance(list_page, dict)
    root = list_page["root"]
    assert isinstance(root, dict)
    children = root["children"]
    assert isinstance(children, list)
    table = children[1]
    assert isinstance(table, dict)
    schema_id = fixture_id("table-schema")
    field_id = fixture_id("table-schema-title")
    table["columns"] = [{"key": "title", "label": "标题", "fieldId": field_id}]
    table["rows"] = []
    runtime = payload["runtime"]
    assert isinstance(runtime, dict)
    runtime["entitySchemas"] = [
        {
            "id": schema_id,
            "key": "table-record",
            "fields": [
                {
                    "id": field_id,
                    "key": "title",
                    "valueType": "string",
                    "nullable": False,
                }
            ],
        }
    ]
    runtime["viewBindings"] = [
        {
            "id": fixture_id("table-view-binding"),
            "nodeId": fixture_id("table-list"),
            "target": "tableRows",
            "schemaId": schema_id,
            "sortFieldId": field_id,
            "sortDirection": "asc",
        }
    ]
    scenarios = runtime["scenarios"]
    assert isinstance(scenarios, list)
    scenario = scenarios[0]
    assert isinstance(scenario, dict)
    scenario["entityFixtures"] = [
        {
            "schemaId": schema_id,
            "entities": [
                {
                    "id": fixture_id("table-entity-open"),
                    "schemaId": schema_id,
                    "fields": [
                        {
                            "fieldId": field_id,
                            "value": {"type": "string", "value": "办公电脑采购"},
                        }
                    ],
                }
            ],
        }
    ]
    payload.pop("id")
    return NewPrototypeDocumentV1.model_validate(
        payload,
        strict=True,
        by_alias=True,
        by_name=False,
    )


def _outcome(payload: dict[str, object]) -> PrototypeAssistantOutcomeV1:
    return PrototypeAssistantOutcomeEnvelopeV1.model_validate(
        {"outcome": payload},
        strict=True,
        by_alias=True,
        by_name=False,
    ).outcome


def _runtime_field_outcome() -> PrototypeAssistantOutcomeV1:
    scenario_id = fixture_id("scenario-happy-path")
    schema_id = fixture_id("table-schema")
    entity_id = fixture_id("table-entity-open")
    field_id = fixture_id("table-schema-title")
    summary = "修改运行时表格数据"
    return _outcome(
        {
            "contractVersion": 1,
            "kind": "commandProposal",
            "message": "准备修改。",
            "summary": summary,
            "batch": {
                "commandContractVersion": 1,
                "summary": summary,
                "commands": [
                    {
                        "kind": "setRuntimeEntityField",
                        "scenarioId": scenario_id,
                        "schemaId": schema_id,
                        "entityId": entity_id,
                        "fieldId": field_id,
                        "value": {"type": "string", "value": "已更新的采购事项"},
                    }
                ],
            },
            "affectedEntityIds": [scenario_id, schema_id, entity_id, field_id],
        }
    )


class _ProjectStore:
    def __init__(self, project: Project) -> None:
        self.project = project

    async def load_project(self, project_id: str) -> Project | None:
        return self.project if project_id == self.project.id else None


class _Runtime:
    def __init__(self, outcome: PrototypeAssistantOutcomeV1) -> None:
        self.outcome = outcome
        self.requests: list[PrototypeUiEngineerTaskRequest] = []

    async def execute(
        self,
        request: PrototypeUiEngineerTaskRequest,
    ) -> PrototypeUiEngineerTaskResult:
        self.requests.append(request)
        return PrototypeUiEngineerTaskResult(
            task_id=request.task_id,
            execution_process_id="process-1",
            outcome=self.outcome,
            submission=PrototypeAiSubmissionReceipt(
                submission_id="submission-1",
                request_hash="sha256:" + "a" * 64,
                accepted_at=1.0,
            ),
        )


class _UnexpectedRuntime:
    async def execute(
        self,
        request: PrototypeUiEngineerTaskRequest,
    ) -> PrototypeUiEngineerTaskResult:
        del request
        raise RuntimeError("unexpected runtime failure")


class _FailingRenderer:
    def __init__(self, renderer: PrototypeRendererWorker) -> None:
        self.identity = renderer.identity

    async def render(
        self,
        *,
        request_id: str,
        artifact_id: str,
        input_manifest: dict[str, object],
        document: dict[str, object],
    ) -> PrototypeRendererWorkerResult:
        del request_id, artifact_id, input_manifest, document
        raise PrototypeRendererWorkerError(
            "renderer_test_failure",
            "renderer failed for the failure-evidence regression",
        )


async def _fixture(
    tmp_path: Path,
    outcome: PrototypeAssistantOutcomeV1,
    runtime: PrototypeUiEngineerExecution | None = None,
    renderer_worker: PrototypeRendererExecution | None = None,
    document: NewPrototypeDocumentV1 | None = None,
) -> tuple[
    AsyncStructuredPrototypeStore,
    StructuredPrototypeService,
    StructuredPrototypeAiService,
    str,
    str,
]:
    store = AsyncStructuredPrototypeStore(tmp_path / "console.db")
    object_store = PrototypeObjectStore(tmp_path / "managed")
    renderer = PrototypeRendererWorker()
    artifact_store = PrototypeRenderArtifactStore(tmp_path / "managed")
    structured = StructuredPrototypeService(
        store=store,
        object_store=object_store,
        renderer_worker=renderer,
        artifact_store=artifact_store,
        clock=lambda: FIXED_NOW,
    )
    created = await structured.create_document(
        project_id="project-1",
        client_request_id=fixture_id("ai-create-document"),
        document=document if document is not None else _new_document(),
    )
    project = Project(
        id="project-1",
        name="Procurement",
        repo_path=str(tmp_path),
        default_branch="main",
    )
    ai_service = StructuredPrototypeAiService(
        store=store,
        project_store=_ProjectStore(project),
        object_store=object_store,
        structured_service=structured,
        runtime=runtime if runtime is not None else _Runtime(outcome),
        renderer_worker=renderer_worker if renderer_worker is not None else renderer,
        artifact_store=artifact_store,
        clock=lambda: FIXED_NOW,
    )
    thread = await ai_service.create_thread(
        document_id=created.state.document_record.id,
        client_request_id=fixture_id("ai-create-thread"),
        title="采购原型调整",
    )
    return store, structured, ai_service, created.state.draft.id, thread.id


def _page_selection() -> PrototypeAiSelectionV1:
    return PrototypeAiSelectionV1(
        scope="page",
        page_id=fixture_id("page-list"),
        selected_node_ids=[],
        flow_id=None,
        viewport="desktop",
    )


@pytest.mark.asyncio
async def test_answer_is_durable_without_changing_the_draft(tmp_path: Path) -> None:
    answer = _outcome(
        {
            "contractVersion": 1,
            "kind": "answer",
            "message": "当前列表页包含标题和申请表格。",
        }
    )
    store, _, service, draft_id, thread_id = await _fixture(tmp_path, answer)
    try:
        draft = await store.load_draft(draft_id)
        assert draft is not None
        queued = await service.send_message(
            thread_id=thread_id,
            client_message_id=fixture_id("ai-answer-message"),
            draft_id=draft_id,
            expected_head_sequence_no=draft.head_sequence_no,
            expected_document_hash=draft.head_document_hash,
            content="这个页面现在有什么?",
            selection=_page_selection(),
        )
        completed = await service.wait_for_run(queued.id)

        assert completed.status == "completed_answer"
        assert completed.submission_id == "submission-1"
        assert completed.submission_request_hash == "sha256:" + "a" * 64
        assert completed.submission_accepted_at is not None
        assert completed.replay_manifest_object_hash is not None
        unchanged = await store.load_draft(draft_id)
        assert unchanged is not None
        assert unchanged.head_sequence_no == 0
        snapshot = await service.get_thread(thread_id)
        assert [message.kind for message in snapshot.messages] == ["instruction", "answer"]
        assert snapshot.messages[-1].content == "当前列表页包含标题和申请表格。"
        operation = await store.load_operation(completed.operation_id)
        assert operation is not None
        assert operation.status == "succeeded"
        assert operation.result_manifest_hash == completed.replay_manifest_object_hash
        replay_descriptor = await store.load_object(
            "project-1", completed.replay_manifest_object_hash
        )
        assert replay_descriptor is not None
        replay_references = await store.list_object_references(
            "project-1", "replay_manifest", completed.operation_id
        )
        assert [reference.content_hash for reference in replay_references] == [
            completed.replay_manifest_object_hash
        ]
        events = await store.list_operation_events(completed.operation_id)
        assert [event.event_no for event in events] == list(range(len(events)))
        assert events[-1].status == "succeeded"
        assert {event.phase for event in events} >= {
            "storing_submission",
            "finalizing_evidence",
        }
        async with (
            aiosqlite.connect(tmp_path / "console.db") as conn,
            conn.execute("PRAGMA table_info(prototype_ai_edit_runs)") as cursor,
        ):
            columns = {str(row[1]) for row in await cursor.fetchall()}
        assert {
            "submission_id",
            "submission_request_hash",
            "submission_accepted_at",
            "replay_manifest_object_hash",
        }.issubset(columns)
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_command_proposal_renders_then_applies_one_ai_batch_and_checkpoint(
    tmp_path: Path,
) -> None:
    title_id = fixture_id("title-list")
    summary = "将列表标题改为全部采购申请"
    proposal = _outcome(
        {
            "contractVersion": 1,
            "kind": "commandProposal",
            "message": "已准备标题调整, 可先查看预览。",
            "summary": summary,
            "batch": {
                "commandContractVersion": 1,
                "summary": summary,
                "commands": [
                    {
                        "kind": "setNodeProperty",
                        "node": {"kind": "existing", "nodeId": title_id},
                        "update": {"kind": "textContent", "content": "全部采购申请"},
                    }
                ],
            },
            "affectedEntityIds": [title_id],
        }
    )
    store, _, service, draft_id, thread_id = await _fixture(tmp_path, proposal)
    try:
        draft = await store.load_draft(draft_id)
        assert draft is not None
        queued = await service.send_message(
            thread_id=thread_id,
            client_message_id=fixture_id("ai-proposal-message"),
            draft_id=draft_id,
            expected_head_sequence_no=0,
            expected_document_hash=draft.head_document_hash,
            content="把列表标题改成全部采购申请",
            selection=_page_selection(),
        )
        ready = await service.wait_for_run(queued.id)

        assert ready.status == "preview_ready"
        assert ready.context_object_hash is not None
        assert ready.outcome_object_hash is not None
        assert ready.submission_id == "submission-1"
        assert ready.submission_request_hash == "sha256:" + "a" * 64
        assert ready.replay_manifest_object_hash is not None
        assert ready.candidate_object_hash is not None
        assert ready.preview_artifact_id is not None
        preview = await service.read_preview_file(run_id=ready.id, relative_path="index.html")
        assert b"<!doctype html>" in preview.content.lower()

        applied = await service.apply(
            run_id=ready.id,
            client_request_id=fixture_id("ai-apply-proposal"),
            expected_head_sequence_no=0,
            expected_document_hash=draft.head_document_hash,
        )
        assert applied.run.status == "applied"
        assert applied.draft_result.state.draft.head_sequence_no == 1
        page = applied.draft_result.state.document.pages[0]
        assert isinstance(page.root, StackNodeV1)
        title = page.root.children[0]
        assert isinstance(title, TextNodeV1)
        assert title.content == "全部采购申请"

        bundle = await store.load_draft_recovery_bundle(draft_id)
        assert bundle.checkpoint.checkpoint_kind == "ai_apply"
        assert bundle.checkpoint.checkpoint_sequence_no == 1
        assert (
            bundle.checkpoint.history_snapshot_object_hash
            == bundle.history_object_descriptor.content_hash
        )
        assert len(bundle.command_batches) == 0
        checkpoint_references = await store.list_object_references(
            "project-1",
            "checkpoint",
            bundle.checkpoint.id,
        )
        assert {reference.payload_type for reference in checkpoint_references} == {
            "prototype_document",
            "prototype_command_history_checkpoint",
        }
        snapshot = await service.get_thread(thread_id)
        assert snapshot.messages[-1].status == "applied"
        assert snapshot.messages[-1].command_batch_id == applied.command_batch_id
        async with (
            aiosqlite.connect(tmp_path / "console.db") as conn,
            conn.execute(
                "SELECT operation_id FROM prototype_command_batches WHERE id = ?",
                (applied.command_batch_id,),
            ) as cursor,
        ):
            operation_row = await cursor.fetchone()
        assert operation_row is not None
        apply_operation = await store.load_operation(str(operation_row[0]))
        assert apply_operation is not None
        assert apply_operation.status == "succeeded"
        assert apply_operation.result_manifest_hash is not None
        assert (
            await store.load_object("project-1", apply_operation.result_manifest_hash) is not None
        )
        apply_references = await store.list_object_references(
            "project-1", "replay_manifest", apply_operation.id
        )
        assert [reference.content_hash for reference in apply_references] == [
            apply_operation.result_manifest_hash
        ]
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_preview_renderer_failure_persists_gap_free_terminal_evidence(
    tmp_path: Path,
) -> None:
    title_id = fixture_id("title-list")
    proposal = _outcome(
        {
            "contractVersion": 1,
            "kind": "commandProposal",
            "message": "Preview this title adjustment.",
            "summary": "Adjust the list title",
            "batch": {
                "commandContractVersion": 1,
                "summary": "Adjust the list title",
                "commands": [
                    {
                        "kind": "setNodeProperty",
                        "node": {"kind": "existing", "nodeId": title_id},
                        "update": {"kind": "textContent", "content": "All requests"},
                    }
                ],
            },
            "affectedEntityIds": [title_id],
        }
    )
    renderer = _FailingRenderer(PrototypeRendererWorker())
    store, _, service, draft_id, thread_id = await _fixture(
        tmp_path,
        proposal,
        renderer_worker=renderer,
    )
    try:
        draft = await store.load_draft(draft_id)
        assert draft is not None
        queued = await service.send_message(
            thread_id=thread_id,
            client_message_id=fixture_id("ai-renderer-failure-message"),
            draft_id=draft_id,
            expected_head_sequence_no=0,
            expected_document_hash=draft.head_document_hash,
            content="Adjust the list title",
            selection=_page_selection(),
        )

        failed = await service.wait_for_run(queued.id)

        assert failed.status == "failed"
        assert failed.error_code == "renderer_test_failure"
        operation = await store.load_operation(failed.operation_id)
        assert operation is not None
        assert operation.status == "failed"
        events = await store.list_operation_events(operation.id)
        assert [event.event_no for event in events] == list(range(len(events)))
        assert events[-1].event_kind == "step_failed"
        assert events[-1].phase == "rendering_preview"
        assert events[-1].error_code == "renderer_test_failure"
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_selection_scope_violation_fails_closed_and_preserves_draft(tmp_path: Path) -> None:
    detail_title_id = fixture_id("title-detail")
    summary = "越权修改详情标题"
    proposal = _outcome(
        {
            "contractVersion": 1,
            "kind": "commandProposal",
            "message": "准备修改。",
            "summary": summary,
            "batch": {
                "commandContractVersion": 1,
                "summary": summary,
                "commands": [
                    {
                        "kind": "setNodeProperty",
                        "node": {"kind": "existing", "nodeId": detail_title_id},
                        "update": {"kind": "textContent", "content": "越权标题"},
                    }
                ],
            },
            "affectedEntityIds": [detail_title_id],
        }
    )
    store, _, service, draft_id, thread_id = await _fixture(tmp_path, proposal)
    try:
        draft = await store.load_draft(draft_id)
        assert draft is not None
        queued = await service.send_message(
            thread_id=thread_id,
            client_message_id=fixture_id("ai-scope-message"),
            draft_id=draft_id,
            expected_head_sequence_no=0,
            expected_document_hash=draft.head_document_hash,
            content="改一下当前页",
            selection=PrototypeAiSelectionV1(
                scope="selection",
                page_id=fixture_id("page-list"),
                selected_node_ids=[fixture_id("title-list")],
                flow_id=None,
                viewport="desktop",
            ),
        )
        failed = await service.wait_for_run(queued.id)

        assert failed.status == "failed"
        assert failed.error_code == "scope_violation"
        unchanged = await store.load_draft(draft_id)
        assert unchanged is not None
        assert unchanged.head_sequence_no == 0
    finally:
        await store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scope", "selected_node_ids"),
    [
        pytest.param("page", (), id="page"),
        pytest.param("selection", (fixture_id("table-list"),), id="selected-table"),
    ],
)
async def test_runtime_fixture_field_edit_is_allowed_when_reachable_from_scope(
    tmp_path: Path,
    scope: Literal["page", "selection"],
    selected_node_ids: tuple[str, ...],
) -> None:
    proposal = _runtime_field_outcome()
    runtime = _Runtime(proposal)
    store, _, service, draft_id, thread_id = await _fixture(
        tmp_path,
        proposal,
        runtime=runtime,
        document=_runtime_table_new_document(),
    )
    try:
        draft = await store.load_draft(draft_id)
        assert draft is not None
        queued = await service.send_message(
            thread_id=thread_id,
            client_message_id=fixture_id(f"ai-runtime-{scope}-message"),
            draft_id=draft_id,
            expected_head_sequence_no=0,
            expected_document_hash=draft.head_document_hash,
            content="修改当前表格数据",
            selection=PrototypeAiSelectionV1(
                scope=scope,
                page_id=fixture_id("page-list"),
                selected_node_ids=list(selected_node_ids),
                flow_id=None,
                viewport="desktop",
            ),
        )

        ready = await service.wait_for_run(queued.id)

        assert ready.status == "preview_ready"
        assert len(runtime.requests) == 1
        runtime_context = runtime.requests[0].frozen_context["runtime"]
        assert isinstance(runtime_context, dict)
        bindings = runtime_context["viewBindings"]
        assert isinstance(bindings, list)
        assert len(bindings) == 1
        binding = bindings[0]
        assert isinstance(binding, dict)
        assert binding["nodeId"] == fixture_id("table-list")
        assert binding["schemaId"] == fixture_id("table-schema")
        schemas = runtime_context["entitySchemas"]
        assert isinstance(schemas, list)
        assert len(schemas) == 1
        schema = schemas[0]
        assert isinstance(schema, dict)
        assert schema["id"] == fixture_id("table-schema")
        scenarios = runtime_context["scenarios"]
        assert isinstance(scenarios, list)
        assert len(scenarios) == 1
        scenario = scenarios[0]
        assert isinstance(scenario, dict)
        assert scenario["id"] == fixture_id("scenario-happy-path")
        fixtures = scenario["entityFixtures"]
        assert isinstance(fixtures, list)
        fixture = fixtures[0]
        assert isinstance(fixture, dict)
        entities = fixture["entities"]
        assert isinstance(entities, list)
        entity = entities[0]
        assert isinstance(entity, dict)
        assert entity["id"] == fixture_id("table-entity-open")
    finally:
        await store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scope", "page_id", "selected_node_ids"),
    [
        pytest.param(
            "selection",
            fixture_id("page-list"),
            (fixture_id("title-list"),),
            id="unrelated-selection",
        ),
        pytest.param(
            "page",
            fixture_id("page-detail"),
            (),
            id="unrelated-page",
        ),
    ],
)
async def test_scope_refuses_unrelated_runtime_fixture_field_edits(
    tmp_path: Path,
    scope: Literal["page", "selection"],
    page_id: str,
    selected_node_ids: tuple[str, ...],
) -> None:
    proposal = _runtime_field_outcome()
    store, _, service, draft_id, thread_id = await _fixture(
        tmp_path,
        proposal,
        document=_runtime_table_new_document(),
    )
    try:
        draft = await store.load_draft(draft_id)
        assert draft is not None
        queued = await service.send_message(
            thread_id=thread_id,
            client_message_id=fixture_id(f"ai-runtime-{scope}-scope-message"),
            draft_id=draft_id,
            expected_head_sequence_no=0,
            expected_document_hash=draft.head_document_hash,
            content="修改当前选中的表格数据",
            selection=PrototypeAiSelectionV1(
                scope=scope,
                page_id=page_id,
                selected_node_ids=list(selected_node_ids),
                flow_id=None,
                viewport="desktop",
            ),
        )

        failed = await service.wait_for_run(queued.id)

        assert failed.status == "failed"
        assert failed.error_code == "scope_violation"
        unchanged = await store.load_draft(draft_id)
        assert unchanged is not None
        assert unchanged.head_sequence_no == 0
        assert unchanged.head_document_hash == draft.head_document_hash
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_preview_blocks_another_run_until_rejected(tmp_path: Path) -> None:
    title_id = fixture_id("title-list")
    summary = "调整列表标题"
    proposal = _outcome(
        {
            "contractVersion": 1,
            "kind": "commandProposal",
            "message": "提案已准备。",
            "summary": summary,
            "batch": {
                "commandContractVersion": 1,
                "summary": summary,
                "commands": [
                    {
                        "kind": "setNodeProperty",
                        "node": {"kind": "existing", "nodeId": title_id},
                        "update": {"kind": "textContent", "content": "全部申请"},
                    }
                ],
            },
            "affectedEntityIds": [title_id],
        }
    )
    store, _, service, draft_id, thread_id = await _fixture(tmp_path, proposal)
    try:
        draft = await store.load_draft(draft_id)
        assert draft is not None
        queued = await service.send_message(
            thread_id=thread_id,
            client_message_id=fixture_id("ai-open-proposal"),
            draft_id=draft_id,
            expected_head_sequence_no=0,
            expected_document_hash=draft.head_document_hash,
            content="改标题",
            selection=_page_selection(),
        )
        ready = await service.wait_for_run(queued.id)
        assert ready.status == "preview_ready"

        with pytest.raises(StructuredPrototypeAiServiceError) as conflict:
            await service.send_message(
                thread_id=thread_id,
                client_message_id=fixture_id("ai-second-open-message"),
                draft_id=draft_id,
                expected_head_sequence_no=0,
                expected_document_hash=draft.head_document_hash,
                content="再改一次",
                selection=_page_selection(),
            )
        assert conflict.value.code == "ai_run_conflict"

        rejected = await service.reject(
            run_id=ready.id,
            client_request_id=fixture_id("ai-reject-proposal"),
        )
        assert rejected.status == "rejected"
        async with (
            aiosqlite.connect(tmp_path / "console.db") as conn,
            conn.execute(
                """
                SELECT id
                FROM prototype_operations
                WHERE parent_operation_id = ? AND operation_kind = 'reject_ai_proposal'
                """,
                (ready.operation_id,),
            ) as cursor,
        ):
            reject_row = await cursor.fetchone()
        assert reject_row is not None
        reject_operation = await store.load_operation(str(reject_row[0]))
        assert reject_operation is not None
        assert reject_operation.status == "succeeded"
        assert reject_operation.result_manifest_hash is not None
        reject_events = await store.list_operation_events(reject_operation.id)
        assert [event.event_no for event in reject_events] == [0, 1, 2]
        assert reject_events[-1].status == "succeeded"
        reject_references = await store.list_object_references(
            "project-1", "replay_manifest", reject_operation.id
        )
        assert [reference.content_hash for reference in reject_references] == [
            reject_operation.result_manifest_hash
        ]
        snapshot = await service.get_thread(thread_id)
        proposal_message = next(
            message for message in snapshot.messages if message.role == "assistant"
        )
        assert proposal_message.status == "rejected"
        unchanged = await store.load_draft(draft_id)
        assert unchanged is not None
        assert unchanged.head_sequence_no == 0
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_unexpected_runtime_failure_persists_terminal_evidence(tmp_path: Path) -> None:
    answer = _outcome(
        {
            "contractVersion": 1,
            "kind": "answer",
            "message": "不会返回。",
        }
    )
    store, _, service, draft_id, thread_id = await _fixture(
        tmp_path,
        answer,
        runtime=_UnexpectedRuntime(),
    )
    try:
        draft = await store.load_draft(draft_id)
        assert draft is not None
        queued = await service.send_message(
            thread_id=thread_id,
            client_message_id=fixture_id("ai-unexpected-runtime-message"),
            draft_id=draft_id,
            expected_head_sequence_no=0,
            expected_document_hash=draft.head_document_hash,
            content="解释当前列表",
            selection=_page_selection(),
        )

        failed = await service.wait_for_run(queued.id)

        assert failed.status == "failed"
        assert failed.error_code == "agent_task_failed"
        operation = await store.load_operation(failed.operation_id)
        assert operation is not None
        assert operation.status == "failed"
        events = await store.list_operation_events(operation.id)
        assert events[-1].event_kind == "step_failed"
        assert events[-1].error_code == "agent_task_failed"
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_page_scope_accepts_behavior_rule_add_with_scoped_references(
    tmp_path: Path,
) -> None:
    summary = "新增创建页返回列表规则"
    proposal = _outcome(
        {
            "contractVersion": 1,
            "kind": "commandProposal",
            "message": "已准备业务规则。",
            "summary": summary,
            "batch": {
                "commandContractVersion": 1,
                "summary": summary,
                "commands": [
                    {
                        "kind": "addBehaviorRule",
                        "newRuleKey": "return-to-list",
                        "definition": {
                            "key": "return-to-list",
                            "enabled": True,
                            "trigger": {
                                "kind": "nodeEvent",
                                "nodeId": fixture_id("button-submit"),
                                "event": "click",
                            },
                            "guard": None,
                            "effects": [
                                {
                                    "kind": "navigate",
                                    "targetPageId": fixture_id("page-list"),
                                }
                            ],
                            "guardFalseEffects": [],
                        },
                    }
                ],
            },
            "affectedEntityIds": [
                fixture_id("button-submit"),
                fixture_id("page-list"),
            ],
        }
    )
    runtime = _Runtime(proposal)
    store, _, service, draft_id, thread_id = await _fixture(
        tmp_path,
        proposal,
        runtime=runtime,
    )
    try:
        draft = await store.load_draft(draft_id)
        assert draft is not None
        queued = await service.send_message(
            thread_id=thread_id,
            client_message_id=fixture_id("ai-page-add-rule-message"),
            draft_id=draft_id,
            expected_head_sequence_no=0,
            expected_document_hash=draft.head_document_hash,
            content="给创建页增加返回列表的规则",
            selection=PrototypeAiSelectionV1(
                scope="page",
                page_id=fixture_id("page-create"),
                selected_node_ids=[],
                flow_id=None,
                viewport="desktop",
            ),
        )

        ready = await service.wait_for_run(queued.id)

        assert ready.status == "preview_ready"
        assert len(runtime.requests) == 1
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_flow_scope_freezes_selected_rule_context_and_accepts_replace(
    tmp_path: Path,
) -> None:
    rule_id = fixture_id("ai-flow-rule")
    flow_id = fixture_id("ai-flow-projection")
    summary = "补充提交流程通知"
    proposal = _outcome(
        {
            "contractVersion": 1,
            "kind": "commandProposal",
            "message": "已准备流程规则调整。",
            "summary": summary,
            "batch": {
                "commandContractVersion": 1,
                "summary": summary,
                "commands": [
                    {
                        "kind": "replaceBehaviorRule",
                        "ruleId": rule_id,
                        "definition": {
                            "key": "submit-to-detail",
                            "enabled": True,
                            "trigger": {
                                "kind": "nodeEvent",
                                "nodeId": fixture_id("button-submit"),
                                "event": "click",
                            },
                            "guard": {
                                "kind": "roleIs",
                                "roleId": fixture_id("role-applicant"),
                            },
                            "effects": [
                                {
                                    "kind": "navigate",
                                    "targetPageId": fixture_id("page-detail"),
                                },
                                {
                                    "kind": "notify",
                                    "level": "success",
                                    "message": "已进入详情",
                                },
                            ],
                            "guardFalseEffects": [],
                        },
                    }
                ],
            },
            "affectedEntityIds": [
                rule_id,
                flow_id,
                fixture_id("button-submit"),
                fixture_id("page-detail"),
            ],
        }
    )
    runtime = _Runtime(proposal)
    store, _, service, draft_id, thread_id = await _fixture(
        tmp_path,
        proposal,
        runtime=runtime,
        document=_flow_rule_new_document(),
    )
    try:
        draft = await store.load_draft(draft_id)
        assert draft is not None
        queued = await service.send_message(
            thread_id=thread_id,
            client_message_id=fixture_id("ai-flow-replace-message"),
            draft_id=draft_id,
            expected_head_sequence_no=0,
            expected_document_hash=draft.head_document_hash,
            content="给当前流程增加成功通知",
            selection=PrototypeAiSelectionV1(
                scope="flow",
                page_id=None,
                selected_node_ids=[],
                flow_id=flow_id,
                viewport="desktop",
            ),
        )

        ready = await service.wait_for_run(queued.id)

        assert ready.status == "preview_ready"
        context = runtime.requests[0].frozen_context
        flow = context["flow"]
        assert isinstance(flow, dict)
        assert flow["id"] == flow_id
        rule = context["rule"]
        assert isinstance(rule, dict)
        assert rule["id"] == rule_id
        source_page = context["page"]
        assert isinstance(source_page, dict)
        assert source_page["id"] == fixture_id("page-create")
        target_pages = context["targetPages"]
        assert isinstance(target_pages, list)
        assert [page["id"] for page in target_pages] == [fixture_id("page-detail")]
        assert "navigation" not in context
        runtime_context = context["runtime"]
        assert isinstance(runtime_context, dict)
        assert [role["id"] for role in runtime_context["roles"]] == [fixture_id("role-applicant")]
        assert [item["id"] for item in runtime_context["rules"]] == [rule_id]
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_flow_scope_accepts_remove_of_its_selected_rule(tmp_path: Path) -> None:
    rule_id = fixture_id("ai-flow-rule")
    flow_id = fixture_id("ai-flow-projection")
    summary = "删除当前流程规则"
    proposal = _outcome(
        {
            "contractVersion": 1,
            "kind": "commandProposal",
            "message": "已准备删除当前规则。",
            "summary": summary,
            "batch": {
                "commandContractVersion": 1,
                "summary": summary,
                "commands": [{"kind": "removeBehaviorRule", "ruleId": rule_id}],
            },
            "affectedEntityIds": [
                rule_id,
                flow_id,
                fixture_id("button-submit"),
                fixture_id("page-detail"),
            ],
        }
    )
    store, _, service, draft_id, thread_id = await _fixture(
        tmp_path,
        proposal,
        document=_flow_rule_new_document(),
    )
    try:
        draft = await store.load_draft(draft_id)
        assert draft is not None
        queued = await service.send_message(
            thread_id=thread_id,
            client_message_id=fixture_id("ai-flow-remove-message"),
            draft_id=draft_id,
            expected_head_sequence_no=0,
            expected_document_hash=draft.head_document_hash,
            content="删除当前流程",
            selection=PrototypeAiSelectionV1(
                scope="flow",
                page_id=None,
                selected_node_ids=[],
                flow_id=flow_id,
                viewport="desktop",
            ),
        )

        ready = await service.wait_for_run(queued.id)

        assert ready.status == "preview_ready"
    finally:
        await store.close()


@pytest.mark.parametrize("scope", ["page", "selection"])
@pytest.mark.parametrize("command_kind", ["replace", "remove"])
def test_page_and_selection_scopes_accept_their_related_behavior_rule(
    scope: Literal["page", "selection"],
    command_kind: Literal["replace", "remove"],
) -> None:
    document = _flow_rule_new_document().materialize(fixture_id("ai-scope-document"))
    rule_id = fixture_id("ai-flow-rule")
    if command_kind == "replace":
        command: dict[str, object] = {
            "kind": "replaceBehaviorRule",
            "ruleId": rule_id,
            "definition": {
                "key": "submit-to-detail",
                "enabled": True,
                "trigger": {
                    "kind": "nodeEvent",
                    "nodeId": fixture_id("button-submit"),
                    "event": "click",
                },
                "guard": {
                    "kind": "roleIs",
                    "roleId": fixture_id("role-applicant"),
                },
                "effects": [{"kind": "navigate", "targetPageId": fixture_id("page-detail")}],
                "guardFalseEffects": [],
            },
        }
    else:
        command = {"kind": "removeBehaviorRule", "ruleId": rule_id}
    batch = DomainCommandBatchV1.model_validate(
        {
            "commandContractVersion": 1,
            "summary": "修改直接相关规则",
            "commands": [command],
        },
        strict=True,
        by_alias=True,
        by_name=False,
    )
    selection = PrototypeAiSelectionV1(
        scope=scope,
        page_id=fixture_id("page-create"),
        selected_node_ids=[fixture_id("button-submit")] if scope == "selection" else [],
        flow_id=None,
        viewport="desktop",
    )

    StructuredPrototypeAiService._validate_command_scope(document, batch, selection)


@pytest.mark.parametrize(
    "command",
    [
        {
            "kind": "addPage",
            "afterPageId": fixture_id("page-list"),
            "newPageKey": "ai-add-page",
            "title": "AI page",
            "includeInNavigation": False,
        },
        {
            "kind": "duplicatePage",
            "pageId": fixture_id("page-list"),
            "newPageKey": "ai-duplicate-page",
            "title": "AI page copy",
        },
        {"kind": "renamePage", "pageId": fixture_id("page-list"), "title": "AI title"},
        {"kind": "deletePage", "pageId": fixture_id("page-list")},
    ],
)
def test_page_scope_accepts_its_page_commands_and_selection_scope_refuses_them(
    command: dict[str, object],
) -> None:
    document = _new_document().materialize(fixture_id("ai-page-command-document"))
    batch = DomainCommandBatchV1.model_validate(
        {
            "commandContractVersion": 1,
            "summary": "Edit selected page",
            "commands": [command],
        },
        strict=True,
        by_alias=True,
        by_name=False,
    )
    page_selection = PrototypeAiSelectionV1(
        scope="page",
        page_id=fixture_id("page-list"),
        selected_node_ids=[],
        flow_id=None,
        viewport="desktop",
    )
    StructuredPrototypeAiService._validate_command_scope(document, batch, page_selection)
    node_selection = page_selection.model_copy(
        update={
            "scope": "selection",
            "selected_node_ids": [fixture_id("title-list")],
        }
    )
    with pytest.raises(StructuredPrototypeAiServiceError) as error:
        StructuredPrototypeAiService._validate_command_scope(document, batch, node_selection)
    assert error.value.code == "scope_violation"


@pytest.mark.parametrize(
    "command",
    [
        {
            "kind": "defineComponent",
            "key": "ai-summary-card",
            "sourceNode": {
                "kind": "existing",
                "nodeId": fixture_id("title-list"),
            },
        },
        {
            "kind": "removeComponentDefinition",
            "componentId": fixture_id("ai-component-definition"),
        },
    ],
)
def test_component_definition_commands_require_document_scope(
    command: dict[str, object],
) -> None:
    document = _new_document().materialize(fixture_id("ai-component-scope-document"))
    batch = DomainCommandBatchV1.model_validate(
        {
            "commandContractVersion": 1,
            "summary": "Edit component definition",
            "commands": [command],
        },
        strict=True,
        by_alias=True,
        by_name=False,
    )
    document_selection = PrototypeAiSelectionV1(
        scope="document",
        page_id=None,
        selected_node_ids=[],
        flow_id=None,
        viewport="desktop",
    )
    StructuredPrototypeAiService._validate_command_scope(
        document,
        batch,
        document_selection,
    )
    for selection in (
        _page_selection(),
        PrototypeAiSelectionV1(
            scope="selection",
            page_id=fixture_id("page-list"),
            selected_node_ids=[fixture_id("title-list")],
            flow_id=None,
            viewport="desktop",
        ),
    ):
        with pytest.raises(StructuredPrototypeAiServiceError) as error:
            StructuredPrototypeAiService._validate_command_scope(document, batch, selection)
        assert error.value.code == "scope_violation"


def test_component_instantiation_scope_validates_only_the_target_parent() -> None:
    document = _new_document().materialize(fixture_id("ai-component-instance-document"))

    def batch_for(parent_id: str) -> DomainCommandBatchV1:
        return DomainCommandBatchV1.model_validate(
            {
                "commandContractVersion": 1,
                "summary": "Insert reusable component",
                "commands": [
                    {
                        "kind": "instantiateComponent",
                        "componentId": fixture_id("ai-component-definition"),
                        "parent": {"kind": "existing", "nodeId": parent_id},
                        "index": 0,
                    }
                ],
            },
            strict=True,
            by_alias=True,
            by_name=False,
        )

    page_selection = _page_selection()
    StructuredPrototypeAiService._validate_command_scope(
        document,
        batch_for(fixture_id("root-list")),
        page_selection,
    )
    selection = PrototypeAiSelectionV1(
        scope="selection",
        page_id=fixture_id("page-list"),
        selected_node_ids=[fixture_id("root-list")],
        flow_id=None,
        viewport="desktop",
    )
    StructuredPrototypeAiService._validate_command_scope(
        document,
        batch_for(fixture_id("root-list")),
        selection,
    )
    with pytest.raises(StructuredPrototypeAiServiceError) as error:
        StructuredPrototypeAiService._validate_command_scope(
            document,
            batch_for(fixture_id("root-detail")),
            page_selection,
        )
    assert error.value.code == "scope_violation"


def test_ai_node_name_scope_accepts_only_nodes_inside_the_selection() -> None:
    document = _new_document().materialize(fixture_id("ai-node-name-document"))
    selection = PrototypeAiSelectionV1(
        scope="selection",
        page_id=fixture_id("page-list"),
        selected_node_ids=[fixture_id("title-list")],
        flow_id=None,
        viewport="desktop",
    )
    accepted = DomainCommandBatchV1.model_validate(
        {
            "commandContractVersion": 1,
            "summary": "Rename selected node",
            "commands": [
                {
                    "kind": "updateNodeName",
                    "nodeId": fixture_id("title-list"),
                    "name": "AI title layer",
                }
            ],
        },
        strict=True,
        by_alias=True,
        by_name=False,
    )
    StructuredPrototypeAiService._validate_command_scope(document, accepted, selection)
    outside = DomainCommandBatchV1.model_validate(
        {
            "commandContractVersion": 1,
            "summary": "Rename another page node",
            "commands": [
                {
                    "kind": "updateNodeName",
                    "nodeId": fixture_id("title-detail"),
                    "name": "Outside layer",
                }
            ],
        },
        strict=True,
        by_alias=True,
        by_name=False,
    )
    with pytest.raises(StructuredPrototypeAiServiceError) as error:
        StructuredPrototypeAiService._validate_command_scope(document, outside, selection)
    assert error.value.code == "scope_violation"


@pytest.mark.parametrize("violation", ["add", "other-rule", "outside-target"])
@pytest.mark.asyncio
async def test_flow_scope_refuses_unrelated_behavior_rule_edits(
    tmp_path: Path,
    violation: str,
) -> None:
    rule_id = fixture_id("ai-flow-rule")
    flow_id = fixture_id("ai-flow-projection")
    if violation == "add":
        command: dict[str, object] = {
            "kind": "addBehaviorRule",
            "newRuleKey": "unrelated-rule",
            "definition": {
                "key": "unrelated-rule",
                "enabled": False,
                "trigger": {
                    "kind": "nodeEvent",
                    "nodeId": fixture_id("button-submit"),
                    "event": "click",
                },
                "guard": None,
                "effects": [{"kind": "notify", "level": "info", "message": "无关"}],
                "guardFalseEffects": [],
            },
        }
    elif violation == "other-rule":
        command = {
            "kind": "removeBehaviorRule",
            "ruleId": fixture_id("another-flow-rule"),
        }
    else:
        command = {
            "kind": "replaceBehaviorRule",
            "ruleId": rule_id,
            "definition": {
                "key": "submit-to-detail",
                "enabled": True,
                "trigger": {
                    "kind": "nodeEvent",
                    "nodeId": fixture_id("button-submit"),
                    "event": "click",
                },
                "guard": {
                    "kind": "roleIs",
                    "roleId": fixture_id("role-applicant"),
                },
                "effects": [{"kind": "navigate", "targetPageId": fixture_id("page-list")}],
                "guardFalseEffects": [],
            },
        }
    summary = "越权修改流程规则"
    proposal = _outcome(
        {
            "contractVersion": 1,
            "kind": "commandProposal",
            "message": "准备修改。",
            "summary": summary,
            "batch": {
                "commandContractVersion": 1,
                "summary": summary,
                "commands": [command],
            },
            "affectedEntityIds": [rule_id],
        }
    )
    store, _, service, draft_id, thread_id = await _fixture(
        tmp_path,
        proposal,
        document=_flow_rule_new_document(),
    )
    try:
        draft = await store.load_draft(draft_id)
        assert draft is not None
        queued = await service.send_message(
            thread_id=thread_id,
            client_message_id=fixture_id(f"ai-flow-scope-{violation}-message"),
            draft_id=draft_id,
            expected_head_sequence_no=0,
            expected_document_hash=draft.head_document_hash,
            content="修改当前流程",
            selection=PrototypeAiSelectionV1(
                scope="flow",
                page_id=None,
                selected_node_ids=[],
                flow_id=flow_id,
                viewport="desktop",
            ),
        )

        failed = await service.wait_for_run(queued.id)

        assert failed.status == "failed"
        assert failed.error_code == "scope_violation"
        unchanged = await store.load_draft(draft_id)
        assert unchanged is not None
        assert unchanged.head_sequence_no == 0
    finally:
        await store.close()


async def _freeform_apply_fixture(
    tmp_path: Path,
    outcome: PrototypeAssistantOutcomeV1,
) -> tuple[
    AsyncStructuredPrototypeStore,
    StructuredPrototypeService,
    StructuredPrototypeAiService,
    str,
    str,
]:
    """Build services over a freeform document and wire the runtime to ``outcome``.

    Kept for the no-evidence regression test where the outcome batch is static.
    """
    store = AsyncStructuredPrototypeStore(tmp_path / "console.db")
    object_store = PrototypeObjectStore(tmp_path / "managed")
    renderer = PrototypeRendererWorker()
    artifact_store = PrototypeRenderArtifactStore(tmp_path / "managed")
    structured = StructuredPrototypeService(
        store=store,
        object_store=object_store,
        renderer_worker=renderer,
        artifact_store=artifact_store,
        clock=lambda: FIXED_NOW,
    )
    created = await structured.create_document(
        project_id="project-1",
        client_request_id=fixture_id("ai-freeform-apply-create"),
        document=_new_freeform_document(),
    )
    project = Project(
        id="project-1",
        name="Procurement",
        repo_path=str(tmp_path),
        default_branch="main",
    )
    ai_service = StructuredPrototypeAiService(
        store=store,
        project_store=_ProjectStore(project),
        object_store=object_store,
        structured_service=structured,
        runtime=_Runtime(outcome),
        renderer_worker=renderer,
        artifact_store=artifact_store,
        clock=lambda: FIXED_NOW,
    )
    thread = await ai_service.create_thread(
        document_id=created.state.document_record.id,
        client_request_id=fixture_id("ai-freeform-apply-thread"),
        title="采购原型自由布局调整",
    )
    return store, structured, ai_service, created.state.draft.id, thread.id


async def _freeform_apply_fixture_with_outcome_builder(
    tmp_path: Path,
    outcome_builder: OutcomeBuilder,
) -> tuple[
    AsyncStructuredPrototypeStore,
    StructuredPrototypeService,
    StructuredPrototypeAiService,
    str,
    str,
]:
    """Build services over a freeform document, then build the outcome from it.

    The outcome builder receives the materialized document, draft id and base
    document hash so the proposed command batch's evidence can reference the real
    base document (used by the evidence-mismatch test).
    """
    store = AsyncStructuredPrototypeStore(tmp_path / "console.db")
    object_store = PrototypeObjectStore(tmp_path / "managed")
    renderer = PrototypeRendererWorker()
    artifact_store = PrototypeRenderArtifactStore(tmp_path / "managed")
    structured = StructuredPrototypeService(
        store=store,
        object_store=object_store,
        renderer_worker=renderer,
        artifact_store=artifact_store,
        clock=lambda: FIXED_NOW,
    )
    created = await structured.create_document(
        project_id="project-1",
        client_request_id=fixture_id("ai-freeform-apply-create"),
        document=_new_freeform_document(),
    )
    outcome = outcome_builder(
        created.state.document,
        created.state.draft.id,
        created.state.draft.head_document_hash,
    )
    project = Project(
        id="project-1",
        name="Procurement",
        repo_path=str(tmp_path),
        default_branch="main",
    )
    ai_service = StructuredPrototypeAiService(
        store=store,
        project_store=_ProjectStore(project),
        object_store=object_store,
        structured_service=structured,
        runtime=_Runtime(outcome),
        renderer_worker=renderer,
        artifact_store=artifact_store,
        clock=lambda: FIXED_NOW,
    )
    thread = await ai_service.create_thread(
        document_id=created.state.document_record.id,
        client_request_id=fixture_id("ai-freeform-apply-thread"),
        title="采购原型自由布局调整",
    )
    return store, structured, ai_service, created.state.draft.id, thread.id


@pytest.mark.asyncio
async def test_ai_apply_rejects_freeform_move_evidence_that_conflicts_with_base_document(
    tmp_path: Path,
) -> None:
    def build_outcome(
        document: PrototypeDocumentV1,
        draft_id: str,
        base_document_hash: str,
    ) -> PrototypeAssistantOutcomeV1:
        root = document.pages[0].root
        assert isinstance(root, FreeformNodeV1)
        moved_node_ids = [child.id for child in root.children[:2]]
        # moveNode affects the moved node, its source parent and its target parent
        # (all the same freeform root here), so the declared affected entity ids must
        # include the container as well or the preview scope check rejects the batch.
        affected_entity_ids = [*moved_node_ids, root.id]
        # Evidence declares base_head_sequence_no=1 while the real head is 0, so the
        # shared evidence-context gate must reject the batch before any persistence.
        batch = _freeform_move_evidence_batch(
            document,
            draft_id=draft_id,
            base_head_sequence_no=1,
            base_document_hash=base_document_hash,
        )
        assert batch.evidence is not None
        return _outcome(
            {
                "contractVersion": 1,
                "kind": "commandProposal",
                "message": "已准备自由布局移动, 可先查看预览。",
                "summary": "移动自由布局组件组",
                "batch": batch.model_dump(mode="json", by_alias=True),
                "affectedEntityIds": affected_entity_ids,
            }
        )

    store, _structured, service, draft_id, thread_id = (
        await _freeform_apply_fixture_with_outcome_builder(tmp_path, build_outcome)
    )
    apply_request_id = fixture_id("ai-freeform-mismatch-apply")
    try:
        draft = await store.load_draft(draft_id)
        assert draft is not None
        queued = await service.send_message(
            thread_id=thread_id,
            client_message_id=fixture_id("ai-freeform-mismatch-message"),
            draft_id=draft_id,
            expected_head_sequence_no=0,
            expected_document_hash=draft.head_document_hash,
            content="把自由布局里的前两个组件往右下移动一点",
            selection=_document_selection(),
        )
        ready = await service.wait_for_run(queued.id)
        assert ready.status == "preview_ready"
        assert ready.proposed_command_batch_json is not None

        with pytest.raises(StructuredPrototypeAiServiceError) as error:
            await service.apply(
                run_id=ready.id,
                client_request_id=apply_request_id,
                expected_head_sequence_no=0,
                expected_document_hash=draft.head_document_hash,
            )

        assert error.value.code == "command_evidence_mismatch"
        assert error.value.run_id == ready.id
        # The run stays preview_ready so the user can reject or retry; no command
        # batch is persisted and the draft head is unchanged.
        unchanged_run = await store.load_ai_edit_run(ready.id)
        assert unchanged_run is not None
        assert unchanged_run.status == "preview_ready"
        unchanged_draft = await store.load_draft(draft_id)
        assert unchanged_draft is not None
        assert unchanged_draft.head_sequence_no == 0
        assert unchanged_draft.head_document_hash == draft.head_document_hash
        assert (
            await store.load_command_batch_by_request(draft_id, apply_request_id)
            is None
        )
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_ai_apply_still_succeeds_for_a_batch_without_evidence(
    tmp_path: Path,
) -> None:
    title_id = fixture_id("title-list")
    summary = "将列表标题改为全部采购申请"
    proposal = _outcome(
        {
            "contractVersion": 1,
            "kind": "commandProposal",
            "message": "已准备标题调整, 可先查看预览。",
            "summary": summary,
            "batch": {
                "commandContractVersion": 1,
                "summary": summary,
                "commands": [
                    {
                        "kind": "setNodeProperty",
                        "node": {"kind": "existing", "nodeId": title_id},
                        "update": {"kind": "textContent", "content": "全部采购申请"},
                    }
                ],
            },
            "affectedEntityIds": [title_id],
        }
    )
    store, _structured, service, draft_id, thread_id = await _freeform_apply_fixture(
        tmp_path, proposal
    )
    apply_request_id = fixture_id("ai-freeform-no-evidence-apply")
    try:
        draft = await store.load_draft(draft_id)
        assert draft is not None
        queued = await service.send_message(
            thread_id=thread_id,
            client_message_id=fixture_id("ai-freeform-no-evidence-message"),
            draft_id=draft_id,
            expected_head_sequence_no=0,
            expected_document_hash=draft.head_document_hash,
            content="把列表标题改成全部采购申请",
            selection=_document_selection(),
        )
        ready = await service.wait_for_run(queued.id)
        assert ready.status == "preview_ready"

        applied = await service.apply(
            run_id=ready.id,
            client_request_id=apply_request_id,
            expected_head_sequence_no=0,
            expected_document_hash=draft.head_document_hash,
        )

        assert applied.run.status == "applied"
        assert applied.draft_result.state.draft.head_sequence_no == 1
    finally:
        await store.close()
