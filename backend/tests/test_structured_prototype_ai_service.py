from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import aiosqlite
import pytest
from structured_prototype_fixtures import fixture_id, procurement_document_payload

from app.adapters.prototype_object_store import PrototypeObjectStore
from app.adapters.prototype_render_artifact_store import PrototypeRenderArtifactStore
from app.adapters.prototype_renderer_worker import PrototypeRendererWorker
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
    NewPrototypeDocumentV1,
    StackNodeV1,
    TextNodeV1,
)
from app.application.structured_prototype_service import StructuredPrototypeService
from app.domain.models import Project

FIXED_NOW = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)


def _new_document() -> NewPrototypeDocumentV1:
    payload = procurement_document_payload()
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


async def _fixture(
    tmp_path: Path,
    outcome: PrototypeAssistantOutcomeV1,
    runtime: PrototypeUiEngineerExecution | None = None,
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
        document=_new_document(),
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
        renderer_worker=renderer,
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
        assert len(bundle.command_batches) == 0
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
