from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from structured_prototype_fixtures import fixture_id, procurement_document_payload

from app.adapters.prototype_object_store import PrototypeObjectStore
from app.adapters.prototype_render_artifact_store import PrototypeRenderArtifactStore
from app.adapters.prototype_renderer_worker import PrototypeRendererWorker
from app.adapters.structured_prototype_store import AsyncStructuredPrototypeStore
from app.application.external_prototype_agent_contracts import (
    GetActiveDesignContextV1,
    GetDocumentSliceV1,
    GetExternalProposalStatusV1,
    SubmitExternalCommandProposalV1,
)
from app.application.structured_prototype_ai_runtime import (
    PrototypeUiEngineerTaskRequest,
    PrototypeUiEngineerTaskResult,
)
from app.application.structured_prototype_ai_service import StructuredPrototypeAiService
from app.application.structured_prototype_contracts import (
    GridNodeV1,
    NewPrototypeDocumentV1,
    StackNodeV1,
    TextNodeV1,
)
from app.application.structured_prototype_external_collaboration import (
    StructuredPrototypeExternalCollaboration,
)
from app.application.structured_prototype_service import StructuredPrototypeService
from app.domain.external_prototype_agent import ExternalAgentPairingRecord
from app.domain.models import Project

NOW = datetime(2026, 7, 14, 8, 0, tzinfo=UTC)


class _ProjectStore:
    def __init__(self, project: Project) -> None:
        self._project = project

    async def load_project(self, project_id: str) -> Project | None:
        return self._project if project_id == self._project.id else None


class _RuntimeMustNotRun:
    async def execute(
        self,
        request: PrototypeUiEngineerTaskRequest,
    ) -> PrototypeUiEngineerTaskResult:
        del request
        raise AssertionError("external proposals must not invoke the built-in Claude runtime")


def _new_document() -> NewPrototypeDocumentV1:
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
    title = children.pop(0)
    children.insert(
        0,
        {
            "id": fixture_id("external-title-grid"),
            "name": "列表标题网格",
            "visibility": "visible",
            "layoutItem": {
                "width": {"unit": "auto", "value": None},
                "minWidth": None,
                "maxWidth": None,
                "height": {"unit": "auto", "value": None},
                "minHeight": None,
                "maxHeight": None,
                "grow": 0,
                "shrink": 1,
                "alignSelf": "stretch",
            },
            "responsive": [],
            "type": "Grid",
            "columns": 1,
            "gap": 8,
            "padding": {"top": 0, "right": 0, "bottom": 0, "left": 0},
            "columnOverrides": [{"minWidth": 768, "columns": 2}],
            "children": [title],
        },
    )
    return NewPrototypeDocumentV1.model_validate(
        payload,
        strict=True,
        by_alias=True,
        by_name=False,
    )


def _pairing(document_id: str) -> ExternalAgentPairingRecord:
    return ExternalAgentPairingRecord(
        id="external-agent-pairing-test",
        client_request_id=fixture_id("external-pairing-request"),
        project_id="project-1",
        document_id=document_id,
        agent_kind="codex",
        token_digest="sha256:" + "a" * 64,
        permissions=("prototype:propose", "prototype:read"),
        status="active",
        protocol_version=1,
        skill_version="1.0.0",
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
        revoked_at=None,
        last_used_at=None,
    )


@pytest.mark.asyncio
async def test_external_proposal_uses_the_studio_preview_and_apply_pipeline(
    tmp_path: Path,
) -> None:
    store = AsyncStructuredPrototypeStore(tmp_path / "console.db")
    object_store = PrototypeObjectStore(tmp_path / "managed")
    renderer = PrototypeRendererWorker()
    artifact_store = PrototypeRenderArtifactStore(tmp_path / "managed")
    structured_service = StructuredPrototypeService(
        store=store,
        object_store=object_store,
        renderer_worker=renderer,
        artifact_store=artifact_store,
        clock=lambda: NOW,
    )
    created = await structured_service.create_document(
        project_id="project-1",
        client_request_id=fixture_id("external-create-document"),
        document=_new_document(),
    )
    ai_service = StructuredPrototypeAiService(
        store=store,
        project_store=_ProjectStore(
            Project(
                id="project-1",
                name="Procurement",
                repo_path=str(tmp_path),
                default_branch="main",
            )
        ),
        object_store=object_store,
        structured_service=structured_service,
        runtime=_RuntimeMustNotRun(),
        renderer_worker=renderer,
        artifact_store=artifact_store,
        clock=lambda: NOW,
    )
    collaboration = StructuredPrototypeExternalCollaboration(
        store=store,
        structured_service=structured_service,
        ai_service=ai_service,
    )
    pairing = _pairing(created.state.document_record.id)
    title_id = fixture_id("title-list")
    draft = created.state.draft
    request_hash = "sha256:" + "b" * 64
    submission = SubmitExternalCommandProposalV1.model_validate(
        {
            "protocolVersion": 1,
            "draftId": draft.id,
            "expectedHeadSequenceNo": draft.head_sequence_no,
            "expectedDocumentHash": draft.head_document_hash,
            "batch": {
                "commandContractVersion": 1,
                "summary": "调整列表标题",
                "commands": [
                    {
                        "kind": "setNodeProperty",
                        "node": {"kind": "existing", "nodeId": title_id},
                        "update": {"kind": "textContent", "content": "全部采购申请"},
                    }
                ],
            },
            "clientRequestId": fixture_id("external-proposal-request"),
            "message": "把列表标题改成全部采购申请",
            "affectedEntityIds": [title_id],
        },
        strict=True,
        by_alias=True,
        by_name=False,
    )
    try:
        await collaboration.assert_pairing_scope(pairing.project_id, pairing.document_id)
        context = await collaboration.get_active_design_context(
            pairing,
            GetActiveDesignContextV1.model_validate(
                {
                    "protocolVersion": 1,
                    "scope": {
                        "pageId": fixture_id("page-list"),
                        "selectedNodeIds": [title_id],
                        "flowId": None,
                        "viewport": "desktop",
                    },
                },
                strict=True,
                by_alias=True,
                by_name=False,
            ),
        )
        assert context.revision.document_hash == draft.head_document_hash
        assert {
            "reorderNavigationItem",
            "addBehaviorRule",
            "replaceBehaviorRule",
            "removeBehaviorRule",
        } <= set(context.supported_command_kinds)
        assert context.context["selectedNodes"]
        command_schema = context.context["commandBatchSchema"]
        assert isinstance(command_schema, dict)
        assert "SetNodePropertyCommandV1" in command_schema["$defs"]
        assert "StackLayoutUpdateV1" in command_schema["$defs"]
        assert "GridLayoutUpdateV1" in command_schema["$defs"]
        assert "FormLayoutUpdateV1" in command_schema["$defs"]
        assert "ResponsiveLayoutUpdateV1" in command_schema["$defs"]
        assert "AddBehaviorRuleCommandV1" in command_schema["$defs"]
        assert "ReplaceBehaviorRuleCommandV1" in command_schema["$defs"]
        assert "RemoveBehaviorRuleCommandV1" in command_schema["$defs"]
        document_slice = await collaboration.get_document_slice(
            pairing,
            GetDocumentSliceV1.model_validate(
                {
                    "protocolVersion": 1,
                    "sliceKind": "selection",
                    "pageId": fixture_id("page-list"),
                    "entityIds": [title_id],
                },
                strict=True,
                by_alias=True,
                by_name=False,
            ),
        )
        assert document_slice.data["entities"]

        validation = await collaboration.validate_command_batch(pairing, submission)
        assert validation.affected_entity_ids == (title_id,)
        receipt = await collaboration.submit_command_proposal(
            pairing,
            submission,
            request_hash,
            origin="external_agent",
        )
        assert receipt.status == "preview_ready"
        run = await ai_service.get_run(receipt.proposal_id)
        assert run.preview_artifact_id is not None
        assert run.replay_manifest_object_hash is not None
        replay_descriptor = await store.load_object(
            pairing.project_id,
            run.replay_manifest_object_hash,
        )
        assert replay_descriptor is not None
        replay = json.loads(object_store.read_canonical_bytes(replay_descriptor))
        assert replay["agentTaskIdentity"]["role"] == "external_prototype_agent"
        assert replay["agentTaskIdentity"]["executor"] == "codex"

        applied = await ai_service.apply(
            run_id=run.id,
            client_request_id=fixture_id("external-apply-request"),
            expected_head_sequence_no=draft.head_sequence_no,
            expected_document_hash=draft.head_document_hash,
        )
        assert applied.run.status == "applied"
        root = applied.draft_result.state.document.pages[0].root
        assert isinstance(root, StackNodeV1)
        title_grid = root.children[0]
        assert isinstance(title_grid, GridNodeV1)
        title = title_grid.children[0]
        assert isinstance(title, TextNodeV1)
        assert title.content == "全部采购申请"
        status = await collaboration.get_proposal_status(
            pairing,
            GetExternalProposalStatusV1.model_validate(
                {"protocolVersion": 1, "proposalId": run.id},
                strict=True,
                by_alias=True,
                by_name=False,
            ),
        )
        assert status.status == "applied"
        assert status.current_revision.head_sequence_no == 1
    finally:
        await store.close()
