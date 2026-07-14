from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from test_structured_prototype_generation_assembler import _create_page_payload

from app.adapters.prototype_object_store import PrototypeObjectStore, canonical_json_bytes
from app.application.prototype_ui_engineer_runner import (
    PrototypeUiEngineerActivity,
    PrototypeUiEngineerActivityCallback,
    PrototypeUiEngineerCompletionCallback,
    PrototypeUiEngineerRunner,
    PrototypeUiEngineerRunnerError,
    PrototypeUiEngineerScopedTaskResult,
)
from app.application.structured_prototype_generation_contracts import (
    GeneratedPageV1,
    GenerationPageEnvelopeV1,
    generation_artifact_payload,
)
from app.application.structured_prototype_generation_mcp import (
    StructuredPrototypeGenerationMcpService,
)
from app.application.structured_prototype_generation_runtime import (
    StructuredPrototypeGenerationRuntime,
    StructuredPrototypeGenerationRuntimeError,
    StructuredPrototypeGenerationTaskRequest,
)
from app.application.worktree_manager import WorktreeError
from app.domain.models import Project


class _SubmittingGenerator:
    def __init__(
        self,
        *,
        root: Path,
        mcp: StructuredPrototypeGenerationMcpService,
        envelope: GenerationPageEnvelopeV1,
        failure: Exception | None = None,
        submit: bool = True,
        submission_payload: dict[str, object] | None = None,
    ) -> None:
        self.root = root
        self.mcp = mcp
        self.envelope = envelope
        self.failure = failure
        self.submit = submit
        self.submission_payload = submission_payload
        self.called = False

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
        activity_callback: PrototypeUiEngineerActivityCallback | None = None,
        completion_callback: PrototypeUiEngineerCompletionCallback | None = None,
        mcp_config: str | None = None,
    ) -> PrototypeUiEngineerScopedTaskResult:
        del project, prompt, source_paths, phase, task_kind, task_title
        self.called = True
        if self.failure is not None:
            raise self.failure
        assert mcp_config is not None
        assert activity_callback is not None
        assert completion_callback is not None
        process_id = "generation-process-1"
        now = datetime.now(UTC)
        await activity_callback(
            PrototypeUiEngineerActivity(
                phase="running",
                task_id=task_id,
                execution_process_id=process_id,
                output_chars=None,
                last_event_at=now,
                occurred_at=now,
            )
        )
        worktree = self.root / scope_id
        config = json.loads(mcp_config)
        token = config["mcpServers"]["structured-prototype-generation"]["headers"][
            "X-Prototype-Generation-Token"
        ]
        context_status, context_response = await self.mcp.handle(
            token=token,
            payload={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "get_generation_submission_context",
                    "arguments": {},
                },
            },
        )
        assert context_status == 200
        assert context_response is not None
        if self.submit:
            submission_payload = (
                self.submission_payload
                if self.submission_payload is not None
                else self.envelope.payload.model_dump(mode="json", by_alias=True)
            )
            status, response = await self.mcp.handle(
                token=token,
                payload={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "finalize_prototype_page",
                        "arguments": {
                            "payloadJson": json.dumps(
                                submission_payload,
                                ensure_ascii=False,
                                separators=(",", ":"),
                            )
                        },
                    },
                },
            )
            assert status == 200
            assert response is not None
            result = response["result"]
            assert isinstance(result, dict)
            assert result["isError"] is False
        await completion_callback(worktree, task_id, process_id)
        return PrototypeUiEngineerScopedTaskResult(
            task_id=task_id,
            execution_process_id=process_id,
            assistant_result="submitted",
        )


def _request(context: dict[str, object]) -> StructuredPrototypeGenerationTaskRequest:
    return StructuredPrototypeGenerationTaskRequest(
        project=Project(id="project-1", name="Procurement", repo_path="/tmp/project"),
        operation_id="generation-operation-1",
        job_id="generation-job-1",
        run_id="generation-run-1",
        item_id="generation-item-1",
        task_id="generation-task-1",
        task_kind="generation_page",
        context_object_hash="sha256:" + hashlib.sha256(canonical_json_bytes(context)).hexdigest(),
        frozen_context=context,
    )


def _envelope(request: StructuredPrototypeGenerationTaskRequest) -> GenerationPageEnvelopeV1:
    return GenerationPageEnvelopeV1.model_validate(
        {
            "generationContractVersion": 1,
            "jobId": request.job_id,
            "runId": request.run_id,
            "itemId": request.item_id,
            "taskKind": request.task_kind,
            "contextObjectHash": request.context_object_hash,
            "payload": GeneratedPageV1.model_validate(
                _create_page_payload(), strict=True
            ).model_dump(mode="json", by_alias=True),
        },
        strict=True,
    )


@pytest.mark.asyncio
async def test_runtime_moves_one_verified_mcp_payload_into_managed_object_store(
    tmp_path: Path,
) -> None:
    context = {"contractVersion": 1, "pageKey": "purchase-create"}
    request = _request(context)
    mcp = StructuredPrototypeGenerationMcpService()
    envelope = _envelope(request)
    generator = _SubmittingGenerator(root=tmp_path, mcp=mcp, envelope=envelope)
    runtime = StructuredPrototypeGenerationRuntime(
        runner=cast(PrototypeUiEngineerRunner, generator),
        mcp_service=mcp,
        object_store=PrototypeObjectStore(tmp_path / "managed"),
    )

    result = await runtime.execute(request)

    assert result.task_id == request.task_id
    assert result.artifact_descriptor.content_hash.startswith("sha256:")
    stored = PrototypeObjectStore(tmp_path / "managed").read_canonical_bytes(
        result.artifact_descriptor
    )
    assert stored == canonical_json_bytes(generation_artifact_payload(envelope))
    assert mcp.active_session_count() == 0


@pytest.mark.asyncio
async def test_runtime_stores_normalized_canonical_payload_with_raw_request_hash(
    tmp_path: Path,
) -> None:
    context = {"contractVersion": 1, "pageKey": "purchase-create"}
    request = _request(context)
    mcp = StructuredPrototypeGenerationMcpService()
    envelope = _envelope(request)
    raw_payload = envelope.payload.model_dump(mode="json", by_alias=True)
    root = raw_payload["root"]
    assert isinstance(root, dict)
    root["gap"] = "16"
    root["padding"] = "24"
    root["children"] = {"item": root["children"]}
    raw_arguments = {
        "payloadJson": json.dumps(
            raw_payload,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    }
    raw_request_hash = "sha256:" + hashlib.sha256(
        canonical_json_bytes(raw_arguments)
    ).hexdigest()
    generator = _SubmittingGenerator(
        root=tmp_path,
        mcp=mcp,
        envelope=envelope,
        submission_payload=raw_payload,
    )
    object_store = PrototypeObjectStore(tmp_path / "managed")
    runtime = StructuredPrototypeGenerationRuntime(
        runner=cast(PrototypeUiEngineerRunner, generator),
        mcp_service=mcp,
        object_store=object_store,
    )

    result = await runtime.execute(request)

    assert result.submission.request_hash == raw_request_hash
    assert result.submission.normalized_fields == (
        "payload.root.gap",
        "payload.root.padding",
        "payload.root.children",
    )
    stored = object_store.read_canonical_bytes(result.artifact_descriptor)
    assert stored == canonical_json_bytes(generation_artifact_payload(envelope))


@pytest.mark.asyncio
async def test_runtime_refuses_task_without_mcp_submission(tmp_path: Path) -> None:
    context = {"contractVersion": 1, "pageKey": "purchase-create"}
    request = _request(context)
    mcp = StructuredPrototypeGenerationMcpService()
    generator = _SubmittingGenerator(
        root=tmp_path,
        mcp=mcp,
        envelope=_envelope(request),
        submit=False,
    )
    runtime = StructuredPrototypeGenerationRuntime(
        runner=cast(PrototypeUiEngineerRunner, generator),
        mcp_service=mcp,
        object_store=PrototypeObjectStore(tmp_path / "managed"),
    )

    with pytest.raises(StructuredPrototypeGenerationRuntimeError) as error:
        await runtime.execute(request)

    assert error.value.code == "submission_missing"
    assert mcp.active_session_count() == 0


@pytest.mark.asyncio
async def test_runtime_refuses_context_hash_mismatch_before_opening_mcp_session(
    tmp_path: Path,
) -> None:
    context = {"contractVersion": 1, "pageKey": "purchase-create"}
    request = _request(context)
    mismatched = replace(request, context_object_hash="sha256:" + "0" * 64)
    mcp = StructuredPrototypeGenerationMcpService()
    generator = _SubmittingGenerator(root=tmp_path, mcp=mcp, envelope=_envelope(request))
    runtime = StructuredPrototypeGenerationRuntime(
        runner=cast(PrototypeUiEngineerRunner, generator),
        mcp_service=mcp,
        object_store=PrototypeObjectStore(tmp_path / "managed"),
    )

    with pytest.raises(StructuredPrototypeGenerationRuntimeError) as error:
        await runtime.execute(mismatched)

    assert error.value.code == "context_hash_mismatch"
    assert generator.called is False
    assert mcp.active_session_count() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "expected_code"),
    [
        (WorktreeError("worktree unavailable"), "generation_worktree_failed"),
        (PrototypeUiEngineerRunnerError("Claude unavailable"), "generation_agent_failed"),
    ],
)
async def test_runtime_normalizes_generator_startup_failures(
    tmp_path: Path,
    failure: Exception,
    expected_code: str,
) -> None:
    context = {"contractVersion": 1, "pageKey": "purchase-create"}
    request = _request(context)
    mcp = StructuredPrototypeGenerationMcpService()
    generator = _SubmittingGenerator(
        root=tmp_path,
        mcp=mcp,
        envelope=_envelope(request),
        failure=failure,
    )
    runtime = StructuredPrototypeGenerationRuntime(
        runner=cast(PrototypeUiEngineerRunner, generator),
        mcp_service=mcp,
        object_store=PrototypeObjectStore(tmp_path / "managed"),
    )

    with pytest.raises(StructuredPrototypeGenerationRuntimeError) as error:
        await runtime.execute(request)

    assert error.value.code == expected_code
    assert mcp.active_session_count() == 0


def test_generation_prompt_requires_direct_mcp_payload_without_file_writes() -> None:
    context = {"contractVersion": 1, "pageKey": "purchase-create"}
    request = _request(context)

    prompt = StructuredPrototypeGenerationRuntime._build_prompt(request)

    assert "Do not edit, format, commit, or create any files" in prompt
    assert "one argument named payloadJson" in prompt
    assert "complete strict JSON serialization of the page" in prompt
    assert "backend assigns all job, task, process, hash, and storage metadata" in prompt
    assert "stagingByteHash" not in prompt
