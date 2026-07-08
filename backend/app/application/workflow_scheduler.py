from __future__ import annotations

"""Task completion hook for Conductor-driven orchestration.

In the Conductor world, the WorkflowScheduler is no longer a scheduler — it
exists only to react to task completion events:

  1. Mirror the task's terminal status onto its WorkflowNode
  2. Emit `workflow_node_updated` so the frontend graph refreshes
  3. Signal TaskCompletionRegistry so the Conductor's awaiting
     `dispatch_subagent` tool call can unblock with a SubAgentResult
  4. Phase 4 only: when a specialist_child finishes, fold its findings into
     the parent task's review_comment and re-dispatch the parent node
  5. Best-effort: advance the issue's `current_phase` label for the UI

It does NOT mark the WorkflowGraph terminal — `run_issue_conductor_loop`
owns the graph lifecycle and sets `graph.status` itself when the Conductor
loop exits.
"""
import asyncio  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
from collections.abc import Awaitable, Callable  # noqa: E402
from datetime import datetime  # noqa: E402
from inspect import isawaitable  # noqa: E402
from typing import Protocol, cast  # noqa: E402
from uuid import uuid4  # noqa: E402

from app.application.task_status_events import build_task_status_event  # noqa: E402
from app.application.task_statuses import (  # noqa: E402
    is_task_failure_status,
    is_task_success_status,
)
from app.domain.models import (  # noqa: E402
    Agent,
    AgentMessage,
    CodexIssue,
    CodexTask,
    EdgeType,
    NodeStatus,
    WorkflowEdge,
    WorkflowGraph,
    WorkflowNode,
)

logger = logging.getLogger(__name__)

_ENGINEER_ROLES = {"engineer", "engineer_frontend", "engineer_backend"}
_DIFF_GUARD_CLAIM_MARKER = "Engineer claimed status="
_DIFF_GUARD_ZERO_DIFF_MARKER = "git diff against the base branch shows no file changes"


class WorkflowSchedulerError(RuntimeError):
    pass


class WorkflowStore(Protocol):
    async def save_workflow_graph(
        self,
        graph: WorkflowGraph,
        nodes: list[WorkflowNode] | None = None,
        edges: list[WorkflowEdge] | None = None,
    ) -> None: ...

    async def load_workflow_graph(self, graph_id: str) -> WorkflowGraph | None: ...

    async def load_workflow_graph_for_issue(self, issue_id: str) -> WorkflowGraph | None: ...

    async def update_workflow_node(
        self,
        node_id: str,
        *,
        status: str | None = None,
        task_id: str | None = None,
        artifact_dir: str | None = None,
        prompt_override: str | None = None,
        retries: int | None = None,
        started_at: datetime | None = None,
        completed_at: object = None,
    ) -> None: ...

    async def find_node_by_task_id(self, task_id: str) -> WorkflowNode | None: ...

    async def load_codex_issue(self, issue_id: str) -> CodexIssue | None: ...

    async def save_codex_issue(self, issue: CodexIssue) -> None: ...

    async def save_codex_task(self, task: CodexTask) -> None: ...

    async def load_codex_task(self, task_id: str) -> CodexTask | None: ...

    async def list_agents(self, workspace_id: str | None = None, role_key: str | None = None) -> list[Agent]: ...

    async def save_agent_message(self, message: AgentMessage) -> None: ...

    async def add_workflow_node(self, node: WorkflowNode) -> None: ...

    async def add_workflow_edge(self, edge: WorkflowEdge) -> None: ...

    async def update_execution_process_status(
        self,
        process_id: str,
        status: str,
        exit_code: int | None = None,
        completed_at: datetime | None = None,
    ) -> None: ...


class WorkflowEventBus(Protocol):
    async def append(self, event: dict[str, object]) -> None: ...


TaskDispatcher = Callable[[CodexTask], object | Awaitable[object]]


class _NoopWorkflowEventBus:
    async def append(self, event: dict[str, object]) -> None:
        return None


class _TaskDispatcherRunner:
    def __init__(self, dispatch: TaskDispatcher | None) -> None:
        self._dispatch = dispatch

    async def start_task_run(self, task: CodexTask) -> object:
        if self._dispatch is None:
            raise WorkflowSchedulerError("task dispatcher is not configured")
        result = self._dispatch(task)
        if isawaitable(result):
            return await result
        return result


def _dag_items(dag: dict[str, object], key: str) -> list[dict[str, object]]:
    value = dag.get(key, [])
    if not isinstance(value, list):
        raise WorkflowSchedulerError(f"dag.{key} must be a list")
    items: list[dict[str, object]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise WorkflowSchedulerError(f"dag.{key}[{index}] must be an object")
        items.append({str(item_key): item_value for item_key, item_value in item.items()})
    return items


def _dag_str(item: dict[str, object], key: str, *, default: str | None = None) -> str:
    value = item.get(key, default)
    if not isinstance(value, str) or not value:
        raise WorkflowSchedulerError(f"dag item field '{key}' is required")
    return value


def _dag_optional_str(item: dict[str, object], key: str) -> str | None:
    value = item.get(key)
    return value if isinstance(value, str) else None


def _dag_edge_type(item: dict[str, object]) -> EdgeType:
    value = item.get("edge_type", "sequence")
    if isinstance(value, str) and value in {
        "sequence",
        "parallel-fanout",
        "refine-loop",
        "retry-on-fail",
        "conditional",
        "critique-loop",
    }:
        return cast(EdgeType, value)
    raise WorkflowSchedulerError("dag item field 'edge_type' is invalid")


async def materialize_graph_from_dag(
    store: WorkflowStore,
    issue_id: str,
    dag: dict[str, object],
    *,
    created_by: str = "user",
) -> WorkflowGraph:
    now = datetime.now()
    graph = WorkflowGraph(
        id=str(uuid4()),
        issue_id=issue_id,
        status="draft",
        dag_json=json.dumps(dag, ensure_ascii=False),
        created_by=created_by,
        created_at=now,
        updated_at=now,
    )
    nodes = [
        WorkflowNode(
            id=str(uuid4()),
            graph_id=graph.id,
            node_key=_dag_str(raw, "node_key"),
            agent_id=_dag_str(raw, "agent_id"),
            title=_dag_optional_str(raw, "title"),
            prompt_override=_dag_optional_str(raw, "prompt_override"),
            created_at=now,
            updated_at=now,
        )
        for raw in _dag_items(dag, "nodes")
    ]
    edges = [
        WorkflowEdge(
            id=str(uuid4()),
            graph_id=graph.id,
            from_node_key=_dag_str(raw, "from_node_key"),
            to_node_key=_dag_str(raw, "to_node_key"),
            edge_type=_dag_edge_type(raw),
            condition_expr=_dag_optional_str(raw, "condition_expr"),
            created_at=now,
        )
        for raw in _dag_items(dag, "edges")
    ]
    graph.nodes = nodes
    graph.edges = edges
    await store.save_workflow_graph(graph, nodes=nodes, edges=edges)
    return graph


class WorkflowScheduler:
    """Task-completion hook owner.

    The name is historical; in Conductor mode this class does not schedule
    anything. It is constructed cheaply and only `on_task_completed` runs.
    """

    def __init__(
        self,
        store: WorkflowStore,
        task_dispatcher: TaskDispatcher | None = None,
        event_bus: WorkflowEventBus | None = None,
    ) -> None:
        self.store = store
        self._task_dispatcher = task_dispatcher  # callable(task) -> awaitable, optional
        self._event_bus = event_bus

    async def start_graph(self, graph_id: str) -> WorkflowGraph:
        graph = await self.store.load_workflow_graph(graph_id)
        if graph is None:
            raise WorkflowSchedulerError(f"Workflow graph {graph_id} not found")
        graph.status = "running"
        graph.locked_at = graph.locked_at or datetime.now()
        graph.updated_at = datetime.now()
        await self.store.save_workflow_graph(graph)
        return await self.store.load_workflow_graph(graph_id) or graph

    async def _emit_node_event(self, node: WorkflowNode, issue: CodexIssue | None) -> None:
        if self._event_bus is None or issue is None:
            return
        try:
            await self._event_bus.append(
                {
                    "type": "workflow_node_updated",
                    "issue_id": issue.id,
                    "session_id": issue.session_id,
                    "node_id": node.id,
                    "node_key": node.node_key,
                    "status": node.status,
                    "task_id": node.task_id,
                }
            )
        except Exception as exc:  # noqa: BLE001, RUF100
            logger.debug("workflow_node_updated emit failed: %s", exc)

    async def _emit_artifact_validation_failed(
        self,
        task: CodexTask,
        node: WorkflowNode,
        issue: CodexIssue | None,
        validation_error: dict[str, object],
    ) -> None:
        """GAP E/J: structured signal that a subagent's artifact failed schema
        validation, so the UI can flag it and the Conductor's re-dispatch is
        observable. Best-effort — never let observability break the hook."""
        if self._event_bus is None:
            return
        try:
            await self._event_bus.append(
                {
                    "type": "artifact_validation_failed",
                    "issue_id": issue.id if issue is not None else task.issue_id,
                    "session_id": issue.session_id if issue is not None else None,
                    "task_id": task.id,
                    "node_id": node.id,
                    "node_key": node.node_key,
                    "role": task.role,
                    "validation_error": validation_error,
                }
            )
        except Exception as exc:  # noqa: BLE001, RUF100
            logger.debug("artifact_validation_failed emit failed: %s", exc)

    async def _emit_diff_guard_failed(
        self,
        task: CodexTask,
        node: WorkflowNode,
        issue: CodexIssue | None,
        reason: str,
    ) -> None:
        if self._event_bus is None:
            return
        try:
            await self._event_bus.append(
                {
                    "type": "workflow_node_diff_guard_failed",
                    "issue_id": issue.id if issue is not None else task.issue_id,
                    "session_id": issue.session_id if issue is not None else task.session_id,
                    "task_id": task.id,
                    "node_id": node.id,
                    "node_key": node.node_key,
                    "role": task.role,
                    "reason": reason,
                }
            )
        except Exception as exc:  # noqa: BLE001, RUF100
            logger.debug("workflow_node_diff_guard_failed emit failed: %s", exc)

    async def on_task_completed(self, task: CodexTask) -> None:
        """Hook called by the task runner once a task ends."""
        # Specialist children bypass the workflow_node_id guard — they are
        # intentionally not graph nodes but still need completion handling.
        if task.task_kind == "specialist_child":
            await self._handle_specialist_child_completed(task)
            return
        if not task.workflow_node_id:
            return
        node = await self.store.find_node_by_task_id(task.id)
        if node is None:
            return
        terminal = self._task_status_to_node_status(task.status)
        if terminal is None:
            return
        graph = await self.store.load_workflow_graph(node.graph_id)
        issue_for_event = None
        if graph is not None:
            try:
                issue_for_event = await self.store.load_codex_issue(graph.issue_id)
            except Exception:  # noqa: BLE001, RUF100
                issue_for_event = None
            diff_guard_reason = self._engineer_diff_guard_failure_reason(task)
            if terminal == "done" and diff_guard_reason:
                task.status = "failed"
                task.result = f"Diff completion guard failed: {diff_guard_reason}"
                task.review_comment = (
                    "Diff completion guard failed: the Engineer report claimed file changes, "
                    "but the real git diff was empty. Retry with a concrete code change or "
                    "explicitly explain why no code change is required."
                )
                task.updated_at = datetime.now()
                await self.store.save_codex_task(task)
                await self._emit_diff_guard_failed(task, node, issue_for_event, diff_guard_reason)
                terminal = "failed"
            if (
                terminal == "failed"
                and task.task_kind != "specialist_child"
                and await self._maybe_auto_retry_failed_node(
                task,
                node,
                graph,
                issue_for_event,
                )
            ):
                return
        await self.store.update_workflow_node(
            node.id,
            status=terminal,
            task_id=node.task_id,
            completed_at=datetime.now(),
        )
        node.status = terminal
        if graph is None:
            return

        await self._emit_node_event(node, issue_for_event)

        # Signal TaskCompletionRegistry so Conductor's dispatch_subagent
        # tool call can unblock with a SubAgentResult.
        from app.application.task_completion_registry import TaskCompletionRegistry

        reg = TaskCompletionRegistry.get()
        if reg.is_registered(task.id):
            from app.application.subagent_result_builder import build_subagent_result

            try:
                subagent_result = build_subagent_result(
                    task=task,
                    node=node,
                    doc=getattr(task, "_subagent_doc", None),
                )
                # GAP E: if artifact persistence failed schema validation, the task
                # is `done` but its structured artifact is missing/malformed. Tell
                # the Conductor explicitly (status=artifact_invalid) so it can
                # re-dispatch with a corrective prompt instead of proceeding on a
                # silent empty handoff. Surface a structured event for observability.
                validation_error = getattr(task, "_validation_error", None)
                signal_payload: dict[str, object] = {
                    "task_id": task.id,
                    "role": task.role,
                    "status": "artifact_invalid" if validation_error else task.status,
                    "summary": subagent_result.summary,
                    "artifact_json": subagent_result.artifact_json,
                    "files_changed": subagent_result.files_changed,
                    "qa_commands": subagent_result.qa_commands,
                    "clarification_question": subagent_result.clarification_question,
                }
                if validation_error:
                    signal_payload["validation_error"] = validation_error
                    await self._emit_artifact_validation_failed(
                        task, node, issue_for_event, validation_error
                    )
                reg.signal(task.id, signal_payload)
            except Exception:  # noqa: BLE001, RUF100
                reg.signal(
                    task.id,
                    {
                        "task_id": task.id,
                        "role": task.role,
                        "status": task.status,
                        "summary": task.result or "",
                    },
                )

        # Keep the issue's `current_phase` label in step with completed roles.
        await self._maybe_advance_phase(graph)

    @staticmethod
    def _engineer_diff_guard_failure_reason(task: CodexTask) -> str | None:
        if task.role not in _ENGINEER_ROLES:
            return None
        doc = getattr(task, "_subagent_doc", None)
        qa_notes = getattr(doc, "qa_notes", None)
        if not isinstance(qa_notes, list):
            return None
        for note in qa_notes:
            if not isinstance(note, str):
                continue
            if _DIFF_GUARD_CLAIM_MARKER in note and _DIFF_GUARD_ZERO_DIFF_MARKER in note:
                return note[:800]
        return None

    async def _maybe_auto_retry_failed_node(
        self,
        task: CodexTask,
        node: WorkflowNode,
        graph: WorkflowGraph,
        issue: CodexIssue | None,
    ) -> bool:
        if self._task_dispatcher is None or issue is None:
            return False
        if node.retries >= node.max_retries:
            return False

        now = datetime.now()
        retry_number = node.retries + 1
        retry_task = CodexTask(
            id=str(uuid4()),
            session_id=task.session_id,
            project_id=task.project_id,
            issue_id=task.issue_id,
            phase=task.phase,
            title=task.title,
            prompt=task.prompt,
            role=task.role,
            executor=task.executor,
            provider=task.provider,
            model=task.model,
            status="pending",
            parent_task_id=task.id,
            task_kind=task.task_kind,
            workspace_path=task.workspace_path,
            git_branch=task.git_branch,
            git_base_branch=task.git_base_branch,
            git_worktree_path=task.git_worktree_path,
            review_comment=self._auto_retry_review_comment(task, retry_number, node.max_retries),
            workflow_node_id=node.id,
            created_at=now,
            updated_at=now,
        )
        await self.store.save_codex_task(retry_task)
        await self.store.update_workflow_node(
            node.id,
            status="running",
            task_id=retry_task.id,
            retries=retry_number,
            started_at=now,
            completed_at=None,
        )
        await self._emit_retry_event(
            task=task,
            retry_task=retry_task,
            node=node,
            issue=issue,
            retry_number=retry_number,
            max_retries=node.max_retries,
        )
        from app.application.task_completion_registry import TaskCompletionRegistry

        TaskCompletionRegistry.get().transfer(task.id, retry_task.id)
        try:
            result = self._task_dispatcher(retry_task)
            if asyncio.iscoroutine(result):
                await result
        except Exception as exc:  # noqa: BLE001, RUF100
            logger.warning(
                "workflow node auto-retry dispatch failed issue_id=%s node_id=%s task_id=%s: %s",
                graph.issue_id,
                node.id,
                retry_task.id,
                exc,
            )
            retry_task.status = "failed"
            retry_task.result = f"Auto retry dispatch failed: {exc}"
            retry_task.updated_at = datetime.now()
            await self.store.save_codex_task(retry_task)
            TaskCompletionRegistry.get().signal(
                retry_task.id,
                {
                    "task_id": retry_task.id,
                    "role": retry_task.role,
                    "status": "failed",
                    "error": retry_task.result,
                },
            )
            node.task_id = task.id
            await self.store.update_workflow_node(
                node.id,
                status="failed",
                task_id=task.id,
                completed_at=datetime.now(),
            )
            await self._emit_retry_failed_event(node, issue, retry_task, exc)
            return True
        return True

    @staticmethod
    def _auto_retry_review_comment(task: CodexTask, retry_number: int, max_retries: int) -> str:
        parts = [
            f"[AUTO RETRY {retry_number}/{max_retries}] The previous attempt failed. "
            "Retry the same workflow node and address the failure before continuing.",
        ]
        if task.review_comment:
            parts.append(f"Previous review context:\n{task.review_comment.strip()}")
        if task.result:
            result = task.result.strip()
            if len(result) > 1000:
                result = result[:1000] + "\n... (truncated)"
            parts.append(f"Previous failure result:\n{result}")
        return "\n\n".join(parts)

    async def _emit_retry_event(
        self,
        *,
        task: CodexTask,
        retry_task: CodexTask,
        node: WorkflowNode,
        issue: CodexIssue,
        retry_number: int,
        max_retries: int,
    ) -> None:
        if self._event_bus is None:
            return
        try:
            await self._event_bus.append(
                {
                    "type": "workflow_node_retrying",
                    "issue_id": issue.id,
                    "session_id": issue.session_id,
                    "node_id": node.id,
                    "node_key": node.node_key,
                    "previous_task_id": task.id,
                    "retry_task_id": retry_task.id,
                    "retry": retry_number,
                    "max_retries": max_retries,
                }
            )
            await self._event_bus.append(
                build_task_status_event(
                    retry_task,
                    retry_task.status,
                    review_comment=retry_task.review_comment,
                )
            )
        except Exception as exc:  # noqa: BLE001, RUF100
            logger.debug("workflow_node_retrying emit failed: %s", exc)

    async def _emit_retry_failed_event(
        self,
        node: WorkflowNode,
        issue: CodexIssue,
        retry_task: CodexTask,
        exc: Exception,
    ) -> None:
        if self._event_bus is None:
            return
        try:
            await self._event_bus.append(
                {
                    "type": "workflow_node_retry_failed",
                    "issue_id": issue.id,
                    "session_id": issue.session_id,
                    "node_id": node.id,
                    "node_key": node.node_key,
                    "retry_task_id": retry_task.id,
                    "status": "failed",
                    "error": str(exc),
                }
            )
            await self._event_bus.append(
                build_task_status_event(
                    retry_task,
                    retry_task.status,
                    review_comment=retry_task.review_comment,
                )
            )
        except Exception as emit_exc:  # noqa: BLE001, RUF100
            logger.debug("workflow_node_retry_failed emit failed: %s", emit_exc)

    async def _handle_specialist_child_completed(self, task: CodexTask) -> None:
        """Handle specialist child completion: fold findings into parent and re-dispatch."""
        from app.application.specialist_orchestrator import (
            SpecialistOrchestrator,
            SpecialistOrchestratorError,
            SpecialistStore,
        )

        orchestrator = SpecialistOrchestrator(
            cast(SpecialistStore, self.store),
            self._event_bus or _NoopWorkflowEventBus(),
            _TaskDispatcherRunner(self._task_dispatcher),
        )
        try:
            parent = await orchestrator.complete_specialist_request(
                task.id,
                task.result or "",
            )
        except SpecialistOrchestratorError as exc:
            logger.warning("Specialist child completion handling failed: %s", exc)
            return

        # Re-dispatch the parent so it actually resumes (fixes 1.4: the
        # orchestrator only resets status to pending but never re-dispatches).
        if parent.issue_id and self._task_dispatcher is not None:
            try:
                issue = await self.store.load_codex_issue(parent.issue_id)
                if issue is not None:
                    from app.application.task_dispatcher import DispatchRoleStore, dispatch_role

                    await dispatch_role(
                        issue=issue,
                        role=parent.role,
                        store=cast(DispatchRoleStore, self.store),
                        task_dispatcher_fn=self._task_dispatcher,
                        event_bus=self._event_bus,
                        prev_node_key=task.role,
                    )
            except Exception as exc:  # noqa: BLE001, RUF100
                logger.warning("Failed to re-dispatch parent after specialist: %s", exc)

    async def _maybe_resume_from_specialist(
        self, specialist_child_task: CodexTask, graph: WorkflowGraph
    ) -> bool:
        """Phase 4: inject specialist findings into the parent task's
        review_comment and create a fresh parent task to re-run with them.
        Returns True if the parent was resumed."""
        if specialist_child_task.parent_task_id is None:
            logger.warning("Specialist child %s has no parent task", specialist_child_task.id)
            return False
        parent = await self.store.load_codex_task(specialist_child_task.parent_task_id)
        if parent is None:
            logger.warning("Specialist child %s has no parent task", specialist_child_task.id)
            return False

        now = datetime.now()
        specialist_summary = specialist_child_task.result or "(no result)"
        if len(specialist_summary) > 1000:
            specialist_summary = specialist_summary[:1000] + "\n... (truncated)"

        continuation = (
            f"[SPECIALIST RESULT from {specialist_child_task.role}]\n\n"
            f"{specialist_summary}\n\n"
            f"Incorporate the above specialist findings into your next output."
        )
        parent.review_comment = (
            f"{parent.review_comment}\n\n{continuation}" if parent.review_comment else continuation
        )
        parent.status = "pending"
        parent.updated_at = now
        await self.store.save_codex_task(parent)

        try:
            if parent.issue_id is not None:
                msg = AgentMessage(
                    id=str(uuid4()),
                    issue_id=parent.issue_id,
                    graph_id=graph.id if graph else "",
                    from_node_key=specialist_child_task.role,
                    to_node_key=parent.role,
                    message_type="specialist_result",
                    body=specialist_summary[:500],
                    created_at=now,
                )
                await self.store.save_agent_message(msg)
        except Exception as exc:  # noqa: BLE001, RUF100
            logger.debug("Failed to record specialist result message: %s", exc)

        if self._event_bus is not None:
            try:
                await self._event_bus.append(
                    {
                        "type": "specialist_completed",
                        "parent_task_id": parent.id,
                        "child_task_id": specialist_child_task.id,
                        "specialist_role": specialist_child_task.role,
                    }
                )
                from app.application.task_status_events import build_task_status_event

                await self._event_bus.append(build_task_status_event(parent, parent.status))
            except Exception:  # noqa: BLE001, RUF100
                logger.debug(
                    "specialist parent resume event emit failed: parent_task_id=%s",
                    parent.id,
                    exc_info=True,
                )

        # Re-dispatch the parent's role on a fresh task so the runner picks
        # up the updated review_comment via the REWORK branch.
        try:
            if parent.issue_id is None:
                return True
            parent_issue = await self.store.load_codex_issue(parent.issue_id)
            if parent_issue is None:
                return True
            from app.application.task_dispatcher import DispatchRoleStore, dispatch_role

            await dispatch_role(
                issue=parent_issue,
                role=parent.role,
                store=cast(DispatchRoleStore, self.store),
                task_dispatcher_fn=self._task_dispatcher,
                event_bus=self._event_bus,
                prev_node_key=specialist_child_task.role,
            )
        except Exception as exc:  # noqa: BLE001, RUF100
            logger.warning("Failed to re-dispatch parent after specialist: %s", exc)

        return True

    @staticmethod
    def _task_status_to_node_status(task_status: str) -> NodeStatus | None:
        if is_task_success_status(task_status):
            return "done"
        if is_task_failure_status(task_status):
            return "failed"
        return None

    # role → phase the issue moves *into* once every node of that role lands
    _ROLE_TO_NEXT_PHASE = {
        "product_manager": "architecture",
        "architect": "development",
        "engineer": "testing",
        "qa": "done",
    }

    async def _maybe_advance_phase(self, graph: WorkflowGraph) -> None:
        if graph is None:
            return
        issue = await self.store.load_codex_issue(graph.issue_id)
        if issue is None:
            return
        agents_by_id = {a.id: a for a in await self.store.list_agents(workspace_id=None)}
        from collections import defaultdict

        statuses_by_role: dict[str, set[str]] = defaultdict(set)
        for node in graph.nodes:
            agent = agents_by_id.get(node.agent_id)
            role = (agent.role_key if agent else None) or node.node_key
            statuses_by_role[role].add(node.status)
        target_phase = None
        for role in ("product_manager", "architect", "engineer", "qa"):
            statuses = statuses_by_role.get(role)
            if statuses and all(
                status == "skipped" or is_task_success_status(status) for status in statuses
            ):
                target_phase = self._ROLE_TO_NEXT_PHASE.get(role)
        if target_phase is None or target_phase == issue.current_phase:
            return
        order = ["requirements", "architecture", "development", "testing", "done"]
        try:
            cur_idx = order.index(issue.current_phase or "requirements")
            tgt_idx = order.index(target_phase)
        except ValueError:
            return
        if tgt_idx <= cur_idx:
            return
        issue.current_phase = target_phase
        issue.updated_at = datetime.now()
        await self.store.save_codex_issue(issue)
        if self._event_bus is not None:
            try:
                await self._event_bus.append(
                    {
                        "type": "issue_updated",
                        "issue_id": issue.id,
                        "session_id": issue.session_id,
                        "current_phase": issue.current_phase,
                    }
                )
            except Exception:  # noqa: BLE001, RUF100
                logger.debug(
                    "workflow issue update event emit failed: issue_id=%s",
                    issue.id,
                    exc_info=True,
                )
