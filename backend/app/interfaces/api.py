from datetime import datetime
from uuid import uuid4
from pathlib import Path
import logging
import shutil

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
import json

from pydantic import BaseModel
from typing import Literal
import subprocess

from app.bootstrap import session_service, orchestration_service, approval_service, codex_store, get_codex_process_manager, check_codex_available, event_bus, MockCodexProcessManager, get_help_orchestrator, project_service, worktree_manager, git_service
from app.domain.models import CodexIssue, Project
from app.application.codex_task_runner import CodexTaskRunner
from app.application.product_manager_service import ProductManagerArtifactError, ProductManagerService
from app.application.role_workflow_service import RoleWorkflowService
from app.application.process_runtime_common import is_agent_message_item_type
from app.application.project_service import ProjectError
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
        workspace = await codex_store.load_codex_workspace(task.session_id)
        workspace_title = workspace.title if workspace is not None else None
        artifact = await role_workflow_service.persist_result(task, workspace_title=workspace_title)

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


@router.get("/codex/stats")
async def get_codex_stats():
    """Aggregate counts across all Codex sessions and issues.

    Returns workspace/session counts, task metrics bucketed by status,
    and executor availability flags. Computed on-demand; no persistence.
    """
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")

    sessions = await codex_store.list_codex_sessions(project_id=None)
    issues = await codex_store.list_codex_issues(project_id=None)

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
    title: str
    project_id: str
    cwd: str = ""


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
    return issue


@router.post("/codex/issues/{issue_id}/duplicate", response_model=CodexIssue, status_code=201)
async def duplicate_codex_issue(issue_id: str):
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    issue = await codex_store.load_codex_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail=f"Issue '{issue_id}' not found")
    import uuid
    new_issue = CodexIssue(
        id=str(uuid.uuid4()),
        session_id=issue.session_id,
        project_id=issue.project_id,
        title=f"{issue.title} (copy)",
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
                branch, worktree_path, base = await worktree_manager.prepare_issue_worktree(project, new_issue)
                new_issue.git_branch = branch
                new_issue.git_worktree_path = worktree_path
                new_issue.git_base_branch = base
            except (GitError, WorktreeError) as exc:
                raise HTTPException(status_code=500, detail=f"failed to create issue worktree: {exc}")
    await codex_store.save_codex_issue(new_issue)
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

    # Load artifacts from DB
    rows = await codex_store.list_artifacts(issue_id)

    # If no DB records exist, fall back to disk scanning and backfill DB
    if not rows:
        rows = await _scan_and_backfill_artifacts(issue_id, issue.session_id, codex_store)

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

    # PM backfill: for each done pm task, check its own worktree for prd files
    # and trigger persist_result if missing.
    for task_row in sorted_tasks:
        if task_row.get("role") != "product_manager":
            continue
        if str(task_row.get("status") or "").lower() != "done":
            continue
        workspace_path = task_row.get("workspace_path")
        if not workspace_path:
            continue
        pm_dir = Path(workspace_path) / "issues" / issue_id / "pm"
        if not ((pm_dir / "prd.json").exists() and (pm_dir / "prd.md").exists()):
            task = await store.load_codex_task(task_row.get("id"))
            if task is not None and getattr(task, "result", None):
                ws = await store.load_codex_workspace(task.session_id)
                try:
                    await role_workflow_service.persist_result(task, workspace_title=ws.title if ws else None)
                except ProductManagerArtifactError:
                    pass
        if (pm_dir / "prd.json").exists() and (pm_dir / "prd.md").exists():
            break

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
    for artifact_name, artifact_data in artifact_map.items():
        await store.save_artifact({
            "id": artifact_data["id"],
            "issue_id": issue_id,
            "task_id": artifact_data["task_id"],
            "name": artifact_data["name"],
            "path": artifact_data["path"],
            "kind": artifact_data["kind"],
            "created_at": artifact_data["created_at"],
        })

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
    """Mark an issue's branch as abandoned and clean up its worktree.

    The DB record stays; only the on-disk worktree + branch state is dropped so
    the user can keep the issue around as history without it counting as open.
    """
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    issue = await codex_store.load_codex_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    if issue.git_merge_status == "merged":
        raise HTTPException(status_code=409, detail="cannot abandon a merged issue")
    if issue.project_id:
        project = await codex_store.load_project(issue.project_id)
        if project is not None:
            try:
                await worktree_manager.cleanup_issue_worktree(project, issue)
            except Exception:
                pass
    issue.git_merge_status = "abandoned"
    issue.git_worktree_path = None
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
        "sha": result["sha"],
        "base_branch": result["base_branch"],
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

    # Determine endpoint and key (use request overrides or executor defaults)
    endpoint = request.api_endpoint or executor.api_endpoint
    api_key = request.api_key or executor.api_key

    if not endpoint or not api_key:
        raise HTTPException(status_code=400, detail="api_endpoint and api_key are required")

    # Build the request
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
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


# --- Workflow plan endpoint (PR2) ---


@router.post("/codex/issues/{issue_id}/plan")
async def propose_issue_plan(issue_id: str):
    """Run the orchestrator and return a proposed DAG. Does NOT persist.

    Tries the real LLM (configured via the runtime catalog) first; silently
    falls back to the keyword heuristic when the LLM is unreachable, the
    response can't be parsed/validated, or `WORKFLOW_ORCHESTRATOR_LLM` is
    explicitly set to "false".
    """
    import os
    store = _require_agent_store()
    issue = await store.load_codex_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail=f"Issue {issue_id} not found")
    from app.application.workflow_orchestrator import WorkflowOrchestrator
    from app.application.llm_runner import build_llm_runner

    llm_disabled = os.getenv("WORKFLOW_ORCHESTRATOR_LLM", "").lower() == "false"
    llm_runner = None if llm_disabled else build_llm_runner(_get_runtime_catalog_service())
    orchestrator = WorkflowOrchestrator(store=store, llm_runner=llm_runner)
    try:
        dag = await orchestrator.propose_graph(issue, use_llm=not llm_disabled)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return dag


# --- Workflow graph persistence (PR3) ---

class SaveGraphRequest(BaseModel):
    dag: dict
    created_by: str = "user"


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


@router.post("/codex/issues/{issue_id}/graph", status_code=201)
async def save_issue_graph(issue_id: str, request: SaveGraphRequest):
    """Persist (or overwrite) the workflow graph for an issue from a DAG payload."""
    store = _require_agent_store()
    issue = await store.load_codex_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail=f"Issue {issue_id} not found")
    agents = await store.list_agents(workspace_id=None)
    from app.application.workflow_orchestrator import validate_dag
    try:
        validate_dag(request.dag, {a.id for a in agents})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    from app.application.workflow_scheduler import materialize_graph_from_dag
    graph = await materialize_graph_from_dag(store, issue_id, request.dag, created_by=request.created_by)
    return _graph_to_dict(graph)


@router.post("/codex/issues/{issue_id}/graph/start")
async def start_issue_graph(issue_id: str):
    """Begin DAG execution. Returns the graph after the first settle pass."""
    store = _require_agent_store()
    graph = await store.load_workflow_graph_for_issue(issue_id)
    if graph is None:
        raise HTTPException(status_code=404, detail="No workflow graph exists for this issue")
    from app.application.workflow_scheduler import WorkflowScheduler
    from app.application.event_bus import _workflow_task_dispatcher
    scheduler = WorkflowScheduler(store=store, task_dispatcher=_workflow_task_dispatcher)
    graph = await scheduler.start_graph(graph.id)
    return _graph_to_dict(graph)


# --- Replanner endpoints (PR6) ---


@router.get("/codex/issues/{issue_id}/graph/replan-pending")
async def list_replan_pending(issue_id: str):
    store = _require_agent_store()
    graph = await store.load_workflow_graph_for_issue(issue_id)
    if graph is None:
        return []
    pending = await store.list_pending_replans(graph.id)
    return [
        {
            "id": r.id,
            "graph_id": r.graph_id,
            "triggered_by_node_key": r.triggered_by_node_key,
            "trigger_reason": r.trigger_reason,
            "diff": json.loads(r.diff_json) if r.diff_json else {},
            "rationale": r.rationale,
            "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in pending
    ]


@router.post("/codex/issues/{issue_id}/graph/replan/{replan_id}/confirm")
async def confirm_replan(issue_id: str, replan_id: str):
    store = _require_agent_store()
    from app.application.workflow_scheduler import WorkflowScheduler, WorkflowSchedulerError
    scheduler = WorkflowScheduler(store=store, task_dispatcher=None)
    try:
        graph = await scheduler.apply_replan(replan_id, "confirmed")
    except (ValueError, WorkflowSchedulerError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _graph_to_dict(graph)


@router.post("/codex/issues/{issue_id}/graph/replan/{replan_id}/reject")
async def reject_replan(issue_id: str, replan_id: str):
    store = _require_agent_store()
    from app.application.workflow_scheduler import WorkflowScheduler, WorkflowSchedulerError
    scheduler = WorkflowScheduler(store=store, task_dispatcher=None)
    try:
        graph = await scheduler.apply_replan(replan_id, "rejected")
    except (ValueError, WorkflowSchedulerError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _graph_to_dict(graph)
