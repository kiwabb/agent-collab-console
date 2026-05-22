from datetime import datetime
from uuid import uuid4
from pathlib import Path
import logging
import shutil

from fastapi import APIRouter, HTTPException, Request, Response, UploadFile, File
from fastapi.responses import JSONResponse, PlainTextResponse
import json
import os

from pydantic import BaseModel, Field
from typing import Literal
import subprocess

from app.bootstrap import session_service, orchestration_service, approval_service, codex_store, get_codex_process_manager, check_codex_available, event_bus, MockCodexProcessManager, get_help_orchestrator, project_service, worktree_manager, git_service, skill_service
from app.domain.models import CodexIssue, ConductorTask, Project
from app.application.codex_task_runner import CodexTaskRunner
from app.application.product_manager_service import ProductManagerArtifactError, ProductManagerService
from app.application.phase_duration_estimator import get_phase_duration_estimator
from app.application.role_workflow_service import RoleWorkflowService
from app.application.process_runtime_common import is_agent_message_item_type
from app.application.project_service import ProjectError
from app.application.skill_service import SkillError
from app.application.worktree_manager import WorktreeError
from app.application.git_service import GitError
from app.interfaces.execution_process_views import build_execution_process_view

logger = logging.getLogger(__name__)

# --- Custom Exception Classes ---

class APIError(Exception):
    """Base API error with status_code and message."""
    def __init__(self, status_code: int, message: str, detail: str | None = None):
        self.status_code = status_code
        self.message = message
        self.detail = detail or message

class NotFoundError(APIError):
    def __init__(self, resource: str, identifier: str):
        super().__init__(404, f"{resource} '{identifier}' not found")

class ValidationError(APIError):
    def __init__(self, message: str, field: str | None = None):
        detail = f"Validation error: {message}" if field else message
        super().__init__(400, message, detail)

class ConflictError(APIError):
    def __init__(self, message: str):
        super().__init__(409, message)

class RateLimitError(APIError):
    def __init__(self, message: str, retry_after: int = 60):
        super().__init__(429, message)
        self.retry_after = retry_after


class ProjectConductorAskRequest(BaseModel):
    question: str = Field(..., min_length=1)


class ProjectConductorStartLoopRequest(BaseModel):
    prompt: str | None = None
    issue_id: str | None = None


# --- Exception Handlers (added in main.py, not on router) ---

router = APIRouter(prefix="/api")

# Legacy phase enums removed (PR5 destructive). Phase is now a free-form tag
# on tasks and a derived presentation field on issues — the source of truth is
# the agent registry's role_keys and the workflow graph's node states.


def _try_parse_json_line(line: str) -> dict | None:
    stripped = line.strip()
    if not stripped.startswith("{"):
        return None
    try:
        parsed = json.loads(stripped)
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _pick_executor_from_tasks(tasks: list[dict]) -> tuple[str | None, str | None, str | None]:
    """Return (executor, provider, model) inherited from the most recently updated task that has them."""
    for task in sorted(tasks, key=lambda t: t.get("updated_at") or "", reverse=True):
        if task.get("executor"):
            return task.get("executor"), task.get("provider"), task.get("model")
    return None, None, None


async def _resolve_runtime_config(
    executor: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> tuple[str, str, str, dict[str, str] | None, str]:
    catalog_service = _get_runtime_catalog_service()
    catalog = await catalog_service.load_catalog()
    if not executor:
        enabled = [e for e in catalog.executors if e.enabled]
        executor = enabled[0].id if enabled else "codex"
    try:
        return catalog_service.resolve_effective_config(
            catalog,
            executor,
            provider,
            model,
        )
    except RuntimeCatalogValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))


async def _resolve_task_runtime_config(task) -> tuple[str, str, str, dict[str, str] | None, str]:
    return await _resolve_runtime_config(task.executor, task.provider, task.model)


from app.application.task_serialization import serialize_task_payload as _serialize_task_payload


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
        except TypeError:
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

    # Fallback to last line of stdout.
    # WARNING: This may not be the actual task result - the last stdout line could be
    # debug output, a progress message, or partial content. This is a best-effort
    # fallback when structured result extraction fails.
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
        if getattr(task, "result_json", None) is None:
            task.result_json = task.result
        workspace = await codex_store.load_codex_workspace(task.session_id)
        workspace_title = workspace.title if workspace is not None else None
        # Persist artifacts but never let a persist failure poison the task's
        # "done" state — the LLM produced output, the failure is a framework
        # bug (schema mismatch, fs write, etc.) that the user should see but
        # shouldn't roll back the run. Log to the project audit + tag the
        # task result so the issue UI can render a warning chip.
        try:
            artifact = await role_workflow_service.persist_result(task, workspace_title=workspace_title)
            task._subagent_doc = artifact
            if task.project_id and task.issue_id and getattr(task, "workflow_node_id", None):
                try:
                    from app.application.project_conductor import ProjectConductor
                    from app.application.subagent_result_builder import build_subagent_result

                    graph = await codex_store.load_workflow_graph_for_issue(task.issue_id)
                    node = next(
                        (n for n in (graph.nodes if graph is not None else []) if n.id == task.workflow_node_id),
                        None,
                    )
                    if node is not None:
                        envelope = build_subagent_result(task=task, node=node, doc=artifact)
                        await ProjectConductor(
                            project_id=task.project_id,
                            store=codex_store,
                            event_bus=event_bus,
                        ).notify_subagent_complete(
                            envelope,
                            project_id=task.project_id,
                            issue_id=task.issue_id,
                        )
                except Exception as exc:  # noqa: BLE001
                    logger.debug("ProjectConductor notify_subagent_complete failed for task %s: %s", task.id, exc)
        except Exception as exc:  # noqa: BLE001
            logger.exception("persist_result failed for task %s (role=%s)", task.id, getattr(task, "role", None))
            try:
                await codex_store.append_project_audit(
                    project_id=getattr(task, "project_id", None),
                    issue_id=task.issue_id,
                    event=f"persist_failed:{type(exc).__name__}",
                    base_branch=None,
                )
            except Exception:  # noqa: BLE001
                pass
            return None

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

        # QA verdict bridge: push failure reason to the WebSocket so the UI can
        # render the review_comment banner without polling.
        if task.role == "qa" and task.status in {"failed"} and task.review_comment:
            await event_bus.append({
                "type": "task_status",
                "task_id": task.id,
                "session_id": task.session_id,
                "status": task.status,
                "review_comment": task.review_comment,
            })
            try:
                from app.interfaces.codex_ws import stream_manager
                stream_manager.buffer_pending(task.session_id, {
                    "type": "task_status",
                    "task_id": task.id,
                    "status": task.status,
                    "review_comment": task.review_comment,
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



def _is_task_running(status: str | None) -> bool:
    # Only running/responding states block transitions. Pending tasks are queued, not active.
    return str(status or "").lower() in {"running", "responding"}


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


async def _cleanup_session_worktrees(session_id: str, project_id: str | None) -> None:
    """Remove all worktrees owned by issues/chat tasks under a workspace."""
    if codex_store is None or not project_id:
        return
    project = await codex_store.load_project(project_id)
    if project is None:
        return
    issues = await codex_store.list_codex_issues(session_id=session_id)
    for issue_dict in issues:
        issue = await codex_store.load_codex_issue(issue_dict["id"])
        if issue is None:
            continue
        try:
            await worktree_manager.cleanup_issue_worktree(project, issue)
        except Exception:
            pass
    chat_tasks = await codex_store.list_codex_tasks(session_id=session_id)
    for task_dict in chat_tasks:
        if task_dict.get("issue_id") or not task_dict.get("git_worktree_path"):
            continue
        task = await codex_store.load_codex_task(task_dict["id"])
        if task is None:
            continue
        try:
            await worktree_manager.cleanup_chat_task_worktree(project, task)
        except Exception:
            pass


async def _delete_task_cascade(task_id: str, *, delete_workspace: bool = True):
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    task = await codex_store.load_codex_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    # Chat tasks (no issue_id) own their own worktree; clean it up.
    # Issue-scoped task worktrees are owned by the issue and cleaned on issue delete.
    if delete_workspace and task.issue_id is None and task.git_worktree_path and task.project_id:
        project = await codex_store.load_project(task.project_id)
        if project is not None:
            try:
                await worktree_manager.cleanup_chat_task_worktree(project, task)
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
role_workflow_service = RoleWorkflowService(codex_store=codex_store)


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


@router.get("/diagnostics")
async def diagnostics():
    """Machine-readable operational snapshot for local-first deployments.

    This endpoint is intentionally safe for support screenshots and CI smoke
    checks: it reports whether secrets are configured, but never returns secret
    values.
    """
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")

    from app.bootstrap import WORKFLOW_DAG_ENABLED
    from app.interfaces.codex_ws import (
        message_stream_manager,
        raw_log_stream_manager,
        stream_manager,
    )

    now = datetime.now().isoformat()
    checks: list[dict] = []

    try:
        sessions = await codex_store.list_codex_sessions()
        issues = await codex_store.list_codex_issues()
        processes = await codex_store.list_execution_processes()
        running_processes = [
            process for process in processes
            if str(getattr(process, "status", "")).lower() in {"running", "responding"}
        ]
        database = {
            "status": "ok",
            "sessions_total": len(sessions),
            "issues_total": len(issues),
            "execution_processes_total": len(processes),
            "execution_processes_running": len(running_processes),
        }
        checks.append({"name": "database", "status": "ok"})
    except Exception as exc:  # noqa: BLE001
        database = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
        checks.append({"name": "database", "status": "error", "detail": database["error"]})

    try:
        catalog = await _get_runtime_catalog_service().load_catalog()
        enabled_executors = [executor for executor in catalog.executors if executor.enabled]
        runtime_catalog = {
            "status": "ok",
            "executors_total": len(catalog.executors),
            "executors_enabled": len(enabled_executors),
            "executors": [
                {
                    "id": executor.id,
                    "label": executor.label,
                    "enabled": executor.enabled,
                    "executor_type": executor.executor_type,
                    "providers_total": len(executor.providers),
                    "providers_enabled": len([provider for provider in executor.providers if provider.enabled]),
                    "default_provider_id": executor.default_provider_id,
                    "default_model": executor.default_model,
                    "api_endpoint_configured": bool(executor.api_endpoint),
                    "api_key_configured": bool(executor.api_key),
                }
                for executor in catalog.executors
            ],
        }
        checks.append({
            "name": "runtime_catalog",
            "status": "ok" if enabled_executors else "degraded",
            "detail": None if enabled_executors else "No enabled executors configured",
        })
    except Exception as exc:  # noqa: BLE001
        runtime_catalog = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
        checks.append({"name": "runtime_catalog", "status": "error", "detail": runtime_catalog["error"]})

    config = {
        "real_cli_enabled": os.getenv("REAL_CLI", "true").lower() == "true",
        "codex_launch_enabled": os.getenv("CODEX_LAUNCH_ENABLED", "true").lower() != "false",
        "workflow_dag_enabled": WORKFLOW_DAG_ENABLED,
        "use_sqlite": os.getenv("USE_SQLITE", "true").lower() == "true",
        "sqlite_db_path_configured": bool(os.getenv("SQLITE_DB_PATH")),
        "workspace_root_configured": bool(os.getenv("CODEX_WORKSPACE_ROOT")),
        "event_bus_buffer_size": getattr(event_bus, "_buffer_size", None),
    }

    executors = {
        "codex_binary_available": check_codex_available(),
        "claude_binary_available": shutil.which("claude") is not None,
    }

    websockets = {
        "workspace_stream_workspaces": len(getattr(stream_manager, "_subscribers", {})),
        "workspace_stream_subscribers": sum(
            len(subscribers) for subscribers in getattr(stream_manager, "_subscribers", {}).values()
        ),
        "raw_log_stream_processes": len(getattr(raw_log_stream_manager, "_subscribers", {})),
        "raw_log_stream_subscribers": sum(
            len(subscribers) for subscribers in getattr(raw_log_stream_manager, "_subscribers", {}).values()
        ),
        "message_stream_processes": len(getattr(message_stream_manager, "_subscribers", {})),
        "message_stream_subscribers": sum(
            len(subscribers) for subscribers in getattr(message_stream_manager, "_subscribers", {}).values()
        ),
        "global_event_subscribers": len(getattr(event_bus, "subscribers", [])),
        "global_event_buffer_size": len(getattr(event_bus, "events", [])),
        "global_event_buffer_capacity": getattr(event_bus, "_buffer_size", None),
    }

    status = "ok"
    if any(check["status"] == "error" for check in checks):
        status = "degraded"
    elif any(check["status"] == "degraded" for check in checks):
        status = "degraded"

    return {
        "service": "agent-collab-console",
        "status": status,
        "generated_at": now,
        "database": database,
        "runtime_catalog": runtime_catalog,
        "executors": executors,
        "websockets": websockets,
        "config": config,
        "checks": checks,
    }


@router.get("/utils/select-directory")
async def select_directory():
    """Opens a native directory picker on macOS and returns the selected path."""
    try:
        # Use osascript to open a native folder picker on macOS.
        # This returns the POSIX path of the selected folder.
        # If the user cancels, it will exit with an error.
        result = subprocess.run(
            ["osascript", "-e", 'POSIX path of (choose folder with prompt "Select Directory")'],
            capture_output=True,
            text=True,
            check=True
        )
        path = result.stdout.strip()
        return {"path": path}
    except subprocess.CalledProcessError as e:
        # User likely cancelled the dialog or osascript failed
        if "User canceled" in e.stderr:
            return {"path": None}
        logger.error(f"osascript failed: {e.stderr}")
        raise HTTPException(status_code=500, detail=f"Failed to open directory picker: {e.stderr}")
    except Exception as e:
        logger.error(f"Unexpected error in select_directory: {e}")
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")


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
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")


@router.get("/sessions/{session_id}/tasks")
async def get_session_tasks(session_id: str):
    try:
        session = await session_service.get_session(session_id)
        return session.tasks
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")


@router.get("/sessions/{session_id}/messages")
async def get_session_messages(session_id: str):
    try:
        return (await session_service.get_session(session_id)).messages
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")


@router.get("/sessions/{session_id}/artifacts")
async def get_session_artifacts(session_id: str):
    try:
        return (await session_service.get_session(session_id)).artifacts
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")


@router.get("/sessions/{session_id}/runs")
async def get_session_runs(session_id: str):
    try:
        return (await session_service.get_session(session_id)).runs
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")


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
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    try:
        task = await orchestration_service.plan_task(session_id, request.title, request.assignee)
    except Exception as e:
        logger.error("Failed to create task in session %s: %s", session_id, e)
        raise HTTPException(status_code=500, detail=f"Failed to create task: {e}")
    return task


@router.post("/tasks/{task_id}/run")
async def run_task(task_id: str):
    try:
        result = await orchestration_service.run_task(task_id)
        return result
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
    except Exception as e:
        logger.error("Failed to run task %s: %s", task_id, e)
        raise HTTPException(status_code=500, detail=f"Failed to run task: {e}")


@router.post("/tasks/{task_id}/retry")
async def retry_task(task_id: str):
    try:
        result = await orchestration_service.retry_task(task_id)
        return result
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Failed to retry task %s: %s", task_id, e)
        raise HTTPException(status_code=500, detail=f"Failed to retry task: {e}")


@router.post("/tasks/{task_id}/approval")
async def request_approval(task_id: str):
    # Find session containing this task
    for session in session_service.sessions.values():
        for task in session.tasks:
            if task.id == task_id:
                try:
                    approval = await approval_service.request_submission(session.id, task_id)
                except Exception as e:
                    logger.error("Failed to request approval for task %s: %s", task_id, e)
                    raise HTTPException(status_code=500, detail=f"Failed to request approval: {e}")
                return approval
    raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")


@router.get("/approvals/{approval_id}")
async def get_approval(approval_id: str):
    try:
        return approval_service.approvals[approval_id]
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Approval '{approval_id}' not found")


@router.post("/approvals/{approval_id}/approve")
async def approve_approval(approval_id: str):
    try:
        return await approval_service.approve(approval_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Approval '{approval_id}' not found")
    except Exception as e:
        logger.error("Failed to approve approval %s: %s", approval_id, e)
        raise HTTPException(status_code=500, detail=f"Failed to approve: {e}")


@router.post("/approvals/{approval_id}/reject")
async def reject_approval(approval_id: str):
    try:
        return await approval_service.reject(approval_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Approval '{approval_id}' not found")
    except Exception as e:
        logger.error("Failed to reject approval %s: %s", approval_id, e)
        raise HTTPException(status_code=500, detail=f"Failed to reject: {e}")


# --- Projects ---


class CreateProjectRequest(BaseModel):
    name: str
    source: Literal["local", "clone"]
    repo_path: str | None = None  # source=local
    origin_url: str | None = None  # source=clone
    dest_parent: str | None = None  # source=clone


class UpdateProjectRequest(BaseModel):
    name: str | None = None
    default_branch: str | None = None
    setup_script: str | None = None


def _require_project_service():
    if project_service is None:
        raise HTTPException(status_code=503, detail="Project service unavailable (no async store)")
    return project_service


@router.get("/projects")
async def list_projects():
    svc = _require_project_service()
    return await svc.list()


@router.post("/projects", status_code=201)
async def create_project(request: CreateProjectRequest):
    svc = _require_project_service()
    try:
        if request.source == "local":
            if not request.repo_path:
                raise HTTPException(status_code=400, detail="repo_path is required for source=local")
            return await svc.create_from_local(request.name, request.repo_path)
        if not request.origin_url or not request.dest_parent:
            raise HTTPException(status_code=400, detail="origin_url and dest_parent are required for source=clone")
        return await svc.create_from_clone(request.name, request.origin_url, request.dest_parent)
    except ProjectError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/projects/{project_id}")
async def get_project(project_id: str):
    svc = _require_project_service()
    try:
        return await svc.get(project_id)
    except ProjectError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.patch("/projects/{project_id}")
async def update_project(project_id: str, request: UpdateProjectRequest):
    svc = _require_project_service()
    try:
        return await svc.update(
            project_id,
            name=request.name,
            default_branch=request.default_branch,
            setup_script=request.setup_script,
        )
    except ProjectError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.delete("/projects/{project_id}")
async def delete_project(project_id: str, force: bool = False):
    """Delete a project record.

    Refuses if any session still references this project, unless `force=true`.
    With force, cascade-deletes all sessions under the project (which in turn
    cleans up issue + chat-task worktrees via _cleanup_session_worktrees).
    """
    svc = _require_project_service()
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    try:
        await svc.get(project_id)
    except ProjectError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    related_sessions = await codex_store.list_codex_sessions(project_id=project_id)
    if related_sessions and not force:
        raise HTTPException(
            status_code=409,
            detail=(
                f"project has {len(related_sessions)} workspace(s) attached; "
                "pass ?force=true to cascade-delete them"
            ),
        )
    project = await svc.get(project_id)
    for ws in related_sessions:
        try:
            await _cleanup_session_worktrees(ws["id"], project_id)
        except Exception:
            pass
        await codex_store.delete_codex_session(ws["id"])
    # Best-effort: remove the now-empty `<name>-worktrees/` parent so the user's
    # filesystem doesn't accumulate empty bookkeeping dirs.
    worktree_parent = Path(project.repo_path).parent / f"{project.name}-worktrees"
    if worktree_parent.exists() and not any(worktree_parent.iterdir()):
        try:
            worktree_parent.rmdir()
        except OSError:
            pass
    await svc.delete(project_id)
    return {"deleted": project_id, "cascaded_sessions": len(related_sessions)}


@router.get("/projects/{project_id}/branches")
async def get_project_branches(project_id: str):
    svc = _require_project_service()
    try:
        return await svc.list_branches(project_id)
    except ProjectError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except GitError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/projects/{project_id}/stats")
async def get_project_stats(project_id: str):
    """Aggregate counts for the project detail view.

    Returns workspaces total + issues bucketed by git merge state. The FE uses
    this to render the "12 workspaces • 3 open / 7 merged / 2 abandoned" summary
    without doing two extra list calls.
    """
    svc = _require_project_service()
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    try:
        await svc.get(project_id)
    except ProjectError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    workspaces = await codex_store.list_codex_sessions(project_id=project_id)
    issues = await codex_store.list_codex_issues(project_id=project_id)
    counts = {"open": 0, "merged": 0, "abandoned": 0}
    for issue in issues:
        # Load full issue to get git_merge_status (list query strips it).
        full = await codex_store.load_codex_issue(issue["id"])
        if full is None:
            continue
        status = full.git_merge_status if full.git_merge_status in counts else "open"
        counts[status] += 1
    return {
        "workspaces": len(workspaces),
        "issues_total": len(issues),
        "issues_open": counts["open"],
        "issues_merged": counts["merged"],
        "issues_abandoned": counts["abandoned"],
    }


# --- Skills library ---

class CreateSkillRequest(BaseModel):
    name: str = Field(..., min_length=1)
    link: str = Field(..., min_length=1)
    description: str | None = None
    category: str | None = None
    tags: list[str] = Field(default_factory=list)


class UpdateSkillRequest(BaseModel):
    name: str | None = None
    link: str | None = None
    description: str | None = None
    category: str | None = None
    tags: list[str] | None = None


def _require_skill_service():
    if skill_service is None:
        raise HTTPException(status_code=503, detail="Skill service unavailable (no async store)")
    return skill_service


@router.get("/skills")
async def list_skills(search: str | None = None, category: str | None = None):
    svc = _require_skill_service()
    items = await svc.list(search=search, category=category)
    return [s.model_dump(mode="json") for s in items]


@router.get("/skills/categories")
async def list_skill_categories():
    svc = _require_skill_service()
    return await svc.list_categories()


class SkillCategoryRequest(BaseModel):
    name: str = Field(..., min_length=1)


@router.post("/skills/categories", status_code=201)
async def create_skill_category(request: SkillCategoryRequest):
    svc = _require_skill_service()
    try:
        name = await svc.add_category(request.name)
    except SkillError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"name": name}


@router.delete("/skills/categories/{name}")
async def delete_skill_category(name: str, force: bool = False):
    svc = _require_skill_service()
    try:
        await svc.delete_category(name, force=force)
    except SkillError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"ok": True}


def _rewrite_to_raw(url: str) -> str:
    """Forgiving URL normaliser — turns common GitHub/gist VIEW pages into the
    raw-content equivalents. If we don't know how to rewrite, return as-is and
    let the caller deal with HTML.

    Repo-root URLs (e.g. github.com/<owner>/<repo>) resolve to the repo's
    README via the special `HEAD` ref, which GitHub maps to the default branch.
    """
    import re
    url = url.rstrip("/")
    # GitHub blob view → raw
    m = re.match(r"^https?://github\.com/([^/]+)/([^/]+)/blob/(.+)$", url)
    if m:
        return f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}/{m.group(3)}"
    # GitHub raw view (rare alt path) → raw.githubusercontent
    m = re.match(r"^https?://github\.com/([^/]+)/([^/]+)/raw/(.+)$", url)
    if m:
        return f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}/{m.group(3)}"
    # GitHub tree view (folder) → README of that folder ref
    m = re.match(r"^https?://github\.com/([^/]+)/([^/]+)/tree/([^/]+)/?(.*)$", url)
    if m:
        owner, repo, ref, path = m.group(1), m.group(2), m.group(3), m.group(4)
        suffix = f"{path.rstrip('/')}/README.md" if path else "README.md"
        return f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{suffix}"
    # Repo root → README at HEAD (HEAD = default branch on raw.githubusercontent)
    m = re.match(r"^https?://github\.com/([^/]+)/([^/]+)$", url)
    if m:
        return f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}/HEAD/README.md"
    # Gist view → raw (only single-file gists handled reliably)
    m = re.match(r"^https?://gist\.github\.com/([^/]+)/([0-9a-f]+)$", url)
    if m:
        return f"https://gist.githubusercontent.com/{m.group(1)}/{m.group(2)}/raw"
    return url


@router.get("/skills/proxy")
async def proxy_skill_link(url: str):
    """Fetch the markdown body of a remote skill link. Used by the right-side
    preview panel — we don't persist body locally; this bypasses browser CORS
    for raw.githubusercontent.com / gist / etc.

    Common GitHub/gist VIEW URLs are auto-rewritten to their raw equivalents
    so users can paste the URL straight from their browser bar.
    """
    if not url or not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(status_code=400, detail="url must be an absolute http(s) URL")
    target = _rewrite_to_raw(url)
    import httpx
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(target, headers={"User-Agent": "agent-collab-console/skills"})
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"upstream fetch failed: {exc}")
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=f"upstream returned {resp.status_code}")
    ctype = (resp.headers.get("content-type") or "").lower()
    # If upstream gave us an HTML page (user pasted a non-raw link we couldn't
    # rewrite), refuse loudly instead of dumping HTML tags into the preview.
    if "html" in ctype:
        raise HTTPException(
            status_code=415,
            detail=(
                "upstream returned HTML, not markdown. Paste the raw file URL "
                "(e.g. raw.githubusercontent.com/...) instead of the page URL."
            ),
        )
    return PlainTextResponse(resp.text, media_type="text/markdown; charset=utf-8")


class SkillTranslateRequest(BaseModel):
    text: str = Field(..., min_length=1)
    target: Literal["zh", "en"] = "zh"


@router.post("/skills/translate")
async def translate_skill_content(request: SkillTranslateRequest):
    """Translate markdown content between Chinese and English using the
    configured Anthropic-compatible executor. Preserves markdown / code / URLs.
    """
    from app.application.llm_runner import _pick_executor, _resolve_model

    catalog_service = _get_runtime_catalog_service()
    catalog = await catalog_service.load_catalog()
    executor = _pick_executor(catalog, os.getenv("WORKFLOW_ORCHESTRATOR_EXECUTOR_ID") or None)
    if executor is None:
        raise HTTPException(status_code=503, detail="No usable executor configured for translation")
    model = _resolve_model(executor, os.getenv("WORKFLOW_ORCHESTRATOR_MODEL") or None)
    if not model:
        raise HTTPException(status_code=503, detail="No resolvable model on the executor")

    # Cap input to a safe size (avoids context-window blow-ups and runaway cost).
    MAX_CHARS = 30000
    text = request.text
    truncated = False
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS]
        truncated = True

    target_label = "Simplified Chinese (简体中文)" if request.target == "zh" else "English"
    system_prompt = (
        f"You are a professional markdown translator. Translate the user's content into {target_label}.\n"
        "Rules:\n"
        "1. Preserve ALL markdown formatting exactly (headings, lists, tables, blockquotes, links, images).\n"
        "2. Do NOT translate content inside code blocks, inline code, URLs, file paths, or HTML attribute values.\n"
        "3. Preserve raw HTML tags (<details>, <summary>, <img>, <picture>, ...) — only translate the visible text.\n"
        "4. Keep proper nouns, library / API / command names untranslated.\n"
        "5. Output ONLY the translated markdown — no preamble, no explanation, no surrounding ``` fence."
    )

    url = f"{executor.api_endpoint.rstrip('/')}/v1/messages"
    payload = {
        "model": model,
        "max_tokens": 16384,
        "system": system_prompt,
        "messages": [{"role": "user", "content": text}],
    }
    import httpx
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                url,
                headers={
                    "x-api-key": executor.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=payload,
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"LLM request failed: {exc}")
    if resp.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"LLM returned HTTP {resp.status_code}: {resp.text[:300]}",
        )
    data = resp.json()
    parts = data.get("content") or []
    translated = "".join(
        p.get("text", "")
        for p in parts
        if isinstance(p, dict) and p.get("type") == "text"
    ).strip()
    if not translated:
        raise HTTPException(status_code=502, detail="LLM returned empty content")
    return {"translated": translated, "target": request.target, "truncated": truncated, "model": model}


@router.post("/skills", status_code=201)
async def create_skill(request: CreateSkillRequest):
    svc = _require_skill_service()
    try:
        skill = await svc.create(
            name=request.name,
            link=request.link,
            description=request.description,
            category=request.category,
            tags=request.tags,
        )
        return skill.model_dump(mode="json")
    except SkillError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/skills/{skill_id}")
async def get_skill(skill_id: str):
    svc = _require_skill_service()
    skill = await svc.get(skill_id)
    if skill is None:
        raise HTTPException(status_code=404, detail=f"skill not found: {skill_id}")
    return skill.model_dump(mode="json")


@router.patch("/skills/{skill_id}")
async def update_skill(skill_id: str, request: UpdateSkillRequest):
    svc = _require_skill_service()
    try:
        skill = await svc.update(
            skill_id,
            name=request.name,
            link=request.link,
            description=request.description,
            category=request.category,
            tags=request.tags,
        )
        return skill.model_dump(mode="json")
    except SkillError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.delete("/skills/{skill_id}")
async def delete_skill(skill_id: str):
    svc = _require_skill_service()
    await svc.delete(skill_id)
    return {"deleted": skill_id}


@router.post("/skills/import/md")
async def import_skills_md(files: list[UploadFile] = File(...)):
    svc = _require_skill_service()
    payloads: list[tuple[str, bytes]] = []
    for f in files:
        payloads.append((f.filename or "skill.md", await f.read()))
    result = await svc.import_markdown(payloads)
    return {
        "created": [s.model_dump(mode="json") for s in result["created"]],
        "skipped": result["skipped"],
    }


@router.post("/skills/import/excel")
async def import_skills_excel(file: UploadFile = File(...)):
    svc = _require_skill_service()
    try:
        result = await svc.import_excel(await file.read())
    except SkillError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "created": [s.model_dump(mode="json") for s in result["created"]],
        "skipped": result["skipped"],
    }


@router.get("/codex/stats")
async def get_codex_stats():
    """Aggregate counts across all Codex sessions and issues.

    Returns workspace/session counts, task metrics bucketed by status,
    and executor availability flags. Computed on-demand; no persistence.
    """
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")

    sessions = await codex_store.list_codex_sessions()
    issues = await codex_store.list_codex_issues()

    sessions_active = 0
    for session in sessions:
        if session.get("status") == "running":
            sessions_active += 1

    tasks_total = 0
    tasks_pending = 0
    tasks_running = 0
    tasks_completed = 0
    tasks_failed = 0
    last_activity_at = None

    for issue in issues:
        tasks_total += 1
        status = issue.get("status", "pending")
        if status == "pending":
            tasks_pending += 1
        elif status in ("running", "responding"):
            tasks_running += 1
        elif status == "done":
            tasks_completed += 1
        elif status == "failed":
            tasks_failed += 1
        # Track most recent activity timestamp
        updated_at = issue.get("updated_at") or issue.get("created_at")
        if updated_at:
            if last_activity_at is None or updated_at > last_activity_at:
                last_activity_at = updated_at

    # Executor availability
    codex_available = check_codex_available()
    claude_available = False
    try:
        pm = get_codex_process_manager()
        if pm is not None:
            # Claude executor is available if any process slots are free
            # We check the process count vs max - simplified check
            claude_available = hasattr(pm, '_processes') or hasattr(pm, 'max_processes')
    except Exception:
        pass

    return {
        "workspaces_total": len(sessions),
        "sessions_total": len(sessions),
        "sessions_active": sessions_active,
        "tasks_total": tasks_total,
        "tasks_pending": tasks_pending,
        "tasks_running": tasks_running,
        "tasks_completed": tasks_completed,
        "tasks_failed": tasks_failed,
        "executor_codex_available": codex_available,
        "executor_claude_available": claude_available,
        "last_activity_at": last_activity_at,
    }


@router.get("/codex/issues/{issue_id}/checklist")
async def get_issue_checklist(issue_id: str):
    """Per-issue acceptance checklist.

    Reads PM's `acceptance_criteria` and matches them against QA's
    `acceptance_coverage`, plus the engineer's `completed_tasks`. Items
    are marked covered when QA explicitly mentions them OR the engineer
    flagged them done.

    Returns:
        {
          criteria: [{text, covered: bool, source: str | null}],
          qa_status: str | null,
          engineer_status: str | null
        }
    """
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    import json as _json
    from pathlib import Path
    issue = await codex_store.load_codex_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    worktree = issue.git_worktree_path
    if not worktree:
        return {"criteria": [], "qa_status": None, "engineer_status": None}

    def _read_json(rel: str) -> dict | None:
        p = Path(worktree) / "issues" / issue_id / rel
        if not p.exists():
            return None
        try:
            return _json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    prd = _read_json("pm/prd.json") or {}
    qa = _read_json("qa/qa_plan.json") or {}
    eng = None
    eng_dir = Path(worktree) / "issues" / issue_id / "engineer"
    if eng_dir.exists():
        for impl in sorted(eng_dir.glob("implementation-*.md")):
            try:
                txt = impl.read_text(encoding="utf-8")
            except OSError:
                continue
            eng = (eng or "") + "\n" + txt

    criteria = prd.get("acceptance_criteria") or []
    if not isinstance(criteria, list):
        criteria = []
    qa_cov = " || ".join(map(str, qa.get("acceptance_coverage") or [])).lower()
    qa_status = qa.get("status") if isinstance(qa, dict) else None

    out = []
    for c in criteria:
        text = str(c).strip()
        if not text:
            continue
        # A criterion is "covered" if QA's acceptance_coverage list mentions
        # any substantial slice of it (≥6 chars overlap). Cheap but works
        # well for human-written criteria + LLM-written coverage notes.
        snippet = " ".join(text.lower().split())
        covered = False
        source = None
        if qa_cov:
            for token in snippet.split():
                if len(token) >= 6 and token in qa_cov:
                    covered = True
                    source = "qa"
                    break
        if not covered and eng:
            eng_lower = eng.lower()
            for token in snippet.split():
                if len(token) >= 6 and token in eng_lower:
                    covered = True
                    source = "engineer"
                    break
        out.append({"text": text, "covered": covered, "source": source})

    return {
        "criteria": out,
        "qa_status": qa_status,
        "engineer_status": (
            (prd.get("status") if isinstance(prd, dict) else None) or None
        ),
    }


@router.get("/codex/issues/{issue_id}/pipeline-stages")
async def get_issue_pipeline_stages(issue_id: str):
    """Aggregated per-role pipeline summary for the Issue Detail Hero / Trace.

    Always returns 4 stages (PM / Architect / Engineer / QA) regardless of
    whether the workflow graph is set up — UI can render the same template
    even before the DAG materializes. Summary lines are deterministic
    extracts from on-disk artifacts (no LLM calls).

    Returns:
        {
          stages: [
            {
              role, label, status, started_at, completed_at,
              duration_seconds, summary, foot, task_id
            }, ...
          ],
          started_at, completed_at, total_duration_seconds
        }
    """
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    import json as _json
    import re as _re
    from datetime import datetime as _dt
    from pathlib import Path

    issue = await codex_store.load_codex_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")

    # Map workflow nodes to roles via agent.role_key.
    nodes_by_role: dict[str, list] = {}
    graph = await codex_store.load_workflow_graph_for_issue(issue_id)
    if graph is not None:
        agents = await codex_store.list_agents(workspace_id=None)
        agent_role = {a.id: a.role_key for a in agents}
        for n in graph.nodes:
            role = agent_role.get(n.agent_id)
            if role:
                nodes_by_role.setdefault(role, []).append(n)

    worktree = issue.git_worktree_path
    issue_root: Path | None = (
        Path(worktree) / "issues" / issue_id if worktree else None
    )

    def _read_json(rel: str):
        if not issue_root:
            return None
        p = issue_root / rel
        if not p.exists():
            return None
        try:
            return _json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _engineer_stats() -> tuple[str, str]:
        if not issue_root:
            return "代码实现", ""
        eng_dir = issue_root / "engineer"
        if not eng_dir.exists():
            return "代码实现", ""
        impls = sorted(eng_dir.glob("implementation-*.md"))
        if not impls:
            return "代码实现", ""
        files_changed = 0
        added = 0
        removed = 0
        for f in impls:
            try:
                text = f.read_text(encoding="utf-8")
            except OSError:
                continue
            m_files = _re.search(
                r"(\d+)\s*files?\s*(?:changed|modified|touched)?",
                text,
                _re.IGNORECASE,
            )
            m_add = _re.search(r"\+(\d+)\s*(?:[-−]|/)", text)
            m_rm = _re.search(r"[-−](\d+)\b", text)
            if m_files:
                try:
                    files_changed = max(files_changed, int(m_files.group(1)))
                except ValueError:
                    pass
            if m_add:
                try:
                    added = max(added, int(m_add.group(1)))
                except ValueError:
                    pass
            if m_rm:
                try:
                    removed = max(removed, int(m_rm.group(1)))
                except ValueError:
                    pass
        if files_changed or added or removed:
            parts: list[str] = []
            if files_changed:
                parts.append(f"{files_changed} files")
            if added or removed:
                parts.append(f"+{added} −{removed}")
            summary = "代码实现 · " + " · ".join(parts)
        else:
            summary = "代码实现"
        return summary, "implementation report 已生成"

    def _stage_summary(role_key: str) -> tuple[str, str]:
        if role_key == "product_manager":
            prd = _read_json("pm/prd.json") or {}
            criteria = prd.get("acceptance_criteria") or []
            goals = prd.get("goals") or []
            reqs = (
                prd.get("requirements")
                or prd.get("functional_requirements")
                or []
            )
            n_c = (
                len([c for c in criteria if c])
                if isinstance(criteria, list)
                else 0
            )
            n_g = (
                len([g for g in goals if g])
                if isinstance(goals, list)
                else 0
            )
            n_r = (
                len([r for r in reqs if r]) if isinstance(reqs, list) else 0
            )
            summary = (
                f"需求分解 · {n_c} acceptance criteria" if n_c else "需求分解"
            )
            parts: list[str] = []
            if n_g:
                parts.append(f"{n_g} goals")
            if n_r:
                parts.append(f"{n_r} reqs")
            return summary, " · ".join(parts)
        if role_key == "architect":
            design = _read_json("architect/system_design.json") or {}
            comps = design.get("components") or []
            sch = (
                design.get("schemas")
                or design.get("data_models")
                or []
            )
            mig = design.get("migrations") or []
            n_c = len(comps) if isinstance(comps, list) else 0
            n_s = len(sch) if isinstance(sch, list) else 0
            n_m = len(mig) if isinstance(mig, list) else 0
            summary = (
                f"系统设计 · {n_c} component" if n_c else "系统设计"
            )
            parts: list[str] = []
            if n_s:
                parts.append(f"{n_s} schemas")
            if n_m:
                parts.append(f"{n_m} migrations")
            return summary, " · ".join(parts)
        if role_key == "engineer":
            return _engineer_stats()
        if role_key == "qa":
            qa = _read_json("qa/qa_plan.json") or {}
            status_lbl = (qa.get("status") or "").lower()
            cmds = (
                qa.get("recommended_commands")
                or qa.get("commands")
                or []
            )
            n_cmds = len(cmds) if isinstance(cmds, list) else 0
            passed = qa.get("passed") or 0
            failed = qa.get("failed") or 0
            results = (
                qa.get("results")
                if isinstance(qa.get("results"), dict)
                else None
            )
            if results:
                passed = results.get("passed") or passed
                failed = results.get("failed") or failed
            if status_lbl in ("passed", "ok", "done"):
                summary = (
                    f"验证通过 · {n_cmds} cmd · {failed} failed"
                    if n_cmds
                    else "验证通过"
                )
            elif status_lbl in ("failed", "error"):
                summary = (
                    f"验证失败 · {n_cmds} cmd · {failed} failed"
                    if n_cmds
                    else "验证失败"
                )
            else:
                summary = "验证"
            foot_parts: list[str] = []
            if cmds:
                first = cmds[0]
                first_text = (
                    first
                    if isinstance(first, str)
                    else (
                        first.get("cmd")
                        or first.get("command")
                        or ""
                    )
                )
                if first_text:
                    foot_parts.append(first_text.split()[0])
            if passed:
                foot_parts.append(f"{passed} passed")
            return summary, " · ".join(foot_parts)
        return "", ""

    role_labels = [
        ("product_manager", "PM"),
        ("architect", "Architect"),
        ("engineer", "Engineer"),
        ("qa", "QA"),
    ]

    def _aggregate_status(statuses: list[str]) -> str:
        if not statuses:
            return "pending"
        lowered = [(s or "").lower() for s in statuses]
        if any(s in ("failed", "error") for s in lowered):
            return "failed"
        if any(s == "running" for s in lowered):
            return "running"
        if any(s in ("awaiting_review", "awaiting_approval") for s in lowered):
            return "awaiting"
        if all(s in ("done", "skipped") for s in lowered):
            return "done"
        if any(s in ("done", "skipped") for s in lowered):
            return "running"
        return lowered[0] or "pending"

    stages = []
    for role_key, label in role_labels:
        role_nodes = nodes_by_role.get(role_key, [])
        if role_nodes:
            status = _aggregate_status([n.status for n in role_nodes])
            starts = [n.started_at for n in role_nodes if n.started_at]
            completes = [n.completed_at for n in role_nodes if n.completed_at]
            started_at = min(starts).isoformat() if starts else None
            completed_at = (
                max(completes).isoformat()
                if completes and status == "done"
                else None
            )
            primary_task_id = next(
                (n.task_id for n in role_nodes if n.task_id), None
            )
        else:
            status = "pending"
            started_at = None
            completed_at = None
            primary_task_id = None

        summary, foot = _stage_summary(role_key)

        duration_seconds = None
        if started_at and completed_at:
            try:
                a = _dt.fromisoformat(started_at)
                b = _dt.fromisoformat(completed_at)
                duration_seconds = max(0, int((b - a).total_seconds()))
            except ValueError:
                pass

        stages.append(
            {
                "role": role_key,
                "label": label,
                "status": status,
                "started_at": started_at,
                "completed_at": completed_at,
                "duration_seconds": duration_seconds,
                "summary": summary,
                "foot": foot,
                "task_id": primary_task_id,
            }
        )

    starts_all = [s["started_at"] for s in stages if s.get("started_at")]
    started_at_all = min(starts_all) if starts_all else None
    completed_at_all = None
    total_duration = None
    if stages and all(s["status"] == "done" for s in stages):
        completes_all = [
            s["completed_at"] for s in stages if s.get("completed_at")
        ]
        if completes_all:
            completed_at_all = max(completes_all)
    if started_at_all and completed_at_all:
        try:
            a = _dt.fromisoformat(started_at_all)
            b = _dt.fromisoformat(completed_at_all)
            total_duration = max(0, int((b - a).total_seconds()))
        except ValueError:
            pass

    return {
        "stages": stages,
        "started_at": started_at_all,
        "completed_at": completed_at_all,
        "total_duration_seconds": total_duration,
    }


@router.get("/codex/issues/{issue_id}/activity")
async def get_issue_activity(issue_id: str, limit: int = 50):
    """Time-ordered activity stream for the Issue Detail side panel.

    Derives events from:
      - issue created_at (synthetic "issue_created")
      - per-task lifecycle (created → started; updated → done/failed)
      - project_audit entries scoped to this issue (created/merged/...)

    Events are deduplicated by (type, timestamp, role) and sorted oldest
    first so the UI can drop the newest N on the timeline tail.
    """
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    from datetime import datetime as _dt

    issue = await codex_store.load_codex_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")

    role_label = {
        "product_manager": "PM",
        "architect": "Architect",
        "engineer": "Engineer",
        "qa": "QA",
    }

    events: list[dict] = []

    if issue.created_at:
        events.append(
            {
                "type": "issue_created",
                "timestamp": issue.created_at.isoformat()
                if hasattr(issue.created_at, "isoformat")
                else str(issue.created_at),
                "actor": "system",
                "role": None,
                "text": "创建 issue",
                "aux": issue.title,
            }
        )

    tasks = await codex_store.list_codex_tasks(issue_id=issue_id)
    for t in tasks:
        role = t.get("role")
        actor = role_label.get(role, role or "agent")
        if t.get("created_at"):
            events.append(
                {
                    "type": "task_started",
                    "timestamp": t["created_at"],
                    "actor": actor,
                    "role": role,
                    "text": t.get("title") or "(no title)",
                    "aux": None,
                }
            )
        status = (t.get("status") or "").lower()
        if status in ("done", "failed") and t.get("updated_at"):
            events.append(
                {
                    "type": f"task_{status}",
                    "timestamp": t["updated_at"],
                    "actor": actor,
                    "role": role,
                    "text": (
                        f"{actor} 完成" if status == "done" else f"{actor} 失败"
                    ),
                    "aux": t.get("title"),
                }
            )

    if issue.project_id:
        try:
            audit = await codex_store.list_project_audit(
                issue.project_id, limit=200
            )
        except Exception:
            audit = []
        for a in audit:
            if a.get("issue_id") != issue_id:
                continue
            ts = a.get("created_at")
            if not ts:
                continue
            events.append(
                {
                    "type": f"audit_{a.get('event') or 'event'}",
                    "timestamp": ts,
                    "actor": "git",
                    "role": None,
                    "text": a.get("event") or "",
                    "aux": a.get("sha")
                    or a.get("base_branch")
                    or None,
                }
            )

    def _ts_key(e: dict) -> str:
        return e.get("timestamp") or ""

    events.sort(key=_ts_key)

    # Dedup adjacent identical events (same type + actor + ts).
    deduped: list[dict] = []
    last_key: tuple | None = None
    for e in events:
        key = (e["type"], e.get("actor"), e["timestamp"])
        if key == last_key:
            continue
        deduped.append(e)
        last_key = key

    # Apply tail limit if requested.
    if limit and len(deduped) > limit:
        deduped = deduped[-limit:]

    return {"events": deduped}


@router.get("/codex/cost-stats")
async def get_codex_cost_stats(
    issue_id: str | None = None,
    workspace_id: str | None = None,
    limit_per_scope: int = 5000,
):
    """Aggregate token usage from log events to give the UI a real-time
    cost meter.

    The Codex app server emits stream events that include a
    `usage: {input_tokens, output_tokens, cache_creation_input_tokens,
    cache_read_input_tokens}` field. We scan the raw stdout JSON,
    extract the latest usage per assistant message and sum them.

    Args:
        issue_id: scope to one issue (preferred for issue-level meter)
        workspace_id: scope to one workspace (preferred for session-level)
        limit_per_scope: cap how many log rows we inspect to stay fast

    Returns:
        {input_tokens, output_tokens, cache_read_tokens, est_cost_usd, sample_size}
    """
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    import json as _json
    # Pricing knobs — overridable so the UI doesn't lie when you switch model.
    # Defaults track gpt-5-mini-ish: $0.30 / 1M input, $1.20 / 1M output, free cache reads.
    input_per_m = float(os.getenv("COST_USD_PER_M_INPUT", "0.30"))
    output_per_m = float(os.getenv("COST_USD_PER_M_OUTPUT", "1.20"))
    cache_per_m = float(os.getenv("COST_USD_PER_M_CACHE_READ", "0.075"))

    target_session_ids: list[str] = []
    target_task_ids: list[str] = []
    if issue_id:
        tasks_in_issue = await codex_store.list_codex_tasks(issue_id=issue_id)
        # list_codex_tasks returns dicts, not models.
        target_task_ids = [t["id"] for t in tasks_in_issue if t.get("id")]
        if tasks_in_issue:
            session_ids = {t.get("session_id") for t in tasks_in_issue if t.get("session_id")}
            target_session_ids = list(session_ids)
    elif workspace_id:
        target_session_ids = [workspace_id]
    else:
        sessions = await codex_store.list_codex_sessions(project_id=None)
        target_session_ids = [s.get("id") for s in sessions if s.get("id")]

    input_tokens = 0
    output_tokens = 0
    cache_read_tokens = 0
    sample_size = 0
    seen_message_ids: set[str] = set()  # dedup re-emitted assistant messages

    for sid in target_session_ids:
        rows = []
        if target_task_ids:
            for tid in target_task_ids:
                rows.extend(
                    await codex_store.load_log_events(
                        session_id=sid, task_id=tid, limit=limit_per_scope
                    )
                )
        else:
            rows = await codex_store.load_log_events(
                session_id=sid, limit=limit_per_scope
            )
        for ev in rows:
            content = ev.content or ""
            if "usage" not in content or "input_tokens" not in content:
                continue
            try:
                obj = _json.loads(content)
            except (ValueError, TypeError):
                continue
            sample_size += 1
            usage = _extract_usage(obj)
            if not usage:
                continue
            msg_id = _extract_message_id(obj)
            if msg_id and msg_id in seen_message_ids:
                continue
            if msg_id:
                seen_message_ids.add(msg_id)
            input_tokens += int(usage.get("input_tokens") or 0)
            output_tokens += int(usage.get("output_tokens") or 0)
            cache_read_tokens += int(usage.get("cache_read_input_tokens") or 0)

    est_cost = (
        input_tokens * input_per_m / 1_000_000
        + output_tokens * output_per_m / 1_000_000
        + cache_read_tokens * cache_per_m / 1_000_000
    )
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_tokens": cache_read_tokens,
        "est_cost_usd": round(est_cost, 4),
        "sample_size": sample_size,
        "pricing": {
            "input_per_m": input_per_m,
            "output_per_m": output_per_m,
            "cache_per_m": cache_per_m,
        },
    }


def _extract_usage(obj):
    """Pull the usage dict out of a Codex / Claude stream event payload.

    Codex app server emits shapes like:
      {"type":"assistant","message":{...,"usage":{...}}}
      {"type":"stream_event","event":{"type":"message_delta","usage":{...}}}
    """
    if not isinstance(obj, dict):
        return None
    if isinstance(obj.get("usage"), dict):
        return obj["usage"]
    msg = obj.get("message")
    if isinstance(msg, dict) and isinstance(msg.get("usage"), dict):
        return msg["usage"]
    event = obj.get("event")
    if isinstance(event, dict) and isinstance(event.get("usage"), dict):
        return event["usage"]
    return None


def _extract_message_id(obj):
    if not isinstance(obj, dict):
        return None
    msg = obj.get("message")
    if isinstance(msg, dict):
        mid = msg.get("id")
        if isinstance(mid, str):
            return mid
    return None


@router.get("/projects/{project_id}/audit")
async def get_project_audit(project_id: str, limit: int = 50, since: str | None = None):
    """Recent project events (most recent first).

    `since` is an ISO-8601 timestamp; entries strictly older than it are skipped.
    """
    svc = _require_project_service()
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    try:
        await svc.get(project_id)
    except ProjectError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return await codex_store.list_project_audit(
        project_id, limit=max(1, min(limit, 200)), since=since,
    )


@router.post("/projects/{project_id}/repair")
async def repair_project(project_id: str):
    """Reconcile DB worktree paths with what git + disk actually have.

    - Prunes stale `.git/worktrees/*` metadata.
    - For every issue under the project: if its `git_worktree_path` no longer
      exists on disk, clear the DB fields so the next task creation rebuilds it.
    """
    svc = _require_project_service()
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    try:
        project = await svc.get(project_id)
    except ProjectError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    try:
        await worktree_manager.prune(project)
    except GitError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    issues = await codex_store.list_codex_issues(project_id=project_id)
    live_issue_ids = {i["id"] for i in issues}
    repaired = 0
    for issue_dict in issues:
        issue = await codex_store.load_codex_issue(issue_dict["id"])
        if issue is None:
            continue
        # Reset when EITHER the on-disk worktree is gone, OR the branch ref
        # has been deleted from the repo (covers `git branch -D` mishaps).
        worktree_missing = bool(issue.git_worktree_path) and not Path(issue.git_worktree_path).exists()
        branch_missing = bool(issue.git_branch) and not await git_service.branch_exists(project.repo_path, issue.git_branch)
        if not (worktree_missing or branch_missing):
            continue
        issue.git_branch = None
        issue.git_base_branch = None
        issue.git_worktree_path = None
        issue.git_last_commit_sha = None
        await codex_store.save_codex_issue(issue)
        repaired += 1
    # Orphan-dir GC: any `issue-<id>` dir under `<name>-worktrees/` that no
    # longer corresponds to a live issue is leftover from a crashed delete.
    orphans_removed = 0
    worktree_parent = Path(project.repo_path).parent / f"{project.name}-worktrees"
    if worktree_parent.exists():
        for entry in worktree_parent.iterdir():
            if not entry.is_dir():
                continue
            if not entry.name.startswith("issue-"):
                continue
            issue_id = entry.name[len("issue-") :]
            if issue_id in live_issue_ids:
                continue
            try:
                await git_service.remove_worktree(project.repo_path, entry)
            except Exception:
                pass
            try:
                shutil.rmtree(entry, ignore_errors=True)
                orphans_removed += 1
            except OSError:
                pass
    return {"pruned": True, "issues_reset": repaired, "orphan_dirs_removed": orphans_removed}


# --- Codex CLI Session APIs ---


class CreateCodexSessionRequest(BaseModel):
    # Title must be at least 3 chars to avoid the historical "1"/"2" anonymous
    # workspaces that are indistinguishable in the sidebar. The UI shows a
    # generated fallback for legacy rows; new rows are required to pick a
    # real name.
    title: str = Field(min_length=3)
    project_id: str
    cwd: str = ""


class UpdateCodexWorkspaceRequest(BaseModel):
    # PATCH validation: when title is provided it must be ≥3 chars; omitting
    # the field entirely is still valid (you might only be updating cwd).
    title: str | None = Field(default=None, min_length=3)
    cwd: str | None = None
    plan_first_pm: bool | None = None


@router.get("/codex/status")
async def codex_status():
    """Check if local codex CLI is available."""
    available = check_codex_available()
    return {"available": available, "binary": "codex"}


@router.get("/codex/workspaces")
@router.get("/codex/sessions")
async def list_codex_workspaces(project_id: str | None = None):
    """List all console-managed Codex workspaces, optionally filtered by project."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    return await codex_store.list_codex_workspaces(project_id=project_id)


list_codex_sessions = list_codex_workspaces


@router.post("/codex/workspaces", status_code=201)
@router.post("/codex/sessions", status_code=201)
async def create_codex_workspace(request: CreateCodexSessionRequest):
    """Create a new Codex workspace. No process is launched — sending input triggers per-turn execution."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    project = await codex_store.load_project(request.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project '{request.project_id}' not found")
    from datetime import datetime
    from app.domain.models import CodexWorkspace
    workspace_id = str(uuid4())
    resolved_cwd = request.cwd or project.repo_path
    workspace = CodexWorkspace(
        id=workspace_id,
        title=request.title,
        cwd=resolved_cwd,
        project_id=project.id,
        status="idle",
        created_at=datetime.now(),
        last_active_at=datetime.now(),
        log_path=None,
        messages=[],
    )
    logger.info(f"Creating workspace: {workspace_id} for project {request.project_id}")
    await codex_store.save_codex_workspace(workspace)
    # Broadcast new workspace
    await event_bus.append({
        "type": "session_created",
        "session_id": workspace.id,
        "session": {"id": workspace.id, "title": workspace.title, "project_id": workspace.project_id, "status": workspace.status}
    })
    logger.info(f"Workspace created and broadcasted: {workspace_id}")
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
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' not found")
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
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' not found")

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
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' not found")
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
    executor: str | None = None
    provider: str | None = None
    model: str | None = None


class RunTaskRequest(BaseModel):
    """Optional run-time overrides for task execution."""
    executor: str | None = None
    provider: str | None = None
    model: str | None = None


@router.patch("/codex/tasks/{task_id}")
async def update_codex_task(task_id: str, request: UpdateCodexTaskRequest):
    """Update a task's mutable fields. Supports executor, provider, and model."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    task = await codex_store.load_codex_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")

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
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
    return await codex_store.list_codex_task_messages(task_id)


@router.post("/codex/tasks/{task_id}/request-help")
async def request_codex_task_help(task_id: str, request: RequestTaskHelpRequest):
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")

    task = await codex_store.load_codex_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
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
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
    except Exception as e:
        logger.error("Failed to request help for task %s: %s", task_id, e)
        raise HTTPException(status_code=500, detail=f"Failed to request help: {e}")

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

    Each input creates a new task with its own git worktree (branch chat/<task_id>-<slug>
    forked from the project's default branch). The worktree is removed when the task
    is deleted. Per-turn tracking: each message becomes an isolated task with its own
    logs and result.
    """
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    workspace = await codex_store.load_codex_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' not found")

    from datetime import datetime
    from app.domain.models import CodexTask

    resolved_executor, resolved_provider, resolved_model, _, _ = await _resolve_runtime_config()

    resume_session_id = workspace.thread_id or None

    # Derive title from first line of input
    title_preview = request.input.split("\n")[0][:60]
    task_title = title_preview if title_preview else "Chat message"

    task_id = str(uuid4())
    if not workspace.project_id:
        raise HTTPException(status_code=409, detail="Workspace has no associated project")
    project = await codex_store.load_project(workspace.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project '{workspace.project_id}' not found")
    task = CodexTask(
        id=task_id,
        session_id=workspace_id,
        project_id=project.id,
        title=task_title,
        prompt=request.input,
        executor=resolved_executor,
        provider=resolved_provider,
        model=resolved_model,
        status="pending",
        result=None,
        parent_task_id=None,
        resume_session_id=resume_session_id,
        resume_message_id=None,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    try:
        branch, worktree_path, base = await worktree_manager.prepare_chat_task_worktree(project, task)
    except (GitError, WorktreeError) as exc:
        raise HTTPException(status_code=500, detail=f"failed to create chat worktree: {exc}")
    task.git_branch = branch
    task.git_worktree_path = worktree_path
    task.git_base_branch = base
    task.workspace_path = worktree_path  # Engineer artifacts / executor cwd resolve to this.
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
        logger.warning("Conflict starting task for workspace %s: %s", workspace_id, e)
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.error("Failed to start task for workspace %s: %s", workspace_id, e)
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
        await _cleanup_session_worktrees(workspace["id"], workspace.get("project_id"))
        await codex_store.delete_codex_workspace(workspace["id"])
    return {"deleted": len(workspaces)}


delete_all_codex_sessions = delete_all_codex_workspaces


@router.patch("/codex/workspaces/{workspace_id}")
@router.patch("/codex/sessions/{workspace_id}")
async def update_codex_workspace(workspace_id: str, request: UpdateCodexWorkspaceRequest):
    """Update workspace title and/or cwd. Only provided fields are changed."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    workspace = await codex_store.load_codex_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' not found")
    if request.title is not None:
        title = request.title.strip()
        if not title:
            raise HTTPException(status_code=400, detail="title cannot be empty")
        workspace.title = title
    if request.cwd is not None:
        workspace.cwd = request.cwd
    if request.plan_first_pm is not None:
        settings = dict(getattr(workspace, "settings", {}) or {})
        settings["plan_first_pm"] = bool(request.plan_first_pm)
        workspace.settings = settings
    from datetime import datetime
    workspace.last_active_at = datetime.now()
    await codex_store.save_codex_workspace(workspace)
    await event_bus.append({
        "type": "session_updated",
        "session_id": workspace.id,
        "session": {
            "id": workspace.id,
            "title": workspace.title,
            "project_id": workspace.project_id,
            "status": workspace.status,
        },
    })
    return workspace


update_codex_session = update_codex_workspace


@router.delete("/codex/workspaces/{workspace_id}")
@router.delete("/codex/sessions/{workspace_id}")
async def delete_codex_workspace(workspace_id: str):
    """Delete a codex workspace, all its tasks, workspaces, and logs."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    workspace = await codex_store.load_codex_workspace(workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' not found")
    # Terminate if running first
    mgr = get_codex_process_manager()
    try:
        mgr.terminate(workspace_id)
    except KeyError:
        pass  # Workspace not running, ok to proceed
    await _cleanup_session_worktrees(workspace_id, workspace.project_id)
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
    base_branch: str | None = None  # Override fork point (defaults to project.default_branch)


class UpdateIssuePhaseRequest(BaseModel):
    current_phase: str


class UpdateIssuePinRequest(BaseModel):
    is_pinned: bool


class ApprovePlanRequest(BaseModel):
    review_comment: str | None = None


@router.post("/codex/issues", status_code=201)
async def create_codex_issue(request: CreateIssueRequest):
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    workspace = await codex_store.load_codex_workspace(request.session_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail=f"Workspace '{request.session_id}' not found")
    if not workspace.project_id:
        raise HTTPException(status_code=409, detail="Workspace has no associated project")
    project = await codex_store.load_project(workspace.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project '{workspace.project_id}' not found")

    from app.domain.models import CodexIssue

    now = datetime.now()
    issue = CodexIssue(
        id=str(uuid4()),
        session_id=request.session_id,
        project_id=project.id,
        title=request.title,
        description=request.description,
        current_phase="requirements",
        status="open",
        created_at=now,
        updated_at=now,
    )
    try:
        branch, worktree_path, base = await worktree_manager.prepare_issue_worktree(
            project, issue, base_branch=request.base_branch
        )
    except (GitError, WorktreeError) as exc:
        raise HTTPException(status_code=500, detail=f"failed to create issue worktree: {exc}")
    issue.git_branch = branch
    issue.git_worktree_path = worktree_path
    issue.git_base_branch = base
    await codex_store.save_codex_issue(issue)
    await codex_store.append_project_audit(
        project_id=project.id,
        issue_id=issue.id,
        event="created",
        base_branch=base,
    )
    await event_bus.append({
        "type": "issue_created",
        "issue_id": issue.id,
        "session_id": issue.session_id,
        "issue": issue.model_dump(mode="json") if hasattr(issue, "model_dump") else None,
    })
    return issue


@router.get("/codex/issues")
async def list_codex_issues(session_id: str | None = None, project_id: str | None = None):
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    return await codex_store.list_codex_issues(session_id=session_id, project_id=project_id)


@router.get("/codex/issues/{issue_id}")
async def get_codex_issue(issue_id: str):
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    issue = await codex_store.load_codex_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail=f"Issue '{issue_id}' not found")
    return issue


@router.post("/codex/issues/{issue_id}/phase")
async def update_codex_issue_phase(issue_id: str, request: UpdateIssuePhaseRequest):
    """Set the issue's current_phase tag. PR5: no longer validates against a
    fixed enum — phase is a free-form display field synced by the scheduler.
    """
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    issue = await codex_store.load_codex_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail=f"Issue '{issue_id}' not found")
    issue.current_phase = request.current_phase
    issue.updated_at = datetime.now()
    await codex_store.save_codex_issue(issue)
    await event_bus.append({
        "type": "issue_updated",
        "issue_id": issue.id,
        "session_id": issue.session_id,
        "current_phase": issue.current_phase,
    })
    return issue


@router.post("/codex/issues/{issue_id}/pin")
async def update_codex_issue_pin(issue_id: str, request: UpdateIssuePinRequest):
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    issue = await codex_store.load_codex_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail=f"Issue '{issue_id}' not found")
    issue.is_pinned = request.is_pinned
    issue.updated_at = datetime.now()
    await codex_store.save_codex_issue(issue)
    await event_bus.append({
        "type": "issue_updated",
        "issue_id": issue.id,
        "session_id": issue.session_id,
        "is_pinned": issue.is_pinned,
    })
    return issue


@router.post("/codex/issues/{issue_id}/approve-plan")
async def approve_codex_issue_plan(issue_id: str, request: ApprovePlanRequest):
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    issue = await codex_store.load_codex_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail=f"Issue '{issue_id}' not found")
    if issue.status != "awaiting_approval":
        raise HTTPException(status_code=409, detail="Issue is not awaiting plan approval")

    review_comment = (request.review_comment or "").strip()
    if review_comment:
        issue.review_comment = review_comment
    elif not (issue.review_comment or "").strip():
        raise HTTPException(status_code=400, detail="review_comment cannot be empty")

    issue.status = "in_progress"
    issue.updated_at = datetime.now()
    await codex_store.save_codex_issue(issue)
    await event_bus.append({
        "type": "issue_updated",
        "issue_id": issue.id,
        "session_id": issue.session_id,
        "status": issue.status,
        "review_comment": issue.review_comment,
    })

    # In Conductor-driven mode, the Conductor loop is running as a background task.
    # Approving the plan just updates the issue status above — the Conductor observes
    # the status change via the event bus and continues orchestration automatically.
    return issue


class QaReviewRequest(BaseModel):
    decision: Literal["approve", "reject"]
    comment: str | None = None


@router.post("/codex/issues/{issue_id}/qa-review")
async def qa_review_codex_issue(issue_id: str, request: QaReviewRequest):
    """Human verdict on a QA-passed issue.

    approve → status flips to `awaiting_merge`; user finishes via Merge Back.
    reject  → reset the engineer + qa workflow nodes so the scheduler reruns
              engineer with the user's feedback, exactly like the auto QA-fail
              rework path. Bounded by engineer.max_retries.
    """
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    issue = await codex_store.load_codex_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail=f"Issue '{issue_id}' not found")
    if issue.status != "awaiting_review":
        raise HTTPException(status_code=409, detail="Issue is not awaiting human QA review")

    comment = (request.comment or "").strip()

    if request.decision == "approve":
        issue.status = "awaiting_merge"
        issue.updated_at = datetime.now()
        await codex_store.save_codex_issue(issue)
        await event_bus.append({
            "type": "issue_updated",
            "issue_id": issue.id,
            "session_id": issue.session_id,
            "status": issue.status,
        })
        return issue

    # decision == "reject": route through engineer rework.
    graph = await codex_store.load_workflow_graph_for_issue(issue_id)
    if graph is None:
        raise HTTPException(status_code=409, detail="No workflow graph found for issue")
    engineer_node = next((n for n in graph.nodes if n.node_key == "engineer"), None)
    qa_node = next((n for n in graph.nodes if n.node_key == "qa"), None)
    if engineer_node is None or qa_node is None:
        raise HTTPException(status_code=409, detail="Graph missing engineer or qa node")
    if engineer_node.retries >= max(engineer_node.max_retries, 1):
        raise HTTPException(
            status_code=409,
            detail=f"Engineer rework budget exhausted ({engineer_node.retries}/{engineer_node.max_retries})",
        )

    # Stash the human's feedback into review_comment so engineer's REWORK
    # branch picks it up the same way QA-failure narratives do.
    if comment:
        issue.review_comment = f"[HUMAN-REJECTED] {comment}"
    issue.status = "in_progress"
    issue.updated_at = datetime.now()
    await codex_store.save_codex_issue(issue)

    await codex_store.update_workflow_node(
        engineer_node.id,
        status="pending",
        retries=engineer_node.retries + 1,
        completed_at=None,
    )
    await codex_store.update_workflow_node(
        qa_node.id,
        status="pending",
        completed_at=None,
    )

    await event_bus.append({
        "type": "issue_updated",
        "issue_id": issue.id,
        "session_id": issue.session_id,
        "status": issue.status,
        "review_comment": issue.review_comment,
    })

    # Conductor-driven re-dispatch: a fresh engineer task is created with the
    # human feedback in review_comment so REWORK branch picks it up. We use
    # dispatch_role (the same path Conductor's dispatch_subagent tool uses).
    try:
        from app.application.task_dispatcher import dispatch_role
        from app.application.event_bus import _workflow_task_dispatcher
        await dispatch_role(
            issue=issue,
            role="engineer",
            store=codex_store,
            task_dispatcher_fn=_workflow_task_dispatcher,
            event_bus=event_bus,
            prev_node_key="qa",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("qa-review reject re-dispatch failed: %s", exc)

    return issue


@router.post("/codex/issues/{issue_id}/duplicate", response_model=CodexIssue, status_code=201)
async def duplicate_codex_issue(issue_id: str, from_current: bool = False):
    """Create a sibling issue.

    Default behaviour ("duplicate"): branches off the project's default
    branch — useful for retrying the same goal from scratch.

    `from_current=true` (Fork): branches off the source issue's current
    branch instead, so the new issue inherits all of the original's
    in-progress changes. This is the Devin-style "fork what I have and
    try a different direction" — pair with a steer note to push the
    fork in a new direction.
    """
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    issue = await codex_store.load_codex_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail=f"Issue '{issue_id}' not found")
    import uuid
    suffix = " (fork)" if from_current else " (copy)"
    new_issue = CodexIssue(
        id=str(uuid.uuid4()),
        session_id=issue.session_id,
        project_id=issue.project_id,
        title=f"{issue.title}{suffix}",
        description=issue.description,
        current_phase="requirements",
        status="open",
        is_pinned=False,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    if new_issue.project_id:
        project = await codex_store.load_project(new_issue.project_id)
        if project is not None:
            try:
                # When forking from current state, override the base branch
                # so the new worktree inherits the source issue's commits.
                if from_current and issue.git_branch:
                    new_issue.git_base_branch = issue.git_branch
                branch, worktree_path, base = await worktree_manager.prepare_issue_worktree(project, new_issue)
                new_issue.git_branch = branch
                new_issue.git_worktree_path = worktree_path
                new_issue.git_base_branch = base
            except (GitError, WorktreeError) as exc:
                raise HTTPException(status_code=500, detail=f"failed to create issue worktree: {exc}")
    await codex_store.save_codex_issue(new_issue)
    await event_bus.append({
        "type": "issue_created",
        "issue_id": new_issue.id,
        "session_id": new_issue.session_id,
        "issue": new_issue.model_dump(mode="json") if hasattr(new_issue, "model_dump") else None,
        "forked_from": issue.id,
    })
    return new_issue


@router.get("/codex/issues/{issue_id}/artifacts")
async def get_codex_issue_artifacts(issue_id: str):
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    issue = await codex_store.load_codex_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail=f"Issue '{issue_id}' not found")

    workspace = await codex_store.load_codex_workspace(issue.session_id)
    if workspace is None:
        return []

    # Always scan disk + backfill DB. The previous "only scan if DB is empty"
    # short-circuit caused a real bug: once PM's artifacts seeded the DB,
    # subsequent Architect/Engineer/QA artifacts that landed on disk later
    # never got picked up. The scan is bounded (≤4 dirs * small file counts)
    # and only writes new rows.
    disk_rows = await _scan_and_backfill_artifacts(issue_id, issue.session_id, codex_store)
    db_rows = await codex_store.list_artifacts(issue_id)
    # Union, preferring the freshest disk scan when there's a name collision.
    by_name: dict[str, dict] = {row["name"]: row for row in db_rows}
    for row in disk_rows:
        by_name[row["name"]] = row
    # Filter framework control files even when they were previously persisted
    # to the artifacts table (legacy rows). Matches the scanner's blocklist.
    def _is_user_artifact(name: str) -> bool:
        base = name.rsplit("/", 1)[-1]
        return not (base.startswith("_") or base.startswith("."))
    rows = [r for r in by_name.values() if _is_user_artifact(r["name"])]

    MAX_FILE_SIZE = 1024 * 1024
    result = []
    for row in rows:
        path = Path(row["path"])
        content = None
        if path.exists() and path.suffix in (".md", ".json", ".txt", ".html", ".js", ".css"):
            try:
                content = path.read_text(encoding="utf-8", errors="replace")[:MAX_FILE_SIZE]
            except OSError:
                content = None
        result.append({
            "id": row["id"],
            "issue_id": row["issue_id"],
            "task_id": row["task_id"],
            "kind": row["kind"],
            "name": row["name"],
            "path": row["path"],
            "content": content,
            "created_at": row["created_at"],
        })
    return result


@router.get("/codex/issues/{issue_id}/artifacts/download")
async def download_issue_artifacts_zip(issue_id: str):
    """Stream a zip of every artifact file under the issue's artifact roots.

    The frontend "下载 zip" button points here. We assemble the archive in
    memory (artifacts are bounded — single-digit MB total) and let FastAPI
    stream it back so the browser saves a single file.
    """
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    from fastapi.responses import Response
    import io
    import zipfile
    from pathlib import Path

    issue = await codex_store.load_codex_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")

    # Reuse the same scan+backfill path the JSON endpoint uses so we always
    # include the freshest on-disk artifacts.
    await _scan_and_backfill_artifacts(issue_id, issue.session_id, codex_store)
    rows = await codex_store.list_artifacts(issue_id)
    if not rows:
        raise HTTPException(status_code=404, detail="No artifacts to download")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for row in rows:
            path = Path(row["path"]) if row.get("path") else None
            if path is None or not path.exists() or not path.is_file():
                continue
            arcname = row.get("name") or path.name
            try:
                zf.write(path, arcname)
            except (OSError, PermissionError):
                continue
    buf.seek(0)
    filename = f"issue-{issue_id[:8]}-artifacts.zip"
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def _scan_and_backfill_artifacts(issue_id: str, session_id: str, store) -> list[dict]:
    """Scan disk for artifacts and backfill the database."""
    workspace = await store.load_codex_workspace(session_id)
    if workspace is None:
        return []

    tasks = await store.list_codex_tasks(session_id=session_id, issue_id=issue_id)
    # Sort newest first so that when scanning multiple roots, newer artifacts take precedence
    sorted_tasks = sorted(
        tasks,
        key=lambda item: item.get("updated_at") or item.get("created_at") or "",
        reverse=True,
    )

    # Build ordered, deduplicated list of issue roots to scan.
    seen_wp: set[str] = set()
    issue_roots: list[Path] = []
    for task_row in sorted_tasks:
        wp = task_row.get("workspace_path")
        if wp and wp not in seen_wp:
            seen_wp.add(wp)
            issue_roots.append(Path(wp) / "issues" / issue_id)
    fallback_root = Path(workspace.cwd) / "issues" / issue_id
    if str(fallback_root) not in {str(r) for r in issue_roots}:
        issue_roots.append(fallback_root)

    # Backfill missing artifacts for *all* managed roles. For each done
    # task, if its expected artifact dir is empty, ask the role workflow
    # service to persist again (it parses task.result and writes to disk).
    # Without this, Architect/Engineer/QA artifacts only appear when their
    # task is individually fetched by the UI — the Artifacts tab gets blank.
    role_to_subdir = {
        "product_manager": "pm",
        "architect": "architect",
        "engineer": "engineer",
        "qa": "qa",
    }
    # Canonical output file each role MUST produce. The backfill check below
    # uses these instead of "any file in the subdir" — the prior heuristic
    # was tricked by PM's auto-created `pm/requirement.md` stub into
    # believing the PRD was already on disk, so prd.json was never written.
    role_canonical_file = {
        "product_manager": ["pm/prd.json", "pm/bugfix.md"],
        "architect": ["architect/system_design.json"],
        "engineer": [None],  # engineer file name embeds task id → checked below
        "qa": ["qa/qa_plan.json"],
    }
    for task_row in sorted_tasks:
        role = task_row.get("role")
        subdir = role_to_subdir.get(role)
        if not subdir:
            continue
        if str(task_row.get("status") or "").lower() != "done":
            continue
        workspace_path = task_row.get("workspace_path")
        if not workspace_path:
            continue
        artifact_dir = Path(workspace_path) / "issues" / issue_id / subdir
        # Did the role actually produce its canonical artifact?
        if role == "engineer":
            persisted = artifact_dir.exists() and any(artifact_dir.glob("implementation-*.md"))
        else:
            wanted = role_canonical_file.get(role, [])
            persisted = any(
                (Path(workspace_path) / "issues" / issue_id / name).exists()
                for name in wanted
                if name
            )
        if not persisted:
            task = await store.load_codex_task(task_row.get("id"))
            if task is not None and getattr(task, "result", None):
                ws = await store.load_codex_workspace(task.session_id)
                try:
                    await role_workflow_service.persist_result(task, workspace_title=ws.title if ws else None)
                except Exception as exc:  # noqa: BLE001
                    import logging
                    logging.getLogger(__name__).warning(
                        "Artifacts backfill: persist_result failed for %s task %s: %s",
                        role, task.id, exc,
                    )

    artifact_map: dict[str, dict] = {}

    folder_to_category = {
        "pm": "product",
        "architect": "architecture",
        "engineer": "development",
        "qa": "testing",
    }

    from datetime import datetime as dt

    def scan_root(root: Path):
        def _walk(target_dir: Path):
            if not target_dir.exists() or not target_dir.is_dir():
                return
            for item in sorted(target_dir.iterdir()):
                # Skip framework control files (steer, future ones). These
                # live alongside artifacts but aren't user-facing outputs.
                if item.name.startswith("_") or item.name.startswith("."):
                    continue
                if item.is_dir():
                    _walk(item)
                elif item.is_file() and item.name != ".DS_Store":
                    rel_path = item.relative_to(root)
                    display_name = str(rel_path)
                    # Newer root already provided this file — don't overwrite
                    if display_name in artifact_map:
                        continue
                    category_folder = rel_path.parts[0] if len(rel_path.parts) > 1 else "general"
                    artifact_map[display_name] = {
                        "id": f"{issue_id}:{display_name}",
                        "issue_id": issue_id,
                        "task_id": None,
                        "kind": folder_to_category.get(category_folder, "general"),
                        "name": display_name,
                        "path": str(item),
                        "created_at": dt.fromtimestamp(item.stat().st_mtime).isoformat(),
                    }
        _walk(root)

    for root in issue_roots:
        scan_root(root)

    # Backfill DB with scanned artifacts
    from app.application import knowledge_index_service as _kidx
    for artifact_name, artifact_data in artifact_map.items():
        row = {
            "id": artifact_data["id"],
            "issue_id": issue_id,
            "task_id": artifact_data["task_id"],
            "name": artifact_data["name"],
            "path": artifact_data["path"],
            "kind": artifact_data["kind"],
            "created_at": artifact_data["created_at"],
        }
        await store.save_artifact(row)
        try:
            await _kidx.index_artifact(store, row)
        except Exception:  # noqa: BLE001
            pass

    return list(artifact_map.values())


@router.delete("/codex/issues/{issue_id}")
async def delete_codex_issue(issue_id: str):
    """Delete an issue and all issue-owned records."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    issue = await codex_store.load_codex_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail=f"Issue '{issue_id}' not found")

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
        await _delete_task_cascade(task["id"], delete_workspace=False)

    if issue.project_id:
        project = await codex_store.load_project(issue.project_id)
        if project is not None:
            try:
                await worktree_manager.cleanup_issue_worktree(project, issue)
            except Exception:
                pass

    await codex_store.delete_codex_issue(issue_id)
    if issue.project_id:
        await codex_store.append_project_audit(
            project_id=issue.project_id,
            issue_id=issue.id,
            event="deleted",
        )
    await event_bus.append({
        "type": "issue_deleted",
        "issue_id": issue_id,
        "session_id": issue.session_id,
    })
    return {"deleted": issue_id}


@router.get("/codex/issues/{issue_id}/diff")
async def get_codex_issue_diff(issue_id: str, stat_only: bool = False):
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    issue = await codex_store.load_codex_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    if not issue.project_id or not issue.git_worktree_path:
        return {"diff": "", "base_branch": None, "branch": None, "stat": None}
    project = await codex_store.load_project(issue.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    base = issue.git_base_branch or project.default_branch
    try:
        stat = await git_service.diff_shortstat(issue.git_worktree_path, base)
        ahead = await git_service.commits_ahead(issue.git_worktree_path, base)
        diff = "" if stat_only else await worktree_manager.issue_diff(project, issue)
    except GitError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {
        "diff": diff,
        "base_branch": issue.git_base_branch,
        "branch": issue.git_branch,
        "stat": stat,
        "commits_ahead": ahead,
    }


class MergeIssueRequest(BaseModel):
    message: str | None = None
    allow_diverged_base: bool = False


@router.post("/codex/issues/{issue_id}/abandon")
async def abandon_codex_issue(issue_id: str):
    """Soft-abandon an issue: flip status to abandoned but keep the worktree
    on disk. The frontend shows a 60s undo countdown; if the user clicks
    Undo we just restore the status. To actually drop the worktree the
    frontend POSTs to /abandon/finalize once the countdown expires.

    This decouples the destructive cleanup from the user-facing "abandon"
    action so accidents are recoverable.
    """
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    issue = await codex_store.load_codex_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    if issue.git_merge_status == "merged":
        raise HTTPException(status_code=409, detail="cannot abandon a merged issue")
    issue.git_merge_status = "abandoned"
    issue.updated_at = datetime.now()
    await codex_store.save_codex_issue(issue)
    await codex_store.append_project_audit(
        project_id=issue.project_id,
        issue_id=issue.id,
        event="abandoned",
        base_branch=issue.git_base_branch,
    )
    await event_bus.append({
        "type": "issue_abandoned",
        "issue_id": issue.id,
        "session_id": issue.session_id,
    })
    return issue


class CreatePRRequest(BaseModel):
    title: str | None = None
    body: str | None = None
    draft: bool = False


@router.post("/codex/issues/{issue_id}/pr/create")
async def create_github_pr(issue_id: str, request: CreatePRRequest):
    """Push the issue's worktree branch to origin and open a GitHub PR via
    `gh pr create`. This is the Devin-killer differentiator — Devin can
    plan & code but can't open a PR against your private remote because
    it's a cloud service. We do it from your local gh CLI.

    Requires:
      * `gh` in PATH and authenticated (`gh auth status`)
      * The project repo has an `origin` remote pointing at GitHub
      * The issue has an active worktree
    """
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    issue = await codex_store.load_codex_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    if not issue.git_worktree_path:
        raise HTTPException(status_code=409, detail="Issue has no active worktree")
    if not issue.git_branch:
        raise HTTPException(status_code=409, detail="Issue has no git branch")
    if issue.github_pr_url:
        raise HTTPException(
            status_code=409,
            detail=f"Issue already has a PR: {issue.github_pr_url}",
        )

    import shutil
    if not shutil.which("gh"):
        raise HTTPException(
            status_code=412,
            detail="gh CLI is not installed. Install from https://cli.github.com/ first.",
        )

    title = (request.title or issue.title or "").strip()
    body = (request.body or _build_default_pr_body(issue) or "").strip()

    base_branch = issue.git_base_branch or "main"
    head_branch = issue.git_branch

    # 1. Push the branch. -u sets upstream so future fetches work.
    push = await _run_subprocess(
        ["git", "push", "-u", "origin", head_branch],
        cwd=issue.git_worktree_path,
        timeout_s=60,
    )
    if push.returncode != 0:
        raise HTTPException(
            status_code=502,
            detail=f"git push failed: {push.stderr.strip()[:500]}",
        )

    # 2. Open the PR.
    args = ["gh", "pr", "create", "--base", base_branch, "--head", head_branch,
            "--title", title, "--body", body]
    if request.draft:
        args.append("--draft")
    create = await _run_subprocess(args, cwd=issue.git_worktree_path, timeout_s=60)
    if create.returncode != 0:
        raise HTTPException(
            status_code=502,
            detail=f"gh pr create failed: {create.stderr.strip()[:500]}",
        )

    pr_url = create.stdout.strip().splitlines()[-1] if create.stdout.strip() else ""
    issue.github_pr_url = pr_url
    issue.github_pr_state = "OPEN:REVIEW_REQUIRED"
    issue.updated_at = datetime.now()
    await codex_store.save_codex_issue(issue)
    await codex_store.append_project_audit(
        project_id=issue.project_id,
        issue_id=issue.id,
        event="github_pr_created",
        base_branch=base_branch,
    )
    await event_bus.append({
        "type": "issue_pr_created",
        "issue_id": issue.id,
        "pr_url": pr_url,
    })
    return issue


@router.post("/codex/issues/{issue_id}/pr/refresh")
async def refresh_github_pr(issue_id: str):
    """Poll `gh pr view` for the issue's PR and update local state. If the
    PR has merged, also flip `git_merge_status` to "merged". If reviewers
    requested changes, the latest review body is stuffed into the most
    recent task's `review_comment` so the existing rework loop fires."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    issue = await codex_store.load_codex_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    if not issue.github_pr_url:
        raise HTTPException(status_code=409, detail="Issue has no PR yet")
    import shutil
    if not shutil.which("gh"):
        raise HTTPException(status_code=412, detail="gh CLI is not installed")

    cwd = issue.git_worktree_path or "."
    view = await _run_subprocess(
        ["gh", "pr", "view", issue.github_pr_url, "--json",
         "state,reviewDecision,reviews,mergeStateStatus"],
        cwd=cwd,
        timeout_s=30,
    )
    if view.returncode != 0:
        raise HTTPException(
            status_code=502,
            detail=f"gh pr view failed: {view.stderr.strip()[:500]}",
        )
    try:
        data = json.loads(view.stdout)
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="gh pr view returned non-JSON")

    state = data.get("state") or "OPEN"
    decision = data.get("reviewDecision") or ""
    issue.github_pr_state = f"{state}:{decision}"

    # Flip merge state if PR was merged remotely.
    if state == "MERGED" and issue.git_merge_status != "merged":
        issue.git_merge_status = "merged"

    issue.updated_at = datetime.now()
    await codex_store.save_codex_issue(issue)

    # If reviewers requested changes, surface the most recent review body
    # back into the engineer's review_comment so the agent re-runs.
    if decision == "CHANGES_REQUESTED":
        reviews = data.get("reviews") or []
        latest_review_body = ""
        if reviews:
            latest_review_body = (reviews[-1] or {}).get("body") or ""
        if latest_review_body:
            tasks = await codex_store.list_codex_tasks(issue_id=issue.id)
            engineer_tasks = [t for t in tasks if t.get("role") == "engineer"]
            if engineer_tasks:
                eng = await codex_store.load_codex_task(engineer_tasks[-1]["id"])
                if eng:
                    eng.status = "pending"
                    eng.review_comment = (
                        "GitHub PR review requested changes. Address the feedback below "
                        "before re-submitting.\n\n" + latest_review_body
                    )
                    eng.updated_at = datetime.now()
                    await codex_store.save_codex_task(eng)
                    await event_bus.append({
                        "type": "task_status",
                        "task_id": eng.id,
                        "session_id": eng.session_id,
                        "status": "pending",
                    })

    return issue


def _build_default_pr_body(issue) -> str:
    parts = [
        f"_Automated PR opened by agent-collab-console for issue `{issue.id}`._",
        "",
        "## Description",
        issue.description or "(no description)",
        "",
        "## Branch",
        f"- base: `{issue.git_base_branch or 'main'}`",
        f"- head: `{issue.git_branch}`",
    ]
    return "\n".join(parts)


async def _run_subprocess(args, *, cwd: str, timeout_s: int = 30):
    """Async wrapper around subprocess that captures stdout/stderr with a
    timeout. Returns a CompletedProcess-like object with .returncode,
    .stdout, .stderr. Used for git/gh shell-outs from the API layer."""
    import asyncio as _asyncio
    import subprocess as _subprocess

    def _run():
        return _subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )

    return await _asyncio.get_running_loop().run_in_executor(None, _run)


class SteerRequest(BaseModel):
    message: str


class IssueConductorMessageRequest(BaseModel):
    message: str


@router.post("/codex/issues/{issue_id}/steer")
async def steer_codex_issue(issue_id: str, request: SteerRequest):
    """Inject a mid-run hint into the issue's worktree. The next time any
    role agent runs for this issue, its prompt picks up `_steer.md` and
    threads the user's note into the run.

    Devin-style "💬 wait, use SHA-256 not MD5" message: you don't have to
    wait for the current turn to finish; the hint lands on disk now and
    sticks until cleared.
    """
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    issue = await codex_store.load_codex_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    msg = (request.message or "").strip()
    if not msg:
        raise HTTPException(status_code=400, detail="message cannot be empty")
    if not issue.git_worktree_path:
        raise HTTPException(status_code=409, detail="Issue has no active worktree")
    from pathlib import Path
    steer_path = Path(issue.git_worktree_path) / "issues" / issue.id / "_steer.md"
    steer_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    block = f"\n## {timestamp}\n{msg}\n"
    existing = ""
    if steer_path.exists():
        try:
            existing = steer_path.read_text(encoding="utf-8")
        except OSError:
            existing = ""
    header = (
        "# Steer notes — read these BEFORE acting\n"
        "These are mid-run hints from the user. Apply them on top of the PRD / design / "
        "implementation_plan whenever they're relevant. Most recent first.\n"
    )
    if header.split("\n", 1)[0] not in existing:
        existing = header + existing
    steer_path.write_text(existing.rstrip() + block, encoding="utf-8")
    await event_bus.append({
        "type": "issue_steered",
        "issue_id": issue.id,
        "session_id": issue.session_id,
        "message": msg,
    })
    return {"ok": True, "steer_path": str(steer_path)}


@router.post("/codex/issues/{issue_id}/restore")
async def restore_codex_issue(issue_id: str):
    """Undo an abandon. Only valid while the worktree is still on disk —
    a finalized abandon (worktree gone) cannot be restored, so the
    frontend's 60s countdown is the user-facing safety window."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    issue = await codex_store.load_codex_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    if issue.git_merge_status != "abandoned":
        raise HTTPException(status_code=409, detail="Issue is not in abandoned state")
    if not issue.git_worktree_path:
        raise HTTPException(
            status_code=410,
            detail="Worktree has been finalized; this abandon cannot be undone",
        )
    issue.git_merge_status = "open"
    issue.updated_at = datetime.now()
    await codex_store.save_codex_issue(issue)
    await codex_store.append_project_audit(
        project_id=issue.project_id,
        issue_id=issue.id,
        event="restored",
        base_branch=issue.git_base_branch,
    )
    await event_bus.append({
        "type": "issue_restored",
        "issue_id": issue.id,
        "session_id": issue.session_id,
    })
    return issue


@router.post("/codex/issues/{issue_id}/abandon/finalize")
async def finalize_abandoned_issue(issue_id: str):
    """Actually delete the worktree of an issue that's already in the
    abandoned soft state. Idempotent — safe to call twice.

    Called by the frontend once the 60s undo countdown expires."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    issue = await codex_store.load_codex_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    if issue.git_merge_status != "abandoned":
        raise HTTPException(status_code=409, detail="Issue must be abandoned before finalize")
    if not issue.git_worktree_path:
        return issue  # already finalized
    if issue.project_id:
        project = await codex_store.load_project(issue.project_id)
        if project is not None:
            try:
                await worktree_manager.cleanup_issue_worktree(project, issue)
            except Exception:
                pass
    issue.git_worktree_path = None
    issue.updated_at = datetime.now()
    await codex_store.save_codex_issue(issue)
    await event_bus.append({
        "type": "issue_updated",
        "issue_id": issue.id,
        "session_id": issue.session_id,
        "git_worktree_path": None,
    })
    return issue


@router.post("/codex/issues/{issue_id}/merge")
async def merge_codex_issue(issue_id: str, request: MergeIssueRequest):
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    issue = await codex_store.load_codex_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    if not issue.project_id or not issue.git_branch:
        raise HTTPException(status_code=409, detail="Issue has no git branch to merge")
    if issue.git_merge_status == "merged":
        raise HTTPException(status_code=409, detail="Issue already merged")
    project = await codex_store.load_project(issue.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    # Diverged-base guard: if the base branch has moved past the worktree's
    # last commit and the caller hasn't opted in, refuse so they can rebase
    # first. Squash-merging a behind-base branch is technically fine but the
    # resulting main can have hidden conflicts.
    if issue.git_worktree_path and not request.allow_diverged_base:
        base = issue.git_base_branch or project.default_branch
        try:
            behind = await git_service.commits_behind(issue.git_worktree_path, base)
        except GitError:
            behind = 0
        if behind > 0:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"base branch '{base}' is {behind} commit(s) ahead of this issue; "
                    "rebase the worktree onto base or retry with allow_diverged_base=true"
                ),
            )
    try:
        result = await worktree_manager.merge_issue(project, issue, message=request.message)
    except (GitError, WorktreeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # Close the loop: merging is the last user-visible step, so flip the
    # issue's lifecycle status to completed alongside git_merge_status=merged.
    if issue.status != "completed":
        issue.status = "completed"
    issue.updated_at = datetime.now()
    await codex_store.save_codex_issue(issue)
    await codex_store.append_project_audit(
        project_id=project.id,
        issue_id=issue.id,
        event="merged",
        sha=result["sha"],
        base_branch=result["base_branch"],
    )
    await event_bus.append({
        "type": "issue_merged",
        "issue_id": issue.id,
        "session_id": issue.session_id,
        "sha": result["sha"],
        "base_branch": result["base_branch"],
    })
    await event_bus.append({
        "type": "issue_updated",
        "issue_id": issue.id,
        "session_id": issue.session_id,
        "status": issue.status,
    })
    return {**result, "issue": issue}


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
    # PR5: phase is now free-form. Default to role_key when caller omits it
    # (the new DAG flow ignores this field anyway).
    resolved_phase = request.phase or (request.role or (issue.current_phase if request.issue_id is not None else "general"))

    # Resolve and validate executor/provider/model against runtime catalog
    resolved_executor, resolved_provider, resolved_model, _, _ = await _resolve_runtime_config(
        request.executor,
        request.provider,
        request.model,
    )

    parent_task = None
    if request.parent_task_id:
        parent_task = await codex_store.load_codex_task(request.parent_task_id)
        if parent_task is None and request.task_kind != "help_child":
            raise HTTPException(status_code=404, detail="Parent task not found")

    project = None
    if session.project_id:
        project = await codex_store.load_project(session.project_id)
        if project is None:
            raise HTTPException(status_code=404, detail=f"Project '{session.project_id}' not found")

    from datetime import datetime
    from app.domain.models import CodexTask
    task_id = str(uuid4())

    # Resolve worktree + branch for this task:
    # - issue task → inherit from issue's worktree (shared across roles)
    # - chat task with project → fresh per-task worktree
    # - chat task without project → fall back to session.cwd (legacy)
    git_branch = None
    git_base_branch = None
    git_worktree_path = None
    workspace_path: str | None = None
    if issue is not None and project is not None:
        if not issue.git_worktree_path:
            try:
                branch, wt_path, base = await worktree_manager.prepare_issue_worktree(project, issue)
            except (GitError, WorktreeError) as exc:
                raise HTTPException(status_code=500, detail=f"failed to prepare issue worktree: {exc}")
            issue.git_branch = branch
            issue.git_worktree_path = wt_path
            issue.git_base_branch = base
            await codex_store.save_codex_issue(issue)
        git_branch = issue.git_branch
        git_base_branch = issue.git_base_branch
        git_worktree_path = issue.git_worktree_path
        workspace_path = issue.git_worktree_path
    elif project is not None:
        scratch_task = CodexTask(
            id=task_id,
            session_id=request.session_id,
            project_id=project.id,
            title=request.title,
            prompt=request.prompt,
            role=request.role,
            executor=resolved_executor,
            status="pending",
        )
        try:
            branch, wt_path, base = await worktree_manager.prepare_chat_task_worktree(project, scratch_task)
        except (GitError, WorktreeError) as exc:
            raise HTTPException(status_code=500, detail=f"failed to prepare chat worktree: {exc}")
        git_branch = branch
        git_base_branch = base
        git_worktree_path = wt_path
        workspace_path = wt_path
    else:
        workspace_path = session.cwd

    task = CodexTask(
        id=task_id,
        session_id=request.session_id,
        project_id=project.id if project else None,
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
        git_branch=git_branch,
        git_base_branch=git_base_branch,
        git_worktree_path=git_worktree_path,
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
    try:
        await get_codex_process_manager().terminate_task(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Task not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to terminate task: {e}")
    return {"status": "ok"}


async def _run_task_with_user_content(task_id: str, content: str, kind: str):
    """Shared implementation for chat / refine endpoints (and the legacy /messages alias).

    Creates a user message, starts a run on the task with the given kind, and
    returns {message, assistant_message, task, execution_process}. The assistant
    reply is delivered async via the event stream in real-CLI mode; in mock
    mode (tests) we finalize inline so callers see the assistant_message in the
    response.
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
        content=content,
        created_at=datetime.now(),
    )
    try:
        exec_process = await _get_task_runner().start_task_run(
            task,
            prompt_override=content,
            resume_session_id=task.resume_session_id,
            resume_message_id=task.resume_message_id,
            kind=kind,
            triggering_message_id=message_id,
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
        # Chat must not mutate task.result or persist artifact. Refine / rerun
        # follow normal task.result + persist semantics.
        if kind != "chat":
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
        # The assistant reply is whatever the run produced. For chat it lives only
        # in the message log; for refine/rerun it's also the new task.result.
        assistant_content = current_task.result or "Task updated."
        existing = await _list_task_messages(task_id, execution_process_id=exec_process.id)
        last = existing[-1] if existing else None

        def _msg_attr(m, name):
            return m.get(name) if isinstance(m, dict) else getattr(m, name, None)

        if last and _msg_attr(last, "role") == "assistant" and _msg_attr(last, "content") == assistant_content:
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


class ChatRequest(BaseModel):
    content: str


@router.post("/codex/tasks/{task_id}/chat", status_code=201)
async def chat_codex_task(task_id: str, request: ChatRequest):
    """Send a conversational follow-up to the task's agent.

    Chat runs DO NOT mutate the task's canonical result or persist role
    artifacts (e.g. pm/prd.md). The user's message and the agent's reply are
    only appended to the task message log. CLI session continuity (resume_*)
    is reused so the agent has prior conversation context.
    """
    return await _run_task_with_user_content(task_id, request.content, kind="chat")


@router.post("/codex/tasks/{task_id}/messages", status_code=201)
async def send_codex_task_message(task_id: str, request: SendTaskMessageRequest):
    """Deprecated: alias for /chat. Kept for backward compatibility."""
    return await _run_task_with_user_content(task_id, request.content, kind="chat")


def _has_canonical_artifact_for_task(task) -> bool:
    """Check whether the role's canonical artifact exists on disk."""
    from app.application.issue_artifact_documents import IssueArtifactDocuments
    if not getattr(task, "workspace_path", None):
        return False
    docs = IssueArtifactDocuments()
    issue_id = task.issue_id or task.id
    role = getattr(task, "role", None)
    if role == "product_manager":
        return docs.pm_prd_json_path(task.workspace_path, issue_id).exists()
    if role == "architect":
        return docs.architect_system_design_json_path(task.workspace_path, issue_id).exists()
    if role == "engineer":
        return docs.engineer_implementation_md_path(task.workspace_path, issue_id, task_id=task.id).exists()
    if role == "qa":
        return docs.qa_plan_json_path(task.workspace_path, issue_id).exists()
    return False


class RefineRequest(BaseModel):
    content: str


@router.post("/codex/tasks/{task_id}/refine", status_code=201)
async def refine_codex_task(task_id: str, request: RefineRequest):
    """Refine an existing artifact: agent re-emits the full artifact incorporating
    user-requested changes, then normal persist_result writes it back.

    Requires that an initial run has produced a canonical artifact.
    """
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    task = await codex_store.load_codex_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if not _has_canonical_artifact_for_task(task):
        raise HTTPException(
            status_code=409,
            detail="无法 refine：当前任务尚未生成产物，请先完成 initial 运行",
        )
    return await _run_task_with_user_content(task_id, request.content, kind="refine")


class SendRequest(BaseModel):
    content: str
    force_mode: Literal["chat", "refine"] | None = None


@router.post("/codex/tasks/{task_id}/send", status_code=201)
async def send_codex_task(task_id: str, request: SendRequest):
    """Auto-route a user follow-up: keyword-classify chat vs refine, then run.

    - force_mode given → use it as-is (refine still requires existing artifact → 409)
    - force_mode absent → classify via intent_classifier
    - Auto-classified refine without canonical artifact → degrade to chat
      (do NOT 409: auto mode should not block the user; show resolved_mode in response)
    """
    from app.application.intent_classifier import classify_intent

    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    task = await codex_store.load_codex_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    if request.force_mode is not None:
        resolved_mode = request.force_mode
        if resolved_mode == "refine" and not _has_canonical_artifact_for_task(task):
            raise HTTPException(
                status_code=409,
                detail="无法 refine：当前任务尚未生成产物，请先完成 initial 运行",
            )
    else:
        proposed = classify_intent(request.content)
        if proposed == "refine" and not _has_canonical_artifact_for_task(task):
            # Auto-detected refine but no artifact yet → safer to chat instead of block
            resolved_mode = "chat"
        else:
            resolved_mode = proposed

    result = await _run_task_with_user_content(task_id, request.content, kind=resolved_mode)
    if isinstance(result, dict):
        result["resolved_mode"] = resolved_mode
    return result


class RerunRequest(BaseModel):
    executor: str | None = None
    provider: str | None = None
    model: str | None = None


@router.post("/codex/tasks/{task_id}/rerun", status_code=201)
async def rerun_codex_task(task_id: str, request: RerunRequest | None = None):
    """Re-run the task from scratch using the original role workflow prompt.

    Optional executor/provider/model overrides are passed through to the runner
    (same precedence as /run: run override > task default > catalog default).
    The agent's new output overwrites the canonical artifact via persist_result.
    Sequencing guards (development phase) still apply.
    """
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    from datetime import datetime
    from app.domain.models import CodexTaskMessage

    task = await codex_store.load_codex_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    # Reuse the same sequencing guard as /run: development tasks with index>0
    # must wait for previous task to be done.
    if task.sequence_index is not None and task.phase == "development" and task.sequence_index > 0:
        prev_index = task.sequence_index - 1
        all_tasks = await codex_store.list_codex_tasks(session_id=task.session_id, issue_id=task.issue_id)
        prev_task = next(
            (t for t in all_tasks if t.get("sequence_index") == prev_index and t.get("sequence_group") == task.sequence_group),
            None,
        )
        if prev_task is None or prev_task.get("status") != "done":
            raise HTTPException(status_code=409, detail="需先完成上一个开发任务并通过评审")

    try:
        exec_process = await _get_task_runner().start_task_run(
            task,
            kind="rerun",
            run_executor=request.executor if request else None,
            run_provider=request.provider if request else None,
            run_model=request.model if request else None,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # In mock mode the run finalizes synchronously; refresh task state for the response.
    if isinstance(get_codex_process_manager(), MockCodexProcessManager):
        task = await codex_store.load_codex_task(task_id) or task

    return {
        "message": None,
        "assistant_message": None,
        "task": task,
        "execution_process": exec_process,
    }


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
    try:
        await run_codex_task(review_task_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start review task: {e}")

    return task


class TaskReviewRequest(BaseModel):
    decision: Literal["approve", "reject"]
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


class AnswerClarificationRequest(BaseModel):
    answer: str


@router.post("/codex/tasks/{task_id}/answer")
async def answer_codex_task_clarification(task_id: str, request: AnswerClarificationRequest):
    """Resolve a task that paused waiting for a clarification.

    The task's prior review_comment carries `[CLARIFY] <question>`. We:
      1. Replace it with `REWORK REQUIRED: ...` containing both the original
         question and the user's answer.
      2. Reset task.status to `pending` and re-dispatch via the task runner,
         so the role re-runs with the answer threaded through its
         REWORK-REQUIRED branch (engineer_workflow already supports this).
    """
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    task = await codex_store.load_codex_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    from app.application.clarification import question_text
    question = question_text(task)
    if not question:
        raise HTTPException(status_code=409, detail="Task has no pending clarification")

    answer = (request.answer or "").strip()
    if not answer:
        raise HTTPException(status_code=400, detail="answer cannot be empty")

    task.review_comment = (
        f"You previously asked: {question}\n"
        f"User answer: {answer}\n\n"
        "Use this answer to complete the task. Do NOT ask the same "
        "clarification_question again — only escalate a different question "
        "if a truly new ambiguity comes up."
    )
    task.status = "pending"
    task.updated_at = datetime.now()
    await codex_store.save_codex_task(task)

    await event_bus.append({
        "type": "task_status",
        "task_id": task.id,
        "session_id": task.session_id,
        "status": "pending",
        "review_comment": task.review_comment,
    })

    try:
        await run_codex_task(task_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to re-run task: {exc}")

    refreshed = await codex_store.load_codex_task(task_id)
    return refreshed or task


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
    try:
        success = await mgr.resolve_approval(request.item_id, request.decision)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to resolve approval: {e}")
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
from app.domain.models import RuntimeCatalog


def _get_runtime_catalog_service() -> RuntimeCatalogService:
    """Get or create the runtime catalog service."""
    return RuntimeCatalogService(codex_store)


class RuntimeCatalogRequest(BaseModel):
    catalog: RuntimeCatalog


async def _merge_existing_runtime_secrets(incoming: RuntimeCatalog) -> RuntimeCatalog:
    """Preserve stored API keys omitted by public catalog edit forms."""
    if codex_store is None:
        return incoming
    existing = await _get_runtime_catalog_service().load_catalog()
    existing_by_id = {executor.id: executor for executor in existing.executors}
    for executor in incoming.executors:
        if "api_key" not in executor.model_fields_set:
            existing_executor = existing_by_id.get(executor.id)
            if existing_executor is not None:
                executor.api_key = existing_executor.api_key
    return incoming


def _public_runtime_catalog(catalog: RuntimeCatalog) -> dict:
    """Return runtime catalog data safe for browser clients.

    The stored catalog may contain provider API keys. Read endpoints expose only
    configuration booleans so frontend state cannot retain raw credentials.
    """
    return {
        "executors": [
            {
                "id": executor.id,
                "label": executor.label,
                "enabled": executor.enabled,
                "executor_type": executor.executor_type,
                "api_endpoint": executor.api_endpoint,
                "api_key_configured": bool(executor.api_key),
                "default_model": executor.default_model,
                "providers": [
                    {
                        "id": provider.id,
                        "label": provider.label,
                        "enabled": provider.enabled,
                        "models": [
                            {
                                "id": model.id,
                                "label": model.label,
                                "enabled": model.enabled,
                            }
                            for model in provider.models
                        ],
                        "default_model_id": provider.default_model_id,
                        "command_template": provider.command_template,
                        "env_template": provider.env_template,
                    }
                    for provider in executor.providers
                ],
                "default_provider_id": executor.default_provider_id,
            }
            for executor in catalog.executors
        ]
    }


@router.get("/runtime-catalog")
async def get_runtime_catalog():
    """Get the global runtime catalog."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    service = _get_runtime_catalog_service()
    catalog = await service.load_catalog()
    return _public_runtime_catalog(catalog)


@router.put("/runtime-catalog")
async def update_runtime_catalog(request: RuntimeCatalogRequest):
    """Update the global runtime catalog.

    Validates the catalog before saving. Returns the saved catalog.
    """
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    service = _get_runtime_catalog_service()
    try:
        catalog = await service.save_catalog(await _merge_existing_runtime_secrets(request.catalog))
        return _public_runtime_catalog(catalog)
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


class TestExecutorRequest(BaseModel):
    executor_id: str
    provider_id: str | None = None
    model_id: str | None = None
    api_endpoint: str | None = None
    api_key: str | None = None


@router.post("/runtime-catalog/test")
async def test_runtime_executor(request: TestExecutorRequest):
    """Test an executor configuration by making a simple API call.

    Returns {"success": true, "latency_ms": ...} or {"success": false, "error": "..."}
    """
    import os
    import time
    import httpx

    catalog = await _get_runtime_catalog_service().load_catalog()
    executor = next((e for e in catalog.executors if e.id == request.executor_id), None)
    if executor is None:
        raise HTTPException(status_code=404, detail=f"Executor '{request.executor_id}' not found")

    # Build effective config
    provider_id = request.provider_id
    if provider_id == "None" or provider_id == "":
        provider_id = None
    if provider_id is None:
        provider_id = executor.default_provider_id
    if provider_id == "None":
        provider_id = None

    provider = next((p for p in executor.providers if p.id == provider_id), None) if provider_id else None
    if provider_id and provider is None:
        raise HTTPException(status_code=400, detail=f"Provider '{provider_id}' not found in executor '{request.executor_id}'")

    model_id = request.model_id
    if model_id == "None" or model_id == "":
        model_id = None
    if model_id is None:
        model_id = executor.default_model or (provider.default_model_id if provider else None)
    if model_id == "None":
        model_id = None

    if model_id is None:
        raise HTTPException(status_code=400, detail=f"No model specified for executor '{request.executor_id}'")

    if provider:
        model = next((m for m in provider.models if m.id == model_id), None)
        if model is None:
            raise HTTPException(status_code=400, detail=f"Model '{model_id}' not found in provider '{provider_id}'")

    # Resolve endpoint + key with env-var fallback (UI placeholder promises this).
    executor_type = executor.executor_type
    if executor_type == "codex":
        endpoint = (
            request.api_endpoint
            or executor.api_endpoint
            or os.getenv("OPENAI_BASE_URL")
            or "https://api.openai.com/v1"
        )
        api_key = request.api_key or executor.api_key or os.getenv("OPENAI_API_KEY")
        env_var_name = "OPENAI_API_KEY"
    else:
        endpoint = (
            request.api_endpoint
            or executor.api_endpoint
            or os.getenv("ANTHROPIC_BASE_URL")
            or "https://api.anthropic.com"
        )
        api_key = request.api_key or executor.api_key or os.getenv("ANTHROPIC_API_KEY")
        env_var_name = "ANTHROPIC_API_KEY"

    if not api_key:
        return {
            "success": False,
            "error": f"No API key: fill the field or set {env_var_name} in the backend env.",
        }

    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            if executor_type == "codex":
                response = await client.post(
                    f"{endpoint.rstrip('/')}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "content-type": "application/json",
                    },
                    json={
                        "model": model_id,
                        "max_tokens": 1,
                        "messages": [{"role": "user", "content": "ping"}],
                    },
                )
            else:
                response = await client.post(
                    f"{endpoint.rstrip('/')}/v1/messages",
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": model_id,
                        "max_tokens": 1,
                        "messages": [{"role": "user", "content": "ping"}],
                    },
                )
        latency_ms = (time.monotonic() - start) * 1000

        if response.status_code == 200:
            return {"success": True, "latency_ms": round(latency_ms, 1)}
        else:
            return {"success": False, "error": f"HTTP {response.status_code}: {response.text[:200]}"}
    except httpx.TimeoutException:
        return {"success": False, "error": "Request timed out after 10s"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# --- Agent CRUD (PR1: Workflow DAG, behind WORKFLOW_DAG_ENABLED) ---

class AgentCreateRequest(BaseModel):
    name: str
    role_key: str
    description: str | None = None
    system_prompt_template: str
    workspace_id: str | None = None
    input_schema: list[dict] | None = None
    output_schema: dict | None = None
    default_executor: str | None = None
    default_provider: str | None = None
    default_model: str | None = None
    artifact_subdir: str | None = None
    persist_kind: str | None = None
    triggers_replan_on_done: bool = False
    triggers_replan_on_fail: bool = False
    agent_tier: str = "custom"


class AgentUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    system_prompt_template: str | None = None
    input_schema: list[dict] | None = None
    output_schema: dict | None = None
    default_executor: str | None = None
    default_provider: str | None = None
    default_model: str | None = None
    artifact_subdir: str | None = None
    persist_kind: str | None = None
    triggers_replan_on_done: bool | None = None
    triggers_replan_on_fail: bool | None = None


def _require_agent_store():
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    return codex_store


@router.get("/agents")
async def list_agents(workspace_id: str | None = None, role_key: str | None = None):
    """List agents available to a workspace (workspace-specific + global) or all globals."""
    store = _require_agent_store()
    agents = await store.list_agents(workspace_id=workspace_id, role_key=role_key)
    return [a.model_dump() for a in agents]


@router.get("/agents/{agent_id}")
async def get_agent(agent_id: str):
    store = _require_agent_store()
    agent = await store.load_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    return agent.model_dump()


@router.post("/agents", status_code=201)
async def create_agent(request: AgentCreateRequest):
    """Create a custom (non-builtin) agent.

    Note: the API never lets callers create a builtin agent — that flag is reserved
    for the startup seeder. Custom agents default `artifact_subdir` to `node_<role_key>`
    so their artifacts don't collide with legacy role subdirs (pm/architect/...).
    """
    store = _require_agent_store()
    from app.domain.models import Agent
    if not request.role_key.strip():
        raise HTTPException(status_code=400, detail="role_key is required")
    if not request.system_prompt_template.strip():
        raise HTTPException(status_code=400, detail="system_prompt_template is required")
    # Enforce uniqueness within scope (matches DB UNIQUE constraint, but returns a clean error).
    existing = await store.list_agents(workspace_id=request.workspace_id, role_key=request.role_key)
    same_scope = [a for a in existing if a.workspace_id == request.workspace_id]
    if same_scope:
        raise HTTPException(
            status_code=409,
            detail=f"Agent with role_key '{request.role_key}' already exists in this scope",
        )
    now = datetime.now()
    agent = Agent(
        id=str(uuid4()),
        workspace_id=request.workspace_id,
        name=request.name,
        role_key=request.role_key,
        description=request.description,
        system_prompt_template=request.system_prompt_template,
        input_schema=request.input_schema or [],
        output_schema=request.output_schema or {},
        default_executor=request.default_executor,
        default_provider=request.default_provider,
        default_model=request.default_model,
        artifact_subdir=request.artifact_subdir or f"node_{request.role_key}",
        persist_kind=request.persist_kind,
        agent_tier=request.agent_tier if request.agent_tier in {"managed", "specialist", "custom"} else "custom",
        triggers_replan_on_done=request.triggers_replan_on_done,
        triggers_replan_on_fail=request.triggers_replan_on_fail,
        is_builtin=False,
        created_at=now,
        updated_at=now,
    )
    await store.save_agent(agent)
    return agent.model_dump()


@router.patch("/agents/{agent_id}")
async def update_agent(agent_id: str, request: AgentUpdateRequest):
    store = _require_agent_store()
    agent = await store.load_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    # Builtin agents are partially editable: only trigger flags and prompt overrides.
    if agent.is_builtin:
        forbidden_changes = {k for k, v in request.model_dump(exclude_unset=True).items() if v is not None and k not in {"triggers_replan_on_done", "triggers_replan_on_fail"}}
        if forbidden_changes:
            raise HTTPException(
                status_code=400,
                detail=f"Built-in agents only allow editing replan triggers; got: {sorted(forbidden_changes)}",
            )
    updates = request.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(agent, field, value)
    agent.updated_at = datetime.now()
    await store.save_agent(agent)
    return agent.model_dump()


@router.delete("/agents/{agent_id}", status_code=204)
async def delete_agent(agent_id: str):
    store = _require_agent_store()
    agent = await store.load_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    if agent.is_builtin:
        raise HTTPException(status_code=400, detail="Built-in agents cannot be deleted")
    deleted = await store.delete_agent(agent_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    return Response(status_code=204)


def _graph_to_dict(graph) -> dict:
    return {
        "id": graph.id,
        "issue_id": graph.issue_id,
        "preset_id": graph.preset_id,
        "status": graph.status,
        "dag_json": graph.dag_json,
        "created_by": graph.created_by,
        "locked_at": graph.locked_at.isoformat() if graph.locked_at else None,
        "created_at": graph.created_at.isoformat() if graph.created_at else None,
        "updated_at": graph.updated_at.isoformat() if graph.updated_at else None,
        "nodes": [n.model_dump() for n in graph.nodes],
        "edges": [e.model_dump() for e in graph.edges],
    }


@router.get("/codex/issues/{issue_id}/graph")
async def get_issue_graph(issue_id: str):
    store = _require_agent_store()
    graph = await store.load_workflow_graph_for_issue(issue_id)
    if graph is None:
        raise HTTPException(status_code=404, detail="No workflow graph exists for this issue")
    return _graph_to_dict(graph)


@router.get("/codex/issues/{issue_id}/graph-stats")
async def get_issue_graph_stats(issue_id: str):
    """Per-node telemetry for the DAG tab's dn-body / dn-tools / dn-foot.

    For each workflow node we report:
      - tokens (input + output, summed from the task's stream events)
      - duration_seconds (task.updated_at - task.created_at; or
        node.started_at..completed_at)
      - tools (role-default chip list; the graph schema doesn't carry
        per-node tools so we derive a sensible default from the role)
      - est_cost_usd (priced with the same env knobs as /cost-stats)

    Always also returns a synthetic `conductor` block so the start node
    in the DAG has stats to display.
    """
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    import json as _json
    import re as _re
    from datetime import datetime as _dt
    from pathlib import Path

    try:
        issue = await codex_store.load_codex_issue(issue_id)
    except AttributeError:
        # Older test stubs may not expose load_codex_issue. Worktree-less
        # paths still work — we just won't have on-disk summary stats.
        issue = None
    graph = await codex_store.load_workflow_graph_for_issue(issue_id)

    # Per-role summary stats are derived from the same on-disk artifacts
    # the pipeline-stages endpoint reads. We compute these even when the
    # graph itself isn't materialized yet so the DAG nodes look populated.
    worktree = issue.git_worktree_path if issue else None
    issue_root: Path | None = (
        Path(worktree) / "issues" / issue_id if worktree else None
    )

    def _read_json(rel: str):
        if not issue_root:
            return None
        p = issue_root / rel
        if not p.exists():
            return None
        try:
            return _json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _summary_stats(role_key: str) -> list[dict]:
        if role_key == "product_manager":
            prd = _read_json("pm/prd.json") or {}
            return [
                {
                    "num": _safe_len(prd.get("acceptance_criteria")),
                    "label": "acceptance",
                    "tone": "good",
                },
                {"num": _safe_len(prd.get("goals")), "label": "goals"},
                {
                    "num": _safe_len(
                        prd.get("requirements")
                        or prd.get("functional_requirements")
                    ),
                    "label": "reqs",
                },
            ]
        if role_key == "architect":
            design = _read_json("architect/system_design.json") or {}
            return [
                {
                    "num": _safe_len(design.get("components")),
                    "label": "component",
                },
                {
                    "num": _safe_len(
                        design.get("schemas") or design.get("data_models")
                    ),
                    "label": "schemas",
                },
                {
                    "num": _safe_len(design.get("migrations")),
                    "label": "migrations",
                },
            ]
        if role_key == "engineer" and issue_root:
            eng_dir = issue_root / "engineer"
            if not eng_dir.exists():
                return []
            files_changed = 0
            added = 0
            removed = 0
            for f in sorted(eng_dir.glob("implementation-*.md")):
                try:
                    text = f.read_text(encoding="utf-8")
                except OSError:
                    continue
                m_files = _re.search(
                    r"(\d+)\s*files?", text, _re.IGNORECASE
                )
                m_add = _re.search(r"\+(\d+)", text)
                m_rm = _re.search(r"[-−](\d+)\b", text)
                if m_files:
                    files_changed = max(files_changed, int(m_files.group(1)))
                if m_add:
                    added = max(added, int(m_add.group(1)))
                if m_rm:
                    removed = max(removed, int(m_rm.group(1)))
            return [
                {"num": added, "label": "added", "tone": "good"},
                {"num": removed, "label": "removed", "tone": "bad"},
                {"num": files_changed, "label": "files"},
            ]
        if role_key == "qa":
            qa = _read_json("qa/qa_plan.json") or {}
            results = (
                qa.get("results") if isinstance(qa.get("results"), dict) else {}
            )
            passed = qa.get("passed") or (results.get("passed") if results else 0) or 0
            failed = qa.get("failed") or (results.get("failed") if results else 0) or 0
            cmds = qa.get("recommended_commands") or qa.get("commands") or []
            n_cmds = len(cmds) if isinstance(cmds, list) else 0
            return [
                {"num": passed, "label": "passed", "tone": "good"},
                {"num": failed, "label": "failed", "tone": "bad" if failed else None},
                {"num": n_cmds, "label": "cmd"},
            ]
        return []

    if graph is None:
        # Return an empty shell — UI degrades gracefully.
        return {"nodes": {}, "conductor": _conductor_stub()}

    agents = await codex_store.list_agents(workspace_id=None)
    agent_role = {a.id: a.role_key for a in agents}

    input_per_m = float(os.getenv("COST_USD_PER_M_INPUT", "0.30"))
    output_per_m = float(os.getenv("COST_USD_PER_M_OUTPUT", "1.20"))
    cache_per_m = float(os.getenv("COST_USD_PER_M_CACHE_READ", "0.075"))

    # Per-role default tool lists matching the design handoff's dn-tools
    # chips. The graph schema doesn't persist per-node tool calls.
    role_tools = {
        "product_manager": ["read", "plan", "write"],
        "architect": ["design", "grep"],
        "engineer": ["edit", "bash", "read", "write"],
        "qa": ["bash", "pytest"],
    }

    out_nodes: dict[str, dict] = {}
    for n in graph.nodes:
        role = agent_role.get(n.agent_id) or n.node_key
        tools = role_tools.get(role, [])

        tokens_in = 0
        tokens_out = 0
        cache_in = 0
        sample = 0

        if n.task_id:
            task = await codex_store.load_codex_task(n.task_id)
            sid = task.session_id if task else None
            if sid:
                seen_msg: set[str] = set()
                rows = await codex_store.load_log_events(
                    session_id=sid, task_id=n.task_id, limit=5000
                )
                for ev in rows:
                    content = ev.content or ""
                    if "usage" not in content or "input_tokens" not in content:
                        continue
                    try:
                        obj = _json.loads(content)
                    except (ValueError, TypeError):
                        continue
                    sample += 1
                    usage = _extract_usage(obj)
                    if not usage:
                        continue
                    msg_id = _extract_message_id(obj)
                    if msg_id and msg_id in seen_msg:
                        continue
                    if msg_id:
                        seen_msg.add(msg_id)
                    tokens_in += int(usage.get("input_tokens") or 0)
                    tokens_out += int(usage.get("output_tokens") or 0)
                    cache_in += int(
                        usage.get("cache_read_input_tokens") or 0
                    )

        # Duration: prefer the node's started_at..completed_at window;
        # fall back to the task's created_at..updated_at.
        dur = None
        start_iso = (
            n.started_at.isoformat() if n.started_at else None
        )
        end_iso = (
            n.completed_at.isoformat() if n.completed_at else None
        )
        if start_iso and end_iso:
            try:
                dur = max(
                    0,
                    int(
                        (
                            _dt.fromisoformat(end_iso)
                            - _dt.fromisoformat(start_iso)
                        ).total_seconds()
                    ),
                )
            except ValueError:
                dur = None
        elif n.task_id:
            task = await codex_store.load_codex_task(n.task_id)
            if task and task.created_at and task.updated_at:
                try:
                    dur = max(
                        0,
                        int(
                            (task.updated_at - task.created_at).total_seconds()
                        ),
                    )
                except (TypeError, ValueError):
                    dur = None

        total_tokens = tokens_in + tokens_out
        est_cost = (
            tokens_in * input_per_m / 1_000_000
            + tokens_out * output_per_m / 1_000_000
            + cache_in * cache_per_m / 1_000_000
        )

        out_nodes[n.node_key] = {
            "task_id": n.task_id,
            "role_key": role,
            "tokens": {
                "input": tokens_in,
                "output": tokens_out,
                "total": total_tokens,
            }
            if sample
            else None,
            "duration_seconds": dur,
            "tools": tools,
            "est_cost_usd": round(est_cost, 4) if sample else None,
            "summary_stats": _summary_stats(role),
        }

    # Conductor synthetic block — knows the planned graph size.
    conductor = _conductor_stub()
    conductor["summary_stats"] = [
        {"num": len(graph.nodes), "label": "nodes planned"},
        {"num": len(graph.edges), "label": "edges"},
    ]
    return {"nodes": out_nodes, "conductor": conductor}


def _safe_len(value) -> int:
    if isinstance(value, list):
        return len([v for v in value if v])
    return 0


def _conductor_stub() -> dict:
    """Static stats block for the synthetic Conductor virtual node.

    Conductor doesn't run as a real task — it's the orchestrator step
    the UI surfaces as the start of the pipeline.
    """
    return {
        "task_id": None,
        "role_key": "conductor",
        "tokens": None,
        "duration_seconds": None,
        "tools": ["plan", "approve"],
        "summary_stats": [],
        "est_cost_usd": None,
    }


@router.post("/codex/issues/{issue_id}/graph/auto-start", status_code=201)
async def auto_start_issue_graph(issue_id: str):
    """Start Conductor-driven orchestration for an issue.

    Creates a minimal WorkflowGraph and launches run_issue_conductor_loop as a
    background task. The Conductor decides which agents to run and in what order,
    dynamically populating the graph with nodes for visualization.
    """
    import asyncio
    store = _require_agent_store()
    issue = await store.load_codex_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail=f"Issue {issue_id} not found")

    # Ensure worktree exists
    if issue.project_id and not issue.git_worktree_path and project_service is not None:
        project = await project_service.get_project(issue.project_id)
        if project is not None:
            try:
                branch, wt_path, base = await worktree_manager.prepare_issue_worktree(project, issue)
                issue.git_branch = branch
                issue.git_worktree_path = wt_path
                issue.git_base_branch = base
                await store.save_codex_issue(issue)
            except (GitError, WorktreeError):
                pass  # No git project — run without worktree (tests, demo mode)

    from app.domain.models import WorkflowGraph
    now = datetime.now()
    graph = WorkflowGraph(
        id=str(uuid4()),
        issue_id=issue_id,
        dag_json="{}",
        status="running",
        created_by="conductor",
        created_at=now,
        updated_at=now,
        nodes=[],
        edges=[],
    )
    await store.save_workflow_graph(graph, nodes=[], edges=[])

    project_id = issue.project_id
    if not project_id:
        workspace = await store.load_codex_session(issue.session_id)
        project_id = getattr(workspace, "project_id", None) if workspace else None

    if not project_id:
        raise HTTPException(status_code=409, detail="Issue has no associated project")

    from app.application.conductor_main_loop import recover_background_conductor_failure, run_issue_conductor_loop
    from app.application.event_bus import _workflow_task_dispatcher

    task = asyncio.create_task(run_issue_conductor_loop(
        issue=issue,
        project_id=project_id,
        store=store,
        event_bus=event_bus,
        task_dispatcher_fn=_workflow_task_dispatcher,
    ))
    task.add_done_callback(
        lambda done: _handle_conductor_loop_done(
            done,
            issue_id=issue_id,
            store=store,
            recover_fn=recover_background_conductor_failure,
        )
    )

    return _graph_to_dict(graph)


def _handle_conductor_loop_done(task, *, issue_id: str, store, recover_fn) -> None:
    import asyncio

    try:
        exc = task.exception()
    except asyncio.CancelledError:
        return
    if exc is None:
        return
    logger.error(
        "background conductor loop crashed for issue %s",
        issue_id,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    asyncio.create_task(
        recover_fn(
            issue_id=issue_id,
            store=store,
            event_bus=event_bus,
            exc=exc,
        )
    )


# ----------------------------------------------------------------------------
# Knowledge stack: cross-issue search, similar issues, team-notes CRUD
# ----------------------------------------------------------------------------


async def _resolve_project_repo_path_async(project_id: str | None) -> str | None:
    if not project_id or codex_store is None:
        return None
    load_project = getattr(codex_store, "load_project", None)
    if not callable(load_project):
        return None
    try:
        proj = await load_project(project_id)
    except Exception:  # noqa: BLE001
        return None
    if proj is None:
        return None
    return getattr(proj, "repo_path", None)


@router.get("/codex/search")
async def codex_search(
    q: str,
    scope: str = "all",
    project_id: str | None = None,
    mode: str = "hybrid",
    limit: int = 20,
):
    """Cross-issue knowledge search across issues_fts + artifacts_fts (and
    embeddings when configured). `mode` = fts | semantic | hybrid.
    """
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    if scope not in ("issues", "artifacts", "all"):
        raise HTTPException(status_code=400, detail="scope must be issues|artifacts|all")
    if mode not in ("fts", "semantic", "hybrid"):
        raise HTTPException(status_code=400, detail="mode must be fts|semantic|hybrid")
    limit = max(1, min(50, limit))
    from app.application import knowledge_index_service as kidx
    from app.application.embedding_service import get_embedding_service
    emb = get_embedding_service()
    result = await kidx.search(
        codex_store,
        query=q,
        scope=scope,  # type: ignore[arg-type]
        project_id=project_id,
        mode=mode,  # type: ignore[arg-type]
        limit=limit,
        embedding_service=emb,
    )
    return result


@router.get("/codex/issues/{issue_id}/conductor-log")
async def codex_issue_conductor_log(issue_id: str):
    """Return conductor decisions for this issue."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    if not hasattr(codex_store, "list_conductor_decisions"):
        return {"decisions": []}
    decisions = await codex_store.list_conductor_decisions(issue_id)
    return {"decisions": [
        {"id": d.id, "issue_id": d.issue_id, "task_id": d.task_id,
         "action": d.action, "reason": d.reason, "diff_json": d.diff_json,
         "applied_at": d.applied_at.isoformat() if d.applied_at else None,
         "created_at": d.created_at.isoformat() if d.created_at else None}
        for d in decisions
    ]}


@router.get("/codex/issues/{issue_id}/conductor-turns")
async def codex_issue_conductor_turns(
    issue_id: str,
    conductor_task_id: str | None = None,
    limit: int = 200,
):
    """Return persisted conductor loop turns for this issue."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    if not hasattr(codex_store, "list_conductor_turns"):
        return {"turns": []}
    turns = await codex_store.list_conductor_turns(
        issue_id,
        conductor_task_id=conductor_task_id,
        limit=limit,
    )
    payload = []
    for turn in turns:
        try:
            turn_payload = json.loads(turn.payload_json or "{}")
        except json.JSONDecodeError:
            turn_payload = {"raw": turn.payload_json}
        payload.append(
            {
                "id": turn.id,
                "conductor_task_id": turn.conductor_task_id,
                "issue_id": turn.issue_id,
                "turn_index": turn.turn_index,
                "sub_index": turn.sub_index,
                "kind": turn.kind,
                "payload": turn_payload,
                "created_at": turn.created_at.isoformat() if turn.created_at else None,
                "consumed_at": turn.consumed_at.isoformat() if getattr(turn, "consumed_at", None) else None,
            }
        )
    return {"turns": payload}


@router.get("/codex/issues/{issue_id}/conductor-state-log")
async def codex_issue_conductor_state_log(issue_id: str, limit: int = 200):
    """Return persisted conductor phase transitions for this issue."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    if not hasattr(codex_store, "list_conductor_state_logs"):
        return {"entries": []}
    entries = await codex_store.list_conductor_state_logs(issue_id, limit=limit, descending=True)
    return {
        "entries": [
            {
                "id": entry.id,
                "issue_id": entry.issue_id,
                "from_phase": entry.from_phase,
                "to_phase": entry.to_phase,
                "from_detail": entry.from_detail,
                "to_detail": entry.to_detail,
                "transition_at": entry.transition_at.isoformat() if entry.transition_at else None,
                "duration_ms": entry.duration_ms,
                "is_legal": entry.is_legal,
            }
            for entry in entries
        ]
    }


@router.post("/codex/issues/{issue_id}/conductor/message")
async def codex_issue_conductor_message(issue_id: str, request: IssueConductorMessageRequest):
    """Queue a user interjection for the currently active issue conductor loop."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    issue = await codex_store.load_codex_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    if not hasattr(codex_store, "load_latest_conductor_task_for_issue") or not hasattr(codex_store, "enqueue_conductor_user_message"):
        raise HTTPException(status_code=501, detail="Conductor inbox not supported by this store")
    conductor_task = await codex_store.load_latest_conductor_task_for_issue(issue_id)
    if conductor_task is None or conductor_task.status not in {"running", "paused"}:
        raise HTTPException(status_code=409, detail="No active conductor loop for this issue")
    text = request.message.strip()
    if not text:
        raise HTTPException(status_code=400, detail="message is required")
    turn = await codex_store.enqueue_conductor_user_message(conductor_task.id, issue_id, text)
    if conductor_task.status == "paused":
        from app.application.conductor_pause_registry import ConductorPauseRegistry
        from app.application.conductor_main_loop import transition_conductor_phase

        payload = conductor_task.payload if isinstance(conductor_task.payload, dict) else {}
        await transition_conductor_phase(
            store=codex_store,
            event_bus=event_bus,
            issue_id=issue_id,
            conductor_task=conductor_task,
            phase=str(payload.get("resume_phase") or "awaiting_llm"),
            detail=str(payload.get("resume_detail")) if payload.get("resume_detail") else None,
            status="running",
            estimator=get_phase_duration_estimator(codex_store),
        )
        await ConductorPauseRegistry.instance().resume(conductor_task.id)
    payload = {"text": text}
    if event_bus is not None and hasattr(event_bus, "append"):
        await event_bus.append(
            {
                "type": "conductor_turn",
                "id": turn.id,
                "issue_id": issue_id,
                "conductor_task_id": conductor_task.id,
                "turn_index": turn.turn_index,
                "sub_index": turn.sub_index,
                "kind": turn.kind,
                "payload": payload,
                "summary": f"User interjection: {text[:80]}",
                "created_at": turn.created_at.isoformat() if turn.created_at else None,
                "consumed_at": None,
            }
        )
    return {"ok": True, "conductor_task_id": conductor_task.id, "status": conductor_task.status}


@router.post("/codex/issues/{issue_id}/conductor/pause")
async def codex_issue_conductor_pause(issue_id: str):
    """Pause the currently active issue conductor loop."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    issue = await codex_store.load_codex_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    if not hasattr(codex_store, "load_latest_conductor_task_for_issue"):
        raise HTTPException(status_code=501, detail="Conductor pause not supported by this store")
    conductor_task = await codex_store.load_latest_conductor_task_for_issue(issue_id)
    if conductor_task is None:
        raise HTTPException(status_code=409, detail="No active conductor loop for this issue")
    if conductor_task.status == "paused":
        return {"ok": True, "conductor_task_id": conductor_task.id, "status": conductor_task.status}
    if conductor_task.status != "running":
        raise HTTPException(status_code=409, detail="Conductor loop is not running")
    from app.application.conductor_pause_registry import ConductorPauseRegistry
    from app.application.conductor_main_loop import transition_conductor_phase

    await ConductorPauseRegistry.instance().request_pause(conductor_task.id)
    await transition_conductor_phase(
        store=codex_store,
        event_bus=event_bus,
        issue_id=issue_id,
        conductor_task=conductor_task,
        phase="paused",
        detail=(conductor_task.payload or {}).get("detail"),
        status="paused",
        estimator=get_phase_duration_estimator(codex_store),
    )
    return {"ok": True, "conductor_task_id": conductor_task.id, "status": conductor_task.status}


@router.post("/codex/issues/{issue_id}/conductor/resume")
async def codex_issue_conductor_resume(issue_id: str):
    """Resume a paused issue conductor loop."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    issue = await codex_store.load_codex_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    if not hasattr(codex_store, "load_latest_conductor_task_for_issue"):
        raise HTTPException(status_code=501, detail="Conductor resume not supported by this store")
    conductor_task = await codex_store.load_latest_conductor_task_for_issue(issue_id)
    if conductor_task is None or conductor_task.status != "paused":
        raise HTTPException(status_code=409, detail="Conductor loop is not paused")
    from app.application.conductor_pause_registry import ConductorPauseRegistry
    from app.application.conductor_main_loop import transition_conductor_phase

    payload = conductor_task.payload if isinstance(conductor_task.payload, dict) else {}
    await transition_conductor_phase(
        store=codex_store,
        event_bus=event_bus,
        issue_id=issue_id,
        conductor_task=conductor_task,
        phase=str(payload.get("resume_phase") or "awaiting_llm"),
        detail=str(payload.get("resume_detail")) if payload.get("resume_detail") else None,
        status="running",
        estimator=get_phase_duration_estimator(codex_store),
    )
    await ConductorPauseRegistry.instance().resume(conductor_task.id)
    return {"ok": True, "conductor_task_id": conductor_task.id, "status": conductor_task.status}


@router.get("/codex/issues/{issue_id}/conductor-state")
async def codex_issue_conductor_state(issue_id: str):
    """Return IssueConductor rolling state for this issue."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    if not hasattr(codex_store, "load_conductor_state"):
        return {
            "issue_id": issue_id,
            "running_thread": [],
            "pending_dispatches": [],
            "scratchpad": "",
            "decision_count": 0,
            "updated_at": None,
            "conductor_task_id": None,
            "conductor_status": None,
            "phase": None,
            "detail": None,
        }
    conductor_task = None
    if hasattr(codex_store, "load_latest_conductor_task_for_issue"):
        conductor_task = await codex_store.load_latest_conductor_task_for_issue(issue_id)
    state = await codex_store.load_conductor_state(issue_id)
    if state is None:
        return {
            "issue_id": issue_id,
            "running_thread": [],
            "pending_dispatches": [],
            "scratchpad": "",
            "decision_count": 0,
            "updated_at": None,
            "conductor_task_id": conductor_task.id if conductor_task else None,
            "conductor_status": conductor_task.status if conductor_task else None,
            "phase": (conductor_task.payload or {}).get("phase") if conductor_task else None,
            "detail": (conductor_task.payload or {}).get("detail") if conductor_task else None,
        }
    try:
        running_thread = json.loads(state.running_thread_json or "[]")
    except json.JSONDecodeError:
        running_thread = []
    try:
        pending_dispatches = json.loads(state.pending_dispatches_json or "[]")
    except json.JSONDecodeError:
        pending_dispatches = []
    return {
        "issue_id": state.issue_id,
        "running_thread": running_thread if isinstance(running_thread, list) else [],
        "pending_dispatches": pending_dispatches if isinstance(pending_dispatches, list) else [],
        "scratchpad": state.scratchpad,
        "decision_count": state.decision_count,
        "updated_at": state.updated_at.isoformat() if state.updated_at else None,
        "conductor_task_id": conductor_task.id if conductor_task else None,
        "conductor_status": conductor_task.status if conductor_task else None,
        "phase": (conductor_task.payload or {}).get("phase") if conductor_task else None,
        "detail": (conductor_task.payload or {}).get("detail") if conductor_task else None,
    }


@router.get("/codex/issues/{issue_id}/conductor-phase-estimates")
async def codex_issue_conductor_phase_estimates(issue_id: str):
    """Return conductor phase duration estimates aggregated from all history."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    estimator = get_phase_duration_estimator(codex_store)
    estimates = await estimator.all_estimates()
    return {
        "issue_id": issue_id,
        "estimates": {
            phase: estimate.to_dict()
            for phase, estimate in estimates.items()
        },
    }


@router.get("/codex/projects/{project_id}/conductor-state")
async def codex_project_conductor_state(project_id: str):
    """Return ProjectConductor tiered-memory state for a project."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    from app.application.project_conductor import ProjectConductor

    project = await codex_store.load_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    conductor = ProjectConductor(project_id=project_id, store=codex_store, event_bus=event_bus)
    state = await conductor.get_or_create_state()
    try:
        hot_thread = json.loads(state.hot_thread_json or "[]")
    except json.JSONDecodeError:
        hot_thread = []
    try:
        warm_summaries = json.loads(state.warm_summaries_json or "[]")
    except json.JSONDecodeError:
        warm_summaries = []
    cold = await codex_store.list_project_memory_embeddings(project_id, limit=20)
    return {
        "project_id": state.project_id,
        "hot_thread": hot_thread if isinstance(hot_thread, list) else [],
        "warm_summaries": warm_summaries if isinstance(warm_summaries, list) else [],
        "cold_memories": [
            {
                "id": memory.id,
                "source_kind": memory.source_kind,
                "source_id": memory.source_id,
                "summary_text": memory.summary_text,
                "created_at": memory.created_at.isoformat() if memory.created_at else None,
            }
            for memory in cold
        ],
        "pinned_text": state.pinned_text,
        "hot_tokens": state.hot_tokens,
        "warm_tokens": state.warm_tokens,
        "total_tasks_handled": state.total_tasks_handled,
        "last_compaction_at": state.last_compaction_at.isoformat() if state.last_compaction_at else None,
        "updated_at": state.updated_at.isoformat() if state.updated_at else None,
    }


@router.post("/codex/projects/{project_id}/conductor/ask")
async def codex_project_conductor_ask(project_id: str, request: ProjectConductorAskRequest):
    """Ask the long-lived ProjectConductor an ad-hoc project question."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    from app.application.project_conductor import ProjectConductor

    project = await codex_store.load_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    task = ConductorTask(
        id=str(uuid4()),
        project_id=project_id,
        task_kind="ad_hoc",
        payload={"question": request.question},
        created_at=datetime.now(),
    )
    conductor = ProjectConductor(project_id=project_id, store=codex_store, event_bus=event_bus)
    return await conductor.handle_task(task)


@router.post("/codex/projects/{project_id}/conductor/schedule-review")
async def codex_project_conductor_schedule_review(project_id: str):
    """Queue a deterministic scheduled-review conductor task."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    from app.application.project_conductor import ProjectConductor

    project = await codex_store.load_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    task = ConductorTask(
        id=str(uuid4()),
        project_id=project_id,
        task_kind="scheduled_review",
        payload={"question": "Run a scheduled project health review."},
        created_at=datetime.now(),
    )
    conductor = ProjectConductor(project_id=project_id, store=codex_store, event_bus=event_bus)
    return await conductor.handle_task(task)


@router.post("/codex/projects/{project_id}/conductor/start-loop")
async def codex_project_conductor_start_loop(project_id: str, request: ProjectConductorStartLoopRequest):
    """Run the Phase 6 ProjectConductor Anthropic tool-use loop."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    from app.application.conductor_main_loop import run_conductor_loop
    from app.application.conductor_tools import build_conductor_tools
    from app.application.llm_runner import call_llm_with_tools, resolve_streaming_context
    from app.application.project_conductor import ProjectConductor

    project = await codex_store.load_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    issue = None
    if request.issue_id:
        issue = await codex_store.load_codex_issue(request.issue_id)
        if issue is None:
            raise HTTPException(status_code=404, detail="Issue not found")

    prompt = (request.prompt or "").strip()
    if not prompt and issue is not None:
        prompt = f"Run ProjectConductor loop for issue: {issue.title}\n\n{issue.description or ''}".strip()
    if not prompt:
        prompt = "Run ProjectConductor loop for this project and summarize the next best action."

    task = ConductorTask(
        id=str(uuid4()),
        project_id=project_id,
        task_kind="issue" if issue else "ad_hoc",
        issue_id=issue.id if issue else None,
        payload={"prompt": prompt, "mode": "loop"},
        status="running",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    await codex_store.save_conductor_task(task)

    registry = build_conductor_tools(project_id=project_id, store=codex_store, event_bus=event_bus)
    catalog = await _get_runtime_catalog_service().load_catalog()
    ctx = resolve_streaming_context(catalog)

    async def llm(messages, tools):
        if ctx is None:
            return {
                "stop_reason": "tool_use",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_fallback_final",
                        "name": "finalize_task",
                        "input": {
                            "status": "done",
                            "answer": "No usable LLM executor is configured; ProjectConductor loop created a deterministic checkpoint instead.",
                        },
                    }
                ],
            }
        return await call_llm_with_tools(messages=messages, tools=tools, ctx=ctx)

    result = await run_conductor_loop(
        prompt=prompt,
        llm=llm,
        tools=registry.tools,
        tool_definitions=registry.definitions,
    )
    conductor = ProjectConductor(project_id=project_id, store=codex_store, event_bus=event_bus)
    await conductor.append_hot_event(
        role="project_conductor",
        content=result.final_text,
        issue_id=issue.id if issue else None,
        extra={
            "task_id": task.id,
            "kind": "loop",
            "status": result.status,
            "tool_events": result.tool_events,
        },
    )
    payload = {
        "status": result.status,
        "answer": result.final_text,
        "task_id": task.id,
        "tool_events": result.tool_events,
        "turn_count": result.turn_count,
        "llm": None if ctx is None else {"executor": ctx.executor_label, "model": ctx.model},
    }
    task.status = result.status
    task.result_json = json.dumps(payload, ensure_ascii=False, default=str)
    task.updated_at = datetime.now()
    await codex_store.save_conductor_task(task)
    if event_bus is not None and hasattr(event_bus, "append"):
        try:
            await event_bus.append(
                {
                    "type": "project_conductor_loop",
                    "project_id": project_id,
                    "task_id": task.id,
                    "status": result.status,
                },
            )
        except Exception:  # noqa: BLE001
            logger.debug("ProjectConductor loop event emit failed", exc_info=True)
    return payload


@router.get("/codex/projects/{project_id}/conductor/stream")
async def codex_project_conductor_stream(project_id: str):
    """SSE replay of recent ProjectConductor loop/tool events."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    from fastapi.responses import StreamingResponse
    from app.application.project_conductor import ProjectConductor

    project = await codex_store.load_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    async def emit(event: str, payload) -> str:
        return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"

    async def gen():
        conductor = ProjectConductor(project_id=project_id, store=codex_store, event_bus=event_bus)
        state = await conductor.get_or_create_state()
        try:
            hot_thread = json.loads(state.hot_thread_json or "[]")
        except json.JSONDecodeError:
            hot_thread = []
        yield await emit("meta", {"project_id": project_id, "mode": "loop"})
        for item in hot_thread[-20:] if isinstance(hot_thread, list) else []:
            yield await emit("event", item)
            for tool_event in item.get("tool_events", []) if isinstance(item, dict) else []:
                yield await emit("tool", tool_event)
        yield await emit("done", {"project_id": project_id})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/codex/issues/{issue_id}/subagent-results")
async def codex_issue_subagent_results(issue_id: str):
    """Return completed/failed sub-agent task results for an issue."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    tasks = await codex_store.list_codex_tasks(issue_id=issue_id)
    terminal = {"done", "failed", "completed"}
    results = []
    for t in tasks:
        if t.get("status") not in terminal:
            continue
        artifact = None
        if t.get("result_json"):
            try:
                artifact = json.loads(t["result_json"])
            except (json.JSONDecodeError, TypeError):
                artifact = None
        results.append({
            "task_id": t["id"],
            "role": t.get("role") or "unknown",
            "title": t.get("title") or "",
            "status": t.get("status"),
            "task_kind": t.get("task_kind") or "initial",
            "parent_task_id": t.get("parent_task_id"),
            "summary": t.get("result") or "",
            "artifact_json": artifact,
            "updated_at": t.get("updated_at"),
        })
    return results


@router.get("/codex/issues/{issue_id}/agent-mesh")
async def codex_issue_agent_mesh(issue_id: str):
    """Return AgentMessage list for an issue (alias of agent-messages logic)."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    if not hasattr(codex_store, "list_agent_messages"):
        return []
    import dataclasses
    messages = await codex_store.list_agent_messages(issue_id)
    return [dataclasses.asdict(m) for m in messages]


class ProjectConductorMessageRequest(BaseModel):
    message: str


@router.post("/codex/projects/{project_id}/conductor/message")
async def codex_project_conductor_message(project_id: str, request: ProjectConductorMessageRequest):
    """Append a user message to the ProjectConductor hot thread."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    from app.application.project_conductor import ProjectConductor
    conductor = ProjectConductor(project_id=project_id, store=codex_store)
    await conductor.append_hot_event(role="user", content=request.message)
    return {"status": "ok"}


@router.get("/codex/issues/{issue_id}/agent-messages")
async def codex_issue_agent_messages(issue_id: str):
    """Return agent-to-agent messages (critiques, handoffs) for this issue."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    if not hasattr(codex_store, "list_agent_messages"):
        return {"messages": []}
    messages = await codex_store.list_agent_messages(issue_id)
    return {
        "messages": [
            {
                "id": m.id,
                "issue_id": m.issue_id,
                "graph_id": m.graph_id,
                "from_node_key": m.from_node_key,
                "to_node_key": m.to_node_key,
                "message_type": m.message_type,
                "body": m.body,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ]
    }


@router.get("/codex/issues/{issue_id}/similar")
async def codex_issue_similar(issue_id: str, k: int = 5):
    """Return up to k issues similar to the given one. Uses embeddings when
    available, falls back to FTS over the title+description bag of words."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    k = max(1, min(20, k))
    from app.application import knowledge_index_service as kidx
    from app.application.embedding_service import get_embedding_service
    items = await kidx.find_similar_issues(
        codex_store, issue_id, k=k, embedding_service=get_embedding_service()
    )
    return {"items": items}


@router.post("/codex/index/reindex")
async def codex_reindex(project_id: str | None = None):
    """Walk codex_issues + artifact_paths and rebuild FTS (+ embeddings if
    configured). Returns counts. Useful right after a migration."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    from app.application import knowledge_index_service as kidx
    from app.application.embedding_service import get_embedding_service
    stats = await kidx.reindex_all(
        codex_store, project_id=project_id, embedding_service=get_embedding_service()
    )
    return stats


@router.get("/codex/embedding/status")
async def codex_embedding_status():
    """Tells the frontend whether semantic search is online."""
    from app.application.embedding_service import get_embedding_service
    emb = get_embedding_service()
    return {
        "enabled": emb.enabled,
        "model": emb.config.model if emb.enabled else None,
        "provider_type": emb.config.provider_type if emb.enabled else None,
    }


@router.get("/projects/{project_id}/team-notes")
async def get_team_notes(project_id: str, include_deleted: bool = False):
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    from app.application.team_notes_service import team_notes
    repo_path = await _resolve_project_repo_path_async(project_id)
    raw = team_notes.read_markdown(repo_path)
    blocks = await team_notes.list_blocks(
        codex_store, project_id, repo_path, include_deleted=include_deleted
    )
    return {
        "project_id": project_id,
        "raw_markdown": raw,
        "blocks": [b.to_dict() for b in blocks],
    }


class TeamNotesPinBody(BaseModel):
    pinned: bool


@router.delete("/projects/{project_id}/team-notes/{block_id}")
async def delete_team_notes_block(project_id: str, block_id: str):
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    from app.application.team_notes_service import team_notes
    await team_notes.soft_delete(codex_store, project_id, block_id)
    return {"ok": True, "block_id": block_id, "deleted": True}


@router.post("/projects/{project_id}/team-notes/{block_id}/restore")
async def restore_team_notes_block(project_id: str, block_id: str):
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    from app.application.team_notes_service import team_notes
    await team_notes.restore(codex_store, project_id, block_id)
    return {"ok": True, "block_id": block_id, "deleted": False}


@router.post("/projects/{project_id}/team-notes/{block_id}/pin")
async def pin_team_notes_block(project_id: str, block_id: str, body: TeamNotesPinBody):
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    from app.application.team_notes_service import team_notes
    await team_notes.set_pinned(codex_store, project_id, block_id, body.pinned)
    return {"ok": True, "block_id": block_id, "pinned": body.pinned}
