from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import cast

import pytest

from app.adapters.prototype_object_store import canonical_json_bytes
from app.application.prototype_ui_engineer_runner import (
    PrototypeUiEngineerActivity,
    PrototypeUiEngineerActivityCallback,
    PrototypeUiEngineerCompletionCallback,
    PrototypeUiEngineerRunner,
    PrototypeUiEngineerScopedTaskResult,
)
from app.application.structured_prototype_ai_mcp import PrototypeAiMcpService
from app.application.structured_prototype_ai_runtime import (
    PrototypeUiEngineerRuntime,
    PrototypeUiEngineerRuntimeError,
    PrototypeUiEngineerTaskRequest,
)
from app.domain.models import Project


class _SubmittingGenerator:
    def __init__(
        self,
        *,
        mcp: PrototypeAiMcpService,
        outcome: dict[str, object],
        process_id: str = "process-1",
    ) -> None:
        self.mcp = mcp
        self.outcome = outcome
        self.process_id = process_id
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
        del project, scope_id, prompt, source_paths, phase, task_kind, task_title
        del completion_callback
        self.called = True
        assert activity_callback is not None
        assert mcp_config is not None
        now = datetime.now(UTC)
        await activity_callback(
            PrototypeUiEngineerActivity(
                phase="running",
                task_id=task_id,
                execution_process_id=self.process_id,
                output_chars=None,
                last_event_at=now,
                occurred_at=now,
            )
        )
        config = json.loads(mcp_config)
        token = config["mcpServers"]["structured-prototype-ai"]["headers"][
            "X-Prototype-Ai-Token"
        ]
        status, response = await self.mcp.handle(
            token=token,
            payload={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "submit_prototype_assistant_outcome",
                    "arguments": {
                        "outcomeJson": json.dumps(
                            self.outcome,
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
        return PrototypeUiEngineerScopedTaskResult(
            task_id=task_id,
            execution_process_id=self.process_id,
            assistant_result="submitted",
        )


def _request(context: dict[str, object]) -> PrototypeUiEngineerTaskRequest:
    return PrototypeUiEngineerTaskRequest(
        project=Project(id="project-1", name="Procurement", repo_path="/tmp/project"),
        operation_id="operation-1",
        edit_run_id="run-1",
        task_id="task-1",
        frozen_context_object_hash="sha256:"
        + hashlib.sha256(canonical_json_bytes(context)).hexdigest(),
        frozen_context=context,
        user_instruction="把标题改为采购申请总览",
    )


@pytest.mark.asyncio
async def test_ai_runtime_accepts_one_process_bound_json_outcome() -> None:
    context = {"contractVersion": 1, "scope": "selection"}
    mcp = PrototypeAiMcpService()
    generator = _SubmittingGenerator(
        mcp=mcp,
        outcome={
            "contractVersion": 1,
            "kind": "answer",
            "message": "当前标题是采购申请。",
        },
    )
    runtime = PrototypeUiEngineerRuntime(
        runner=cast(PrototypeUiEngineerRunner, generator),
        mcp_service=mcp,
    )

    result = await runtime.execute(_request(context))

    assert result.task_id == "task-1"
    assert result.execution_process_id == "process-1"
    assert result.outcome.kind == "answer"
    assert result.submission.request_hash.startswith("sha256:")
    assert mcp.active_session_count() == 0


@pytest.mark.asyncio
async def test_ai_runtime_refuses_context_hash_mismatch_before_starting_agent() -> None:
    context = {"contractVersion": 1, "scope": "selection"}
    mcp = PrototypeAiMcpService()
    generator = _SubmittingGenerator(
        mcp=mcp,
        outcome={
            "contractVersion": 1,
            "kind": "answer",
            "message": "不会执行。",
        },
    )
    runtime = PrototypeUiEngineerRuntime(
        runner=cast(PrototypeUiEngineerRunner, generator),
        mcp_service=mcp,
    )

    with pytest.raises(PrototypeUiEngineerRuntimeError) as error:
        await runtime.execute(
            replace(
                _request(context),
                frozen_context_object_hash="sha256:" + "0" * 64,
            )
        )

    assert error.value.code == "context_hash_mismatch"
    assert generator.called is False
    assert mcp.active_session_count() == 0


def test_ai_prompt_requires_json_string_submission() -> None:
    prompt = PrototypeUiEngineerRuntime._build_prompt(
        _request({"contractVersion": 1, "scope": "selection"})
    )

    assert "only argument must be outcomeJson" in prompt
    assert "Encode commands and affectedEntityIds as JSON arrays" in prompt
    assert "replacement PrototypeDocument" in prompt
