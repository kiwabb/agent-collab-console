"""Tests for /api/codex/tasks/{id}/chat endpoint (P2)."""

from datetime import datetime  # noqa: I001

import pytest
from fastapi.testclient import TestClient

from app.domain.models import CodexSession, CodexTask, ExecutionProcess
import app.interfaces.api as api_module
from app.main import app


class ChatStoreStub:
    """In-memory store stub for chat endpoint tests."""

    def __init__(self, *, session, tasks):
        self.session = session
        self.tasks = {task.id: task for task in tasks}
        self.execution_processes: dict[str, ExecutionProcess] = {}
        self.messages: list[dict] = []
        self.start_task_run_calls: list[dict] = []

    async def load_codex_session(self, session_id: str):
        return self.session if session_id == self.session.id else None

    async def load_codex_workspace(self, session_id: str):
        return self.session if session_id == self.session.id else None

    async def load_codex_task(self, task_id: str):
        return self.tasks.get(task_id)

    async def save_codex_task(self, task):
        self.tasks[task.id] = task

    async def list_codex_tasks(self, session_id: str | None = None, issue_id: str | None = None):
        return []

    async def save_codex_task_message(self, message):
        self.messages.append(
            {
                "id": message.id,
                "task_id": message.task_id,
                "execution_process_id": message.execution_process_id,
                "role": message.role,
                "content": message.content,
            }
        )

    async def list_codex_task_messages(self, task_id: str, execution_process_id: str | None = None):
        result = [m for m in self.messages if m["task_id"] == task_id]
        if execution_process_id is not None:
            result = [m for m in result if m["execution_process_id"] == execution_process_id]
        return result

    async def save_execution_process(self, ep):
        self.execution_processes[ep.id] = ep

    async def load_execution_process(self, ep_id):
        return self.execution_processes.get(ep_id)

    async def update_execution_process_status(self, *args, **kwargs):
        pass

    async def load_runtime_catalog(self):
        return None

    async def save_runtime_catalog(self, catalog):
        pass


def _make_task(
    *,
    workspace_path,
    status="done",
    result="canonical task result",
    resume_session_id="cli-session-7",
):
    now = datetime.now()
    return CodexTask(
        id="task-1",
        session_id="ws-1",
        issue_id="issue-1",
        phase="requirements",
        title="需求 - 购物车",
        prompt="分析需求并输出PRD",
        role="product_manager",
        executor="codex",
        status=status,
        result=result,
        workspace_path=workspace_path,
        resume_session_id=resume_session_id,
        resume_message_id="msg-77",
        created_at=now,
        updated_at=now,
    )


def _make_session(workspace_path):
    now = datetime.now()
    return CodexSession(
        id="ws-1", title="Workspace", cwd=workspace_path, created_at=now, last_active_at=now
    )


@pytest.fixture
def isolated_client():
    return TestClient(app)


# ---------------------------------------------------------------------------
# Endpoint shape
# ---------------------------------------------------------------------------


def test_chat_endpoint_creates_user_message_and_returns_ep(isolated_client, monkeypatch, tmp_path):
    session = _make_session(str(tmp_path))
    task = _make_task(workspace_path=str(tmp_path))
    store = ChatStoreStub(session=session, tasks=[task])
    monkeypatch.setattr(api_module, "codex_store", store)

    # Stub start_task_run to just create an EP marked kind=chat (mirrors what the
    # real runner should do). Captures kwargs so we can assert kind propagation.
    captured = {}

    async def _fake_start_task_run(
        t,
        *,
        prompt_override=None,
        resume_session_id=None,
        resume_message_id=None,
        kind="initial",
        triggering_message_id=None,
    ):
        captured["task_id"] = t.id
        captured["kind"] = kind
        captured["triggering_message_id"] = triggering_message_id
        captured["prompt_override"] = prompt_override
        captured["resume_session_id"] = resume_session_id
        ep = ExecutionProcess(
            id="ep-chat-1",
            task_id=t.id,
            session_id=t.session_id,
            status="Running",
            kind=kind,
            triggering_message_id=triggering_message_id,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        await store.save_execution_process(ep)
        t.last_execution_process_id = ep.id
        return ep

    class _RunnerStub:
        async def start_task_run(self, t, **kwargs):
            return await _fake_start_task_run(t, **kwargs)

    monkeypatch.setattr(api_module, "_get_task_runner", lambda: _RunnerStub())

    response = isolated_client.post(
        "/api/codex/tasks/task-1/chat",
        json={"content": "你好，麻烦解释一下需求里的第3点"},  # noqa: RUF001
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["message"]["role"] == "user"
    assert payload["message"]["content"] == "你好，麻烦解释一下需求里的第3点"  # noqa: RUF001
    assert payload["execution_process"]["kind"] == "chat"
    assert payload["execution_process"]["triggering_message_id"] == payload["message"]["id"]
    assert captured["kind"] == "chat"
    assert captured["prompt_override"] == "你好，麻烦解释一下需求里的第3点"  # noqa: RUF001
    # Chat should resume the existing CLI session for context continuity
    assert captured["resume_session_id"] == "cli-session-7"


def test_chat_rejects_running_task(isolated_client, monkeypatch, tmp_path):
    session = _make_session(str(tmp_path))
    task = _make_task(workspace_path=str(tmp_path), status="running")
    store = ChatStoreStub(session=session, tasks=[task])
    monkeypatch.setattr(api_module, "codex_store", store)

    # When start_task_run rejects, api layer translates to 409
    class _RunnerStub:
        async def start_task_run(self, t, **kwargs):
            raise ValueError("Task already running")

    monkeypatch.setattr(api_module, "_get_task_runner", lambda: _RunnerStub())

    response = isolated_client.post(
        "/api/codex/tasks/task-1/chat",
        json={"content": "hello"},
    )
    assert response.status_code == 409


def test_legacy_messages_endpoint_routes_to_chat(isolated_client, monkeypatch, tmp_path):
    """Old /messages endpoint must still work and produce a chat-kind EP."""
    session = _make_session(str(tmp_path))
    task = _make_task(workspace_path=str(tmp_path))
    store = ChatStoreStub(session=session, tasks=[task])
    monkeypatch.setattr(api_module, "codex_store", store)

    captured_kinds: list[str] = []

    class _RunnerStub:
        async def start_task_run(self, t, *, kind="initial", triggering_message_id=None, **_):
            captured_kinds.append(kind)
            ep = ExecutionProcess(
                id=f"ep-legacy-{len(captured_kinds)}",
                task_id=t.id,
                session_id=t.session_id,
                status="Running",
                kind=kind,
                triggering_message_id=triggering_message_id,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
            await store.save_execution_process(ep)
            t.last_execution_process_id = ep.id
            return ep

    monkeypatch.setattr(api_module, "_get_task_runner", lambda: _RunnerStub())

    response = isolated_client.post(
        "/api/codex/tasks/task-1/messages",
        json={"content": "legacy say hi"},
    )
    assert response.status_code == 201, response.text
    assert captured_kinds == ["chat"]


# ---------------------------------------------------------------------------
# _mark_task_done behavior (process_runtime_common) — chat must NOT clobber
# task.result or trigger artifact persistence.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_task_done_skips_refresh_for_chat_ep(tmp_path):
    """For EP.kind == 'chat', _mark_task_done must keep task.result unchanged
    and skip refresh_task_result (which is what runs persist_result)."""
    from app.application.process_runtime_common import ProcessEntry  # noqa: F401, I001

    from app.adapters.async_sqlite_store import AsyncSQLiteStore

    db = AsyncSQLiteStore(str(tmp_path / "db.sqlite"))

    now = datetime.now()
    session = CodexSession(
        id="ws-1", title="W", cwd=str(tmp_path), created_at=now, last_active_at=now
    )
    await db.save_codex_session(session)

    task = CodexTask(
        id="task-1",
        session_id="ws-1",
        phase="requirements",
        title="t",
        prompt="p",
        role="product_manager",
        executor="codex",
        status="running",
        result="ORIGINAL_CANONICAL_RESULT",  # this MUST survive a chat run
        workspace_path=str(tmp_path),
        last_execution_process_id="ep-chat-x",
        created_at=now,
        updated_at=now,
    )
    await db.save_codex_task(task)

    ep = ExecutionProcess(
        id="ep-chat-x",
        task_id="task-1",
        session_id="ws-1",
        status="Running",
        kind="chat",
        triggering_message_id="msg-1",
        created_at=now,
        updated_at=now,
    )
    await db.save_execution_process(ep)

    # Build a runtime-common-like runtime with our store and a refresh_task_result spy
    refresh_calls: list[str] = []

    async def _refresh(t):
        refresh_calls.append(t.id)

    # We instantiate the base runtime directly to test _mark_task_done
    from app.application.process_runtime_common import BaseProcessRuntime

    runtime = BaseProcessRuntime(
        codex_store=db,
        log_store=db,
        data_dir=str(tmp_path),
        event_bus=None,
        refresh_task_result=_refresh,
    )

    entry = type("E", (), {"result_text": "你好！我是 Codex", "help_requested": False})()  # noqa: RUF001

    await runtime._mark_task_done("task-1", entry)

    reloaded = await db.load_codex_task("task-1")
    # chat must preserve canonical task.result
    assert reloaded.result == "ORIGINAL_CANONICAL_RESULT"
    # refresh_task_result must NOT be invoked for chat
    assert refresh_calls == []
    # task transitions back to done
    assert reloaded.status == "done"


@pytest.mark.asyncio
async def test_mark_task_done_runs_refresh_for_initial_ep(tmp_path):
    """For EP.kind == 'initial', behavior is unchanged: task.result is updated and refresh runs."""
    from app.application.process_runtime_common import ProcessEntry, BaseProcessRuntime  # noqa: F401, I001
    from app.adapters.async_sqlite_store import AsyncSQLiteStore

    db = AsyncSQLiteStore(str(tmp_path / "db.sqlite"))

    now = datetime.now()
    session = CodexSession(
        id="ws-1", title="W", cwd=str(tmp_path), created_at=now, last_active_at=now
    )
    await db.save_codex_session(session)

    task = CodexTask(
        id="task-1",
        session_id="ws-1",
        phase="requirements",
        title="t",
        prompt="p",
        role="product_manager",
        executor="codex",
        status="running",
        result=None,
        workspace_path=str(tmp_path),
        last_execution_process_id="ep-initial-x",
        created_at=now,
        updated_at=now,
    )
    await db.save_codex_task(task)

    ep = ExecutionProcess(
        id="ep-initial-x",
        task_id="task-1",
        session_id="ws-1",
        status="Running",
        kind="initial",
        created_at=now,
        updated_at=now,
    )
    await db.save_execution_process(ep)

    refresh_calls: list[str] = []

    async def _refresh(t):
        refresh_calls.append(t.id)

    runtime = BaseProcessRuntime(
        codex_store=db,
        log_store=db,
        data_dir=str(tmp_path),
        event_bus=None,
        refresh_task_result=_refresh,
    )
    entry = type("E", (), {"result_text": "AGENT_GENERATED_PRD", "help_requested": False})()

    await runtime._mark_task_done("task-1", entry)

    reloaded = await db.load_codex_task("task-1")
    # initial run: task.result is updated and refresh fires
    assert reloaded.result == "AGENT_GENERATED_PRD"
    assert refresh_calls == ["task-1"]


@pytest.mark.asyncio
async def test_mark_task_done_persists_assistant_summary_for_initial_run(tmp_path):
    """For initial runs the role workflow rewrites task.result to a human summary.
    The assistant message saved to the chat thread must use that summary, NOT
    the raw JSON the agent emitted (which lives in entry.result_text)."""
    from app.application.process_runtime_common import BaseProcessRuntime  # noqa: I001
    from app.adapters.async_sqlite_store import AsyncSQLiteStore

    db = AsyncSQLiteStore(str(tmp_path / "db.sqlite"))
    now = datetime.now()
    session = CodexSession(
        id="ws-1", title="W", cwd=str(tmp_path), created_at=now, last_active_at=now
    )
    await db.save_codex_session(session)

    task = CodexTask(
        id="task-1",
        session_id="ws-1",
        phase="requirements",
        title="t",
        prompt="p",
        role="product_manager",
        executor="codex",
        status="running",
        result=None,
        workspace_path=str(tmp_path),
        last_execution_process_id="ep-init-y",
        created_at=now,
        updated_at=now,
    )
    await db.save_codex_task(task)

    ep = ExecutionProcess(
        id="ep-init-y",
        task_id="task-1",
        session_id="ws-1",
        status="Running",
        kind="initial",
        created_at=now,
        updated_at=now,
    )
    await db.save_execution_process(ep)

    async def _refresh_rewrites_to_summary(t):
        # Simulate role workflow's persist_result rewriting task.result.
        t.result = "PRD generated. Files: prd.json, prd.md."

    runtime = BaseProcessRuntime(
        codex_store=db,
        log_store=db,
        data_dir=str(tmp_path),
        event_bus=None,
        refresh_task_result=_refresh_rewrites_to_summary,
    )
    entry = type(
        "E",
        (),
        {
            "result_text": '{"language":"zh","project_name":"x","product_goals":["g"]}',
            "help_requested": False,
        },
    )()

    await runtime._mark_task_done("task-1", entry)

    msgs = await db.list_codex_task_messages("task-1")
    assistants = [m for m in msgs if m.role == "assistant"]
    assert len(assistants) == 1
    # Chat thread must show the human summary, not the raw JSON
    assert assistants[0].content == "PRD generated. Files: prd.json, prd.md."
    assert "product_goals" not in assistants[0].content


@pytest.mark.asyncio
async def test_mark_task_done_replaces_json_chat_reply_with_hint(tmp_path):
    """Weak-instruction-following models sometimes output the role artifact JSON
    even when asked to chat. The chat-mode persist path must detect this and
    swap the raw JSON for a friendly hint instead of dumping a JSON blob into
    the conversation thread."""
    from app.application.process_runtime_common import BaseProcessRuntime  # noqa: I001
    from app.adapters.async_sqlite_store import AsyncSQLiteStore

    db = AsyncSQLiteStore(str(tmp_path / "db.sqlite"))
    now = datetime.now()
    session = CodexSession(
        id="ws-1", title="W", cwd=str(tmp_path), created_at=now, last_active_at=now
    )
    await db.save_codex_session(session)
    task = CodexTask(
        id="task-1",
        session_id="ws-1",
        phase="requirements",
        title="t",
        prompt="p",
        role="product_manager",
        executor="codex",
        status="running",
        result="OLD_CANONICAL_SUMMARY",
        workspace_path=str(tmp_path),
        last_execution_process_id="ep-chat-json",
        created_at=now,
        updated_at=now,
    )
    await db.save_codex_task(task)
    ep = ExecutionProcess(
        id="ep-chat-json",
        task_id="task-1",
        session_id="ws-1",
        status="Running",
        kind="chat",
        created_at=now,
        updated_at=now,
    )
    await db.save_execution_process(ep)

    runtime = BaseProcessRuntime(
        codex_store=db,
        log_store=db,
        data_dir=str(tmp_path),
        event_bus=None,
        refresh_task_result=None,
    )
    entry = type(
        "E",
        (),
        {
            "result_text": '{"language":"zh","project_name":"x","product_goals":["g"],"user_stories":[]}',
            "help_requested": False,
        },
    )()
    await runtime._mark_task_done("task-1", entry)

    msgs = await db.list_codex_task_messages("task-1")
    assistants = [m for m in msgs if m.role == "assistant"]
    assert len(assistants) == 1
    content = assistants[0].content
    assert "language" not in content  # raw JSON keys not present
    assert "product_goals" not in content
    assert ("结构化 JSON" in content) or ("模型未按对话格式" in content)


@pytest.mark.asyncio
async def test_mark_task_done_persists_assistant_raw_text_for_chat_run(tmp_path):
    """For chat runs the agent reply is plain natural language; pass it through verbatim."""
    from app.application.process_runtime_common import BaseProcessRuntime  # noqa: I001
    from app.adapters.async_sqlite_store import AsyncSQLiteStore

    db = AsyncSQLiteStore(str(tmp_path / "db.sqlite"))
    now = datetime.now()
    session = CodexSession(
        id="ws-1", title="W", cwd=str(tmp_path), created_at=now, last_active_at=now
    )
    await db.save_codex_session(session)

    task = CodexTask(
        id="task-1",
        session_id="ws-1",
        phase="requirements",
        title="t",
        prompt="p",
        role="product_manager",
        executor="codex",
        status="running",
        result="OLD_CANONICAL_SUMMARY",
        workspace_path=str(tmp_path),
        last_execution_process_id="ep-chat-y",
        created_at=now,
        updated_at=now,
    )
    await db.save_codex_task(task)

    ep = ExecutionProcess(
        id="ep-chat-y",
        task_id="task-1",
        session_id="ws-1",
        status="Running",
        kind="chat",
        created_at=now,
        updated_at=now,
    )
    await db.save_execution_process(ep)

    runtime = BaseProcessRuntime(
        codex_store=db,
        log_store=db,
        data_dir=str(tmp_path),
        event_bus=None,
        refresh_task_result=None,
    )
    entry = type(
        "E",
        (),
        {
            "result_text": "你好！需要我帮你做什么？",  # noqa: RUF001
            "help_requested": False,
        },
    )()

    await runtime._mark_task_done("task-1", entry)

    msgs = await db.list_codex_task_messages("task-1")
    assistants = [m for m in msgs if m.role == "assistant"]
    assert len(assistants) == 1
    # Chat should show the agent's natural-language reply, NOT the prior task.result.
    assert assistants[0].content == "你好！需要我帮你做什么？"  # noqa: RUF001


# ---------------------------------------------------------------------------
# Prompt building branch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_prompt_text_chat_branch_is_minimal_and_does_not_use_role_template():
    """For kind='chat', _build_prompt_text must produce a short prompt that
    explicitly tells the agent not to output JSON or rewrite the artifact.
    It must NOT call into role workflow's build_prompt."""
    from app.application.codex_task_runner import CodexTaskRunner

    runner = CodexTaskRunner.__new__(CodexTaskRunner)
    # only the bits we need
    runner._role_workflow_service = type(
        "S", (), {"is_managed_role": staticmethod(lambda r: True)}
    )()
    runner._CODEX_COLLABORATION_HINT = "(hint)"

    fake_task = type("T", (), {"role": "product_manager", "executor": "codex"})()

    out = await runner._build_prompt_text(
        fake_task,
        prompt_text="你好",
        prompt_override="你好",
        resume_session_id="cli-1",
        resume_message_id=None,
        kind="chat",
    )
    lowered = out.lower()
    assert "json" in lowered  # mentions JSON to suppress it
    assert "你好" in out  # user message included
    # No collaboration hint should be in chat prompt (it's for initial codex runs)
    assert "(hint)" not in out
