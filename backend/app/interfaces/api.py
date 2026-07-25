import ast
import base64
import io
import json
import logging
import shutil
import zipfile
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol, TypedDict, cast
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field, field_validator, model_validator

from app.adapters.local_process import CalledProcessError, run_trusted_local
from app.application import timeouts
from app.application.budget_service import IssueBudgetPayload, compute_issue_budget_status
from app.application.codex_task_runner import CodexTaskRunner, TaskProcessManager, TaskRunnerStore
from app.application.conductor_policy import classify_issue_orchestration
from app.application.event_bus import event_bus
from app.application.git_service import GitError
from app.application.github_pr_followup import (
    CompletedProcessLike,
    GitHubPRFollowupStore,
    sweep_project_github_prs,
)
from app.application.llm_runner import llm_api_url
from app.application.local_service_probe import (
    LocalServiceStatus,
    ProjectRunStatusPayload,
    add_service_status,
    probe_local_service,
    resolve_project_access_url,
    resolve_project_readiness_probe,
    unknown_local_service_status,
)
from app.application.mcp_registry import McpManagementService
from app.application.process_runtime_common import is_agent_message_item_type
from app.application.product_manager_service import (
    ProductManagerArtifactError,
    ProductManagerService,
)
from app.application.project_conductor import (
    PROJECT_CONDUCTOR_INPUT_MAX_CHARS,
    PROJECT_CONDUCTOR_STATE_COLD_LIMIT,
    PROJECT_CONDUCTOR_STATE_HOT_LIMIT,
    PROJECT_CONDUCTOR_STATE_WARM_LIMIT,
    ProjectConductor,
    ProjectConductorStore,
)
from app.application.project_conductor import _run_subprocess as _project_conductor_run_subprocess
from app.application.project_run_manager import ProjectRunError, project_run_manager
from app.application.project_script_suggestions import suggest_project_scripts
from app.application.project_service import ProjectError, ProjectService
from app.application.project_service_readiness import (
    ApplicationReadinessStatus,
    evaluate_project_service,
    invalid_readiness_status,
)
from app.application.resume_service import (
    MAX_PDF_IMPORT_BYTES,
    ResumeDependencyError,
    ResumeDocument,
    ResumeProjectPathError,
    ResumeValidationError,
    resume_service,
)
from app.application.role_workflow_service import RoleWorkflowService, RoleWorkflowStore
from app.application.runtime_catalog_service import (
    RuntimeCatalogService,
    RuntimeCatalogValidationError,
)
from app.application.self_improvement_apply_service import (
    SelfImprovementApplyError,
    apply_project_memory_proposal,
    build_self_improvement_apply_plan,
    rollback_project_memory_proposal,
)
from app.application.task_status_events import build_task_status_event
from app.application.task_statuses import (
    execution_process_state_for_task,
    is_task_active_status,
    is_task_failure_status,
    is_task_pending_status,
    is_task_success_status,
    is_task_waiting_for_help_status,
)
from app.application.worktree_manager import WorktreeError
from app.bootstrap import (
    MockCodexProcessManager,
    approval_service,
    check_codex_available,
    get_codex_process_manager,
    get_help_orchestrator,
    git_service,
    mcp_registry,
    orchestration_service,
    project_service,
    project_startup_config_service,
    project_startup_mcp_service,
    session_service,
    worktree_manager,
)
from app.bootstrap import (
    codex_store as _bootstrap_codex_store,
)
from app.domain.models import (
    Agent,
    AgentCallTrace,
    AgentMessage,
    AuditLog,
    CodexIssue,
    CodexSession,
    CodexTask,
    CodexTaskMessage,
    CodexWorkspace,
    ConductorTask,
    ExecutionProcess,
    GraphReplanPending,
    HelpRequest,
    LogEvent,
    Project,
    ProjectConductorState,
    ProjectEnvVar,
    ProjectMemoryEmbedding,
    ProjectReadinessProbe,
    ProjectStartupService,
    RuntimeCatalog,
    RuntimeExecutorConfig,
    SelfImprovementApplicationEvent,
    SelfImprovementProposal,
    WorkflowEdge,
    WorkflowGraph,
    WorkflowNode,
)
from app.interfaces.execution_process_views import build_execution_process_view
from app.json_safety import (
    JsonObject,
)
from app.json_safety import (
    object_dict as _json_object,
)
from app.json_safety import (
    object_dict_list as _json_object_list,
)
from app.json_safety import (
    parse_json_list as _safe_json_list,
)
from app.json_safety import (
    parse_json_object as _safe_json_object,
)
from app.json_safety import (
    parse_json_object_list as _safe_json_object_list,
)
from benchmark import api as benchmark_handlers
from benchmark.api import TriggerRunRequest as BenchmarkTriggerRunRequest

logger = logging.getLogger(__name__)


class CodexApiStore(Protocol):
    async def append_log_event(self, event: LogEvent) -> None: ...

    async def list_audit_logs(
        self,
        *,
        category: str | None = None,
        categories: list[str] | None = None,
        issue_id: str | None = None,
        task_id: str | None = None,
        since: str | None = None,
        until: str | None = None,
        q: str | None = None,
        cursor_created_at: str | None = None,
        cursor_id: str | None = None,
        limit: int = 200,
        descending: bool = True,
    ) -> list[AuditLog]: ...
    async def load_audit_log(self, audit_log_id: str) -> AuditLog | None: ...
    async def save_agent_call_trace(self, trace: AgentCallTrace) -> None: ...
    async def load_agent_call_trace(self, audit_log_id: str) -> AgentCallTrace | None: ...
    async def list_agent_call_traces(
        self,
        *,
        trace_id: str | None = None,
        task_id: str | None = None,
        execution_process_id: str | None = None,
        limit: int = 100,
    ) -> list[AgentCallTrace]: ...

    async def load_codex_issue(self, issue_id: str) -> CodexIssue | None: ...
    async def save_codex_issue(self, issue: CodexIssue) -> None: ...
    async def delete_codex_issue(self, issue_id: str) -> None: ...
    async def list_codex_issues(
        self,
        session_id: str | None = None,
        project_id: str | None = None,
    ) -> list[JsonObject]: ...

    async def load_codex_task(self, task_id: str) -> CodexTask | None: ...
    async def save_codex_task(self, task: CodexTask) -> None: ...
    async def delete_codex_task(self, task_id: str) -> None: ...
    async def list_codex_tasks(
        self,
        session_id: str | None = None,
        issue_id: str | None = None,
        project_id: str | None = None,
    ) -> list[JsonObject]: ...

    async def load_codex_session(self, session_id: str) -> CodexSession | None: ...
    async def load_codex_workspace(self, workspace_id: str) -> CodexWorkspace | None: ...
    async def save_codex_workspace(self, workspace: CodexWorkspace) -> None: ...
    async def delete_codex_session(self, session_id: str) -> None: ...
    async def delete_codex_workspace(self, workspace_id: str) -> None: ...
    async def list_codex_sessions(
        self,
        project_id: str | None = None,
    ) -> list[JsonObject]: ...
    async def list_codex_workspaces(
        self,
        project_id: str | None = None,
    ) -> list[JsonObject]: ...

    async def list_agent_messages(self, issue_id: str) -> list[AgentMessage]: ...
    async def list_agents(
        self,
        workspace_id: str | None = None,
        role_key: str | None = None,
    ) -> list[Agent]: ...
    async def load_workflow_graph_for_issue(self, issue_id: str) -> WorkflowGraph | None: ...
    async def save_conductor_task(self, task: ConductorTask) -> None: ...
    async def save_project_conductor_state(self, state: ProjectConductorState) -> bool: ...

    async def save_codex_task_message(self, message: CodexTaskMessage) -> None: ...
    async def list_codex_task_messages(
        self,
        task_id: str,
        execution_process_id: str | None = None,
    ) -> list[CodexTaskMessage]: ...
    async def load_log_events(
        self,
        session_id: str,
        task_id: str | None = None,
        execution_process_id: str | None = None,
        limit: int = 1000,
        reverse: bool = False,
    ) -> list[LogEvent]: ...

    async def load_execution_process(self, process_id: str) -> ExecutionProcess | None: ...
    async def list_execution_processes(
        self,
        session_id: str | None = None,
        task_id: str | None = None,
    ) -> list[ExecutionProcess]: ...
    async def update_execution_process_status(
        self,
        process_id: str,
        status: str,
        exit_code: int | None = None,
        completed_at: datetime | None = None,
    ) -> None: ...

    async def load_project(self, project_id: str) -> Project | None: ...
    async def list_projects(self) -> list[Project]: ...
    async def load_project_env_vars(
        self, project_id: str
    ) -> list["ProjectEnvVar"]: ...
    async def load_project_env_var(
        self, project_id: str, name: str
    ) -> "ProjectEnvVar | None": ...
    async def list_project_startup_services(
        self, project_id: str
    ) -> list[ProjectStartupService]: ...
    async def save_project_env_var(
        self,
        project_id: str,
        name: str,
        value: str,
        *,
        secret: bool = False,
        source: str = "",
    ) -> None: ...
    async def delete_project_env_var(
        self, project_id: str, name: str
    ) -> None: ...
    async def append_project_audit(
        self,
        *,
        project_id: str | None,
        issue_id: str | None,
        event: str,
        sha: str | None = None,
        base_branch: str | None = None,
    ) -> None: ...
    async def list_project_audit(
        self,
        project_id: str,
        *,
        limit: int = 50,
        since: str | None = None,
    ) -> list[JsonObject]: ...

    async def list_help_requests(
        self,
        *,
        parent_task_id: str | None = None,
        child_task_id: str | None = None,
    ) -> list[HelpRequest]: ...
    async def list_artifacts(self, issue_id: str) -> list[JsonObject]: ...
    async def save_artifact(self, artifact: JsonObject) -> None: ...

    async def load_runtime_catalog(self) -> RuntimeCatalog | None: ...
    async def save_runtime_catalog(self, catalog: RuntimeCatalog) -> None: ...

    async def list_self_improvement_proposals(
        self,
        project_id: str | None = None,
        issue_id: str | None = None,
        status: str | None = None,
        limit: int | None = None,
    ) -> list[SelfImprovementProposal]: ...
    async def load_self_improvement_proposal(
        self,
        proposal_id: str,
    ) -> SelfImprovementProposal | None: ...
    async def update_self_improvement_proposal_status(
        self,
        proposal_id: str,
        status: str,
    ) -> SelfImprovementProposal | None: ...
    async def save_self_improvement_application_event(
        self,
        event: SelfImprovementApplicationEvent,
    ) -> None: ...
    async def list_self_improvement_application_events(
        self,
        project_id: str | None = None,
        proposal_id: str | None = None,
        limit: int | None = None,
    ) -> list[SelfImprovementApplicationEvent]: ...


class AgentWorkflowApiStore(CodexApiStore, Protocol):
    async def load_agent(self, agent_id: str) -> Agent | None: ...

    async def save_agent(self, agent: Agent) -> None: ...

    async def delete_agent(self, agent_id: str) -> bool: ...

    async def load_workflow_graph(self, graph_id: str) -> WorkflowGraph | None: ...

    async def save_workflow_graph(
        self,
        graph: WorkflowGraph,
        nodes: list[WorkflowNode] | None = None,
        edges: list[WorkflowEdge] | None = None,
    ) -> None: ...

    async def list_pending_replans(self, graph_id: str) -> list[GraphReplanPending]: ...

    async def resolve_replan(self, replan_id: str, status: str) -> bool: ...


codex_store: CodexApiStore | None = cast("CodexApiStore | None", _bootstrap_codex_store)


class PipelineStagePayload(TypedDict):
    role: str
    label: str
    status: str
    task_id: str | None
    started_at: str | None
    completed_at: str | None
    duration_seconds: int | None
    summary: str | None
    foot: str | None


class PipelineStagesResponse(TypedDict):
    issue_id: str
    stages: list[PipelineStagePayload]
    started_at: str | None
    completed_at: str | None
    total_duration_seconds: int | None


class IssueOrchestrationPolicyResponse(TypedDict):
    issue_id: str
    recommendation: str
    batch_allowed: bool
    signals: list[str]
    guidance: list[str]


class IssueActivityEvent(TypedDict, total=False):
    type: str
    timestamp: str
    title: str | None
    issue_id: str
    task_id: str | None
    role: str | None


class IssueActivityResponse(TypedDict):
    issue_id: str
    events: list[IssueActivityEvent]


class GraphStatsTokens(TypedDict):
    input: int
    output: int


class GraphStatsNode(TypedDict):
    role_key: str
    status: str
    task_id: str | None
    duration_seconds: int | None
    tokens: GraphStatsTokens | None
    est_cost_usd: float


class GraphStatsConductor(TypedDict):
    role_key: str


class GraphStatsResponse(TypedDict):
    issue_id: str
    nodes: dict[str, GraphStatsNode]
    conductor: GraphStatsConductor


class LoadCodexWorkspaceFn(Protocol):
    def __call__(self, workspace_id: str) -> Awaitable[CodexWorkspace | None]: ...


class SaveCodexWorkspaceFn(Protocol):
    def __call__(self, workspace: CodexWorkspace) -> Awaitable[None]: ...

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


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _encode_audit_cursor(created_at: str, row_id: str) -> str:
    payload = json.dumps({"created_at": created_at, "id": row_id}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(payload).decode()


def _decode_audit_cursor(cursor: str | None) -> tuple[str | None, str | None]:
    if not cursor:
        return None, None
    try:
        raw = base64.urlsafe_b64decode(cursor.encode())
        parsed = json.loads(raw.decode())
    except Exception:
        return None, None
    if not isinstance(parsed, dict):
        return None, None
    created_at = parsed.get("created_at")
    row_id = parsed.get("id")
    if isinstance(created_at, str) and isinstance(row_id, str):
        return created_at, row_id
    return None, None


def _model_json_object(model: BaseModel) -> JsonObject:
    return _json_object(model.model_dump(mode="json"))


def _flatten_audit_categories(values: list[str]) -> list[str]:
    categories: list[str] = []
    for value in values:
        for part in value.split(","):
            part = part.strip()
            if part:
                categories.append(part)
    return categories


def _audit_payload_object(payload_json: str | None) -> JsonObject:
    if not payload_json:
        return {}
    try:
        parsed = json.loads(payload_json)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _audit_role_label(role: str | None) -> str | None:
    if not role:
        return None
    labels = {
        "architect": "Architect",
        "conductor": "Conductor",
        "engineer": "Engineer",
        "operations": "Operations Engineer",
        "product_manager": "Product Manager",
        "qa": "QA",
        "system": "System",
        "system_planner": "System Planner",
    }
    return labels.get(role, role.replace("_", " ").title())


def _audit_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _audit_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _audit_payload_role(payload: JsonObject, task_roles: Mapping[str, str]) -> str | None:
    role = _audit_str(payload.get("role"))
    if role:
        return role
    input_obj = payload.get("input")
    if isinstance(input_obj, dict):
        role = _audit_str(input_obj.get("role"))
        if role:
            return role
        task_id = _audit_str(input_obj.get("task_id"))
        if task_id and task_id in task_roles:
            return task_roles[task_id]
    result_obj = payload.get("result")
    if isinstance(result_obj, dict):
        role = _audit_str(result_obj.get("role"))
        if role:
            return role
        task_id = _audit_str(result_obj.get("task_id"))
        if task_id and task_id in task_roles:
            return task_roles[task_id]
    return None


def _audit_payload_task_id(payload: JsonObject) -> str | None:
    for key in ("task_id", "child_task_id", "parent_task_id"):
        task_id = _audit_str(payload.get(key))
        if task_id:
            return task_id
    for key in ("input", "result"):
        value = payload.get(key)
        if isinstance(value, dict):
            for task_key in ("task_id", "child_task_id", "parent_task_id"):
                task_id = _audit_str(value.get(task_key))
                if task_id:
                    return task_id
    return None


def _audit_call_name(entry: AuditLog, payload: JsonObject) -> str | None:
    for key in ("name", "tool", "command", "cmd", "type", "model"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
        if key in {"command", "cmd"} and isinstance(value, list):
            return " ".join(str(part) for part in value)
    if entry.category in {"git_command", "command_exec"}:
        argv = payload.get("argv")
        if isinstance(argv, list):
            return " ".join(str(part) for part in argv)
        command = payload.get("command")
        if isinstance(command, str):
            return command
    return entry.actor or entry.category


def _audit_call_input(entry: AuditLog, payload: JsonObject) -> object:
    if entry.category == "git_command":
        return {"argv": payload.get("argv"), "cwd": payload.get("cwd")}
    if entry.category == "command_exec":
        return {"command": payload.get("command"), "cwd": payload.get("cwd")}
    if entry.category == "tool_use":
        return payload.get("input")
    if entry.category == "llm_call":
        return payload
    return None


def _audit_call_output(entry: AuditLog, payload: JsonObject) -> object:
    if entry.category in {"git_command", "command_exec"}:
        return {
            "exit_code": payload.get("exit_code"),
            "stdout": payload.get("stdout"),
            "stderr": payload.get("stderr"),
            "duration_ms": entry.duration_ms,
            "refused": payload.get("refused"),
        }
    if entry.category == "tool_result":
        return payload.get("result")
    if entry.category == "llm_return":
        return payload.get("content") or payload.get("message") or payload
    if entry.category == "agent_finalize":
        return payload
    return None


def _audit_call_summary(entry: AuditLog, payload: JsonObject, call_name: str | None) -> str:
    if entry.error:
        return entry.error
    for key in ("summary", "message", "content"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value[:500]
    if entry.category in {"git_command", "command_exec"} and call_name:
        return call_name
    return call_name or entry.actor or entry.category


def _derive_audit_call_metadata(
    entry: AuditLog,
    payload: JsonObject,
    task_metadata: Mapping[str, JsonObject],
) -> JsonObject:
    payload_task_id = _audit_payload_task_id(payload)
    role = entry.task_id and _audit_str(task_metadata.get(entry.task_id, {}).get("role"))
    if role is None and payload_task_id:
        role = _audit_str(task_metadata.get(payload_task_id, {}).get("role"))
    if role is None:
        task_roles = {
            task_id: role
            for task_id, metadata in task_metadata.items()
            if (role := _audit_str(metadata.get("role"))) is not None
        }
        role = _audit_payload_role(payload, task_roles)
    if role is None and entry.actor == "auto_plan":
        role = "system_planner"
    if role is None and entry.actor == "operations_engineer":
        role = "operations"
    if role is None and entry.conductor_task_id:
        role = "conductor"
    if role is None and entry.category in {"git_command", "command_exec", "event"}:
        role = "system"
    operation_task_id = entry.task_id or payload_task_id
    task_title = (
        _audit_str(task_metadata.get(operation_task_id, {}).get("title"))
        if operation_task_id
        else None
    )
    call_name = _audit_call_name(entry, payload)
    return {
        "role": role,
        "role_label": _audit_role_label(role),
        "operation_task_id": operation_task_id,
        "task_title": task_title,
        "turn_index": _audit_int(payload.get("turn_index")),
        "sub_index": _audit_int(payload.get("sub_index")),
        "call_name": call_name,
        "call_input": _audit_call_input(entry, payload),
        "call_output": _audit_call_output(entry, payload),
        "call_summary": _audit_call_summary(entry, payload, call_name),
    }


async def _load_audit_task_metadata(rows: list[AuditLog], payloads: Mapping[str, JsonObject]) -> dict[str, JsonObject]:
    task_ids: set[str] = set()
    for row in rows:
        if row.task_id:
            task_ids.add(row.task_id)
        payload_task_id = _audit_payload_task_id(payloads.get(row.id, {}))
        if payload_task_id:
            task_ids.add(payload_task_id)
        payload = payloads.get(row.id, {})
        for key in ("input", "result"):
            value = payload.get(key)
            if isinstance(value, dict):
                task_id = _audit_str(value.get("task_id"))
                if task_id:
                    task_ids.add(task_id)
    if not task_ids or codex_store is None:
        return {}
    metadata: dict[str, JsonObject] = {}
    for task_id in task_ids:
        loaded_task = await codex_store.load_codex_task(task_id)
        if loaded_task is not None:
            metadata[task_id] = {"role": loaded_task.role, "title": loaded_task.title}
    if len(metadata) == len(task_ids):
        return metadata
    tasks = await codex_store.list_codex_tasks()
    for task_row in tasks:
        task_id = _audit_str(task_row.get("id"))
        if task_id in task_ids and task_id not in metadata:
            metadata[task_id] = {
                "role": _audit_str(task_row.get("role")),
                "title": _audit_str(task_row.get("title")),
            }
    return metadata


def _serialize_audit_log(
    entry: AuditLog,
    payload: JsonObject | None = None,
    task_metadata: Mapping[str, JsonObject] | None = None,
) -> JsonObject:
    payload_obj = payload if payload is not None else _audit_payload_object(entry.payload_json)
    result: JsonObject = {
        "id": entry.id,
        "category": entry.category,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
        "actor": entry.actor,
        "issue_id": entry.issue_id,
        "task_id": entry.task_id,
        "conductor_task_id": entry.conductor_task_id,
        "execution_process_id": entry.execution_process_id,
        "correlation_id": entry.correlation_id,
        "trace_id": entry.trace_id,
        "span_id": entry.span_id,
        "parent_span_id": entry.parent_span_id,
        "status": entry.status,
        "duration_ms": entry.duration_ms,
        "payload_json": entry.payload_json,
        "error": entry.error,
    }
    result.update(_derive_audit_call_metadata(entry, payload_obj, task_metadata or {}))
    return result


def _trace_json_value(raw: str | None) -> object | None:
    if raw is None:
        return None
    try:
        parsed: object = json.loads(raw)
        return parsed
    except json.JSONDecodeError:
        return raw


def _serialize_agent_call_trace(trace: AgentCallTrace) -> JsonObject:
    metadata = _safe_json_object(trace.metadata_json)
    return {
        "available": True,
        "id": trace.id,
        "audit_log_id": trace.audit_log_id,
        "trace_id": trace.trace_id,
        "span_id": trace.span_id,
        "parent_span_id": trace.parent_span_id,
        "issue_id": trace.issue_id,
        "task_id": trace.task_id,
        "execution_process_id": trace.execution_process_id,
        "kind": trace.kind,
        "title": trace.title,
        "request": _trace_json_value(trace.request_json),
        "response": _trace_json_value(trace.response_json),
        "request_preview": trace.request_preview,
        "response_preview": trace.response_preview,
        "metadata": metadata,
        "is_truncated": trace.is_truncated,
        "created_at": trace.created_at.isoformat() if trace.created_at else None,
    }


async def _runtime_trace_from_audit(entry: AuditLog) -> JsonObject | None:
    payload = _audit_payload_object(entry.payload_json)
    event_type = _audit_str(payload.get("type")) or (
        entry.actor if entry.category == "event" else None
    )
    task = None
    messages = []
    logs = []
    if entry.task_id:
        store = _require_codex_store()
        task = await store.load_codex_task(entry.task_id)
        if task is not None:
            messages = await store.list_codex_task_messages(
                entry.task_id,
                execution_process_id=entry.execution_process_id,
            )
            logs = await store.load_log_events(
                task.session_id,
                task_id=entry.task_id,
                execution_process_id=entry.execution_process_id,
                limit=500,
                reverse=False,
            )
    if entry.category == "cli_spawn":
        return {
            "available": True,
            "id": f"audit-row-{entry.id}",
            "audit_log_id": entry.id,
            "trace_id": entry.trace_id,
            "span_id": entry.span_id,
            "parent_span_id": entry.parent_span_id,
            "issue_id": entry.issue_id,
            "task_id": entry.task_id,
            "execution_process_id": entry.execution_process_id,
            "kind": "cli_spawn",
            "title": "CLI process started",
            "request": {
                "argv": payload.get("argv"),
                "cwd": payload.get("cwd"),
                "executor": payload.get("executor"),
                "provider": payload.get("provider"),
                "model": payload.get("model"),
                "resume_session_id": payload.get("resume_session_id"),
                "task": {
                    "id": task.id,
                    "title": task.title,
                    "role": task.role,
                    "prompt": task.prompt,
                    "executor": task.executor,
                    "provider": task.provider,
                    "model": task.model,
                }
                if task is not None
                else None,
            },
            "response": {
                "pid": payload.get("pid"),
                "status": entry.status,
                "execution_process_id": entry.execution_process_id,
                "messages": [
                    {
                        "id": message.id,
                        "role": message.role,
                        "content": message.content,
                        "created_at": message.created_at.isoformat() if message.created_at else None,
                    }
                    for message in messages
                ],
                "logs": [
                    {
                        "id": event.id,
                        "stream": event.stream,
                        "content": event.content,
                        "created_at": event.created_at.isoformat() if event.created_at else None,
                    }
                    for event in logs
                ],
            },
            "request_preview": _audit_str(payload.get("executor")) or entry.actor,
            "response_preview": f"{len(messages)} messages · {len(logs)} logs",
            "metadata": {
                "source": "audit_log+runtime_logs",
                "message_count": len(messages),
                "log_count": len(logs),
                "note": "CLI launch details plus reconstructed Claude Code runtime messages and log events.",
            },
            "is_truncated": False,
            "created_at": entry.created_at.isoformat() if entry.created_at else None,
        }
    if event_type == "project_script_updated":
        project_id = _agent_timeline_payload_str(payload, "project_id")
        task_id = _agent_timeline_payload_str(payload, "task_id") or entry.task_id
        execution_process_id = (
            _agent_timeline_payload_str(payload, "execution_process_id")
            or entry.execution_process_id
        )
        setup_script = _agent_timeline_payload_str(payload, "setup_script")
        run_command = _agent_timeline_payload_str(payload, "run_command")
        return {
            "available": True,
            "id": f"audit-row-{entry.id}",
            "audit_log_id": entry.id,
            "trace_id": entry.trace_id,
            "span_id": entry.span_id,
            "parent_span_id": entry.parent_span_id,
            "issue_id": entry.issue_id,
            "task_id": entry.task_id,
            "execution_process_id": entry.execution_process_id,
            "kind": "project_script_updated",
            "title": "Project startup scripts updated",
            "request": {
                "project_id": project_id,
                "task_id": task_id,
                "execution_process_id": execution_process_id,
            },
            "response": {
                "setup_script": setup_script,
                "run_command": run_command,
            },
            "request_preview": project_id,
            "response_preview": run_command or setup_script,
            "metadata": {
                "source": "audit_log",
                "note": "This is the business-result event for the Operations Engineer script update.",
            },
            "is_truncated": False,
            "created_at": entry.created_at.isoformat() if entry.created_at else None,
        }
    if not entry.task_id:
        return None
    if task is None:
        return None
    if not messages and not logs:
        return None
    request_payload = {
        "task_id": task.id,
        "title": task.title,
        "role": task.role,
        "prompt": task.prompt,
        "executor": task.executor,
        "provider": task.provider,
        "model": task.model,
    }
    response_payload = {
        "messages": [
            {
                "id": message.id,
                "role": message.role,
                "content": message.content,
                "created_at": message.created_at.isoformat() if message.created_at else None,
            }
            for message in messages
        ],
        "logs": [
            {
                "id": event.id,
                "stream": event.stream,
                "content": event.content,
                "created_at": event.created_at.isoformat() if event.created_at else None,
            }
            for event in logs
        ],
    }
    return {
        "available": True,
        "id": f"runtime-{entry.id}",
        "audit_log_id": entry.id,
        "trace_id": entry.trace_id,
        "span_id": entry.span_id,
        "parent_span_id": entry.parent_span_id,
        "issue_id": entry.issue_id,
        "task_id": entry.task_id,
        "execution_process_id": entry.execution_process_id,
        "kind": "runtime_logs",
        "title": task.title,
        "request": request_payload,
        "response": response_payload,
        "request_preview": task.prompt[:4000] if task.prompt else None,
        "response_preview": None,
        "metadata": {
            "source": "log_events",
            "message_count": len(messages),
            "log_count": len(logs),
            "note": "CLI runtimes do not expose raw provider HTTP requests; this is reconstructed from persisted task messages and runtime log events.",
        },
        "is_truncated": False,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
    }


def _audit_cursor_from_entry(entry: AuditLog) -> str | None:
    if entry.created_at is None:
        return None
    return _encode_audit_cursor(entry.created_at.isoformat(), entry.id)


def _audit_chain_key(item: JsonObject) -> str:
    role = _audit_str(item.get("role")) or "unknown"
    conductor_task_id = _audit_str(item.get("conductor_task_id"))
    turn_index = item.get("turn_index")
    operation_task_id = _audit_str(item.get("operation_task_id")) or _audit_str(item.get("task_id"))
    if operation_task_id is not None:
        return f"task:{operation_task_id}:{role}"
    if conductor_task_id is not None:
        call_name = _audit_str(item.get("call_name")) or _audit_str(item.get("actor")) or item.get("category")
        return f"conductor:{conductor_task_id}:{turn_index}:{role}:{call_name}"
    return f"entry:{item.get('id')}"


def _audit_chain_title(item: JsonObject) -> str:
    role_label = _audit_str(item.get("role_label")) or _audit_str(item.get("role")) or "Agent"
    call_name = _audit_str(item.get("call_name"))
    if call_name and call_name not in {role_label, _audit_str(item.get("actor"))}:
        return f"{role_label} · {call_name}"
    return role_label


def _audit_chain_summary(entries: list[JsonObject]) -> str:
    for item in entries:
        summary = _audit_str(item.get("call_summary"))
        if summary:
            return summary
    return _audit_str(entries[0].get("call_name")) or _audit_str(entries[0].get("role_label")) or "Agent operation"


def _audit_chain_status(entries: list[JsonObject]) -> str | None:
    if any(item.get("error") or item.get("status") == "error" for item in entries):
        return "error"
    for item in entries:
        status = _audit_str(item.get("status"))
        if status:
            return status
    return None


def _audit_chain_operation(key: str, entries: list[JsonObject]) -> JsonObject:
    ordered = sorted(
        entries,
        key=lambda item: (
            item.get("turn_index") if isinstance(item.get("turn_index"), int) else 10**9,
            item.get("sub_index") if isinstance(item.get("sub_index"), int) else 10**9,
            _audit_str(item.get("created_at")) or "",
            _audit_str(item.get("id")) or "",
        ),
    )
    latest = max((_audit_str(item.get("created_at")) or "" for item in ordered), default="")
    first = min((_audit_str(item.get("created_at")) or "" for item in ordered), default="")
    duration_values: list[int] = []
    for item in ordered:
        duration_ms = item.get("duration_ms")
        if isinstance(duration_ms, int) and not isinstance(duration_ms, bool):
            duration_values.append(duration_ms)
    return {
        "id": key,
        "role": ordered[0].get("role"),
        "role_label": ordered[0].get("role_label"),
        "title": _audit_chain_title(ordered[0]),
        "summary": _audit_chain_summary(ordered),
        "status": _audit_chain_status(ordered),
        "issue_id": ordered[0].get("issue_id"),
        "task_id": ordered[0].get("task_id"),
        "operation_task_id": ordered[0].get("operation_task_id"),
        "task_title": ordered[0].get("task_title"),
        "conductor_task_id": ordered[0].get("conductor_task_id"),
        "turn_index": ordered[0].get("turn_index"),
        "started_at": first or None,
        "last_at": latest or None,
        "duration_ms": sum(duration_values) if duration_values else None,
        "entry_count": len(ordered),
        "entries": ordered,
    }


_AGENT_TIMELINE_EVENT_TYPES = frozenset({"project_script_updated"})
_AGENT_TIMELINE_CATEGORIES = frozenset(
    {
        "agent_finalize",
        "cli_spawn",
        "command_exec",
        "git_command",
        "tool_result",
        "tool_use",
    }
)
_AGENT_TIMELINE_STATUS_ORDER = {
    "pending": 1,
    "queued": 1,
    "starting": 1,
    "running": 2,
    "responding": 3,
    "ok": 4,
    "success": 5,
    "done": 5,
    "completed": 5,
    "failed": 6,
    "error": 6,
    "cancelled": 6,
    "canceled": 6,
    "killed": 6,
    "timeout": 6,
    "protocol_error": 6,
    "timed_out": 6,
}


def _agent_timeline_payload(item: JsonObject) -> JsonObject:
    raw = _audit_str(item.get("payload_json"))
    return _audit_payload_object(raw)


def _agent_timeline_preview_payload(payload: JsonObject) -> JsonObject:
    preview = _audit_str(payload.get("payload_preview"))
    if not preview:
        return {}
    try:
        parsed = ast.literal_eval(preview)
    except (SyntaxError, ValueError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(key): value for key, value in parsed.items()}


def _agent_timeline_payload_str(payload: JsonObject, key: str) -> str | None:
    value = _audit_str(payload.get(key))
    if value:
        return value
    return _audit_str(_agent_timeline_preview_payload(payload).get(key))


def _agent_timeline_event_type(item: JsonObject, payload: JsonObject) -> str | None:
    return _agent_timeline_payload_str(payload, "type") or (
        _audit_str(item.get("actor")) if item.get("category") == "event" else None
    )


def _agent_timeline_is_node(item: JsonObject, payload: JsonObject) -> bool:
    category = _audit_str(item.get("category"))
    if category in _AGENT_TIMELINE_CATEGORIES:
        return True
    if category == "event":
        return _agent_timeline_event_type(item, payload) in _AGENT_TIMELINE_EVENT_TYPES
    return False


def _agent_timeline_status_key(
    item: JsonObject,
    payload: JsonObject,
) -> tuple[str | None, str | None]:
    task_id = (
        _audit_str(item.get("operation_task_id"))
        or _audit_str(item.get("task_id"))
        or _agent_timeline_payload_str(payload, "task_id")
    )
    execution_id = (
        _audit_str(item.get("execution_process_id"))
        or _agent_timeline_payload_str(payload, "execution_process_id")
        or _audit_str(item.get("trace_id"))
        or _agent_timeline_payload_str(payload, "trace_id")
    )
    return task_id, execution_id


def _agent_timeline_merge_status(current: str | None, next_status: str | None) -> str | None:
    if not next_status:
        return current
    if current is None:
        return next_status
    current_rank = _AGENT_TIMELINE_STATUS_ORDER.get(current.lower(), 0)
    next_rank = _AGENT_TIMELINE_STATUS_ORDER.get(next_status.lower(), 0)
    return next_status if next_rank > current_rank else current


def _agent_timeline_collect_status(
    status_by_key: dict[tuple[str | None, str | None], str],
    item: JsonObject,
    payload: JsonObject,
) -> None:
    if _agent_timeline_event_type(item, payload) != "task_status":
        return
    status = _agent_timeline_payload_str(payload, "status") or _audit_str(item.get("status"))
    key = _agent_timeline_status_key(item, payload)
    if not key[0] and not key[1]:
        return
    merged = _agent_timeline_merge_status(status_by_key.get(key), status)
    if merged:
        status_by_key[key] = merged


def _agent_timeline_resolved_status(
    item: JsonObject,
    payload: JsonObject,
    status_by_key: Mapping[tuple[str | None, str | None], str],
) -> str | None:
    key = _agent_timeline_status_key(item, payload)
    return _agent_timeline_merge_status(status_by_key.get(key), _audit_str(item.get("status")))


def _agent_timeline_title(item: JsonObject, payload: JsonObject) -> str:
    category = _audit_str(item.get("category"))
    event_type = _agent_timeline_event_type(item, payload)
    if category == "cli_spawn":
        executor = (
            _agent_timeline_payload_str(payload, "executor")
            or _audit_str(item.get("actor"))
            or "CLI"
        )
        return f"{executor} CLI"
    if event_type == "project_script_updated":
        return "Project startup scripts updated"
    call_name = _audit_str(item.get("call_name"))
    return call_name or category or "agent_operation"


def _agent_timeline_summary(item: JsonObject, payload: JsonObject) -> str:
    category = _audit_str(item.get("category"))
    event_type = _agent_timeline_event_type(item, payload)
    if category == "cli_spawn":
        parts = [
            _agent_timeline_payload_str(payload, "model"),
            _agent_timeline_payload_str(payload, "cwd"),
        ]
        return " · ".join(part for part in parts if part) or "CLI process started"
    if event_type == "project_script_updated":
        run_command = _agent_timeline_payload_str(payload, "run_command")
        setup_script = _agent_timeline_payload_str(payload, "setup_script")
        if run_command:
            return f"run_command: {run_command}"
        if setup_script:
            return f"setup_script: {setup_script}"
        return "Project startup scripts updated"
    return (
        _audit_str(item.get("call_summary"))
        or _audit_str(item.get("call_name"))
        or _audit_str(item.get("actor"))
        or category
        or "Agent operation"
    )


def _agent_timeline_result(item: JsonObject, payload: JsonObject) -> JsonObject | None:
    event_type = _agent_timeline_event_type(item, payload)
    if event_type == "project_script_updated":
        return {
            "setup_script": _agent_timeline_payload_str(payload, "setup_script"),
            "run_command": _agent_timeline_payload_str(payload, "run_command"),
        }
    if item.get("category") == "cli_spawn":
        return {
            "executor": _agent_timeline_payload_str(payload, "executor"),
            "provider": _agent_timeline_payload_str(payload, "provider"),
            "model": _agent_timeline_payload_str(payload, "model"),
            "pid": payload.get("pid"),
            "cwd": _agent_timeline_payload_str(payload, "cwd"),
        }
    return None


def _agent_timeline_operation(
    item: JsonObject,
    payload: JsonObject,
    status_by_key: Mapping[tuple[str | None, str | None], str],
) -> JsonObject:
    started_at = _audit_str(item.get("created_at"))
    event_type = _agent_timeline_event_type(item, payload)
    category = _audit_str(item.get("category"))
    status_key = _agent_timeline_status_key(item, payload)
    status_source = "task_status" if status_by_key.get(status_key) is not None else "audit_row"
    execution_process_id = _audit_str(item.get("execution_process_id")) or _agent_timeline_payload_str(
        payload, "execution_process_id"
    )
    trace_id = (
        _audit_str(item.get("trace_id"))
        or _agent_timeline_payload_str(payload, "trace_id")
        or execution_process_id
    )
    span_id = _audit_str(item.get("span_id")) or _agent_timeline_payload_str(payload, "span_id")
    parent_span_id = _audit_str(item.get("parent_span_id")) or _agent_timeline_payload_str(
        payload, "parent_span_id"
    )
    return {
        "id": f"timeline:{item.get('id')}",
        "timeline_kind": event_type or category or "agent_operation",
        "event_type": event_type,
        "role": item.get("role") or _agent_timeline_payload_str(payload, "role"),
        "role_label": item.get("role_label"),
        "title": _agent_timeline_title(item, payload),
        "summary": _agent_timeline_summary(item, payload),
        "result": _agent_timeline_result(item, payload),
        "status": _agent_timeline_resolved_status(item, payload, status_by_key),
        # Debug metadata: tells maintainers whether status came from the
        # semantic node row itself or from a task_status span-state event.
        "status_source": status_source,
        "issue_id": item.get("issue_id"),
        "task_id": item.get("task_id"),
        "operation_task_id": item.get("operation_task_id"),
        "task_title": item.get("task_title"),
        "conductor_task_id": item.get("conductor_task_id"),
        "execution_process_id": execution_process_id,
        "trace_id": trace_id,
        "span_id": span_id,
        "parent_span_id": parent_span_id,
        "turn_index": item.get("turn_index"),
        "started_at": started_at,
        "last_at": started_at,
        "duration_ms": item.get("duration_ms"),
        "entry_count": 1,
        "entries": [item],
    }


def _agent_timeline_operation_task_id(operation: JsonObject) -> str | None:
    return _audit_str(operation.get("operation_task_id")) or _audit_str(operation.get("task_id"))


def _agent_timeline_operation_execution_id(operation: JsonObject) -> str | None:
    return _audit_str(operation.get("execution_process_id")) or _audit_str(operation.get("trace_id"))


def _agent_timeline_first_str(operations: list[JsonObject], key: str) -> str | None:
    for operation in operations:
        value = _audit_str(operation.get(key))
        if value:
            return value
    return None


def _agent_timeline_merged_result(operations: list[JsonObject]) -> JsonObject | None:
    merged: JsonObject = {}
    for operation in operations:
        result = operation.get("result")
        if not isinstance(result, dict):
            continue
        for key, value in result.items():
            if value is None or value == "":
                continue
            merged[str(key)] = value
    return merged or None


def _agent_timeline_execution_summary(result: JsonObject | None, operations: list[JsonObject]) -> str:
    if result is not None:
        run_command = _audit_str(result.get("run_command"))
        setup_script = _audit_str(result.get("setup_script"))
        if run_command:
            return f"run_command: {run_command}"
        if setup_script:
            return f"setup_script: {setup_script}"
    if len(operations) == 1:
        return _audit_str(operations[0].get("summary")) or "Agent operation"
    return f"{len(operations)} timeline steps"


def _agent_timeline_aggregate_group(key: str, operations: list[JsonObject]) -> JsonObject:
    ordered = sorted(
        operations,
        key=lambda operation: (
            _audit_str(operation.get("started_at")) or "",
            _audit_str(operation.get("id")) or "",
        ),
    )
    first_started = _audit_str(ordered[0].get("started_at"))
    last_at = _audit_str(ordered[-1].get("last_at")) or _audit_str(ordered[-1].get("started_at"))
    duration_values = [
        value for operation in ordered if isinstance((value := operation.get("duration_ms")), int)
    ]
    result = _agent_timeline_merged_result(ordered)
    status: str | None = None
    status_source = "audit_row"
    for operation in ordered:
        status = _agent_timeline_merge_status(status, _audit_str(operation.get("status")))
        if operation.get("status_source") == "task_status":
            status_source = "task_status"
    task_id = _agent_timeline_first_str(ordered, "operation_task_id") or _agent_timeline_first_str(
        ordered, "task_id"
    )
    execution_process_id = _agent_timeline_first_str(ordered, "execution_process_id")
    title = _agent_timeline_first_str(ordered, "task_title") or _audit_str(ordered[0].get("title"))
    entries = [
        entry
        for operation in ordered
        for entry in _json_object_list(operation.get("entries"))
    ]
    is_execution = bool(task_id)
    return {
        "id": f"timeline:{key}",
        "timeline_kind": "agent_execution" if is_execution else ordered[0].get("timeline_kind"),
        "event_type": None if len(ordered) > 1 else ordered[0].get("event_type"),
        "role": _agent_timeline_first_str(ordered, "role"),
        "role_label": _agent_timeline_first_str(ordered, "role_label"),
        "title": title or "Agent operation",
        "summary": _agent_timeline_execution_summary(result, ordered),
        "result": result,
        "status": status,
        "status_source": status_source,
        "issue_id": _agent_timeline_first_str(ordered, "issue_id"),
        "task_id": task_id,
        "operation_task_id": task_id,
        "task_title": _agent_timeline_first_str(ordered, "task_title"),
        "conductor_task_id": _agent_timeline_first_str(ordered, "conductor_task_id"),
        "execution_process_id": execution_process_id,
        "trace_id": _agent_timeline_first_str(ordered, "trace_id") or execution_process_id,
        "span_id": _agent_timeline_first_str(ordered, "span_id"),
        "parent_span_id": _agent_timeline_first_str(ordered, "parent_span_id"),
        "turn_index": ordered[0].get("turn_index"),
        "started_at": first_started,
        "last_at": last_at,
        "duration_ms": sum(duration_values) if duration_values else None,
        "entry_count": len(entries),
        "entries": entries,
    }


def _agent_timeline_aggregate_operations(operations: list[JsonObject]) -> list[JsonObject]:
    execution_ids_by_task: dict[str, set[str]] = {}
    for operation in operations:
        task_id = _agent_timeline_operation_task_id(operation)
        execution_id = _agent_timeline_operation_execution_id(operation)
        if task_id and execution_id:
            execution_ids_by_task.setdefault(task_id, set()).add(execution_id)
    single_execution_by_task = {
        task_id: next(iter(execution_ids))
        for task_id, execution_ids in execution_ids_by_task.items()
        if len(execution_ids) == 1
    }
    grouped: dict[str, list[JsonObject]] = {}
    for operation in operations:
        task_id = _agent_timeline_operation_task_id(operation)
        execution_id = _agent_timeline_operation_execution_id(operation)
        if task_id and execution_id:
            key = f"execution:{task_id}:{execution_id}"
        elif task_id and task_id in single_execution_by_task:
            key = f"execution:{task_id}:{single_execution_by_task[task_id]}"
        elif task_id:
            key = f"legacy-task:{task_id}"
        else:
            key = f"entry:{operation.get('id')}"
        grouped.setdefault(key, []).append(operation)
    return [_agent_timeline_aggregate_group(key, values) for key, values in grouped.items()]


def _agent_timeline_operation_status_key(operation: JsonObject) -> tuple[str | None, str | None]:
    task_id = _audit_str(operation.get("operation_task_id")) or _audit_str(operation.get("task_id"))
    execution_id = _audit_str(operation.get("execution_process_id")) or _audit_str(
        operation.get("trace_id")
    )
    return task_id, execution_id


async def _agent_timeline_statuses_for_operations(
    request: Request,
    operations: list[JsonObject],
) -> dict[tuple[str | None, str | None], str]:
    task_ids = {
        task_id
        for operation in operations
        if (task_id := _agent_timeline_operation_status_key(operation)[0]) is not None
    }
    if not task_ids or codex_store is None:
        return {}
    rows = await codex_store.list_audit_logs(
        categories=["event"],
        issue_id=request.query_params.get("issue_id"),
        task_id=request.query_params.get("task_id"),
        since=request.query_params.get("since"),
        until=request.query_params.get("until"),
        cursor_created_at=None,
        cursor_id=None,
        limit=1000,
        descending=True,
    )
    statuses: dict[tuple[str | None, str | None], str] = {}
    for row in rows:
        payload = _audit_payload_object(row.payload_json)
        event_type = _audit_str(payload.get("type")) or row.actor
        if event_type != "task_status":
            continue
        task_id = _agent_timeline_payload_str(payload, "task_id") or row.task_id
        if task_id not in task_ids:
            continue
        execution_id = (
            _agent_timeline_payload_str(payload, "execution_process_id")
            or row.execution_process_id
            or _agent_timeline_payload_str(payload, "trace_id")
            or row.trace_id
        )
        status = _agent_timeline_payload_str(payload, "status") or row.status
        key = (task_id, execution_id)
        merged = _agent_timeline_merge_status(statuses.get(key), status)
        if merged:
            statuses[key] = merged
    return statuses


def _agent_timeline_apply_nearby_statuses(
    operations: list[JsonObject],
    statuses: Mapping[tuple[str | None, str | None], str],
) -> None:
    for operation in operations:
        key = _agent_timeline_operation_status_key(operation)
        status = statuses.get(key)
        if status is None and key[1] is None:
            status = statuses.get((key[0], None))
        if status is None:
            continue
        operation["status"] = _agent_timeline_merge_status(_audit_str(operation.get("status")), status)
        operation["status_source"] = "task_status"


@router.get("/codex/audit-log")
async def get_codex_audit_log(request: Request) -> object:
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    try:
        raw_limit = int(request.query_params.get("limit", "200"))
    except ValueError:
        raw_limit = 200
    limit = max(1, min(raw_limit, 200))
    cursor_created_at, cursor_id = _decode_audit_cursor(request.query_params.get("cursor"))
    rows = await codex_store.list_audit_logs(
        categories=_flatten_audit_categories(request.query_params.getlist("category")),
        issue_id=request.query_params.get("issue_id"),
        task_id=request.query_params.get("task_id"),
        since=request.query_params.get("since"),
        until=request.query_params.get("until"),
        q=request.query_params.get("q"),
        cursor_created_at=cursor_created_at,
        cursor_id=cursor_id,
        limit=limit + 1,
        descending=True,
    )
    page = rows[:limit]
    next_cursor = None
    if len(rows) > limit and page:
        last = page[-1]
        next_cursor = _encode_audit_cursor(last.created_at.isoformat() if last.created_at else "", last.id)
    payloads = {entry.id: _audit_payload_object(entry.payload_json) for entry in page}
    task_metadata = await _load_audit_task_metadata(page, payloads)
    return {
        "items": [_serialize_audit_log(row, payloads[row.id], task_metadata) for row in page],
        "next_cursor": next_cursor,
    }


@router.get("/codex/audit-log/chains")
async def get_codex_audit_log_chains(request: Request) -> object:
    """Legacy audit-row grouping kept for compatibility.

    Product UI should prefer `/codex/agent-timeline`, which filters raw audit
    evidence into semantic agent operations instead of treating every event
    (notably task_status) as a visible chain node.
    """
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    try:
        raw_limit = int(request.query_params.get("limit", "30"))
    except ValueError:
        raw_limit = 30
    limit = max(1, min(raw_limit, 50))
    cursor_created_at, cursor_id = _decode_audit_cursor(request.query_params.get("cursor"))
    grouped: dict[str, list[JsonObject]] = {}
    group_order: list[str] = []
    next_cursor: str | None = None
    scanned_pages = 0
    last_included: AuditLog | None = None
    consumed_page: AuditLog | None = None
    stopped_at_limit = False

    while not stopped_at_limit and scanned_pages < 8:
        scanned_pages += 1
        rows = await codex_store.list_audit_logs(
            categories=_flatten_audit_categories(request.query_params.getlist("category")),
            issue_id=request.query_params.get("issue_id"),
            task_id=request.query_params.get("task_id"),
            since=request.query_params.get("since"),
            until=request.query_params.get("until"),
            q=request.query_params.get("q"),
            cursor_created_at=cursor_created_at,
            cursor_id=cursor_id,
            limit=201,
            descending=True,
        )
        page = rows[:200]
        if not page:
            break
        consumed_page = page[-1]
        payloads = {entry.id: _audit_payload_object(entry.payload_json) for entry in page}
        task_metadata = await _load_audit_task_metadata(page, payloads)
        for row in page:
            item = _serialize_audit_log(row, payloads[row.id], task_metadata)
            if item.get("role") == "system":
                continue
            key = _audit_chain_key(item)
            if key not in grouped:
                if len(grouped) >= limit:
                    stopped_at_limit = True
                    break
                grouped[key] = []
                group_order.append(key)
            grouped.setdefault(key, []).append(item)
            last_included = row
        if stopped_at_limit:
            break
        if len(rows) <= 200:
            consumed_page = None
            break
        cursor_created_at = page[-1].created_at.isoformat() if page[-1].created_at else None
        cursor_id = page[-1].id

    if stopped_at_limit and last_included is not None:
        next_cursor = _audit_cursor_from_entry(last_included)
    elif consumed_page is not None:
        next_cursor = _audit_cursor_from_entry(consumed_page)
    operations = [_audit_chain_operation(key, grouped[key]) for key in group_order]
    operations.sort(
        key=lambda item: (
            _audit_str(item.get("last_at")) or "",
            _audit_str(item.get("id")) or "",
        ),
        reverse=True,
    )
    return {
        "items": operations[:limit],
        "next_cursor": next_cursor,
    }


@router.get("/codex/agent-timeline")
async def get_codex_agent_timeline(request: Request) -> object:
    """Semantic Agent Timeline projection built from audit evidence.

    Raw audit rows remain the evidence layer. This endpoint projects them into
    user-facing agent operations and consumes task_status events only as span
    state, not as timeline nodes.
    """
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    try:
        raw_limit = int(request.query_params.get("limit", "30"))
    except ValueError:
        raw_limit = 30
    limit = max(1, min(raw_limit, 50))
    cursor_created_at, cursor_id = _decode_audit_cursor(request.query_params.get("cursor"))
    node_operations: list[JsonObject] = []
    status_by_key: dict[tuple[str | None, str | None], str] = {}
    next_cursor: str | None = None
    scanned_pages = 0
    last_included: AuditLog | None = None
    consumed_page: AuditLog | None = None
    stopped_at_limit = False

    while not stopped_at_limit and scanned_pages < 8:
        scanned_pages += 1
        rows = await codex_store.list_audit_logs(
            categories=_flatten_audit_categories(request.query_params.getlist("category")),
            issue_id=request.query_params.get("issue_id"),
            task_id=request.query_params.get("task_id"),
            since=request.query_params.get("since"),
            until=request.query_params.get("until"),
            q=request.query_params.get("q"),
            cursor_created_at=cursor_created_at,
            cursor_id=cursor_id,
            limit=201,
            descending=True,
        )
        page = rows[:200]
        if not page:
            break
        consumed_page = page[-1]
        payloads = {entry.id: _audit_payload_object(entry.payload_json) for entry in page}
        task_metadata = await _load_audit_task_metadata(page, payloads)
        serialized = [_serialize_audit_log(row, payloads[row.id], task_metadata) for row in page]
        timeline_payloads = [_agent_timeline_payload(item) for item in serialized]
        for item, payload in zip(serialized, timeline_payloads, strict=False):
            _agent_timeline_collect_status(status_by_key, item, payload)
        for row, item, payload in zip(page, serialized, timeline_payloads, strict=False):
            if item.get("role") == "system":
                continue
            if not _agent_timeline_is_node(item, payload):
                continue
            if len(node_operations) >= limit * 4:
                stopped_at_limit = True
                break
            node_operations.append(_agent_timeline_operation(item, payload, status_by_key))
            last_included = row
        if stopped_at_limit:
            break
        if len(rows) <= 200:
            consumed_page = None
            break
        cursor_created_at = page[-1].created_at.isoformat() if page[-1].created_at else None
        cursor_id = page[-1].id

    if stopped_at_limit and last_included is not None:
        next_cursor = _audit_cursor_from_entry(last_included)
    elif consumed_page is not None:
        next_cursor = _audit_cursor_from_entry(consumed_page)
    operations = _agent_timeline_aggregate_operations(node_operations)
    nearby_statuses = await _agent_timeline_statuses_for_operations(request, operations)
    _agent_timeline_apply_nearby_statuses(operations, nearby_statuses)
    return {
        "items": operations,
        "next_cursor": next_cursor,
    }


@router.get("/codex/audit-log/{audit_id}/trace")
async def get_codex_audit_log_trace(audit_id: str) -> object:
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    trace = await codex_store.load_agent_call_trace(audit_id)
    if trace is None:
        entry = await codex_store.load_audit_log(audit_id)
        if entry is not None:
            runtime_trace = await _runtime_trace_from_audit(entry)
            if runtime_trace is not None:
                return runtime_trace
        return {
            "available": False,
            "audit_log_id": audit_id,
            "reason": "trace_not_recorded",
        }
    return _serialize_agent_call_trace(trace)


@router.get("/codex/traces/{trace_id}")
async def get_codex_trace(trace_id: str) -> object:
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    traces = await codex_store.list_agent_call_traces(trace_id=trace_id, limit=100)
    if not traces:
        return {
            "available": False,
            "trace_id": trace_id,
            "reason": "trace_not_recorded",
            "items": [],
        }
    return {
        "available": True,
        "trace_id": trace_id,
        "items": [_serialize_agent_call_trace(trace) for trace in traces],
    }


@router.get("/codex/echo")
async def codex_echo(msg: str = "") -> object:
    return {"msg": msg, "length": len(msg), "ts": _utc_now_iso()}


@router.get("/codex/heartbeat")
async def codex_heartbeat() -> object:
    return {"status": "ok"}


@router.get("/codex/ready")
async def codex_ready() -> object:
    return {"ready": True}


@router.get("/skills/proxy")
async def skills_proxy(url: str) -> object:
    host = (urlparse(url).hostname or "").lower()
    if host in {"localhost", "127.0.0.1", "::1"} or host.startswith("127."):
        raise HTTPException(status_code=400, detail="URL is not allowed")
    raise HTTPException(status_code=400, detail="URL is not allowed")


@router.get("/codex/issues/{issue_id}/orchestration-policy")
async def get_issue_orchestration_policy(issue_id: str) -> IssueOrchestrationPolicyResponse:
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    issue = await codex_store.load_codex_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail=f"Issue '{issue_id}' not found")
    policy = classify_issue_orchestration(issue.title, issue.description)
    return {
        "issue_id": issue_id,
        "recommendation": policy.recommendation,
        "batch_allowed": policy.batch_allowed,
        "signals": list(policy.signals),
        "guidance": list(policy.guidance),
    }


@router.get("/codex/issues/{issue_id}/budget")
async def get_issue_budget(issue_id: str) -> IssueBudgetPayload:
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    issue = await codex_store.load_codex_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail=f"Issue '{issue_id}' not found")
    status = await compute_issue_budget_status(codex_store, issue)
    status.reserved_usd = 0.0
    return status.to_dict()


@router.get("/codex/issues/{issue_id}/subagent-results")
async def codex_issue_subagent_results(issue_id: str) -> object:
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    tasks = await codex_store.list_codex_tasks(issue_id=issue_id)
    results = []
    for task in tasks:
        status = task.get("status")
        if not (is_task_success_status(status) or is_task_failure_status(status)):
            continue
        results.append(
            {
                "task_id": task.get("id"),
                "role": task.get("role"),
                "status": status,
                "summary": task.get("result"),
                "artifact_json": _safe_json_object(_json_text(task.get("result_json"))),
                "task_kind": task.get("task_kind"),
                "created_at": task.get("created_at"),
                "updated_at": task.get("updated_at"),
            }
        )
    return results


@router.get("/codex/issues/{issue_id}/agent-mesh")
async def codex_issue_agent_mesh(issue_id: str) -> object:
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    if not hasattr(codex_store, "list_agent_messages"):
        return []
    try:
        messages = await codex_store.list_agent_messages(issue_id)
    except TypeError:
        messages = await codex_store.list_agent_messages(issue_id=issue_id)
    return [
        message.model_dump() if hasattr(message, "model_dump") else dict(message)
        for message in messages
    ]


class ProjectConductorAskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=PROJECT_CONDUCTOR_INPUT_MAX_CHARS)

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        question = value.strip()
        if not question:
            raise ValueError("question must not be blank")
        return question


class ProjectConductorMessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=PROJECT_CONDUCTOR_INPUT_MAX_CHARS)

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        message = value.strip()
        if not message:
            raise ValueError("message must not be blank")
        return message


class ProjectConductorStartLoopRequest(BaseModel):
    prompt: str | None = Field(default=None, max_length=PROJECT_CONDUCTOR_INPUT_MAX_CHARS)

    @field_validator("prompt")
    @classmethod
    def validate_prompt(cls, value: str | None) -> str | None:
        if value is None:
            return None
        prompt = value.strip()
        if not prompt:
            raise ValueError("prompt must not be blank")
        return prompt


class ProjectPRFollowupRequest(BaseModel):
    auto_merge: bool = False


async def _run_subprocess(args: list[str], *, cwd: str, timeout_s: int = 30) -> CompletedProcessLike:
    return await _project_conductor_run_subprocess(args, cwd=cwd, timeout_s=timeout_s)


def _serialize_project_conductor_state(
    state: ProjectConductorState,
    cold_memories: list[ProjectMemoryEmbedding],
    cold_memories_total: int,
) -> JsonObject:
    hot_thread = _safe_json_list(state.hot_thread_json)
    warm_summaries = _safe_json_list(state.warm_summaries_json)
    visible_hot = hot_thread[-PROJECT_CONDUCTOR_STATE_HOT_LIMIT:]
    visible_warm = warm_summaries[-PROJECT_CONDUCTOR_STATE_WARM_LIMIT:]
    visible_cold = cold_memories[:PROJECT_CONDUCTOR_STATE_COLD_LIMIT]
    return {
        "project_id": state.project_id,
        "hot_thread": visible_hot,
        "hot_thread_total": len(hot_thread),
        "hot_thread_truncated": len(visible_hot) < len(hot_thread),
        "warm_summaries": visible_warm,
        "warm_summaries_total": len(warm_summaries),
        "warm_summaries_truncated": len(visible_warm) < len(warm_summaries),
        "cold_memories": [
            {
                "id": memory.id,
                "source_kind": memory.source_kind,
                "source_id": memory.source_id,
                "summary_text": memory.summary_text,
                "created_at": memory.created_at.isoformat() if memory.created_at else None,
            }
            for memory in visible_cold
        ],
        "cold_memories_total": cold_memories_total,
        "cold_memories_truncated": len(visible_cold) < cold_memories_total,
        "pinned_text": state.pinned_text,
        "hot_tokens": state.hot_tokens,
        "warm_tokens": state.warm_tokens,
        "last_compaction_at": state.last_compaction_at.isoformat() if state.last_compaction_at else None,
        "total_tasks_handled": state.total_tasks_handled,
        "updated_at": state.updated_at.isoformat() if state.updated_at else None,
    }


def _require_project_conductor(project_id: str) -> ProjectConductor:
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    return ProjectConductor(
        project_id=project_id,
        store=cast(ProjectConductorStore, codex_store),
        event_bus=event_bus,
    )


@router.get("/codex/projects/{project_id}/conductor/state")
async def codex_project_conductor_state(project_id: str) -> JsonObject:
    conductor = _require_project_conductor(project_id)
    state = await conductor.get_or_create_state()
    cold_memories = await conductor.list_recent_cold_memories()
    cold_memories_total = await conductor.count_cold_memories()
    return _serialize_project_conductor_state(state, cold_memories, cold_memories_total)


@router.post("/codex/projects/{project_id}/conductor/ask")
async def codex_project_conductor_ask(project_id: str, request: ProjectConductorAskRequest) -> object:
    conductor = _require_project_conductor(project_id)
    task = ConductorTask(
        id=str(uuid4()),
        project_id=project_id,
        task_kind="qa_question",
        payload={"question": request.question},
        created_at=datetime.now(),
    )
    return await conductor.handle_task(task)


@router.post("/codex/projects/{project_id}/conductor/schedule-review")
async def codex_project_conductor_schedule_review(project_id: str) -> object:
    conductor = _require_project_conductor(project_id)
    task = ConductorTask(
        id=str(uuid4()),
        project_id=project_id,
        task_kind="scheduled_review",
        payload={"question": "Run a scheduled project health review."},
        created_at=datetime.now(),
    )
    return await conductor.handle_task(task)


@router.post("/codex/projects/{project_id}/conductor/message")
async def codex_project_conductor_message(project_id: str, request: ProjectConductorMessageRequest) -> object:
    conductor = _require_project_conductor(project_id)
    await conductor.append_hot_event(role="user", content=request.message)
    return {"status": "ok"}


@router.post("/codex/projects/{project_id}/conductor/start-loop")
async def codex_project_conductor_start_loop(
    project_id: str,
    request: ProjectConductorStartLoopRequest,
) -> JsonObject:
    store = _require_codex_store()
    conductor = _require_project_conductor(project_id)
    prompt = (request.prompt or "Run a deterministic project conductor checkpoint.").strip()
    task = ConductorTask(
        id=str(uuid4()),
        project_id=project_id,
        task_kind="ad_hoc",
        payload={"prompt": prompt},
        status="running",
        result_json="{}",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    await store.save_conductor_task(task)
    answer = (
        "ProjectConductor deterministic checkpoint complete. "
        "No LLM call was required for this local state update."
    )
    await conductor.append_hot_event(
        role="user",
        content=prompt,
        extra={"kind": "loop", "task_id": task.id},
    )
    await conductor.append_hot_event(
        role="project_conductor",
        content=answer,
        extra={"kind": "loop", "task_id": task.id},
    )
    tool_event_id = str(uuid4())
    payload: JsonObject = {
        "status": "done",
        "answer": answer,
        "task_id": task.id,
        "tool_events": [
            {
                "id": tool_event_id,
                "name": "finalize_task",
                "input": {},
                "result": {"status": "done"},
                "is_error": False,
            }
        ],
        "turn_count": 1,
        "llm": None,
    }
    task.status = "done"
    task.result_json = json.dumps(payload, ensure_ascii=False)
    task.updated_at = datetime.now()
    await store.save_conductor_task(task)
    return payload


@router.post("/codex/projects/{project_id}/github-pr-followup")
async def follow_up_project_github_prs(
    project_id: str,
    request: ProjectPRFollowupRequest | None = None,
) -> JsonObject:
    store = _require_codex_store()
    summary = await sweep_project_github_prs(
        project_id,
        store=cast(GitHubPRFollowupStore, store),
        event_bus=event_bus,
        run_subprocess=_run_subprocess,
        auto_merge=bool(request and request.auto_merge),
    )
    return summary.to_dict()


_PIPELINE_ROLES: tuple[tuple[str, str], ...] = (
    ("product_manager", "PM"),
    ("architect", "Architect"),
    ("engineer", "Engineer"),
    ("qa", "QA"),
)


def _seconds_between(start: datetime | None, end: datetime | None) -> int | None:
    if start is None or end is None:
        return None
    return int((end - start).total_seconds())


def _task_time(value: object) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return value if isinstance(value, str) else None


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _required_str(value: object, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _json_text(value: object) -> str | bytes | bytearray | None:
    return value if isinstance(value, (str, bytes, bytearray)) else None


def _read_pm_artifact_summary(issue: CodexIssue) -> tuple[str | None, str | None]:
    if not issue.git_worktree_path:
        return None, None
    prd_path = Path(issue.git_worktree_path) / "issues" / issue.id / "pm" / "prd.json"
    try:
        data = json.loads(prd_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, None
    acceptance = data.get("acceptance_criteria") if isinstance(data, dict) else None
    goals = data.get("goals") if isinstance(data, dict) else None
    requirements = data.get("requirements") if isinstance(data, dict) else None
    parts = []
    foot = []
    if isinstance(acceptance, list):
        parts.append(f"{len(acceptance)} acceptance criteria")
    if isinstance(goals, list):
        foot.append(f"{len(goals)} goals")
    if isinstance(requirements, list):
        foot.append(f"{len(requirements)} reqs")
    return ", ".join(parts) or None, " · ".join(foot) or None


@router.get("/codex/issues/{issue_id}/pipeline-stages")
async def get_issue_pipeline_stages(issue_id: str) -> PipelineStagesResponse:
    store = _require_codex_store()
    issue = await store.load_codex_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail=f"Issue '{issue_id}' not found")
    graph = await store.load_workflow_graph_for_issue(issue_id)
    agents = await store.list_agents(workspace_id=None)
    role_by_agent = {agent.id: agent.role_key for agent in agents}
    stages: list[PipelineStagePayload] = [
        {
            "role": role,
            "label": label,
            "status": "pending",
            "task_id": None,
            "started_at": None,
            "completed_at": None,
            "duration_seconds": None,
            "summary": None,
            "foot": None,
        }
        for role, label in _PIPELINE_ROLES
    ]
    by_role: dict[str, PipelineStagePayload] = {stage["role"]: stage for stage in stages}
    if graph is not None:
        for node in graph.nodes:
            role = role_by_agent.get(node.agent_id, node.node_key)
            stage = by_role.get(role)
            if stage is None:
                continue
            stage.update(
                {
                    "status": node.status,
                    "task_id": node.task_id,
                    "started_at": node.started_at.isoformat() if node.started_at else None,
                    "completed_at": node.completed_at.isoformat() if node.completed_at else None,
                    "duration_seconds": _seconds_between(node.started_at, node.completed_at),
                }
            )
    pm_summary, pm_foot = _read_pm_artifact_summary(issue)
    if pm_summary:
        by_role["product_manager"]["summary"] = pm_summary
    if pm_foot:
        by_role["product_manager"]["foot"] = pm_foot
    starts = [
        parsed
        for stage in stages
        if stage.get("started_at")
        for parsed in [_parse_iso_datetime(stage["started_at"])]
        if parsed is not None
    ]
    completions = [
        parsed
        for stage in stages
        if stage.get("completed_at")
        for parsed in [_parse_iso_datetime(stage["completed_at"])]
        if parsed is not None
    ]
    started_at = min(starts).isoformat() if starts else None
    completed_at = max(completions).isoformat() if completions and all(s["status"] == "done" for s in stages) else None
    total_duration = None
    if started_at and completed_at:
        total_duration = _seconds_between(_parse_iso_datetime(started_at), _parse_iso_datetime(completed_at))
    return {
        "issue_id": issue_id,
        "stages": stages,
        "started_at": started_at,
        "completed_at": completed_at,
        "total_duration_seconds": total_duration,
    }


@router.get("/codex/issues/{issue_id}/activity")
async def get_issue_activity(issue_id: str, limit: int = 50) -> IssueActivityResponse:
    store = _require_codex_store()
    issue = await store.load_codex_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail=f"Issue '{issue_id}' not found")
    events: list[IssueActivityEvent] = [
        {
            "type": "issue_created",
            "timestamp": issue.created_at.isoformat() if issue.created_at else "",
            "title": issue.title,
            "issue_id": issue.id,
        }
    ]
    for task in await store.list_codex_tasks(issue_id=issue_id):
        created_at = _task_time(task.get("created_at"))
        updated_at = _task_time(task.get("updated_at"))
        events.append(
            {
                "type": "task_started",
                "timestamp": created_at or updated_at or "",
                "task_id": _optional_str(task.get("id")),
                "role": _optional_str(task.get("role")),
                "title": _optional_str(task.get("title")),
            }
        )
        status = task.get("status")
        if is_task_success_status(status) or is_task_failure_status(status):
            events.append(
                {
                    "type": "task_done" if is_task_success_status(status) else "task_failed",
                    "timestamp": updated_at or created_at or "",
                    "task_id": _optional_str(task.get("id")),
                    "role": _optional_str(task.get("role")),
                    "title": _optional_str(task.get("title")),
                }
            )
    events = sorted(events, key=lambda item: str(item.get("timestamp") or ""))
    capped = events[-max(1, min(limit, 200)) :]
    return {"issue_id": issue_id, "events": capped}


def _extract_usage_from_log(content: str) -> dict[str, int]:
    try:
        parsed = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return {"input": 0, "output": 0}
    message = parsed.get("message") if isinstance(parsed, dict) else None
    usage = message.get("usage") if isinstance(message, dict) else parsed.get("usage")
    if not isinstance(usage, dict):
        return {"input": 0, "output": 0}
    return {
        "input": int(usage.get("input_tokens") or 0),
        "output": int(usage.get("output_tokens") or 0),
    }


@router.get("/codex/issues/{issue_id}/graph-stats")
async def get_issue_graph_stats(issue_id: str) -> GraphStatsResponse:
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    graph = await codex_store.load_workflow_graph_for_issue(issue_id)
    if graph is None:
        return {"issue_id": issue_id, "nodes": {}, "conductor": {"role_key": "conductor"}}
    agents = await codex_store.list_agents(workspace_id=None)
    role_by_agent = {agent.id: agent.role_key for agent in agents}
    nodes: dict[str, GraphStatsNode] = {}
    for node in graph.nodes:
        role = role_by_agent.get(node.agent_id, node.node_key)
        tokens: GraphStatsTokens = {"input": 0, "output": 0}
        task = await codex_store.load_codex_task(node.task_id) if node.task_id else None
        if task is not None:
            logs = await codex_store.load_log_events(task.session_id, task_id=task.id, limit=5000)
            for log in logs:
                usage = _extract_usage_from_log(getattr(log, "content", ""))
                tokens["input"] += usage["input"]
                tokens["output"] += usage["output"]
        duration = _seconds_between(node.started_at, node.completed_at)
        nodes[node.node_key] = {
            "role_key": role,
            "status": node.status,
            "task_id": node.task_id,
            "duration_seconds": duration,
            "tokens": tokens if tokens["input"] or tokens["output"] else None,
            "est_cost_usd": round((tokens["input"] + tokens["output"]) / 1_000_000, 6),
        }
    return {"issue_id": issue_id, "nodes": nodes, "conductor": {"role_key": "conductor"}}


def _parse_iso_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _append_degraded_check(checks: list[dict[str, object]], name: str, detail: str) -> None:
    checks.append({"name": name, "status": "degraded", "detail": detail})


def _append_supervisor_checks(
    checks: list[dict[str, object]],
    *,
    name: str,
    snapshot: dict[str, object],
    running_detail: str,
    stale_detail: str | None = None,
) -> None:
    last_error = snapshot.get("last_error")
    if last_error:
        _append_degraded_check(checks, name, str(last_error))
        return
    if snapshot.get("running") is True:
        _append_degraded_check(checks, name, running_detail)
        return
    if stale_detail is None:
        return
    interval_s = snapshot.get("interval_s")
    completed_at = _parse_iso_datetime(snapshot.get("last_completed_at"))
    if completed_at is None:
        return
    if not isinstance(interval_s, int | float | str):
        return
    try:
        interval = float(interval_s)
    except ValueError:
        return
    if interval > 0 and (datetime.now() - completed_at).total_seconds() > interval * 2:
        _append_degraded_check(checks, name, stale_detail)


@router.get("/diagnostics")
async def get_diagnostics() -> object:
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")

    checks: list[JsonObject] = []
    try:
        projects = await codex_store.list_projects()
        database = {"status": "ok", "projects_total": len(projects)}
    except Exception as exc:
        database = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
        checks.append({"name": "database", "status": "degraded", "detail": database["error"]})

    try:
        catalog = await _get_runtime_catalog_service().load_catalog()
        runtime_catalog = _runtime_catalog_response(catalog)
        executors = _json_object_list(runtime_catalog.get("executors", []))
        enabled = [executor for executor in executors if executor.get("enabled")]
        runtime_catalog = {
            "status": "ok",
            "executors_total": len(executors),
            "executors_enabled": len(enabled),
            "executors": executors,
        }
        if not enabled:
            _append_degraded_check(checks, "runtime_catalog", "No enabled runtime executors")
    except Exception as exc:
        runtime_catalog = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
        checks.append({"name": "runtime_catalog", "status": "degraded", "detail": runtime_catalog["error"]})

    from app.application import (
        github_pr_followup,
        project_review_scheduler,
        self_improvement_proposal_scheduler,
    )

    github_status = github_pr_followup.get_github_pr_followup_status()
    project_review_status = project_review_scheduler.get_project_review_scheduler_status()
    proposal_status = self_improvement_proposal_scheduler.get_self_improvement_proposal_scheduler_status()
    _append_supervisor_checks(
        checks,
        name="github_pr_followup",
        snapshot=github_status,
        running_detail="GitHub PR follow-up sweep is running",
    )
    _append_supervisor_checks(
        checks,
        name="project_review_scheduler",
        snapshot=project_review_status,
        running_detail="Project review scheduler is running",
        stale_detail="Project review scheduler has not completed recently",
    )
    _append_supervisor_checks(
        checks,
        name="self_improvement_proposal_scheduler",
        snapshot=proposal_status,
        running_detail="Self-improvement proposal scheduler is running",
        stale_detail="Self-improvement proposal scheduler has not completed recently",
    )

    status = "degraded" if checks else "ok"
    return {
        "service": "agent-collab-console",
        "status": status,
        "generated_at": _utc_now_iso(),
        "database": database,
        "runtime_catalog": runtime_catalog,
        "github_pr_followup": github_status,
        "project_review_scheduler": project_review_status,
        "self_improvement_proposal_scheduler": proposal_status,
        "executors": {"codex_binary_available": check_codex_available()},
        "websockets": {"global_event_subscribers": len(event_bus.subscribers)},
        "config": {
            "real_cli_enabled": timeouts.real_cli_enabled(),
            "use_sqlite": timeouts.use_sqlite(),
        },
        "checks": checks,
    }


@router.post("/codex/benchmark/runs", status_code=202)
async def trigger_benchmark_run(
    request: BenchmarkTriggerRunRequest,
) -> benchmark_handlers.TriggerRunResponse:
    payload: benchmark_handlers.TriggerRunPayload = {
        "label": request.label,
        "epochs": request.epochs,
        "fixture_ids": request.fixture_ids,
        "is_baseline": request.is_baseline,
        "max_budget_usd": request.max_budget_usd,
        "project_id": request.project_id,
        "workspace_id": request.workspace_id,
        "dry_run": request.dry_run,
    }
    return await benchmark_handlers.trigger_run(payload)


@router.get("/codex/benchmark/runs")
def list_benchmark_runs() -> benchmark_handlers.ListRunsResponse:
    return benchmark_handlers.list_runs()


@router.get("/codex/benchmark/runs/{run_id}")
def get_benchmark_run(run_id: str) -> benchmark_handlers.SerializedRun:
    return benchmark_handlers.get_run(run_id)


@router.get("/codex/benchmark/runs/{run_id}/diff")
def get_benchmark_run_diff(run_id: str) -> benchmark_handlers.RunDiffResponse:
    return benchmark_handlers.get_run_diff(run_id)


@router.get("/codex/benchmark/baseline")
def get_benchmark_baseline() -> benchmark_handlers.BaselineResponse:
    return benchmark_handlers.get_baseline()


@router.post("/codex/benchmark/baseline/{run_id}")
def set_benchmark_baseline(run_id: str) -> benchmark_handlers.SetBaselineResponse:
    return benchmark_handlers.set_baseline(run_id)


@router.get("/codex/benchmark/jobs/{job_id}")
def get_benchmark_job(job_id: str) -> benchmark_handlers.JobResponse:
    return benchmark_handlers.get_job(job_id)


@router.get("/codex/benchmark/calibration")
def get_benchmark_calibration(floor: float = 0.7) -> benchmark_handlers.CalibrationReportResponse:
    return benchmark_handlers.get_calibration_report(floor=floor)


def _try_parse_json_line(line: str) -> JsonObject | None:
    stripped = line.strip()
    if not stripped.startswith("{"):
        return None
    try:
        parsed = json.loads(stripped)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None
    return _json_object(parsed)


def _pick_executor_from_tasks(tasks: list[JsonObject]) -> tuple[str | None, str | None, str | None]:
    """Return (executor, provider, model) inherited from the most recently updated task that has them."""
    for task in sorted(tasks, key=lambda t: str(t.get("updated_at") or ""), reverse=True):
        executor = _optional_str(task.get("executor"))
        if executor:
            return executor, _optional_str(task.get("provider")), _optional_str(task.get("model"))
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
    except RuntimeCatalogValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def _resolve_task_runtime_config(task: CodexTask) -> tuple[str, str, str, dict[str, str] | None, str]:
    return await _resolve_runtime_config(task.executor, task.provider, task.model)


def _serialize_task_payload(task: CodexTask) -> JsonObject:
    return {
        "id": task.id,
        "session_id": task.session_id,
        "project_id": task.project_id,
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
        "git_branch": task.git_branch,
        "git_base_branch": task.git_base_branch,
        "git_worktree_path": task.git_worktree_path,
        "last_execution_process_id": task.last_execution_process_id,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
    }


async def _list_task_messages(
    task_id: str,
    execution_process_id: str | None = None,
) -> list[CodexTaskMessage]:
    store = _require_codex_store()
    if execution_process_id:
        try:
            return await store.list_codex_task_messages(task_id, execution_process_id=execution_process_id)
        except TypeError:
            pass
    return await store.list_codex_task_messages(task_id)


async def _load_task_logs(
    session_id: str,
    task_id: str,
    execution_process_id: str | None = None,
    limit: int = 1000,
    reverse: bool = False,
) -> list[LogEvent]:
    store = _require_codex_store()
    if execution_process_id:
        try:
            return await store.load_log_events(
                session_id,
                task_id=task_id,
                execution_process_id=execution_process_id,
                limit=limit,
                reverse=reverse,
            )
        except TypeError:
            return await store.load_log_events(session_id, task_id=task_id, limit=limit, reverse=reverse)
    return await store.load_log_events(session_id, task_id=task_id, limit=limit, reverse=reverse)


async def _load_execution_process(process_id: str) -> ExecutionProcess:
    store = _require_codex_store()
    process = await store.load_execution_process(process_id)
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

    def find_result(log_list: list[LogEvent]) -> tuple[str | None, bool]:
        for log in log_list:
            if log.stream != "stdout":
                continue
            event = _try_parse_json_line(log.content)
            if event is None:
                continue

            method = event.get("method")
            if event.get("type") == "assistant" or method == "item/completed":
                params_raw = event.get("params")
                params = params_raw if isinstance(params_raw, dict) else {}
                item_raw = params.get("item") or event.get("message") or {}
                item = item_raw if isinstance(item_raw, dict) else {}
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
                item_raw = event.get("item") or {}
                item = item_raw if isinstance(item_raw, dict) else {}
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


async def _refresh_task_result(task: CodexTask) -> None:
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
    if is_task_success_status(task.status) and task.result:
        store = _require_codex_store()
        workspace = await store.load_codex_workspace(task.session_id)
        workspace_title = workspace.title if workspace is not None else None
        artifact = await role_workflow_service.persist_result(task, workspace_title=workspace_title)

        # Automated Code Review Logic
        if task.role == "architect" and getattr(task, "task_kind", "normal") == "review" and task.parent_task_id:
            from app.application.architect_workflow import ReviewReportDocument
            if isinstance(artifact, ReviewReportDocument):
                parent_task = await store.load_codex_task(task.parent_task_id)
                if parent_task:
                    if artifact.decision == "approve":
                        parent_task.status = "done"
                    else:
                        parent_task.status = "rework"

                    # Format complete review feedback
                    review_parts = [artifact.reason]
                    if artifact.suggestions:
                        review_parts.append("\n\n**改进建议:**")
                        for i, suggestion in enumerate(artifact.suggestions, 1):
                            review_parts.append(f"{i}. {suggestion}")
                    if artifact.risks_identified:
                        review_parts.append("\n\n**识别的风险:**")
                        for i, risk in enumerate(artifact.risks_identified, 1):
                            review_parts.append(f"{i}. {risk}")

                    parent_task.review_comment = "\n".join(review_parts)
                    parent_task.updated_at = datetime.now()
                    await store.save_codex_task(parent_task)
                    from app.application.task_status_events import build_task_status_event

                    parent_status_event = build_task_status_event(
                        parent_task,
                        review_comment=parent_task.review_comment,
                    )
                    await event_bus.append(parent_status_event)


async def _latest_assistant_message_content(task_id: str) -> str | None:
    messages = await _list_task_messages(task_id)
    for message in reversed(messages):
        content = getattr(message, "content", None)
        if getattr(message, "role", None) == "assistant" and isinstance(content, str) and content:
            return content
    return None


async def _build_execution_process_payload(process: ExecutionProcess) -> JsonObject:
    store = codex_store
    if store is None:
        return build_execution_process_view(process, None, [], [])
    task = await store.load_codex_task(process.task_id)
    messages = await store.list_codex_task_messages(
        process.task_id,
        execution_process_id=process.id,
    )
    logs = await store.load_log_events(
        process.session_id,
        task_id=process.task_id,
        execution_process_id=process.id,
        limit=1000,
    )
    return build_execution_process_view(process, task, messages, logs)

def _delete_issue_artifact_root(workspace_path: str | None, issue_id: str) -> None:
    if not workspace_path:
        return
    issue_root = Path(workspace_path) / "issues" / issue_id
    if not issue_root.exists():
        return
    with suppress(Exception):
        shutil.rmtree(issue_root)


async def _cleanup_session_worktrees(session_id: str, project_id: str | None) -> None:
    """Remove all worktrees owned by issues/chat tasks under a workspace."""
    if codex_store is None or not project_id:
        return
    project = await codex_store.load_project(project_id)
    if project is None:
        return
    issues = await codex_store.list_codex_issues(session_id=session_id)
    for issue_dict in issues:
        issue_id = _optional_str(issue_dict.get("id"))
        if issue_id is None:
            continue
        issue = await codex_store.load_codex_issue(issue_id)
        if issue is None:
            continue
        with suppress(Exception):
            await worktree_manager.cleanup_issue_worktree(project, issue)
    chat_tasks = await codex_store.list_codex_tasks(session_id=session_id)
    for task_dict in chat_tasks:
        if task_dict.get("issue_id") or not task_dict.get("git_worktree_path"):
            continue
        task_id = _optional_str(task_dict.get("id"))
        if task_id is None:
            continue
        task = await codex_store.load_codex_task(task_id)
        if task is None:
            continue
        with suppress(Exception):
            await worktree_manager.cleanup_chat_task_worktree(project, task)


async def _delete_task_cascade(task_id: str, *, delete_workspace: bool = True) -> CodexTask:
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
            with suppress(Exception):
                await worktree_manager.cleanup_chat_task_worktree(project, task)
    await codex_store.delete_codex_task(task_id)
    await event_bus.append({
        "type": "task_deleted",
        "task_id": task_id,
    })
    return task


task_runner: CodexTaskRunner | None = None
product_manager_service = ProductManagerService()
role_workflow_service = RoleWorkflowService(
    codex_store=cast(RoleWorkflowStore | None, codex_store),
    project_startup_mcp_service=project_startup_mcp_service,
)


def _get_task_runner() -> CodexTaskRunner:
    global task_runner
    store = cast(TaskRunnerStore, _require_codex_store())
    if task_runner is None:
        task_runner = CodexTaskRunner(
            codex_store=store,
            event_bus=event_bus,
            process_manager_factory=cast(Callable[[], TaskProcessManager], get_codex_process_manager),
            mock_manager_cls=MockCodexProcessManager,
            refresh_task_result=_refresh_task_result,
            help_orchestrator_factory=lambda: get_help_orchestrator(_refresh_task_result),
            role_workflow_service=role_workflow_service,
        )
    elif isinstance(task_runner, CodexTaskRunner):
        task_runner.codex_store = store
        task_runner.event_bus = event_bus
        task_runner._process_manager_factory = cast(Callable[[], TaskProcessManager], get_codex_process_manager)
        task_runner._mock_manager_cls = MockCodexProcessManager
        task_runner._refresh_task_result = _refresh_task_result
        task_runner._help_orchestrator_factory = lambda: get_help_orchestrator(_refresh_task_result)
        task_runner._role_workflow_service = role_workflow_service
    mgr = get_codex_process_manager()
    if hasattr(mgr, "refresh_task_result"):
        mgr.refresh_task_result = _refresh_task_result
    return task_runner


@router.get("/health")
async def health_check() -> object:
    """Health check endpoint to verify this is the correct backend."""
    return {"service": "agent-collab-console", "version": "1.0"}


@router.get("/browser-smoke")
async def browser_smoke() -> object:
    """Minimal smoke endpoint for browser health checks."""
    return {"ok": True}


@router.get("/utils/select-directory")
async def select_directory() -> object:
    """Opens a native directory picker on macOS and returns the selected path."""
    try:
        # Use osascript to open a native folder picker on macOS.
        # This returns the POSIX path of the selected folder.
        # If the user cancels, it will exit with an error.
        result = run_trusted_local(
            ["osascript", "-e", 'POSIX path of (choose folder with prompt "Select Directory")'],
            capture_output=True,
            text=True,
            check=True,
        )
        path = result.stdout.strip()
        return {"path": path}
    except CalledProcessError as exc:
        # User likely cancelled the dialog or osascript failed
        if "User canceled" in exc.stderr:
            return {"path": None}
        logger.error("osascript failed: stderr=%s", exc.stderr)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to open directory picker: {exc.stderr}",
        ) from exc
    except Exception as exc:
        logger.error("Unexpected error in select_directory: error=%s", exc)
        raise HTTPException(status_code=500, detail=f"Unexpected error: {exc}") from exc


class CreateSessionRequest(BaseModel):
    title: str


class CreateSessionTaskRequest(BaseModel):
    title: str
    assignee: str = "claude"


@router.post("/sessions", status_code=201)
async def create_session(request: CreateSessionRequest) -> object:
    return await session_service.create_session(request.title)


@router.get("/sessions")
async def list_sessions() -> object:
    sessions = await session_service.list_sessions()
    return [{"id": s.id, "title": s.title, "state": s.state.value} for s in sessions]


@router.get("/sessions/{session_id}")
async def get_session(session_id: str) -> object:
    try:
        return await session_service.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found") from exc


@router.get("/sessions/{session_id}/tasks")
async def get_session_tasks(session_id: str) -> object:
    try:
        session = await session_service.get_session(session_id)
        return session.tasks
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found") from exc


@router.get("/sessions/{session_id}/messages")
async def get_session_messages(session_id: str) -> object:
    try:
        return (await session_service.get_session(session_id)).messages
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found") from exc


@router.get("/sessions/{session_id}/artifacts")
async def get_session_artifacts(session_id: str) -> object:
    try:
        return (await session_service.get_session(session_id)).artifacts
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found") from exc


@router.get("/sessions/{session_id}/runs")
async def get_session_runs(session_id: str) -> object:
    try:
        return (await session_service.get_session(session_id)).runs
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found") from exc


@router.get("/tasks/{task_id}")
async def get_task(task_id: str) -> object:
    for session in session_service.sessions.values():
        for task in session.tasks:
            if task.id == task_id:
                return task
    raise HTTPException(status_code=404, detail="Task not found")


@router.post("/sessions/{session_id}/tasks", status_code=201)
async def create_task(session_id: str, request: CreateSessionTaskRequest) -> object:
    try:
        await session_service.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found") from exc

    try:
        task = await orchestration_service.plan_task(session_id, request.title, request.assignee)
    except Exception as exc:
        logger.error("Failed to create task in session %s: %s", session_id, exc)
        raise HTTPException(status_code=500, detail=f"Failed to create task: {exc}") from exc
    return task


@router.post("/tasks/{task_id}/run")
async def run_task(task_id: str) -> object:
    try:
        result = await orchestration_service.run_task(task_id)
        return result
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found") from exc
    except Exception as exc:
        logger.error("Failed to run task %s: %s", task_id, exc)
        raise HTTPException(status_code=500, detail=f"Failed to run task: {exc}") from exc


@router.post("/tasks/{task_id}/retry")
async def retry_task(task_id: str) -> object:
    try:
        result = await orchestration_service.retry_task(task_id)
        return result
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Failed to retry task %s: %s", task_id, exc)
        raise HTTPException(status_code=500, detail=f"Failed to retry task: {exc}") from exc


@router.post("/tasks/{task_id}/approval")
async def request_approval(task_id: str) -> object:
    # Find session containing this task
    for session in session_service.sessions.values():
        for task in session.tasks:
            if task.id == task_id:
                try:
                    approval = await approval_service.request_submission(session.id, task_id)
                except Exception as exc:
                    logger.error("Failed to request approval for task %s: %s", task_id, exc)
                    raise HTTPException(
                        status_code=500,
                        detail=f"Failed to request approval: {exc}",
                    ) from exc
                return approval
    raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")


@router.get("/approvals/{approval_id}")
async def get_approval(approval_id: str) -> object:
    try:
        return approval_service.approvals[approval_id]
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Approval '{approval_id}' not found") from exc


@router.post("/approvals/{approval_id}/approve")
async def approve_approval(approval_id: str) -> object:
    try:
        return await approval_service.approve(approval_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Approval '{approval_id}' not found") from exc
    except Exception as exc:
        logger.error("Failed to approve approval %s: %s", approval_id, exc)
        raise HTTPException(status_code=500, detail=f"Failed to approve: {exc}") from exc


@router.post("/approvals/{approval_id}/reject")
async def reject_approval(approval_id: str) -> object:
    try:
        return await approval_service.reject(approval_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Approval '{approval_id}' not found") from exc
    except Exception as exc:
        logger.error("Failed to reject approval %s: %s", approval_id, exc)
        raise HTTPException(status_code=500, detail=f"Failed to reject: {exc}") from exc


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
    run_command: str | None = None


class ScriptSuggestionRequest(BaseModel):
    setup_script: str | None = None
    run_command: str | None = None
    verify: bool = False


class ScriptTaskRequest(ScriptSuggestionRequest):
    executor: str | None = None
    provider: str | None = None
    model: str | None = None


class ScriptTaskResponse(BaseModel):
    task_id: str
    status: str
    title: str
    execution_process_id: str | None = None
    reused: bool = False


class ResumeResponse(BaseModel):
    project_id: str
    markdown: str
    exists: bool
    relative_path: str
    updated_at: str | None = None
    size_bytes: int


class UpdateResumeRequest(BaseModel):
    markdown: str


class ResumeImportResponse(BaseModel):
    project_id: str
    markdown: str
    source_filename: str
    page_count: int
    extracted_pages: int
    size_bytes: int
    warnings: list[str]


class SelfImprovementProposalStatusRequest(BaseModel):
    status: Literal["proposed", "accepted", "rejected", "applied"]


class SelfImprovementApplyRequest(BaseModel):
    content_sha256: str


class SelfImprovementActivateRequest(BaseModel):
    start_conductor: bool = False


def _require_project_service() -> ProjectService:
    if project_service is None:
        raise HTTPException(status_code=503, detail="Project service unavailable (no async store)")
    return project_service


async def _get_project_or_404(project_id: str) -> Project:
    svc = _require_project_service()
    try:
        return await svc.get(project_id)
    except ProjectError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _resume_response(project_id: str, document: ResumeDocument) -> ResumeResponse:
    return ResumeResponse(
        project_id=project_id,
        markdown=document.markdown,
        exists=document.exists,
        relative_path=document.relative_path,
        updated_at=document.updated_at,
        size_bytes=document.size_bytes,
    )


def _require_codex_store() -> CodexApiStore:
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    return codex_store


def _serialize_self_improvement_proposal(proposal: SelfImprovementProposal) -> JsonObject:
    return {
        "id": proposal.id,
        "project_id": proposal.project_id,
        "issue_id": proposal.issue_id,
        "target_kind": proposal.target_kind,
        "title": proposal.title,
        "recommendation": proposal.recommendation,
        "evidence": _safe_json_object_list(proposal.evidence_json),
        "severity": proposal.severity,
        "confidence": proposal.confidence,
        "status": proposal.status,
        "fingerprint": proposal.fingerprint,
        "created_at": proposal.created_at.isoformat() if proposal.created_at else None,
        "updated_at": proposal.updated_at.isoformat() if proposal.updated_at else None,
    }


def _serialize_self_improvement_application(event: SelfImprovementApplicationEvent) -> JsonObject:
    result = _safe_json_object(event.result_json) or {}
    return {
        "id": event.id,
        "proposal_id": event.proposal_id,
        "project_id": event.project_id,
        "issue_id": event.issue_id,
        "target_kind": event.target_kind,
        "action": event.action,
        "status": event.status,
        "path": event.path,
        "content_sha256": event.content_sha256,
        "result": result,
        **result,
        "error": event.error,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


def _serialize_workflow_graph(graph: WorkflowGraph | None) -> JsonObject | None:
    if graph is None:
        return None
    return {
        "id": graph.id,
        "issue_id": graph.issue_id,
        "status": graph.status,
        "nodes": [
            _model_json_object(node)
            for node in (graph.nodes or [])
        ],
        "edges": [
            _model_json_object(edge)
            for edge in (graph.edges or [])
        ],
    }


async def _load_project_or_self_improvement_404(project_id: str) -> Project:
    store = _require_codex_store()
    project = await store.load_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def _load_self_improvement_proposal_for_project(
    project_id: str,
    proposal_id: str,
) -> SelfImprovementProposal:
    store = _require_codex_store()
    await _load_project_or_self_improvement_404(project_id)
    proposal = await store.load_self_improvement_proposal(proposal_id)
    if proposal is None or proposal.project_id != project_id:
        raise HTTPException(status_code=404, detail="Self-improvement proposal not found")
    return proposal


def _validate_self_improvement_status_transition(current: str, requested: str) -> None:
    if current == requested:
        return
    allowed = {
        "proposed": {"accepted", "rejected"},
        "accepted": {"applied"},
    }
    if requested not in allowed.get(current, set()):
        raise HTTPException(
            status_code=409,
            detail="Invalid self-improvement proposal status transition",
        )


def _self_improvement_apply_status(exc: SelfImprovementApplyError) -> int:
    if exc.code in {"invalid_status", "unsupported_target", "hash_mismatch"}:
        return 409
    return 500


def _self_improvement_evidence_lines(proposal: SelfImprovementProposal) -> list[str]:
    lines: list[str] = []
    for item in _safe_json_object_list(proposal.evidence_json):
        kind = str(item.get("kind") or "evidence")
        pointer = item.get("id") or item.get("path") or item.get("summary") or item.get("value")
        if pointer is None:
            pointer = json.dumps(item, sort_keys=True)
        lines.append(f"- {kind}: {pointer}")
    return lines


def _self_improvement_issue_description(proposal: SelfImprovementProposal) -> str:
    lines = [
        f"Proposal ID: `{proposal.id}`",
        f"Target kind: `{proposal.target_kind}`",
        f"Source issue ID: `{proposal.issue_id}`",
        "",
        proposal.recommendation.strip(),
    ]
    evidence = _self_improvement_evidence_lines(proposal)
    if evidence:
        lines.extend(["", "Evidence:", *evidence])
    return "\n".join(lines).strip()


async def _save_self_improvement_application_event(
    *,
    proposal: SelfImprovementProposal,
    action: str,
    status: str,
    path: str | None = None,
    content_sha256: str | None = None,
    result: Mapping[str, object] | None = None,
    error: str | None = None,
) -> SelfImprovementApplicationEvent:
    store = _require_codex_store()
    event = SelfImprovementApplicationEvent(
        id=str(uuid4()),
        proposal_id=proposal.id,
        project_id=proposal.project_id,
        issue_id=proposal.issue_id,
        target_kind=proposal.target_kind,
        action=action,
        status=status,
        path=path,
        content_sha256=content_sha256,
        result_json=json.dumps(result or {}, sort_keys=True),
        error=error,
        created_at=datetime.now(),
    )
    await store.save_self_improvement_application_event(event)
    return event


async def _find_self_improvement_activation_issue(
    proposal: SelfImprovementProposal,
) -> tuple[CodexIssue | None, SelfImprovementApplicationEvent | None]:
    store = _require_codex_store()
    events = await store.list_self_improvement_application_events(
        project_id=proposal.project_id,
        proposal_id=proposal.id,
        limit=100,
    )
    for event in events:
        if event.action != "open_pr_task" or event.status != "succeeded":
            continue
        issue_id = (_safe_json_object(event.result_json) or {}).get("issue_id")
        if not isinstance(issue_id, str):
            continue
        issue = await store.load_codex_issue(issue_id)
        if issue is not None:
            return issue, event
    return None, None


async def _start_issue_conductor_graph(
    issue_id: str,
    *,
    store: AgentWorkflowApiStore,
) -> JsonObject:
    from app.application.conductor_main_loop import run_issue_conductor_loop
    from app.application.conductor_session_registry import ConductorSessionRegistry

    issue = await store.load_codex_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    if ConductorSessionRegistry.instance().is_alive(issue_id):
        return {
            "started": False,
            "already_running": True,
            "graph": _serialize_workflow_graph(await store.load_workflow_graph_for_issue(issue_id)),
        }

    graph = await store.load_workflow_graph_for_issue(issue_id)
    if graph is None:
        now = datetime.now()
        graph = WorkflowGraph(
            id=str(uuid4()),
            issue_id=issue_id,
            status="running",
            dag_json="{}",
            created_by="conductor",
            created_at=now,
            updated_at=now,
            nodes=[],
            edges=[],
        )
        await store.save_workflow_graph(graph, nodes=[], edges=[])

    handle = await ConductorSessionRegistry.instance().try_start(
        issue_id,
        lambda: run_issue_conductor_loop(
            issue=issue,
            project_id=issue.project_id or "",
            store=store,
            event_bus=event_bus,
        ),
        name=f"conductor-{issue_id[:8]}",
    )
    return {
        "started": handle is not None,
        "already_running": handle is None,
        "graph": _serialize_workflow_graph(graph),
    }


@router.get("/projects")
async def list_projects() -> object:
    svc = _require_project_service()
    return await svc.list()


@router.post("/projects", status_code=201)
async def create_project(request: CreateProjectRequest) -> object:
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
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/projects/{project_id}")
async def get_project(project_id: str) -> object:
    svc = _require_project_service()
    try:
        return await svc.get(project_id)
    except ProjectError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/projects/{project_id}")
async def update_project(project_id: str, request: UpdateProjectRequest) -> object:
    svc = _require_project_service()
    try:
        return await svc.update(
            project_id,
            name=request.name,
            default_branch=request.default_branch,
            setup_script=request.setup_script,
            run_command=request.run_command,
        )
    except ProjectError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


async def _load_project_for_run(project_id: str) -> Project:
    svc = _require_project_service()
    try:
        return await svc.get(project_id)
    except ProjectError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


async def _reconcile_project_env_file(project: Project, store: CodexApiStore) -> None:
    from app.application.env_materializer import materialize_env_file

    stored_vars = await store.load_project_env_vars(project.id)
    result = await materialize_env_file(
        project_id=project.id,
        repo_path=project.repo_path,
        agent_env_vars=[],
        stored_vars=stored_vars,
    )
    if result.valid:
        return
    raise HTTPException(
        status_code=409,
        detail={
            "reason": "env_incomplete",
            "errors": [error.to_dict() for error in result.errors],
            "message": "项目环境变量未完整配置。请在「环境配置」面板填写所有必填项后再启动。",
        },
    )


async def _project_service_status(
    project: Project,
    store: CodexApiStore | None,
) -> LocalServiceStatus:
    if store is None:
        return unknown_local_service_status("store_unavailable")
    access_url = await resolve_project_access_url(
        store,
        project.id,
        project.run_command,
    )
    return await probe_local_service(access_url)


async def _project_readiness_probe(
    project: Project,
    store: CodexApiStore | None,
) -> ProjectReadinessProbe | None:
    if store is None:
        return None
    if not callable(getattr(store, "list_codex_tasks", None)) or not callable(
        getattr(store, "load_codex_task", None)
    ):
        return None
    return await resolve_project_readiness_probe(
        store,
        project.id,
        project.run_command,
    )


async def _project_run_evaluation(
    project: Project,
    store: CodexApiStore | None,
) -> tuple[LocalServiceStatus, ApplicationReadinessStatus]:
    service = await _project_service_status(project, store)
    if store is None:
        return service, invalid_readiness_status("store_unavailable")
    readiness_probe = await _project_readiness_probe(project, store)
    if readiness_probe is None:
        return service, invalid_readiness_status("readiness_not_configured")
    evaluation = await evaluate_project_service(readiness_probe)
    return evaluation["service"], evaluation["readiness"]


async def _project_run_status_payload(
    project: Project,
    store: CodexApiStore | None,
) -> ProjectRunStatusPayload:
    service, readiness = await _project_run_evaluation(project, store)
    return add_service_status(
        project_run_manager.status(project.id),
        service,
        readiness,
    )


async def _load_startup_service(project_id: str, service_id: str) -> tuple[Project, ProjectStartupService]:
    project = await _load_project_for_run(project_id)
    store = _require_codex_store()
    services = await store.list_project_startup_services(project_id)
    for service in services:
        if service.service_id == service_id:
            return project, service
    raise HTTPException(status_code=404, detail="startup_service_not_found")


async def _startup_service_evaluation(
    service: ProjectStartupService,
) -> tuple[LocalServiceStatus, ApplicationReadinessStatus]:
    evaluation = await evaluate_project_service(
        service.readiness_probe,
        fallback_access_url=service.access_url,
    )
    return evaluation["service"], evaluation["readiness"]


async def _startup_service_status(
    project: Project, service: ProjectStartupService
) -> ProjectRunStatusPayload:
    local_service, readiness = await _startup_service_evaluation(service)
    return add_service_status(
        project_run_manager.status(project.id, service_id=service.service_id),
        local_service,
        readiness,
    )


def _startup_config_invalid_detail(service_id: str | None = None) -> dict[str, object]:
    detail: dict[str, object] = {
        "reason": "startup_config_invalid",
        "message": "Startup readiness identity is missing or invalid. Re-analyze startup configuration.",
    }
    if service_id is not None:
        detail["service_id"] = service_id
    return detail


def _occupied_service_detail(
    local_service: LocalServiceStatus,
    readiness: ApplicationReadinessStatus,
    *,
    service_id: str | None = None,
) -> dict[str, object]:
    detail: dict[str, object] = {
        "reason": "service_address_occupied",
        "url": local_service["url"],
        "http_status": local_service["http_status"],
        "readiness_state": readiness["state"],
    }
    if service_id is not None:
        detail["service_id"] = service_id
    return detail


def _startup_service_order(services: list[ProjectStartupService]) -> list[ProjectStartupService]:
    by_id = {service.service_id: service for service in services}
    ordered: list[ProjectStartupService] = []
    visited: set[str] = set()

    def visit(service: ProjectStartupService) -> None:
        if service.service_id in visited:
            return
        for dependency_id in service.depends_on:
            dependency = by_id.get(dependency_id)
            if dependency is None:
                raise HTTPException(status_code=409, detail="startup_dependency_missing")
            visit(dependency)
        visited.add(service.service_id)
        ordered.append(service)

    for service in services:
        visit(service)
    return ordered


@router.get("/projects/{project_id}/startup-config")
async def get_project_startup_config(project_id: str) -> object:
    project = await _load_project_for_run(project_id)
    if project_startup_config_service is None:
        raise HTTPException(status_code=503, detail="project_startup_config_unavailable")
    return await project_startup_config_service.get_config(project)


@router.get("/projects/{project_id}/services/{service_id}/run/status")
async def get_project_service_run_status(project_id: str, service_id: str) -> object:
    project, service = await _load_startup_service(project_id, service_id)
    return await _startup_service_status(project, service)


@router.get("/projects/{project_id}/services/{service_id}/run/logs")
async def get_project_service_run_logs(
    project_id: str, service_id: str, after: int = 0
) -> object:
    project, service = await _load_startup_service(project_id, service_id)
    return project_run_manager.get_logs(
        project.id, after=after, service_id=service.service_id
    )


@router.post("/projects/{project_id}/services/{service_id}/run/start")
async def start_project_service_run(project_id: str, service_id: str) -> object:
    project, service = await _load_startup_service(project_id, service_id)
    store = _require_codex_store()
    local_service, readiness = await _startup_service_evaluation(service)
    current = project_run_manager.status(project.id, service_id=service.service_id)
    if readiness["state"] == "invalid_config":
        raise HTTPException(
            status_code=409,
            detail=_startup_config_invalid_detail(service.service_id),
        )
    if local_service["state"] == "reachable" and not current["running"]:
        raise HTTPException(
            status_code=409,
            detail=_occupied_service_detail(
                local_service,
                readiness,
                service_id=service.service_id,
            ),
        )
    await _reconcile_project_env_file(project, store)
    try:
        started = await project_run_manager.start(
            project.id,
            service.run_command,
            str((Path(project.repo_path) / service.working_directory).resolve()),
            service_id=service.service_id,
        )
    except ProjectRunError as exc:
        detail: dict[str, object] = {"reason": exc.reason}
        if exc.pattern:
            detail["pattern"] = exc.pattern
        raise HTTPException(status_code=409, detail=detail) from exc
    local_service, readiness = await _startup_service_evaluation(service)
    return add_service_status(started, local_service, readiness)


@router.post("/projects/{project_id}/services/{service_id}/run/stop")
async def stop_project_service_run(project_id: str, service_id: str) -> object:
    project, service = await _load_startup_service(project_id, service_id)
    stopped = await project_run_manager.stop(project.id, service_id=service.service_id)
    local_service, readiness = await _startup_service_evaluation(service)
    return add_service_status(stopped, local_service, readiness)


@router.post("/projects/{project_id}/run/start-all")
async def start_all_project_services(project_id: str) -> object:
    project = await _load_project_for_run(project_id)
    store = _require_codex_store()
    services = _startup_service_order(await store.list_project_startup_services(project_id))
    if not services:
        raise HTTPException(status_code=409, detail={"reason": "no_run_command"})
    for service in services:
        local_service, readiness = await _startup_service_evaluation(service)
        managed = project_run_manager.status(project.id, service_id=service.service_id)
        if readiness["state"] == "invalid_config":
            raise HTTPException(
                status_code=409,
                detail=_startup_config_invalid_detail(service.service_id),
            )
        if local_service["state"] == "reachable" and not managed["running"]:
            raise HTTPException(
                status_code=409,
                detail=_occupied_service_detail(
                    local_service,
                    readiness,
                    service_id=service.service_id,
                ),
            )
    await _reconcile_project_env_file(project, store)
    results: list[dict[str, object]] = []
    for service in services:
        try:
            status = await project_run_manager.start(
                project.id,
                service.run_command,
                str((Path(project.repo_path) / service.working_directory).resolve()),
                service_id=service.service_id,
            )
        except ProjectRunError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "reason": exc.reason,
                    "service_id": service.service_id,
                    "started": results,
                    **({"pattern": exc.pattern} if exc.pattern else {}),
                },
            ) from exc
        local_service, readiness = await _startup_service_evaluation(service)
        results.append(
            {
                "service_id": service.service_id,
                "status": add_service_status(status, local_service, readiness),
            }
        )
    return {"services": results}


@router.post("/projects/{project_id}/run/stop-all")
async def stop_all_project_services(project_id: str) -> object:
    project = await _load_project_for_run(project_id)
    services = _startup_service_order(
        await _require_codex_store().list_project_startup_services(project_id)
    )
    results: list[dict[str, object]] = []
    for service in reversed(services):
        status = await project_run_manager.stop(project.id, service_id=service.service_id)
        local_service, readiness = await _startup_service_evaluation(service)
        results.append(
            {
                "service_id": service.service_id,
                "status": add_service_status(status, local_service, readiness),
            }
        )
    return {"services": results}


@router.post("/projects/{project_id}/run/start")
async def start_project_run(project_id: str) -> ProjectRunStatusPayload:
    project = await _load_project_for_run(project_id)
    store = _require_codex_store()
    service = await _project_service_status(project, store)
    readiness_probe = await _project_readiness_probe(project, store)
    if readiness_probe is None:
        readiness = invalid_readiness_status("readiness_not_configured")
    else:
        evaluation = await evaluate_project_service(readiness_probe)
        service = evaluation["service"]
        readiness = evaluation["readiness"]
    current = project_run_manager.status(project.id)
    if readiness["state"] == "invalid_config":
        if service["state"] == "reachable" and not current["running"]:
            await store.append_project_audit(
                project_id=project.id,
                issue_id=None,
                event="run_refused:service_address_occupied",
            )
            raise HTTPException(
                status_code=409,
                detail=_occupied_service_detail(service, readiness),
            )
        raise HTTPException(
            status_code=409,
            detail=_startup_config_invalid_detail(),
        )
    if service["state"] == "reachable" and not current["running"]:
        await store.append_project_audit(
            project_id=project.id,
            issue_id=None,
            event="run_refused:service_address_occupied",
        )
        raise HTTPException(
            status_code=409,
            detail=_occupied_service_detail(service, readiness),
        )
    run_command = project.run_command
    if not run_command or not run_command.strip():
        raise HTTPException(status_code=409, detail={"reason": "no_run_command"})
    await _reconcile_project_env_file(project, store)
    try:
        started = await project_run_manager.start(
            project.id,
            run_command,
            project.repo_path,
        )
    except ProjectRunError as exc:
        detail: dict[str, object] = {"reason": exc.reason}
        if exc.pattern:
            detail["pattern"] = exc.pattern
        raise HTTPException(status_code=409, detail=detail) from exc
    service, readiness = await _project_run_evaluation(project, store)
    return add_service_status(started, service, readiness)


@router.post("/projects/{project_id}/run/stop")
async def stop_project_run(project_id: str) -> ProjectRunStatusPayload:
    project = await _load_project_for_run(project_id)
    stopped = await project_run_manager.stop(project_id)
    service, readiness = await _project_run_evaluation(project, codex_store)
    return add_service_status(stopped, service, readiness)


@router.get("/projects/{project_id}/run/status")
async def get_project_run_status(project_id: str) -> ProjectRunStatusPayload:
    project = await _load_project_for_run(project_id)
    return await _project_run_status_payload(project, codex_store)


@router.get("/projects/{project_id}/run/logs")
async def get_project_run_logs(project_id: str, after: int = 0) -> object:
    await _load_project_for_run(project_id)
    return project_run_manager.get_logs(project_id, after=after)


# --- Project env vars endpoints (Agent-driven env config) ---

@router.get("/projects/{project_id}/env")
async def get_project_env_vars(project_id: str) -> object:
    """List stored env vars for a project. Secret values are NOT returned as
    plaintext — only ``is_set: true`` is indicated."""
    project = await _load_project_for_run(project_id)
    store = _require_codex_store()
    stored = await store.load_project_env_vars(project.id)
    env_entries: list[dict[str, object]] = []
    for sv in stored:
        entry: dict[str, object] = {
            "name": sv.name,
            "secret": sv.secret,
            "source": sv.source or "",
            "is_set": bool(sv.value.strip()) if sv.value else False,
        }
        if not sv.secret:
            entry["value"] = sv.value
        env_entries.append(entry)
    return {"env_vars": env_entries}


@router.put("/projects/{project_id}/env")
async def put_project_env_vars(project_id: str, body: JsonObject) -> object:
    """Save one or more env vars for a project. Accepts either a single var or
    ``{vars: [{name, value, secret?, source?}]}``. Secret values are encrypted
    before storage."""
    project = await _load_project_for_run(project_id)
    store = _require_codex_store()

    # Accept both {name, value, ...} and {vars: [...]}
    raw_vars: list[dict[str, object]] = []
    if isinstance(body.get("vars"), list):
        raw_vars = cast("list[dict[str, object]]", body["vars"])
    elif isinstance(body.get("name"), str):
        raw_vars = [body]

    if not raw_vars:
        raise HTTPException(status_code=422, detail="No variables provided")

    from app.application.env_crypto import encrypt, is_configured
    from app.application.env_materializer import is_secret_name

    saved: list[str] = []
    for rv in raw_vars:
        name = str(rv.get("name", "")).strip()
        if not name:
            continue
        value = str(rv.get("value", ""))
        secret = bool(rv.get("secret", False)) or is_secret_name(name)
        source = str(rv.get("source", "user"))

        # Encrypt secret values
        stored_value = value
        if secret and value.strip():
            if not is_configured():
                raise HTTPException(
                    status_code=500,
                    detail="CONSOLE_ENCRYPTION_KEY 未配置, 无法存储密钥类变量。请管理员配置后重试。",
                )
            stored_value = encrypt(value)

        await store.save_project_env_var(
            project.id,
            name,
            stored_value,
            secret=secret,
            source=source,
        )
        saved.append(name)

    await _reconcile_project_env_file(project, store)

    return {"saved": saved}


@router.delete("/projects/{project_id}/env/{name}")
async def delete_project_env_var(project_id: str, name: str) -> object:
    """Delete a single env var for a project."""
    project = await _load_project_for_run(project_id)
    store = _require_codex_store()
    await store.delete_project_env_var(project_id, name)
    await _reconcile_project_env_file(project, store)
    return {"deleted": name}


@router.get("/codex/projects/{project_id}/self-improvement-proposals")
async def list_project_self_improvement_proposals(
    project_id: str,
    issue_id: str | None = None,
    status: str | None = None,
    limit: int | None = None,
) -> JsonObject:
    store = _require_codex_store()
    await _load_project_or_self_improvement_404(project_id)
    proposals = await store.list_self_improvement_proposals(
        project_id=project_id,
        issue_id=issue_id,
        status=status,
        limit=limit,
    )
    return {"proposals": [_serialize_self_improvement_proposal(proposal) for proposal in proposals]}


@router.patch("/codex/projects/{project_id}/self-improvement-proposals/{proposal_id}")
async def update_project_self_improvement_proposal_status(
    project_id: str,
    proposal_id: str,
    request: SelfImprovementProposalStatusRequest,
) -> JsonObject:
    store = _require_codex_store()
    proposal = await _load_self_improvement_proposal_for_project(project_id, proposal_id)
    _validate_self_improvement_status_transition(proposal.status, request.status)
    updated = await store.update_self_improvement_proposal_status(proposal_id, request.status)
    if updated is None:
        raise HTTPException(status_code=404, detail="Self-improvement proposal not found")
    return _serialize_self_improvement_proposal(updated)


@router.post("/codex/projects/{project_id}/self-improvement-proposals/{proposal_id}/apply-plan")
async def get_project_self_improvement_proposal_apply_plan(project_id: str, proposal_id: str) -> object:
    proposal = await _load_self_improvement_proposal_for_project(project_id, proposal_id)
    if proposal.status != "accepted":
        raise HTTPException(
            status_code=409,
            detail="Self-improvement proposal must be accepted before building an apply plan",
        )
    return {
        "proposal": _serialize_self_improvement_proposal(proposal),
        "plan": build_self_improvement_apply_plan(proposal),
    }


@router.get(
    "/codex/projects/{project_id}/self-improvement-proposals/{proposal_id}/applications"
)
async def list_project_self_improvement_proposal_applications(
    project_id: str,
    proposal_id: str,
) -> JsonObject:
    store = _require_codex_store()
    await _load_self_improvement_proposal_for_project(project_id, proposal_id)
    events = await store.list_self_improvement_application_events(
        project_id=project_id,
        proposal_id=proposal_id,
        limit=100,
    )
    return {"applications": [_serialize_self_improvement_application(event) for event in events]}


@router.post("/codex/projects/{project_id}/self-improvement-proposals/{proposal_id}/apply")
async def apply_project_self_improvement_proposal(
    project_id: str,
    proposal_id: str,
    request: SelfImprovementApplyRequest,
) -> JsonObject:
    store = _require_codex_store()
    project = await _load_project_or_self_improvement_404(project_id)
    proposal = await _load_self_improvement_proposal_for_project(project_id, proposal_id)
    try:
        result = apply_project_memory_proposal(
            project_repo_path=project.repo_path,
            proposal=proposal,
            reviewed_content_sha256=request.content_sha256,
        )
    except SelfImprovementApplyError as exc:
        await _save_self_improvement_application_event(
            proposal=proposal,
            action="apply",
            status="failed",
            content_sha256=request.content_sha256,
            error=exc.message,
        )
        raise HTTPException(
            status_code=_self_improvement_apply_status(exc),
            detail=exc.message,
        ) from exc

    updated = await store.update_self_improvement_proposal_status(proposal.id, "applied")
    if updated is None:
        raise HTTPException(status_code=404, detail="Self-improvement proposal not found")
    event = await _save_self_improvement_application_event(
        proposal=updated,
        action="apply",
        status="succeeded",
        path=result.path,
        content_sha256=result.content_sha256,
        result=result.to_dict(),
    )
    return {
        "proposal": _serialize_self_improvement_proposal(updated),
        "application": _serialize_self_improvement_application(event),
    }


@router.post("/codex/projects/{project_id}/self-improvement-proposals/{proposal_id}/rollback")
async def rollback_project_self_improvement_proposal(project_id: str, proposal_id: str) -> object:
    store = _require_codex_store()
    project = await _load_project_or_self_improvement_404(project_id)
    proposal = await _load_self_improvement_proposal_for_project(project_id, proposal_id)
    try:
        result = rollback_project_memory_proposal(
            project_repo_path=project.repo_path,
            proposal=proposal,
        )
    except SelfImprovementApplyError as exc:
        await _save_self_improvement_application_event(
            proposal=proposal,
            action="rollback",
            status="failed",
            error=exc.message,
        )
        raise HTTPException(
            status_code=_self_improvement_apply_status(exc),
            detail=exc.message,
        ) from exc

    updated = await store.update_self_improvement_proposal_status(proposal.id, "accepted")
    if updated is None:
        raise HTTPException(status_code=404, detail="Self-improvement proposal not found")
    event = await _save_self_improvement_application_event(
        proposal=updated,
        action="rollback",
        status="succeeded",
        path=result.path,
        content_sha256=result.content_sha256,
        result=result.to_dict(),
    )
    return {
        "proposal": _serialize_self_improvement_proposal(updated),
        "rollback": result.to_dict(),
        "application": _serialize_self_improvement_application(event),
    }


@router.post("/codex/projects/{project_id}/self-improvement-proposals/{proposal_id}/activate-task")
async def activate_project_self_improvement_proposal_task(
    project_id: str,
    proposal_id: str,
    request: SelfImprovementActivateRequest | None = None,
) -> JsonObject:
    store = _require_agent_store()
    project = await _load_project_or_self_improvement_404(project_id)
    proposal = await _load_self_improvement_proposal_for_project(project_id, proposal_id)
    if proposal.status != "accepted":
        raise HTTPException(
            status_code=409,
            detail="Self-improvement proposal must be accepted before activation",
        )
    if proposal.target_kind == "project_memory":
        raise HTTPException(
            status_code=409,
            detail="project_memory proposals are applied directly, not activated as PR tasks",
        )
    source_issue = await store.load_codex_issue(proposal.issue_id)
    if source_issue is None:
        raise HTTPException(status_code=409, detail="Self-improvement source issue not found")

    existing_issue, existing_event = await _find_self_improvement_activation_issue(proposal)
    already_created = existing_issue is not None
    issue = existing_issue
    application_event = existing_event

    if issue is None:
        now = datetime.now()
        issue = CodexIssue(
            id=str(uuid4()),
            session_id=source_issue.session_id,
            project_id=project.id,
            title=f"Apply self-improvement proposal: {proposal.title}",
            description=_self_improvement_issue_description(proposal),
            current_phase="requirements",
            status="open",
            executor=source_issue.executor,
            provider=source_issue.provider,
            model=source_issue.model,
            created_at=now,
            updated_at=now,
        )
        try:
            branch, worktree_path, base = await worktree_manager.prepare_issue_worktree(
                project,
                issue,
            )
        except (GitError, WorktreeError) as exc:
            await _save_self_improvement_application_event(
                proposal=proposal,
                action="open_pr_task",
                status="failed",
                error=str(exc),
            )
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        issue.git_branch = branch
        issue.git_worktree_path = worktree_path
        issue.git_base_branch = base
        await store.save_codex_issue(issue)
        application_event = await _save_self_improvement_application_event(
            proposal=proposal,
            action="open_pr_task",
            status="succeeded",
            path=f"codex_issues/{issue.id}",
            result={
                "issue_id": issue.id,
                "issue_title": issue.title,
                "git_branch": issue.git_branch,
                "git_base_branch": issue.git_base_branch,
                "git_worktree_path": issue.git_worktree_path,
            },
        )

    activation: dict[str, object] = {
        "already_created": already_created,
        "issue": issue.model_dump(mode="json"),
    }
    if application_event is not None:
        activation["application"] = _serialize_self_improvement_application(application_event)

    if request and request.start_conductor:
        try:
            conductor_result = await _start_issue_conductor_graph(issue.id, store=store)
        except Exception as exc:
            await _save_self_improvement_application_event(
                proposal=proposal,
                action="start_conductor",
                status="failed",
                path=f"codex_issues/{issue.id}",
                error=str(exc),
            )
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        activation["conductor"] = conductor_result
        conductor_event_result = dict(conductor_result)
        conductor_graph = conductor_result.get("graph")
        if isinstance(conductor_graph, dict) and isinstance(conductor_graph.get("id"), str):
            conductor_event_result["graph_id"] = conductor_graph["id"]
        await _save_self_improvement_application_event(
            proposal=proposal,
            action="start_conductor",
            status="succeeded",
            path=f"codex_issues/{issue.id}",
            result=conductor_event_result,
        )

    return {
        "proposal": _serialize_self_improvement_proposal(proposal),
        "activation": activation,
    }


async def activate_self_improvement_proposal_task(
    project_id: str,
    proposal_id: str,
    *,
    start_conductor: bool = False,
) -> JsonObject:
    return await activate_project_self_improvement_proposal_task(
        project_id,
        proposal_id,
        SelfImprovementActivateRequest(start_conductor=start_conductor),
    )


@router.get("/projects/{project_id}/resume", response_model=ResumeResponse)
async def get_project_resume(project_id: str) -> object:
    project = await _get_project_or_404(project_id)
    try:
        return _resume_response(project.id, resume_service.read(project.repo_path))
    except ResumeProjectPathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ResumeValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/projects/{project_id}/resume", response_model=ResumeResponse)
async def update_project_resume(project_id: str, request: UpdateResumeRequest) -> object:
    project = await _get_project_or_404(project_id)
    try:
        return _resume_response(project.id, resume_service.write(project.repo_path, request.markdown))
    except ResumeProjectPathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ResumeValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/projects/{project_id}/resume/import-pdf", response_model=ResumeImportResponse)
async def import_project_resume_pdf(
    project_id: str,
    file: UploadFile = File(...),
) -> ResumeImportResponse:
    project = await _get_project_or_404(project_id)
    data = await file.read(MAX_PDF_IMPORT_BYTES + 1)
    try:
        draft = resume_service.extract_pdf_text(
            filename=file.filename,
            content_type=file.content_type,
            data=data,
        )
    except ResumeDependencyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ResumeValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        await file.close()
    return ResumeImportResponse(
        project_id=project.id,
        markdown=draft.markdown,
        source_filename=draft.source_filename,
        page_count=draft.page_count,
        extracted_pages=draft.extracted_pages,
        size_bytes=draft.size_bytes,
        warnings=draft.warnings,
    )


@router.post("/projects/{project_id}/script-suggestion")
async def suggest_project_script(project_id: str, request: ScriptSuggestionRequest) -> object:
    svc = _require_project_service()
    try:
        project = await svc.get(project_id)
    except ProjectError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    from app.application.llm_runner import build_llm_runner

    async def no_op_runner(prompt: str) -> str | None:
        return None

    existing_setup_script = request.setup_script
    if existing_setup_script is None:
        existing_setup_script = project.setup_script

    existing_run_command = request.run_command
    if existing_run_command is None:
        existing_run_command = project.run_command

    try:
        llm_runner = build_llm_runner(_get_runtime_catalog_service(), trace_store=_require_codex_store())

        async def _run_prompt(prompt: str) -> str | None:
            return await llm_runner(prompt)

        active_runner = _run_prompt
    except Exception:
        active_runner = no_op_runner

    suggestion = await suggest_project_scripts(
        project=project,
        runner=active_runner,
        existing_setup_script=existing_setup_script,
        existing_run_command=existing_run_command,
        verify=request.verify,
    )

    if suggestion is None:
        return {
            "setup_script": existing_setup_script or "",
            "run_command": existing_run_command or "",
            "agent_name": "Operations Engineer",
            "access_url": None,
            "notes": ["Operations Engineer could not infer a suggestion."],
            "verification": None,
        }

    return suggestion.model_dump()


@router.post("/projects/{project_id}/script-task")
async def start_project_script_task(project_id: str, request: ScriptTaskRequest) -> object:
    store = _require_codex_store()
    svc = _require_project_service()
    try:
        project = await svc.get(project_id)
    except ProjectError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    async def _ensure_project_script_workspace() -> str:
        load_workspace_raw = getattr(store, "load_codex_workspace", None)
        save_workspace_raw = getattr(store, "save_codex_workspace", None)
        if not callable(load_workspace_raw) or not callable(save_workspace_raw):
            return project.id
        load_workspace = cast(LoadCodexWorkspaceFn, load_workspace_raw)
        save_workspace = cast(SaveCodexWorkspaceFn, save_workspace_raw)
        existing_workspace = await load_workspace(project.id)
        if existing_workspace is not None:
            return project.id
        from app.domain.models import CodexWorkspace

        now = datetime.now()
        workspace = CodexWorkspace(
            id=project.id,
            title=project.name,
            cwd=project.repo_path,
            project_id=project.id,
            status="idle",
            created_at=now,
            last_active_at=now,
            log_path=None,
            messages=[],
        )
        await save_workspace(workspace)
        await event_bus.append(
            {
                "type": "session_created",
                "session": {
                    "id": workspace.id,
                    "title": workspace.title,
                    "project_id": workspace.project_id,
                    "status": workspace.status,
                },
            }
        )
        return project.id

    existing_tasks = await store.list_codex_tasks(project_id=project.id)
    sorted_existing_tasks = sorted(
        existing_tasks or [],
        key=lambda row: str(row.get("updated_at") or row.get("created_at") or ""),
        reverse=True,
    )

    def _is_reusable_script_task_status(status: object | None) -> bool:
        return is_task_pending_status(status) or is_task_active_status(status)

    async def _active_execution_process_known(task_id: str, execution_process_id: str | None) -> bool | None:
        if not execution_process_id:
            return False
        try:
            processes = await store.list_execution_processes(task_id=task_id)
        except TypeError:
            processes = await store.list_execution_processes()
        active_statuses = {"running", "starting", "pending", "queued"}
        for process in processes or []:
            if str(getattr(process, "id", "") or "") != execution_process_id:
                continue
            return str(getattr(process, "status", "") or "").lower() in active_statuses
        return False

    async def _mark_stale_script_task_failed(
        task: CodexTask,
        execution_process_id: str | None,
    ) -> None:
        task.status = "failed"
        task.result = (
            "Stale project script task was still marked active, but no active "
            "execution process exists; starting a fresh Operations Engineer task."
        )
        task.updated_at = datetime.now()
        await store.save_codex_task(task)
        await event_bus.append(
            build_task_status_event(
                task,
                "failed",
                result=task.result,
                execution_process_id=execution_process_id,
            )
        )

    for row in sorted_existing_tasks:
        if row.get("task_kind") != "project_script_suggestion":
            continue
        row_id = _optional_str(row.get("id"))
        if row_id is None:
            continue
        row_role = row.get("role")
        if row_role is not None and row_role != "operations_engineer":
            continue
        if not _is_reusable_script_task_status(row.get("status")):
            continue
        existing_task = None
        load_task = getattr(codex_store, "load_codex_task", None)
        if callable(load_task):
            existing_task = await load_task(row_id)
        if (
            existing_task is not None
            and getattr(existing_task, "role", None) is not None
            and getattr(existing_task, "role", None) != "operations_engineer"
        ):
            continue
        if existing_task is not None and not _is_reusable_script_task_status(
            existing_task.status
        ):
            continue
        reused_status = _required_str(row.get("status"), "running")
        reused_title = _required_str(row.get("title"), "Generate Startup Scripts")
        reused_execution_process_id = _optional_str(row.get("last_execution_process_id"))
        if existing_task is not None:
            reused_status = existing_task.status or reused_status
            reused_title = existing_task.title or reused_title
            reused_execution_process_id = (
                existing_task.last_execution_process_id or reused_execution_process_id
            )
        active_process = await _active_execution_process_known(row_id, reused_execution_process_id)
        if (
            active_process is not False
            and project_startup_mcp_service is not None
            and not project_startup_mcp_service.has_task_session(row_id)
        ):
            active_process = False
        if active_process is False:
            if existing_task is not None:
                await _mark_stale_script_task_failed(existing_task, reused_execution_process_id)
            else:
                await event_bus.append(
                    {
                        "type": "task_status",
                        "task_id": row_id,
                        "project_id": project.id,
                        "issue_id": None,
                        "workspace_id": project.id,
                        "session_id": project.id,
                        "role": _required_str(row.get("role"), "operations_engineer"),
                        "task_kind": _required_str(
                            row.get("task_kind"), "project_script_suggestion"
                        ),
                        "status": "failed",
                        "result": (
                            "Stale project script task was still marked active, but no active "
                            "execution process exists; starting a fresh Operations Engineer task."
                        ),
                        "review_comment": row.get("review_comment"),
                        "execution_process_id": reused_execution_process_id,
                    }
                )
            continue
        if existing_task is not None:
            await event_bus.append(
                build_task_status_event(
                    existing_task,
                    reused_status,
                    execution_process_id=reused_execution_process_id,
                )
            )
        else:
            await event_bus.append(
                {
                    "type": "task_status",
                    "task_id": row_id,
                    "project_id": project.id,
                    "issue_id": None,
                    "workspace_id": project.id,
                    "session_id": project.id,
                    "role": _required_str(row.get("role"), "operations_engineer"),
                    "task_kind": _required_str(
                        row.get("task_kind"), "project_script_suggestion"
                    ),
                    "status": reused_status,
                    "result": row.get("result"),
                    "review_comment": row.get("review_comment"),
                    "execution_process_id": reused_execution_process_id,
                }
            )
        return ScriptTaskResponse(
            task_id=row_id,
            status=reused_status,
            title=reused_title,
            execution_process_id=reused_execution_process_id,
            reused=True,
        )

    resolved_executor, resolved_provider, resolved_model, _, _ = await _resolve_runtime_config(
        "claude",
        request.provider,
        request.model,
    )
    task_id = str(uuid4())
    workspace_id = await _ensure_project_script_workspace()
    existing_setup_script = (
        request.setup_script if request.setup_script is not None else project.setup_script
    ) or ""
    existing_run_command = (
        request.run_command if request.run_command is not None else project.run_command
    ) or ""
    request_context = json.dumps(
        {
            "setup_script": existing_setup_script,
            "run_command": existing_run_command,
        },
        ensure_ascii=False,
    )
    prompt = (
        "Generate startup scripts for this project. "
        "Return setup_script and run_command as the Operations Engineer. "
        f"Operations request context JSON: {request_context}"
    )
    task = CodexTask(
        id=task_id,
        session_id=workspace_id,
        project_id=project.id,
        issue_id=None,
        phase="operations",
        title="Generate Startup Scripts",
        prompt=prompt,
        role="operations_engineer",
        executor=resolved_executor,
        provider=resolved_provider,
        model=resolved_model,
        status="pending",
        result=None,
        parent_task_id=None,
        task_kind="project_script_suggestion",
        workspace_path=project.repo_path,
        git_branch=project.default_branch,
        git_base_branch=project.default_branch,
        git_worktree_path=None,
        resume_session_id=None,
        resume_message_id=None,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    await store.save_codex_task(task)
    await event_bus.append(
        {
            "type": "task_created",
            "task": _serialize_task_payload(task),
            "project_id": project.id,
            "workspace_id": project.id,
            "session_id": project.id,
            "role": "operations_engineer",
            "task_kind": "project_script_suggestion",
        }
    )
    mcp_session = None
    command_args_override: list[str] | None = None
    if project_startup_mcp_service is None:
        task.status = "failed"
        task.result = "project startup MCP is unavailable"
        task.updated_at = datetime.now()
        await store.save_codex_task(task)
        raise HTTPException(status_code=503, detail=task.result)
    mcp_session = project_startup_mcp_service.open_session(project=project, task_id=task.id)
    command_args_override = [
        "--mcp-config",
        mcp_session.claude_config(timeouts.project_startup_mcp_endpoint()),
        "--strict-mcp-config",
    ]
    try:
        exec_process = await _get_task_runner().start_task_run(
            task,
            command_args_override=command_args_override,
        )
        task.status = "running"
        task.last_execution_process_id = exec_process.id
        task.updated_at = datetime.now()
        await store.save_codex_task(task)
        await event_bus.append(
            build_task_status_event(
                task,
                "running",
                execution_process_id=exec_process.id,
            )
        )
        return ScriptTaskResponse(
            task_id=task.id,
            status="running",
            title=task.title,
            execution_process_id=exec_process.id,
            reused=False,
        )
    except ValueError as exc:
        project_startup_mcp_service.close_task_session(task.id)
        task.status = "failed"
        task.result = str(exc)
        task.updated_at = datetime.now()
        await store.save_codex_task(task)
        await event_bus.append(
            build_task_status_event(task, "failed", result=task.result)
        )
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        project_startup_mcp_service.close_task_session(task.id)
        task.status = "failed"
        task.result = str(exc)
        task.updated_at = datetime.now()
        await store.save_codex_task(task)
        await event_bus.append(
            build_task_status_event(task, "failed", result=task.result)
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/projects/{project_id}")
async def delete_project(project_id: str, force: bool = False) -> object:
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
        raise HTTPException(status_code=404, detail=str(exc)) from exc
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
        workspace_id = _optional_str(ws.get("id"))
        if workspace_id is None:
            continue
        with suppress(Exception):
            await _cleanup_session_worktrees(workspace_id, project_id)
        await codex_store.delete_codex_session(workspace_id)
    # Best-effort: remove the now-empty `<name>-worktrees/` parent so the user's
    # filesystem doesn't accumulate empty bookkeeping dirs.
    worktree_parent = Path(project.repo_path).parent / f"{project.name}-worktrees"
    if worktree_parent.exists() and not any(worktree_parent.iterdir()):
        with suppress(OSError):
            worktree_parent.rmdir()
    await svc.delete(project_id)
    return {"deleted": project_id, "cascaded_sessions": len(related_sessions)}


@router.get("/projects/{project_id}/branches")
async def get_project_branches(project_id: str) -> object:
    svc = _require_project_service()
    try:
        return await svc.list_branches(project_id)
    except ProjectError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GitError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/projects/{project_id}/stats")
async def get_project_stats(project_id: str) -> object:
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
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    workspaces = await codex_store.list_codex_sessions(project_id=project_id)
    issues = await codex_store.list_codex_issues(project_id=project_id)
    counts = {"open": 0, "merged": 0, "abandoned": 0}
    for issue in issues:
        # Load full issue to get git_merge_status (list query strips it).
        issue_id = _optional_str(issue.get("id"))
        if issue_id is None:
            continue
        full = await codex_store.load_codex_issue(issue_id)
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


@router.get("/projects/{project_id}/remote-status")
async def get_project_remote_status(project_id: str, fetch: bool = True) -> object:
    svc = _require_project_service()
    try:
        return await svc.remote_status(project_id, do_fetch=fetch)
    except ProjectError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/projects/{project_id}/pull")
async def pull_project(project_id: str) -> object:
    svc = _require_project_service()
    try:
        result = await svc.fast_forward_pull(project_id)
    except ProjectError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GitError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if not result.get("success"):
        raise HTTPException(status_code=409, detail=result)
    return result


@router.get("/codex/stats")
async def get_codex_stats() -> object:
    """Aggregate counts across all Codex sessions and issues.

    Returns workspace/session counts, task metrics bucketed by status,
    and executor availability flags. Computed on-demand; no persistence.
    """
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")

    sessions = await codex_store.list_codex_sessions(project_id=None)
    issues = await codex_store.list_codex_issues(project_id=None)
    tasks = await codex_store.list_codex_tasks()

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

    for task in tasks:
        tasks_total += 1
        status = task.get("status", "pending")
        if is_task_pending_status(status):
            tasks_pending += 1
        elif is_task_active_status(status):
            tasks_running += 1
        elif is_task_success_status(status):
            tasks_completed += 1
        elif is_task_failure_status(status):
            tasks_failed += 1

        updated_at = _task_time(task.get("updated_at") or task.get("created_at"))
        if updated_at and (last_activity_at is None or updated_at > last_activity_at):
            last_activity_at = updated_at

    for issue in issues:
        # Track most recent activity timestamp
        updated_at = _task_time(issue.get("updated_at") or issue.get("created_at"))
        if updated_at and (last_activity_at is None or updated_at > last_activity_at):
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
        logger.debug("executor availability probe failed", exc_info=True)

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
async def get_project_audit(project_id: str, limit: int = 50, since: str | None = None) -> object:
    """Recent project events (most recent first).

    `since` is an ISO-8601 timestamp; entries strictly older than it are skipped.
    """
    svc = _require_project_service()
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    try:
        await svc.get(project_id)
    except ProjectError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return await codex_store.list_project_audit(
        project_id, limit=max(1, min(limit, 200)), since=since,
    )


@router.post("/projects/{project_id}/repair")
async def repair_project(project_id: str) -> object:
    """Reconcile DB worktree paths with what git + disk actually have.

    - Prunes stale `.git/worktrees/*` metadata.
    - For every issue under the project: if its `git_worktree_path` no longer
      exists on disk, clear the DB fields so the next task creation rebuilds it.
    """
    svc = _require_project_service()
    store = _require_codex_store()
    try:
        project = await svc.get(project_id)
    except ProjectError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        await worktree_manager.prune(project)
    except GitError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    issues = await store.list_codex_issues(project_id=project_id)
    live_issue_ids = {issue_id for i in issues if (issue_id := _optional_str(i.get("id")))}
    repaired = 0
    for issue_dict in issues:
        issue_id = _optional_str(issue_dict.get("id"))
        if issue_id is None:
            continue
        issue = await store.load_codex_issue(issue_id)
        if issue is None:
            continue
        # Reset when EITHER the on-disk worktree is gone, OR the branch ref
        # has been deleted from the repo (covers `git branch -D` mishaps).
        git_worktree_path = issue.git_worktree_path
        git_branch = issue.git_branch
        worktree_missing = git_worktree_path is not None and not Path(git_worktree_path).exists()
        branch_missing = git_branch is not None and not await git_service.branch_exists(project.repo_path, git_branch)
        if not (worktree_missing or branch_missing):
            continue
        issue.git_branch = None
        issue.git_base_branch = None
        issue.git_worktree_path = None
        issue.git_last_commit_sha = None
        await store.save_codex_issue(issue)
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
            with suppress(Exception):
                await git_service.remove_worktree(project.repo_path, entry)
            with suppress(OSError):
                shutil.rmtree(entry, ignore_errors=True)
                orphans_removed += 1
    return {"pruned": True, "issues_reset": repaired, "orphan_dirs_removed": orphans_removed}


# --- Codex CLI Session APIs ---


class CreateCodexSessionRequest(BaseModel):
    title: str
    project_id: str
    cwd: str = ""


@router.get("/codex/version")
async def get_codex_version(request: Request) -> object:
    """Return Codex service version and startup time."""
    return {
        "version": "0.1.0",
        "started_at": request.app.state.started_at,
    }


@router.get("/codex/status")
async def codex_status() -> object:
    """Check if local codex CLI is available."""
    available = check_codex_available()
    return {"available": available, "binary": "codex"}


@router.get("/codex/workspaces")
@router.get("/codex/sessions")
async def list_codex_workspaces(project_id: str | None = None) -> object:
    """List all console-managed Codex workspaces, optionally filtered by project."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    return await codex_store.list_codex_workspaces(project_id=project_id)


list_codex_sessions = list_codex_workspaces


@router.post("/codex/workspaces", status_code=201)
@router.post("/codex/sessions", status_code=201)
async def create_codex_workspace(request: CreateCodexSessionRequest) -> object:
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
    logger.info("Creating workspace: workspace_id=%s project_id=%s", workspace_id, request.project_id)
    await codex_store.save_codex_workspace(workspace)
    # Broadcast new workspace
    await event_bus.append({
        "type": "session_created",
        "session": {"id": workspace.id, "title": workspace.title, "project_id": workspace.project_id, "status": workspace.status}
    })
    logger.info("Workspace created and broadcasted: workspace_id=%s", workspace_id)
    return workspace


create_codex_session = create_codex_workspace


@router.get("/codex/workspaces/{workspace_id}")
@router.get("/codex/sessions/{workspace_id}")
async def get_codex_workspace(workspace_id: str) -> object:
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
async def get_workspace_execution_processes(workspace_id: str) -> object:
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
async def get_codex_workspace_logs(workspace_id: str, limit: int = 1000) -> object:
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
async def update_codex_task(task_id: str, request: UpdateCodexTaskRequest) -> object:
    """Update a task's mutable fields. Supports executor, provider, and model."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    task = await codex_store.load_codex_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")

    if is_task_active_status(task.status):
        raise HTTPException(status_code=409, detail="Cannot update an active task")

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
    except RuntimeCatalogValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    task.executor = resolved_executor
    task.provider = resolved_provider
    task.model = resolved_model
    task.updated_at = datetime.now()
    await codex_store.save_codex_task(task)

    return task


@router.get("/codex/tasks/{task_id}/messages")
async def get_codex_task_messages(task_id: str) -> object:
    """Get the conversation history for a task."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    task = await codex_store.load_codex_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
    return await codex_store.list_codex_task_messages(task_id)


@router.post("/codex/tasks/{task_id}/request-help")
async def request_codex_task_help(task_id: str, request: RequestTaskHelpRequest) -> object:
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")

    task = await codex_store.load_codex_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
    if task.task_kind == "help_child":
        raise HTTPException(status_code=409, detail="Help child tasks cannot request help")
    if is_task_waiting_for_help_status(task.status):
        raise HTTPException(status_code=409, detail="Task is already waiting for help")
    if request.target_executor == task.executor:
        raise HTTPException(status_code=400, detail="Target executor must differ from task executor")
    if not is_task_active_status(task.status):
        raise HTTPException(
            status_code=409,
            detail="Task must be running or responding to request help",
        )

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
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found") from exc
    except Exception as exc:
        logger.error("Failed to request help for task %s: %s", task_id, exc)
        raise HTTPException(status_code=500, detail=f"Failed to request help: {exc}") from exc

    parent_task = await codex_store.load_codex_task(task.id)
    child_task = await codex_store.load_codex_task(help_request.child_task_id)
    return {
        "help_request": help_request,
        "parent_task": parent_task,
        "child_task": child_task,
    }


@router.post("/codex/workspaces/{workspace_id}/input")
@router.post("/codex/sessions/{workspace_id}/input")
async def send_workspace_input(workspace_id: str, request: SendInputRequest) -> object:
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
        raise HTTPException(status_code=500, detail=f"failed to create chat worktree: {exc}") from exc
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
    except ValueError as exc:
        logger.warning("Conflict starting task for workspace %s: %s", workspace_id, exc)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Failed to start task for workspace %s: %s", workspace_id, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


send_codex_input = send_workspace_input


@router.post("/codex/workspaces/{workspace_id}/terminate")
@router.post("/codex/sessions/{workspace_id}/terminate")
async def terminate_codex_workspace(workspace_id: str) -> object:
    """Terminate a running codex process."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    mgr = get_codex_process_manager()
    try:
        return await mgr.terminate(workspace_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


terminate_codex_session = terminate_codex_workspace

@router.delete("/codex/workspaces")
@router.delete("/codex/sessions")
async def delete_all_codex_workspaces() -> object:
    """Delete all codex workspaces and their logs. Terminates any running processes first."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    workspaces = await codex_store.list_codex_workspaces()
    mgr = get_codex_process_manager()
    for workspace in workspaces:
        workspace_id = _optional_str(workspace.get("id"))
        if workspace_id is None:
            continue
        with suppress(KeyError):
            await mgr.terminate(workspace_id)
        await _cleanup_session_worktrees(workspace_id, _optional_str(workspace.get("project_id")))
        await codex_store.delete_codex_workspace(workspace_id)
    return {"deleted": len(workspaces)}


delete_all_codex_sessions = delete_all_codex_workspaces


@router.delete("/codex/workspaces/{workspace_id}")
@router.delete("/codex/sessions/{workspace_id}")
async def delete_codex_workspace(workspace_id: str) -> object:
    """Delete a codex workspace, all its tasks, workspaces, and logs."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    workspace = await codex_store.load_codex_workspace(workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' not found")
    # Terminate if running first
    mgr = get_codex_process_manager()
    with suppress(KeyError):
        await mgr.terminate(workspace_id)
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


def _normalize_acceptance_criteria(value: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        criterion = item.strip()
        if not criterion or criterion in seen:
            continue
        seen.add(criterion)
        normalized.append(criterion)
    return normalized


class CreateIssueRequest(BaseModel):
    session_id: str
    title: str
    description: str | None = None
    acceptance_criteria: list[str] = Field(default_factory=list)
    acceptance_criteria_confirmed: bool = False
    base_branch: str | None = None  # Override fork point (defaults to project.default_branch)

    @field_validator("acceptance_criteria")
    @classmethod
    def normalize_acceptance_criteria(cls, value: list[str]) -> list[str]:
        return _normalize_acceptance_criteria(value)

    @model_validator(mode="after")
    def require_confirmed_criteria(self) -> "CreateIssueRequest":
        if self.acceptance_criteria_confirmed and not self.acceptance_criteria:
            raise ValueError("confirmed acceptance criteria must include at least one item")
        return self


class ConfirmIssueAcceptanceCriteriaRequest(BaseModel):
    acceptance_criteria: list[str] = Field(min_length=1)

    @field_validator("acceptance_criteria")
    @classmethod
    def normalize_acceptance_criteria(cls, value: list[str]) -> list[str]:
        return _normalize_acceptance_criteria(value)

    @model_validator(mode="after")
    def require_criteria(self) -> "ConfirmIssueAcceptanceCriteriaRequest":
        if not self.acceptance_criteria:
            raise ValueError("acceptance criteria must include at least one item")
        return self


class UpdateIssuePhaseRequest(BaseModel):
    current_phase: str


class UpdateIssuePinRequest(BaseModel):
    is_pinned: bool


@router.post("/codex/issues", status_code=201)
async def create_codex_issue(request: CreateIssueRequest) -> CodexIssue:
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
        acceptance_criteria=request.acceptance_criteria,
        acceptance_criteria_confirmed=request.acceptance_criteria_confirmed,
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
        raise HTTPException(status_code=500, detail=f"failed to create issue worktree: {exc}") from exc
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
async def list_codex_issues(session_id: str | None = None, project_id: str | None = None) -> object:
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    return await codex_store.list_codex_issues(session_id=session_id, project_id=project_id)


@router.get("/codex/issues/{issue_id}")
async def get_codex_issue(issue_id: str) -> object:
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    issue = await codex_store.load_codex_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail=f"Issue '{issue_id}' not found")
    return issue


@router.post("/codex/issues/{issue_id}/phase")
async def update_codex_issue_phase(issue_id: str, request: UpdateIssuePhaseRequest) -> object:
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


@router.post(
    "/codex/issues/{issue_id}/acceptance-criteria/confirm",
    response_model=CodexIssue,
)
async def confirm_issue_acceptance_criteria(
    issue_id: str,
    request: ConfirmIssueAcceptanceCriteriaRequest,
) -> CodexIssue:
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    issue = await codex_store.load_codex_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail=f"Issue '{issue_id}' not found")
    if issue.acceptance_criteria_confirmed:
        raise HTTPException(
            status_code=409,
            detail="Acceptance criteria are already confirmed and cannot be changed",
        )
    if issue.status in {"abandoned", "completed", "done", "merged"}:
        raise HTTPException(
            status_code=409,
            detail="Acceptance criteria cannot be confirmed after the issue is closed",
        )

    issue.acceptance_criteria = list(request.acceptance_criteria)
    issue.acceptance_criteria_confirmed = True
    issue.updated_at = datetime.now()
    await codex_store.save_codex_issue(issue)
    if issue.project_id:
        await codex_store.append_project_audit(
            project_id=issue.project_id,
            issue_id=issue.id,
            event=f"acceptance_criteria_confirmed:{len(issue.acceptance_criteria)}",
        )
    await event_bus.append(
        {
            "type": "issue_updated",
            "issue_id": issue.id,
            "session_id": issue.session_id,
            "project_id": issue.project_id,
            "status": issue.status,
        }
    )
    return issue


@router.post("/codex/issues/{issue_id}/pin")
async def update_codex_issue_pin(issue_id: str, request: UpdateIssuePinRequest) -> object:
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
async def duplicate_codex_issue(issue_id: str) -> object:
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
        acceptance_criteria=list(issue.acceptance_criteria),
        acceptance_criteria_confirmed=issue.acceptance_criteria_confirmed,
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
                raise HTTPException(status_code=500, detail=f"failed to create issue worktree: {exc}") from exc
    await codex_store.save_codex_issue(new_issue)
    return new_issue


@router.get("/codex/issues/{issue_id}/artifacts")
async def get_codex_issue_artifacts(issue_id: str) -> list[JsonObject]:
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
        row_path = row.get("path")
        if not isinstance(row_path, str):
            continue
        path = Path(row_path)
        if path.is_symlink():
            continue
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
async def download_issue_artifacts_zip(issue_id: str) -> object:
    artifacts = await get_codex_issue_artifacts(issue_id)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for artifact in artifacts:
            artifact_path = artifact.get("path")
            artifact_name = artifact.get("name")
            if not isinstance(artifact_path, str) or not isinstance(artifact_name, str):
                continue
            path = Path(artifact_path)
            if path.is_symlink() or not path.is_file():
                continue
            try:
                archive.write(path, arcname=artifact_name)
            except OSError:
                continue
    buffer.seek(0)
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{issue_id}-artifacts.zip"'},
    )


async def _scan_and_backfill_artifacts(
    issue_id: str,
    session_id: str,
    store: CodexApiStore,
) -> list[JsonObject]:
    """Scan disk for artifacts and backfill the database."""
    workspace = await store.load_codex_workspace(session_id)
    if workspace is None:
        return []

    tasks = await store.list_codex_tasks(session_id=session_id, issue_id=issue_id)
    # Sort newest first so that when scanning multiple roots, newer artifacts take precedence
    sorted_tasks = sorted(
        tasks,
        key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""),
        reverse=True,
    )

    # Build ordered, deduplicated list of issue roots to scan.
    seen_wp: set[str] = set()
    issue_roots: list[Path] = []
    for task_row in sorted_tasks:
        wp = task_row.get("workspace_path")
        if isinstance(wp, str) and wp and wp not in seen_wp:
            seen_wp.add(wp)
            issue_roots.append(Path(wp) / "issues" / issue_id)
    fallback_root = Path(workspace.cwd) / "issues" / issue_id
    if str(fallback_root) not in {str(r) for r in issue_roots}:
        issue_roots.append(fallback_root)

    # PM backfill: for each successful pm task, check its own worktree for prd files
    # and trigger persist_result if missing.
    for task_row in sorted_tasks:
        if task_row.get("role") != "product_manager":
            continue
        if not is_task_success_status(task_row.get("status")):
            continue
        workspace_path = task_row.get("workspace_path")
        task_id = _optional_str(task_row.get("id"))
        if not isinstance(workspace_path, str) or not workspace_path or task_id is None:
            continue
        pm_dir = Path(workspace_path) / "issues" / issue_id / "pm"
        if not ((pm_dir / "prd.json").exists() and (pm_dir / "prd.md").exists()):
            task = await store.load_codex_task(task_id)
            if task is not None and getattr(task, "result", None):
                ws = await store.load_codex_workspace(task.session_id)
                with suppress(ProductManagerArtifactError):
                    await role_workflow_service.persist_result(task, workspace_title=ws.title if ws else None)
        if (pm_dir / "prd.json").exists() and (pm_dir / "prd.md").exists():
            break

    artifact_map: dict[str, JsonObject] = {}

    folder_to_category = {
        "pm": "product",
        "architect": "architecture",
        "engineer": "development",
        "qa": "testing",
    }

    from datetime import datetime as dt

    def scan_root(root: Path) -> None:
        def _walk(target_dir: Path) -> None:
            if not target_dir.exists() or not target_dir.is_dir():
                return
            for item in sorted(target_dir.iterdir()):
                if item.is_dir():
                    _walk(item)
                elif item.is_file() and not item.is_symlink() and item.name != ".DS_Store":
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
    for artifact_data in artifact_map.values():
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
async def delete_codex_issue(issue_id: str) -> object:
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
    candidate_roots.extend(
        workspace_path
        for task in tasks
        if (workspace_path := _optional_str(task.get("workspace_path"))) is not None
    )

    seen_roots: set[str] = set()
    for workspace_path in candidate_roots:
        if workspace_path in seen_roots:
            continue
        seen_roots.add(workspace_path)
        _delete_issue_artifact_root(workspace_path, issue_id)

    for task in tasks:
        task_id = _optional_str(task.get("id"))
        if task_id is not None:
            await _delete_task_cascade(task_id, delete_workspace=False)

    if issue.project_id:
        project = await codex_store.load_project(issue.project_id)
        if project is not None:
            with suppress(Exception):
                await worktree_manager.cleanup_issue_worktree(project, issue)

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
async def get_codex_issue_diff(issue_id: str, stat_only: bool = False) -> object:
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    issue = await codex_store.load_codex_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    if not issue.project_id or not issue.git_worktree_path:
        return {"diff": "", "base_branch": None, "branch": None, "stat": None}
    if not Path(issue.git_worktree_path).exists():
        issue.git_worktree_path = None
        issue.git_branch = None
        issue.git_base_branch = None
        issue.updated_at = datetime.now()
        await codex_store.save_codex_issue(issue)
        return {
            "diff": "",
            "base_branch": None,
            "branch": None,
            "stat": None,
            "commits_ahead": 0,
            "worktree_missing": True,
        }
    project = await codex_store.load_project(issue.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    base = issue.git_base_branch or project.default_branch
    try:
        stat = await git_service.diff_shortstat(issue.git_worktree_path, base)
        ahead = await git_service.commits_ahead(issue.git_worktree_path, base)
        diff = "" if stat_only else await worktree_manager.issue_diff(project, issue)
    except GitError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
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
async def abandon_codex_issue(issue_id: str) -> object:
    """Mark an issue abandoned while keeping its worktree available for undo."""

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
    })
    return issue


@router.post("/codex/issues/{issue_id}/abandon/finalize")
async def finalize_abandoned_codex_issue(issue_id: str) -> object:
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    issue = await codex_store.load_codex_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    if issue.git_merge_status != "abandoned":
        raise HTTPException(status_code=409, detail="issue is not abandoned")
    if issue.project_id:
        project = await codex_store.load_project(issue.project_id)
        if project is not None:
            with suppress(Exception):
                await worktree_manager.cleanup_issue_worktree(project, issue)
    issue.git_worktree_path = None
    issue.updated_at = datetime.now()
    await codex_store.save_codex_issue(issue)
    return issue


@router.post("/codex/issues/{issue_id}/reset", status_code=201)
async def reset_codex_issue(issue_id: str) -> object:
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    issue = await codex_store.load_codex_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    if not issue.project_id:
        raise HTTPException(status_code=409, detail="Issue has no project to reset")
    project = await codex_store.load_project(issue.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if not Path(project.repo_path).exists():
        raise HTTPException(status_code=409, detail="Project repo path is missing")

    tasks = await codex_store.list_codex_tasks(issue_id=issue.id)
    try:
        await worktree_manager.cleanup_issue_worktree_for_reset(project, issue)
        issue.git_branch = None
        issue.git_base_branch = None
        issue.git_worktree_path = None
        branch, worktree_path, base = await worktree_manager.prepare_issue_worktree(project, issue)
    except (GitError, WorktreeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    for task in tasks:
        task_id = _optional_str(task.get("id"))
        if task_id is not None:
            await _delete_task_cascade(task_id, delete_workspace=False)

    issue.git_branch = branch
    issue.git_worktree_path = worktree_path
    issue.git_base_branch = base
    issue.git_merge_status = "open"
    issue.status = "open"
    issue.current_phase = "requirements"
    issue.review_comment = None
    issue.updated_at = datetime.now()
    await codex_store.save_codex_issue(issue)
    await codex_store.append_project_audit(
        project_id=project.id,
        issue_id=issue.id,
        event="reset",
        base_branch=base,
    )
    return issue


@router.post("/codex/issues/{issue_id}/conductor/restart")
async def restart_issue_conductor(issue_id: str) -> object:
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    issue = await codex_store.load_codex_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    if not issue.project_id:
        raise HTTPException(status_code=409, detail="Issue has no project to restart")
    project = await codex_store.load_project(issue.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if not Path(project.repo_path).exists():
        raise HTTPException(status_code=409, detail="Project repo path is missing")
    return await _start_issue_conductor_graph(issue_id, store=cast(AgentWorkflowApiStore, codex_store))


@router.post("/codex/issues/{issue_id}/merge")
async def merge_codex_issue(issue_id: str, request: MergeIssueRequest) -> object:
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
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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
async def create_codex_task(request: CreateTaskRequest) -> object:
    """Create a new Codex task within a session workspace."""
    store = _require_codex_store()
    session = await store.load_codex_session(request.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    issue = None
    if request.issue_id is not None:
        issue = await store.load_codex_issue(request.issue_id)
        if issue is None:
            raise HTTPException(status_code=404, detail="Issue not found")
        if issue.session_id != request.session_id:
            raise HTTPException(status_code=409, detail="Issue does not belong to workspace")
    # PR5: phase is now free-form. Default to role_key when caller omits it
    # (the new DAG flow ignores this field anyway).
    resolved_phase = request.phase or (request.role or (issue.current_phase if issue is not None else "general"))

    # Resolve and validate executor/provider/model against runtime catalog
    resolved_executor, resolved_provider, resolved_model, _, _ = await _resolve_runtime_config(
        request.executor,
        request.provider,
        request.model,
    )

    parent_task = None
    if request.parent_task_id:
        parent_task = await store.load_codex_task(request.parent_task_id)
        if parent_task is None and request.task_kind != "help_child":
            raise HTTPException(status_code=404, detail="Parent task not found")

    project = None
    if session.project_id:
        project = await store.load_project(session.project_id)
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
                raise HTTPException(status_code=500, detail=f"failed to prepare issue worktree: {exc}") from exc
            issue.git_branch = branch
            issue.git_worktree_path = wt_path
            issue.git_base_branch = base
            await store.save_codex_issue(issue)
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
            raise HTTPException(status_code=500, detail=f"failed to prepare chat worktree: {exc}") from exc
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
    await store.save_codex_task(task)
    # Broadcast new task with complete data structure
    await event_bus.append({
        "type": "task_created",
        "task": _serialize_task_payload(task),
    })
    return task


@router.get("/codex/tasks/{task_id}/help-requests")
async def get_codex_task_help_requests(task_id: str) -> object:
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    task = await codex_store.load_codex_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return await codex_store.list_help_requests(parent_task_id=task_id)


@router.get("/codex/tasks")
async def list_codex_tasks(
    session_id: str | None = None,
    issue_id: str | None = None,
    project_id: str | None = None,
) -> list[JsonObject]:
    """List all tasks, optionally filtered by session, issue, or project."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    return await codex_store.list_codex_tasks(
        session_id=session_id,
        issue_id=issue_id,
        project_id=project_id,
    )


@router.get("/codex/tasks/{task_id}")
async def get_codex_task(task_id: str) -> object:
    """Get a task by ID."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    task = await codex_store.load_codex_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.post("/codex/tasks/{task_id}/run")
async def run_codex_task(task_id: str, request: RunTaskRequest | None = None) -> object:
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
        # Check for successful completion (not awaiting_review or rework)
        if prev_task is None or not is_task_success_status(prev_task.get("status")):
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
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        task.status = "failed"
        task.result = str(exc)
        task.updated_at = datetime.now()
        await codex_store.save_codex_task(task)
        from app.application.task_status_events import build_task_status_event

        await event_bus.append(
            build_task_status_event(
                task,
                "failed",
                result=str(exc),
                execution_process_id=task.last_execution_process_id,
            )
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/codex/tasks/{task_id}/terminate")
async def terminate_codex_task(task_id: str) -> object:
    try:
        await get_codex_process_manager().terminate_task(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to terminate task: {exc}") from exc
    return {"status": "ok"}


async def _run_task_with_user_content(
    task_id: str,
    content: str,
    kind: Literal["chat", "refine"],
) -> JsonObject:
    """Shared implementation for chat / refine endpoints (and the legacy /messages alias).

    Creates a user message, starts a run on the task with the given kind, and
    returns {message, assistant_message, task, execution_process}. The assistant
    reply is delivered async via the event stream in real-CLI mode; in mock
    mode (tests) we finalize inline so callers see the assistant_message in the
    response.
    """
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")

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
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

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

    async def _finalize_completed_task(current_task: CodexTask) -> CodexTaskMessage | JsonObject:
        current_task.status = "done"
        current_task.updated_at = datetime.now()
        # Chat must not mutate task.result or persist artifact. Refine / rerun
        # follow normal task.result + persist semantics.
        if kind != "chat":
            await _refresh_task_result(current_task)
        await codex_store.save_codex_task(current_task)
        process_status, process_exit_code = execution_process_state_for_task(
            current_task.status
        )
        await codex_store.update_execution_process_status(
            exec_process.id,
            process_status,
            exit_code=process_exit_code,
            completed_at=(
                datetime.now()
                if is_task_success_status(current_task.status)
                or is_task_failure_status(current_task.status)
                else None
            ),
        )
        from app.application.task_status_events import build_task_status_event

        await event_bus.append(
            build_task_status_event(
                current_task,
                current_task.status,
                result=current_task.result,
                execution_process_id=exec_process.id,
            )
        )
        # The assistant reply is whatever the run produced. For chat it lives only
        # in the message log; for refine/rerun it's also the new task.result.
        assistant_content = current_task.result or "Task updated."
        existing = await _list_task_messages(task_id, execution_process_id=exec_process.id)
        last = cast("CodexTaskMessage | JsonObject | None", existing[-1] if existing else None)

        def _msg_attr(message_item: CodexTaskMessage | JsonObject, name: str) -> object | None:
            return message_item.get(name) if isinstance(message_item, dict) else getattr(message_item, name, None)

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
    real_assistant_message: CodexTaskMessage | JsonObject | None = None
    if is_task_success_status(task.status):
        real_assistant_message = await _finalize_completed_task(task)
    return {"message": message, "assistant_message": real_assistant_message, "task": task, "execution_process": exec_process}


class ChatRequest(BaseModel):
    content: str


@router.post("/codex/tasks/{task_id}/chat", status_code=201)
async def chat_codex_task(task_id: str, request: ChatRequest) -> object:
    """Send a conversational follow-up to the task's agent.

    Chat runs DO NOT mutate the task's canonical result or persist role
    artifacts (e.g. pm/prd.md). The user's message and the agent's reply are
    only appended to the task message log. CLI session continuity (resume_*)
    is reused so the agent has prior conversation context.
    """
    return await _run_task_with_user_content(task_id, request.content, kind="chat")


@router.post("/codex/tasks/{task_id}/messages", status_code=201)
async def send_codex_task_message(task_id: str, request: SendTaskMessageRequest) -> object:
    """Deprecated: alias for /chat. Kept for backward compatibility."""
    return await _run_task_with_user_content(task_id, request.content, kind="chat")


def _has_canonical_artifact_for_task(task: CodexTask) -> bool:
    """Check whether the role's canonical artifact exists on disk."""
    from app.application.issue_artifact_documents import IssueArtifactDocuments

    workspace_path = task.workspace_path
    if not workspace_path:
        return False
    docs = IssueArtifactDocuments()
    issue_id = task.issue_id or task.id
    role = task.role
    if role == "product_manager":
        return docs.pm_prd_json_path(workspace_path, issue_id).exists()
    if role == "architect":
        return docs.architect_system_design_json_path(workspace_path, issue_id).exists()
    if role == "engineer":
        return docs.engineer_implementation_md_path(workspace_path, issue_id, task_id=task.id).exists()
    if role == "qa":
        return docs.qa_plan_json_path(workspace_path, issue_id).exists()
    return False


class RefineRequest(BaseModel):
    content: str


@router.post("/codex/tasks/{task_id}/refine", status_code=201)
async def refine_codex_task(task_id: str, request: RefineRequest) -> object:
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
            detail="无法 refine: 当前任务尚未生成产物, 请先完成 initial 运行",
        )
    return await _run_task_with_user_content(task_id, request.content, kind="refine")


class SendRequest(BaseModel):
    content: str
    force_mode: Literal["chat", "refine"] | None = None


@router.post("/codex/tasks/{task_id}/send", status_code=201)
async def send_codex_task(task_id: str, request: SendRequest) -> object:
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
                detail="无法 refine: 当前任务尚未生成产物, 请先完成 initial 运行",
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
async def rerun_codex_task(task_id: str, request: RerunRequest | None = None) -> object:
    """Re-run the task from scratch using the original role workflow prompt.

    Optional executor/provider/model overrides are passed through to the runner
    (same precedence as /run: run override > task default > catalog default).
    The agent's new output overwrites the canonical artifact via persist_result.
    Sequencing guards (development phase) still apply.
    """
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")

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
        if prev_task is None or not is_task_success_status(prev_task.get("status")):
            raise HTTPException(status_code=409, detail="需先完成上一个开发任务并通过评审")

    try:
        exec_process = await _get_task_runner().start_task_run(
            task,
            kind="rerun",
            run_executor=request.executor if request else None,
            run_provider=request.provider if request else None,
            run_model=request.model if request else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

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
async def get_codex_task_logs(task_id: str) -> object:
    """Get logs for a specific task run."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    task = await codex_store.load_codex_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    # Return only logs tagged with this task_id
    return await codex_store.load_log_events(task.session_id, task_id=task_id, limit=1000)


@router.post("/codex/tasks/{task_id}/submit")
async def submit_codex_task_for_review(task_id: str) -> object:
    """Mark a completed development task as awaiting review and trigger automated AI review."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")

    task = await codex_store.load_codex_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    if not is_task_success_status(task.status):
        raise HTTPException(status_code=409, detail="Task must be completed before submission")

    try:
        from app.application.review_guard import compute_review_guard

        guard = compute_review_guard(
            task.workspace_path,
            task.issue_id or task.id,
            include_diff_summary=False,
        )
    except Exception:  # noqa: BLE001, RUF100
        guard = None
    if guard is not None and getattr(guard, "is_hard_mismatch", False):
        task.status = "rework"
        task.review_comment = (
            "[FRAMEWORK] Engineer report claimed changed files, but the workspace "
            "has zero real git diff. Automated LLM review was skipped; rework is "
            "required before submission."
        )
        task.updated_at = datetime.now()
        await codex_store.save_codex_task(task)
        from app.application.task_status_events import build_task_status_event

        await event_bus.append(
            build_task_status_event(task, "rework", review_comment=task.review_comment)
        )
        return task

    # 1. Update original task status
    task.status = "awaiting_review"
    task.updated_at = datetime.now()
    await codex_store.save_codex_task(task)

    from app.application.task_status_events import build_task_status_event

    await event_bus.append(build_task_status_event(task, "awaiting_review"))

    # 2. Automatically spawn an Architect Review task
    import logging

    logging.getLogger(__name__).debug(
        "spawning automated review task for parent_task=%s",
        task.id,
    )
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
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to start review task: {exc}") from exc

    return task


class TaskReviewRequest(BaseModel):
    decision: Literal["approve", "reject"]
    comment: str | None = None


@router.post("/codex/tasks/{task_id}/review")
async def review_codex_task(task_id: str, request: TaskReviewRequest) -> object:
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

    from app.application.task_status_events import build_task_status_event

    await event_bus.append(
        build_task_status_event(task, task.status, review_comment=task.review_comment)
    )
    return task


@router.delete("/codex/tasks/{task_id}")
async def delete_codex_task(task_id: str) -> object:
    """Delete a task."""
    await _delete_task_cascade(task_id)
    return {"deleted": task_id}


class ResolveApprovalRequest(BaseModel):
    item_id: str
    decision: str  # "accept", "acceptForSession", "decline", "cancel"
    feedback: str | None = None


@router.post("/codex/approvals/resolve")
async def resolve_approval(request: ResolveApprovalRequest) -> object:
    """
    Resolve a pending approval request from Codex app-server.

    Called when user approves or rejects a file change or command execution request.
    """
    mgr = get_codex_process_manager()
    try:
        success = await mgr.resolve_approval(request.item_id, request.decision)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to resolve approval: {exc}") from exc
    if not success:
        raise HTTPException(status_code=404, detail="Pending approval not found")
    return {"resolved": True, "item_id": request.item_id, "decision": request.decision}


@router.get("/codex/approvals/pending")
async def list_pending_approvals() -> object:
    """List all pending approval requests."""
    mgr = get_codex_process_manager()
    return {"pending": list(mgr.get_pending_approvals().values())}


# --- ExecutionProcess APIs ---

@router.get("/codex/execution-processes")
async def list_execution_processes(session_id: str | None = None, task_id: str | None = None) -> object:
    """List execution processes, optionally filtered by session_id and/or task_id."""
    store = _require_codex_store()
    processes = await store.list_execution_processes(session_id=session_id, task_id=task_id)
    return processes


@router.get("/codex/execution-processes/{process_id}")
async def get_execution_process(process_id: str) -> object:
    """Get an ExecutionProcess by ID."""
    return await _load_execution_process(process_id)


@router.get("/codex/execution-processes/{process_id}/messages")
async def get_execution_process_messages(process_id: str) -> object:
    """Get process-scoped task messages for a specific execution process."""
    store = _require_codex_store()
    process = await _load_execution_process(process_id)
    return await store.list_codex_task_messages(
        process.task_id,
        execution_process_id=process.id,
    )


@router.get("/codex/execution-processes/{process_id}/logs")
async def get_execution_process_logs(process_id: str) -> object:
    """Get process-scoped logs for a specific execution process."""
    store = _require_codex_store()
    process = await _load_execution_process(process_id)
    return await store.load_log_events(
        process.session_id,
        task_id=process.task_id,
        execution_process_id=process.id,
        limit=1000,
    )


# --- Runtime Catalog APIs ---


@router.get("/mcp/catalog")
async def get_mcp_catalog() -> object:
    """Return the framework-owned MCP inventory and recent invocation summaries."""
    service = McpManagementService(mcp_registry, _require_codex_store())
    return await service.catalog()


def _get_runtime_catalog_service() -> RuntimeCatalogService:
    """Get or create the runtime catalog service."""
    return RuntimeCatalogService(_require_codex_store())


class RuntimeCatalogRequest(BaseModel):
    catalog: RuntimeCatalog


def _runtime_catalog_response(catalog: RuntimeCatalog) -> JsonObject:
    payload = _model_json_object(catalog)
    executors_payload = payload.get("executors")
    if isinstance(executors_payload, list):
        for executor, executor_payload in zip(catalog.executors, executors_payload, strict=True):
            if not isinstance(executor_payload, dict):
                continue
            executor_payload.pop("api_key", None)
            executor_payload["api_key_configured"] = bool(executor.api_key)
    return payload


def _preserve_omitted_runtime_api_keys(
    incoming: RuntimeCatalog, existing: RuntimeCatalog
) -> RuntimeCatalog:
    existing_by_id = {executor.id: executor for executor in existing.executors}
    for executor in incoming.executors:
        previous = existing_by_id.get(executor.id)
        if previous is not None and executor.api_key is None and previous.api_key:
            executor.api_key = previous.api_key
    return incoming


def _runtime_test_timeout_s(catalog: RuntimeCatalog) -> float:
    timeout_s = catalog.conductor_llm.timeout_s or 10.0
    return max(10.0, min(float(timeout_s), 120.0))


@router.get("/runtime-catalog")
async def get_runtime_catalog() -> object:
    """Get the global runtime catalog."""
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    service = _get_runtime_catalog_service()
    catalog = await service.load_catalog()
    return _runtime_catalog_response(catalog)


@router.put("/runtime-catalog")
async def update_runtime_catalog(request: RuntimeCatalogRequest) -> object:
    """Update the global runtime catalog.

    Validates the catalog before saving. Returns the saved catalog.
    """
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    service = _get_runtime_catalog_service()
    try:
        existing = await service.load_catalog()
        catalog = await service.save_catalog(
            _preserve_omitted_runtime_api_keys(request.catalog, existing)
        )
        return _runtime_catalog_response(catalog)
    except RuntimeCatalogValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/runtime-catalog/validate")
async def validate_runtime_catalog(request: RuntimeCatalogRequest) -> object:
    """Validate the runtime catalog without saving.

    Returns validation result: {"valid": true} or {"valid": false, "error": "..."}
    """
    service = _get_runtime_catalog_service()
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


class _JsonResponse(Protocol):
    def json(self) -> object: ...


def _runtime_test_error_status(value: object) -> str | None:
    if isinstance(value, int) and value >= 400:
        return str(value)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit() and int(stripped) >= 400:
            return stripped
    return None


def _runtime_test_string_field(payload: dict[str, object], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _runtime_test_body_error(response: _JsonResponse) -> str | None:
    try:
        payload = response.json()
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None

    error = payload.get("error")
    if isinstance(error, dict):
        message = _runtime_test_string_field(error, "message", "error_msg", "detail", "type")
        return f"API error: {message}" if message else "API error"
    if isinstance(error, str) and error.strip():
        return f"API error: {error.strip()}"

    status = (
        _runtime_test_error_status(payload.get("error_status"))
        or _runtime_test_error_status(payload.get("error_code"))
        or _runtime_test_error_status(payload.get("code"))
    )
    if status:
        message = _runtime_test_string_field(payload, "error_msg", "message", "detail")
        return f"API error {status}: {message}" if message else f"API error {status}"
    return None


def _runtime_test_request_catalog(
    catalog: RuntimeCatalog,
    executor_id: str,
    api_endpoint: str | None,
    api_key: str | None,
) -> tuple[RuntimeExecutorConfig, RuntimeCatalog, str | None, str | None]:
    executor = next((e for e in catalog.executors if e.id == executor_id), None)
    if executor is None:
        raise HTTPException(status_code=404, detail=f"Executor '{executor_id}' not found")
    endpoint = api_endpoint or executor.api_endpoint
    key = api_key or executor.api_key
    effective_executor = executor.model_copy(update={"api_endpoint": endpoint, "api_key": key})
    effective_catalog = catalog.model_copy(
        update={
            "executors": [
                effective_executor if item.id == executor.id else item for item in catalog.executors
            ]
        }
    )
    return effective_executor, effective_catalog, endpoint, key


@router.post("/runtime-catalog/test")
async def test_runtime_executor(request: TestExecutorRequest) -> object:
    """Test an executor configuration by making a simple API call.

    Returns {"success": true, "latency_ms": ...} or {"success": false, "error": "..."}
    """
    import time

    import httpx

    catalog_service = _get_runtime_catalog_service()
    catalog = await catalog_service.load_catalog()
    executor, effective_catalog, endpoint, api_key = _runtime_test_request_catalog(
        catalog,
        request.executor_id,
        request.api_endpoint,
        request.api_key,
    )
    try:
        _, _, model_id, _, _ = catalog_service.resolve_effective_config(
            effective_catalog,
            request.executor_id,
            request.provider_id,
            request.model_id,
        )
    except RuntimeCatalogValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not endpoint or not api_key:
        raise HTTPException(status_code=400, detail="api_endpoint and api_key are required")

    protocol = (executor.protocol or "anthropic").lower()

    # Build the request
    start = time.monotonic()
    try:
        timeout_s = _runtime_test_timeout_s(catalog)
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            if protocol == "openai":
                response = await client.post(
                    llm_api_url(endpoint, "/v1/chat/completions"),
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
                    llm_api_url(endpoint, "/v1/messages"),
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
            body_error = _runtime_test_body_error(response)
            if body_error:
                return {"success": False, "error": body_error}
            return {"success": True, "latency_ms": round(latency_ms, 1)}
        else:
            return {"success": False, "error": f"HTTP {response.status_code}: {response.text[:200]}"}
    except httpx.TimeoutException:
        return {"success": False, "error": f"Request timed out after {timeout_s:g}s"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _runtime_cli_event_error(event: dict[str, object]) -> str | None:
    status = (
        _runtime_test_error_status(event.get("error_status"))
        or _runtime_test_error_status(event.get("error_code"))
        or _runtime_test_error_status(event.get("code"))
    )
    error = _runtime_test_string_field(event, "error", "message", "detail")
    if status:
        return f"Claude CLI API error {status}: {error}" if error else f"Claude CLI API error {status}"
    if error and event.get("type") in {"error", "api_error"}:
        return f"Claude CLI error: {error}"
    return None


def _runtime_cli_output_error(stdout_text: str, stderr_text: str) -> str | None:
    import json

    last_retry_error: str | None = None
    for line in stdout_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        event_error = _runtime_cli_event_error(event)
        if not event_error:
            continue
        if event.get("subtype") == "api_retry":
            last_retry_error = event_error
            continue
        return event_error
    if last_retry_error:
        return last_retry_error
    if stderr_text.strip():
        return stderr_text.strip()[:500]
    return None


@router.post("/runtime-catalog/test-cli")
async def test_runtime_executor_cli(request: TestExecutorRequest) -> object:
    """Test the actual Claude CLI subprocess path with the runtime catalog environment."""
    import asyncio
    import os
    import time

    catalog_service = _get_runtime_catalog_service()
    catalog = await catalog_service.load_catalog()
    _executor, effective_catalog, _endpoint, _api_key = _runtime_test_request_catalog(
        catalog,
        request.executor_id,
        request.api_endpoint,
        request.api_key,
    )
    try:
        _resolved_executor, provider, model, env_overrides, executor_type = (
            catalog_service.resolve_effective_config(
                effective_catalog,
                request.executor_id,
                request.provider_id,
                request.model_id,
            )
        )
    except RuntimeCatalogValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if executor_type != "claude":
        raise HTTPException(status_code=400, detail="Claude CLI test only supports claude executors")

    env = os.environ.copy()
    paths = [
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
        "/usr/sbin",
        "/sbin",
        os.path.expanduser("~/.npm-global/bin"),
    ]
    env["PATH"] = ":".join(paths) + ":" + env.get("PATH", "")
    env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    if provider:
        env["CLAUDE_PROVIDER"] = provider
    if model:
        env["CLAUDE_MODEL"] = model
    if env_overrides:
        env.update(env_overrides)

    runtime_catalog_controls_api = bool(
        env_overrides
        and ("ANTHROPIC_BASE_URL" in env_overrides or "ANTHROPIC_API_KEY" in env_overrides)
    )
    cmd = [
        "claude",
        "-p",
        "Reply with OK only.",
        "--output-format=stream-json",
        "--verbose",
        "--model",
        model,
        "--permission-mode=bypassPermissions",
        "--disallowedTools=AskUserQuestion",
    ]
    if runtime_catalog_controls_api:
        cmd.extend(["--setting-sources", "project,local"])
    timeout_s = min(_runtime_test_timeout_s(catalog), 20.0)
    started = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            cmd[0],
            *cmd[1:],
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            start_new_session=True,
            limit=1024 * 1024,
        )
    except FileNotFoundError:
        return {"success": False, "error": "Claude CLI executable not found in PATH"}

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return {"success": False, "error": f"Claude CLI test timed out after {timeout_s:g}s"}

    latency_ms = (time.monotonic() - started) * 1000
    stdout_text = stdout_bytes.decode("utf-8", errors="replace")
    stderr_text = stderr_bytes.decode("utf-8", errors="replace")
    output_error = _runtime_cli_output_error(stdout_text, stderr_text)
    if output_error:
        return {"success": False, "error": output_error}
    if proc.returncode != 0:
        return {"success": False, "error": f"Claude CLI exited with code {proc.returncode}"}
    return {"success": True, "latency_ms": round(latency_ms, 1), "mode": "claude_cli"}


@router.post("/runtime-catalog/test-acp")
async def test_runtime_executor_acp(request: TestExecutorRequest) -> object:
    """Probe an ACP v1 executor by running a real ``initialize`` handshake.

    Unlike the HTTP ``/test`` (requires api_endpoint+api_key) and ``/test-cli``
    (claude-only) endpoints, this spawns the configured ACP ``command args``
    over stdio and negotiates protocol version 1. Verifies the agent is actually
    wire-reachable, not just that the binary exists.

    Env values are never returned; missing allowlisted env variables reject the
    probe with an actionable error. Fail-closed: handshake timeout, protocol
    mismatch, and early process exit all report ``success=False``.
    """
    from app.bootstrap import get_codex_process_manager

    catalog_service = _get_runtime_catalog_service()
    catalog = await catalog_service.load_catalog()
    # Resolve the executor and confirm it is an ACP executor before probing.
    executor = next(
        (e for e in catalog.executors if e.id == request.executor_id),
        None,
    )
    if executor is None:
        raise HTTPException(
            status_code=404, detail=f"Executor '{request.executor_id}' not found"
        )
    if executor.executor_type != "acp":
        raise HTTPException(
            status_code=400,
            detail="ACP probe only supports acp executors",
        )

    mgr = get_codex_process_manager()
    # Mock manager (REAL_CLI=false) has no acp_runtime — report unavailable
    # rather than crashing the probe.
    acp_runtime = getattr(mgr, "acp_runtime", None)
    if acp_runtime is None:
        return {
            "success": False,
            "error": "ACP runtime unavailable (REAL_CLI disabled or not bootstrapped)",
        }

    success, error, latency_ms = await acp_runtime.probe_connectivity(request.executor_id)
    result: dict[str, object] = {"success": success, "latency_ms": latency_ms, "mode": "acp"}
    if error:
        result["error"] = error
    return result


# --- Agent CRUD (PR1: Workflow DAG, behind WORKFLOW_DAG_ENABLED) ---

class AgentCreateRequest(BaseModel):
    name: str
    role_key: str
    description: str | None = None
    system_prompt_template: str
    workspace_id: str | None = None
    input_schema: list[JsonObject] | None = None
    output_schema: JsonObject | None = None
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
    input_schema: list[JsonObject] | None = None
    output_schema: JsonObject | None = None
    default_executor: str | None = None
    default_provider: str | None = None
    default_model: str | None = None
    artifact_subdir: str | None = None
    persist_kind: str | None = None
    triggers_replan_on_done: bool | None = None
    triggers_replan_on_fail: bool | None = None


def _require_agent_store() -> AgentWorkflowApiStore:
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    return cast(AgentWorkflowApiStore, codex_store)


@router.get("/agents")
async def list_agents(workspace_id: str | None = None, role_key: str | None = None) -> object:
    """List agents available to a workspace (workspace-specific + global) or all globals."""
    store = _require_agent_store()
    agents = await store.list_agents(workspace_id=workspace_id, role_key=role_key)
    return [a.model_dump() for a in agents]


@router.get("/agents/{agent_id}")
async def get_agent(agent_id: str) -> object:
    store = _require_agent_store()
    agent = await store.load_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    return agent.model_dump()


@router.post("/agents", status_code=201)
async def create_agent(request: AgentCreateRequest) -> object:
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
        agent_tier="custom",
        triggers_replan_on_done=request.triggers_replan_on_done,
        triggers_replan_on_fail=request.triggers_replan_on_fail,
        is_builtin=False,
        created_at=now,
        updated_at=now,
    )
    await store.save_agent(agent)
    return agent.model_dump()


@router.patch("/agents/{agent_id}")
async def update_agent(agent_id: str, request: AgentUpdateRequest) -> object:
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
async def delete_agent(agent_id: str) -> Response:
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
async def propose_issue_plan(issue_id: str) -> object:
    """Run the orchestrator and return a proposed DAG. Does NOT persist.

    Tries the real LLM (configured via the runtime catalog) first; silently
    falls back to the keyword heuristic when the LLM is unreachable, the
    response can't be parsed/validated, or `WORKFLOW_ORCHESTRATOR_LLM` is
    explicitly set to "false".
    """
    store = _require_agent_store()
    issue = await store.load_codex_issue(issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail=f"Issue {issue_id} not found")
    from app.application.llm_runner import build_llm_runner
    from app.application.workflow_orchestrator import WorkflowOrchestrator

    llm_disabled = not timeouts.workflow_orchestrator_llm_enabled()
    llm_runner = (
        None
        if llm_disabled
        else build_llm_runner(_get_runtime_catalog_service(), trace_store=store)
    )
    orchestrator = WorkflowOrchestrator(store=store, llm_runner=llm_runner)
    try:
        dag = await orchestrator.propose_graph(issue, use_llm=not llm_disabled)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return dag


# --- Workflow graph persistence (PR3) ---

class SaveGraphRequest(BaseModel):
    dag: JsonObject
    created_by: str = "user"


def _graph_to_dict(graph: WorkflowGraph) -> JsonObject:
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
        "nodes": [_model_json_object(node) for node in graph.nodes],
        "edges": [_model_json_object(edge) for edge in graph.edges],
    }


@router.get("/codex/issues/{issue_id}/graph")
async def get_issue_graph(issue_id: str) -> object:
    store = _require_agent_store()
    graph = await store.load_workflow_graph_for_issue(issue_id)
    if graph is None:
        raise HTTPException(status_code=404, detail="No workflow graph exists for this issue")
    return _graph_to_dict(graph)


@router.post("/codex/issues/{issue_id}/graph", status_code=201)
async def save_issue_graph(issue_id: str, request: SaveGraphRequest) -> object:
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
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    from app.application.workflow_scheduler import WorkflowStore, materialize_graph_from_dag
    graph = await materialize_graph_from_dag(
        cast(WorkflowStore, store),
        issue_id,
        request.dag,
        created_by=request.created_by,
    )
    return _graph_to_dict(graph)


@router.post("/codex/issues/{issue_id}/graph/start")
async def start_issue_graph(issue_id: str) -> object:
    """Begin DAG execution. Returns the graph after the first settle pass."""
    store = _require_agent_store()
    graph = await store.load_workflow_graph_for_issue(issue_id)
    if graph is None:
        raise HTTPException(status_code=404, detail="No workflow graph exists for this issue")
    from app.application.event_bus import _workflow_task_dispatcher
    from app.application.workflow_scheduler import WorkflowScheduler, WorkflowStore
    scheduler = WorkflowScheduler(
        store=cast(WorkflowStore, store),
        task_dispatcher=_workflow_task_dispatcher,
    )
    graph = await scheduler.start_graph(graph.id)
    return _graph_to_dict(graph)


# --- Replanner endpoints (PR6) ---


@router.get("/codex/issues/{issue_id}/graph/replan-pending")
async def list_replan_pending(issue_id: str) -> object:
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
async def confirm_replan(issue_id: str, replan_id: str) -> object:
    store = _require_agent_store()
    graph = await store.load_workflow_graph_for_issue(issue_id)
    if graph is None:
        raise HTTPException(status_code=404, detail="No workflow graph exists for this issue")
    resolved = await store.resolve_replan(replan_id, "confirmed")
    if not resolved:
        raise HTTPException(status_code=404, detail="Pending replan not found")
    graph = await store.load_workflow_graph(graph.id)
    if graph is None:
        raise HTTPException(status_code=404, detail="No workflow graph exists for this issue")
    return _graph_to_dict(graph)


@router.post("/codex/issues/{issue_id}/graph/replan/{replan_id}/reject")
async def reject_replan(issue_id: str, replan_id: str) -> object:
    store = _require_agent_store()
    graph = await store.load_workflow_graph_for_issue(issue_id)
    if graph is None:
        raise HTTPException(status_code=404, detail="No workflow graph exists for this issue")
    resolved = await store.resolve_replan(replan_id, "rejected")
    if not resolved:
        raise HTTPException(status_code=404, detail="Pending replan not found")
    graph = await store.load_workflow_graph(graph.id)
    if graph is None:
        raise HTTPException(status_code=404, detail="No workflow graph exists for this issue")
    return _graph_to_dict(graph)
