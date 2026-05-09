from datetime import datetime
from uuid import uuid4
from pathlib import Path
import shutil

from fastapi import APIRouter, HTTPException
import json

from pydantic import BaseModel
from typing import Literal

from app.bootstrap import session_service, orchestration_service, approval_service, codex_store, get_codex_process_manager, check_codex_available, workspace_manager, event_bus, MockCodexProcessManager, get_help_orchestrator
from app.application.codex_task_runner import CodexTaskRunner
from app.application.product_manager_service import ProductManagerArtifactError, ProductManagerService
from app.application.role_workflow_service import RoleWorkflowService
from app.application.process_runtime_common import is_agent_message_item_type
from app.interfaces.execution_process_views import build_execution_process_view


router = APIRouter(prefix="/api")

VALID_ISSUE_PHASES = {"requirements", "architecture", "development", "testing"}
ROLE_PHASE_DEFAULTS = {
    "product_manager": "requirements",
    "architect": "architecture",
    "engineer": "development",
    "qa": "testing",
}


def _try_parse_json_line(line: str) -> dict | None:
    stripped = line.strip()
    if not stripped.startswith("{"):
        return None
    try:
        parsed = json.loads(stripped)
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


async def _resolve_runtime_config(
    executor: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> tuple[str, str, str, dict[str, str] | None, str]:
    catalog_service = _get_runtime_catalog_service()
    catalog = await catalog_service.load_catalog()
    try:
        return catalog_service.resolve_effective_config(
            catalog,
            executor or "codex",
            provider,
            model,
        )
    except RuntimeCatalogValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))


async def _resolve_task_runtime_config(task) -> tuple[str, str, str, dict[str, str] | None, str]:
    return await _resolve_runtime_config(task.executor, task.provider, task.model)


def _serialize_task_payload(task) -> dict:
    return {
        "id": task.id,
        "session_id": task.session_id,
        "issue_id": task.issue_id,
        "phase": task.phase,
        "title": task.title,
        "prompt": task.prompt,
        "role": task.role,
        "status": task.status,
        "result": task.result,
        "executor": task.executor,
        "provider": task.provider,
        "model": task.model,
        "parent_task_id": task.parent_task_id,
        "task_kind": task.task_kind,
        "blocked_by_help_id": task.blocked_by_help_id,
        "resume_session_id": task.resume_session_id,
        "workspace_path": task.workspace_path,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
    }


async def _list_task_messages(task_id: str, execution_process_id: str | None = None):
    if execution_process_id:
        try:
            return await codex_store.list_codex_task_messages(task_id, execution_process_id=execution_process_id)
        except TypeError:
            pass
    return await codex_store.list_codex_task_messages(task_id)


async def _load_task_logs(
    session_id: str,
    task_id: str,
    execution_process_id: str | None = None,
    limit: int = 1000,
    reverse: bool = False,
):
    if execution_process_id:
        try:
            return await codex_store.load_log_events(
                session_id,
                task_id=task_id,
                execution_process_id=execution_process_id,
                limit=limit,
                reverse=reverse,
            )
        except Exception:
            return await codex_store.load_log_events(session_id, task_id=task_id, limit=limit, reverse=reverse)
    return await codex_store.load_log_events(session_id, task_id=task_id, limit=limit, reverse=reverse)


async def _load_execution_process(process_id: str):
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    process = await codex_store.load_execution_process(process_id)
    if process is None:
        raise HTTPException(status_code=404, detail="ExecutionProcess not found")
    return process


async def _extract_task_result_from_logs(
    session_id: str,
    task_id: str,
    execution_process_id: str | None = None,
) -> str | None:
    if codex_store is None:
        return None
    # Optimization: Search backwards through the last 500 logs first (where the result usually is)
    # for faster response times on large turns.
    logs = await _load_task_logs(session_id, task_id, execution_process_id=execution_process_id, limit=500, reverse=True)
    
    def find_result(log_list):
        for log in log_list:
            if log.stream != "stdout":
                continue
            event = _try_parse_json_line(log.content)
            if event is None:
                continue

            method = event.get("method")
            if event.get("type") == "assistant" or method == "item/completed":
                params = event.get("params") or {}
                item = params.get("item") or event.get("message") or {}
                if is_agent_message_item_type(item.get("type")):
                    text = item.get("text")
                    if isinstance(text, str) and text.strip():
                        # Priority: Has 'final_answer' phase
                        if item.get("phase") == "final_answer":
                            return text, True
                        return text, False
            elif event.get("type") == "result":
                value = event.get("result")
                if isinstance(value, str) and value.strip():
                    return value, False
            elif event.get("type") == "item.completed":
                item = event.get("item") or {}
                if is_agent_message_item_type(item.get("type")):
                    text = item.get("text")
                    if isinstance(text, str) and text.strip():
                        return text, False
        return None, False

    result_text, is_final = find_result(logs)
    if is_final:
        return result_text
        
    # If not found or not final, try a deeper search (forward search up to 5000)
    if result_text is None:
        deep_logs = await _load_task_logs(session_id, task_id, execution_process_id=execution_process_id, limit=5000)
        deep_logs.reverse()
        deep_result, _ = find_result(deep_logs)
        if deep_result:
            return deep_result

    if result_text:
        return result_text

    # Fallback to last line of stdout
    if not logs:
        # Load again without reverse for raw stdout fallback if needed
        logs = await _load_task_logs(session_id, task_id, execution_process_id=execution_process_id, limit=10)
        
    for log in logs:
        if log.stream == "stdout" and log.content:
            return log.content.strip()
    return None


async def _refresh_task_result(task):
    """Refresh a task's result from its latest logs when available.

    Optimization: Skip SQLite query if task.result is already set (Phase 2 in-memory capture).
    Only re-extract from logs if task.result is empty.
    """
    if not task.result:
        latest_result = await _extract_task_result_from_logs(
            task.session_id,
            task.id,
            execution_process_id=task.last_execution_process_id,
        )
        if latest_result:
            task.result = latest_result
    if task.status == "done" and task.result:
        workspace = await codex_store.load_codex_workspace(task.session_id)
        workspace_title = workspace.title if workspace is not None else None
        artifact = role_workflow_service.persist_result(task, workspace_title=workspace_title)

        # Automated Code Review Logic
        if task.role == "architect" and getattr(task, "task_kind", "normal") == "review" and task.parent_task_id:
            from app.application.architect_workflow import ReviewReportDocument
            if isinstance(artifact, ReviewReportDocument):
                parent_task = await codex_store.load_codex_task(task.parent_task_id)
                if parent_task:
                    if artifact.decision == "approve":
                        parent_task.status = "done"
                    else:
                        parent_task.status = "rework"
                    
                    # Format complete review feedback
                    review_parts = [artifact.reason]
                    if artifact.suggestions:
                        review_parts.append("\n\n**改进建议：**")
                        for i, suggestion in enumerate(artifact.suggestions, 1):
                            review_parts.append(f"{i}. {suggestion}")
                    if artifact.risks_identified:
                        review_parts.append("\n\n**识别的风险：**")
                        for i, risk in enumerate(artifact.risks_identified, 1):
                            review_parts.append(f"{i}. {risk}")
                    
                    parent_task.review_comment = "\n".join(review_parts)
                    parent_task.updated_at = datetime.now()
                    await codex_store.save_codex_task(parent_task)
                    await event_bus.append({
                        "type": "task_status",
                        "task_id": parent_task.id,
                        "session_id": parent_task.session_id,
                        "status": parent_task.status,
                        "review_comment": parent_task.review_comment,
                    })
                    
                    # Push to WebSocket for real-time update
                    try:
                        from app.interfaces.codex_ws import stream_manager
                        stream_manager.buffer_pending(parent_task.session_id, {
                            "type": "task_status",
                            "task_id": parent_task.id,
                            "status": parent_task.status,
                            "review_comment": parent_task.review_comment,
                        })
                    except Exception:
                        pass


async def _latest_assistant_message_content(task_id: str) -> str | None:
    messages = await _list_task_messages(task_id)
    for message in reversed(messages):
        if getattr(message, "role", None) == "assistant" and getattr(message, "content", None):
            return message.content
    return None


async def _build_execution_process_payload(process):
    task = await codex_store.load_codex_task(process.task_id) if codex_store is not None else None
    messages = await codex_store.list_codex_task_messages(
        process.task_id,
        execution_process_id=process.id,
    ) if codex_store is not None else []
    logs = await codex_store.load_log_events(
        process.session_id,
        task_id=process.task_id,
        execution_process_id=process.id,
        limit=1000,
    ) if codex_store is not None else []
    return build_execution_process_view(process, task, messages, logs)


def _has_requirements_artifacts(workspace_path: str | None, issue_id: str) -> bool:
    if not workspace_path:
        return False
    issue_root = Path(workspace_path) / "issues" / issue_id
    if not issue_root.exists() or not issue_root.is_dir():
        return False
    
    # Check in pm/ subdirectory
    pm_dir = issue_root / "pm"
    return any(
        (pm_dir / name).exists()
        for name in {"requirement.md", "prd.json", "prd.md"}
    )


def _has_architecture_artifacts(workspace_path: str | None, issue_id: str) -> tuple[bool, str]:
    """Returns (has_artifacts, error_detail). error_detail is empty string when artifacts exist."""
    if not workspace_path:
        return False, "架构产物路径无效"
    issue_root = Path(workspace_path) / "issues" / issue_id
    if not issue_root.exists() or not issue_root.is_dir():
        return False, "架构产物不存在"
    
    # Check in architect/ subdirectory
    architect_dir = issue_root / "architect"
    design_path = architect_dir / "system_design.json"
    plan_path = architect_dir / "implementation_plan.json"
    
    if not design_path.exists():
        return False, "请先生成 system_design.json 架构产物后再流转到开发"
    if not plan_path.exists():
        return False, "请先生成 implementation_plan.json 架构产物后再流转到开发"
    try:
        payload = json.loads(plan_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False, "implementation_plan.json 格式无效"
    if not isinstance(payload, list) or len(payload) == 0:
        return False, "架构产物 implementation_plan.json 为空，请先生成有效拆分任务后再流转到开发"
    return True, ""


def _load_implementation_tasks(workspace_path: str | None, issue_id: str) -> list[dict]:
    if not workspace_path:
        return []
    issue_root = Path(workspace_path) / "issues" / issue_id
    
    # Check in architect/ subdirectory
    architect_dir = issue_root / "architect"
    design_path = architect_dir / "system_design.json"
    plan_path = architect_dir / "implementation_plan.json"
    
    if not design_path.exists() or not plan_path.exists():
        return []
    try:
        payload = json.loads(plan_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(payload, list):
        return []
    normalized = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        description = str(item.get("description") or "").strip()
        priority = str(item.get("priority") or "P1").strip() or "P1"
        if not title:
            continue
        normalized.append({"title": title, "description": description, "priority": priority})
    return normalized


def _load_development_task_list(workspace_path: str | None, issue_id: str) -> tuple[bool, str, list[str]]:
    """Load and validate development_task_list.json.

    Returns: (success, error_message, ordered_titles)
    """
    if not workspace_path:
        return False, "workspace_path 无效", []

    issue_root = Path(workspace_path) / "issues" / issue_id
    
    # Check in architect/ subdirectory
    architect_dir = issue_root / "architect"
    dev_list_path = architect_dir / "development_task_list.json"

    if not dev_list_path.exists():
        return False, "请先生成 development_task_list.json 架构产物后再流转到开发", []

    try:
        payload = json.loads(dev_list_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False, "development_task_list.json 格式无效", []

    if not isinstance(payload, list):
        return False, "development_task_list.json 必须是数组", []

    titles = [str(t).strip() for t in payload if t]

    if not titles:
        return False, "development_task_list.json 不能为空", []

    if len(titles) != len(set(titles)):
        return False, "development_task_list.json 包含重复的 title", []

    return True, "", titles


def _validate_and_order_implementation_tasks(
    impl_tasks: list[dict], dev_task_list: list[str]
) -> tuple[bool, str, list[dict]]:
    """Validate development_task_list matches implementation_tasks and return ordered tasks.

    Returns: (success, error_message, ordered_tasks)
    """
    # Check for duplicates in implementation_tasks first
    impl_titles = [task["title"] for task in impl_tasks]
    if len(impl_titles) != len(set(impl_titles)):
        return False, "implementation_plan.json 包含重复的 title", []

    impl_set = set(impl_titles)
    dev_set = set(dev_task_list)

    if dev_set != impl_set:
        missing = impl_set - dev_set
        extra = dev_set - impl_set
        parts = []
        if missing:
            parts.append(f"缺少: {missing}")
        if extra:
            parts.append(f"多余: {extra}")
        return False, f"development_task_list 与 implementation_plan 不匹配。{'; '.join(parts)}", []

    # Build title -> task map (safe now after duplicate check)
    task_map = {task["title"]: task for task in impl_tasks}

    # Return tasks in development_task_list order
    ordered = [task_map[title] for title in dev_task_list]
    return True, "", ordered


def _is_task_running(status: str | None) -> bool:
    return str(status or "").lower() in {"running", "responding"}


def _should_use_workspace_root_for_task(workspace, request: "CreateTaskRequest") -> bool:
    """Return True if task should use workspace root, False for a dedicated task workspace."""
    if request.issue_id:
        return True
    if request.role in ("product_manager", "architect"):
        return True
    return False


def _is_managed_task_workspace(task, workspace) -> bool:
    if not task.workspace_path:
        return False
    if workspace is None:
        return True
    return task.workspace_path != workspace.cwd


def _delete_issue_artifact_root(workspace_path: str | None, issue_id: str):
    if not workspace_path:
        return
    issue_root = Path(workspace_path) / "issues" / issue_id
    if not issue_root.exists():
        return
    try:
        shutil.rmtree(issue_root)
    except Exception:
        pass


async def _delete_task_cascade(task_id: str, *, delete_workspace: bool = True):
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    task = await codex_store.load_codex_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    workspace = await codex_store.load_codex_workspace(task.session_id)
    if delete_workspace and _is_managed_task_workspace(task, workspace):
        try:
            workspace_manager.delete_workspace(task.workspace_path)
        except Exception:
            pass
    await codex_store.delete_codex_task(task_id)
    await event_bus.append({
        "type": "task_deleted",
        "task_id": task_id,
    })
    return task


task_runner = None
product_manager_service = ProductManagerService()
role_workflow_service = RoleWorkflowService()


def _get_task_runner():
    global task_runner
    if task_runner is None:
        task_runner = CodexTaskRunner(
            codex_store=codex_store,
            event_bus=event_bus,
            process_manager_factory=get_codex_process_manager,
            mock_manager_cls=MockCodexProcessManager,
            refresh_task_result=_refresh_task_result,
            help_orchestrator_factory=lambda: get_help_orchestrator(_refresh_task_result),
            role_workflow_service=role_workflow_service,
        )
    elif isinstance(task_runner, CodexTaskRunner):
        task_runner.codex_store = codex_store
        task_runner.event_bus = event_bus
        task_runner._process_manager_factory = get_codex_process_manager
        task_runner._mock_manager_cls = MockCodexProcessManager
        task_runner._refresh_task_result = _refresh_task_result
        task_runner._help_orchestrator_factory = lambda: get_help_orchestrator(_refresh_task_result)
        task_runner._role_workflow_service = role_workflow_service
    mgr = get_codex_process_manager()
    if hasattr(mgr, "refresh_task_result"):
        mgr.refresh_task_result = _refresh_task_result
    return task_runner


@router.get("/health")
async def health_check():
    """Health check endpoint to verify this is the correct backend."""
    return {"service": "agent-collab-console", "version": "1.0"}


class CreateSessionRequest(BaseModel):
    title: str


class CreateTaskRequest(BaseModel):
    title: str
    assignee: str = "claude"


@router.post("/sessions", status_code=201)
async def create_session(request: CreateSessionRequest):
    return await session_service.create_session(request.title)


@router.get("/sessions")
async def list_sessions():
    sessions = await session_service.list_sessions()
    return [{"id": s.id, "title": s.title, "state": s.state.value} for s in sessions]


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    try:
        return await session_service.get_session(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")


@router.get("/sessions/{session_id}/tasks")
async def get_session_tasks(session_id: str):
    try:
        session = await session_service.get_session(session_id)
        return session.tasks
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")


@router.get("/sessions/{session_id}/messages")
async def get_session_messages(session_id: str):
    try:
        return (await session_service.get_session(session_id)).messages
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")


@router.get("/sessions/{session_id}/artifacts")
async def get_session_artifacts(session_id: str):
    try:
        return (await session_service.get_session(session_id)).artifacts
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")


@router.get("/sessions/{session_id}/runs")
async def get_session_runs(session_id: str):
    try:
        return (await session_service.get_session(session_id)).runs
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")


@router.get("/tasks/{task_id}")
async def get_task(task_id: str):
    for session in session_service.sessions.values():
        for task in session.tasks:
            if task.id == task_id:
                return task
    raise HTTPException(status_code=404, detail="Task not found")


@router.post("/sessions/{session_id}/tasks", status_code=201)
async def create_task(session_id: str, request: CreateTaskRequest):
    try:
        session = await session_service.get_session(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")

    task = await orchestration_service.plan_task(session_id, request.title, request.assignee)
    return task


@router.post("/tasks/{task_id}/run")
async def run_task(task_id: str):
    try:
        result = await orchestration_service.run_task(task_id)
        return result
    except KeyError:
        raise HTTPException(status_code=404, detail="Task not found")


@router.post("/tasks/{task_id}/retry")
async def retry_task(task_id: str):
    try:
        result = await orchestration_service.retry_task(task_id)
        return result
    except KeyError:
        raise HTTPException(status_code=404, detail="Task not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/tasks/{task_id}/approval")
async def request_approval(task_id: str):
    # Find session containing this task
    for session in session_service.sessions.values():
        for task in session.tasks:
            if task.id == task_id:
                approval = await approval_service.request_submission(session.id, task_id)
                return approval
    raise HTTPException(status_code=404, detail="Task not found")


@router.get("/approvals/{approval_id}")
async def get_approval(approval_id: str):
    try:
        return approval_service.approvals[approval_id]
    except KeyError:
        raise HTTPException(status_code=404, detail="Approval not found")


@router.post("/approvals/{approval_id}/approve")
async def approve_approval(approval_id: str):
    try:
        return await approval_service.approve(approval_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Approval not found")


@router.post("/approvals/{approval_id}/reject")
async def reject_approval(approval_id: str):
    try:
        return await approval_service.reject(approval_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Approval not found")


# --- Codex CLI Session APIs ---


class CreateCodexSessionRequest(BaseModel):
    title: str
    cwd: str = ""


@router.get("/codex/status")
async def codex_status():
    """Check if local codex CLI is available."""
    available = check_codex_available()
    return {"available": available, "binary": "codex"}


@router.get("/codex/workspaces")
@router.get("/codex/sessions")
async def list_codex_workspaces():
    """List all console-managed Codex workspaces."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    return await codex_store.list_codex_workspaces()


list_codex_sessions = list_codex_workspaces


@router.post("/codex/workspaces", status_code=201)
@router.post("/codex/sessions", status_code=201)
async def create_codex_workspace(request: CreateCodexSessionRequest):
    """Create a new Codex workspace. No process is launched — sending input triggers per-turn execution."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    from datetime import datetime
    from app.domain.models import CodexWorkspace
    workspace_id = str(uuid4())
    resolved_cwd = request.cwd or str(workspace_manager.source_root)
    workspace = CodexWorkspace(
        id=workspace_id,
        title=request.title,
        cwd=resolved_cwd,
        status="idle",
        created_at=datetime.now(),
        last_active_at=datetime.now(),
        log_path=None,
        messages=[],
    )
    await codex_store.save_codex_workspace(workspace)
    # Broadcast new workspace
    await event_bus.append({
        "type": "session_created",
        "session": {"id": workspace.id, "title": workspace.title, "status": workspace.status}
    })
    return workspace


create_codex_session = create_codex_workspace


@router.get("/codex/workspaces/{workspace_id}")
@router.get("/codex/sessions/{workspace_id}")
async def get_codex_workspace(workspace_id: str):
    """Get a Codex workspace by ID."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    workspace = await codex_store.load_codex_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Codex workspace not found")
    return workspace


get_codex_session = get_codex_workspace


@router.get("/codex/workspaces/{workspace_id}/execution_processes")
@router.get("/codex/sessions/{workspace_id}/execution_processes")
async def get_workspace_execution_processes(workspace_id: str):
    """Get the execution-process collection for a workspace."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    workspace = await codex_store.load_codex_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Codex workspace not found")

    processes = await codex_store.list_execution_processes(session_id=workspace_id)
    return {
        "execution_processes": {
            process.id: await _build_execution_process_payload(process)
            for process in processes
        }
    }


get_session_execution_processes = get_workspace_execution_processes


@router.get("/codex/workspaces/{workspace_id}/logs")
@router.get("/codex/sessions/{workspace_id}/logs")
async def get_codex_workspace_logs(workspace_id: str, limit: int = 1000):
    """Get log events for a Codex workspace."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    workspace = await codex_store.load_codex_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Codex workspace not found")
    return await codex_store.load_log_events(workspace_id, limit=limit)


get_codex_session_logs = get_codex_workspace_logs


class SendInputRequest(BaseModel):
    input: str


class SendTaskMessageRequest(BaseModel):
    content: str


class RequestTaskHelpRequest(BaseModel):
    target_executor: str
    title: str | None = None
    prompt: str | None = None
    context_summary: str | None = None


class UpdateCodexTaskRequest(BaseModel):
    executor: Literal["codex", "claude"] | None = None
    provider: str | None = None
    model: str | None = None


class RunTaskRequest(BaseModel):
    """Optional run-time overrides for task execution."""
    executor: Literal["codex", "claude"] | None = None
    provider: str | None = None
    model: str | None = None


@router.patch("/codex/tasks/{task_id}")
async def update_codex_task(task_id: str, request: UpdateCodexTaskRequest):
    """Update a task's mutable fields. Supports executor, provider, and model."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    task = await codex_store.load_codex_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status == "running":
        raise HTTPException(status_code=409, detail="Cannot update a running task")

    if request.executor is None and request.provider is None and request.model is None:
        raise HTTPException(status_code=400, detail="Must specify at least one field to update")

    # Validate and resolve executor/provider/model against runtime catalog
    new_executor = request.executor if request.executor is not None else task.executor
    new_provider = request.provider if request.provider is not None else task.provider
    new_model = request.model if request.model is not None else task.model

    catalog_service = _get_runtime_catalog_service()
    catalog = await catalog_service.load_catalog()
    try:
        resolved_executor, resolved_provider, resolved_model, _, _ = catalog_service.resolve_effective_config(
            catalog, new_executor, new_provider, new_model
        )
    except RuntimeCatalogValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    task.executor = resolved_executor
    task.provider = resolved_provider
    task.model = resolved_model
    task.updated_at = datetime.now()
    await codex_store.save_codex_task(task)

    return task


@router.get("/codex/tasks/{task_id}/messages")
async def get_codex_task_messages(task_id: str):
    """Get the conversation history for a task."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    task = await codex_store.load_codex_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return await codex_store.list_codex_task_messages(task_id)


@router.post("/codex/tasks/{task_id}/request-help")
async def request_codex_task_help(task_id: str, request: RequestTaskHelpRequest):
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")

    task = await codex_store.load_codex_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.task_kind == "help_child":
        raise HTTPException(status_code=409, detail="Help child tasks cannot request help")
    if task.status == "waiting_for_help":
        raise HTTPException(status_code=409, detail="Task is already waiting for help")
    if request.target_executor == task.executor:
        raise HTTPException(status_code=400, detail="Target executor must differ from task executor")

    if task.status != "running":
        task.status = "running"
        task.updated_at = datetime.now()
        await codex_store.save_codex_task(task)

    help_title = request.title or f"Help: {task.title}"
    help_prompt = request.prompt or (
        f"Please help with task '{task.title}'.\n\n"
        f"Original prompt:\n{task.prompt}\n\n"
        f"Current result:\n{task.result or '(no current result)'}"
    )
    help_context_summary = request.context_summary or f"Manual help requested from the web UI for task {task.id}."

    try:
        orchestrator = get_help_orchestrator(_refresh_task_result)
        help_request = await orchestrator.request_help(
            parent_task_id=task.id,
            target_executor=request.target_executor,
            title=help_title,
            prompt=help_prompt,
            context_summary=help_context_summary,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except KeyError:
        raise HTTPException(status_code=404, detail="Task not found")

    parent_task = await codex_store.load_codex_task(task.id)
    child_task = await codex_store.load_codex_task(help_request.child_task_id)
    return {
        "help_request": help_request,
        "parent_task": parent_task,
        "child_task": child_task,
    }


@router.post("/codex/workspaces/{workspace_id}/input")
@router.post("/codex/sessions/{workspace_id}/input")
async def send_workspace_input(workspace_id: str, request: SendInputRequest):
    """Send input to trigger a per-turn codex execution.

    Creates a workspace-scoped task and runs it immediately, so the message
    appears in the task list with live logs — matching vibe-kanban UX.
    """
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    workspace = await codex_store.load_codex_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Codex workspace not found")

    from datetime import datetime
    from app.domain.models import CodexTask

    resolved_executor, resolved_provider, resolved_model, _, _ = await _resolve_runtime_config()

    resume_session_id = workspace.thread_id or None

    # Derive title from first line of input
    title_preview = request.input.split("\n")[0][:60]
    task_title = title_preview if title_preview else "Chat message"

    task_id = str(uuid4())
    workspace_path = workspace_manager.create_workspace(task_id)
    task = CodexTask(
        id=task_id,
        session_id=workspace_id,
        title=task_title,
        prompt=request.input,
        executor=resolved_executor,
        provider=resolved_provider,
        model=resolved_model,
        status="pending",
        result=None,
        parent_task_id=None,
        workspace_path=workspace_path,
        resume_session_id=resume_session_id,
        resume_message_id=None,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    await codex_store.save_codex_task(task)
    # Broadcast new task with complete data structure
    await event_bus.append({
        "type": "task_created",
        "task": _serialize_task_payload(task),
    })

    try:
        exec_process = await _get_task_runner().start_task_run(
            task,
            prompt_override=request.input,
            resume_session_id=resume_session_id,
        )
        return {
            "task_id": task_id,
            "status": "running",
            "title": task.title,
            "execution_process_id": exec_process.id,
        }
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


send_codex_input = send_workspace_input


@router.post("/codex/workspaces/{workspace_id}/terminate")
@router.post("/codex/sessions/{workspace_id}/terminate")
async def terminate_codex_workspace(workspace_id: str):
    """Terminate a running codex process."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    mgr = get_codex_process_manager()
    try:
        return await mgr.terminate(workspace_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


terminate_codex_session = terminate_codex_workspace

@router.delete("/codex/workspaces")
@router.delete("/codex/sessions")
async def delete_all_codex_workspaces():
    """Delete all codex workspaces and their logs. Terminates any running processes first."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    workspaces = await codex_store.list_codex_workspaces()
    mgr = get_codex_process_manager()
    for workspace in workspaces:
        try:
            mgr.terminate(workspace["id"])
        except KeyError:
            pass
        tasks = await codex_store.list_codex_tasks(session_id=workspace["id"])
        for task in tasks:
            if task.get("workspace_path") and task.get("workspace_path") != workspace.get("cwd"):
                try:
                    workspace_manager.delete_workspace(task["workspace_path"])
                except Exception:
                    pass
        await codex_store.delete_codex_workspace(workspace["id"])
    return {"deleted": len(workspaces)}


delete_all_codex_sessions = delete_all_codex_workspaces


@router.delete("/codex/workspaces/{workspace_id}")
@router.delete("/codex/sessions/{workspace_id}")
async def delete_codex_workspace(workspace_id: str):
    """Delete a codex workspace, all its tasks, workspaces, and logs."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    workspace = await codex_store.load_codex_workspace(workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Codex workspace not found")
    # Terminate if running first
    mgr = get_codex_process_manager()
    try:
        mgr.terminate(workspace_id)
    except KeyError:
        pass  # Workspace not running, ok to proceed
    # Delete workspaces for all tasks in this workspace before deleting DB records
    tasks = await codex_store.list_codex_tasks(session_id=workspace_id)
    for task in tasks:
        if task.get("workspace_path") and task.get("workspace_path") != workspace.cwd:
            try:
                workspace_manager.delete_workspace(task["workspace_path"])
            except Exception:
                pass
    await codex_store.delete_codex_workspace(workspace_id)
    # Broadcast workspace deletion
    await event_bus.append({
        "type": "session_deleted",
        "session_id": workspace_id
    })
    return {"deleted": workspace_id}


delete_codex_session = delete_codex_workspace


# --- Codex Tasks ---


class CreateTaskRequest(BaseModel):
    session_id: str
    issue_id: str | None = None
    phase: str | None = None
    title: str
    prompt: str
    role: str = "general"
    executor: str = "codex"
    provider: str | None = None
    model: str | None = None
    parent_task_id: str | None = None
    task_kind: str = "normal"
    blocked_by_help_id: str | None = None


class CreateIssueRequest(BaseModel):
    session_id: str
    title: str
    description: str | None = None


class UpdateIssuePhaseRequest(BaseModel):
    current_phase: str


@router.post("/codex/issues", status_code=201)
async def create_codex_issue(request: CreateIssueRequest):
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    workspace = await codex_store.load_codex_workspace(request.session_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")

    from app.domain.models import CodexIssue

    now = datetime.now()
    issue = CodexIssue(
        id=str(uuid4()),
        session_id=request.session_id,
        title=request.title,
        description=request.description,
        current_phase="requirements",
        status="open",
        created_at=now,
        updated_at=now,
    )
    await codex_store.save_codex_issue(issue)
    return issue


@router.get("/codex/issues")
async def list_codex_issues(session_id: str | None = None):
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    return await codex_store.list_codex_issues(session_id=session_id)


@router.get("/codex/issues/{issue_id}")
async def get_codex_issue(issue_id: str):
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    issue = await codex_store.load_codex_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    return issue


@router.post("/codex/issues/{issue_id}/phase")
async def update_codex_issue_phase(issue_id: str, request: UpdateIssuePhaseRequest):
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    if request.current_phase not in VALID_ISSUE_PHASES:
        raise HTTPException(status_code=400, detail=f"Invalid issue phase: {request.current_phase}")
    issue = await codex_store.load_codex_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    issue.current_phase = request.current_phase
    issue.updated_at = datetime.now()
    await codex_store.save_codex_issue(issue)
    return issue


@router.post("/codex/issues/{issue_id}/transition-to-architecture")
async def transition_codex_issue_to_architecture(issue_id: str):
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")

    issue = await codex_store.load_codex_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    if issue.current_phase not in ["requirements", "architecture"]:
        raise HTTPException(status_code=409, detail="只有需求或架构阶段的 issue 才能流转到架构")

    session = await codex_store.load_codex_session(issue.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    tasks = await codex_store.list_codex_tasks(session_id=issue.session_id, issue_id=issue_id)
    if any(_is_task_running(task.get("status")) for task in tasks):
        raise HTTPException(status_code=409, detail="当前有任务仍在运行，请等待完成后再流转")

    workspace_path = next((task.get("workspace_path") for task in tasks if task.get("workspace_path")), None) or session.cwd
    if not _has_requirements_artifacts(workspace_path, issue_id):
        raise HTTPException(status_code=409, detail="请先生成需求产物后再流转到架构")

    existing_architect_row = next(
        (task for task in tasks if task.get("role") == "architect" and task.get("issue_id") == issue_id),
        None,
    )

    issue.current_phase = "architecture"
    issue.updated_at = datetime.now()
    await codex_store.save_codex_issue(issue)

    architect_task = None
    created = False
    if existing_architect_row is not None:
        architect_task = await codex_store.load_codex_task(existing_architect_row["id"])
    else:
        from app.domain.models import CodexTask

        now = datetime.now()
        resolved_executor, resolved_provider, resolved_model, _, _ = await _resolve_runtime_config()
        architect_task = CodexTask(
            id=str(uuid4()),
            session_id=issue.session_id,
            issue_id=issue.id,
            phase="architecture",
            title=f"架构 - {issue.title}",
            prompt="请基于当前需求产物进行架构设计。",
            role="architect",
            executor=resolved_executor,
            provider=resolved_provider,
            model=resolved_model,
            status="pending",
            result=None,
            parent_task_id=None,
            task_kind="normal",
            blocked_by_help_id=None,
            workspace_path=workspace_path,
            resume_session_id=None,
            resume_message_id=None,
            created_at=now,
            updated_at=now,
        )
        await codex_store.save_codex_task(architect_task)
        created = True
        await event_bus.append({
            "type": "task_created",
            "task": architect_task.model_dump(mode="json"),
        })

    return {
        "issue": issue.model_dump(mode="json"),
        "task": architect_task.model_dump(mode="json") if architect_task is not None else None,
        "created": created,
    }


async def _create_development_tasks(
    codex_store,
    issue: "CodexIssue",
    ordered_tasks: list[dict],
    existing_by_title: dict[str, dict],
    workspace_path: str,
) -> tuple[list["CodexTask"], bool]:
    """Create or update development tasks for an issue.

    Returns a tuple of (engineer_tasks, created_any).
    """
    from app.domain.models import CodexTask

    engineer_tasks = []
    created_any = False
    for idx, item in enumerate(ordered_tasks):
        task_title = f"开发 - {issue.title} - {item['title']}"
        task_prompt = f"请实现以下开发任务：{item['title']}\n\n任务描述：{item['description']}\n\n优先级：{item['priority']}"
        existing_row = existing_by_title.get(task_title.strip().lower())
        if existing_row is not None:
            engineer_task = await codex_store.load_codex_task(existing_row["id"])
            if engineer_task.sequence_index != idx or engineer_task.sequence_group != issue.id:
                engineer_task.sequence_index = idx
                engineer_task.sequence_group = issue.id
                engineer_task.updated_at = datetime.now()
                await codex_store.save_codex_task(engineer_task)
        else:
            now = datetime.now()
            resolved_executor, resolved_provider, resolved_model, _, _ = await _resolve_runtime_config()
            engineer_task = CodexTask(
                id=str(uuid4()),
                session_id=issue.session_id,
                issue_id=issue.id,
                phase="development",
                title=task_title,
                prompt=task_prompt,
                role="engineer",
                executor=resolved_executor,
                provider=resolved_provider,
                model=resolved_model,
                status="pending",
                result=None,
                parent_task_id=None,
                task_kind="normal",
                blocked_by_help_id=None,
                workspace_path=workspace_path,
                resume_session_id=None,
                resume_message_id=None,
                sequence_index=idx,
                sequence_group=issue.id,
                created_at=now,
                updated_at=now,
            )
            await codex_store.save_codex_task(engineer_task)
            created_any = True
        engineer_tasks.append(engineer_task)
    return engineer_tasks, created_any


@router.post("/codex/issues/{issue_id}/transition-to-development")
async def transition_codex_issue_to_development(issue_id: str):
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")

    issue = await codex_store.load_codex_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    if issue.current_phase not in ["architecture", "development"]:
        raise HTTPException(status_code=409, detail="只有架构或开发阶段的 issue 才能流转到开发")

    session = await codex_store.load_codex_session(issue.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    tasks = await codex_store.list_codex_tasks(session_id=issue.session_id, issue_id=issue_id)
    if any(_is_task_running(task.get("status")) for task in tasks):
        raise HTTPException(status_code=409, detail="当前有任务仍在运行，请等待完成后再流转")

    workspace_path = next((task.get("workspace_path") for task in tasks if task.get("workspace_path")), None) or session.cwd
    has_artifacts, artifact_error = _has_architecture_artifacts(workspace_path, issue_id)
    if not has_artifacts:
        raise HTTPException(status_code=409, detail=artifact_error)

    success, error_msg, dev_task_list = _load_development_task_list(workspace_path, issue_id)
    if not success:
        raise HTTPException(status_code=409, detail=error_msg)

    implementation_tasks = _load_implementation_tasks(workspace_path, issue_id)
    success, error_msg, ordered_tasks = _validate_and_order_implementation_tasks(implementation_tasks, dev_task_list)
    if not success:
        raise HTTPException(status_code=409, detail=error_msg)

    existing_rows = [task for task in tasks if task.get("role") == "engineer" and task.get("issue_id") == issue_id]
    existing_by_title = {str(task.get("title") or "").strip().lower(): task for task in existing_rows}

    engineer_tasks, created_any = await _create_development_tasks(
        codex_store, issue, ordered_tasks, existing_by_title, workspace_path
    )

    issue.current_phase = "development"
    issue.updated_at = datetime.now()
    await codex_store.save_codex_issue(issue)
    return {
        "issue": issue.model_dump(mode="json"),
        "tasks": [task.model_dump(mode="json") for task in engineer_tasks],
        "created": created_any,
    }


@router.get("/codex/issues/{issue_id}/artifacts")
async def get_codex_issue_artifacts(issue_id: str):
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    issue = await codex_store.load_codex_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")

    workspace = await codex_store.load_codex_workspace(issue.session_id)
    if workspace is None:
        return []
    issue_root = Path(workspace.cwd) / "issues" / issue_id

    tasks = await codex_store.list_codex_tasks(session_id=issue.session_id, issue_id=issue_id)
    sorted_tasks = sorted(
        tasks,
        key=lambda item: item.get("updated_at") or item.get("created_at") or "",
        reverse=True,
    )

    MAX_FILE_SIZE = 1024 * 1024
    for task_row in sorted_tasks:
        if task_row.get("role") != "product_manager":
            continue
        if str(task_row.get("status") or "").lower() != "done":
            continue
        workspace_path = task_row.get("workspace_path")
        if not workspace_path:
            continue
        pm_dir = issue_root / "pm"
        
        # Check in pm/ subdirectory
        has_prd_json = (pm_dir / "prd.json").exists()
        has_prd_md = (pm_dir / "prd.md").exists()
        
        if not (has_prd_json and has_prd_md):
            task = await codex_store.load_codex_task(task_row.get("id"))
            if task is not None and getattr(task, "result", None):
                workspace = await codex_store.load_codex_workspace(task.session_id)
                workspace_title = workspace.title if workspace is not None else None
                try:
                    role_workflow_service.persist_result(task, workspace_title=workspace_title)
                except ProductManagerArtifactError:
                    pass
        
        # Re-check after potential backfill
        has_prd_json = (pm_dir / "prd.json").exists()
        has_prd_md = (pm_dir / "prd.md").exists()
        if has_prd_json and has_prd_md:
            break

    artifact_map: dict[str, dict] = {}
    
    # Define a helper to map folder names to roles/categories
    folder_to_category = {
        "pm": "product",
        "architect": "architecture",
        "engineer": "development",
        "qa": "testing"
    }

    # Recursive traversal of the issue root
    def scan_dir(target_dir: Path):
        if not target_dir.exists() or not target_dir.is_dir():
            return
        for item in sorted(target_dir.iterdir()):
            if item.is_dir():
                scan_dir(item)
            elif item.is_file():
                rel_path = item.relative_to(issue_root)
                # Category is the first part of the relative path
                category_folder = rel_path.parts[0] if len(rel_path.parts) > 1 else "general"
                category = folder_to_category.get(category_folder, "general")
                
                # Use relative path as name for better context if in subfolder
                display_name = str(rel_path)
                
                artifact_map[display_name] = {
                    "id": f"{issue_id}:{display_name}",
                    "issue_id": issue_id,
                    "task_id": None, # Could be linked if needed
                    "kind": category,
                    "name": display_name,
                    "path": str(item),
                    "content": item.read_text(encoding="utf-8", errors="replace")[:MAX_FILE_SIZE] if item.suffix in (".md", ".json", ".txt", ".html", ".js", ".css") else "Binary content",
                }

    scan_dir(issue_root)
    return list(artifact_map.values())


@router.delete("/codex/issues/{issue_id}")
async def delete_codex_issue(issue_id: str):
    """Delete an issue and all issue-owned records."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    issue = await codex_store.load_codex_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")

    session = await codex_store.load_codex_workspace(issue.session_id)
    tasks = await codex_store.list_codex_tasks(session_id=issue.session_id, issue_id=issue_id)

    candidate_roots: list[str] = []
    if session and session.cwd:
        candidate_roots.append(session.cwd)
    candidate_roots.extend(task["workspace_path"] for task in tasks if task.get("workspace_path"))

    seen_roots: set[str] = set()
    for workspace_path in candidate_roots:
        if workspace_path in seen_roots:
            continue
        seen_roots.add(workspace_path)
        _delete_issue_artifact_root(workspace_path, issue_id)

    for task in tasks:
        await _delete_task_cascade(task["id"])

    await codex_store.delete_codex_issue(issue_id)
    await event_bus.append({
        "type": "issue_deleted",
        "issue_id": issue_id,
        "session_id": issue.session_id,
    })
    return {"deleted": issue_id}


@router.post("/codex/tasks", status_code=201)
async def create_codex_task(request: CreateTaskRequest):
    """Create a new Codex task within a session workspace."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    session = await codex_store.load_codex_session(request.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    issue = None
    if request.issue_id is not None:
        issue = await codex_store.load_codex_issue(request.issue_id)
        if issue is None:
            raise HTTPException(status_code=404, detail="Issue not found")
        if issue.session_id != request.session_id:
            raise HTTPException(status_code=409, detail="Issue does not belong to workspace")
    resolved_phase = request.phase
    expected_phase = ROLE_PHASE_DEFAULTS.get(request.role)
    if resolved_phase is None:
        resolved_phase = expected_phase or (issue.current_phase if request.issue_id is not None else "requirements")
    if resolved_phase not in VALID_ISSUE_PHASES:
        raise HTTPException(status_code=400, detail=f"Invalid task phase: {resolved_phase}")
    if expected_phase is not None and resolved_phase != expected_phase:
        raise HTTPException(
            status_code=400,
            detail=f"Role '{request.role}' must run in phase '{expected_phase}', got '{resolved_phase}'",
        )

    # Resolve and validate executor/provider/model against runtime catalog
    resolved_executor, resolved_provider, resolved_model, _, _ = await _resolve_runtime_config(
        request.executor,
        request.provider,
        request.model,
    )

    parent_task = None
    parent_workspace_path = None
    if request.parent_task_id:
        parent_task = await codex_store.load_codex_task(request.parent_task_id)
        if parent_task is None and request.task_kind != "help_child":
            raise HTTPException(status_code=404, detail="Parent task not found")
        if parent_task is not None:
            parent_workspace_path = parent_task.workspace_path
    from datetime import datetime
    from app.domain.models import CodexTask
    task_id = str(uuid4())
    if _should_use_workspace_root_for_task(session, request):
        workspace_path = session.cwd or str(workspace_manager.source_root)
    else:
        workspace_path = workspace_manager.create_workspace(task_id, parent_workspace_path=parent_workspace_path)
    task = CodexTask(
        id=task_id,
        session_id=request.session_id,
        issue_id=request.issue_id,
        phase=resolved_phase,
        title=request.title,
        prompt=request.prompt,
        role=request.role,
        executor=resolved_executor,
        provider=resolved_provider,
        model=resolved_model,
        status="pending",
        result=None,
        parent_task_id=request.parent_task_id,
        task_kind=request.task_kind,
        blocked_by_help_id=request.blocked_by_help_id,
        workspace_path=workspace_path,
        resume_session_id=None,
        resume_message_id=None,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    await codex_store.save_codex_task(task)
    # Broadcast new task with complete data structure
    await event_bus.append({
        "type": "task_created",
        "task": _serialize_task_payload(task),
    })
    return task


@router.get("/codex/tasks/{task_id}/help-requests")
async def get_codex_task_help_requests(task_id: str):
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    task = await codex_store.load_codex_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return await codex_store.list_help_requests(parent_task_id=task_id)


@router.get("/codex/tasks")
async def list_codex_tasks(session_id: str | None = None, issue_id: str | None = None):
    """List all tasks, optionally filtered by session_id."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    return await codex_store.list_codex_tasks(session_id=session_id, issue_id=issue_id)


@router.get("/codex/tasks/{task_id}")
async def get_codex_task(task_id: str):
    """Get a task by ID."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    task = await codex_store.load_codex_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.post("/codex/tasks/{task_id}/run")
async def run_codex_task(task_id: str, request: RunTaskRequest | None = None):
    """Run a task using initial or follow-up CLI semantics based on resume metadata.

    Returns an ExecutionProcess record which is bound to the task via
    task.last_execution_process_id, allowing the frontend to re-subscribe to
    the process stream after reload.

    Optional run-time overrides can be provided to change the executor/provider/model
    for this specific run. If provided and different from task defaults, the new
    values will be persisted as the task's new defaults.
    """
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    from datetime import datetime
    task = await codex_store.load_codex_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    # Serial unlock: development tasks with sequence_index > 0 must wait for previous task to be FULLY DONE (and approved)
    if task.sequence_index is not None and task.phase == "development" and task.sequence_index > 0:
        prev_index = task.sequence_index - 1
        all_tasks = await codex_store.list_codex_tasks(session_id=task.session_id, issue_id=task.issue_id)
        prev_task = next(
            (t for t in all_tasks if t.get("sequence_index") == prev_index and t.get("sequence_group") == task.sequence_group),
            None,
        )
        # Check for explicit "done" status (not awaiting_review or rework)
        if prev_task is None or prev_task.get("status") != "done":
            raise HTTPException(status_code=409, detail="需先完成上一个开发任务并通过评审")

    resume_session_id = None
    resume_message_id = None
    # Only try to resume if it's NOT a review task (Review tasks are fresh runs of Architect)
    if task.parent_task_id and getattr(task, "task_kind", "normal") != "review":
        parent_task = await codex_store.load_codex_task(task.parent_task_id)
        if parent_task is None:
            raise HTTPException(status_code=404, detail="Parent task not found")
        if not parent_task.resume_session_id:
            raise HTTPException(status_code=409, detail="Parent task is not resumable")
        resume_session_id = parent_task.resume_session_id
        resume_message_id = parent_task.resume_message_id

    try:
        exec_process = await _get_task_runner().start_task_run(
            task,
            resume_session_id=resume_session_id,
            resume_message_id=resume_message_id,
            run_executor=request.executor if request else None,
            run_provider=request.provider if request else None,
            run_model=request.model if request else None,
        )
        return exec_process
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        task.status = "failed"
        task.updated_at = datetime.now()
        await codex_store.save_codex_task(task)
        await event_bus.append({
            "type": "task_status",
            "task_id": task.id,
            "session_id": task.session_id,
            "status": "failed",
            "result": str(e),
            "execution_process_id": task.last_execution_process_id,
        })
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/codex/tasks/{task_id}/terminate")
async def terminate_codex_task(task_id: str):
    await get_codex_process_manager().terminate_task(task_id)
    return {"status": "ok"}


@router.post("/codex/tasks/{task_id}/messages", status_code=201)
async def send_codex_task_message(task_id: str, request: SendTaskMessageRequest):
    """Append a user message to a task's conversation history and trigger a follow-up run.

    The message is stored in the task message table, and the task is re-run
    in the same workspace with the new content, using the task's resume_session_id
    for conversation continuity.

    Non-blocking (vibe-kanban): marks the task running and returns immediately.
    Completion and assistant reply are delivered via the live event stream.
    """
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    from datetime import datetime
    from app.domain.models import CodexTaskMessage

    task = await codex_store.load_codex_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    message_id = str(uuid4())
    message = CodexTaskMessage(
        id=message_id,
        task_id=task_id,
        execution_process_id=None,
        role="user",
        content=request.content,
        created_at=datetime.now(),
    )
    try:
        exec_process = await _get_task_runner().start_task_run(
            task,
            prompt_override=request.content,
            resume_session_id=task.resume_session_id,
            resume_message_id=task.resume_message_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    message.execution_process_id = exec_process.id
    await codex_store.save_codex_task_message(message)
    await event_bus.append({
        "type": "message_created",
        "session_id": task.session_id,
        "execution_process_id": exec_process.id,
        "message": {
            "id": message.id,
            "task_id": message.task_id,
            "execution_process_id": message.execution_process_id,
            "role": message.role,
            "content": message.content,
            "created_at": message.created_at.isoformat() if message.created_at else None,
        }
    })

    async def _finalize_completed_task(current_task):
        current_task.status = "done"
        current_task.updated_at = datetime.now()
        await _refresh_task_result(current_task)
        await codex_store.save_codex_task(current_task)
        await codex_store.update_execution_process_status(exec_process.id, "Completed", exit_code=0, completed_at=datetime.now())
        await event_bus.append({
            "type": "task_status",
            "task_id": task_id,
            "session_id": current_task.session_id,
            "status": "done",
            "result": current_task.result,
            "execution_process_id": exec_process.id,
        })
        assistant_content = current_task.result or "Task updated."
        existing = await _list_task_messages(task_id, execution_process_id=exec_process.id)
        last = existing[-1] if existing else None
        if last and last.role == "assistant" and last.content == assistant_content:
            return last
        assistant_message = CodexTaskMessage(
            id=str(uuid4()),
            task_id=task_id,
            execution_process_id=exec_process.id,
            role="assistant",
            content=assistant_content,
            created_at=datetime.now(),
        )
        await codex_store.save_codex_task_message(assistant_message)
        await event_bus.append({
            "type": "message_created",
            "execution_process_id": exec_process.id,
            "message": {
                "id": assistant_message.id,
                "task_id": assistant_message.task_id,
                "execution_process_id": assistant_message.execution_process_id,
                "role": assistant_message.role,
                "content": assistant_message.content,
                "created_at": assistant_message.created_at.isoformat() if assistant_message.created_at else None,
            }
        })
        return assistant_message

    # Only wait for completion in mock mode; real manager relies on notifications
    if isinstance(get_codex_process_manager(), MockCodexProcessManager):
        task = await codex_store.load_codex_task(task_id) or task
        assistant_message = await _finalize_completed_task(task)
        return {"message": message, "assistant_message": assistant_message, "task": task, "execution_process": exec_process}

    # Real manager: return immediately; notification handler will update task state
    assistant_message = None
    if task.status == "done":
        assistant_message = await _finalize_completed_task(task)
    return {"message": message, "assistant_message": assistant_message, "task": task, "execution_process": exec_process}


@router.get("/codex/tasks/{task_id}/logs")
async def get_codex_task_logs(task_id: str):
    """Get logs for a specific task run."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    task = await codex_store.load_codex_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    # Return only logs tagged with this task_id
    return await codex_store.load_log_events(task.session_id, task_id=task_id, limit=1000)


@router.post("/codex/tasks/{task_id}/submit")
async def submit_codex_task_for_review(task_id: str):
    """Mark a completed development task as awaiting review and trigger automated AI review."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    
    task = await codex_store.load_codex_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    
    if task.status != "done":
        raise HTTPException(status_code=409, detail="Task must be completed before submission")
    
    # 1. Update original task status
    task.status = "awaiting_review"
    task.updated_at = datetime.now()
    await codex_store.save_codex_task(task)
    
    await event_bus.append({
        "type": "task_status",
        "task_id": task.id,
        "session_id": task.session_id,
        "status": "awaiting_review",
    })

    # 2. Automatically spawn an Architect Review task
    print(f"DEBUG: Spawning automated review task for parent_task={task.id}")
    from app.domain.models import CodexTask
    review_task_id = str(uuid4())
    review_executor, review_provider, review_model, _, _ = await _resolve_task_runtime_config(task)
    review_task = CodexTask(
        id=review_task_id,
        session_id=task.session_id,
        issue_id=task.issue_id,
        phase="architecture",  # Place in Architecture phase for visibility
        title=f"代码评审 - {task.title}",
        prompt=f"请评审任务 '{task.title}' 的实现代码。",
        role="architect",
        executor=review_executor,
        provider=review_provider,
        model=review_model,
        status="pending",
        parent_task_id=task.id,
        task_kind="review",
        workspace_path=task.workspace_path,
    )
    review_task.created_at = datetime.now()
    review_task.updated_at = datetime.now()
    await codex_store.save_codex_task(review_task)
    
    await event_bus.append({
        "type": "task_created",
        "session_id": task.session_id,
        "task": _serialize_task_payload(review_task),
    })

    # 3. Run the review task automatically
    await run_codex_task(review_task_id)
    
    return task


class TaskReviewRequest(BaseModel):
    decision: str  # "approve" | "reject"
    comment: str | None = None


@router.post("/codex/tasks/{task_id}/review")
async def review_codex_task(task_id: str, request: TaskReviewRequest):
    """Submit architect review for a task."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    
    task = await codex_store.load_codex_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    
    if request.decision == "approve":
        task.status = "done"
    else:
        task.status = "rework"
    
    task.review_comment = request.comment
    task.updated_at = datetime.now()
    await codex_store.save_codex_task(task)
    
    await event_bus.append({
        "type": "task_status",
        "task_id": task.id,
        "session_id": task.session_id,
        "status": task.status,
        "review_comment": task.review_comment,
    })
    return task


@router.delete("/codex/tasks/{task_id}")
async def delete_codex_task(task_id: str):
    """Delete a task."""
    await _delete_task_cascade(task_id)
    return {"deleted": task_id}


class ResolveApprovalRequest(BaseModel):
    item_id: str
    decision: str  # "accept", "acceptForSession", "decline", "cancel"
    feedback: str | None = None


@router.post("/codex/approvals/resolve")
async def resolve_approval(request: ResolveApprovalRequest):
    """
    Resolve a pending approval request from Codex app-server.

    Called when user approves or rejects a file change or command execution request.
    """
    mgr = get_codex_process_manager()
    success = await mgr.resolve_approval(request.item_id, request.decision)
    if not success:
        raise HTTPException(status_code=404, detail="Pending approval not found")
    return {"resolved": True, "item_id": request.item_id, "decision": request.decision}


@router.get("/codex/approvals/pending")
async def list_pending_approvals():
    """List all pending approval requests."""
    mgr = get_codex_process_manager()
    return {"pending": list(mgr.get_pending_approvals().values())}


# --- ExecutionProcess APIs ---

@router.get("/codex/execution-processes")
async def list_execution_processes(session_id: str | None = None, task_id: str | None = None):
    """List execution processes, optionally filtered by session_id and/or task_id."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    processes = await codex_store.list_execution_processes(session_id=session_id, task_id=task_id)
    return processes


@router.get("/codex/execution-processes/{process_id}")
async def get_execution_process(process_id: str):
    """Get an ExecutionProcess by ID."""
    return await _load_execution_process(process_id)


@router.get("/codex/execution-processes/{process_id}/messages")
async def get_execution_process_messages(process_id: str):
    """Get process-scoped task messages for a specific execution process."""
    process = await _load_execution_process(process_id)
    return await codex_store.list_codex_task_messages(
        process.task_id,
        execution_process_id=process.id,
    )


@router.get("/codex/execution-processes/{process_id}/logs")
async def get_execution_process_logs(process_id: str):
    """Get process-scoped logs for a specific execution process."""
    process = await _load_execution_process(process_id)
    return await codex_store.load_log_events(
        process.session_id,
        task_id=process.task_id,
        execution_process_id=process.id,
        limit=1000,
    )


# --- Runtime Catalog APIs ---

from app.application.runtime_catalog_service import RuntimeCatalogService, RuntimeCatalogValidationError


def _get_runtime_catalog_service() -> RuntimeCatalogService:
    """Get or create the runtime catalog service."""
    return RuntimeCatalogService(codex_store)


class RuntimeCatalogRequest(BaseModel):
    catalog: RuntimeCatalog


@router.get("/runtime-catalog")
async def get_runtime_catalog():
    """Get the global runtime catalog."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    service = _get_runtime_catalog_service()
    catalog = await service.load_catalog()
    return catalog


@router.put("/runtime-catalog")
async def update_runtime_catalog(request: RuntimeCatalogRequest):
    """Update the global runtime catalog.

    Validates the catalog before saving. Returns the saved catalog.
    """
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    service = _get_runtime_catalog_service()
    try:
        catalog = await service.save_catalog(request.catalog)
        return catalog
    except RuntimeCatalogValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/runtime-catalog/validate")
async def validate_runtime_catalog(request: RuntimeCatalogRequest):
    """Validate the runtime catalog without saving.

    Returns validation result: {"valid": true} or {"valid": false, "error": "..."}
    """
    service = RuntimeCatalogService(codex_store)
    try:
        service.validate_catalog(request.catalog)
        return {"valid": True}
    except RuntimeCatalogValidationError as e:
        return {"valid": False, "error": str(e)}
