from __future__ import annotations

from datetime import datetime
from typing import cast

import pytest

from app.application.engineer_workflow import EngineerWorkflow
from app.application.knowledge_index_service import ArtifactRow, DbConnection, IssueInput
from app.application.project_script_suggestions import ProjectScriptSuggestion
from app.application.role_workflow_service import RoleWorkflowService, RoleWorkflowStore
from app.application.specialist_orchestrator import SpecialistGraphRef
from app.domain.models import (
    AgentMessage,
    CodexSession,
    CodexTask,
    ExecutionProcess,
    Project,
    ProjectEnvVar,
)


def _project(repo_path: str) -> Project:
    return Project(
        id="project-1",
        name="demo",
        repo_path=repo_path,
        default_branch="main",
        setup_script="stale setup",
        run_command="stale run",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


def _task(*, prompt: str, workspace_path: str | None = None, result: str | None = None) -> CodexTask:
    return CodexTask(
        id="task-1",
        session_id="project-1",
        project_id="project-1",
        phase="operations",
        title="Generate Startup Scripts",
        prompt=prompt,
        role="operations_engineer",
        status="done",
        result=result,
        task_kind="project_script_suggestion",
        workspace_path=workspace_path,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


class FakeStore:
    def __init__(self, project: Project):
        self.project = project
        self.saved_projects: list[Project] = []
        self.saved_tasks: list[CodexTask] = []
        self.env_vars: dict[str, ProjectEnvVar] = {}

    async def load_project(self, project_id: str) -> Project | None:
        assert project_id == self.project.id
        return self.project

    async def get(self, project_id: str) -> Project:
        assert project_id == self.project.id
        return self.project

    async def save_project(self, project: Project) -> None:
        self.project = project
        self.saved_projects.append(project)

    async def save_codex_task(self, task: CodexTask) -> None:
        self.saved_tasks.append(task)

    async def load_codex_task(self, task_id: str) -> CodexTask | None:
        return next((task for task in self.saved_tasks if task.id == task_id), None)

    async def load_project_env_var(
        self,
        project_id: str,
        name: str,
    ) -> ProjectEnvVar | None:
        assert project_id == self.project.id
        return self.env_vars.get(name)

    async def save_project_env_var(
        self,
        project_id: str,
        name: str,
        value: str,
        *,
        secret: bool = False,
        source: str = "user",
    ) -> None:
        assert project_id == self.project.id
        self.env_vars[name] = ProjectEnvVar(
            project_id=project_id,
            name=name,
            value=value,
            secret=secret,
            source=source,
        )

    async def _get_conn(self) -> DbConnection:
        raise RuntimeError("FakeStore has no database connection")

    async def list_codex_issues(
        self, session_id: str | None = None, project_id: str | None = None
    ) -> list[IssueInput]:
        return []

    async def list_artifacts(self, issue_id: str) -> list[ArtifactRow]:
        return []

    async def save_artifact(self, artifact: ArtifactRow) -> None:
        return None

    async def load_workflow_graph_for_issue(self, issue_id: str) -> SpecialistGraphRef | None:
        return None

    async def save_agent_message(self, msg: AgentMessage) -> None:
        return None

    async def update_execution_process_status(
        self,
        proc_id: str,
        status: str,
        completed_at: datetime | None = None,
    ) -> None:
        return None


@pytest.mark.asyncio
async def test_operations_prompt_preserves_explicit_empty_request_context(tmp_path):
    store = FakeStore(_project(str(tmp_path)))
    service = RoleWorkflowService(codex_store=cast(RoleWorkflowStore, store))
    task = _task(
        prompt=(
            "Generate startup scripts. "
            'Operations request context JSON: {"setup_script":"","run_command":""}'
        )
    )

    prompt = await service.build_prompt(task)

    assert prompt is not None
    assert "Existing setup script: (empty)" in prompt
    assert "Existing run command: (empty)" in prompt
    assert "stale setup" not in prompt
    assert "stale run" not in prompt


def test_operations_request_context_reads_legacy_prompt_lines():
    task = _task(
        prompt=(
            "Generate startup scripts.\n"
            "Existing setup_script: (empty)\n"
            "Existing run_command: npm run dev"
        )
    )

    context = RoleWorkflowService._read_operations_request_context(task)

    assert context == {"setup_script": "", "run_command": "npm run dev"}


@pytest.mark.asyncio
async def test_persist_result_surfaces_specialist_request_failure(monkeypatch):
    class SpecialistDoc:
        call_specialist = {
            "role_key": "specialist:security_reviewer",
            "prompt": "Review auth flow",
            "why": "Sensitive path",
        }

    class EngineerService:
        def persist_result(self, task, workspace_title=None):
            return SpecialistDoc()

    service = RoleWorkflowService()
    service._engineer_service = cast(EngineerWorkflow, EngineerService())
    task = _task(prompt="Implement auth flow")
    task.role = "engineer"

    async def fail_request(*args, **kwargs):
        raise RuntimeError("specialist unavailable")

    monkeypatch.setattr(service, "_request_specialist", fail_request)

    with pytest.raises(RuntimeError, match="specialist unavailable"):
        await service.persist_result(task)


@pytest.mark.asyncio
async def test_operations_persist_falls_back_to_repo_inference_for_empty_result(
    tmp_path, monkeypatch
):
    import app.application.event_bus as event_bus_module

    event_bus = FakeEventBus()
    monkeypatch.setattr(event_bus_module, "event_bus", event_bus)
    (tmp_path / "package.json").write_text('{"scripts":{"dev":"vite"}}')
    store = FakeStore(_project(str(tmp_path)))
    service = RoleWorkflowService(codex_store=cast(RoleWorkflowStore, store))
    task = _task(prompt="Generate startup scripts.", workspace_path=str(tmp_path), result="")

    suggestion = await service._persist_operations_engineer_result(task)

    assert isinstance(suggestion, ProjectScriptSuggestion)
    assert suggestion.setup_script == "npm install"
    assert suggestion.run_command == "npm run dev"
    assert store.saved_projects
    assert store.project.setup_script == "npm install"
    assert store.project.run_command == "npm run dev"
    assert store.saved_tasks[-1].result is not None
    assert "[OPERATIONS SCRIPT UPDATED]" in (store.saved_tasks[-1].review_comment or "")
    assert [event["type"] for event in event_bus.events] == [
        "project_updated",
        "project_script_updated",
    ]


@pytest.mark.asyncio
async def test_operations_persist_preserves_existing_field_when_suggestion_empty(
    tmp_path, monkeypatch
):
    import app.application.event_bus as event_bus_module

    event_bus = FakeEventBus()
    monkeypatch.setattr(event_bus_module, "event_bus", event_bus)
    project = _project(str(tmp_path))
    project.setup_script = "pnpm install"
    project.run_command = "pnpm old"
    store = FakeStore(project)
    service = RoleWorkflowService(codex_store=cast(RoleWorkflowStore, store))
    task = _task(
        prompt="Generate startup scripts.",
        workspace_path=str(tmp_path),
        result='{"setup_script":"","run_command":"pnpm dev","notes":["run command found"]}',
    )

    suggestion = await service._persist_operations_engineer_result(task)

    assert isinstance(suggestion, ProjectScriptSuggestion)
    assert suggestion.setup_script == "pnpm install"
    assert suggestion.run_command == "pnpm dev"
    assert store.project.setup_script == "pnpm install"
    assert store.project.run_command == "pnpm dev"
    assert '"setup_script":"pnpm install"' in (store.saved_tasks[-1].result or "")
    assert '"run_command":"pnpm dev"' in (store.saved_tasks[-1].result or "")


class FakeEventBus:
    def __init__(self):
        self.events: list[dict] = []

    async def append(self, event: dict) -> None:
        self.events.append(event)


class ScriptTaskStore(FakeStore):
    def __init__(
        self,
        project: Project,
        existing_tasks: list[dict] | None = None,
        execution_processes: list[ExecutionProcess] | None = None,
    ):
        super().__init__(project)
        self.existing_tasks = existing_tasks or []
        self.execution_processes = execution_processes or []
        self.saved_task_by_id: dict[str, CodexTask] = {}

    async def list_codex_tasks(self, **kwargs):
        assert kwargs.get("project_id") == self.project.id
        return self.existing_tasks

    async def load_codex_task(self, task_id: str):
        return self.saved_task_by_id.get(task_id)

    async def save_codex_task(self, task: CodexTask) -> None:
        self.saved_tasks.append(task)
        self.saved_task_by_id[task.id] = task

    async def list_execution_processes(self, task_id: str | None = None, **kwargs):
        if task_id is None:
            return self.execution_processes
        return [process for process in self.execution_processes if process.task_id == task_id]


class WorkspaceScriptTaskStore(ScriptTaskStore):
    def __init__(self, project: Project):
        super().__init__(project)
        self.saved_workspaces: list[CodexSession] = []

    async def load_codex_workspace(self, workspace_id: str) -> CodexSession | None:
        for workspace in self.saved_workspaces:
            if workspace.id == workspace_id:
                return workspace
        return None

    async def save_codex_workspace(self, workspace: CodexSession) -> None:
        self.saved_workspaces.append(workspace)


class FakeExecutionProcess:
    def __init__(self, process_id: str, task_id: str = "task-1", status: str = "Running"):
        self.id = process_id
        self.task_id = task_id
        self.status = status


class ScriptTaskRunner:
    def __init__(self):
        self.started: list[CodexTask] = []
        self.command_args_override: list[str] | None = None

    async def start_task_run(
        self, task: CodexTask, *, command_args_override: list[str] | None = None
    ):
        self.started.append(task)
        self.command_args_override = command_args_override
        task.last_execution_process_id = "ep-1"
        return FakeExecutionProcess("ep-1")


class FakeRuntimeCatalogService:
    async def load_catalog(self):
        return object()

    def resolve_effective_config(self, catalog, executor, provider, model):
        return executor or "codex", provider or "openai", model or "gpt-test", None, executor or "codex"


class ActiveStartupMcp:
    def has_task_session(self, task_id: str) -> bool:
        return True


def test_start_project_script_task_creates_operations_task(client, tmp_path, monkeypatch):
    import app.interfaces.api as api_module

    project = _project(str(tmp_path))
    store = ScriptTaskStore(project)
    runner = ScriptTaskRunner()
    event_bus = FakeEventBus()

    monkeypatch.setattr(api_module, "codex_store", store)
    monkeypatch.setattr(api_module, "project_service", store)
    monkeypatch.setattr(api_module, "event_bus", event_bus)
    monkeypatch.setattr(api_module, "_get_task_runner", lambda: runner)
    monkeypatch.setattr(api_module, "_get_runtime_catalog_service", lambda: FakeRuntimeCatalogService())

    response = client.post(
        f"/api/projects/{project.id}/script-task",
        json={"setup_script": "", "run_command": "npm run dev", "executor": "codex"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "running"
    assert body["execution_process_id"] == "ep-1"
    assert body["reused"] is False
    assert len(runner.started) == 1
    task = runner.started[0]
    assert body["task_id"] == task.id
    assert store.saved_task_by_id[task.id] == task
    assert task.role == "operations_engineer"
    assert task.task_kind == "project_script_suggestion"
    assert task.project_id == project.id
    assert task.session_id == project.id
    assert task.workspace_path == project.repo_path
    assert task.provider == "openai"
    assert task.model == "gpt-test"
    assert task.status == "running"
    assert task.last_execution_process_id == "ep-1"
    assert '"setup_script": ""' in task.prompt
    assert '"run_command": "npm run dev"' in task.prompt
    assert event_bus.events[0]["type"] == "task_created"
    assert event_bus.events[0]["task"]["project_id"] == project.id
    assert event_bus.events[0]["project_id"] == project.id
    assert event_bus.events[0]["workspace_id"] == project.id
    assert event_bus.events[0]["session_id"] == project.id
    assert event_bus.events[0]["role"] == "operations_engineer"
    assert event_bus.events[0]["task_kind"] == "project_script_suggestion"
    status_event = event_bus.events[-1]
    assert status_event["type"] == "task_status"
    assert status_event["task_id"] == task.id
    assert status_event["project_id"] == project.id
    assert status_event["workspace_id"] == project.id
    assert status_event["role"] == "operations_engineer"
    assert status_event["task_kind"] == "project_script_suggestion"
    assert status_event["status"] == "running"
    assert status_event["execution_process_id"] == "ep-1"


def test_start_project_script_task_creates_project_workspace_for_runner(
    client, tmp_path, monkeypatch
):
    import app.interfaces.api as api_module

    project = _project(str(tmp_path))
    store = WorkspaceScriptTaskStore(project)
    runner = ScriptTaskRunner()
    event_bus = FakeEventBus()

    monkeypatch.setattr(api_module, "codex_store", store)
    monkeypatch.setattr(api_module, "project_service", store)
    monkeypatch.setattr(api_module, "event_bus", event_bus)
    monkeypatch.setattr(api_module, "_get_task_runner", lambda: runner)
    monkeypatch.setattr(api_module, "_get_runtime_catalog_service", lambda: FakeRuntimeCatalogService())

    response = client.post(f"/api/projects/{project.id}/script-task", json={})

    assert response.status_code == 200, response.text
    assert len(store.saved_workspaces) == 1
    workspace = store.saved_workspaces[0]
    assert workspace.id == project.id
    assert workspace.project_id == project.id
    assert workspace.cwd == project.repo_path
    task = runner.started[0]
    assert task.session_id == workspace.id
    assert event_bus.events[0]["type"] == "session_created"
    assert event_bus.events[0]["session"]["id"] == project.id


def test_list_codex_tasks_accepts_project_id_filter(client, tmp_path, monkeypatch):
    import app.interfaces.api as api_module

    project = _project(str(tmp_path))
    store = ScriptTaskStore(
        project,
        existing_tasks=[
            {
                "id": "task-project",
                "project_id": project.id,
                "task_kind": "project_script_suggestion",
                "status": "done",
            }
        ],
    )

    monkeypatch.setattr(api_module, "codex_store", store)

    response = client.get(f"/api/codex/tasks?project_id={project.id}")

    assert response.status_code == 200, response.text
    assert response.json() == store.existing_tasks


def test_start_project_script_task_reuses_active_operations_task(client, tmp_path, monkeypatch):
    import app.interfaces.api as api_module

    project = _project(str(tmp_path))
    store = ScriptTaskStore(
        project,
        existing_tasks=[
            {
                "id": "task-existing",
                "title": "Generate Startup Scripts",
                "status": "running",
                "task_kind": "project_script_suggestion",
                "last_execution_process_id": "ep-existing",
            }
        ],
        execution_processes=[
            ExecutionProcess(id="ep-existing", task_id="task-existing", session_id=project.id),
        ],
    )
    runner = ScriptTaskRunner()
    event_bus = FakeEventBus()

    monkeypatch.setattr(api_module, "codex_store", store)
    monkeypatch.setattr(api_module, "project_service", store)
    monkeypatch.setattr(api_module, "event_bus", event_bus)
    monkeypatch.setattr(api_module, "_get_task_runner", lambda: runner)
    monkeypatch.setattr(api_module, "_get_runtime_catalog_service", lambda: FakeRuntimeCatalogService())
    monkeypatch.setattr(api_module, "project_startup_mcp_service", ActiveStartupMcp())

    response = client.post(f"/api/projects/{project.id}/script-task", json={})

    assert response.status_code == 200, response.text
    assert response.json() == {
        "task_id": "task-existing",
        "status": "running",
        "title": "Generate Startup Scripts",
        "execution_process_id": "ep-existing",
        "reused": True,
    }
    assert runner.started == []
    assert store.saved_tasks == []
    assert event_bus.events == [
        {
            "type": "task_status",
            "task_id": "task-existing",
            "project_id": project.id,
            "issue_id": None,
            "workspace_id": project.id,
            "session_id": project.id,
            "role": "operations_engineer",
            "task_kind": "project_script_suggestion",
            "status": "running",
            "result": None,
            "review_comment": None,
            "execution_process_id": "ep-existing",
        }
    ]


def test_start_project_script_task_does_not_reuse_non_operations_task(
    client, tmp_path, monkeypatch
):
    import app.interfaces.api as api_module

    project = _project(str(tmp_path))
    store = ScriptTaskStore(
        project,
        existing_tasks=[
            {
                "id": "task-existing",
                "title": "Generate Startup Scripts",
                "status": "running",
                "task_kind": "project_script_suggestion",
                "role": "engineer",
                "last_execution_process_id": "ep-existing",
            }
        ],
        execution_processes=[
            ExecutionProcess(id="ep-existing", task_id="task-existing", session_id=project.id),
        ],
    )
    runner = ScriptTaskRunner()
    event_bus = FakeEventBus()

    monkeypatch.setattr(api_module, "codex_store", store)
    monkeypatch.setattr(api_module, "project_service", store)
    monkeypatch.setattr(api_module, "event_bus", event_bus)
    monkeypatch.setattr(api_module, "_get_task_runner", lambda: runner)
    monkeypatch.setattr(api_module, "_get_runtime_catalog_service", lambda: FakeRuntimeCatalogService())

    response = client.post(f"/api/projects/{project.id}/script-task", json={})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["reused"] is False
    assert body["task_id"] != "task-existing"
    assert len(runner.started) == 1


def test_start_project_script_task_reuse_emits_builder_event_when_task_loads(
    client, tmp_path, monkeypatch
):
    import app.interfaces.api as api_module

    project = _project(str(tmp_path))
    existing_task = _task(prompt="Generate startup scripts.", workspace_path=str(tmp_path))
    existing_task.id = "task-existing"
    existing_task.status = "responding"
    existing_task.last_execution_process_id = "ep-existing"
    store = ScriptTaskStore(
        project,
        existing_tasks=[
            {
                "id": existing_task.id,
                "title": existing_task.title,
                "status": existing_task.status,
                "task_kind": existing_task.task_kind,
                "last_execution_process_id": existing_task.last_execution_process_id,
            }
        ],
        execution_processes=[
            ExecutionProcess(id="ep-existing", task_id=existing_task.id, session_id=project.id),
        ],
    )
    store.saved_task_by_id[existing_task.id] = existing_task
    runner = ScriptTaskRunner()
    event_bus = FakeEventBus()

    monkeypatch.setattr(api_module, "codex_store", store)
    monkeypatch.setattr(api_module, "project_service", store)
    monkeypatch.setattr(api_module, "event_bus", event_bus)
    monkeypatch.setattr(api_module, "_get_task_runner", lambda: runner)
    monkeypatch.setattr(api_module, "_get_runtime_catalog_service", lambda: FakeRuntimeCatalogService())
    monkeypatch.setattr(api_module, "project_startup_mcp_service", ActiveStartupMcp())

    response = client.post(f"/api/projects/{project.id}/script-task", json={})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["reused"] is True
    assert body["status"] == "responding"
    assert body["execution_process_id"] == "ep-existing"
    assert runner.started == []
    event = event_bus.events[-1]
    assert event["type"] == "task_status"
    assert event["task_id"] == existing_task.id
    assert event["project_id"] == project.id
    assert event["workspace_id"] == project.id
    assert event["role"] == "operations_engineer"
    assert event["task_kind"] == "project_script_suggestion"
    assert event["status"] == "responding"
    assert event["execution_process_id"] == "ep-existing"


def test_start_project_script_task_marks_zombie_active_task_failed_and_starts_new(
    client, tmp_path, monkeypatch
):
    import app.interfaces.api as api_module

    project = _project(str(tmp_path))
    existing_task = _task(prompt="Generate startup scripts.", workspace_path=str(tmp_path))
    existing_task.id = "task-existing"
    existing_task.status = "running"
    existing_task.last_execution_process_id = "ep-stale"
    store = ScriptTaskStore(
        project,
        existing_tasks=[
            {
                "id": existing_task.id,
                "title": existing_task.title,
                "status": existing_task.status,
                "task_kind": existing_task.task_kind,
                "last_execution_process_id": existing_task.last_execution_process_id,
            }
        ],
        execution_processes=[
            ExecutionProcess(
                id="ep-stale",
                task_id=existing_task.id,
                session_id=project.id,
                status="Completed",
            ),
        ],
    )
    store.saved_task_by_id[existing_task.id] = existing_task
    runner = ScriptTaskRunner()
    event_bus = FakeEventBus()

    monkeypatch.setattr(api_module, "codex_store", store)
    monkeypatch.setattr(api_module, "project_service", store)
    monkeypatch.setattr(api_module, "event_bus", event_bus)
    monkeypatch.setattr(api_module, "_get_task_runner", lambda: runner)
    monkeypatch.setattr(api_module, "_get_runtime_catalog_service", lambda: FakeRuntimeCatalogService())

    response = client.post(f"/api/projects/{project.id}/script-task", json={})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["reused"] is False
    assert body["task_id"] != existing_task.id
    assert len(runner.started) == 1
    assert existing_task.status == "failed"
    assert "no active execution process exists" in (existing_task.result or "")
    stale_event = event_bus.events[0]
    assert stale_event["type"] == "task_status"
    assert stale_event["task_id"] == existing_task.id
    assert stale_event["status"] == "failed"
    assert stale_event["role"] == "operations_engineer"
    assert stale_event["task_kind"] == "project_script_suggestion"


def test_start_project_script_task_ignores_stale_active_row_when_loaded_task_terminal(
    client, tmp_path, monkeypatch
):
    import app.interfaces.api as api_module

    project = _project(str(tmp_path))
    existing_task = _task(prompt="Generate startup scripts.", workspace_path=str(tmp_path))
    existing_task.id = "task-existing"
    existing_task.status = "failed"
    store = ScriptTaskStore(
        project,
        existing_tasks=[
            {
                "id": existing_task.id,
                "title": existing_task.title,
                "status": "running",
                "task_kind": existing_task.task_kind,
                "last_execution_process_id": "ep-stale",
            }
        ],
    )
    store.saved_task_by_id[existing_task.id] = existing_task
    runner = ScriptTaskRunner()
    event_bus = FakeEventBus()

    monkeypatch.setattr(api_module, "codex_store", store)
    monkeypatch.setattr(api_module, "project_service", store)
    monkeypatch.setattr(api_module, "event_bus", event_bus)
    monkeypatch.setattr(api_module, "_get_task_runner", lambda: runner)
    monkeypatch.setattr(api_module, "_get_runtime_catalog_service", lambda: FakeRuntimeCatalogService())

    response = client.post(f"/api/projects/{project.id}/script-task", json={})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["reused"] is False
    assert body["task_id"] != existing_task.id
    assert len(runner.started) == 1
    assert runner.started[0].id == body["task_id"]

def test_sync_store_roundtrips_operations_task_project_and_runtime_fields(tmp_path):
    from app.adapters.sqlite_store import SQLiteStore

    store = SQLiteStore(str(tmp_path / "ops_task.db"))
    task = _task(prompt="p", workspace_path=str(tmp_path), result=None)
    task.provider = "openai"
    task.model = "gpt-test"
    task.git_branch = "feature/ops"
    task.git_base_branch = "main"
    task.git_worktree_path = str(tmp_path / "worktree")
    task.git_merge_status = "clean"
    task.git_last_commit_sha = "abc123"
    task.sequence_index = 2
    task.sequence_group = "ops"
    task.review_comment = "reviewed"
    task.workflow_node_id = "node-1"

    store.save_codex_task(task)

    loaded = store.load_codex_task(task.id)
    assert loaded is not None
    assert loaded.project_id == "project-1"
    assert loaded.provider == "openai"
    assert loaded.model == "gpt-test"
    assert loaded.git_branch == "feature/ops"
    assert loaded.git_base_branch == "main"
    assert loaded.git_worktree_path == str(tmp_path / "worktree")
    assert loaded.git_merge_status == "clean"
    assert loaded.git_last_commit_sha == "abc123"
    assert loaded.sequence_index == 2
    assert loaded.sequence_group == "ops"
    assert loaded.review_comment == "reviewed"
    assert loaded.workflow_node_id == "node-1"

    listed = store.list_codex_tasks(project_id="project-1")
    assert len(listed) == 1
    assert listed[0]["id"] == task.id
    assert listed[0]["project_id"] == "project-1"
    assert listed[0]["provider"] == "openai"
    assert listed[0]["model"] == "gpt-test"
    assert listed[0]["git_branch"] == "feature/ops"
    assert listed[0]["git_base_branch"] == "main"
    assert listed[0]["git_worktree_path"] == str(tmp_path / "worktree")
    assert listed[0]["git_merge_status"] == "clean"
    assert listed[0]["git_last_commit_sha"] == "abc123"
    assert listed[0]["sequence_index"] == 2
    assert listed[0]["sequence_group"] == "ops"
    assert listed[0]["review_comment"] == "reviewed"
    assert listed[0]["workflow_node_id"] == "node-1"


@pytest.mark.asyncio
async def test_async_store_lists_operations_task_project_and_runtime_fields(tmp_path):
    from app.adapters.async_sqlite_store import AsyncSQLiteStore

    store = AsyncSQLiteStore(str(tmp_path / "ops_task_async.db"))
    try:
        task = _task(prompt="p", workspace_path=str(tmp_path), result=None)
        task.provider = "openai"
        task.model = "gpt-test"
        await store.save_codex_task(task)

        listed = await store.list_codex_tasks(project_id="project-1")
        assert len(listed) == 1
        assert listed[0]["id"] == task.id
        assert listed[0]["project_id"] == "project-1"
        assert listed[0]["provider"] == "openai"
        assert listed[0]["model"] == "gpt-test"
    finally:
        await store.close()

class FailingScriptTaskRunner:
    async def start_task_run(
        self, task: CodexTask, *, command_args_override: list[str] | None = None
    ):
        raise RuntimeError("executor offline")


class ConflictingScriptTaskRunner:
    async def start_task_run(
        self, task: CodexTask, *, command_args_override: list[str] | None = None
    ):
        raise ValueError("executor already running")


def test_start_project_script_task_marks_task_failed_when_runner_start_fails(
    client, tmp_path, monkeypatch
):
    import app.interfaces.api as api_module

    project = _project(str(tmp_path))
    store = ScriptTaskStore(project)
    event_bus = FakeEventBus()

    monkeypatch.setattr(api_module, "codex_store", store)
    monkeypatch.setattr(api_module, "project_service", store)
    monkeypatch.setattr(api_module, "event_bus", event_bus)
    monkeypatch.setattr(api_module, "_get_task_runner", lambda: FailingScriptTaskRunner())
    monkeypatch.setattr(api_module, "_get_runtime_catalog_service", lambda: FakeRuntimeCatalogService())

    response = client.post(f"/api/projects/{project.id}/script-task", json={})

    assert response.status_code == 500
    failed_task = store.saved_tasks[-1]
    assert failed_task.status == "failed"
    assert failed_task.result == "executor offline"
    event = event_bus.events[-1]
    assert event["type"] == "task_status"
    assert event["task_id"] == failed_task.id
    assert event["project_id"] == project.id
    assert event["issue_id"] is None
    assert event["workspace_id"] == project.id
    assert event["session_id"] == project.id
    assert event["role"] == "operations_engineer"
    assert event["task_kind"] == "project_script_suggestion"
    assert event["status"] == "failed"
    assert event["result"] == "executor offline"
    assert event["execution_process_id"] is None


def test_start_project_script_task_marks_task_failed_when_runner_start_conflicts(
    client, tmp_path, monkeypatch
):
    import app.interfaces.api as api_module

    project = _project(str(tmp_path))
    store = ScriptTaskStore(project)
    event_bus = FakeEventBus()

    monkeypatch.setattr(api_module, "codex_store", store)
    monkeypatch.setattr(api_module, "project_service", store)
    monkeypatch.setattr(api_module, "event_bus", event_bus)
    monkeypatch.setattr(api_module, "_get_task_runner", lambda: ConflictingScriptTaskRunner())
    monkeypatch.setattr(api_module, "_get_runtime_catalog_service", lambda: FakeRuntimeCatalogService())

    response = client.post(f"/api/projects/{project.id}/script-task", json={})

    assert response.status_code == 409
    failed_task = store.saved_tasks[-1]
    assert failed_task.status == "failed"
    assert failed_task.result == "executor already running"
    event = event_bus.events[-1]
    assert event["type"] == "task_status"
    assert event["task_id"] == failed_task.id
    assert event["status"] == "failed"
    assert event["role"] == "operations_engineer"
    assert event["task_kind"] == "project_script_suggestion"


def test_start_project_script_task_reuses_latest_active_operations_task(
    client, tmp_path, monkeypatch
):
    import app.interfaces.api as api_module

    project = _project(str(tmp_path))
    store = ScriptTaskStore(
        project,
        existing_tasks=[
            {
                "id": "task-old",
                "title": "Old Scripts",
                "status": "running",
                "task_kind": "project_script_suggestion",
                "last_execution_process_id": "ep-old",
                "updated_at": "2026-01-01T00:00:00",
            },
            {
                "id": "task-new",
                "title": "New Scripts",
                "status": "responding",
                "task_kind": "project_script_suggestion",
                "last_execution_process_id": "ep-new",
                "updated_at": "2026-02-01T00:00:00",
            },
        ],
        execution_processes=[
            ExecutionProcess(id="ep-new", task_id="task-new", session_id=project.id),
        ],
    )
    runner = ScriptTaskRunner()
    event_bus = FakeEventBus()

    monkeypatch.setattr(api_module, "codex_store", store)
    monkeypatch.setattr(api_module, "project_service", store)
    monkeypatch.setattr(api_module, "event_bus", event_bus)
    monkeypatch.setattr(api_module, "_get_task_runner", lambda: runner)
    monkeypatch.setattr(api_module, "project_startup_mcp_service", ActiveStartupMcp())

    response = client.post(f"/api/projects/{project.id}/script-task", json={})

    assert response.status_code == 200, response.text
    assert response.json()["task_id"] == "task-new"
    assert response.json()["execution_process_id"] == "ep-new"
    assert runner.started == []


def test_start_project_script_task_reuses_status_with_case_and_spaces(
    client, tmp_path, monkeypatch
):
    import app.interfaces.api as api_module

    project = _project(str(tmp_path))
    store = ScriptTaskStore(
        project,
        existing_tasks=[
            {
                "id": "task-new",
                "title": "New Scripts",
                "status": " Responding ",
                "task_kind": "project_script_suggestion",
                "last_execution_process_id": "ep-new",
                "updated_at": "2026-02-01T00:00:00",
            },
        ],
        execution_processes=[
            ExecutionProcess(id="ep-new", task_id="task-new", session_id=project.id),
        ],
    )
    runner = ScriptTaskRunner()
    event_bus = FakeEventBus()

    monkeypatch.setattr(api_module, "codex_store", store)
    monkeypatch.setattr(api_module, "project_service", store)
    monkeypatch.setattr(api_module, "event_bus", event_bus)
    monkeypatch.setattr(api_module, "_get_task_runner", lambda: runner)
    monkeypatch.setattr(api_module, "project_startup_mcp_service", ActiveStartupMcp())

    response = client.post(f"/api/projects/{project.id}/script-task", json={})

    assert response.status_code == 200, response.text
    assert response.json()["task_id"] == "task-new"
    assert response.json()["execution_process_id"] == "ep-new"
    assert runner.started == []
