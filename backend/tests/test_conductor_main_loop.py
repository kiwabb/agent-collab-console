import asyncio
import json
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.application.conductor_main_loop import (
    _run_heartbeat_pulse,
    _seal_graph_and_issue_status,
    build_issue_conductor_prompt,
    conductor_language_directive,
    detect_text_language,
    run_conductor_loop,
)
from app.application.conductor_tools import build_conductor_tools
from app.application.llm_runner import extract_tool_use_blocks
from app.application.verification_evidence import capture_verification_state
from app.domain.models import CodexIssue, ProjectMemoryEmbedding
from app.json_safety import JsonObject, object_dict

_DEFAULT_ACCEPTANCE_CRITERION = "Verified behavior matches the request"
_VERIFICATION_TEMP_DIR: tempfile.TemporaryDirectory[str] | None = None


def _verification_workspace() -> str:
    global _VERIFICATION_TEMP_DIR
    if _VERIFICATION_TEMP_DIR is not None:
        return _VERIFICATION_TEMP_DIR.name
    _VERIFICATION_TEMP_DIR = tempfile.TemporaryDirectory()
    root = Path(_VERIFICATION_TEMP_DIR.name)
    subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "conductor@example.test"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Conductor Test"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    (root / "README.md").write_text("verified state\n")
    subprocess.run(["git", "add", "README.md"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return str(root)


async def _tool_result(registry, name: str, payload: JsonObject) -> JsonObject:
    try:
        return object_dict(await registry.tools[name](payload))
    except (ValueError, RuntimeError) as exc:
        return {"status": "failed", "error": str(exc)}


def _text(payload: JsonObject, key: str) -> str:
    value = payload.get(key)
    return value if isinstance(value, str) else ""


class _FinalizeStore:
    def __init__(
        self,
        nodes,
        tasks=None,
        *,
        acceptance_criteria=None,
        confirmed=True,
        worktree_path=None,
    ):
        self.nodes = nodes
        self.tasks = tasks or {}
        self.issue = SimpleNamespace(
            id="issue-1",
            acceptance_criteria=(
                acceptance_criteria
                if acceptance_criteria is not None
                else [_DEFAULT_ACCEPTANCE_CRITERION]
            ),
            acceptance_criteria_confirmed=confirmed,
            git_worktree_path=worktree_path or _verification_workspace(),
        )

    async def load_workflow_graph_for_issue(self, issue_id):
        return SimpleNamespace(nodes=self.nodes)

    async def load_codex_task(self, task_id):
        return self.tasks.get(task_id)

    async def load_codex_issue(self, issue_id):
        return self.issue


def _passed_qa_task(task_id: str = "qa-task", *, workspace_path: str | None = None):
    workspace = workspace_path or _verification_workspace()
    verification_state = capture_verification_state(
        workspace_path=workspace,
        issue_id="issue-1",
        task_id=task_id,
        role="qa",
    )
    return SimpleNamespace(
        id=task_id,
        issue_id="issue-1",
        role="qa",
        workspace_path=workspace,
        status="done",
        result=json.dumps(
            {
                "status": "passed",
                "execution_results": [
                    {
                        "command": "pytest -q",
                        "exit_code": 0,
                        "stdout": "1 passed",
                        "stderr": "",
                        "duration_s": 0.1,
                    }
                ],
                "criterion_evidence": [
                    {
                        "criterion_index": 0,
                        "criterion": _DEFAULT_ACCEPTANCE_CRITERION,
                        "command": "pytest -q",
                        "execution_result_index": 0,
                        "evidence": "1 passed",
                    }
                ],
                "verification_state": verification_state.model_dump(mode="json"),
            }
        ),
    )


def test_conductor_language_directive_auto_is_empty():
    """'auto' (default) keeps the legacy match-the-issue behavior: no directive."""
    assert conductor_language_directive("auto") == ""
    assert conductor_language_directive("") == ""
    assert conductor_language_directive(None) == ""


def test_conductor_language_directive_forces_locale():
    """A concrete locale injects a non-empty, locale-appropriate directive."""
    zh = conductor_language_directive("zh-CN")
    assert "简体中文" in zh
    en = conductor_language_directive("en-US")
    assert "English" in en
    # Unknown locale codes still produce a directive referencing the code.
    other = conductor_language_directive("fr-FR")
    assert "fr-FR" in other


def test_detect_text_language_matches_issue_language():
    """'auto' resolution: CJK content => zh, otherwise en. This is what un-froze
    the conductor's English narration on Chinese issues when output_language is
    unset/auto."""
    assert detect_text_language("为 backend 添加 GET /api/codex/echo 端点", None) == "zh"
    assert detect_text_language("Add GET /api/codex/echo endpoint", None) == "en"
    # Description carries the language even when the title is English.
    assert detect_text_language("Add endpoint", "需要返回时间戳") == "zh"
    assert detect_text_language("", None) == "en"
    # A concrete zh locale produced by auto-resolution drives a Chinese directive.
    assert "简体中文" in conductor_language_directive(
        detect_text_language("为 backend 添加端点", None)
    )


def test_build_issue_conductor_prompt_includes_recovery_context():
    issue = CodexIssue(
        id="issue-recovery",
        session_id="session-recovery",
        title="Fix recovery",
        description="Resume safely",
    )

    prompt = build_issue_conductor_prompt(
        issue=issue,
        project_context="",
        budget_context="",
        language_directive="",
        recovery_context="\n\n## RECOVERY CONTEXT\nResume node engineer.",
    )

    assert "## RECOVERY CONTEXT" in prompt
    assert "Resume node engineer." in prompt
    assert prompt.index("## RECOVERY CONTEXT") < prompt.index("## Your Job")


@pytest.mark.asyncio
async def test_heartbeat_pulse_survives_transient_failures_and_alerts():
    """GAP A: a failing heartbeat must not kill the pulse; it alerts after N."""
    beats = {"ok": 0, "fail": 0}
    degraded: list[tuple[int, str]] = []

    async def heartbeat():
        # Fail the first 3 renewals, then recover.
        if beats["ok"] + beats["fail"] < 3:
            beats["fail"] += 1
            raise RuntimeError("db unavailable")
        beats["ok"] += 1

    async def on_degraded(n, exc):
        degraded.append((n, str(exc)))

    pulse = asyncio.create_task(
        _run_heartbeat_pulse(heartbeat, 0.0, on_degraded=on_degraded, alert_after=3)
    )
    # Let the pulse run several iterations, then stop it.
    for _ in range(200):
        if beats["ok"] >= 2 and degraded:
            break
        await asyncio.sleep(0)
    pulse.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pulse

    # Loop survived the 3 failures and went on to renew successfully.
    assert beats["fail"] == 3
    assert beats["ok"] >= 1
    # Degraded callback fired exactly once, at the 3rd consecutive failure.
    assert len(degraded) == 1
    assert degraded[0][0] == 3


@pytest.mark.asyncio
async def test_heartbeat_pulse_propagates_cancellation():
    """Cancellation must tear the pulse down cleanly (not be swallowed)."""

    async def heartbeat():
        return None

    pulse = asyncio.create_task(_run_heartbeat_pulse(heartbeat, 0.0))
    await asyncio.sleep(0)
    pulse.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pulse


@pytest.mark.asyncio
async def test_conductor_loop_executes_tool_use_and_feeds_tool_result_back():
    calls = []

    async def fake_llm(messages, tools):
        calls.append(messages)
        if len(calls) == 1:
            return {
                "stop_reason": "tool_use",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_memory",
                        "name": "retrieve_cold_memory",
                        "input": {"query": "auth token"},
                    }
                ],
            }
        assert messages[-1]["role"] == "user"
        assert messages[-1]["content"][0]["type"] == "tool_result"
        assert messages[-1]["content"][0]["tool_use_id"] == "toolu_memory"
        assert "auth token regression" in messages[-1]["content"][0]["content"]
        return {
            "stop_reason": "tool_use",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_final",
                    "name": "finalize_task",
                    "input": {
                        "status": "done",
                        "answer": "Use the auth token regression memory.",
                    },
                }
            ],
        }

    async def retrieve_cold_memory(tool_input):
        assert tool_input == {"query": "auth token"}
        return {"memories": ["auth token regression happened in refresh flow"]}

    async def finalize_task(tool_input):
        return tool_input

    result = await run_conductor_loop(
        prompt="Plan the auth fix.",
        llm=fake_llm,
        tools={
            "retrieve_cold_memory": retrieve_cold_memory,
            "finalize_task": finalize_task,
        },
        tool_definitions=[{"name": "retrieve_cold_memory"}, {"name": "finalize_task"}],
    )

    assert result.final_text == "Use the auth token regression memory."
    assert len(result.tool_events) == 2
    assert result.tool_events[0]["name"] == "retrieve_cold_memory"
    assert result.tool_events[1]["name"] == "finalize_task"
    assert calls[1][-1]["content"][0]["tool_use_id"] == "toolu_memory"


@pytest.mark.asyncio
async def test_conductor_loop_stops_when_finalize_task_tool_returns_answer():
    async def fake_llm(messages, tools):
        return {
            "stop_reason": "tool_use",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_final",
                    "name": "finalize_task",
                    "input": {"answer": "done with confidence", "status": "done"},
                }
            ],
        }

    async def finalize_task(tool_input):
        return tool_input

    result = await run_conductor_loop(
        prompt="Finish the review.",
        llm=fake_llm,
        tools={"finalize_task": finalize_task},
        tool_definitions=[{"name": "finalize_task"}],
    )

    assert result.status == "done"
    assert result.final_text == "done with confidence"
    assert result.turn_count == 1


@pytest.mark.asyncio
async def test_conductor_loop_requires_finalize_tool_for_plain_text_response():
    calls = []

    async def fake_llm(messages, tools):
        calls.append(messages)
        return {
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "I think this is done."}],
        }

    result = await run_conductor_loop(
        prompt="Finish the review.",
        llm=fake_llm,
        tools={},
        tool_definitions=[],
        max_turns=2,
    )

    assert result.status == "protocol_error"
    assert result.turn_count == 2
    assert len(calls) == 2
    assert "MUST call finalize_task" in calls[1][-1]["content"]


@pytest.mark.asyncio
async def test_conductor_loop_unknown_finalize_status_fails_closed():
    async def fake_llm(messages, tools):
        return {
            "stop_reason": "tool_use",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_final",
                    "name": "finalize_task",
                    "input": {"answer": "not really done", "status": "maybe"},
                }
            ],
        }

    async def finalize_task(tool_input):
        return tool_input

    result = await run_conductor_loop(
        prompt="Finish the review.",
        llm=fake_llm,
        tools={"finalize_task": finalize_task},
        tool_definitions=[{"name": "finalize_task"}],
    )

    assert result.status == "failed"
    assert result.final_text == "not really done"
    assert result.turn_count == 1


@pytest.mark.asyncio
async def test_finalize_task_tool_normalizes_statuses():
    qa_task = _passed_qa_task()
    store = _FinalizeStore(
        [
            SimpleNamespace(node_key="engineer", status="done", task_id="engineer-task"),
            SimpleNamespace(node_key="qa", status="done", task_id=qa_task.id),
        ],
        {qa_task.id: qa_task},
    )
    registry = build_conductor_tools(
        project_id="project-1", store=store, issue_id="issue-1"
    )

    ok = await _tool_result(registry, "finalize_task", {"status": "completed", "answer": "done"})
    unknown = await _tool_result(registry, "finalize_task", {"status": "maybe", "answer": "hmm"})
    blocked = await _tool_result(
        registry, "finalize_task", {"status": "needs_user", "answer": "blocked"}
    )
    canceled = await _tool_result(
        registry, "finalize_task", {"status": "canceled", "answer": "stopped"}
    )
    killed = await _tool_result(
        registry, "finalize_task", {"status": "killed", "answer": "stopped"}
    )
    protocol_error = await _tool_result(
        registry,
        "finalize_task",
        {"status": "protocol_error", "answer": "bad protocol"}
    )

    assert ok["status"] == "done"
    assert unknown["status"] == "failed"
    assert blocked["status"] == "needs_user"
    assert canceled["status"] == "canceled"
    assert killed["status"] == "killed"
    assert protocol_error["status"] == "protocol_error"


@pytest.mark.asyncio
async def test_finalize_task_tool_rejects_done_with_unresolved_graph_node():
    class Store:
        async def load_workflow_graph_for_issue(self, issue_id):
            assert issue_id == "issue-1"
            return SimpleNamespace(
                nodes=[
                    SimpleNamespace(node_key="engineer", status="pending"),
                ]
            )

    registry = build_conductor_tools(project_id="project-1", store=Store(), issue_id="issue-1")

    result = await _tool_result(registry, "finalize_task", {"status": "done", "answer": "ship it"})

    assert result["status"] == "failed"
    assert "finalize rejected" in _text(result, "error")
    assert "unresolved nodes" in _text(result, "error")


@pytest.mark.asyncio
async def test_finalize_task_tool_does_not_count_skipped_as_completed_work():
    class Store:
        async def load_workflow_graph_for_issue(self, issue_id):
            return SimpleNamespace(
                nodes=[
                    SimpleNamespace(node_key="optional-docs", status="skipped"),
                ]
            )

    registry = build_conductor_tools(project_id="project-1", store=Store(), issue_id="issue-1")

    result = await _tool_result(
        registry, "finalize_task", {"status": "done", "answer": "nothing ran"}
    )

    assert result["status"] == "failed"
    assert "no completed work node" in _text(result, "error")


@pytest.mark.asyncio
async def test_finalize_task_tool_fails_closed_when_graph_missing():
    class Store:
        async def load_workflow_graph_for_issue(self, issue_id):
            return None

    registry = build_conductor_tools(project_id="project-1", store=Store(), issue_id="issue-1")

    result = await _tool_result(registry, "finalize_task", {"status": "done", "answer": "ship it"})

    assert result["status"] == "failed"
    assert "graph is missing" in _text(result, "error")


@pytest.mark.asyncio
async def test_finalize_task_tool_fails_closed_when_graph_load_raises():
    class Store:
        async def load_workflow_graph_for_issue(self, issue_id):
            raise RuntimeError("db unavailable")

    registry = build_conductor_tools(project_id="project-1", store=Store(), issue_id="issue-1")

    result = await _tool_result(registry, "finalize_task", {"status": "done", "answer": "ship it"})

    assert result["status"] == "failed"
    assert "could not be evaluated" in _text(result, "error")


@pytest.mark.asyncio
async def test_finalize_task_tool_rejects_planning_only_graph():
    class Store:
        async def load_workflow_graph_for_issue(self, issue_id):
            return SimpleNamespace(
                nodes=[
                    SimpleNamespace(node_key="product_manager", status="done"),
                    SimpleNamespace(node_key="architect", status="done"),
                ]
            )

    registry = build_conductor_tools(project_id="project-1", store=Store(), issue_id="issue-1")

    result = await _tool_result(registry, "finalize_task", {"status": "done", "answer": "planned"})

    assert result["status"] == "failed"
    assert "only has planning/design completed" in _text(result, "error")


@pytest.mark.asyncio
async def test_finalize_task_tool_rejects_implementation_without_verification():
    class Store:
        async def load_workflow_graph_for_issue(self, issue_id):
            return SimpleNamespace(
                nodes=[
                    SimpleNamespace(node_key="engineer", status="done"),
                ]
            )

    registry = build_conductor_tools(project_id="project-1", store=Store(), issue_id="issue-1")

    result = await _tool_result(
        registry, "finalize_task", {"status": "done", "answer": "implemented"}
    )

    assert result["status"] == "failed"
    assert "no verification node completed" in _text(result, "error")


@pytest.mark.asyncio
async def test_finalize_task_tool_rejects_verification_only_graph():
    class Store:
        async def load_workflow_graph_for_issue(self, issue_id):
            return SimpleNamespace(
                nodes=[
                    SimpleNamespace(node_key="qa", status="done"),
                ]
            )

    registry = build_conductor_tools(project_id="project-1", store=Store(), issue_id="issue-1")

    result = await _tool_result(registry, "finalize_task", {"status": "done", "answer": "verified"})

    assert result["status"] == "failed"
    assert "only has verification completed" in _text(result, "error")


@pytest.mark.asyncio
async def test_finalize_task_tool_accepts_implementation_with_passed_execution_evidence():
    qa_task = _passed_qa_task()
    store = _FinalizeStore(
        [
            SimpleNamespace(node_key="engineer", status="done", task_id="engineer-task"),
            SimpleNamespace(node_key="qa", status="done", task_id=qa_task.id),
        ],
        {qa_task.id: qa_task},
    )
    registry = build_conductor_tools(
        project_id="project-1", store=store, issue_id="issue-1"
    )

    result = await _tool_result(registry, "finalize_task", {"status": "done", "answer": "verified"})

    assert result["status"] == "done"
    assert result["answer"] == "verified"


@pytest.mark.asyncio
async def test_finalize_ignores_qa_artifact_changes_after_verification():
    workspace = Path(_verification_workspace())
    qa_task = _passed_qa_task(workspace_path=str(workspace))
    qa_root = workspace / "issues" / "issue-1" / "qa"
    qa_root.mkdir(parents=True, exist_ok=True)
    (qa_root / "qa_plan.json").write_text('{"status":"passed"}\n')
    (qa_root / "qa_report.md").write_text("updated presentation artifact\n")
    store = _FinalizeStore(
        [
            SimpleNamespace(node_key="engineer", status="done", task_id="engineer-task"),
            SimpleNamespace(node_key="qa", status="done", task_id=qa_task.id),
        ],
        {qa_task.id: qa_task},
        worktree_path=str(workspace),
    )
    registry = build_conductor_tools(
        project_id="project-1", store=store, issue_id="issue-1"
    )

    result = await _tool_result(
        registry,
        "finalize_task",
        {"status": "done", "answer": "artifact-only update"},
    )

    assert result["status"] == "done"


@pytest.mark.asyncio
async def test_finalize_rejects_missing_verification_fingerprint():
    qa_task = _passed_qa_task()
    report = json.loads(qa_task.result)
    report.pop("verification_state")
    qa_task.result = json.dumps(report)
    store = _FinalizeStore(
        [
            SimpleNamespace(node_key="engineer", status="done", task_id="engineer-task"),
            SimpleNamespace(node_key="qa", status="done", task_id=qa_task.id),
        ],
        {qa_task.id: qa_task},
    )
    registry = build_conductor_tools(
        project_id="project-1", store=store, issue_id="issue-1"
    )

    result = await _tool_result(
        registry,
        "finalize_task",
        {"status": "done", "answer": "missing fingerprint"},
    )

    assert result["status"] == "failed"
    assert "no valid framework-owned worktree fingerprint" in _text(result, "error")


@pytest.mark.asyncio
async def test_finalize_rejects_verification_after_the_tested_worktree_changes(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "stale@example.test"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Stale Evidence Test"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    source = root / "app.py"
    source.write_text("VALUE = 1\n")
    subprocess.run(["git", "add", "app.py"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    qa_task = _passed_qa_task(workspace_path=str(root))
    source.write_text("VALUE = 2\n")
    store = _FinalizeStore(
        [
            SimpleNamespace(node_key="engineer", status="done", task_id="engineer-task"),
            SimpleNamespace(node_key="qa", status="done", task_id=qa_task.id),
        ],
        {qa_task.id: qa_task},
        worktree_path=str(root),
    )
    registry = build_conductor_tools(
        project_id="project-1", store=store, issue_id="issue-1"
    )

    result = await _tool_result(
        registry,
        "finalize_task",
        {"status": "done", "answer": "stale verification"},
    )

    assert result["status"] == "failed"
    assert "worktree changed after testing" in _text(result, "error")


@pytest.mark.asyncio
async def test_finalize_rejects_verification_after_untracked_code_is_added(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "untracked@example.test"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Untracked Evidence Test"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    (root / "README.md").write_text("verified state\n")
    subprocess.run(["git", "add", "README.md"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    qa_task = _passed_qa_task(workspace_path=str(root))
    (root / "new_feature.py").write_text("VALUE = 1\n")
    store = _FinalizeStore(
        [
            SimpleNamespace(node_key="engineer", status="done", task_id="engineer-task"),
            SimpleNamespace(node_key="qa", status="done", task_id=qa_task.id),
        ],
        {qa_task.id: qa_task},
        worktree_path=str(root),
    )
    registry = build_conductor_tools(
        project_id="project-1", store=store, issue_id="issue-1"
    )

    result = await _tool_result(
        registry,
        "finalize_task",
        {"status": "done", "answer": "untracked code change"},
    )

    assert result["status"] == "failed"
    assert "worktree changed after testing" in _text(result, "error")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("acceptance_criteria", "confirmed", "reason"),
    [
        ([], False, "no acceptance criteria"),
        (["Anonymous requests return 401"], False, "not user-confirmed"),
    ],
)
async def test_finalize_task_tool_requires_confirmed_acceptance_criteria(
    acceptance_criteria,
    confirmed,
    reason,
):
    qa_task = _passed_qa_task()
    store = _FinalizeStore(
        [
            SimpleNamespace(node_key="engineer", status="done", task_id="engineer-task"),
            SimpleNamespace(node_key="qa", status="done", task_id=qa_task.id),
        ],
        {qa_task.id: qa_task},
        acceptance_criteria=acceptance_criteria,
        confirmed=confirmed,
    )
    registry = build_conductor_tools(
        project_id="project-1", store=store, issue_id="issue-1"
    )

    result = await _tool_result(
        registry, "finalize_task", {"status": "done", "answer": "verified"}
    )

    assert result["status"] == "failed"
    assert reason in _text(result, "error")


@pytest.mark.asyncio
async def test_finalize_rejects_passing_command_without_criterion_evidence():
    qa_task = _passed_qa_task()
    report = json.loads(qa_task.result)
    report.pop("criterion_evidence")
    qa_task.result = json.dumps(report)
    store = _FinalizeStore(
        [
            SimpleNamespace(node_key="engineer", status="done", task_id="engineer-task"),
            SimpleNamespace(node_key="qa", status="done", task_id=qa_task.id),
        ],
        {qa_task.id: qa_task},
    )
    registry = build_conductor_tools(
        project_id="project-1", store=store, issue_id="issue-1"
    )

    result = await _tool_result(
        registry, "finalize_task", {"status": "done", "answer": "generic green"}
    )

    assert result["status"] == "failed"
    assert "no criterion-level acceptance evidence" in _text(result, "error")


@pytest.mark.asyncio
async def test_finalize_rejects_trivial_true_as_criterion_evidence():
    qa_task = _passed_qa_task()
    report = json.loads(qa_task.result)
    report["execution_results"] = [
        {
            "command": "true",
            "exit_code": 0,
            "stdout": "",
            "stderr": "",
            "duration_s": 0.01,
        }
    ]
    report["criterion_evidence"] = [
        {
            "criterion_index": 0,
            "criterion": _DEFAULT_ACCEPTANCE_CRITERION,
            "command": "true",
            "execution_result_index": 0,
            "evidence": "command exited with code 0",
        }
    ]
    qa_task.result = json.dumps(report)
    store = _FinalizeStore(
        [
            SimpleNamespace(node_key="engineer", status="done", task_id="engineer-task"),
            SimpleNamespace(node_key="qa", status="done", task_id=qa_task.id),
        ],
        {qa_task.id: qa_task},
    )
    registry = build_conductor_tools(
        project_id="project-1", store=store, issue_id="issue-1"
    )

    result = await _tool_result(
        registry, "finalize_task", {"status": "done", "answer": "noop green"}
    )

    assert result["status"] == "failed"
    assert "trivial command" in _text(result, "error")


@pytest.mark.asyncio
async def test_finalize_rejects_reused_command_across_acceptance_criteria():
    criteria = ["Anonymous requests return 401", "Wrong tokens return 401"]
    qa_task = _passed_qa_task()
    report = json.loads(qa_task.result)
    report["criterion_evidence"] = [
        {
            "criterion_index": index,
            "criterion": criterion,
            "command": "pytest -q",
            "execution_result_index": 0,
            "evidence": "1 passed",
        }
        for index, criterion in enumerate(criteria)
    ]
    qa_task.result = json.dumps(report)
    store = _FinalizeStore(
        [
            SimpleNamespace(node_key="engineer", status="done", task_id="engineer-task"),
            SimpleNamespace(node_key="qa", status="done", task_id=qa_task.id),
        ],
        {qa_task.id: qa_task},
        acceptance_criteria=criteria,
    )
    registry = build_conductor_tools(
        project_id="project-1", store=store, issue_id="issue-1"
    )

    result = await _tool_result(
        registry, "finalize_task", {"status": "done", "answer": "suite reused"}
    )

    assert result["status"] == "failed"
    assert "reuses another criterion's verification command" in _text(result, "error")


@pytest.mark.asyncio
async def test_finalize_task_tool_rejects_role_and_status_without_execution_evidence():
    qa_task = SimpleNamespace(
        id="qa-task",
        status="done",
        result=json.dumps(
            {
                "status": "passed",
                "commands_run": ["pytest -q → exit 0"],
            }
        ),
    )
    store = _FinalizeStore(
        [
            SimpleNamespace(node_key="engineer", status="done", task_id="engineer-task"),
            SimpleNamespace(node_key="qa", status="done", task_id=qa_task.id),
        ],
        {qa_task.id: qa_task},
    )
    registry = build_conductor_tools(
        project_id="project-1", store=store, issue_id="issue-1"
    )

    result = await _tool_result(
        registry, "finalize_task", {"status": "done", "answer": "self-reported pass"}
    )

    assert result["status"] == "failed"
    assert "no verification node with auditable passed" in _text(result, "error")
    assert "no structured execution results" in _text(result, "error")


@pytest.mark.asyncio
async def test_finalize_task_tool_rejects_unverified_qa_task_even_with_stale_done_node():
    qa_task = _passed_qa_task()
    qa_task.status = "failed"
    qa_task.result = json.dumps(
        {
            "status": "unverified",
            "execution_results": [],
        }
    )
    store = _FinalizeStore(
        [
            SimpleNamespace(node_key="engineer", status="done", task_id="engineer-task"),
            SimpleNamespace(node_key="qa", status="done", task_id=qa_task.id),
        ],
        {qa_task.id: qa_task},
    )
    registry = build_conductor_tools(
        project_id="project-1", store=store, issue_id="issue-1"
    )

    result = await _tool_result(
        registry, "finalize_task", {"status": "done", "answer": "unverified"}
    )

    assert result["status"] == "failed"
    assert "verification task status is 'failed'" in _text(result, "error")


@pytest.mark.asyncio
async def test_finalize_task_tool_rejects_unreadable_verification_report():
    qa_task = SimpleNamespace(id="qa-task", status="done", result="not-json")
    store = _FinalizeStore(
        [
            SimpleNamespace(node_key="engineer", status="done", task_id="engineer-task"),
            SimpleNamespace(node_key="qa", status="done", task_id=qa_task.id),
        ],
        {qa_task.id: qa_task},
    )
    registry = build_conductor_tools(
        project_id="project-1", store=store, issue_id="issue-1"
    )

    result = await _tool_result(
        registry, "finalize_task", {"status": "done", "answer": "unreadable"}
    )

    assert result["status"] == "failed"
    assert "verification task report is not valid JSON" in _text(result, "error")


@pytest.mark.asyncio
async def test_finalize_task_tool_accepts_parallel_engineer_with_verification():
    qa_task = _passed_qa_task()
    store = _FinalizeStore(
        [
            SimpleNamespace(
                node_key="engineer_frontend", status="done", task_id="frontend-task"
            ),
            SimpleNamespace(
                node_key="engineer_backend", status="done", task_id="backend-task"
            ),
            SimpleNamespace(node_key="qa", status="done", task_id=qa_task.id),
        ],
        {qa_task.id: qa_task},
    )
    registry = build_conductor_tools(
        project_id="project-1", store=store, issue_id="issue-1"
    )

    result = await _tool_result(registry, "finalize_task", {"status": "done", "answer": "verified"})

    assert result["status"] == "done"


@pytest.mark.asyncio
async def test_finalize_task_tool_accepts_operations_engineer_with_verification():
    qa_task = _passed_qa_task()
    store = _FinalizeStore(
        [
            SimpleNamespace(
                node_key="operations_engineer", status="done", task_id="operations-task"
            ),
            SimpleNamespace(node_key="qa", status="done", task_id=qa_task.id),
        ],
        {qa_task.id: qa_task},
    )
    registry = build_conductor_tools(
        project_id="project-1", store=store, issue_id="issue-1"
    )

    result = await _tool_result(
        registry, "finalize_task", {"status": "done", "answer": "scripts verified"}
    )

    assert result["status"] == "done"
    assert result["answer"] == "scripts verified"


@pytest.mark.asyncio
async def test_finalize_task_tool_accepts_delivery_specialist_with_verification():
    qa_task = _passed_qa_task()
    store = _FinalizeStore(
        [
            SimpleNamespace(
                node_key="specialist:doc_writer", status="done", task_id="docs-task"
            ),
            SimpleNamespace(node_key="qa", status="done", task_id=qa_task.id),
        ],
        {qa_task.id: qa_task},
    )
    registry = build_conductor_tools(
        project_id="project-1", store=store, issue_id="issue-1"
    )

    result = await _tool_result(
        registry, "finalize_task", {"status": "done", "answer": "docs verified"}
    )

    assert result["status"] == "done"
    assert result["answer"] == "docs verified"


@pytest.mark.asyncio
async def test_finalize_task_tool_rejects_unclassified_specialist_only_graph():
    class Store:
        async def load_workflow_graph_for_issue(self, issue_id):
            return SimpleNamespace(
                nodes=[
                    SimpleNamespace(node_key="specialist:log_summarizer", status="done"),
                ]
            )

    registry = build_conductor_tools(project_id="project-1", store=Store(), issue_id="issue-1")

    result = await _tool_result(
        registry, "finalize_task", {"status": "done", "answer": "summarized"}
    )

    assert result["status"] == "failed"
    assert "no recognized implementation or delivery evidence" in _text(result, "error")


@pytest.mark.asyncio
async def test_finalize_task_tool_rejects_planning_plus_unclassified_specialist_graph():
    class Store:
        async def load_workflow_graph_for_issue(self, issue_id):
            return SimpleNamespace(
                nodes=[
                    SimpleNamespace(node_key="architect", status="done"),
                    SimpleNamespace(node_key="specialist:log_summarizer", status="done"),
                ]
            )

    registry = build_conductor_tools(project_id="project-1", store=Store(), issue_id="issue-1")

    result = await _tool_result(
        registry, "finalize_task", {"status": "done", "answer": "described"}
    )

    assert result["status"] == "failed"
    assert "no recognized implementation or delivery evidence" in _text(result, "error")


@pytest.mark.asyncio
async def test_finalize_task_tool_rejects_planning_with_verification_but_no_delivery():
    class Store:
        async def load_workflow_graph_for_issue(self, issue_id):
            return SimpleNamespace(
                nodes=[
                    SimpleNamespace(node_key="architect", status="done"),
                    SimpleNamespace(node_key="qa", status="done"),
                ]
            )

    registry = build_conductor_tools(project_id="project-1", store=Store(), issue_id="issue-1")

    result = await _tool_result(registry, "finalize_task", {"status": "done", "answer": "reviewed"})

    assert result["status"] == "failed"
    assert "no recognized implementation or delivery evidence" in _text(result, "error")


@pytest.mark.asyncio
async def test_conductor_loop_rejects_clarification_mixed_with_dispatch_without_side_effects():
    dispatched = False
    calls = []

    async def fake_llm(messages, tools):
        calls.append(messages)
        if len(calls) == 1:
            return {
                "stop_reason": "tool_use",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_question",
                        "name": "request_user_clarification",
                        "input": {"question": "Which path should we take?"},
                    },
                    {
                        "type": "tool_use",
                        "id": "toolu_dispatch",
                        "name": "dispatch_subagent",
                        "input": {"role": "engineer"},
                    },
                ],
            }
        assert "request_user_clarification cannot be used in the same turn" in calls[-1][-1][
            "content"
        ][0]["content"]
        return {
            "stop_reason": "tool_use",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_final",
                    "name": "finalize_task",
                    "input": {"status": "blocked", "answer": "Need user input first."},
                }
            ],
        }

    async def request_user_clarification(tool_input):
        return {"question": tool_input["question"]}

    async def dispatch_subagent(tool_input):
        nonlocal dispatched
        dispatched = True
        return {"status": "done", "role": tool_input["role"]}

    async def finalize_task(tool_input):
        return tool_input

    result = await run_conductor_loop(
        prompt="Ask if needed.",
        llm=fake_llm,
        tools={
            "request_user_clarification": request_user_clarification,
            "dispatch_subagent": dispatch_subagent,
            "finalize_task": finalize_task,
        },
        tool_definitions=[
            {"name": "request_user_clarification"},
            {"name": "dispatch_subagent"},
            {"name": "finalize_task"},
        ],
        max_turns=2,
    )

    assert result.status == "blocked"
    assert dispatched is False


@pytest.mark.asyncio
async def test_seal_graph_load_failure_still_updates_issue_status():
    class Store:
        def __init__(self):
            self.saved_issue = None

        async def load_workflow_graph_for_issue(self, issue_id):
            raise RuntimeError("graph unavailable")

        async def save_codex_issue(self, issue):
            self.saved_issue = issue

        async def load_project(self, project_id):
            return None

    class Bus:
        def __init__(self):
            self.events = []

        async def append(self, event):
            self.events.append(event)

    issue = CodexIssue(
        id="issue-1",
        project_id="project-1",
        session_id="session-1",
        title="Seal graph",
        status="in_progress",
        updated_at=None,
    )
    store = Store()
    bus = Bus()

    await _seal_graph_and_issue_status(
        store=store,
        issue=issue,
        event_bus=bus,
        result_status="failed",
    )

    assert store.saved_issue is issue
    assert issue.status == "failed"
    assert any(
        event.get("type") == "issue_updated" and event.get("status") == "failed"
        for event in bus.events
    )


@pytest.mark.asyncio
async def test_conductor_loop_rejects_finalize_mixed_with_other_tools_until_next_turn():
    calls = []

    async def fake_llm(messages, tools):
        calls.append(messages)
        if len(calls) == 1:
            return {
                "stop_reason": "tool_use",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_dispatch",
                        "name": "dispatch_subagent",
                        "input": {"role": "qa"},
                    },
                    {
                        "type": "tool_use",
                        "id": "toolu_final",
                        "name": "finalize_task",
                        "input": {"status": "done", "answer": "too early"},
                    },
                ],
            }
        assert "finalize_task cannot be used in the same turn" in calls[-1][-1]["content"][1]["content"]
        return {
            "stop_reason": "tool_use",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_final_2",
                    "name": "finalize_task",
                    "input": {"status": "done", "answer": "after reading results"},
                }
            ],
        }

    async def dispatch_subagent(tool_input):
        return {"status": "done", "role": tool_input["role"]}

    async def finalize_task(tool_input):
        return tool_input

    result = await run_conductor_loop(
        prompt="Run QA then finish.",
        llm=fake_llm,
        tools={"dispatch_subagent": dispatch_subagent, "finalize_task": finalize_task},
        tool_definitions=[{"name": "dispatch_subagent"}, {"name": "finalize_task"}],
    )

    assert result.status == "done"
    assert result.final_text == "after reading results"
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_conductor_loop_keeps_non_finalize_tools_concurrent_when_finalize_is_mixed():
    calls = []
    state = {"current": 0, "peak": 0}

    async def fake_llm(messages, tools):
        calls.append(messages)
        if len(calls) == 1:
            return {
                "stop_reason": "tool_use",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_dispatch_a",
                        "name": "dispatch_subagent",
                        "input": {"role": "qa"},
                    },
                    {
                        "type": "tool_use",
                        "id": "toolu_dispatch_b",
                        "name": "dispatch_reviewer",
                        "input": {"role": "specialist:security_reviewer"},
                    },
                    {
                        "type": "tool_use",
                        "id": "toolu_final",
                        "name": "finalize_task",
                        "input": {"status": "done", "answer": "too early"},
                    },
                ],
            }
        result_blocks = calls[-1][-1]["content"]
        assert [block["tool_use_id"] for block in result_blocks] == [
            "toolu_dispatch_a",
            "toolu_dispatch_b",
            "toolu_final",
        ]
        assert "finalize_task cannot be used in the same turn" in result_blocks[2]["content"]
        return {
            "stop_reason": "tool_use",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_final_2",
                    "name": "finalize_task",
                    "input": {"status": "done", "answer": "after reading results"},
                }
            ],
        }

    async def _tracked_tool(tool_input):
        state["current"] += 1
        state["peak"] = max(state["peak"], state["current"])
        await asyncio.sleep(0.02)
        state["current"] -= 1
        return {"status": "done", "role": tool_input["role"]}

    async def finalize_task(tool_input):
        return tool_input

    result = await run_conductor_loop(
        prompt="Run reviewers then finish.",
        llm=fake_llm,
        tools={
            "dispatch_subagent": _tracked_tool,
            "dispatch_reviewer": _tracked_tool,
            "finalize_task": finalize_task,
        },
        tool_definitions=[
            {"name": "dispatch_subagent"},
            {"name": "dispatch_reviewer"},
            {"name": "finalize_task"},
        ],
    )

    assert result.status == "done"
    assert state["peak"] == 2


@pytest.mark.asyncio
async def test_conductor_loop_stops_for_user_clarification():
    async def fake_llm(messages, tools):
        return {
            "stop_reason": "tool_use",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_clarify",
                    "name": "request_user_clarification",
                    "input": {"question": "Which deployment target should we use?"},
                }
            ],
        }

    async def request_user_clarification(tool_input):
        return {"status": "waiting_for_user", "question": tool_input["question"]}

    result = await run_conductor_loop(
        prompt="Deploy the project.",
        llm=fake_llm,
        tools={"request_user_clarification": request_user_clarification},
        tool_definitions=[{"name": "request_user_clarification"}],
    )

    assert result.status == "needs_user"
    assert result.final_text == "Which deployment target should we use?"
    assert result.turn_count == 1


@pytest.mark.asyncio
async def test_conductor_loop_records_turn_timeline():
    recorded = []

    async def fake_llm(messages, tools):
        return {
            "stop_reason": "tool_use",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_final",
                    "name": "finalize_task",
                    "input": {"answer": "captured", "status": "done"},
                }
            ],
        }

    async def finalize_task(tool_input):
        return tool_input

    await run_conductor_loop(
        prompt="Record turns.",
        llm=fake_llm,
        tools={"finalize_task": finalize_task},
        tool_definitions=[{"name": "finalize_task"}],
        turn_recorder=lambda **turn: recorded.append(
            (turn["kind"], turn["turn_index"], turn["sub_index"])
        ),
    )

    assert recorded == [
        ("llm_request", 0, 0),
        ("llm_response", 0, 0),
        ("tool_use", 0, 1),
        ("tool_result", 0, 1),
        ("finalize", 0, 1),
    ]


@pytest.mark.asyncio
async def test_conductor_loop_passes_token_delta_callback_to_llm():
    deltas = []

    async def fake_llm(messages, tools, on_token_delta=None):
        assert on_token_delta is not None
        await on_token_delta(
            turn_index=0,
            sub_index=0,
            content_block_index=0,
            kind="text",
            chunk="hello",
        )
        return {
            "stop_reason": "tool_use",
            "content": [
                {"type": "text", "text": "hello"},
                {
                    "type": "tool_use",
                    "id": "toolu_final",
                    "name": "finalize_task",
                    "input": {"status": "done", "answer": "hello"},
                },
            ],
            "usage": {"output_tokens": 1},
        }

    async def capture_delta(**payload):
        deltas.append(payload)

    async def finalize_task(tool_input):
        return tool_input

    result = await run_conductor_loop(
        prompt="Stream a token.",
        llm=fake_llm,
        tools={"finalize_task": finalize_task},
        tool_definitions=[{"name": "finalize_task"}],
        on_token_delta=capture_delta,
    )

    assert result.status == "done"
    assert deltas == [
        {
            "turn_index": 0,
            "sub_index": 0,
            "content_block_index": 0,
            "kind": "text",
            "chunk": "hello",
        }
    ]


@pytest.mark.asyncio
async def test_conductor_loop_injects_user_interjection_before_next_llm_call():
    calls = []
    pending_inbox = [["skip architect, go straight to engineer"], []]

    async def fake_llm(messages, tools):
        calls.append(messages)
        if len(calls) == 1:
            return {
                "stop_reason": "tool_use",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_memory",
                        "name": "retrieve_cold_memory",
                        "input": {"query": "plan"},
                    }
                ],
            }
        assert any(
            entry.get("role") == "user"
            and entry.get("content")
            == "[USER INTERJECTION] skip architect, go straight to engineer"
            for entry in messages
        )
        return {
            "stop_reason": "tool_use",
            "content": [
                {"type": "text", "text": "Skipping architect."},
                {
                    "type": "tool_use",
                    "id": "toolu_final",
                    "name": "finalize_task",
                    "input": {"status": "done", "answer": "Skipping architect."},
                },
            ],
        }

    async def retrieve_cold_memory(tool_input):
        return {"memories": ["plan"]}  # pragma: no cover - value asserted through flow

    async def drain_inbox():
        return pending_inbox.pop(0) if pending_inbox else []

    async def finalize_task(tool_input):
        return tool_input

    result = await run_conductor_loop(
        prompt="Plan this issue.",
        llm=fake_llm,
        tools={
            "retrieve_cold_memory": retrieve_cold_memory,
            "finalize_task": finalize_task,
        },
        tool_definitions=[{"name": "retrieve_cold_memory"}, {"name": "finalize_task"}],
        inbox_drain=drain_inbox,
    )

    assert result.status == "done"
    assert result.final_text == "Skipping architect."


@pytest.mark.asyncio
async def test_conductor_loop_runs_multiple_tool_uses_in_one_turn_concurrently():
    """A single turn that emits several tool_use blocks executes them in parallel
    (overlapping in time) and feeds back tool_results in the original order."""
    running = 0
    max_concurrent = 0

    async def slow_dispatch(tool_input):
        nonlocal running, max_concurrent
        running += 1
        max_concurrent = max(max_concurrent, running)
        try:
            await asyncio.sleep(0.05)
            return {"role": tool_input.get("role"), "status": "done"}
        finally:
            running -= 1

    calls = []

    async def fake_llm(messages, tools):
        calls.append(messages)
        if len(calls) == 1:
            return {
                "stop_reason": "tool_use",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "dispatch_subagent",
                        "input": {"role": "reviewer_a"},
                    },
                    {
                        "type": "tool_use",
                        "id": "t2",
                        "name": "dispatch_subagent",
                        "input": {"role": "reviewer_b"},
                    },
                    {
                        "type": "tool_use",
                        "id": "t3",
                        "name": "dispatch_subagent",
                        "input": {"role": "reviewer_c"},
                    },
                ],
            }
        # tool_results must come back aligned with the original tool_use ids/order.
        blocks = messages[-1]["content"]
        assert [b["tool_use_id"] for b in blocks] == ["t1", "t2", "t3"]
        return {
            "stop_reason": "tool_use",
            "content": [
                {"type": "text", "text": "all reviewed"},
                {
                    "type": "tool_use",
                    "id": "toolu_final",
                    "name": "finalize_task",
                    "input": {"status": "done", "answer": "all reviewed"},
                },
            ],
        }

    async def finalize_task(tool_input):
        return tool_input

    result = await run_conductor_loop(
        prompt="Review from three angles.",
        llm=fake_llm,
        tools={"dispatch_subagent": slow_dispatch, "finalize_task": finalize_task},
        tool_definitions=[{"name": "dispatch_subagent"}, {"name": "finalize_task"}],
    )

    assert result.final_text == "all reviewed"
    assert sum(event["name"] == "dispatch_subagent" for event in result.tool_events) == 3
    # If execution were serial, max_concurrent would be 1. Parallel => 3.
    assert max_concurrent == 3


@pytest.mark.asyncio
async def test_conductor_loop_seals_max_wall_when_wall_clock_exceeded():
    """The whole-loop wall-clock ceiling stops a loop that never finalizes, even
    if it is still under max_turns."""

    async def fake_llm(messages, tools):
        # Always asks for more work; would loop until max_turns without the ceiling.
        return {
            "stop_reason": "tool_use",
            "content": [
                {
                    "type": "tool_use",
                    "id": "tx",
                    "name": "dispatch_subagent",
                    "input": {"role": "engineer"},
                }
            ],
        }

    async def dispatch(tool_input):
        await asyncio.sleep(0.03)
        return {"status": "done"}

    result = await run_conductor_loop(
        prompt="Never-ending work.",
        llm=fake_llm,
        tools={"dispatch_subagent": dispatch},
        tool_definitions=[{"name": "dispatch_subagent"}],
        max_turns=50,
        max_wall_s=0.05,
    )

    assert result.status == "max_wall"
    assert result.turn_count < 50


@pytest.mark.asyncio
async def test_conductor_loop_wall_clock_disabled_when_zero():
    """max_wall_s=0 disables the ceiling; the loop runs to its natural finalize."""

    async def fake_llm(messages, tools):
        return {
            "stop_reason": "tool_use",
            "content": [
                {
                    "type": "tool_use",
                    "id": "f",
                    "name": "finalize_task",
                    "input": {"status": "done", "answer": "ok"},
                }
            ],
        }

    async def finalize_task(tool_input):
        return tool_input

    result = await run_conductor_loop(
        prompt="Quick.",
        llm=fake_llm,
        tools={"finalize_task": finalize_task},
        tool_definitions=[{"name": "finalize_task"}],
        max_wall_s=0,
    )
    assert result.status == "done"


@pytest.mark.asyncio
async def test_conductor_tools_expose_phase6_tool_schema_and_memory_lookup(tmp_path):
    from app.adapters.async_sqlite_store import AsyncSQLiteStore

    store = AsyncSQLiteStore(tmp_path / "console.db")
    await store.save_project_memory_embedding(
        ProjectMemoryEmbedding(
            id="mem-1",
            project_id="project-1",
            source_kind="warm_summary",
            source_id="sum-1",
            summary_text="auth token regression happened in refresh flow",
        )
    )

    registry = build_conductor_tools(project_id="project-1", store=store)
    await store.close()

    names = {tool["name"] for tool in registry.definitions}
    assert names == {
        "retrieve_cold_memory",
        "dispatch_subagent",
        "dispatch_batch",
        "spawn_custom_subagent",
        "inject_context_into_node",
        "request_user_clarification",
        "finalize_task",
    }
    memory = await _tool_result(registry, "retrieve_cold_memory", {"query": "auth token", "top_k": 2})
    assert memory["memories"] == ["auth token regression happened in refresh flow"]


def test_llm_runner_extracts_anthropic_tool_use_blocks():
    response: JsonObject = {
        "content": [
            {"type": "text", "text": "I need memory."},
            {
                "type": "tool_use",
                "id": "toolu_1",
                "name": "retrieve_cold_memory",
                "input": {"query": "auth"},
            },
            {"type": "tool_use", "id": "toolu_bad", "name": "", "input": "bad"},
        ]
    }

    assert extract_tool_use_blocks(response) == [
        {
            "type": "tool_use",
            "id": "toolu_1",
            "name": "retrieve_cold_memory",
            "input": {"query": "auth"},
        }
    ]
