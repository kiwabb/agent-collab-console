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
from app.application.codex_task_runner import (
    CodexTaskExecutionTerminalEvidence,
    CodexTaskWireInputEvidence,
)
from app.application.prototype_ui_engineer_runner import (
    PrototypeUiEngineerActivity,
    PrototypeUiEngineerActivityCallback,
    PrototypeUiEngineerCompletionCallback,
    PrototypeUiEngineerInstrumentationCallback,
    PrototypeUiEngineerPreparedCallback,
    PrototypeUiEngineerProcessStartedEvidence,
    PrototypeUiEngineerReleaseCallback,
    PrototypeUiEngineerRunner,
    PrototypeUiEngineerRunnerError,
    PrototypeUiEngineerRuntimeProfile,
    PrototypeUiEngineerScopedTaskResult,
    PrototypeUiEngineerTaskCreatedEvidence,
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
    GenerationMcpSubmissionEvidence,
    GenerationProcessStartedEvidence,
    GenerationProcessTerminalEvidence,
    GenerationTaskCreatedEvidence,
    GenerationWireInputEvidence,
    StructuredPrototypeGenerationExecutionEvidence,
    StructuredPrototypeGenerationRuntime,
    StructuredPrototypeGenerationRuntimeError,
    StructuredPrototypeGenerationTaskRequest,
)
from app.application.worktree_manager import WorktreeError
from app.domain.models import CodexTask, ExecutionProcess, Project
from app.domain.structured_prototype_generation import PrototypeGenerationSourceSnapshot


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
        retry_submission_on_error: bool = False,
    ) -> None:
        self.root = root
        self.mcp = mcp
        self.envelope = envelope
        self.failure = failure
        self.submit = submit
        self.submission_payload = submission_payload
        self.retry_submission_on_error = retry_submission_on_error
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
        source_snapshot: PrototypeGenerationSourceSnapshot | None = None,
        activity_callback: PrototypeUiEngineerActivityCallback | None = None,
        prepared_callback: PrototypeUiEngineerPreparedCallback | None = None,
        release_callback: PrototypeUiEngineerReleaseCallback | None = None,
        completion_callback: PrototypeUiEngineerCompletionCallback | None = None,
        instrumentation_callback: PrototypeUiEngineerInstrumentationCallback | None = None,
        mcp_config: str | None = None,
    ) -> PrototypeUiEngineerScopedTaskResult:
        del project, source_paths, phase, task_kind, task_title
        assert source_snapshot == _source_snapshot()
        self.called = True
        if self.failure is not None:
            raise self.failure
        assert mcp_config is not None
        assert activity_callback is not None
        assert prepared_callback is not None
        assert release_callback is not None
        assert completion_callback is not None
        assert instrumentation_callback is not None
        process_id = "generation-process-1"
        now = datetime.now(UTC)
        worktree = self.root / scope_id
        worktree.mkdir(parents=True, exist_ok=True)
        await prepared_callback(worktree, task_id)
        task = CodexTask(
            id=task_id,
            session_id="generation-workspace-1",
            project_id="project-1",
            title="Generate page",
            prompt=prompt,
            role="prototype_ui_engineer",
            executor="claude",
            status="pending",
            task_kind="generation_page",
            workspace_path=str(worktree),
            git_worktree_path=str(worktree),
            git_base_branch=_source_snapshot().worktree_base_commit,
            created_at=now,
            updated_at=now,
        )
        profile = PrototypeUiEngineerRuntimeProfile(
            runtime_profile_id="prototype-ui-engineer/generation_page/v1",
            runtime_profile_hash="sha256:" + "1" * 64,
            executor="claude",
            runtime_binary="claude",
            runtime_binary_hash="sha256:" + "2" * 64,
            adapter_config_hash="sha256:" + "3" * 64,
            executor_adapter_version="claude-process-runtime/v1",
        )
        await instrumentation_callback(
            PrototypeUiEngineerTaskCreatedEvidence(
                task=task,
                task_id=task_id,
                workspace_id=task.session_id,
                worktree_path=str(worktree),
                repository_root=str(worktree.resolve()),
                worktree_path_contained=True,
                worktree_base_commit=_source_snapshot().worktree_base_commit,
                source_snapshot_ref=_source_snapshot().source_snapshot_ref,
                source_fingerprint=_source_snapshot().source_fingerprint,
                runtime_profile=profile,
            )
        )
        process = ExecutionProcess(
            id=process_id,
            task_id=task_id,
            session_id=task.session_id,
            status="Running",
            executor="claude",
            started_at=now,
            created_at=now,
            updated_at=now,
        )
        task.last_execution_process_id = process.id
        task.status = "running"
        await instrumentation_callback(
            PrototypeUiEngineerProcessStartedEvidence(task=task, process=process)
        )
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
        await instrumentation_callback(
            CodexTaskWireInputEvidence(
                task_id=task_id,
                execution_process_id=process_id,
                wire_input_hash="sha256:" + "4" * 64,
                wire_input_size=256,
                framing="claude-stream-json/user-message/v1",
                executor="claude",
                executor_type="claude",
                provider=None,
                model="test-model",
                runtime_config_hash="sha256:" + "5" * 64,
            )
        )
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
            submission_call = {
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
            }
            status, response = await self.mcp.handle(token=token, payload=submission_call)
            assert status == 200
            assert response is not None
            result = response["result"]
            assert isinstance(result, dict)
            if result["isError"] is True and self.retry_submission_on_error:
                status, response = await self.mcp.handle(token=token, payload=submission_call)
                assert status == 200
                assert response is not None
                result = response["result"]
                assert isinstance(result, dict)
            if result["isError"] is True:
                task.status = "failed"
                task.result = "MCP submission was refused"
                process.status = "Failed"
                process.exit_code = -1
                process.completed_at = datetime.now(UTC)
                await instrumentation_callback(
                    CodexTaskExecutionTerminalEvidence(
                        task=task,
                        process=process,
                        task_status=task.status,
                        result_hash="sha256:" + "7" * 64,
                        result_size=len(task.result),
                    )
                )
                await release_callback()
                raise PrototypeUiEngineerRunnerError("MCP submission was refused")
        task.status = "done"
        task.result = "submitted"
        process.status = "Completed"
        process.exit_code = 0
        process.completed_at = datetime.now(UTC)
        await instrumentation_callback(
            CodexTaskExecutionTerminalEvidence(
                task=task,
                process=process,
                task_status=task.status,
                result_hash="sha256:" + "6" * 64,
                result_size=len(task.result),
            )
        )
        await completion_callback(worktree, task_id, process_id)
        await release_callback()
        return PrototypeUiEngineerScopedTaskResult(
            task_id=task_id,
            execution_process_id=process_id,
            assistant_result="submitted",
        )


def _request(context: dict[str, object]) -> StructuredPrototypeGenerationTaskRequest:
    return StructuredPrototypeGenerationTaskRequest(
        project=Project(id="project-1", name="admin-demo", repo_path="/tmp/project"),
        operation_id="generation-operation-1",
        job_id="generation-job-1",
        run_id="generation-run-1",
        item_id="generation-item-1",
        task_id="generation-task-1",
        task_kind="generation_page",
        context_object_hash="sha256:" + hashlib.sha256(canonical_json_bytes(context)).hexdigest(),
        frozen_context=context,
        source_snapshot=_source_snapshot(),
    )


def _source_snapshot() -> PrototypeGenerationSourceSnapshot:
    return PrototypeGenerationSourceSnapshot(
        source_policy="committed_head_v1",
        source_snapshot_object_hash="sha256:" + "1" * 64,
        source_fingerprint="sha256:" + "2" * 64,
        source_snapshot_ref=(
            "refs/agent-collab/prototype-generation/11111111-1111-1111-1111-111111111111"
        ),
        repository_object_format="sha1",
        worktree_base_commit="3" * 40,
        repository_project_prefix="",
        repository_tree_object_id="4" * 40,
        source_file_exclusion_policy="dotenv_checkout_filter_v1",
        working_tree_dirty=False,
        excluded_tracked_change_count=0,
        excluded_untracked_count=0,
        excluded_sensitive_file_count=0,
        excluded_status_hash="sha256:" + "5" * 64,
    )


def _envelope(request: StructuredPrototypeGenerationTaskRequest) -> GenerationPageEnvelopeV1:
    return GenerationPageEnvelopeV1.model_validate(
        {
            "generationContractVersion": 3,
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


def _page_context() -> dict[str, object]:
    return {
        "contractVersion": 3,
        "page": {
            "pageKey": "users",
            "title": "用户管理",
            "route": "/users",
        },
        "confirmedIntents": {
            "flows": [],
            "forms": [],
            "entities": [],
            "viewBindings": [
                {
                    "key": "users-table-rows",
                    "pageKey": "users",
                    "target": "tableRows",
                    "schemaKey": "user",
                    "sortFieldKey": "name",
                    "sortDirection": "asc",
                }
            ],
            "behaviors": [],
        },
    }


async def _accept_evidence(_: StructuredPrototypeGenerationExecutionEvidence) -> None:
    return None


@pytest.mark.asyncio
async def test_runtime_moves_one_verified_mcp_payload_into_managed_object_store(
    tmp_path: Path,
) -> None:
    context = _page_context()
    request = _request(context)
    mcp = StructuredPrototypeGenerationMcpService()
    envelope = _envelope(request)
    generator = _SubmittingGenerator(root=tmp_path, mcp=mcp, envelope=envelope)
    runtime = StructuredPrototypeGenerationRuntime(
        runner=cast(PrototypeUiEngineerRunner, generator),
        mcp_service=mcp,
        object_store=PrototypeObjectStore(tmp_path / "managed"),
    )
    activities: list[PrototypeUiEngineerActivity] = []
    evidence: list[StructuredPrototypeGenerationExecutionEvidence] = []
    callback_order: list[str] = []

    async def capture_activity(activity: PrototypeUiEngineerActivity) -> None:
        callback_order.append("activity")
        activities.append(activity)

    async def capture_evidence(item: StructuredPrototypeGenerationExecutionEvidence) -> None:
        callback_order.append(type(item).__name__)
        evidence.append(item)

    result = await runtime.execute(
        request,
        activity_callback=capture_activity,
        evidence_callback=capture_evidence,
    )

    assert result.task_id == request.task_id
    assert [activity.execution_process_id for activity in activities] == [
        result.execution_process_id
    ]
    assert result.artifact_descriptor.content_hash.startswith("sha256:")
    assert [type(item) for item in evidence] == [
        GenerationTaskCreatedEvidence,
        GenerationProcessStartedEvidence,
        GenerationWireInputEvidence,
        GenerationMcpSubmissionEvidence,
        GenerationProcessTerminalEvidence,
    ]
    assert callback_order == [
        "GenerationTaskCreatedEvidence",
        "GenerationProcessStartedEvidence",
        "activity",
        "GenerationWireInputEvidence",
        "GenerationMcpSubmissionEvidence",
        "GenerationProcessTerminalEvidence",
    ]
    mcp_evidence = evidence[3]
    assert isinstance(mcp_evidence, GenerationMcpSubmissionEvidence)
    assert mcp_evidence.execution_process_id == result.execution_process_id
    assert mcp_evidence.wire_input_hash == "sha256:" + "4" * 64
    terminal_evidence = evidence[4]
    assert isinstance(terminal_evidence, GenerationProcessTerminalEvidence)
    assert terminal_evidence.process.status == "Completed"
    stored = PrototypeObjectStore(tmp_path / "managed").read_canonical_bytes(
        result.artifact_descriptor
    )
    assert stored == canonical_json_bytes(generation_artifact_payload(envelope))
    assert mcp.active_session_count() == 0


@pytest.mark.asyncio
async def test_runtime_stores_normalized_canonical_payload_with_raw_request_hash(
    tmp_path: Path,
) -> None:
    context = _page_context()
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
    raw_request_hash = "sha256:" + hashlib.sha256(canonical_json_bytes(raw_arguments)).hexdigest()
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

    result = await runtime.execute(request, evidence_callback=_accept_evidence)

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
    context = _page_context()
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
        await runtime.execute(request, evidence_callback=_accept_evidence)

    assert error.value.code == "submission_missing"
    assert mcp.active_session_count() == 0


@pytest.mark.asyncio
async def test_runtime_refuses_context_hash_mismatch_before_opening_mcp_session(
    tmp_path: Path,
) -> None:
    context = _page_context()
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
        await runtime.execute(mismatched, evidence_callback=_accept_evidence)

    assert error.value.code == "context_hash_mismatch"
    assert generator.called is False
    assert mcp.active_session_count() == 0


@pytest.mark.asyncio
async def test_runtime_refuses_generation_without_durable_evidence_callback(tmp_path: Path) -> None:
    request = _request(_page_context())
    mcp = StructuredPrototypeGenerationMcpService()
    generator = _SubmittingGenerator(root=tmp_path, mcp=mcp, envelope=_envelope(request))
    runtime = StructuredPrototypeGenerationRuntime(
        runner=cast(PrototypeUiEngineerRunner, generator),
        mcp_service=mcp,
        object_store=PrototypeObjectStore(tmp_path / "managed"),
    )

    with pytest.raises(StructuredPrototypeGenerationRuntimeError) as error:
        await runtime.execute(request)

    assert error.value.code == "generation_evidence_callback_missing"
    assert generator.called is False
    assert mcp.active_session_count() == 0


@pytest.mark.asyncio
async def test_runtime_mcp_evidence_failure_refuses_submission_and_returns_terminal_failure(
    tmp_path: Path,
) -> None:
    request = _request(_page_context())
    mcp = StructuredPrototypeGenerationMcpService()
    generator = _SubmittingGenerator(root=tmp_path, mcp=mcp, envelope=_envelope(request))
    object_store = PrototypeObjectStore(tmp_path / "managed")
    runtime = StructuredPrototypeGenerationRuntime(
        runner=cast(PrototypeUiEngineerRunner, generator),
        mcp_service=mcp,
        object_store=object_store,
    )
    events: list[StructuredPrototypeGenerationExecutionEvidence] = []

    async def reject_mcp(evidence: StructuredPrototypeGenerationExecutionEvidence) -> None:
        events.append(evidence)
        if isinstance(evidence, GenerationMcpSubmissionEvidence):
            raise RuntimeError("mcp operation event unavailable")

    with pytest.raises(StructuredPrototypeGenerationRuntimeError) as error:
        await runtime.execute(request, evidence_callback=reject_mcp)

    assert error.value.code == "generation_agent_failed"
    assert [type(event) for event in events] == [
        GenerationTaskCreatedEvidence,
        GenerationProcessStartedEvidence,
        GenerationWireInputEvidence,
        GenerationMcpSubmissionEvidence,
        GenerationProcessTerminalEvidence,
    ]
    terminal = events[-1]
    assert isinstance(terminal, GenerationProcessTerminalEvidence)
    assert terminal.process.status == "Failed"
    assert terminal.process.exit_code == -1
    assert list((tmp_path / "managed").glob("**/*")) == []
    assert mcp.active_session_count() == 0


@pytest.mark.asyncio
async def test_runtime_identical_mcp_retry_clears_prior_evidence_failure(
    tmp_path: Path,
) -> None:
    request = _request(_page_context())
    mcp = StructuredPrototypeGenerationMcpService()
    generator = _SubmittingGenerator(
        root=tmp_path,
        mcp=mcp,
        envelope=_envelope(request),
        retry_submission_on_error=True,
    )
    runtime = StructuredPrototypeGenerationRuntime(
        runner=cast(PrototypeUiEngineerRunner, generator),
        mcp_service=mcp,
        object_store=PrototypeObjectStore(tmp_path / "managed"),
    )
    mcp_callback_attempts = 0
    accepted_operation_step_transitions = 0
    terminal_events: list[GenerationProcessTerminalEvidence] = []

    async def fail_once_then_accept(
        evidence: StructuredPrototypeGenerationExecutionEvidence,
    ) -> None:
        nonlocal mcp_callback_attempts, accepted_operation_step_transitions
        if isinstance(evidence, GenerationMcpSubmissionEvidence):
            mcp_callback_attempts += 1
            if mcp_callback_attempts == 1:
                raise RuntimeError("mcp operation event unavailable")
            accepted_operation_step_transitions += 1
        elif isinstance(evidence, GenerationProcessTerminalEvidence):
            terminal_events.append(evidence)

    result = await runtime.execute(request, evidence_callback=fail_once_then_accept)

    assert result.task_id == request.task_id
    assert mcp_callback_attempts == 2
    assert accepted_operation_step_transitions == 1
    assert len(terminal_events) == 1
    assert terminal_events[0].process.status == "Completed"
    assert terminal_events[0].process.exit_code == 0
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
    context = _page_context()
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
        await runtime.execute(request, evidence_callback=_accept_evidence)

    assert error.value.code == expected_code
    assert mcp.active_session_count() == 0


def test_generation_prompt_requires_direct_mcp_payload_without_file_writes() -> None:
    context = _page_context()
    request = _request(context)

    prompt = StructuredPrototypeGenerationRuntime._build_prompt(request)

    assert "Do not edit, format, commit, or create any files" in prompt
    assert "one argument named payloadJson" in prompt
    assert "exactly one accepted submission" in prompt
    assert "If it returns schema_invalid" in prompt
    assert "after acceptance, do not submit a changed payload" in prompt
    assert "complete strict JSON serialization of the page" in prompt
    assert "exact camelCase columnOverrides field name" in prompt
    assert "backend assigns all job, task, process, hash, and storage metadata" in prompt
    assert "list_project_files with a narrow root-relative glob" in prompt
    assert "search_project_text with a literal query" in prompt
    assert "read_project_file with bounded startLine and lineCount" in prompt
    assert "Built-in Read, Glob, Grep, Bash, Edit, and Write are unavailable" in prompt
    assert "Do not guess absolute worktree paths" in prompt
    assert "stagingByteHash" not in prompt

    blueprint_prompt = StructuredPrototypeGenerationRuntime._build_prompt(
        replace(request, task_kind="generation_blueprint")
    )
    assert "ordinary route and menu transitions in navigation only" in blueprint_prompt
    assert "active route's render dependency chain" in blueprint_prompt
    assert "responsive layout, and navigation structure" in blueprint_prompt
    assert "explicit scoped requirement in the frozen brief" in blueprint_prompt
    assert "GET endpoint" in blueprint_prompt
    assert "read-only table does not by itself require runtime entities" in blueprint_prompt
    assert "visible control without a source handler is visual-only" in blueprint_prompt
    assert "Prefer empty optional intent arrays" in blueprint_prompt
    assert "flowIntents, roleIntents, entityIntents" in blueprint_prompt
    assert "behaviorIntents, and scenarioIntents as empty arrays" in blueprint_prompt
    assert "Before calling finalize_prototype_blueprint" in blueprint_prompt
    assert (
        "each of list_project_files, search_project_text, and read_project_file" in blueprint_prompt
    )
    assert "same MCP session" in blueprint_prompt
    assert "failed repository discovery call does not satisfy" in blueprint_prompt
    assert "submit it promptly" in blueprint_prompt

    page_prompt = StructuredPrototypeGenerationRuntime._build_prompt(request)
    assert "Before calling finalize_prototype_blueprint" not in page_prompt
    assert "without a confirmed view binding" in page_prompt
    assert "static structured Text and Table data" in page_prompt


def test_generation_page_prompt_requires_repository_content_fidelity() -> None:
    request = _request(_page_context())

    page_prompt = StructuredPrototypeGenerationRuntime._build_prompt(request)

    assert "Prompt version: structured-prototype-generation/v13" in page_prompt
    assert "frozen task scope, repository runtime evidence, then generated fallback" in page_prompt
    assert "target route's actual render and data dependency chain" in page_prompt
    assert "reuse the copy verbatim and preserve the exact semantic value" in page_prompt
    assert "only when it does not change the underlying value" in page_prompt
    assert "Do not paraphrase, replace, round, rescale, anonymize, or invent" in page_prompt
    assert "choose only source-backed items" in page_prompt
    assert "defines structure but no concrete copy or value" in page_prompt
    assert "Never use fallback content to replace available repository evidence" in page_prompt
    assert "use a Grid node instead of a row Stack" in page_prompt
    assert "breakpoint widths exactly" in page_prompt
    assert "mobile column count as Grid columns" in page_prompt
    assert "source 4/2/1 layout" in page_prompt
    assert "Page payload node contract summary" in page_prompt
    assert "root must be a Stack object with a non-empty visible content subtree" in page_prompt
    assert "leaf content nodes are Text" in page_prompt
    assert "Do not finalize an empty root" in page_prompt
    assert "Page submission discipline" in page_prompt
    assert "do not draft, print, narrate, or fully expand the page payload" in page_prompt
    assert "directly in the finalize_prototype_page tool argument" in page_prompt
    assert "target 12-40 nodes" in page_prompt
    assert "use Table rows for repeated source collections" in page_prompt

    foundation_prompt = StructuredPrototypeGenerationRuntime._build_prompt(
        replace(request, task_kind="generation_foundation")
    )
    assert "one argument named payloadJson" in foundation_prompt
    assert "complete strict JSON serialization of the foundation" in foundation_prompt
    assert "encode colors and spacing as JSON arrays" in foundation_prompt
    assert "sharedShell as a JSON object inside that string" in foundation_prompt
    assert "one renderer-safe single length such as 16px or 1.5rem" in foundation_prompt
    assert "do not emit CSS shorthand values" in foundation_prompt
    assert "one argument named payload to obtain" not in foundation_prompt
    assert "target route's actual render and data dependency chain" not in foundation_prompt
    assert "active frontend style entrypoints and shared shell" in foundation_prompt
    assert "color, typography, spacing, density, sidebar" in foundation_prompt
    assert "Follow imported CSS, theme tokens, and component styles" in foundation_prompt
    assert "Do not substitute framework defaults or a generic dashboard theme" in foundation_prompt
    assert "foundation spacing tokens cannot use CSS shorthand" in foundation_prompt
    assert "minimal generated fallback tokens" in foundation_prompt
    assert "Page payload node contract summary" not in foundation_prompt
    assert "Page submission discipline" not in foundation_prompt

    blueprint_prompt = StructuredPrototypeGenerationRuntime._build_prompt(
        replace(request, task_kind="generation_blueprint")
    )
    assert "one argument named payload to obtain" in blueprint_prompt
    assert "one argument named payloadJson" not in blueprint_prompt
    assert "Its payload value must be the complete JSON object" in blueprint_prompt
    assert "Page payload node contract summary" not in blueprint_prompt
    assert "Page submission discipline" not in blueprint_prompt
