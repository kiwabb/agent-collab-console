from __future__ import annotations

import asyncio
import hashlib
import json
import threading
import warnings
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

import aiosqlite
import pytest
from structured_prototype_fixtures import (
    fixture_id,
    procurement_document_payload,
    text_insert_batch_payload,
)

from app.adapters.prototype_object_store import PrototypeObjectStore, PrototypeObjectStoreError
from app.adapters.prototype_render_artifact_store import PrototypeRenderArtifactStore
from app.adapters.prototype_renderer_worker import (
    PrototypeRendererWorker,
    PrototypeRendererWorkerError,
)
from app.adapters.prototype_runtime_worker import PrototypeRuntimeWorker
from app.adapters.prototype_snap_worker import PrototypeSnapWorkerError
from app.adapters.structured_prototype_store import AsyncStructuredPrototypeStore
from app.application import structured_prototype_service as prototype_service_module
from app.application.structured_prototype_contracts import (
    CommandExecutionResultV1,
    DomainCommandBatchV1,
    FreeformGridsUpdateV1,
    FreeformNodeV1,
    InverseCommandBatchV1,
    LayoutItemV1,
    LengthV1,
    NewPrototypeDocumentV1,
    PrototypeDocumentV1,
    SetNodeLayoutCommandV1,
    SetNodePropertyCommandV1,
    StackNodeV1,
    TextNodeV1,
    canonical_model_json,
    command_batch_envelope_hash,
    document_hash,
    freeform_grid_list_hash,
    parse_command_batch_json,
    parse_inverse_command_batch_json,
)
from app.application.structured_prototype_service import (
    SNAP_WORKER_INFRASTRUCTURE_ERROR_CODES,
    ApplyStructuredPrototypeCommandsResult,
    StructuredPrototypeService,
    StructuredPrototypeServiceError,
)
from app.domain.structured_prototype import (
    PrototypeCommandBatchRecord,
    PrototypeDraftRecord,
    PrototypeObjectDescriptor,
    PrototypeObjectReference,
    PrototypeOperation,
    PrototypeOperationEvent,
    PrototypeOperationKind,
    PrototypeOperationStep,
    PrototypeRendererWorkerIdentity,
    PrototypeRendererWorkerResult,
    PrototypeRuntimeWorkerReplayResult,
    PrototypeRuntimeWorkerStateResult,
    PrototypeSnapWorkerAttestationResult,
    PrototypeSnapWorkerIdentity,
)

FIXED_NOW = datetime(2026, 7, 13, 8, 0, tzinfo=UTC)


class _SnapAttesterSpy:
    identity = PrototypeSnapWorkerIdentity(
        protocol_version="prototype-snap-worker/v1",
        snap_solver_version="structured-prototype-freeform-snap/v1",
        snap_solver_source_hash="sha256:" + "f" * 64,
        snap_solver_bundle_hash="sha256:" + "e" * 64,
        snap_solver_bundle_byte_size=1,
        build_tool="test",
        target="node20",
    )

    def __init__(self) -> None:
        self.attest_calls: list[str] = []
        self.attest_many_calls: list[list[str]] = []
        self.failure_code: str | None = None

    @staticmethod
    def _result(evidence_json: str) -> PrototypeSnapWorkerAttestationResult:
        return PrototypeSnapWorkerAttestationResult(
            evidence_hash="sha256:" + hashlib.sha256(evidence_json.encode("utf-8")).hexdigest()
        )

    async def attest(
        self,
        *,
        request_id: str,
        evidence_json: str,
    ) -> PrototypeSnapWorkerAttestationResult:
        assert request_id
        self.attest_calls.append(evidence_json)
        if self.failure_code is not None:
            raise PrototypeSnapWorkerError(self.failure_code, "snap attestation failed")
        return self._result(evidence_json)

    async def attest_many(
        self,
        *,
        request_id: str,
        evidence_jsons: list[str],
    ) -> tuple[PrototypeSnapWorkerAttestationResult, ...]:
        assert request_id
        self.attest_many_calls.append(list(evidence_jsons))
        if self.failure_code is not None:
            raise PrototypeSnapWorkerError(self.failure_code, "snap attestation failed")
        return tuple(self._result(evidence_json) for evidence_json in evidence_jsons)


class _FailOncePurgeObjectStore(PrototypeObjectStore):
    def __init__(self, data_root: Path) -> None:
        super().__init__(data_root)
        self.purge_attempts = 0

    def purge_project_store(self, project_id: str, deletion_operation_id: str) -> None:
        self.purge_attempts += 1
        if self.purge_attempts == 1:
            raise PrototypeObjectStoreError(
                "object_purge_failed",
                "intentional project store purge failure",
            )
        super().purge_project_store(project_id, deletion_operation_id)


class _BlockingPurgeObjectStore(PrototypeObjectStore):
    def __init__(self, data_root: Path) -> None:
        super().__init__(data_root)
        self.purge_started = threading.Event()
        self.release_purge = threading.Event()

    def purge_project_store(self, project_id: str, deletion_operation_id: str) -> None:
        self.purge_started.set()
        if not self.release_purge.wait(timeout=2):
            raise PrototypeObjectStoreError(
                "object_purge_failed",
                "timed out waiting to finish project store purge",
            )
        super().purge_project_store(project_id, deletion_operation_id)


@pytest.mark.parametrize("code", sorted(SNAP_WORKER_INFRASTRUCTURE_ERROR_CODES))
def test_snap_worker_infrastructure_errors_are_retryable(code: str) -> None:
    assert StructuredPrototypeServiceError(code, "snap worker unavailable").retryable is True


@pytest.mark.parametrize(
    "code",
    ["snap_attestation_mismatch", "snap_evidence_invalid", "command_evidence_mismatch"],
)
def test_snap_worker_deterministic_mismatches_are_not_retryable(code: str) -> None:
    assert StructuredPrototypeServiceError(code, "snap evidence mismatch").retryable is False


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


def _new_document_with_constrained_title_layout() -> NewPrototypeDocumentV1:
    payload = procurement_document_payload()
    payload.pop("id")
    pages = payload["pages"]
    assert isinstance(pages, list)
    list_page = pages[0]
    assert isinstance(list_page, dict)
    root = list_page["root"]
    assert isinstance(root, dict)
    children = root["children"]
    assert isinstance(children, list)
    title = children[0]
    assert isinstance(title, dict)
    layout = title["layoutItem"]
    assert isinstance(layout, dict)
    layout.update(
        {
            "minWidth": {"unit": "px", "value": "240"},
            "maxWidth": {"unit": "px", "value": "720"},
            "minHeight": {"unit": "px", "value": "40"},
            "maxHeight": {"unit": "px", "value": "160"},
            "grow": 2,
            "shrink": 3,
            "alignSelf": "center",
        }
    )
    return NewPrototypeDocumentV1.model_validate(
        payload,
        strict=True,
        by_alias=True,
        by_name=False,
    )


def _text_insert_batch() -> DomainCommandBatchV1:
    return DomainCommandBatchV1.model_validate(
        text_insert_batch_payload(),
        strict=True,
        by_alias=True,
        by_name=False,
    )


def _text_update_batch(content: str) -> DomainCommandBatchV1:
    return DomainCommandBatchV1.model_validate(
        {
            "commandContractVersion": 1,
            "summary": "更新详情标题",
            "commands": [
                {
                    "kind": "setNodeProperty",
                    "node": {
                        "kind": "existing",
                        "nodeId": fixture_id("title-detail"),
                    },
                    "update": {"kind": "textContent", "content": content},
                }
            ],
        },
        strict=True,
        by_alias=True,
        by_name=False,
    )


def _static_table_update_batch() -> DomainCommandBatchV1:
    return DomainCommandBatchV1.model_validate(
        {
            "commandContractVersion": 1,
            "summary": "新增静态表格行",
            "commands": [
                {
                    "kind": "setNodeProperty",
                    "node": {
                        "kind": "existing",
                        "nodeId": fixture_id("table-list"),
                    },
                    "update": {
                        "kind": "tableData",
                        "columns": [
                            {
                                "key": "title",
                                "label": "申请事项",
                                "fieldId": None,
                            },
                            {"key": "status", "label": "状态", "fieldId": None},
                        ],
                        "rows": [
                            {
                                "id": fixture_id("static-table-row"),
                                "cells": [
                                    {"columnKey": "title", "value": "新增电脑"},
                                    {"columnKey": "status", "value": "草稿"},
                                ],
                            }
                        ],
                    },
                }
            ],
        },
        strict=True,
        by_alias=True,
        by_name=False,
    )


def _layout_update_batch() -> DomainCommandBatchV1:
    return DomainCommandBatchV1.model_validate(
        {
            "commandContractVersion": 1,
            "summary": "调整标题尺寸",
            "commands": [
                {
                    "kind": "setNodeLayout",
                    "node": {
                        "kind": "existing",
                        "nodeId": fixture_id("title-list"),
                    },
                    "update": {
                        "width": {"unit": "px", "value": "360"},
                        "height": {"unit": "px", "value": "72"},
                    },
                }
            ],
        },
        strict=True,
        by_alias=True,
        by_name=False,
    )


def _runtime_flow_position_batch(
    flow_node_id: str,
    *,
    x: int,
    y: int,
) -> DomainCommandBatchV1:
    return DomainCommandBatchV1.model_validate(
        {
            "commandContractVersion": 1,
            "summary": "调整业务流程节点位置",
            "commands": [
                {
                    "kind": "setRuntimeFlowNodePosition",
                    "flowNodeId": flow_node_id,
                    "x": x,
                    "y": y,
                }
            ],
        },
        strict=True,
        by_alias=True,
        by_name=False,
    )


def _list_title_layout(document: PrototypeDocumentV1) -> LayoutItemV1:
    root = document.pages[0].root
    assert isinstance(root, StackNodeV1)
    title = root.children[0]
    assert isinstance(title, TextNodeV1)
    return title.layout_item


def _assert_title_layout_constraints(layout: LayoutItemV1) -> None:
    assert layout.min_width == LengthV1(unit="px", value="240")
    assert layout.max_width == LengthV1(unit="px", value="720")
    assert layout.min_height == LengthV1(unit="px", value="40")
    assert layout.max_height == LengthV1(unit="px", value="160")
    assert (layout.grow, layout.shrink, layout.align_self) == (2, 3, "center")


def _service(
    db_path: Path,
    object_root: Path,
    *,
    snap_attester: _SnapAttesterSpy | None = None,
    object_store: PrototypeObjectStore | None = None,
) -> tuple[AsyncStructuredPrototypeStore, StructuredPrototypeService]:
    store = AsyncStructuredPrototypeStore(db_path)
    service = StructuredPrototypeService(
        store=store,
        object_store=object_store or PrototypeObjectStore(object_root),
        snap_attester=snap_attester or _SnapAttesterSpy(),
        clock=lambda: FIXED_NOW,
    )
    return store, service


def _runtime_service(
    db_path: Path,
    object_root: Path,
) -> tuple[AsyncStructuredPrototypeStore, StructuredPrototypeService]:
    store = AsyncStructuredPrototypeStore(db_path)
    service = StructuredPrototypeService(
        store=store,
        object_store=PrototypeObjectStore(object_root),
        runtime_worker=PrototypeRuntimeWorker(),
        clock=lambda: FIXED_NOW,
    )
    return store, service


def _queued_operation(
    label: str,
    *,
    operation_kind: PrototypeOperationKind,
    resource_kind: str,
    parent_operation_id: str | None = None,
    operation_id: str | None = None,
) -> PrototypeOperation:
    return PrototypeOperation(
        id=operation_id or fixture_id(f"{label}-operation"),
        operation_kind=operation_kind,
        project_id="project-1",
        resource_kind=resource_kind,
        resource_id=fixture_id(f"{label}-resource"),
        client_request_id=fixture_id(f"{label}-request"),
        correlation_id=fixture_id(f"{label}-correlation"),
        parent_operation_id=parent_operation_id,
        status="queued",
        phase="queued",
        attempt=1,
        request_manifest_hash="sha256:" + "a" * 64,
        config_manifest_hash="sha256:" + "b" * 64,
        result_manifest_hash=None,
        failure_evidence_hash=None,
        error_code=None,
        created_at=FIXED_NOW,
        started_at=None,
        completed_at=None,
    )


async def _persist_queued_operation(
    store: AsyncStructuredPrototypeStore,
    operation: PrototypeOperation,
) -> None:
    created = await store.create_operation(
        operation,
        PrototypeOperationEvent(
            operation_id=operation.id,
            event_no=0,
            step_id=None,
            event_kind="operation_queued",
            status="queued",
            phase="queued",
            input_hash=operation.request_manifest_hash,
            output_hash=None,
            evidence_hash=None,
            error_code=None,
            occurred_at=FIXED_NOW,
        ),
    )
    assert created.created


async def _persist_runtime_replay_cause(
    store: AsyncStructuredPrototypeStore,
    *,
    label: str,
    project_id: str,
    session_id: str,
    status: Literal["running", "succeeded", "failed"],
) -> PrototypeOperation:
    operation = PrototypeOperation(
        id=fixture_id(f"{label}-operation"),
        operation_kind="replay_runtime_session",
        project_id=project_id,
        resource_kind="runtime_session",
        resource_id=session_id,
        client_request_id=fixture_id(f"{label}-request"),
        correlation_id=fixture_id(f"{label}-correlation"),
        parent_operation_id=None,
        status="queued",
        phase="queued",
        attempt=1,
        request_manifest_hash="sha256:" + "a" * 64,
        config_manifest_hash="sha256:" + "b" * 64,
        result_manifest_hash=None,
        failure_evidence_hash=None,
        error_code=None,
        created_at=FIXED_NOW,
        started_at=None,
        completed_at=None,
    )
    created = await store.create_operation(
        operation,
        PrototypeOperationEvent(
            operation_id=operation.id,
            event_no=0,
            step_id=None,
            event_kind="operation_queued",
            status="queued",
            phase="queued",
            input_hash=operation.request_manifest_hash,
            output_hash=None,
            evidence_hash=None,
            error_code=None,
            occurred_at=FIXED_NOW,
        ),
    )
    assert created.created
    phase = "replay_runtime_event_tail"
    running = replace(
        operation,
        status="running",
        phase=phase,
        started_at=FIXED_NOW,
    )
    step = PrototypeOperationStep(
        id=fixture_id(f"{label}-step"),
        operation_id=operation.id,
        parent_step_id=None,
        step_kind=phase,
        step_ordinal=0,
        attempt=1,
        status="running",
        phase=phase,
        input_manifest_hash=operation.request_manifest_hash,
        config_manifest_hash=operation.config_manifest_hash,
        output_manifest_hash=None,
        completion_evidence_kind=None,
        completion_evidence_ref=None,
        error_code=None,
        started_at=FIXED_NOW,
        completed_at=None,
    )
    await store.record_operation_transition(
        running,
        step,
        PrototypeOperationEvent(
            operation_id=operation.id,
            event_no=1,
            step_id=step.id,
            event_kind="step_started",
            status="running",
            phase=phase,
            input_hash=operation.request_manifest_hash,
            output_hash=None,
            evidence_hash=None,
            error_code=None,
            occurred_at=FIXED_NOW,
        ),
    )
    if status == "running":
        return running

    evidence_hash = "sha256:" + ("c" if status == "succeeded" else "f") * 64
    terminal_operation = replace(
        running,
        status=status,
        result_manifest_hash=evidence_hash if status == "succeeded" else None,
        failure_evidence_hash=evidence_hash if status == "failed" else None,
        error_code="runtime_replay_failed" if status == "failed" else None,
        completed_at=FIXED_NOW,
    )
    terminal_step = replace(
        step,
        status=status,
        output_manifest_hash=evidence_hash,
        completion_evidence_kind=(
            "runtime_replay_manifest" if status == "succeeded" else "failure_manifest_hash"
        ),
        completion_evidence_ref=evidence_hash,
        error_code="runtime_replay_failed" if status == "failed" else None,
        completed_at=FIXED_NOW,
    )
    terminal_event = PrototypeOperationEvent(
        operation_id=operation.id,
        event_no=2,
        step_id=step.id,
        event_kind="step_succeeded" if status == "succeeded" else "step_failed",
        status=status,
        phase=phase,
        input_hash=operation.request_manifest_hash,
        output_hash=evidence_hash if status == "succeeded" else None,
        evidence_hash=evidence_hash,
        error_code="runtime_replay_failed" if status == "failed" else None,
        occurred_at=FIXED_NOW,
    )
    if status == "succeeded":
        await store.register_replay_manifest_and_transition(
            replay_descriptor=PrototypeObjectDescriptor(
                project_id=project_id,
                content_hash=evidence_hash,
                media_type="application/json",
                storage_codec="zstd",
                storage_codec_version="test",
                canonical_byte_size=1,
                stored_byte_size=1,
                storage_hash="sha256:" + "d" * 64,
                storage_key=f"test/replay-manifests/{operation.id}.json.zst",
                created_at=FIXED_NOW,
            ),
            replay_reference=PrototypeObjectReference(
                project_id=project_id,
                owner_kind="replay_manifest",
                owner_id=operation.id,
                role="operation-replay-manifest",
                content_hash=evidence_hash,
                payload_type="replay_manifest",
                schema_version=1,
                created_at=FIXED_NOW,
            ),
            completed_operation=terminal_operation,
            completion_step=terminal_step,
            completion_event=terminal_event,
        )
    else:
        await store.record_operation_transition(
            terminal_operation,
            terminal_step,
            terminal_event,
        )
    return terminal_operation


class _FailingRenderer:
    def __init__(self, identity: PrototypeRendererWorkerIdentity) -> None:
        self.identity = identity

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
            "renderer_intentional_failure",
            "intentional renderer failure",
        )


class _RuntimeWorkerSpy(PrototypeRuntimeWorker):
    def __init__(self) -> None:
        super().__init__()
        self.initialized_session_ids: list[str] = []
        self.replayed_session_ids: list[str] = []

    async def initialize_state(
        self,
        *,
        request_id: str,
        definition: dict[str, object],
        scenario_id: str,
        session_id: str,
    ) -> PrototypeRuntimeWorkerStateResult:
        self.initialized_session_ids.append(session_id)
        return await super().initialize_state(
            request_id=request_id,
            definition=definition,
            scenario_id=scenario_id,
            session_id=session_id,
        )

    async def replay_event_batches(
        self,
        *,
        request_id: str,
        definition: dict[str, object],
        state_json: str,
        batches: list[dict[str, object]],
    ) -> PrototypeRuntimeWorkerReplayResult:
        state = json.loads(state_json)
        assert isinstance(state, dict)
        session_id = state.get("sessionId")
        assert isinstance(session_id, str)
        self.replayed_session_ids.append(session_id)
        return await super().replay_event_batches(
            request_id=request_id,
            definition=definition,
            state_json=state_json,
            batches=batches,
        )


class _RuntimeWorkerStatusDrift(PrototypeRuntimeWorker):
    def __init__(self, store: AsyncStructuredPrototypeStore) -> None:
        super().__init__()
        self._store = store
        self._initialize_count = 0

    async def initialize_state(
        self,
        *,
        request_id: str,
        definition: dict[str, object],
        scenario_id: str,
        session_id: str,
    ) -> PrototypeRuntimeWorkerStateResult:
        self._initialize_count += 1
        if self._initialize_count == 2:
            conn = await self._store._get_conn()
            await conn.execute(
                """
                UPDATE prototype_runtime_sessions
                SET status = 'corrupt', latest_checkpoint_id = NULL,
                    updated_at = ?, completed_at = ?
                WHERE status = 'active'
                """,
                (FIXED_NOW.isoformat(), FIXED_NOW.isoformat()),
            )
            await conn.commit()
        return await super().initialize_state(
            request_id=request_id,
            definition=definition,
            scenario_id=scenario_id,
            session_id=session_id,
        )


class _ToggleHistoryFailureObjectStore(PrototypeObjectStore):
    fail_history_writes = False

    def write_json(self, project_id: str, value: object) -> PrototypeObjectDescriptor:
        if (
            self.fail_history_writes
            and isinstance(value, dict)
            and "journalPrefixHash" in value
            and "undoStack" in value
        ):
            raise PrototypeObjectStoreError(
                "object_write_failed",
                "intentional command history checkpoint write failure",
            )
        return super().write_json(project_id, value)


class _BlockingDraftLoadStore(AsyncStructuredPrototypeStore):
    def __init__(self, db_path: Path) -> None:
        super().__init__(db_path)
        self.block_next_draft_load = False
        self.draft_load_started = asyncio.Event()
        self.release_draft_load = asyncio.Event()

    async def load_draft(self, draft_id: str) -> PrototypeDraftRecord | None:
        if self.block_next_draft_load:
            self.block_next_draft_load = False
            self.draft_load_started.set()
            await self.release_draft_load.wait()
        return await super().load_draft(draft_id)


class _BlockingRenderer:
    def __init__(self, identity: PrototypeRendererWorkerIdentity) -> None:
        self.identity = identity
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def render(
        self,
        *,
        request_id: str,
        artifact_id: str,
        input_manifest: dict[str, object],
        document: dict[str, object],
    ) -> PrototypeRendererWorkerResult:
        del request_id, artifact_id, input_manifest, document
        self.started.set()
        await self.release.wait()
        raise AssertionError("blocking renderer must be cancelled by the test")


def _publication_service(
    db_path: Path,
    object_root: Path,
    artifact_root: Path,
    *,
    renderer: PrototypeRendererWorker | _FailingRenderer | _BlockingRenderer | None = None,
) -> tuple[AsyncStructuredPrototypeStore, StructuredPrototypeService, PrototypeRendererWorker]:
    store = AsyncStructuredPrototypeStore(db_path)
    real_renderer = PrototypeRendererWorker()
    service = StructuredPrototypeService(
        store=store,
        object_store=PrototypeObjectStore(object_root),
        runtime_worker=PrototypeRuntimeWorker(),
        renderer_worker=renderer or real_renderer,
        artifact_store=PrototypeRenderArtifactStore(artifact_root),
        clock=lambda: FIXED_NOW,
    )
    return store, service, real_renderer


@pytest.mark.asyncio
async def test_create_apply_retry_and_restart_recover_the_same_document_hash(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "console.db"
    object_root = tmp_path / "managed-data"
    store, service = _service(db_path, object_root)
    create_request_id = fixture_id("service-create-request")
    apply_request_id = fixture_id("service-apply-request")

    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=create_request_id,
            document=_new_document(),
        )
        applied = await service.apply_command_batch(
            draft_id=created.state.draft.id,
            client_request_id=apply_request_id,
            expected_head_sequence_no=0,
            expected_document_hash=created.state.draft.head_document_hash,
            batch=_text_insert_batch(),
        )
        retried = await service.apply_command_batch(
            draft_id=created.state.draft.id,
            client_request_id=apply_request_id,
            expected_head_sequence_no=0,
            expected_document_hash=created.state.draft.head_document_hash,
            batch=_text_insert_batch(),
        )

        assert applied.state.draft.head_sequence_no == 1
        assert applied.state.draft.head_document_hash == document_hash(applied.state.document)
        assert retried.operation_id == applied.operation_id
        assert retried.applied_batch_id == applied.applied_batch_id
        assert retried.allocated_entity_ids == applied.allocated_entity_ids
        assert len(await store.list_operation_events(applied.operation_id)) == 3
        expected_hash = applied.state.draft.head_document_hash
        draft_id = applied.state.draft.id
    finally:
        await store.close()

    reopened_store, reopened_service = _service(db_path, object_root)
    try:
        recovery = await reopened_service.recover_draft(
            draft_id=draft_id,
            client_request_id=fixture_id("service-restart-recovery"),
        )
        recovered = recovery.state

        assert recovered.draft.head_sequence_no == 1
        assert recovered.draft.head_document_hash == expected_hash
        assert document_hash(recovered.document) == expected_hash
        assert len(recovered.applied_tail_batch_ids) == 1
    finally:
        await reopened_store.close()


@pytest.mark.asyncio
async def test_freeform_move_evidence_persists_through_recovery_history_and_checkpoint(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "console.db"
    object_root = tmp_path / "managed-data"
    live_attester = _SnapAttesterSpy()
    store, service = _service(db_path, object_root, snap_attester=live_attester)
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("service-move-evidence-create"),
            document=_new_freeform_document(),
        )
        base_hash = created.state.draft.head_document_hash
        base_root = created.state.document.pages[0].root
        assert isinstance(base_root, FreeformNodeV1)
        base_positions = {child.id: child.layout_item.position for child in base_root.children}
        batch = _freeform_move_evidence_batch(
            created.state.document,
            draft_id=created.state.draft.id,
            base_head_sequence_no=0,
            base_document_hash=base_hash,
        )
        assert batch.evidence is not None
        applied = await service.apply_command_batch(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("service-move-evidence-apply"),
            expected_head_sequence_no=0,
            expected_document_hash=base_hash,
            batch=batch,
        )
        stored = await store.load_command_batch(
            created.state.draft.id,
            applied.applied_batch_id,
        )
        assert stored is not None
        assert stored.commands_json == canonical_model_json(batch)
        stored_forward = parse_command_batch_json(stored.commands_json)
        assert stored_forward.evidence == batch.evidence
        assert stored_forward.evidence is not None
        assert stored_forward.evidence.grid_list_hash == freeform_grid_list_hash(
            stored_forward.evidence.grids
        )
        assert live_attester.attest_calls == [canonical_model_json(batch.evidence)]
        assert live_attester.attest_many_calls == []
        applied_hash = applied.state.draft.head_document_hash
        draft_id = applied.state.draft.id
        batch_id = applied.applied_batch_id
    finally:
        await store.close()

    recovery_attester = _SnapAttesterSpy()
    reopened_store, reopened_service = _service(
        db_path,
        object_root,
        snap_attester=recovery_attester,
    )
    try:
        recovered = await reopened_service.recover_draft(
            draft_id=draft_id,
            client_request_id=fixture_id("service-move-evidence-recover"),
        )
        assert recovered.state.draft.head_sequence_no == 1
        assert recovered.state.draft.head_document_hash == applied_hash
        assert recovered.state.applied_tail_batch_ids == (batch_id,)
        assert recovery_attester.attest_calls == []
        assert len(recovery_attester.attest_many_calls) == 1
        assert recovery_attester.attest_many_calls[0] == [canonical_model_json(batch.evidence)]
        recovered_root = recovered.state.document.pages[0].root
        assert isinstance(recovered_root, FreeformNodeV1)
        for child in recovered_root.children[:2]:
            base_position = base_positions[child.id]
            position = child.layout_item.position
            assert base_position is not None
            assert position is not None
            assert position.x == str(Decimal(base_position.x) + Decimal("8"))
            assert position.y == str(Decimal(base_position.y) + Decimal("4"))

        undone = await reopened_service.undo(
            draft_id=draft_id,
            client_request_id=fixture_id("service-move-evidence-undo"),
            expected_head_sequence_no=1,
            expected_document_hash=applied_hash,
        )
        assert undone.state.draft.head_document_hash == base_hash
        undone_root = undone.state.document.pages[0].root
        assert isinstance(undone_root, FreeformNodeV1)
        assert {
            child.id: child.layout_item.position for child in undone_root.children
        } == base_positions

        redone = await reopened_service.redo(
            draft_id=draft_id,
            client_request_id=fixture_id("service-move-evidence-redo"),
            expected_head_sequence_no=2,
            expected_document_hash=base_hash,
        )
        assert redone.state.draft.head_document_hash == applied_hash
        checkpointed = await reopened_service.checkpoint_draft(
            draft_id=draft_id,
            client_request_id=fixture_id("service-move-evidence-checkpoint"),
        )
        assert checkpointed.state.draft.head_sequence_no == 3
        assert checkpointed.state.applied_tail_batch_ids == ()
    finally:
        await reopened_store.close()

    checkpoint_store, checkpoint_service = _service(db_path, object_root)
    try:
        recovered_checkpoint = await checkpoint_service.recover_draft(
            draft_id=draft_id,
            client_request_id=fixture_id("service-move-evidence-checkpoint-recover"),
        )
        assert recovered_checkpoint.state.draft.head_sequence_no == 3
        assert recovered_checkpoint.state.draft.head_document_hash == applied_hash
        assert recovered_checkpoint.state.applied_tail_batch_ids == ()
        assert recovered_checkpoint.state.command_history.can_undo is True
        stored = await checkpoint_store.load_command_batch(draft_id, batch_id)
        assert stored is not None
        assert parse_command_batch_json(stored.commands_json).evidence == batch.evidence

        undone_checkpoint = await checkpoint_service.undo(
            draft_id=draft_id,
            client_request_id=fixture_id("service-move-evidence-checkpoint-undo"),
            expected_head_sequence_no=3,
            expected_document_hash=applied_hash,
        )
        assert undone_checkpoint.state.draft.head_document_hash == base_hash
    finally:
        await checkpoint_store.close()


@pytest.mark.asyncio
async def test_freeform_grid_list_survives_journal_reload_checkpoint_and_one_step_history(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "console.db"
    object_root = tmp_path / "managed-data"
    store, service = _service(db_path, object_root)
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("service-grid-list-create"),
            document=_new_freeform_document(),
        )
        base_hash = created.state.draft.head_document_hash
        base_root = created.state.document.pages[0].root
        assert isinstance(base_root, FreeformNodeV1)
        prior_grids = list(base_root.grids)
        assert len(prior_grids) == 2
        batch = DomainCommandBatchV1.model_validate(
            {
                "commandContractVersion": 1,
                "summary": "保存自由布局网格",
                "commands": [
                    {
                        "kind": "setNodeProperty",
                        "node": {"kind": "existing", "nodeId": base_root.id},
                        "update": {
                            "kind": "freeformGrids",
                            "grids": [
                                {
                                    "id": fixture_id("service-grid-list-rows"),
                                    "version": 1,
                                    "type": "rows",
                                    "visible": True,
                                    "snapEnabled": True,
                                    "origin": {"x": "0", "y": "0"},
                                    "params": {
                                        "count": 8,
                                        "itemSize": "72",
                                        "gutter": "12",
                                        "margin": "24",
                                        "alignment": "start",
                                        "colorTokenKey": "primary",
                                        "opacity": "0.18",
                                    },
                                }
                            ],
                        },
                    }
                ],
            },
            strict=True,
            by_alias=True,
            by_name=False,
        )
        forward_command = batch.commands[0]
        assert isinstance(forward_command, SetNodePropertyCommandV1)
        assert isinstance(forward_command.update, FreeformGridsUpdateV1)
        next_grids = forward_command.update.grids
        assert len(next_grids) == 1
        assert next_grids != prior_grids

        applied = await service.apply_command_batch(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("service-grid-list-apply"),
            expected_head_sequence_no=0,
            expected_document_hash=base_hash,
            batch=batch,
        )
        applied_hash = applied.state.draft.head_document_hash
        applied_root = applied.state.document.pages[0].root
        assert isinstance(applied_root, FreeformNodeV1)
        assert applied.state.draft.head_sequence_no == 1
        assert applied_hash == document_hash(applied.state.document)
        assert applied_root.grids == next_grids

        stored = await store.load_command_batch(
            applied.state.draft.id,
            applied.applied_batch_id,
        )
        assert stored is not None
        assert (
            stored.base_sequence_no,
            stored.result_sequence_no,
            stored.base_document_hash,
            stored.result_document_hash,
        ) == (0, 1, base_hash, applied_hash)
        stored_forward = parse_command_batch_json(stored.commands_json)
        stored_inverse = parse_inverse_command_batch_json(stored.inverse_commands_json)
        assert len(stored_forward.commands) == len(stored_inverse.commands) == 1
        stored_forward_command = stored_forward.commands[0]
        stored_inverse_command = stored_inverse.commands[0]
        assert isinstance(stored_forward_command, SetNodePropertyCommandV1)
        assert isinstance(stored_forward_command.update, FreeformGridsUpdateV1)
        assert stored_forward_command.update.grids == next_grids
        assert isinstance(stored_inverse_command, SetNodePropertyCommandV1)
        assert isinstance(stored_inverse_command.update, FreeformGridsUpdateV1)
        assert stored_inverse_command.update.grids == prior_grids
        assert stored.command_batch_hash == command_batch_envelope_hash(
            draft_id=stored.draft_id,
            base_sequence_no=stored.base_sequence_no,
            result_sequence_no=stored.result_sequence_no,
            origin=stored.origin,
            operation_kind=stored.operation_kind,
            target_batch_id=stored.target_batch_id,
            commands=stored_forward,
            inverse_commands=stored_inverse,
        )
        draft_id = applied.state.draft.id
        applied_batch_id = applied.applied_batch_id
    finally:
        await store.close()

    reopened_store, reopened_service = _service(db_path, object_root)
    try:
        reloaded = await reopened_service.recover_draft(
            draft_id=draft_id,
            client_request_id=fixture_id("service-grid-list-reload"),
        )
        reloaded_root = reloaded.state.document.pages[0].root
        assert isinstance(reloaded_root, FreeformNodeV1)
        assert reloaded.state.draft.head_sequence_no == 1
        assert reloaded.state.draft.head_document_hash == applied_hash
        assert document_hash(reloaded.state.document) == applied_hash
        assert reloaded.state.applied_tail_batch_ids == (applied_batch_id,)
        assert reloaded_root.grids == next_grids

        checkpointed = await reopened_service.checkpoint_draft(
            draft_id=draft_id,
            client_request_id=fixture_id("service-grid-list-checkpoint"),
        )
        assert checkpointed.state.draft.head_sequence_no == 1
        assert checkpointed.state.draft.head_document_hash == applied_hash
        assert checkpointed.state.loaded_checkpoint_sequence_no == 1
        assert checkpointed.state.applied_tail_batch_ids == ()
    finally:
        await reopened_store.close()

    checkpoint_store, checkpoint_service = _service(db_path, object_root)
    try:
        recovered = await checkpoint_service.recover_draft(
            draft_id=draft_id,
            client_request_id=fixture_id("service-grid-list-checkpoint-recover"),
        )
        recovered_root = recovered.state.document.pages[0].root
        assert isinstance(recovered_root, FreeformNodeV1)
        assert recovered.state.draft.head_sequence_no == 1
        assert recovered.state.draft.head_document_hash == applied_hash
        assert document_hash(recovered.state.document) == applied_hash
        assert recovered.state.applied_tail_batch_ids == ()
        assert recovered.state.command_history.can_undo is True
        assert recovered_root.grids == next_grids

        undone = await checkpoint_service.undo(
            draft_id=draft_id,
            client_request_id=fixture_id("service-grid-list-undo"),
            expected_head_sequence_no=1,
            expected_document_hash=applied_hash,
        )
        undone_root = undone.state.document.pages[0].root
        assert isinstance(undone_root, FreeformNodeV1)
        assert undone.state.draft.head_sequence_no == 2
        assert undone.state.draft.head_document_hash == base_hash
        assert document_hash(undone.state.document) == base_hash
        assert undone_root.grids == prior_grids
        undo_record = await checkpoint_store.load_command_batch(draft_id, undone.applied_batch_id)
        assert undo_record is not None
        assert (
            undo_record.base_sequence_no,
            undo_record.result_sequence_no,
            undo_record.base_document_hash,
            undo_record.result_document_hash,
        ) == (1, 2, applied_hash, base_hash)

        redone = await checkpoint_service.redo(
            draft_id=draft_id,
            client_request_id=fixture_id("service-grid-list-redo"),
            expected_head_sequence_no=2,
            expected_document_hash=base_hash,
        )
        redone_root = redone.state.document.pages[0].root
        assert isinstance(redone_root, FreeformNodeV1)
        assert redone.state.draft.head_sequence_no == 3
        assert redone.state.draft.head_document_hash == applied_hash
        assert document_hash(redone.state.document) == applied_hash
        assert redone_root.grids == next_grids
        redo_record = await checkpoint_store.load_command_batch(draft_id, redone.applied_batch_id)
        assert redo_record is not None
        assert (
            redo_record.base_sequence_no,
            redo_record.result_sequence_no,
            redo_record.base_document_hash,
            redo_record.result_document_hash,
        ) == (2, 3, base_hash, applied_hash)
    finally:
        await checkpoint_store.close()


@pytest.mark.asyncio
async def test_freeform_resize_frame_survives_reload_and_one_step_undo_redo(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "console.db"
    object_root = tmp_path / "managed-data"
    store, service = _service(db_path, object_root)
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("service-freeform-resize-create"),
            document=_new_freeform_document(),
        )
        base_hash = created.state.draft.head_document_hash
        base_root = created.state.document.pages[0].root
        assert isinstance(base_root, FreeformNodeV1)
        resized_node = base_root.children[0]
        base_frame = (
            resized_node.layout_item.position,
            resized_node.layout_item.width,
            resized_node.layout_item.height,
        )
        batch = DomainCommandBatchV1.model_validate(
            {
                "commandContractVersion": 1,
                "summary": "从西北方向调整自由布局节点",
                "commands": [
                    {
                        "kind": "setNodeLayout",
                        "node": {"kind": "existing", "nodeId": resized_node.id},
                        "update": {
                            "position": {"x": "16", "y": "24"},
                            "width": {"unit": "px", "value": "320"},
                            "height": {"unit": "px", "value": "96"},
                        },
                    }
                ],
            },
            strict=True,
            by_alias=True,
            by_name=False,
        )
        forward_command = batch.commands[0]
        assert isinstance(forward_command, SetNodeLayoutCommandV1)
        next_frame = (
            forward_command.update.position,
            forward_command.update.width,
            forward_command.update.height,
        )
        assert base_frame[0] is not None
        assert forward_command.update.position is not None
        assert Decimal(forward_command.update.position.x) < Decimal(base_frame[0].x)
        assert Decimal(forward_command.update.position.y) < Decimal(base_frame[0].y)

        applied = await service.apply_command_batch(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("service-freeform-resize-apply"),
            expected_head_sequence_no=0,
            expected_document_hash=base_hash,
            batch=batch,
        )
        applied_hash = applied.state.draft.head_document_hash
        applied_root = applied.state.document.pages[0].root
        assert isinstance(applied_root, FreeformNodeV1)
        applied_layout = applied_root.children[0].layout_item
        assert applied.state.draft.head_sequence_no == 1
        assert applied_hash == document_hash(applied.state.document)
        assert (applied_layout.position, applied_layout.width, applied_layout.height) == next_frame

        stored = await store.load_command_batch(
            applied.state.draft.id,
            applied.applied_batch_id,
        )
        assert stored is not None
        assert (
            stored.base_sequence_no,
            stored.result_sequence_no,
            stored.base_document_hash,
            stored.result_document_hash,
        ) == (0, 1, base_hash, applied_hash)
        stored_forward = parse_command_batch_json(stored.commands_json)
        stored_inverse = parse_inverse_command_batch_json(stored.inverse_commands_json)
        assert len(stored_forward.commands) == len(stored_inverse.commands) == 1
        stored_forward_command = stored_forward.commands[0]
        stored_inverse_command = stored_inverse.commands[0]
        assert isinstance(stored_forward_command, SetNodeLayoutCommandV1)
        assert stored_forward_command.update.model_fields_set == {
            "position",
            "width",
            "height",
        }
        assert (
            stored_forward_command.update.position,
            stored_forward_command.update.width,
            stored_forward_command.update.height,
        ) == next_frame
        assert isinstance(stored_inverse_command, SetNodeLayoutCommandV1)
        assert stored_inverse_command.update.model_fields_set == {
            "position",
            "width",
            "height",
        }
        assert (
            stored_inverse_command.update.position,
            stored_inverse_command.update.width,
            stored_inverse_command.update.height,
        ) == base_frame
        assert stored.command_batch_hash == command_batch_envelope_hash(
            draft_id=stored.draft_id,
            base_sequence_no=stored.base_sequence_no,
            result_sequence_no=stored.result_sequence_no,
            origin=stored.origin,
            operation_kind=stored.operation_kind,
            target_batch_id=stored.target_batch_id,
            commands=stored_forward,
            inverse_commands=stored_inverse,
        )
        draft_id = applied.state.draft.id
        applied_batch_id = applied.applied_batch_id
    finally:
        await store.close()

    reopened_store, reopened_service = _service(db_path, object_root)
    try:
        recovered = await reopened_service.recover_draft(
            draft_id=draft_id,
            client_request_id=fixture_id("service-freeform-resize-recover"),
        )
        recovered_root = recovered.state.document.pages[0].root
        assert isinstance(recovered_root, FreeformNodeV1)
        recovered_layout = recovered_root.children[0].layout_item
        assert recovered.state.draft.head_sequence_no == 1
        assert recovered.state.draft.head_document_hash == applied_hash
        assert document_hash(recovered.state.document) == applied_hash
        assert recovered.state.applied_tail_batch_ids == (applied_batch_id,)
        assert (
            recovered_layout.position,
            recovered_layout.width,
            recovered_layout.height,
        ) == next_frame

        undone = await reopened_service.undo(
            draft_id=draft_id,
            client_request_id=fixture_id("service-freeform-resize-undo"),
            expected_head_sequence_no=1,
            expected_document_hash=applied_hash,
        )
        undone_root = undone.state.document.pages[0].root
        assert isinstance(undone_root, FreeformNodeV1)
        undone_layout = undone_root.children[0].layout_item
        assert undone.state.draft.head_sequence_no == 2
        assert undone.state.draft.head_document_hash == base_hash
        assert document_hash(undone.state.document) == base_hash
        assert (undone_layout.position, undone_layout.width, undone_layout.height) == base_frame
        undo_record = await reopened_store.load_command_batch(draft_id, undone.applied_batch_id)
        assert undo_record is not None
        assert (
            undo_record.base_sequence_no,
            undo_record.result_sequence_no,
            undo_record.base_document_hash,
            undo_record.result_document_hash,
        ) == (1, 2, applied_hash, base_hash)

        redone = await reopened_service.redo(
            draft_id=draft_id,
            client_request_id=fixture_id("service-freeform-resize-redo"),
            expected_head_sequence_no=2,
            expected_document_hash=base_hash,
        )
        redone_root = redone.state.document.pages[0].root
        assert isinstance(redone_root, FreeformNodeV1)
        redone_layout = redone_root.children[0].layout_item
        assert redone.state.draft.head_sequence_no == 3
        assert redone.state.draft.head_document_hash == applied_hash
        assert document_hash(redone.state.document) == applied_hash
        assert (redone_layout.position, redone_layout.width, redone_layout.height) == next_frame
        redo_record = await reopened_store.load_command_batch(draft_id, redone.applied_batch_id)
        assert redo_record is not None
        assert (
            redo_record.base_sequence_no,
            redo_record.result_sequence_no,
            redo_record.base_document_hash,
            redo_record.result_document_hash,
        ) == (2, 3, base_hash, applied_hash)
    finally:
        await reopened_store.close()


@pytest.mark.asyncio
async def test_apply_snapshots_mutable_command_batch_before_its_first_await(
    tmp_path: Path,
) -> None:
    store = _BlockingDraftLoadStore(tmp_path / "console.db")
    service = StructuredPrototypeService(
        store=store,
        object_store=PrototypeObjectStore(tmp_path / "managed-data"),
        snap_attester=_SnapAttesterSpy(),
        clock=lambda: FIXED_NOW,
    )
    request_id = fixture_id("service-move-evidence-snapshot-apply")
    apply_task: asyncio.Task[ApplyStructuredPrototypeCommandsResult] | None = None
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("service-move-evidence-snapshot-create"),
            document=_new_freeform_document(),
        )
        base_hash = created.state.draft.head_document_hash
        batch = _freeform_move_evidence_batch(
            created.state.document,
            draft_id=created.state.draft.id,
            base_head_sequence_no=0,
            base_document_hash=base_hash,
        )
        original_batch_json = canonical_model_json(batch)
        store.block_next_draft_load = True
        apply_task = asyncio.create_task(
            service.apply_command_batch(
                draft_id=created.state.draft.id,
                client_request_id=request_id,
                expected_head_sequence_no=0,
                expected_document_hash=base_hash,
                batch=batch,
            )
        )
        await store.draft_load_started.wait()
        assert batch.evidence is not None
        batch.evidence.base_head_sequence_no = 99
        batch.summary = "调用方并发篡改"
        store.release_draft_load.set()
        applied = await apply_task

        stored = await store.load_command_batch_by_request(
            created.state.draft.id,
            request_id,
        )
        assert stored is not None
        assert stored.commands_json == original_batch_json
        persisted_batch = parse_command_batch_json(stored.commands_json)
        assert persisted_batch.evidence is not None
        assert persisted_batch.evidence.base_head_sequence_no == 0
        assert persisted_batch.summary == "移动自由布局组件组"

        retried = await service.apply_command_batch(
            draft_id=created.state.draft.id,
            client_request_id=request_id,
            expected_head_sequence_no=0,
            expected_document_hash=base_hash,
            batch=parse_command_batch_json(original_batch_json),
        )
        assert retried.operation_id == applied.operation_id
        assert retried.applied_batch_id == applied.applied_batch_id
    finally:
        store.release_draft_load.set()
        if apply_task is not None and not apply_task.done():
            await apply_task
        await store.close()


@pytest.mark.asyncio
async def test_operation_outcome_returns_durable_result_and_unknown_is_retryable(
    tmp_path: Path,
) -> None:
    store, service = _service(tmp_path / "console.db", tmp_path / "managed-data")
    request_id = fixture_id("service-operation-outcome")
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=request_id,
            document=_new_document(),
        )

        outcome = await service.get_operation_outcome(
            project_id="project-1",
            operation_kind="create_document",
            client_request_id=request_id,
        )
        assert outcome.id == created.operation_id
        assert outcome.status == "succeeded"
        assert outcome.resource_kind == "document"
        assert outcome.resource_id == created.state.document_record.id
        assert outcome.result_manifest_hash is not None

        with pytest.raises(StructuredPrototypeServiceError) as unknown:
            await service.get_operation_outcome(
                project_id="project-2",
                operation_kind="create_document",
                client_request_id=request_id,
            )
        assert unknown.value.code == "operation_outcome_unknown"
        assert unknown.value.retryable is True
        assert unknown.value.operation_id is None
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_static_table_row_survives_recovery_undo_and_redo(tmp_path: Path) -> None:
    db_path = tmp_path / "console.db"
    object_root = tmp_path / "managed-data"
    store, service = _service(db_path, object_root)
    row_id = fixture_id("static-table-row")
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("service-table-create"),
            document=_new_document(),
        )
        base_hash = created.state.draft.head_document_hash
        applied = await service.apply_command_batch(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("service-table-apply"),
            expected_head_sequence_no=0,
            expected_document_hash=base_hash,
            batch=_static_table_update_batch(),
        )
        applied_hash = applied.state.draft.head_document_hash
        draft_id = applied.state.draft.id
        assert row_id in canonical_model_json(applied.state.document)
    finally:
        await store.close()

    reopened_store, reopened_service = _service(db_path, object_root)
    try:
        recovered = await reopened_service.recover_draft(
            draft_id=draft_id,
            client_request_id=fixture_id("service-table-recover"),
        )
        assert recovered.state.draft.head_document_hash == applied_hash
        assert row_id in canonical_model_json(recovered.state.document)

        undone = await reopened_service.undo(
            draft_id=draft_id,
            client_request_id=fixture_id("service-table-undo"),
            expected_head_sequence_no=1,
            expected_document_hash=applied_hash,
        )
        assert undone.state.draft.head_document_hash == base_hash
        assert row_id not in canonical_model_json(undone.state.document)

        redone = await reopened_service.redo(
            draft_id=draft_id,
            client_request_id=fixture_id("service-table-redo"),
            expected_head_sequence_no=2,
            expected_document_hash=base_hash,
        )
        assert redone.state.draft.head_document_hash == applied_hash
        assert row_id in canonical_model_json(redone.state.document)
    finally:
        await reopened_store.close()


@pytest.mark.asyncio
async def test_node_layout_size_survives_recovery_undo_and_redo(tmp_path: Path) -> None:
    db_path = tmp_path / "console.db"
    object_root = tmp_path / "managed-data"
    store, service = _service(db_path, object_root)
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("service-layout-create"),
            document=_new_document_with_constrained_title_layout(),
        )
        base_hash = created.state.draft.head_document_hash
        base_document_json = canonical_model_json(created.state.document)
        with warnings.catch_warnings():
            warnings.simplefilter("error", UserWarning)
            applied = await service.apply_command_batch(
                draft_id=created.state.draft.id,
                client_request_id=fixture_id("service-layout-apply"),
                expected_head_sequence_no=0,
                expected_document_hash=base_hash,
                batch=_layout_update_batch(),
            )

        applied_layout = _list_title_layout(applied.state.document)
        assert applied_layout.width == LengthV1(unit="px", value="360")
        assert applied_layout.height == LengthV1(unit="px", value="72")
        _assert_title_layout_constraints(applied_layout)
        stored = await store.load_command_batch(
            applied.state.draft.id,
            applied.applied_batch_id,
        )
        assert stored is not None
        stored_forward = parse_command_batch_json(stored.commands_json)
        forward_command = stored_forward.commands[0]
        assert isinstance(forward_command, SetNodeLayoutCommandV1)
        assert forward_command.update.model_fields_set == {"width", "height"}
        assert forward_command.update.width == LengthV1(unit="px", value="360")
        assert forward_command.update.height == LengthV1(unit="px", value="72")
        stored_inverse = parse_inverse_command_batch_json(stored.inverse_commands_json)
        inverse_command = stored_inverse.commands[0]
        assert isinstance(inverse_command, SetNodeLayoutCommandV1)
        assert inverse_command.update.model_fields_set == {"width", "height"}
        assert inverse_command.update.width == LengthV1(unit="auto", value=None)
        assert inverse_command.update.height == LengthV1(unit="auto", value=None)
        applied_hash = applied.state.draft.head_document_hash
        draft_id = applied.state.draft.id
    finally:
        await store.close()

    reopened_store, reopened_service = _service(db_path, object_root)
    try:
        recovered = await reopened_service.recover_draft(
            draft_id=draft_id,
            client_request_id=fixture_id("service-layout-recover"),
        )
        assert recovered.state.draft.head_document_hash == applied_hash
        recovered_layout = _list_title_layout(recovered.state.document)
        assert recovered_layout.width == LengthV1(unit="px", value="360")
        assert recovered_layout.height == LengthV1(unit="px", value="72")
        _assert_title_layout_constraints(recovered_layout)

        undone = await reopened_service.undo(
            draft_id=draft_id,
            client_request_id=fixture_id("service-layout-undo"),
            expected_head_sequence_no=1,
            expected_document_hash=applied_hash,
        )
        assert undone.state.draft.head_document_hash == base_hash
        assert canonical_model_json(undone.state.document) == base_document_json
        undone_layout = _list_title_layout(undone.state.document)
        assert undone_layout.width == LengthV1(unit="auto", value=None)
        assert undone_layout.height == LengthV1(unit="auto", value=None)
        _assert_title_layout_constraints(undone_layout)

        redone = await reopened_service.redo(
            draft_id=draft_id,
            client_request_id=fixture_id("service-layout-redo"),
            expected_head_sequence_no=2,
            expected_document_hash=base_hash,
        )
        assert redone.state.draft.head_document_hash == applied_hash
        redone_layout = _list_title_layout(redone.state.document)
        assert redone_layout.width == LengthV1(unit="px", value="360")
        assert redone_layout.height == LengthV1(unit="px", value="72")
        _assert_title_layout_constraints(redone_layout)
    finally:
        await reopened_store.close()


@pytest.mark.asyncio
async def test_runtime_flow_position_survives_checkpoint_recovery_undo_and_redo(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "console.db"
    object_root = tmp_path / "managed-data"
    page_id = fixture_id("page-list")
    store, service = _service(db_path, object_root)
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("service-flow-layout-create"),
            document=_new_document(),
        )
        base_hash = created.state.draft.head_document_hash
        assert '"flowLayout"' not in canonical_model_json(created.state.document)
        applied = await service.apply_command_batch(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("service-flow-layout-apply"),
            expected_head_sequence_no=0,
            expected_document_hash=base_hash,
            batch=_runtime_flow_position_batch(page_id, x=-640, y=360),
        )
        applied_hash = applied.state.draft.head_document_hash
        assert applied_hash != base_hash
        await service.checkpoint_draft(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("service-flow-layout-checkpoint"),
        )
        draft_id = created.state.draft.id
    finally:
        await store.close()

    reopened_store, reopened_service = _service(db_path, object_root)
    try:
        recovered = await reopened_service.recover_draft(
            draft_id=draft_id,
            client_request_id=fixture_id("service-flow-layout-recover"),
        )
        assert recovered.state.draft.head_document_hash == applied_hash
        assert document_hash(recovered.state.document) == applied_hash
        assert recovered.state.applied_tail_batch_ids == ()
        recovered_layout = recovered.state.document.runtime.flow_layout
        assert recovered_layout is not None
        assert [(node.node_id, node.x, node.y) for node in recovered_layout.nodes] == [
            (page_id, -640, 360)
        ]

        undone = await reopened_service.undo(
            draft_id=draft_id,
            client_request_id=fixture_id("service-flow-layout-undo"),
            expected_head_sequence_no=1,
            expected_document_hash=applied_hash,
        )
        assert undone.state.draft.head_document_hash == base_hash
        assert document_hash(undone.state.document) == base_hash
        assert undone.state.document.runtime.flow_layout is None
        assert '"flowLayout"' not in canonical_model_json(undone.state.document)

        redone = await reopened_service.redo(
            draft_id=draft_id,
            client_request_id=fixture_id("service-flow-layout-redo"),
            expected_head_sequence_no=2,
            expected_document_hash=base_hash,
        )
        assert redone.state.draft.head_document_hash == applied_hash
        assert document_hash(redone.state.document) == applied_hash
        redone_layout = redone.state.document.runtime.flow_layout
        assert redone_layout is not None
        assert [(node.node_id, node.x, node.y) for node in redone_layout.nodes] == [
            (page_id, -640, 360)
        ]
    finally:
        await reopened_store.close()


@pytest.mark.asyncio
async def test_undo_redo_retry_branching_and_multi_step_history(tmp_path: Path) -> None:
    store, service = _service(tmp_path / "console.db", tmp_path / "managed-data")
    undo_request_id = fixture_id("service-undo-insert")
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("service-history-create"),
            document=_new_document(),
        )
        base_hash = created.state.draft.head_document_hash
        assert created.state.command_history.can_undo is False
        assert created.state.command_history.can_redo is False

        inserted = await service.apply_command_batch(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("service-history-insert"),
            expected_head_sequence_no=0,
            expected_document_hash=base_hash,
            batch=_text_insert_batch(),
        )
        inserted_id = dict(inserted.allocated_entity_ids)["approval-note"]
        inserted_hash = inserted.state.draft.head_document_hash
        assert inserted.state.command_history.can_undo is True
        assert inserted.state.command_history.can_redo is False

        undone = await service.undo(
            draft_id=created.state.draft.id,
            client_request_id=undo_request_id,
            expected_head_sequence_no=1,
            expected_document_hash=inserted_hash,
        )
        retried_undo = await service.undo(
            draft_id=created.state.draft.id,
            client_request_id=undo_request_id,
            expected_head_sequence_no=1,
            expected_document_hash=inserted_hash,
        )
        assert undone.state.draft.head_document_hash == base_hash
        assert undone.allocated_entity_ids == ()
        assert undone.state.command_history.can_undo is False
        assert undone.state.command_history.can_redo is True
        assert retried_undo.operation_id == undone.operation_id
        assert retried_undo.applied_batch_id == undone.applied_batch_id
        assert retried_undo.allocated_entity_ids == ()

        redone = await service.redo(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("service-redo-insert"),
            expected_head_sequence_no=2,
            expected_document_hash=base_hash,
        )
        assert redone.state.draft.head_document_hash == inserted_hash
        assert redone.allocated_entity_ids == ()
        assert inserted_id in redone.state.document.model_dump_json(by_alias=True)

        with pytest.raises(StructuredPrototypeServiceError) as superseded:
            await service.undo(
                draft_id=created.state.draft.id,
                client_request_id=undo_request_id,
                expected_head_sequence_no=1,
                expected_document_hash=inserted_hash,
            )
        assert superseded.value.code == "idempotent_result_superseded"

        second = await service.apply_command_batch(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("service-history-second"),
            expected_head_sequence_no=3,
            expected_document_hash=inserted_hash,
            batch=_text_update_batch("第二步"),
        )
        second_undo = await service.undo(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("service-history-second-undo"),
            expected_head_sequence_no=4,
            expected_document_hash=second.state.draft.head_document_hash,
        )
        assert second_undo.state.command_history.can_redo is True

        branch = await service.apply_command_batch(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("service-history-branch"),
            expected_head_sequence_no=5,
            expected_document_hash=inserted_hash,
            batch=_text_update_batch("分支步骤"),
        )
        assert branch.state.command_history.can_redo is False
        with pytest.raises(StructuredPrototypeServiceError) as unavailable:
            await service.redo(
                draft_id=created.state.draft.id,
                client_request_id=fixture_id("service-history-cleared-redo"),
                expected_head_sequence_no=6,
                expected_document_hash=branch.state.draft.head_document_hash,
            )
        assert unavailable.value.code == "redo_unavailable"

        branch_undo = await service.undo(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("service-history-branch-undo"),
            expected_head_sequence_no=6,
            expected_document_hash=branch.state.draft.head_document_hash,
        )
        insert_undo = await service.undo(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("service-history-insert-undo-again"),
            expected_head_sequence_no=7,
            expected_document_hash=branch_undo.state.draft.head_document_hash,
        )
        assert insert_undo.state.draft.head_document_hash == base_hash
        assert insert_undo.state.command_history.can_undo is False
        assert insert_undo.state.command_history.can_redo is True

        insert_redo = await service.redo(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("service-history-insert-redo-again"),
            expected_head_sequence_no=8,
            expected_document_hash=base_hash,
        )
        branch_redo = await service.redo(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("service-history-branch-redo"),
            expected_head_sequence_no=9,
            expected_document_hash=insert_redo.state.draft.head_document_hash,
        )
        assert branch_redo.state.draft.head_document_hash == branch.state.draft.head_document_hash
        assert inserted_id in branch_redo.state.document.model_dump_json(by_alias=True)
        assert branch_redo.state.command_history.can_redo is False
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_checkpoint_preserves_undo_history(tmp_path: Path) -> None:
    store, service = _service(tmp_path / "console.db", tmp_path / "managed-data")
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("service-checkpoint-history-create"),
            document=_new_document(),
        )
        base_hash = created.state.draft.head_document_hash
        applied = await service.apply_command_batch(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("service-checkpoint-history-command"),
            expected_head_sequence_no=0,
            expected_document_hash=base_hash,
            batch=_text_insert_batch(),
        )
        checkpointed = await service.checkpoint_draft(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("service-checkpoint-history"),
        )

        assert checkpointed.state.applied_tail_batch_ids == ()
        assert checkpointed.state.command_history.can_undo is True
        undone = await service.undo(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("service-checkpoint-history-undo"),
            expected_head_sequence_no=1,
            expected_document_hash=applied.state.draft.head_document_hash,
        )
        assert undone.state.draft.head_document_hash == base_hash
        assert undone.state.command_history.can_redo is True
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_undo_rejects_a_tampered_snapshot_stack_target(
    tmp_path: Path,
) -> None:
    store, service = _service(tmp_path / "console.db", tmp_path / "managed-data")
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("service-prefix-inverse-create"),
            document=_new_document(),
        )
        await service.apply_command_batch(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("service-prefix-inverse-command"),
            expected_head_sequence_no=0,
            expected_document_hash=created.state.draft.head_document_hash,
            batch=_text_insert_batch(),
        )
        await service.checkpoint_draft(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("service-prefix-inverse-checkpoint"),
        )
        stored = await store.load_command_batch_by_request(
            created.state.draft.id,
            fixture_id("service-prefix-inverse-command"),
        )
        assert stored is not None
        bad_inverse = InverseCommandBatchV1.model_validate(
            {
                "commandContractVersion": 1,
                "commands": [
                    {
                        "kind": "removeNode",
                        "nodeId": fixture_id("service-prefix-inverse-missing-node"),
                    }
                ],
            },
            strict=True,
            by_alias=True,
            by_name=False,
        )
        bad_inverse_json = canonical_model_json(bad_inverse)
        bad_envelope_hash = command_batch_envelope_hash(
            draft_id=stored.draft_id,
            base_sequence_no=stored.base_sequence_no,
            result_sequence_no=stored.result_sequence_no,
            origin=stored.origin,
            operation_kind=stored.operation_kind,
            target_batch_id=stored.target_batch_id,
            commands=parse_command_batch_json(stored.commands_json),
            inverse_commands=bad_inverse,
        )
        conn = await store._get_conn()
        await conn.execute(
            "UPDATE prototype_command_batches "
            "SET inverse_commands_json = ?, command_batch_hash = ? WHERE id = ?",
            (bad_inverse_json, bad_envelope_hash, stored.id),
        )
        await conn.commit()

        recovered = await service.recover_draft(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("service-prefix-inverse-recovery"),
        )
        assert recovered.state.applied_tail_batch_ids == ()

        with pytest.raises(StructuredPrototypeServiceError) as error:
            await service.undo(
                draft_id=created.state.draft.id,
                client_request_id=fixture_id("service-prefix-inverse-undo"),
                expected_head_sequence_no=1,
                expected_document_hash=recovered.state.draft.head_document_hash,
            )

        assert error.value.code == "command_history_corrupt"
        corrupt_draft = await store.load_draft(created.state.draft.id)
        assert corrupt_draft is not None
        assert corrupt_draft.status == "corrupt"
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_undo_corruption_atomically_marks_the_draft_corrupt(
    tmp_path: Path,
) -> None:
    store, service = _service(tmp_path / "console.db", tmp_path / "managed-data")
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("service-undo-corruption-create"),
            document=_new_document(),
        )
        applied = await service.apply_command_batch(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("service-undo-corruption-command"),
            expected_head_sequence_no=0,
            expected_document_hash=created.state.draft.head_document_hash,
            batch=_text_insert_batch(),
        )
        conn = await store._get_conn()
        await conn.execute(
            "UPDATE prototype_command_batches SET inverse_commands_json = ? WHERE id = ?",
            (
                '{"commandContractVersion":1,"commands":['
                '{"kind":"removeNode","nodeId":"'
                f"{fixture_id('service-undo-corruption-missing-node')}"
                '"}]}',
                applied.applied_batch_id,
            ),
        )
        await conn.commit()

        with pytest.raises(StructuredPrototypeServiceError) as error:
            await service.undo(
                draft_id=created.state.draft.id,
                client_request_id=fixture_id("service-undo-corruption-request"),
                expected_head_sequence_no=1,
                expected_document_hash=applied.state.draft.head_document_hash,
            )

        assert error.value.code == "replay_batch_hash_mismatch"
        assert error.value.operation_id is not None
        corrupt_draft = await store.load_draft(created.state.draft.id)
        assert corrupt_draft is not None
        assert corrupt_draft.status == "corrupt"
        operation = await store.load_operation(error.value.operation_id)
        assert operation is not None
        assert operation.status == "failed"
        assert operation.error_code == "replay_batch_hash_mismatch"
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_recovery_marks_a_history_target_payload_mismatch_as_corrupt(tmp_path: Path) -> None:
    store, service = _service(tmp_path / "console.db", tmp_path / "managed-data")
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("service-corrupt-history-create"),
            document=_new_document(),
        )
        first = await service.apply_command_batch(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("service-corrupt-history-first"),
            expected_head_sequence_no=0,
            expected_document_hash=created.state.draft.head_document_hash,
            batch=_text_insert_batch(),
        )
        second = await service.apply_command_batch(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("service-corrupt-history-second"),
            expected_head_sequence_no=1,
            expected_document_hash=first.state.draft.head_document_hash,
            batch=_text_update_batch("待破坏"),
        )
        undone = await service.undo(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("service-corrupt-history-undo"),
            expected_head_sequence_no=2,
            expected_document_hash=second.state.draft.head_document_hash,
        )
        conn = await store._get_conn()
        await conn.execute(
            "UPDATE prototype_command_batches SET commands_json = ? WHERE id = ?",
            ('{"commandContractVersion":1,"commands":[]}', undone.applied_batch_id),
        )
        await conn.commit()

        with pytest.raises(StructuredPrototypeServiceError) as error:
            await service.recover_draft(
                draft_id=created.state.draft.id,
                client_request_id=fixture_id("service-corrupt-history-recovery"),
            )

        assert error.value.code == "inverse_command_batch_invalid"
        corrupt_draft = await store.load_draft(created.state.draft.id)
        assert corrupt_draft is not None
        assert corrupt_draft.status == "corrupt"
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_delete_project_prototype_purges_historical_objects_and_render_files(
    tmp_path: Path,
) -> None:
    object_root = tmp_path / "managed-data"
    store, service = _service(tmp_path / "console.db", object_root)
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("delete-physical-document"),
            document=_new_document(),
        )
        await service.apply_command_batch(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("delete-physical-command"),
            expected_head_sequence_no=0,
            expected_document_hash=created.state.draft.head_document_hash,
            batch=_text_insert_batch(),
        )
        project_store = object_root / "projects/project-1/prototype-store"
        render_file = project_store / "renders/document-1/artifact-1/index.html"
        render_file.parent.mkdir(parents=True)
        render_file.write_text("historical render", encoding="utf-8")
        assert len(tuple(project_store.rglob("*.json.zst"))) > 1

        request_id = fixture_id("delete-physical-request")
        deleted = await service.delete_project_prototype(
            project_id="project-1",
            client_request_id=request_id,
        )

        assert deleted.deleted is True
        assert await store.load_document(created.state.document_record.id) is None
        assert not (project_store / "renders").exists()
        assert len(tuple(project_store.rglob("*.json.zst"))) == 1
        detail = await service.get_operation_detail(deleted.operation_id)
        assert detail.snapshot.operation.status == "succeeded"
        assert detail.replay_manifest is not None
        conn = await store._get_conn()
        async with conn.execute(
            "SELECT COUNT(*) FROM prototype_objects WHERE project_id = ?",
            ("project-1",),
        ) as cursor:
            object_count = await cursor.fetchone()
        async with conn.execute(
            "SELECT COUNT(*) FROM prototype_object_references WHERE project_id = ?",
            ("project-1",),
        ) as cursor:
            reference_count = await cursor.fetchone()
        assert object_count is not None and int(object_count[0]) == 1
        assert reference_count is not None and int(reference_count[0]) == 1

        replayed = await service.delete_project_prototype(
            project_id="project-1",
            client_request_id=request_id,
        )
        assert replayed == deleted

        replacement = await service.delete_project_prototype(
            project_id="project-1",
            client_request_id=fixture_id("delete-physical-replacement-request"),
        )
        assert replacement.operation_id != deleted.operation_id
        assert await store.load_operation(deleted.operation_id) is None
        assert len(tuple(project_store.rglob("*.json.zst"))) == 1
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_delete_project_prototype_recovers_physical_cleanup_before_releasing_gate(
    tmp_path: Path,
) -> None:
    object_store = _FailOncePurgeObjectStore(tmp_path / "managed-data")
    store, service = _service(
        tmp_path / "console.db",
        tmp_path / "managed-data",
        object_store=object_store,
    )
    request_id = fixture_id("delete-cleanup-retry-request")
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("delete-cleanup-retry-document"),
            document=_new_document(),
        )

        with pytest.raises(StructuredPrototypeServiceError) as exc_info:
            await service.delete_project_prototype(
                project_id="project-1",
                client_request_id=request_id,
            )

        assert exc_info.value.code == "prototype_cleanup_pending"
        assert exc_info.value.retryable is True
        assert exc_info.value.operation_id is not None
        running = await store.load_operation(exc_info.value.operation_id)
        assert running is not None and running.status == "running"
        assert await store.load_document(created.state.document_record.id) is None
        assert await service.recover_interrupted_non_generation_operations() == 0

        with pytest.raises(StructuredPrototypeServiceError) as busy_info:
            await service.create_document(
                project_id="project-1",
                client_request_id=fixture_id("delete-cleanup-retry-blocked-create"),
                document=_new_document(),
            )
        assert busy_info.value.code == "prototype_busy"

        assert await service.recover_pending_project_prototype_deletions() == 1
        completed = await service.delete_project_prototype(
            project_id="project-1",
            client_request_id=request_id,
        )
        assert completed.operation_id == running.id
        assert object_store.purge_attempts == 2
        persisted = await store.load_operation(running.id)
        assert persisted is not None and persisted.status == "succeeded"
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_delete_project_prototype_waits_for_physical_cleanup_when_cancelled(
    tmp_path: Path,
) -> None:
    object_store = _BlockingPurgeObjectStore(tmp_path / "managed-data")
    store, service = _service(
        tmp_path / "console.db",
        tmp_path / "managed-data",
        object_store=object_store,
    )
    request_id = fixture_id("delete-cleanup-cancel-request")
    try:
        await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("delete-cleanup-cancel-document"),
            document=_new_document(),
        )
        delete_task = asyncio.create_task(
            service.delete_project_prototype(
                project_id="project-1",
                client_request_id=request_id,
            )
        )
        assert await asyncio.wait_for(
            asyncio.to_thread(object_store.purge_started.wait, 1),
            timeout=1,
        )

        assert delete_task.cancel()
        await asyncio.sleep(0)
        assert not delete_task.done()
        object_store.release_purge.set()

        with pytest.raises(asyncio.CancelledError):
            await delete_task

        running = await store.load_operation_by_request(
            "project-1",
            "delete_project_prototype",
            request_id,
        )
        assert running is not None and running.status == "running"
        assert await service.recover_pending_project_prototype_deletions() == 1
    finally:
        object_store.release_purge.set()
        await store.close()


@pytest.mark.asyncio
async def test_delete_project_prototype_fails_closed_while_an_operation_is_active(
    tmp_path: Path,
) -> None:
    store, service = _service(tmp_path / "console.db", tmp_path / "managed-data")
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("delete-busy-document"),
            document=_new_document(),
        )
        active_operation = PrototypeOperation(
            id=fixture_id("delete-busy-active-operation"),
            operation_kind="apply_command_batch",
            project_id="project-1",
            resource_kind="draft",
            resource_id=created.state.draft.id,
            client_request_id=fixture_id("delete-busy-active-request"),
            correlation_id=fixture_id("delete-busy-active-correlation"),
            parent_operation_id=None,
            status="queued",
            phase="queued",
            attempt=1,
            request_manifest_hash="sha256:" + "a" * 64,
            config_manifest_hash="sha256:" + "b" * 64,
            result_manifest_hash=None,
            failure_evidence_hash=None,
            error_code=None,
            created_at=FIXED_NOW,
            started_at=None,
            completed_at=None,
        )
        await store.create_operation(
            active_operation,
            PrototypeOperationEvent(
                operation_id=active_operation.id,
                event_no=0,
                step_id=None,
                event_kind="operation_queued",
                status="queued",
                phase="queued",
                input_hash=active_operation.request_manifest_hash,
                output_hash=None,
                evidence_hash=None,
                error_code=None,
                occurred_at=FIXED_NOW,
            ),
        )
        active_step = PrototypeOperationStep(
            id=fixture_id("delete-busy-active-step"),
            operation_id=active_operation.id,
            parent_step_id=None,
            step_kind="apply_commands",
            step_ordinal=0,
            attempt=1,
            status="running",
            phase="apply_commands",
            input_manifest_hash=active_operation.request_manifest_hash,
            config_manifest_hash=active_operation.config_manifest_hash,
            output_manifest_hash=None,
            completion_evidence_kind=None,
            completion_evidence_ref=None,
            error_code=None,
            started_at=FIXED_NOW,
            completed_at=None,
        )
        running_operation = replace(
            active_operation,
            status="running",
            phase="apply_commands",
            started_at=FIXED_NOW,
        )
        await store.record_operation_transition(
            running_operation,
            active_step,
            PrototypeOperationEvent(
                operation_id=active_operation.id,
                event_no=1,
                step_id=active_step.id,
                event_kind="step_started",
                status="running",
                phase="apply_commands",
                input_hash=active_operation.request_manifest_hash,
                output_hash=None,
                evidence_hash=None,
                error_code=None,
                occurred_at=FIXED_NOW,
            ),
        )

        with pytest.raises(StructuredPrototypeServiceError) as exc_info:
            await service.delete_project_prototype(
                project_id="project-1",
                client_request_id=fixture_id("delete-busy-request"),
            )

        assert exc_info.value.code == "prototype_busy"
        assert exc_info.value.retryable is True
        assert await store.load_document(created.state.document_record.id) is not None
        assert exc_info.value.operation_id is not None
        failed_delete = await store.load_operation(exc_info.value.operation_id)
        assert failed_delete is not None
        assert failed_delete.status == "failed"
        assert failed_delete.error_code == "prototype_busy"

        assert await service.recover_interrupted_non_generation_operations() == 1
        recovered = await service.get_operation_detail(active_operation.id)
        assert recovered.snapshot.operation.status == "interrupted"
        assert recovered.snapshot.operation.phase == "service_restart_recovery"
        assert recovered.snapshot.operation.error_code == "service_restart"
        assert recovered.snapshot.steps == (
            replace(
                active_step,
                status="interrupted",
                phase="service_restart_recovery",
                output_manifest_hash=recovered.snapshot.operation.failure_evidence_hash,
                completion_evidence_kind="failure_manifest_hash",
                completion_evidence_ref=recovered.snapshot.operation.failure_evidence_hash,
                error_code="service_restart",
                completed_at=FIXED_NOW,
            ),
        )
        assert [event.status for event in recovered.snapshot.events] == [
            "queued",
            "running",
            "interrupted",
        ]
        assert recovered.snapshot.events[-1].event_kind == "operation_interrupted"

        deleted = await service.delete_project_prototype(
            project_id="project-1",
            client_request_id=fixture_id("delete-after-restart-recovery"),
        )
        assert deleted.deleted is True
        assert await store.load_document(created.state.document_record.id) is None
        assert await store.load_operation(active_operation.id) is None
    finally:
        await store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation_kind", "resource_kind"),
    [
        ("generation_job", "generation_job"),
        ("generation_item", "generation_item"),
    ],
)
async def test_delete_project_prototype_treats_unmatched_generation_operation_as_busy(
    tmp_path: Path,
    operation_kind: Literal["generation_job", "generation_item"],
    resource_kind: str,
) -> None:
    store, service = _service(tmp_path / "console.db", tmp_path / "managed-data")
    active_operation = _queued_operation(
        f"delete-busy-unmatched-{operation_kind}",
        operation_kind=operation_kind,
        resource_kind=resource_kind,
    )
    try:
        await _persist_queued_operation(store, active_operation)

        with pytest.raises(StructuredPrototypeServiceError) as exc_info:
            await service.delete_project_prototype(
                project_id="project-1",
                client_request_id=fixture_id(f"delete-busy-unmatched-{operation_kind}-request"),
            )

        assert exc_info.value.code == "prototype_busy"
        loaded = await store.load_operation(active_operation.id)
        assert loaded is not None
        assert loaded.status == "queued"
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_restart_recovery_completes_queued_operation_but_skips_recursive_generation_tree(
    tmp_path: Path,
) -> None:
    store, service = _service(tmp_path / "console.db", tmp_path / "managed-data")
    ordinary = _queued_operation(
        "restart-queued-ordinary",
        operation_kind="gc_run",
        resource_kind="project_prototype",
    )
    generation_root = _queued_operation(
        "restart-generation-root",
        operation_kind="generation_job",
        resource_kind="generation_job",
    )
    generation_child = _queued_operation(
        "restart-generation-child",
        operation_kind="create_document",
        resource_kind="document",
        parent_operation_id=generation_root.id,
    )
    generation_grandchild = _queued_operation(
        "restart-generation-grandchild",
        operation_kind="gc_run",
        resource_kind="project_prototype",
        parent_operation_id=generation_child.id,
    )
    try:
        for item in (ordinary, generation_root, generation_child, generation_grandchild):
            await _persist_queued_operation(store, item)

        assert await service.recover_interrupted_non_generation_operations() == 1
        recovered = await service.get_operation_detail(ordinary.id)
        assert recovered.snapshot.operation.status == "interrupted"
        assert [event.status for event in recovered.snapshot.events] == [
            "queued",
            "running",
            "interrupted",
        ]
        assert len(recovered.snapshot.steps) == 1
        assert recovered.snapshot.steps[0].status == "interrupted"
        assert recovered.snapshot.steps[0].step_kind == "service_restart_recovery"
        assert await service.recover_interrupted_non_generation_operations() == 0

        for item in (generation_root, generation_child, generation_grandchild):
            loaded = await store.load_operation(item.id)
            assert loaded is not None
            assert loaded.status == "queued"
            assert [event.status for event in await store.list_operation_events(item.id)] == [
                "queued"
            ]
    finally:
        await store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation_kind", "resource_kind", "has_broken_parent"),
    [
        ("generation_job", "generation_job", True),
        ("generation_item", "generation_item", False),
    ],
)
async def test_restart_recovery_rejects_generation_operations_outside_owned_tree(
    tmp_path: Path,
    operation_kind: Literal["generation_job", "generation_item"],
    resource_kind: str,
    has_broken_parent: bool,
) -> None:
    store, service = _service(tmp_path / "console.db", tmp_path / "managed-data")
    ordinary = _queued_operation(
        "restart-rollback-ordinary",
        operation_kind="gc_run",
        resource_kind="project_prototype",
        operation_id="00000000-0000-4000-8000-000000000001",
    )
    unowned = _queued_operation(
        f"restart-unowned-{operation_kind}",
        operation_kind=operation_kind,
        resource_kind=resource_kind,
        parent_operation_id=ordinary.id if has_broken_parent else None,
        operation_id="ffffffff-ffff-4fff-bfff-ffffffffffff",
    )
    try:
        await _persist_queued_operation(store, ordinary)
        await _persist_queued_operation(store, unowned)

        with pytest.raises(StructuredPrototypeServiceError) as exc_info:
            await service.recover_interrupted_non_generation_operations()

        assert exc_info.value.code == "operation_recovery_corrupt"
        loaded_ordinary = await store.load_operation(ordinary.id)
        assert loaded_ordinary is not None
        assert loaded_ordinary.status == "queued"
        assert await store.list_operation_steps(ordinary.id) == []
        assert [event.event_no for event in await store.list_operation_events(ordinary.id)] == [0]
        loaded_unowned = await store.load_operation(unowned.id)
        assert loaded_unowned is not None
        assert loaded_unowned.status == "queued"
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_restart_recovery_rejects_gapped_operation_event_history(
    tmp_path: Path,
) -> None:
    store, service = _service(tmp_path / "console.db", tmp_path / "managed-data")
    operation = _queued_operation(
        "restart-gapped-events",
        operation_kind="gc_run",
        resource_kind="project_prototype",
    )
    try:
        await _persist_queued_operation(store, operation)
        conn = await store._get_conn()
        await conn.execute(
            """
            INSERT INTO prototype_operation_events (
                operation_id, event_no, step_id, event_kind, status, phase,
                input_hash, output_hash, evidence_hash, error_code, occurred_at
            ) VALUES (?, 2, NULL, 'operation_queued', 'queued', 'queued', ?, NULL, NULL, NULL, ?)
            """,
            (operation.id, operation.request_manifest_hash, FIXED_NOW.isoformat()),
        )
        await conn.commit()

        with pytest.raises(StructuredPrototypeServiceError) as exc_info:
            await service.recover_interrupted_non_generation_operations()

        assert exc_info.value.code == "operation_event_corrupt"
        loaded = await store.load_operation(operation.id)
        assert loaded is not None
        assert loaded.status == "queued"
        assert await store.list_operation_steps(operation.id) == []
        assert [event.event_no for event in await store.list_operation_events(operation.id)] == [
            0,
            2,
        ]
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_restart_recovery_rolls_back_when_cancelled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, service = _service(tmp_path / "console.db", tmp_path / "managed-data")
    operation = _queued_operation(
        "restart-cancelled-transaction",
        operation_kind="gc_run",
        resource_kind="project_prototype",
    )
    try:
        await _persist_queued_operation(store, operation)
        conn = await store._get_conn()
        original_apply = store._apply_operation_transition
        apply_calls = 0

        async def cancel_first_transition(
            connection: aiosqlite.Connection,
            incoming_operation: PrototypeOperation,
            step: PrototypeOperationStep,
            event: PrototypeOperationEvent,
        ) -> None:
            nonlocal apply_calls
            await original_apply(connection, incoming_operation, step, event)
            apply_calls += 1
            if apply_calls == 1:
                raise asyncio.CancelledError

        monkeypatch.setattr(store, "_apply_operation_transition", cancel_first_transition)

        with pytest.raises(asyncio.CancelledError):
            await service.recover_interrupted_non_generation_operations()

        assert conn.in_transaction is False
        loaded = await store.load_operation(operation.id)
        assert loaded is not None
        assert loaded.status == "queued"
        assert await store.list_operation_steps(operation.id) == []
        assert [event.event_no for event in await store.list_operation_events(operation.id)] == [0]
        assert await service.recover_interrupted_non_generation_operations() == 1
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_restart_recovery_cancellation_while_worker_commit_is_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, service = _service(tmp_path / "console.db", tmp_path / "managed-data")
    operation = _queued_operation(
        "restart-cancelled-worker-commit",
        operation_kind="gc_run",
        resource_kind="project_prototype",
    )
    release_worker = threading.Event()
    try:
        await _persist_queued_operation(store, operation)
        conn = await store._get_conn()
        raw_connection = conn._conn
        assert raw_connection is not None
        raw_commit = raw_connection.commit
        original_rollback = conn.rollback
        loop = asyncio.get_running_loop()
        worker_started = asyncio.Event()
        rollback_calls = 0

        async def worker_gated_commit() -> None:
            def blocked_commit() -> None:
                loop.call_soon_threadsafe(worker_started.set)
                if not release_worker.wait(timeout=2):
                    raise TimeoutError("timed out waiting to release worker commit")
                raw_commit()

            await conn._execute(blocked_commit)

        async def track_rollback() -> None:
            nonlocal rollback_calls
            rollback_calls += 1
            await original_rollback()

        monkeypatch.setattr(conn, "commit", worker_gated_commit)
        monkeypatch.setattr(conn, "rollback", track_rollback)

        recovery_task = asyncio.create_task(service.recover_interrupted_non_generation_operations())
        await asyncio.wait_for(worker_started.wait(), timeout=1)
        assert recovery_task.cancel()
        await asyncio.sleep(0)
        assert not recovery_task.done()
        release_worker.set()

        with pytest.raises(asyncio.CancelledError):
            await recovery_task

        assert rollback_calls == 0
        assert conn.in_transaction is False
        loaded = await store.load_operation(operation.id)
        assert loaded is not None
        assert loaded.status == "interrupted"
        assert loaded.error_code == "service_restart"
        assert [event.status for event in await store.list_operation_events(operation.id)] == [
            "queued",
            "running",
            "interrupted",
        ]
    finally:
        release_worker.set()
        await store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cancel_count",
    [1, 2],
    ids=["single-cancel", "double-cancel"],
)
async def test_restart_recovery_cancellation_during_commit_preserves_committed_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cancel_count: Literal[1, 2],
) -> None:
    store, service = _service(tmp_path / "console.db", tmp_path / "managed-data")
    operation = _queued_operation(
        "restart-cancelled-commit",
        operation_kind="gc_run",
        resource_kind="project_prototype",
    )
    try:
        await _persist_queued_operation(store, operation)
        conn = await store._get_conn()
        original_commit = conn.commit
        original_rollback = conn.rollback
        commit_applied = asyncio.Event()
        release_commit_result = asyncio.Event()
        rollback_calls = 0

        async def commit_then_hold_result() -> None:
            await original_commit()
            commit_applied.set()
            await release_commit_result.wait()

        async def track_rollback() -> None:
            nonlocal rollback_calls
            rollback_calls += 1
            await original_rollback()

        monkeypatch.setattr(conn, "commit", commit_then_hold_result)
        monkeypatch.setattr(conn, "rollback", track_rollback)

        recovery_task = asyncio.create_task(service.recover_interrupted_non_generation_operations())
        await asyncio.wait_for(commit_applied.wait(), timeout=1)
        for _ in range(cancel_count):
            assert recovery_task.cancel()
            await asyncio.sleep(0)
            assert not recovery_task.done()
        release_commit_result.set()

        with pytest.raises(asyncio.CancelledError):
            await recovery_task

        assert rollback_calls == 0
        assert conn.in_transaction is False
        loaded = await store.load_operation(operation.id)
        assert loaded is not None
        assert loaded.status == "interrupted"
        assert loaded.error_code == "service_restart"
        assert [event.status for event in await store.list_operation_events(operation.id)] == [
            "queued",
            "running",
            "interrupted",
        ]
        assert await service.recover_interrupted_non_generation_operations() == 0
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_restart_recovery_propagates_commit_failure_after_cancellation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, service = _service(tmp_path / "console.db", tmp_path / "managed-data")
    operation = _queued_operation(
        "restart-cancelled-failed-commit",
        operation_kind="gc_run",
        resource_kind="project_prototype",
    )
    release_commit_failure = asyncio.Event()
    release_rollback = asyncio.Event()
    try:
        await _persist_queued_operation(store, operation)
        conn = await store._get_conn()
        original_commit = conn.commit
        original_rollback = conn.rollback
        commit_started = asyncio.Event()
        rollback_started = asyncio.Event()
        rollback_completed = asyncio.Event()
        rollback_calls = 0

        async def fail_commit_after_release() -> None:
            commit_started.set()
            await release_commit_failure.wait()
            raise aiosqlite.OperationalError("injected delayed commit failure")

        async def track_rollback() -> None:
            nonlocal rollback_calls
            rollback_calls += 1
            rollback_started.set()
            await release_rollback.wait()
            await original_rollback()
            rollback_completed.set()

        monkeypatch.setattr(conn, "commit", fail_commit_after_release)
        monkeypatch.setattr(conn, "rollback", track_rollback)

        recovery_task = asyncio.create_task(service.recover_interrupted_non_generation_operations())
        await asyncio.wait_for(commit_started.wait(), timeout=1)
        assert recovery_task.cancel()
        await asyncio.sleep(0)
        assert not recovery_task.done()
        assert recovery_task.cancel()
        await asyncio.sleep(0)
        assert not recovery_task.done()
        release_commit_failure.set()
        await asyncio.wait_for(rollback_started.wait(), timeout=1)
        assert not recovery_task.done()
        assert recovery_task.cancel()
        await asyncio.sleep(0)
        assert not recovery_task.done()
        release_rollback.set()

        with pytest.raises(
            aiosqlite.OperationalError, match="injected delayed commit failure"
        ) as exc:
            await recovery_task

        assert isinstance(exc.value.__cause__, asyncio.CancelledError)
        assert rollback_calls == 1
        assert rollback_completed.is_set()
        assert conn.in_transaction is False
        loaded = await store.load_operation(operation.id)
        assert loaded is not None
        assert loaded.status == "queued"
        assert await store.list_operation_steps(operation.id) == []
        assert [event.event_no for event in await store.list_operation_events(operation.id)] == [0]

        monkeypatch.setattr(conn, "commit", original_commit)
        assert await service.recover_interrupted_non_generation_operations() == 1
    finally:
        release_commit_failure.set()
        release_rollback.set()
        await store.close()


@pytest.mark.asyncio
async def test_restart_recovery_rolls_back_when_commit_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, service = _service(tmp_path / "console.db", tmp_path / "managed-data")
    operation = _queued_operation(
        "restart-commit-failure",
        operation_kind="gc_run",
        resource_kind="project_prototype",
    )
    try:
        await _persist_queued_operation(store, operation)
        conn = await store._get_conn()
        original_commit = conn.commit
        commit_calls = 0

        async def fail_first_commit() -> None:
            nonlocal commit_calls
            commit_calls += 1
            if commit_calls == 1:
                raise aiosqlite.OperationalError("injected commit failure")
            await original_commit()

        monkeypatch.setattr(conn, "commit", fail_first_commit)

        with pytest.raises(aiosqlite.OperationalError, match="injected commit failure"):
            await service.recover_interrupted_non_generation_operations()

        assert conn.in_transaction is False
        loaded = await store.load_operation(operation.id)
        assert loaded is not None
        assert loaded.status == "queued"
        assert await store.list_operation_steps(operation.id) == []
        assert [event.event_no for event in await store.list_operation_events(operation.id)] == [0]
        assert await service.recover_interrupted_non_generation_operations() == 1
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_create_retry_returns_the_existing_durable_draft(tmp_path: Path) -> None:
    store, service = _service(tmp_path / "console.db", tmp_path / "managed-data")
    request_id = fixture_id("service-create-idempotent")
    try:
        first = await service.create_document(
            project_id="project-1",
            client_request_id=request_id,
            document=_new_document(),
        )
        second = await service.create_document(
            project_id="project-1",
            client_request_id=request_id,
            document=_new_document(),
        )

        assert second.operation_id == first.operation_id
        assert second.state.draft.id == first.state.draft.id
        assert second.state.draft.head_document_hash == first.state.draft.head_document_hash
        assert len(await store.list_operation_events(first.operation_id)) == 3
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_corrupt_checkpoint_object_marks_draft_corrupt_with_failure_evidence(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "console.db"
    object_root = tmp_path / "managed-data"
    store, service = _service(db_path, object_root)
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("service-create-corrupt"),
            document=_new_document(),
        )
        recovery_request_id = fixture_id("service-corrupt-recovery")
        successful_recovery = await service.recover_draft(
            draft_id=created.state.draft.id,
            client_request_id=recovery_request_id,
        )
        bundle = await store.load_draft_recovery_bundle(created.state.draft.id)
        object_path = object_root / bundle.object_descriptor.storage_key
        payload = bytearray(object_path.read_bytes())
        payload[-1] ^= 0x01
        object_path.write_bytes(payload)

        with pytest.raises(StructuredPrototypeServiceError) as error:
            await service.recover_draft(
                draft_id=created.state.draft.id,
                client_request_id=recovery_request_id,
            )

        assert error.value.code == "object_hash_mismatch"
        draft = await store.load_draft(created.state.draft.id)
        assert draft is not None
        assert draft.status == "corrupt"
        operation_id = error.value.operation_id
        assert operation_id is not None
        assert operation_id != successful_recovery.operation_id
        assert [item.status for item in await store.list_operation_events(operation_id)] == [
            "queued",
            "running",
            "failed",
        ]
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_stale_apply_fails_with_current_head_and_durable_operation_evidence(
    tmp_path: Path,
) -> None:
    store, service = _service(tmp_path / "console.db", tmp_path / "managed-data")
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("service-create-conflict"),
            document=_new_document(),
        )
        applied = await service.apply_command_batch(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("service-first-command"),
            expected_head_sequence_no=0,
            expected_document_hash=created.state.draft.head_document_hash,
            batch=_text_insert_batch(),
        )

        with pytest.raises(StructuredPrototypeServiceError) as error:
            await service.apply_command_batch(
                draft_id=created.state.draft.id,
                client_request_id=fixture_id("service-stale-command"),
                expected_head_sequence_no=0,
                expected_document_hash=created.state.draft.head_document_hash,
                batch=_text_insert_batch(),
            )

        assert error.value.code == "draft_conflict"
        assert error.value.current_head_sequence_no == 1
        assert error.value.current_document_hash == applied.state.draft.head_document_hash
        operation_id = error.value.operation_id
        assert operation_id is not None
        assert [item.status for item in await store.list_operation_events(operation_id)] == [
            "queued",
            "running",
            "failed",
        ]
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_freeform_move_evidence_mismatch_fails_without_advancing_the_draft(
    tmp_path: Path,
) -> None:
    store, service = _service(tmp_path / "console.db", tmp_path / "managed-data")
    request_id = fixture_id("service-move-evidence-mismatch")
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("service-move-evidence-mismatch-create"),
            document=_new_freeform_document(),
        )
        base_hash = created.state.draft.head_document_hash
        batch = _freeform_move_evidence_batch(
            created.state.document,
            draft_id=created.state.draft.id,
            base_head_sequence_no=1,
            base_document_hash=base_hash,
        )

        with pytest.raises(StructuredPrototypeServiceError) as error:
            await service.apply_command_batch(
                draft_id=created.state.draft.id,
                client_request_id=request_id,
                expected_head_sequence_no=0,
                expected_document_hash=base_hash,
                batch=batch,
            )

        assert error.value.code == "command_evidence_mismatch"
        assert error.value.operation_id is not None
        draft = await store.load_draft(created.state.draft.id)
        assert draft is not None
        assert draft.status == "active"
        assert draft.head_sequence_no == 0
        assert draft.head_document_hash == base_hash
        assert await store.load_command_batch_by_request(draft.id, request_id) is None
        operation = await store.load_operation(error.value.operation_id)
        assert operation is not None
        assert operation.status == "failed"
        assert operation.error_code == "command_evidence_mismatch"
        assert operation.failure_evidence_hash is not None
        events = await store.list_operation_events(operation.id)
        assert [event.status for event in events] == ["queued", "running", "failed"]
        assert events[-1].error_code == "command_evidence_mismatch"
        assert events[-1].evidence_hash == operation.failure_evidence_hash
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_live_snap_attestation_mismatch_fails_before_journal_append(
    tmp_path: Path,
) -> None:
    attester = _SnapAttesterSpy()
    attester.failure_code = "snap_attestation_mismatch"
    store, service = _service(
        tmp_path / "console.db",
        tmp_path / "managed-data",
        snap_attester=attester,
    )
    request_id = fixture_id("service-live-snap-attestation-mismatch")
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("service-live-snap-attestation-create"),
            document=_new_freeform_document(),
        )
        base_hash = created.state.draft.head_document_hash
        batch = _freeform_move_evidence_batch(
            created.state.document,
            draft_id=created.state.draft.id,
            base_head_sequence_no=0,
            base_document_hash=base_hash,
        )
        assert batch.evidence is not None

        with pytest.raises(StructuredPrototypeServiceError) as error:
            await service.apply_command_batch(
                draft_id=created.state.draft.id,
                client_request_id=request_id,
                expected_head_sequence_no=0,
                expected_document_hash=base_hash,
                batch=batch,
            )

        assert error.value.code == "command_evidence_mismatch"
        assert attester.attest_calls == [canonical_model_json(batch.evidence)]
        assert attester.attest_many_calls == []
        draft = await store.load_draft(created.state.draft.id)
        assert draft is not None
        assert draft.status == "active"
        assert draft.head_sequence_no == 0
        assert draft.head_document_hash == base_hash
        assert await store.load_command_batch_by_request(draft.id, request_id) is None
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_live_snap_worker_unavailable_refuses_without_corrupting_draft(
    tmp_path: Path,
) -> None:
    store = AsyncStructuredPrototypeStore(tmp_path / "console.db")
    service = StructuredPrototypeService(
        store=store,
        object_store=PrototypeObjectStore(tmp_path / "managed-data"),
        clock=lambda: FIXED_NOW,
    )
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("service-snap-unavailable-create"),
            document=_new_freeform_document(),
        )
        batch = _freeform_move_evidence_batch(
            created.state.document,
            draft_id=created.state.draft.id,
            base_head_sequence_no=0,
            base_document_hash=created.state.draft.head_document_hash,
        )

        with pytest.raises(StructuredPrototypeServiceError) as error:
            await service.apply_command_batch(
                draft_id=created.state.draft.id,
                client_request_id=fixture_id("service-snap-unavailable-apply"),
                expected_head_sequence_no=0,
                expected_document_hash=created.state.draft.head_document_hash,
                batch=batch,
            )

        assert error.value.code == "snap_worker_unavailable"
        draft = await store.load_draft(created.state.draft.id)
        assert draft is not None
        assert draft.status == "active"
        assert draft.head_sequence_no == 0
        assert draft.head_document_hash == created.state.draft.head_document_hash
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_recovery_revalidates_stored_freeform_move_evidence_context(
    tmp_path: Path,
) -> None:
    store, service = _service(tmp_path / "console.db", tmp_path / "managed-data")
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("service-stored-evidence-create"),
            document=_new_freeform_document(),
        )
        batch = _freeform_move_evidence_batch(
            created.state.document,
            draft_id=created.state.draft.id,
            base_head_sequence_no=0,
            base_document_hash=created.state.draft.head_document_hash,
        )
        assert batch.evidence is not None
        applied = await service.apply_command_batch(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("service-stored-evidence-apply"),
            expected_head_sequence_no=0,
            expected_document_hash=created.state.draft.head_document_hash,
            batch=batch,
        )
        stored = await store.load_command_batch(
            created.state.draft.id,
            applied.applied_batch_id,
        )
        assert stored is not None
        tampered_payload = json.loads(stored.commands_json)
        assert isinstance(tampered_payload, dict)
        tampered_evidence = tampered_payload["evidence"]
        assert isinstance(tampered_evidence, dict)
        tampered_evidence["baseHeadSequenceNo"] = 9
        tampered_batch = DomainCommandBatchV1.model_validate(
            tampered_payload,
            strict=True,
            by_alias=True,
            by_name=False,
        )
        inverse = parse_inverse_command_batch_json(stored.inverse_commands_json)
        tampered_commands_json = canonical_model_json(tampered_batch)
        tampered_envelope_hash = command_batch_envelope_hash(
            draft_id=stored.draft_id,
            base_sequence_no=stored.base_sequence_no,
            result_sequence_no=stored.result_sequence_no,
            origin=stored.origin,
            operation_kind=stored.operation_kind,
            target_batch_id=stored.target_batch_id,
            commands=tampered_batch,
            inverse_commands=inverse,
        )
        conn = await store._get_conn()
        await conn.execute(
            "UPDATE prototype_command_batches "
            "SET commands_json = ?, command_batch_hash = ? WHERE id = ?",
            (tampered_commands_json, tampered_envelope_hash, stored.id),
        )
        await conn.commit()

        with pytest.raises(StructuredPrototypeServiceError) as error:
            await service.recover_draft(
                draft_id=created.state.draft.id,
                client_request_id=fixture_id("service-stored-evidence-recover"),
            )

        assert error.value.code == "command_evidence_mismatch"
        assert error.value.operation_id is not None
        corrupt_draft = await store.load_draft(created.state.draft.id)
        assert corrupt_draft is not None
        assert corrupt_draft.status == "corrupt"
        operation = await store.load_operation(error.value.operation_id)
        assert operation is not None
        assert operation.status == "failed"
        assert operation.error_code == "command_evidence_mismatch"
        assert operation.failure_evidence_hash is not None
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_recovery_bulk_attestation_rejects_before_any_command_executes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attester = _SnapAttesterSpy()
    store, service = _service(
        tmp_path / "console.db",
        tmp_path / "managed-data",
        snap_attester=attester,
    )
    executed_batch_ids: list[str] = []
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("service-bulk-attestation-create"),
            document=_new_freeform_document(),
        )
        batch = _freeform_move_evidence_batch(
            created.state.document,
            draft_id=created.state.draft.id,
            base_head_sequence_no=0,
            base_document_hash=created.state.draft.head_document_hash,
        )
        applied = await service.apply_command_batch(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("service-bulk-attestation-apply"),
            expected_head_sequence_no=0,
            expected_document_hash=created.state.draft.head_document_hash,
            batch=batch,
        )
        original_execute = service._execute_stored_command_batch

        def counted_execute(
            document: PrototypeDocumentV1,
            stored_batch: PrototypeCommandBatchRecord,
        ) -> CommandExecutionResultV1:
            executed_batch_ids.append(stored_batch.id)
            return original_execute(document, stored_batch)

        monkeypatch.setattr(service, "_execute_stored_command_batch", counted_execute)
        attester.failure_code = "snap_attestation_mismatch"

        with pytest.raises(StructuredPrototypeServiceError) as error:
            await service.recover_draft(
                draft_id=created.state.draft.id,
                client_request_id=fixture_id("service-bulk-attestation-recover"),
            )

        assert error.value.code == "command_evidence_mismatch"
        assert executed_batch_ids == []
        assert len(attester.attest_many_calls) == 1
        assert batch.evidence is not None
        assert attester.attest_many_calls[0] == [canonical_model_json(batch.evidence)]
        corrupt = await store.load_draft(created.state.draft.id)
        assert corrupt is not None
        assert corrupt.status == "corrupt"
        assert corrupt.head_sequence_no == applied.state.draft.head_sequence_no
        assert corrupt.head_document_hash == applied.state.draft.head_document_hash
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_recovery_snap_worker_unavailable_refuses_without_marking_draft_corrupt(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "console.db"
    object_root = tmp_path / "managed-data"
    store, service = _service(db_path, object_root)
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("service-recovery-snap-unavailable-create"),
            document=_new_freeform_document(),
        )
        batch = _freeform_move_evidence_batch(
            created.state.document,
            draft_id=created.state.draft.id,
            base_head_sequence_no=0,
            base_document_hash=created.state.draft.head_document_hash,
        )
        applied = await service.apply_command_batch(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("service-recovery-snap-unavailable-apply"),
            expected_head_sequence_no=0,
            expected_document_hash=created.state.draft.head_document_hash,
            batch=batch,
        )
        draft_id = applied.state.draft.id
    finally:
        await store.close()

    reopened_store = AsyncStructuredPrototypeStore(db_path)
    unavailable_service = StructuredPrototypeService(
        store=reopened_store,
        object_store=PrototypeObjectStore(object_root),
        clock=lambda: FIXED_NOW,
    )
    try:
        with pytest.raises(StructuredPrototypeServiceError) as error:
            await unavailable_service.recover_draft(
                draft_id=draft_id,
                client_request_id=fixture_id("service-recovery-snap-unavailable-recover"),
            )

        assert error.value.code == "snap_worker_unavailable"
        draft = await reopened_store.load_draft(draft_id)
        assert draft is not None
        assert draft.status == "active"
        assert draft.head_sequence_no == 1
        assert draft.head_document_hash == applied.state.draft.head_document_hash
    finally:
        await reopened_store.close()


@pytest.mark.asyncio
@pytest.mark.slow
async def test_recovery_attests_two_hundred_evidence_entries_in_one_bulk_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        prototype_service_module,
        "COMMAND_BATCHES_PER_AUTOMATIC_CHECKPOINT",
        1_000,
    )
    db_path = tmp_path / "console.db"
    object_root = tmp_path / "managed-data"
    write_attester = _SnapAttesterSpy()
    store, service = _service(db_path, object_root, snap_attester=write_attester)
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("service-200-attest-create"),
            document=_new_freeform_document(),
        )
        state = created.state
        for index in range(200):
            direction = Decimal("1") if index % 2 == 0 else Decimal("-1")
            batch = _freeform_move_evidence_batch(
                state.document,
                draft_id=state.draft.id,
                base_head_sequence_no=state.draft.head_sequence_no,
                base_document_hash=state.draft.head_document_hash,
                delta_x=Decimal("8") * direction,
                delta_y=Decimal("4") * direction,
            )
            applied = await service.apply_command_batch(
                draft_id=state.draft.id,
                client_request_id=fixture_id(f"service-200-attest-apply-{index}"),
                expected_head_sequence_no=state.draft.head_sequence_no,
                expected_document_hash=state.draft.head_document_hash,
                batch=batch,
            )
            state = applied.state
        draft_id = state.draft.id
        final_hash = state.draft.head_document_hash
        assert state.draft.head_sequence_no == 200
    finally:
        await store.close()

    recovery_attester = _SnapAttesterSpy()
    reopened_store, reopened_service = _service(
        db_path,
        object_root,
        snap_attester=recovery_attester,
    )
    try:
        recovered = await reopened_service.recover_draft(
            draft_id=draft_id,
            client_request_id=fixture_id("service-200-attest-recover"),
        )

        assert recovered.state.draft.head_sequence_no == 200
        assert recovered.state.draft.head_document_hash == final_hash
        assert recovery_attester.attest_calls == []
        assert len(recovery_attester.attest_many_calls) == 1
        assert len(recovery_attester.attest_many_calls[0]) == 200
    finally:
        await reopened_store.close()


@pytest.mark.asyncio
async def test_checkpoint_materializes_the_current_head_and_resets_replay_tail(
    tmp_path: Path,
) -> None:
    store, service = _service(tmp_path / "console.db", tmp_path / "managed-data")
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("service-create-checkpoint"),
            document=_new_document(),
        )
        applied = await service.apply_command_batch(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("service-command-before-checkpoint"),
            expected_head_sequence_no=0,
            expected_document_hash=created.state.draft.head_document_hash,
            batch=_text_insert_batch(),
        )
        checkpoint_request_id = fixture_id("service-checkpoint-head")
        checkpointed = await service.checkpoint_draft(
            draft_id=created.state.draft.id,
            client_request_id=checkpoint_request_id,
        )
        retried = await service.checkpoint_draft(
            draft_id=created.state.draft.id,
            client_request_id=checkpoint_request_id,
        )
        bundle = await store.load_draft_recovery_bundle(created.state.draft.id)

        assert checkpointed.state.draft.head_sequence_no == 1
        assert checkpointed.state.draft.head_document_hash == applied.state.draft.head_document_hash
        assert checkpointed.state.loaded_checkpoint_sequence_no == 1
        assert checkpointed.state.applied_tail_batch_ids == ()
        assert retried.checkpoint_id == checkpointed.checkpoint_id
        assert bundle.checkpoint.id == checkpointed.checkpoint_id
        assert bundle.checkpoint.checkpoint_sequence_no == 1
        assert bundle.command_batches == ()
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_100_modifications_auto_checkpoint_and_recover_only_latest_tail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "console.db"
    object_root = tmp_path / "managed-data"
    store, service = _service(db_path, object_root)
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("service-auto-checkpoint-create"),
            document=_new_document(),
        )
        state = created.state
        mutation_replay_count = [0]
        execute_during_mutation = service._execute_stored_command_batch

        def count_mutation_replay(
            document: PrototypeDocumentV1,
            stored_batch: PrototypeCommandBatchRecord,
        ) -> CommandExecutionResultV1:
            mutation_replay_count[0] += 1
            return execute_during_mutation(document, stored_batch)

        monkeypatch.setattr(
            service,
            "_execute_stored_command_batch",
            count_mutation_replay,
        )
        mutation_replay_counts: list[int] = []
        for index in range(100):
            mutation_replay_count[0] = 0
            applied = await service.apply_command_batch(
                draft_id=state.draft.id,
                client_request_id=fixture_id(f"service-auto-checkpoint-command-{index}"),
                expected_head_sequence_no=state.draft.head_sequence_no,
                expected_document_hash=state.draft.head_document_hash,
                batch=_text_update_batch(f"自动保存步骤 {index}"),
            )
            state = applied.state
            mutation_replay_counts.append(mutation_replay_count[0])

        bundle = await store.load_draft_recovery_bundle(state.draft.id)
        assert state.draft.head_sequence_no == 100
        assert bundle.checkpoint.checkpoint_sequence_no == 50
        assert len(bundle.command_batches) == 50
        assert max(mutation_replay_counts) <= 50
        draft_id = state.draft.id
    finally:
        await store.close()

    reopened_store, reopened_service = _service(db_path, object_root)
    replayed_batch_ids: list[str] = []
    execute_stored = reopened_service._execute_stored_command_batch

    def counted_execute(
        document: PrototypeDocumentV1,
        stored_batch: PrototypeCommandBatchRecord,
    ) -> CommandExecutionResultV1:
        replayed_batch_ids.append(stored_batch.id)
        return execute_stored(document, stored_batch)

    monkeypatch.setattr(
        reopened_service,
        "_execute_stored_command_batch",
        counted_execute,
    )
    try:
        recovered = await reopened_service.recover_draft(
            draft_id=draft_id,
            client_request_id=fixture_id("service-auto-checkpoint-recovery"),
        )

        assert recovered.state.loaded_checkpoint_sequence_no == 50
        assert recovered.state.draft.head_sequence_no == 100
        assert len(recovered.state.applied_tail_batch_ids) == 50
        assert replayed_batch_ids == list(recovered.state.applied_tail_batch_ids)
    finally:
        await reopened_store.close()


@pytest.mark.asyncio
async def test_automatic_checkpoint_failure_refuses_mutation_without_advancing_head(
    tmp_path: Path,
) -> None:
    store = AsyncStructuredPrototypeStore(tmp_path / "console.db")
    object_store = _ToggleHistoryFailureObjectStore(tmp_path / "managed-data")
    service = StructuredPrototypeService(
        store=store,
        object_store=object_store,
        clock=lambda: FIXED_NOW,
    )
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("service-auto-checkpoint-failure-create"),
            document=_new_document(),
        )
        state = created.state
        for index in range(50):
            applied = await service.apply_command_batch(
                draft_id=state.draft.id,
                client_request_id=fixture_id(f"service-auto-checkpoint-failure-command-{index}"),
                expected_head_sequence_no=state.draft.head_sequence_no,
                expected_document_hash=state.draft.head_document_hash,
                batch=_text_update_batch(f"失败前步骤 {index}"),
            )
            state = applied.state

        object_store.fail_history_writes = True
        with pytest.raises(StructuredPrototypeServiceError) as error:
            await service.apply_command_batch(
                draft_id=state.draft.id,
                client_request_id=fixture_id("service-auto-checkpoint-refused-command"),
                expected_head_sequence_no=state.draft.head_sequence_no,
                expected_document_hash=state.draft.head_document_hash,
                batch=_text_update_batch("不应提交"),
            )

        assert error.value.code == "checkpoint_required_unavailable"
        persisted = await store.load_draft(state.draft.id)
        assert persisted is not None
        assert persisted.head_sequence_no == 50
        assert persisted.head_document_hash == state.draft.head_document_hash
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_runtime_session_apply_retry_and_recover_use_the_node_worker(
    tmp_path: Path,
) -> None:
    store, service = _runtime_service(tmp_path / "console.db", tmp_path / "managed-data")
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("runtime-service-document"),
            document=_new_document(),
        )
        runtime = await service.create_runtime_session(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("runtime-service-session"),
            scenario_id=fixture_id("scenario-happy-path"),
            recording_kind="studio_preview",
            actor_subject_id="product-manager-1",
        )
        event_request_id = fixture_id("runtime-service-field-event")
        batch: dict[str, object] = {
            "clientEventId": event_request_id,
            "expectedSequenceNo": 0,
            "events": [
                {
                    "kind": "fieldValueCommitted",
                    "nodeId": fixture_id("input-title"),
                    "formId": fixture_id("form-create"),
                    "fieldId": fixture_id("form-field-title"),
                    "value": {"type": "string", "value": "采购办公设备"},
                }
            ],
        }
        applied = await service.apply_runtime_event_batch(
            session_id=runtime.state.session.id,
            client_request_id=event_request_id,
            expected_head_sequence_no=0,
            expected_state_hash=runtime.state.session.head_state_hash,
            batch=batch,
        )
        retried = await service.apply_runtime_event_batch(
            session_id=runtime.state.session.id,
            client_request_id=event_request_id,
            expected_head_sequence_no=0,
            expected_state_hash=runtime.state.session.head_state_hash,
            batch=batch,
        )
        checkpoint_request_id = fixture_id("runtime-service-checkpoint")
        checkpointed = await service.checkpoint_runtime_session(
            session_id=runtime.state.session.id,
            client_request_id=checkpoint_request_id,
        )
        checkpoint_retry = await service.checkpoint_runtime_session(
            session_id=runtime.state.session.id,
            client_request_id=checkpoint_request_id,
        )
        recovered = await service.recover_runtime_session(
            session_id=runtime.state.session.id,
            client_request_id=fixture_id("runtime-service-recover"),
        )

        assert runtime.state.session.runtime_core_version == "0.2.0-spike"
        assert runtime.state.session.state_machine_kernel_version == "5.32.4"
        assert applied.state.session.head_sequence_no == 1
        assert applied.outcome == "applied"
        assert retried.event_batch_id == applied.event_batch_id
        assert checkpointed.state.loaded_checkpoint_sequence_no == 1
        assert checkpoint_retry.checkpoint_id == checkpointed.checkpoint_id
        assert recovered.state.session.head_state_hash == applied.state.session.head_state_hash
        assert recovered.state.state_json == applied.state.state_json
        assert recovered.state.view_model_json == applied.state.view_model_json
        assert recovered.state.replayed_event_batch_ids == ()
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_runtime_replay_evidence_mismatch_marks_session_corrupt(
    tmp_path: Path,
) -> None:
    store, service = _runtime_service(tmp_path / "console.db", tmp_path / "managed-data")
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("runtime-corrupt-document"),
            document=_new_document(),
        )
        runtime = await service.create_runtime_session(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("runtime-corrupt-session"),
            scenario_id=fixture_id("scenario-happy-path"),
            recording_kind="recorded_review",
            actor_subject_id=None,
        )
        event_request_id = fixture_id("runtime-corrupt-event")
        applied = await service.apply_runtime_event_batch(
            session_id=runtime.state.session.id,
            client_request_id=event_request_id,
            expected_head_sequence_no=0,
            expected_state_hash=runtime.state.session.head_state_hash,
            batch={
                "clientEventId": event_request_id,
                "expectedSequenceNo": 0,
                "events": [
                    {
                        "kind": "switchSimulatedRole",
                        "roleId": fixture_id("role-applicant"),
                    }
                ],
            },
        )
        conn = await store._get_conn()
        await conn.execute(
            "UPDATE prototype_runtime_event_batches SET guard_report_hash = ? WHERE id = ?",
            ("sha256:" + "f" * 64, applied.event_batch_id),
        )
        await conn.commit()

        with pytest.raises(StructuredPrototypeServiceError) as error:
            await service.recover_runtime_session(
                session_id=runtime.state.session.id,
                client_request_id=fixture_id("runtime-corrupt-recovery"),
            )

        assert error.value.code == "runtime_replay_evidence_mismatch"
        persisted = await store.load_runtime_session(runtime.state.session.id)
        assert persisted is not None
        assert persisted.status == "corrupt"
        operation_id = error.value.operation_id
        assert operation_id is not None
        assert [item.status for item in await store.list_operation_events(operation_id)] == [
            "queued",
            "running",
            "failed",
        ]
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_runtime_worker_version_mismatch_preserves_session_and_records_failure(
    tmp_path: Path,
) -> None:
    store, service = _runtime_service(tmp_path / "console.db", tmp_path / "managed-data")
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("runtime-version-document"),
            document=_new_document(),
        )
        runtime = await service.create_runtime_session(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("runtime-version-session"),
            scenario_id=fixture_id("scenario-happy-path"),
            recording_kind="studio_preview",
            actor_subject_id=None,
        )
        conn = await store._get_conn()
        unavailable_bundle_hash = "sha256:" + "f" * 64
        assert unavailable_bundle_hash != runtime.state.session.runtime_core_bundle_hash
        await conn.execute(
            "UPDATE prototype_runtime_sessions SET runtime_core_bundle_hash = ? WHERE id = ?",
            (unavailable_bundle_hash, runtime.state.session.id),
        )
        await conn.commit()

        with pytest.raises(StructuredPrototypeServiceError) as error:
            await service.recover_runtime_session(
                session_id=runtime.state.session.id,
                client_request_id=fixture_id("runtime-version-recovery"),
            )

        assert error.value.code == "runtime_replay_version_mismatch"
        assert error.value.current_head_sequence_no == 0
        assert error.value.current_state_hash == runtime.state.session.head_state_hash
        assert error.value.current_view_model_hash == runtime.state.session.head_view_model_hash
        assert error.value.runtime_core_bundle_hash == unavailable_bundle_hash
        assert error.value.resource_url == (
            f"/api/structured-prototype-runtime-sessions/{runtime.state.session.id}/reset"
        )
        persisted = await store.load_runtime_session(runtime.state.session.id)
        assert persisted is not None
        assert persisted.status == "active"
        assert persisted.runtime_core_bundle_hash == unavailable_bundle_hash
        operation_id = error.value.operation_id
        assert operation_id is not None
        assert [item.status for item in await store.list_operation_events(operation_id)] == [
            "queued",
            "running",
            "failed",
        ]
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_persisted_runtime_event_identity_mismatch_marks_session_corrupt(
    tmp_path: Path,
) -> None:
    store, service = _runtime_service(tmp_path / "console.db", tmp_path / "managed-data")
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("runtime-event-version-document"),
            document=_new_document(),
        )
        runtime = await service.create_runtime_session(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("runtime-event-version-session"),
            scenario_id=fixture_id("scenario-happy-path"),
            recording_kind="studio_preview",
            actor_subject_id=None,
        )
        event_request_id = fixture_id("runtime-event-version-event")
        applied = await service.apply_runtime_event_batch(
            session_id=runtime.state.session.id,
            client_request_id=event_request_id,
            expected_head_sequence_no=0,
            expected_state_hash=runtime.state.session.head_state_hash,
            batch={
                "clientEventId": event_request_id,
                "expectedSequenceNo": 0,
                "events": [
                    {
                        "kind": "switchSimulatedRole",
                        "roleId": fixture_id("role-applicant"),
                    }
                ],
            },
        )
        conn = await store._get_conn()
        await conn.execute(
            "UPDATE prototype_runtime_event_batches SET runtime_core_version = ? WHERE id = ?",
            ("persisted-incompatible-runtime", applied.event_batch_id),
        )
        await conn.commit()

        with pytest.raises(StructuredPrototypeServiceError) as error:
            await service.recover_runtime_session(
                session_id=runtime.state.session.id,
                client_request_id=fixture_id("runtime-event-version-recovery"),
            )

        assert error.value.code == "runtime_replay_version_mismatch"
        persisted = await store.load_runtime_session(runtime.state.session.id)
        assert persisted is not None
        assert persisted.status == "corrupt"
        assert error.value.resource_url == (
            f"/api/structured-prototype-runtime-sessions/{runtime.state.session.id}/reset"
        )
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_runtime_contract_mismatch_exposes_reset_evidence_and_can_rebuild(
    tmp_path: Path,
) -> None:
    store, service = _runtime_service(tmp_path / "console.db", tmp_path / "managed-data")
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("runtime-contract-document"),
            document=_new_document(),
        )
        runtime = await service.create_runtime_session(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("runtime-contract-session"),
            scenario_id=fixture_id("scenario-happy-path"),
            recording_kind="studio_preview",
            actor_subject_id=None,
        )
        conn = await store._get_conn()
        await conn.execute(
            """
            UPDATE prototype_runtime_checkpoints
            SET runtime_state_schema_version = 99
            WHERE id = ?
            """,
            (runtime.state.loaded_checkpoint_id,),
        )
        await conn.commit()

        with pytest.raises(StructuredPrototypeServiceError) as error:
            await service.recover_runtime_session(
                session_id=runtime.state.session.id,
                client_request_id=fixture_id("runtime-contract-recovery"),
            )

        assert error.value.code == "runtime_replay_contract_unsupported"
        assert error.value.current_head_sequence_no == 0
        assert error.value.current_state_hash == runtime.state.session.head_state_hash
        assert error.value.current_view_model_hash == runtime.state.session.head_view_model_hash
        assert error.value.runtime_core_bundle_hash == (
            runtime.state.session.runtime_core_bundle_hash
        )
        assert error.value.resource_url == (
            f"/api/structured-prototype-runtime-sessions/{runtime.state.session.id}/reset"
        )
        persisted = await store.load_runtime_session(runtime.state.session.id)
        assert persisted is not None
        assert persisted.status == "active"
        cause_operation_id = error.value.operation_id
        assert cause_operation_id is not None
        rebuilt = await service.reset_runtime_session(
            session_id=persisted.id,
            client_request_id=fixture_id("runtime-contract-reset"),
            cause_operation_id=cause_operation_id,
            expected_old_head_sequence_no=persisted.head_sequence_no,
            expected_old_state_hash=persisted.head_state_hash,
            expected_old_view_model_hash=persisted.head_view_model_hash,
            expected_old_runtime_core_bundle_hash=persisted.runtime_core_bundle_hash,
            target_draft_id=created.state.draft.id,
            expected_target_head_sequence_no=created.state.draft.head_sequence_no,
            expected_target_document_hash=created.state.draft.head_document_hash,
            scenario_id=fixture_id("scenario-happy-path"),
        )
        assert rebuilt.state.session.replaces_session_id == persisted.id
        reset_operation = await store.load_operation(rebuilt.operation_id)
        assert reset_operation is not None
        assert reset_operation.parent_operation_id == cause_operation_id
        descriptor = await store.load_object("project-1", rebuilt.reset_manifest_hash)
        assert descriptor is not None
        manifest = json.loads(
            PrototypeObjectStore(tmp_path / "managed-data").read_canonical_bytes(descriptor)
        )
        assert manifest["causeOperationId"] == cause_operation_id
        assert manifest["operation"]["parentOperationId"] == cause_operation_id
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_runtime_session_reset_rejects_cross_project_failed_cause_before_operation(
    tmp_path: Path,
) -> None:
    store, service = _runtime_service(tmp_path / "console.db", tmp_path / "managed-data")
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("runtime-reset-cross-project-document"),
            document=_new_document(),
        )
        runtime = await service.create_runtime_session(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("runtime-reset-cross-project-session"),
            scenario_id=fixture_id("scenario-happy-path"),
            recording_kind="studio_preview",
            actor_subject_id=None,
        )
        cause = await _persist_runtime_replay_cause(
            store,
            label="runtime-reset-cross-project-cause",
            project_id="project-2",
            session_id=runtime.state.session.id,
            status="failed",
        )
        reset_request_id = fixture_id("runtime-reset-cross-project-request")

        with pytest.raises(StructuredPrototypeServiceError) as error:
            await service.reset_runtime_session(
                session_id=runtime.state.session.id,
                client_request_id=reset_request_id,
                cause_operation_id=cause.id,
                expected_old_head_sequence_no=runtime.state.session.head_sequence_no,
                expected_old_state_hash=runtime.state.session.head_state_hash,
                expected_old_view_model_hash=runtime.state.session.head_view_model_hash,
                expected_old_runtime_core_bundle_hash=(
                    runtime.state.session.runtime_core_bundle_hash
                ),
                target_draft_id=created.state.draft.id,
                expected_target_head_sequence_no=created.state.draft.head_sequence_no,
                expected_target_document_hash=created.state.draft.head_document_hash,
                scenario_id=fixture_id("scenario-happy-path"),
            )

        assert error.value.code == "runtime_reset_cause_invalid"
        assert error.value.operation_id is None
        assert (
            await store.load_operation_by_request(
                "project-1",
                "reset_runtime_session",
                reset_request_id,
            )
            is None
        )
        persisted = await store.load_runtime_session(runtime.state.session.id)
        assert persisted is not None
        assert persisted.status == "active"
    finally:
        await store.close()


@pytest.mark.parametrize("cause_status", ["running", "succeeded"])
@pytest.mark.asyncio
async def test_runtime_session_reset_rejects_non_failed_replay_cause_before_operation(
    tmp_path: Path,
    cause_status: Literal["running", "succeeded"],
) -> None:
    store, service = _runtime_service(tmp_path / "console.db", tmp_path / "managed-data")
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id(f"runtime-reset-{cause_status}-cause-document"),
            document=_new_document(),
        )
        runtime = await service.create_runtime_session(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id(f"runtime-reset-{cause_status}-cause-session"),
            scenario_id=fixture_id("scenario-happy-path"),
            recording_kind="studio_preview",
            actor_subject_id=None,
        )
        cause = await _persist_runtime_replay_cause(
            store,
            label=f"runtime-reset-{cause_status}-cause",
            project_id="project-1",
            session_id=runtime.state.session.id,
            status=cause_status,
        )
        reset_request_id = fixture_id(f"runtime-reset-{cause_status}-cause-request")

        with pytest.raises(StructuredPrototypeServiceError) as error:
            await service.reset_runtime_session(
                session_id=runtime.state.session.id,
                client_request_id=reset_request_id,
                cause_operation_id=cause.id,
                expected_old_head_sequence_no=runtime.state.session.head_sequence_no,
                expected_old_state_hash=runtime.state.session.head_state_hash,
                expected_old_view_model_hash=runtime.state.session.head_view_model_hash,
                expected_old_runtime_core_bundle_hash=(
                    runtime.state.session.runtime_core_bundle_hash
                ),
                target_draft_id=created.state.draft.id,
                expected_target_head_sequence_no=created.state.draft.head_sequence_no,
                expected_target_document_hash=created.state.draft.head_document_hash,
                scenario_id=fixture_id("scenario-happy-path"),
            )

        assert error.value.code == "runtime_reset_cause_invalid"
        assert error.value.operation_id is None
        assert (
            await store.load_operation_by_request(
                "project-1",
                "reset_runtime_session",
                reset_request_id,
            )
            is None
        )
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_runtime_session_reset_accepts_failed_reset_for_same_old_session_as_parent(
    tmp_path: Path,
) -> None:
    object_root = tmp_path / "managed-data"
    store, service = _runtime_service(tmp_path / "console.db", object_root)
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("runtime-reset-failed-parent-document"),
            document=_new_document(),
        )
        runtime = await service.create_runtime_session(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("runtime-reset-failed-parent-session"),
            scenario_id=fixture_id("scenario-happy-path"),
            recording_kind="studio_preview",
            actor_subject_id=None,
        )

        with pytest.raises(StructuredPrototypeServiceError) as first_error:
            await service.reset_runtime_session(
                session_id=runtime.state.session.id,
                client_request_id=fixture_id("runtime-reset-failed-parent-first-request"),
                cause_operation_id=None,
                expected_old_head_sequence_no=runtime.state.session.head_sequence_no,
                expected_old_state_hash=runtime.state.session.head_state_hash,
                expected_old_view_model_hash=runtime.state.session.head_view_model_hash,
                expected_old_runtime_core_bundle_hash=(
                    runtime.state.session.runtime_core_bundle_hash
                ),
                target_draft_id=created.state.draft.id,
                expected_target_head_sequence_no=created.state.draft.head_sequence_no + 1,
                expected_target_document_hash=created.state.draft.head_document_hash,
                scenario_id=fixture_id("scenario-happy-path"),
            )

        assert first_error.value.code == "draft_conflict"
        failed_operation_id = first_error.value.operation_id
        assert failed_operation_id is not None
        failed_operation = await store.load_operation(failed_operation_id)
        assert failed_operation is not None
        assert failed_operation.operation_kind == "reset_runtime_session"
        assert failed_operation.project_id == "project-1"
        assert failed_operation.status == "failed"
        assert [
            event.status for event in await store.list_operation_events(failed_operation.id)
        ] == ["queued", "running", "failed"]

        rebuilt = await service.reset_runtime_session(
            session_id=runtime.state.session.id,
            client_request_id=fixture_id("runtime-reset-failed-parent-second-request"),
            cause_operation_id=failed_operation.id,
            expected_old_head_sequence_no=runtime.state.session.head_sequence_no,
            expected_old_state_hash=runtime.state.session.head_state_hash,
            expected_old_view_model_hash=runtime.state.session.head_view_model_hash,
            expected_old_runtime_core_bundle_hash=(runtime.state.session.runtime_core_bundle_hash),
            target_draft_id=created.state.draft.id,
            expected_target_head_sequence_no=created.state.draft.head_sequence_no,
            expected_target_document_hash=created.state.draft.head_document_hash,
            scenario_id=fixture_id("scenario-happy-path"),
        )

        reset_operation = await store.load_operation(rebuilt.operation_id)
        assert reset_operation is not None
        assert reset_operation.status == "succeeded"
        assert reset_operation.parent_operation_id == failed_operation.id
        assert rebuilt.state.session.replaces_session_id == runtime.state.session.id
        descriptor = await store.load_object("project-1", rebuilt.reset_manifest_hash)
        assert descriptor is not None
        manifest = json.loads(PrototypeObjectStore(object_root).read_canonical_bytes(descriptor))
        assert manifest["causeOperationId"] == failed_operation.id
        assert manifest["operation"]["parentOperationId"] == failed_operation.id
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_runtime_session_reset_rebuilds_without_replaying_old_events_and_is_idempotent(
    tmp_path: Path,
) -> None:
    store = AsyncStructuredPrototypeStore(tmp_path / "console.db")
    object_store = PrototypeObjectStore(tmp_path / "managed-data")
    worker = _RuntimeWorkerSpy()
    service = StructuredPrototypeService(
        store=store,
        object_store=object_store,
        runtime_worker=worker,
        clock=lambda: FIXED_NOW,
    )
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("runtime-reset-document"),
            document=_new_document(),
        )
        runtime = await service.create_runtime_session(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("runtime-reset-old-session"),
            scenario_id=fixture_id("scenario-happy-path"),
            recording_kind="studio_preview",
            actor_subject_id="product-manager-1",
        )
        event_request_id = fixture_id("runtime-reset-old-event")
        applied = await service.apply_runtime_event_batch(
            session_id=runtime.state.session.id,
            client_request_id=event_request_id,
            expected_head_sequence_no=0,
            expected_state_hash=runtime.state.session.head_state_hash,
            batch={
                "clientEventId": event_request_id,
                "expectedSequenceNo": 0,
                "events": [
                    {
                        "kind": "switchSimulatedRole",
                        "roleId": fixture_id("role-applicant"),
                    }
                ],
            },
        )
        conn = await store._get_conn()
        old_events_before = await (
            await conn.execute(
                """
                SELECT id, client_event_id, events_json, event_batch_hash,
                       base_state_hash, result_state_hash, result_view_model_hash
                FROM prototype_runtime_event_batches
                WHERE session_id = ? ORDER BY result_sequence_no
                """,
                (runtime.state.session.id,),
            )
        ).fetchall()
        old_checkpoints_before = await (
            await conn.execute(
                """
                SELECT id, checkpoint_sequence_no, state_object_hash, state_hash,
                       view_model_hash, created_by_operation_id
                FROM prototype_runtime_checkpoints
                WHERE session_id = ? ORDER BY checkpoint_sequence_no
                """,
                (runtime.state.session.id,),
            )
        ).fetchall()
        worker.replayed_session_ids.clear()
        reset_request_id = fixture_id("runtime-reset-request")
        reset = await service.reset_runtime_session(
            session_id=runtime.state.session.id,
            client_request_id=reset_request_id,
            cause_operation_id=None,
            expected_old_head_sequence_no=applied.state.session.head_sequence_no,
            expected_old_state_hash=applied.state.session.head_state_hash,
            expected_old_view_model_hash=applied.state.session.head_view_model_hash,
            expected_old_runtime_core_bundle_hash=(applied.state.session.runtime_core_bundle_hash),
            target_draft_id=created.state.draft.id,
            expected_target_head_sequence_no=created.state.draft.head_sequence_no,
            expected_target_document_hash=created.state.draft.head_document_hash,
            scenario_id=fixture_id("scenario-happy-path"),
        )
        assert worker.replayed_session_ids == []
        assert worker.initialized_session_ids[-1] == reset.state.session.id
        retried = await service.reset_runtime_session(
            session_id=runtime.state.session.id,
            client_request_id=reset_request_id,
            cause_operation_id=None,
            expected_old_head_sequence_no=applied.state.session.head_sequence_no,
            expected_old_state_hash=applied.state.session.head_state_hash,
            expected_old_view_model_hash=applied.state.session.head_view_model_hash,
            expected_old_runtime_core_bundle_hash=(applied.state.session.runtime_core_bundle_hash),
            target_draft_id=created.state.draft.id,
            expected_target_head_sequence_no=created.state.draft.head_sequence_no,
            expected_target_document_hash=created.state.draft.head_document_hash,
            scenario_id=fixture_id("scenario-happy-path"),
        )
        assert worker.replayed_session_ids == [reset.state.session.id]
        with pytest.raises(StructuredPrototypeServiceError) as second_reset_error:
            await service.reset_runtime_session(
                session_id=runtime.state.session.id,
                client_request_id=fixture_id("runtime-reset-second-request"),
                cause_operation_id=None,
                expected_old_head_sequence_no=applied.state.session.head_sequence_no,
                expected_old_state_hash=applied.state.session.head_state_hash,
                expected_old_view_model_hash=applied.state.session.head_view_model_hash,
                expected_old_runtime_core_bundle_hash=(
                    applied.state.session.runtime_core_bundle_hash
                ),
                target_draft_id=created.state.draft.id,
                expected_target_head_sequence_no=created.state.draft.head_sequence_no,
                expected_target_document_hash=created.state.draft.head_document_hash,
                scenario_id=fixture_id("scenario-happy-path"),
            )

        assert reset.state.session.id != runtime.state.session.id
        assert reset.state.session.replaces_session_id == runtime.state.session.id
        assert reset.state.session.head_sequence_no == 0
        assert reset.state.session.pinned_document_object_hash == (
            created.state.draft.head_document_hash
        )
        assert reset.state.replayed_event_batch_ids == ()
        assert retried.operation_id == reset.operation_id
        assert retried.reset_manifest_hash == reset.reset_manifest_hash
        assert retried.state.session.id == reset.state.session.id
        assert second_reset_error.value.code == "runtime_session_conflict"
        old_persisted = await store.load_runtime_session(runtime.state.session.id)
        assert old_persisted is not None
        assert old_persisted.status == "completed"
        operation = await store.load_operation(reset.operation_id)
        assert operation is not None
        assert operation.status == "succeeded"
        assert operation.resource_kind == "runtime_session"
        assert operation.resource_id == reset.state.session.id
        assert operation.result_manifest_hash != reset.reset_manifest_hash
        operation_detail = await service.get_operation_detail(reset.operation_id)
        assert operation_detail.replay_manifest is not None
        assert operation_detail.replay_manifest.runtime_session_id == reset.state.session.id
        assert reset.reset_manifest_hash in (
            operation_detail.replay_manifest.ordered_input_object_hashes
        )
        descriptor = await store.load_object("project-1", reset.reset_manifest_hash)
        assert descriptor is not None
        manifest = json.loads(object_store.read_canonical_bytes(descriptor))
        assert manifest["payloadType"] == "runtime_session_reset_manifest"
        assert manifest["oldSession"]["head"]["sequenceNo"] == 1
        assert manifest["newSession"]["replacesSessionId"] == runtime.state.session.id
        assert manifest["newSession"]["scenarioId"] == fixture_id("scenario-happy-path")
        assert manifest["eventReplayPolicy"] == "none"
        assert manifest["causeOperationId"] is None
        assert manifest["operation"]["parentOperationId"] is None
        new_event_count = await (
            await conn.execute(
                "SELECT COUNT(*) FROM prototype_runtime_event_batches WHERE session_id = ?",
                (reset.state.session.id,),
            )
        ).fetchone()
        reset_ref_count = await (
            await conn.execute(
                """
                SELECT COUNT(*)
                FROM prototype_object_references
                WHERE content_hash = ? AND payload_type = 'runtime_session_reset_manifest'
                """,
                (reset.reset_manifest_hash,),
            )
        ).fetchone()
        old_events_after = await (
            await conn.execute(
                """
                SELECT id, client_event_id, events_json, event_batch_hash,
                       base_state_hash, result_state_hash, result_view_model_hash
                FROM prototype_runtime_event_batches
                WHERE session_id = ? ORDER BY result_sequence_no
                """,
                (runtime.state.session.id,),
            )
        ).fetchall()
        old_checkpoints_after = await (
            await conn.execute(
                """
                SELECT id, checkpoint_sequence_no, state_object_hash, state_hash,
                       view_model_hash, created_by_operation_id
                FROM prototype_runtime_checkpoints
                WHERE session_id = ? ORDER BY checkpoint_sequence_no
                """,
                (runtime.state.session.id,),
            )
        ).fetchall()
        session_count = await (
            await conn.execute("SELECT COUNT(*) FROM prototype_runtime_sessions")
        ).fetchone()
        assert new_event_count == (0,)
        assert reset_ref_count == (2,)
        assert old_events_after == old_events_before
        assert old_checkpoints_after == old_checkpoints_before
        assert session_count == (2,)
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_runtime_session_reset_rejects_old_and_target_cas_without_partial_session(
    tmp_path: Path,
) -> None:
    store, service = _runtime_service(tmp_path / "console.db", tmp_path / "managed-data")
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("runtime-reset-cas-document"),
            document=_new_document(),
        )
        runtime = await service.create_runtime_session(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("runtime-reset-cas-session"),
            scenario_id=fixture_id("scenario-happy-path"),
            recording_kind="studio_preview",
            actor_subject_id=None,
        )
        with pytest.raises(StructuredPrototypeServiceError) as old_error:
            await service.reset_runtime_session(
                session_id=runtime.state.session.id,
                client_request_id=fixture_id("runtime-reset-old-cas-conflict"),
                cause_operation_id=None,
                expected_old_head_sequence_no=0,
                expected_old_state_hash="sha256:" + "f" * 64,
                expected_old_view_model_hash=runtime.state.session.head_view_model_hash,
                expected_old_runtime_core_bundle_hash=(
                    runtime.state.session.runtime_core_bundle_hash
                ),
                target_draft_id=created.state.draft.id,
                expected_target_head_sequence_no=0,
                expected_target_document_hash=created.state.draft.head_document_hash,
                scenario_id=fixture_id("scenario-happy-path"),
            )
        with pytest.raises(StructuredPrototypeServiceError) as target_error:
            await service.reset_runtime_session(
                session_id=runtime.state.session.id,
                client_request_id=fixture_id("runtime-reset-target-cas-conflict"),
                cause_operation_id=None,
                expected_old_head_sequence_no=0,
                expected_old_state_hash=runtime.state.session.head_state_hash,
                expected_old_view_model_hash=runtime.state.session.head_view_model_hash,
                expected_old_runtime_core_bundle_hash=(
                    runtime.state.session.runtime_core_bundle_hash
                ),
                target_draft_id=created.state.draft.id,
                expected_target_head_sequence_no=1,
                expected_target_document_hash=created.state.draft.head_document_hash,
                scenario_id=fixture_id("scenario-happy-path"),
            )

        assert old_error.value.code == "runtime_session_conflict"
        assert target_error.value.code == "draft_conflict"
        persisted = await store.load_runtime_session(runtime.state.session.id)
        assert persisted is not None
        assert persisted.status == "active"
        conn = await store._get_conn()
        count = await (
            await conn.execute("SELECT COUNT(*) FROM prototype_runtime_sessions")
        ).fetchone()
        assert count == (1,)
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_runtime_session_reset_rolls_back_when_old_status_drifts_during_initialize(
    tmp_path: Path,
) -> None:
    store = AsyncStructuredPrototypeStore(tmp_path / "console.db")
    service = StructuredPrototypeService(
        store=store,
        object_store=PrototypeObjectStore(tmp_path / "managed-data"),
        runtime_worker=_RuntimeWorkerStatusDrift(store),
        clock=lambda: FIXED_NOW,
    )
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("runtime-reset-status-drift-document"),
            document=_new_document(),
        )
        runtime = await service.create_runtime_session(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("runtime-reset-status-drift-session"),
            scenario_id=fixture_id("scenario-happy-path"),
            recording_kind="studio_preview",
            actor_subject_id=None,
        )

        with pytest.raises(StructuredPrototypeServiceError) as error:
            await service.reset_runtime_session(
                session_id=runtime.state.session.id,
                client_request_id=fixture_id("runtime-reset-status-drift-request"),
                cause_operation_id=None,
                expected_old_head_sequence_no=runtime.state.session.head_sequence_no,
                expected_old_state_hash=runtime.state.session.head_state_hash,
                expected_old_view_model_hash=runtime.state.session.head_view_model_hash,
                expected_old_runtime_core_bundle_hash=(
                    runtime.state.session.runtime_core_bundle_hash
                ),
                target_draft_id=created.state.draft.id,
                expected_target_head_sequence_no=created.state.draft.head_sequence_no,
                expected_target_document_hash=created.state.draft.head_document_hash,
                scenario_id=fixture_id("scenario-happy-path"),
            )

        assert error.value.code == "runtime_session_conflict"
        old_persisted = await store.load_runtime_session(runtime.state.session.id)
        assert old_persisted is not None
        assert old_persisted.status == "corrupt"
        assert old_persisted.latest_checkpoint_id is None
        conn = await store._get_conn()
        session_count = await (
            await conn.execute("SELECT COUNT(*) FROM prototype_runtime_sessions")
        ).fetchone()
        reset_ref_count = await (
            await conn.execute(
                """
                SELECT COUNT(*) FROM prototype_object_references
                WHERE payload_type = 'runtime_session_reset_manifest'
                """
            )
        ).fetchone()
        assert session_count == (1,)
        assert reset_ref_count == (0,)
        assert error.value.operation_id is not None
        operation = await store.load_operation(error.value.operation_id)
        assert operation is not None
        assert operation.status == "failed"
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_runtime_session_reset_rejects_recorded_but_rebuilds_corrupt_missing_checkpoint(
    tmp_path: Path,
) -> None:
    store, service = _runtime_service(tmp_path / "console.db", tmp_path / "managed-data")
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("runtime-reset-eligibility-document"),
            document=_new_document(),
        )
        recorded = await service.create_runtime_session(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("runtime-reset-recorded-session"),
            scenario_id=fixture_id("scenario-happy-path"),
            recording_kind="recorded_review",
            actor_subject_id=None,
        )
        with pytest.raises(StructuredPrototypeServiceError) as recorded_error:
            await service.reset_runtime_session(
                session_id=recorded.state.session.id,
                client_request_id=fixture_id("runtime-reset-recorded-request"),
                cause_operation_id=None,
                expected_old_head_sequence_no=0,
                expected_old_state_hash=recorded.state.session.head_state_hash,
                expected_old_view_model_hash=recorded.state.session.head_view_model_hash,
                expected_old_runtime_core_bundle_hash=(
                    recorded.state.session.runtime_core_bundle_hash
                ),
                target_draft_id=created.state.draft.id,
                expected_target_head_sequence_no=0,
                expected_target_document_hash=created.state.draft.head_document_hash,
                scenario_id=fixture_id("scenario-happy-path"),
            )
        assert recorded_error.value.code == "runtime_session_reset_not_allowed"

        conn = await store._get_conn()
        await conn.execute(
            """
            UPDATE prototype_runtime_sessions
            SET recording_kind = 'studio_preview', status = 'corrupt',
                latest_checkpoint_id = NULL, completed_at = ?
            WHERE id = ?
            """,
            (FIXED_NOW.isoformat(), recorded.state.session.id),
        )
        await conn.commit()
        corrupt = await store.load_runtime_session(recorded.state.session.id)
        assert corrupt is not None
        with pytest.raises(StructuredPrototypeServiceError) as corrupt_error:
            await service.recover_runtime_session(
                session_id=corrupt.id,
                client_request_id=fixture_id("runtime-reset-corrupt-recovery"),
            )
        assert corrupt_error.value.code == "runtime_session_corrupt"
        assert corrupt_error.value.current_head_sequence_no == corrupt.head_sequence_no
        assert corrupt_error.value.current_state_hash == corrupt.head_state_hash
        assert corrupt_error.value.current_view_model_hash == corrupt.head_view_model_hash
        assert corrupt_error.value.runtime_core_bundle_hash == corrupt.runtime_core_bundle_hash
        assert corrupt_error.value.resource_url == (
            f"/api/structured-prototype-runtime-sessions/{corrupt.id}/reset"
        )
        rebuilt = await service.reset_runtime_session(
            session_id=corrupt.id,
            client_request_id=fixture_id("runtime-reset-corrupt-request"),
            cause_operation_id=None,
            expected_old_head_sequence_no=corrupt.head_sequence_no,
            expected_old_state_hash=corrupt.head_state_hash,
            expected_old_view_model_hash=corrupt.head_view_model_hash,
            expected_old_runtime_core_bundle_hash=corrupt.runtime_core_bundle_hash,
            target_draft_id=created.state.draft.id,
            expected_target_head_sequence_no=0,
            expected_target_document_hash=created.state.draft.head_document_hash,
            scenario_id=fixture_id("scenario-happy-path"),
        )
        descriptor = await store.load_object("project-1", rebuilt.reset_manifest_hash)
        assert descriptor is not None
        manifest = json.loads(
            PrototypeObjectStore(tmp_path / "managed-data").read_canonical_bytes(descriptor)
        )
        assert rebuilt.state.session.replaces_session_id == corrupt.id
        assert manifest["resetReason"] == "runtime_session_corrupt"
        assert manifest["oldSession"]["latestCheckpointId"] is None
        assert manifest["oldSession"]["checkpointInspectionPolicy"] == "none"
        old_persisted = await store.load_runtime_session(corrupt.id)
        assert old_persisted is not None
        assert old_persisted.status == "corrupt"
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_runtime_worker_unavailable_records_failed_operation(tmp_path: Path) -> None:
    store, service = _service(tmp_path / "console.db", tmp_path / "managed-data")
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("runtime-unavailable-document"),
            document=_new_document(),
        )

        with pytest.raises(StructuredPrototypeServiceError) as error:
            await service.create_runtime_session(
                draft_id=created.state.draft.id,
                client_request_id=fixture_id("runtime-unavailable-session"),
                scenario_id=fixture_id("scenario-happy-path"),
                recording_kind="studio_preview",
                actor_subject_id=None,
            )

        assert error.value.code == "runtime_worker_unavailable"
        operation_id = error.value.operation_id
        assert operation_id is not None
        assert [item.status for item in await store.list_operation_events(operation_id)] == [
            "queued",
            "running",
            "failed",
        ]
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_publish_is_idempotent_observable_and_serves_verified_artifact(
    tmp_path: Path,
) -> None:
    store, service, _ = _publication_service(
        tmp_path / "console.db",
        tmp_path / "objects",
        tmp_path / "managed-data",
    )
    request_id = fixture_id("publication-success")
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("publication-document"),
            document=_new_document(),
        )
        first = await service.publish_draft(
            draft_id=created.state.draft.id,
            client_request_id=request_id,
            expected_head_sequence_no=0,
            expected_document_hash=created.state.draft.head_document_hash,
        )
        retried = await service.publish_draft(
            draft_id=created.state.draft.id,
            client_request_id=request_id,
            expected_head_sequence_no=0,
            expected_document_hash=created.state.draft.head_document_hash,
        )
        current = await service.get_published_prototype(created.state.document_record.id)
        index = await service.read_published_file(
            document_id=created.state.document_record.id,
            revision_no=first.publication.revision_no,
            artifact_id=first.publication.artifact_id,
            relative_path="index.html",
        )

        assert retried.operation_id == first.operation_id
        assert retried.publication == first.publication
        assert retried.state.draft.id == first.state.draft.id
        assert first.publication.revision_no == 1
        assert first.state.draft.id != created.state.draft.id
        assert first.state.draft.base_revision_no == 1
        assert first.state.draft.head_sequence_no == 0
        assert current == first.publication
        assert b'<script src="./runtime.js" defer></script>' in index.content
        assert [
            event.status for event in await store.list_operation_events(first.operation_id)
        ] == [
            "queued",
            "running",
            "succeeded",
            "running",
            "succeeded",
            "running",
            "succeeded",
        ]
        closed = await store.load_draft(created.state.draft.id)
        assert closed is not None
        assert closed.status == "closed"
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_render_failure_restores_draft_and_preserves_previous_publication(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "console.db"
    object_root = tmp_path / "objects"
    artifact_root = tmp_path / "managed-data"
    store, service, real_renderer = _publication_service(db_path, object_root, artifact_root)
    try:
        created = await service.create_document(
            project_id="project-1",
            client_request_id=fixture_id("publication-failure-document"),
            document=_new_document(),
        )
        first = await service.publish_draft(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("publication-before-failure"),
            expected_head_sequence_no=0,
            expected_document_hash=created.state.draft.head_document_hash,
        )
        edited = await service.apply_command_batch(
            draft_id=first.state.draft.id,
            client_request_id=fixture_id("publication-edit-before-failure"),
            expected_head_sequence_no=0,
            expected_document_hash=first.state.draft.head_document_hash,
            batch=_text_insert_batch(),
        )
        failing_service = StructuredPrototypeService(
            store=store,
            object_store=PrototypeObjectStore(object_root),
            runtime_worker=PrototypeRuntimeWorker(),
            renderer_worker=_FailingRenderer(real_renderer.identity),
            artifact_store=PrototypeRenderArtifactStore(artifact_root),
            clock=lambda: FIXED_NOW,
        )

        with pytest.raises(StructuredPrototypeServiceError) as error:
            await failing_service.publish_draft(
                draft_id=edited.state.draft.id,
                client_request_id=fixture_id("publication-render-failure"),
                expected_head_sequence_no=edited.state.draft.head_sequence_no,
                expected_document_hash=edited.state.draft.head_document_hash,
            )

        assert error.value.code == "renderer_intentional_failure"
        restored = await store.load_draft(edited.state.draft.id)
        assert restored is not None
        assert restored.status == "active"
        assert restored.head_document_hash == edited.state.draft.head_document_hash
        current = await service.get_published_prototype(created.state.document_record.id)
        assert current == first.publication
        assert error.value.operation_id is not None
        run = await store.load_render_run_by_operation(error.value.operation_id)
        assert run is not None
        assert run.status == "failed"
        assert run.error_code == "renderer_intentional_failure"
        events = await store.list_operation_events(error.value.operation_id)
        assert events[-1].status == "failed"
        assert events[-1].error_code == "renderer_intentional_failure"
        assert events[-1].evidence_hash is not None
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_startup_recovery_interrupts_render_and_reactivates_publishing_draft(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "console.db"
    object_root = tmp_path / "objects"
    artifact_root = tmp_path / "managed-data"
    real_renderer = PrototypeRendererWorker()
    blocking_renderer = _BlockingRenderer(real_renderer.identity)
    store, service, _ = _publication_service(
        db_path,
        object_root,
        artifact_root,
        renderer=blocking_renderer,
    )
    created = await service.create_document(
        project_id="project-1",
        client_request_id=fixture_id("publication-interrupted-document"),
        document=_new_document(),
    )
    publish_task = asyncio.create_task(
        service.publish_draft(
            draft_id=created.state.draft.id,
            client_request_id=fixture_id("publication-interrupted-render"),
            expected_head_sequence_no=0,
            expected_document_hash=created.state.draft.head_document_hash,
        )
    )
    await asyncio.wait_for(blocking_renderer.started.wait(), timeout=5)
    publishing = await store.load_draft(created.state.draft.id)
    assert publishing is not None
    assert publishing.status == "publishing"
    publish_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await publish_task
    await store.close()

    reopened_store = AsyncStructuredPrototypeStore(db_path)
    recovery_service = StructuredPrototypeService(
        store=reopened_store,
        object_store=PrototypeObjectStore(object_root),
        clock=lambda: FIXED_NOW,
    )
    try:
        recovered_count = await recovery_service.recover_interrupted_publications()
        restored = await reopened_store.load_draft(created.state.draft.id)
        conn = await reopened_store._get_conn()
        run_row = await (
            await conn.execute("SELECT status, error_code, operation_id FROM prototype_render_runs")
        ).fetchone()

        assert recovered_count == 1
        assert restored is not None
        assert restored.status == "active"
        assert run_row is not None
        assert tuple(run_row[:2]) == ("interrupted", "service_restart")
        operation = await reopened_store.load_operation(str(run_row[2]))
        assert operation is not None
        assert operation.status == "interrupted"
        assert operation.error_code == "service_restart"
        assert (
            await recovery_service.get_published_prototype(created.state.document_record.id) is None
        )
    finally:
        await reopened_store.close()
