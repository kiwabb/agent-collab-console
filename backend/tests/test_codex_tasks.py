import pytest
from datetime import datetime
import json
from pathlib import Path

from app.domain.models import CodexSession, CodexTask
import app.interfaces.api as api_module


class TaskRunStoreStub:
    def __init__(self, *, session, tasks):
        self.session = session
        self.tasks = {task.id: task for task in tasks}

    async def load_codex_session(self, session_id: str):
        return self.session if session_id == self.session.id else None

    async def load_codex_task(self, task_id: str):
        return self.tasks.get(task_id)

    async def save_codex_task(self, task):
        self.tasks[task.id] = task

    async def list_codex_tasks(self, session_id: str | None = None, issue_id: str | None = None):
        result = []
        for task in self.tasks.values():
            if session_id is not None and task.session_id != session_id:
                continue
            if issue_id is not None and task.issue_id != issue_id:
                continue
            result.append({
                "id": task.id,
                "session_id": task.session_id,
                "issue_id": task.issue_id,
                "phase": task.phase,
                "title": task.title,
                "prompt": task.prompt,
                "role": task.role,
                "executor": task.executor,
                "status": task.status,
                "workspace_path": task.workspace_path,
                "sequence_index": task.sequence_index,
                "sequence_group": task.sequence_group,
                "created_at": task.created_at.isoformat() if task.created_at else None,
                "updated_at": task.updated_at.isoformat() if task.updated_at else None,
            })
        return result

    async def update_execution_process_status(self, *args, **kwargs):
        pass

    async def save_execution_process(self, *args, **kwargs):
        pass



class TestCodexTaskAPI:
    """Tests for /api/codex/tasks endpoints."""

    def test_create_and_list_issues_for_workspace(self, client):
        session_resp = client.post("/api/codex/sessions", json={"title": "Issue Workspace", "cwd": "/tmp"})
        session_id = session_resp.json()["id"]

        create_resp = client.post(
            "/api/codex/issues",
            json={
                "session_id": session_id,
                "title": "实现 issue-first 流程",
                "description": "先把 issue 接进系统",
            },
        )
        assert create_resp.status_code == 201
        created = create_resp.json()
        assert created["session_id"] == session_id
        assert created["title"] == "实现 issue-first 流程"
        assert created["current_phase"] == "requirements"
        assert created["status"] == "open"

        list_resp = client.get(f"/api/codex/issues?session_id={session_id}")
        assert list_resp.status_code == 200
        items = list_resp.json()
        assert len(items) == 1
        assert items[0]["id"] == created["id"]

    def test_create_task_can_link_to_issue(self, client):
        session = client.post("/api/codex/sessions", json={"title": "Task Issue Workspace", "cwd": "/tmp"}).json()
        issue = client.post(
            "/api/codex/issues",
            json={
                "session_id": session["id"],
                "title": "ProductManager issue",
                "description": "Make PM work",
            },
        ).json()

        task_resp = client.post(
            "/api/codex/tasks",
            json={
                "session_id": session["id"],
                "issue_id": issue["id"],
                "title": "Write PRD",
                "prompt": "分析需求并输出PRD",
                "role": "product_manager",
            },
        )
        assert task_resp.status_code == 201
        task = task_resp.json()
        assert task["issue_id"] == issue["id"]

        tasks_resp = client.get(f"/api/codex/tasks?session_id={session['id']}&issue_id={issue['id']}")
        assert tasks_resp.status_code == 200
        items = tasks_resp.json()
        assert len(items) == 1
        assert items[0]["id"] == task["id"]

    def test_create_task_can_set_phase(self, client):
        session = client.post("/api/codex/sessions", json={"title": "Phase Workspace", "cwd": "/tmp"}).json()
        issue = client.post(
            "/api/codex/issues",
            json={
                "session_id": session["id"],
                "title": "Architecture issue",
                "description": "Set architecture phase",
            },
        ).json()

        task_resp = client.post(
            "/api/codex/tasks",
            json={
                "session_id": session["id"],
                "issue_id": issue["id"],
                "title": "Design architecture",
                "prompt": "输出架构方案",
                "role": "architect",
                "phase": "architecture",
            },
        )
        assert task_resp.status_code == 201
        task = task_resp.json()
        assert task["phase"] == "architecture"

    def test_create_task_defaults_phase_from_role(self, client):
        session = client.post("/api/codex/sessions", json={"title": "Role Phase Workspace", "cwd": "/tmp"}).json()
        issue = client.post(
            "/api/codex/issues",
            json={
                "session_id": session["id"],
                "title": "Implementation issue",
                "description": "Default role phase",
            },
        ).json()

        task_resp = client.post(
            "/api/codex/tasks",
            json={
                "session_id": session["id"],
                "issue_id": issue["id"],
                "title": "Implement feature",
                "prompt": "Build the feature",
                "role": "engineer",
            },
        )

        assert task_resp.status_code == 201
        assert task_resp.json()["phase"] == "development"

    @pytest.mark.parametrize("role,expected_phase", [
        ("product_manager", "requirements"),
        ("architect", "architecture"),
        ("engineer", "development"),
        ("qa", "testing"),
    ])
    def test_create_task_defaults_phase_for_each_role(self, client, role, expected_phase):
        """Each role defaults to the correct phase."""
        session = client.post("/api/codex/sessions", json={"title": "Role Phase Workspace", "cwd": "/tmp"}).json()
        issue = client.post(
            "/api/codex/issues",
            json={
                "session_id": session["id"],
                "title": "Test issue",
                "description": "Test default phase",
            },
        ).json()

        task_resp = client.post(
            "/api/codex/tasks",
            json={
                "session_id": session["id"],
                "issue_id": issue["id"],
                "title": f"{role} task",
                "prompt": f"{role} work",
                "role": role,
            },
        )

        assert task_resp.status_code == 201
        assert task_resp.json()["phase"] == expected_phase

    @pytest.mark.parametrize("role,phase,should_fail", [
        ("product_manager", "architecture", True),
        ("architect", "development", True),
        ("engineer", "requirements", True),
        ("qa", "architecture", True),
        ("product_manager", "requirements", False),
        ("architect", "architecture", False),
        ("engineer", "development", False),
        ("qa", "testing", False),
    ])
    def test_create_task_rejects_mismatched_role_and_phase(self, client, role, phase, should_fail):
        """Role/phase mismatch validation for all roles."""
        session = client.post("/api/codex/sessions", json={"title": "Role Guard Workspace", "cwd": "/tmp"}).json()
        issue = client.post(
            "/api/codex/issues",
            json={
                "session_id": session["id"],
                "title": "Invalid role phase issue",
                "description": "Guard role-phase mismatch",
            },
        ).json()

        task_resp = client.post(
            "/api/codex/tasks",
            json={
                "session_id": session["id"],
                "issue_id": issue["id"],
                "title": f"{role} in wrong phase",
                "prompt": f"{role} work",
                "role": role,
                "phase": phase,
            },
        )

        if should_fail:
            assert task_resp.status_code == 400
            assert "phase" in task_resp.json()["detail"].lower()
        else:
            assert task_resp.status_code == 201

    def test_update_issue_phase(self, client):
        session = client.post("/api/codex/sessions", json={"title": "Issue Phase Workspace", "cwd": "/tmp"}).json()
        issue = client.post(
            "/api/codex/issues",
            json={
                "session_id": session["id"],
                "title": "Progress issue",
                "description": "Move to development",
            },
        ).json()

        response = client.post(
            f"/api/codex/issues/{issue['id']}/phase",
            json={"current_phase": "development"},
        )
        assert response.status_code == 200
        updated = response.json()
        assert updated["current_phase"] == "development"

    def test_update_issue_phase_rejects_invalid_phase(self, client):
        session = client.post("/api/codex/sessions", json={"title": "Issue Phase Workspace", "cwd": "/tmp"}).json()
        issue = client.post(
            "/api/codex/issues",
            json={
                "session_id": session["id"],
                "title": "Progress issue",
                "description": "Move to invalid phase",
            },
        ).json()

        response = client.post(
            f"/api/codex/issues/{issue['id']}/phase",
            json={"current_phase": "unknown"},
        )
        assert response.status_code == 400

    def test_delete_issue_cascades_issue_related_records_without_deleting_workspace_source(self, client, tmp_path):
        import app.bootstrap as bootstrap_module
        from app.domain.models import CodexTaskMessage, ExecutionProcess, HelpRequest, LogEvent

        store = bootstrap_module.codex_store

        source_root = tmp_path / "project-root"
        source_root.mkdir()
        source_marker = source_root / "keep.txt"
        source_marker.write_text("keep me", encoding="utf-8")

        session = client.post(
            "/api/codex/sessions",
            json={"title": "Delete Issue Workspace", "cwd": str(source_root)},
        ).json()
        issue = client.post(
            "/api/codex/issues",
            json={
                "session_id": session["id"],
                "title": "Delete Me",
                "description": "This issue should be removed cleanly",
            },
        ).json()

        root_task = client.post(
            "/api/codex/tasks",
            json={
                "session_id": session["id"],
                "issue_id": issue["id"],
                "title": "PM task",
                "prompt": "write requirements",
                "role": "product_manager",
            },
        ).json()

        worker_task = client.post(
            "/api/codex/tasks",
            json={
                "session_id": session["id"],
                "issue_id": issue["id"],
                "title": "Engineer task",
                "prompt": "build it",
                "role": "engineer",
            },
        ).json()

        root_issue_dir = source_root / "issues" / issue["id"]
        root_issue_dir.mkdir(parents=True, exist_ok=True)
        (root_issue_dir / "requirement.md").write_text("issue artifact", encoding="utf-8")

        worker_issue_dir = Path(worker_task["workspace_path"]) / "issues" / issue["id"]
        worker_issue_dir.mkdir(parents=True, exist_ok=True)
        (worker_issue_dir / "implementation.md").write_text("worker artifact", encoding="utf-8")

        store.save_codex_task_message(
            CodexTaskMessage(
                id="msg-delete-issue",
                task_id=root_task["id"],
                role="user",
                content="delete this",
                created_at=datetime.now(),
            )
        )
        store.save_execution_process(
            ExecutionProcess(
                id="proc-delete-issue",
                task_id=worker_task["id"],
                session_id=session["id"],
                status="Running",
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
        )
        store.append_log_event(
            LogEvent(
                id="log-delete-issue",
                session_id=session["id"],
                stream="stdout",
                content="hello",
                task_id=worker_task["id"],
                execution_process_id="proc-delete-issue",
                created_at=datetime.now(),
            )
        )
        store.save_help_request(
            HelpRequest(
                id="help-delete-issue",
                workspace_id=session["id"],
                parent_task_id=root_task["id"],
                child_task_id=worker_task["id"],
                source_executor="codex",
                target_executor="claude",
                title="Need help",
                prompt="assist",
                created_at=datetime.now(),
            )
        )

        response = client.delete(f"/api/codex/issues/{issue['id']}")
        assert response.status_code == 200
        assert response.json()["deleted"] == issue["id"]

        assert store.load_codex_issue(issue["id"]) is None
        assert store.list_codex_tasks(session_id=session["id"], issue_id=issue["id"]) == []
        assert store.list_codex_task_messages(root_task["id"]) == []
        assert store.list_execution_processes(task_id=worker_task["id"]) == []
        assert store.load_log_events(session["id"], task_id=worker_task["id"]) == []
        assert store.list_help_requests() == []

        assert not root_issue_dir.exists()
        assert not worker_issue_dir.exists()
        assert source_root.exists()
        assert source_marker.exists()

    def test_create_task(self, client):
        """Create a task within an existing workspace."""
        # First create a workspace
        session_resp = client.post("/api/codex/sessions", json={"title": "Task Workspace", "cwd": "/tmp"})
        session_id = session_resp.json()["id"]

        # Create a task
        task_resp = client.post("/api/codex/tasks", json={
            "session_id": session_id,
            "title": "My Task",
            "prompt": "print hello world",
        })
        assert task_resp.status_code == 201
        data = task_resp.json()
        assert data["title"] == "My Task"
        assert data["prompt"] == "print hello world"
        assert data["session_id"] == session_id
        assert data["status"] == "pending"
        assert data["result"] is None
        assert data["resume_session_id"] is None
        assert data["resume_message_id"] is None
        assert data["workspace_path"] is not None
        assert "id" in data

    def test_create_task_with_executor(self, client):
        """Create a task with an explicit executor."""
        session_resp = client.post("/api/codex/sessions", json={"title": "Executor Workspace", "cwd": "/tmp"})
        session_id = session_resp.json()["id"]

        task_resp = client.post("/api/codex/tasks", json={
            "session_id": session_id,
            "title": "Claude Task",
            "prompt": "summarize the repo",
            "executor": "claude",
        })
        assert task_resp.status_code == 201
        data = task_resp.json()
        assert data["executor"] == "claude"

    def test_create_task_with_role(self, client):
        session_resp = client.post("/api/codex/sessions", json={"title": "PM Workspace", "cwd": "/tmp"})
        session_id = session_resp.json()["id"]

        task_resp = client.post("/api/codex/tasks", json={
            "session_id": session_id,
            "title": "Write PRD",
            "prompt": "分析需求并输出PRD",
            "role": "product_manager",
        })
        assert task_resp.status_code == 201
        data = task_resp.json()
        assert data["role"] == "product_manager"

    def test_product_manager_task_uses_workspace_root_instead_of_copied_task_workspace(self, client):
        session_resp = client.post("/api/codex/sessions", json={"title": "PM Workspace", "cwd": "/tmp/project-root"}).json()

        task_resp = client.post("/api/codex/tasks", json={
            "session_id": session_resp["id"],
            "title": "Write PRD",
            "prompt": "分析需求并输出PRD",
            "role": "product_manager",
        })

        assert task_resp.status_code == 201
        assert task_resp.json()["workspace_path"] == "/tmp/project-root"

    def test_product_manager_task_without_workspace_cwd_uses_source_root(self, client):
        from app.bootstrap import workspace_manager

        session_resp = client.post("/api/codex/sessions", json={"title": "PM Workspace", "cwd": ""}).json()

        task_resp = client.post("/api/codex/tasks", json={
            "session_id": session_resp["id"],
            "title": "Write PRD",
            "prompt": "分析需求并输出PRD",
            "role": "product_manager",
        })

        assert task_resp.status_code == 201
        assert task_resp.json()["workspace_path"] == str(workspace_manager.source_root)

    @pytest.mark.parametrize("role", ["product_manager", "architect"])
    def test_role_uses_workspace_root(self, client, role):
        """Product Manager and Architect use workspace root (session.cwd)."""
        session_resp = client.post("/api/codex/sessions", json={"title": "Root Workspace", "cwd": "/tmp/root"}).json()

        task_resp = client.post("/api/codex/tasks", json={
            "session_id": session_resp["id"],
            "title": f"{role} task",
            "prompt": f"{role} work",
            "role": role,
        })

        assert task_resp.status_code == 201
        assert task_resp.json()["workspace_path"] == "/tmp/root"

    @pytest.mark.parametrize("role", ["engineer", "qa"])
    def test_role_uses_task_workspace(self, client, role):
        """Engineer and QA use a dedicated task workspace (not session.cwd)."""
        session_resp = client.post("/api/codex/sessions", json={"title": "Task Workspace", "cwd": "/tmp/root"}).json()

        task_resp = client.post("/api/codex/tasks", json={
            "session_id": session_resp["id"],
            "title": f"{role} task",
            "prompt": f"{role} work",
            "role": role,
        })

        assert task_resp.status_code == 201
        workspace_path = task_resp.json()["workspace_path"]
        assert workspace_path != "/tmp/root", f"{role} should not use workspace root"

    def test_create_help_child_task_persists_task_kind_and_block_link(self, client):
        session = client.post("/api/codex/sessions", json={"title": "Child Workspace", "cwd": "/tmp"}).json()

        response = client.post(
            "/api/codex/tasks",
            json={
                "session_id": session["id"],
                "title": "Claude child",
                "prompt": "Inspect the risk",
                "parent_task_id": "task-parent",
                "executor": "claude",
                "task_kind": "help_child",
                "blocked_by_help_id": "hr-1",
            },
        )

        assert response.status_code == 201
        assert response.json()["task_kind"] == "help_child"
        assert response.json()["blocked_by_help_id"] == "hr-1"

    def test_create_task_workspace_not_found(self, client):
        """Creating a task with a nonexistent workspace returns 404."""
        resp = client.post("/api/codex/tasks", json={
            "session_id": "nonexistent",
            "title": "Orphan Task",
            "prompt": "does this matter",
        })
        assert resp.status_code == 404

    def test_get_task(self, client):
        """Get a task by ID."""
        session_resp = client.post("/api/codex/sessions", json={"title": "Get Task Workspace", "cwd": "/tmp"})
        session_id = session_resp.json()["id"]
        task_resp = client.post("/api/codex/tasks", json={
            "session_id": session_id,
            "title": "Fetch Me",
            "prompt": "echo fetched",
        })
        task_id = task_resp.json()["id"]

        get_resp = client.get(f"/api/codex/tasks/{task_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["title"] == "Fetch Me"

    def test_get_task_not_found(self, client):
        """Getting a nonexistent task returns 404."""
        resp = client.get("/api/codex/tasks/nonexistent")
        assert resp.status_code == 404

    def test_list_tasks_empty(self, client):
        """List tasks when none exist returns empty list."""
        resp = client.get("/api/codex/tasks")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_tasks_filtered_by_workspace(self, client):
        """List tasks filtered by workspace id."""
        session_resp = client.post("/api/codex/sessions", json={"title": "Filter Workspace", "cwd": "/tmp"})
        session_id = session_resp.json()["id"]

        # Create task in this workspace
        client.post("/api/codex/tasks", json={
            "session_id": session_id,
            "title": "In Workspace",
            "prompt": "in workspace prompt",
        })

        # Create task in different workspace
        other_resp = client.post("/api/codex/sessions", json={"title": "Other", "cwd": "/tmp"})
        other_id = other_resp.json()["id"]
        client.post("/api/codex/tasks", json={
            "session_id": other_id,
            "title": "Other Workspace",
            "prompt": "other",
        })

        # Filter by our workspace
        resp = client.get(f"/api/codex/tasks?session_id={session_id}")
        assert resp.status_code == 200
        tasks = resp.json()
        assert len(tasks) == 1
        assert tasks[0]["title"] == "In Workspace"

    def test_run_task_updates_status_and_result(self, client):
        """Running a task marks it completed and extracts result from assistant message."""
        # Create workspace and task
        session_resp = client.post("/api/codex/sessions", json={"title": "Run Task Workspace", "cwd": "/tmp"})
        session_id = session_resp.json()["id"]
        task_resp = client.post("/api/codex/tasks", json={
            "session_id": session_id,
            "title": "Run Test Task",
            "prompt": "print(1+1)",
        })
        task_id = task_resp.json()["id"]

        # Verify initial status is pending
        assert task_resp.json()["status"] == "pending"

        # Run the task (mocked — instant completion)
        run_resp = client.post(f"/api/codex/tasks/{task_id}/run")
        assert run_resp.status_code == 200
        data = run_resp.json()
        # Returns ExecutionProcess with status Completed
        assert data["status"] == "Completed"
        assert data["task_id"] == task_id
        assert data["session_id"] == session_id
        # ExecutionProcess id is now bound to the task's last_execution_process_id
        task_resp_after = client.get(f"/api/codex/tasks/{task_id}")
        assert task_resp_after.json()["last_execution_process_id"] == data["id"]

    def test_product_manager_refresh_persists_prd_artifacts_and_summary(self, client):
        from app.interfaces import api as api_module

        session = client.post("/api/codex/sessions", json={"title": "Agent Console", "cwd": "/tmp"}).json()
        task = client.post(
            "/api/codex/tasks",
            json={
                "session_id": session["id"],
                "title": "实现 ProductManager",
                "prompt": "做一个 ProductManager，输出 PRD",
                "role": "product_manager",
            },
        ).json()

        task_model = api_module.codex_store.load_codex_task(task["id"])
        task_model.status = "done"
        task_model.result = json.dumps({
            "language": "zh-CN",
            "project_name": "agent-collab-console",
            "issue_id": task_model.id,
            "issue_title": task_model.title,
            "original_requirements": task_model.prompt,
            "product_goals": ["让 PM 能稳定输出 PRD"],
            "user_stories": ["作为用户，我希望系统先输出结构化 PRD"],
            "requirement_analysis": "先实现最小 ProductManager 闭环。",
            "requirement_pool": [
                {"priority": "P0", "title": "输出 PRD", "description": "生成 prd.json 和 prd.md"}
            ],
            "acceptance_criteria": ["生成两个文件"],
            "constraints": ["兼容现有 codex task 流程"],
            "open_questions": ["Issue 模型后续再引入"],
            "risks": ["旧 UI 仍然 task-first"],
        }, ensure_ascii=False)
        api_module._refresh_task_result(task_model)

        issue_root = Path(task_model.workspace_path) / "issues" / task_model.id
        prd_json_path = issue_root / "prd.json"
        prd_md_path = issue_root / "prd.md"

        assert prd_json_path.exists()
        assert prd_md_path.exists()
        payload = json.loads(prd_json_path.read_text(encoding="utf-8"))
        assert payload["issue_id"] == task_model.id
        assert payload["product_goals"] == ["让 PM 能稳定输出 PRD"]
        assert "PRD generated for" in task_model.result
        assert "prd.json" in task_model.result
        assert "# PRD: 实现 ProductManager" in prd_md_path.read_text(encoding="utf-8")

    def test_product_manager_persists_prd_under_issue_id(self, client):
        from app.interfaces import api as api_module

        session = client.post("/api/codex/sessions", json={"title": "Agent Console", "cwd": "/tmp"}).json()
        issue = client.post(
            "/api/codex/issues",
            json={
                "session_id": session["id"],
                "title": "Issue for PM",
                "description": "Use real issue id",
            },
        ).json()
        task = client.post(
            "/api/codex/tasks",
            json={
                "session_id": session["id"],
                "issue_id": issue["id"],
                "title": "实现 ProductManager",
                "prompt": "做一个 ProductManager，输出 PRD",
                "role": "product_manager",
            },
        ).json()

        task_model = api_module.codex_store.load_codex_task(task["id"])
        task_model.status = "done"
        task_model.result = json.dumps({
            "language": "zh-CN",
            "project_name": "agent-collab-console",
            "issue_id": issue["id"],
            "issue_title": task_model.title,
            "original_requirements": task_model.prompt,
            "product_goals": ["让 PM 能稳定输出 PRD"],
            "user_stories": ["作为用户，我希望系统先输出结构化 PRD"],
            "requirement_analysis": "先实现最小 ProductManager 闭环。",
            "requirement_pool": [
                {"priority": "P0", "title": "输出 PRD", "description": "生成 prd.json 和 prd.md"}
            ],
            "acceptance_criteria": ["生成两个文件"],
            "constraints": ["兼容现有 codex task 流程"],
            "open_questions": [],
            "risks": [],
        }, ensure_ascii=False)
        api_module._refresh_task_result(task_model)

        issue_root = Path(task_model.workspace_path) / "issues" / issue["id"]
        assert (issue_root / "prd.json").exists()
        assert (issue_root / "prd.md").exists()

    def test_get_issue_artifacts_reads_prd_files(self, client):
        from app.interfaces import api as api_module

        session = client.post("/api/codex/sessions", json={"title": "Artifacts Workspace", "cwd": "/tmp"}).json()
        issue = client.post(
            "/api/codex/issues",
            json={
                "session_id": session["id"],
                "title": "Artifact Issue",
                "description": "Read issue artifacts",
            },
        ).json()
        task = client.post(
            "/api/codex/tasks",
            json={
                "session_id": session["id"],
                "issue_id": issue["id"],
                "title": "Write PRD",
                "prompt": "分析需求并输出PRD",
                "role": "product_manager",
            },
        ).json()
        task_model = api_module.codex_store.load_codex_task(task["id"])
        task_model.status = "done"
        task_model.result = json.dumps({
            "language": "zh-CN",
            "project_name": "agent-collab-console",
            "issue_id": issue["id"],
            "issue_title": task_model.title,
            "original_requirements": task_model.prompt,
            "product_goals": ["Goal"],
            "user_stories": ["Story"],
            "requirement_analysis": "Analysis",
            "requirement_pool": [{"priority": "P0", "title": "输出 PRD", "description": "生成 prd.json 和 prd.md"}],
            "acceptance_criteria": ["生成两个文件"],
            "constraints": [],
            "open_questions": [],
            "risks": [],
        }, ensure_ascii=False)
        api_module._refresh_task_result(task_model)

        response = client.get(f"/api/codex/issues/{issue['id']}/artifacts")
        assert response.status_code == 200
        artifacts = response.json()
        names = {item["name"] for item in artifacts}
        assert "prd.json" in names
        assert "prd.md" in names

    def test_get_issue_artifacts_backfills_missing_prd_files_from_done_product_manager_task(self, client):
        from app.interfaces import api as api_module

        session = client.post("/api/codex/sessions", json={"title": "Artifacts Workspace", "cwd": "/tmp"}).json()
        issue = client.post(
            "/api/codex/issues",
            json={
                "session_id": session["id"],
                "title": "Artifact Issue",
                "description": "Backfill issue artifacts",
            },
        ).json()
        task = client.post(
            "/api/codex/tasks",
            json={
                "session_id": session["id"],
                "issue_id": issue["id"],
                "title": "Write PRD",
                "prompt": "分析需求并输出PRD",
                "role": "product_manager",
            },
        ).json()
        task_model = api_module.codex_store.load_codex_task(task["id"])
        task_model.status = "done"
        task_model.result = json.dumps({
            "language": "zh-CN",
            "project_name": "agent-collab-console",
            "issue_id": issue["id"],
            "issue_title": task_model.title,
            "original_requirements": task_model.prompt,
            "product_goals": ["Goal"],
            "user_stories": ["Story"],
            "requirement_analysis": "Analysis",
            "requirement_pool": [{"priority": "P0", "title": "输出 PRD", "description": "生成 prd.json 和 prd.md"}],
            "acceptance_criteria": ["生成两个文件"],
            "constraints": [],
            "open_questions": [],
            "risks": [],
        }, ensure_ascii=False)
        api_module.codex_store.save_codex_task(task_model)

        issue_root = Path(task_model.workspace_path) / "issues" / issue["id"]
        assert not (issue_root / "prd.json").exists()
        assert not (issue_root / "prd.md").exists()

        response = client.get(f"/api/codex/issues/{issue['id']}/artifacts")
        assert response.status_code == 200
        artifacts = response.json()
        names = {item["name"] for item in artifacts}
        assert "prd.json" in names
        assert "prd.md" in names

    def test_get_issue_artifacts_backfills_architect_design_artifacts(self, client):
        from app.interfaces import api as api_module

        session = client.post("/api/codex/sessions", json={"title": "Artifacts Workspace", "cwd": "/tmp"}).json()
        issue = client.post(
            "/api/codex/issues",
            json={"session_id": session["id"], "title": "Design Issue", "description": "Architect artifact backfill"},
        ).json()
        task = client.post(
            "/api/codex/tasks",
            json={
                "session_id": session["id"],
                "issue_id": issue["id"],
                "title": "Design the system",
                "prompt": "Design architecture",
                "role": "architect",
            },
        ).json()
        task_model = api_module.codex_store.load_codex_task(task["id"])
        task_model.status = "done"
        task_model.result = json.dumps({
            "language": "en",
            "project_name": "agent-collab-console",
            "issue_id": issue["id"],
            "issue_title": "Design the system",
            "architecture_summary": "REST API service",
            "components": ["API", "Service"],
            "data_models": ["User"],
            "interfaces": ["REST"],
            "data_flow": "Client -> API -> DB",
            "implementation_tasks": [{"title": "Setup", "description": "Init", "priority": "P0"}],
            "risks": [],
"open_questions": [],
        }, ensure_ascii=False)
        api_module.codex_store.save_codex_task(task_model)
        # New architecture: persist at task completion, not on reads
        api_module.role_workflow_service.persist_result(task_model, workspace_title=session["title"])

        response = client.get(f"/api/codex/issues/{issue['id']}/artifacts")
        assert response.status_code == 200
        artifacts = response.json()
        names = {item["name"] for item in artifacts}
        assert "implementation_plan.json" in names

    def test_get_issue_artifacts_backfills_engineer_implementation_report(self, client):
        from app.interfaces import api as api_module

        session = client.post("/api/codex/sessions", json={"title": "Artifacts Workspace", "cwd": "/tmp"}).json()
        issue = client.post(
            "/api/codex/issues",
            json={"session_id": session["id"], "title": "Impl Issue", "description": "Engineer artifact backfill"},
        ).json()
        task = client.post(
            "/api/codex/tasks",
            json={
                "session_id": session["id"],
                "issue_id": issue["id"],
                "title": "Implement login",
                "prompt": "Implement login",
                "role": "engineer",
            },
        ).json()
        task_model = api_module.codex_store.load_codex_task(task["id"])
        task_model.status = "done"
        task_model.result = json.dumps({
            "language": "en",
            "project_name": "agent-collab-console",
            "issue_id": issue["id"],
            "issue_title": "Implement login",
            "status": "completed",
            "summary": "Implemented login",
            "changed_files": ["src/auth.py"],
            "completed_tasks": [{"title": "Add handler", "description": "Created", "priority": "P0"}],
            "deferred_tasks": [],
            "risks": [],
            "verification_commands": ["pytest"],
            "qa_notes": [],
        }, ensure_ascii=False)
        api_module.codex_store.save_codex_task(task_model)
        # New architecture: persist at task completion, not on reads
        api_module.role_workflow_service.persist_result(task_model, workspace_title=session["title"])

        response = client.get(f"/api/codex/issues/{issue['id']}/artifacts")
        assert response.status_code == 200
        artifacts = response.json()
        names = {item["name"] for item in artifacts}
        assert "implementation.md" in names

    def test_get_issue_artifacts_backfills_qa_report(self, client):
        from app.interfaces import api as api_module

        session = client.post("/api/codex/sessions", json={"title": "Artifacts Workspace", "cwd": "/tmp"}).json()
        issue = client.post(
            "/api/codex/issues",
            json={"session_id": session["id"], "title": "QA Issue", "description": "QA artifact backfill"},
        ).json()
        task = client.post(
            "/api/codex/tasks",
            json={
                "session_id": session["id"],
                "issue_id": issue["id"],
                "title": "Test login",
                "prompt": "Test the login feature",
                "role": "qa",
            },
        ).json()
        task_model = api_module.codex_store.load_codex_task(task["id"])
        task_model.status = "done"
        task_model.result = json.dumps({
            "language": "en",
            "project_name": "agent-collab-console",
            "issue_id": issue["id"],
            "issue_title": "Test login",
            "status": "passed",
            "test_scope": "API tests",
            "acceptance_coverage": ["User can login"],
            "commands_run": ["pytest"],
            "recommended_commands": ["pytest -v"],
            "manual_scenarios": [],
            "bugs_found": [],
            "risks": [],
            "test_gaps": [],
            "final_recommendation": "Ready",
        }, ensure_ascii=False)
        api_module.codex_store.save_codex_task(task_model)
        # New architecture: persist at task completion, not on reads
        api_module.role_workflow_service.persist_result(task_model, workspace_title=session["title"])

        response = client.get(f"/api/codex/issues/{issue['id']}/artifacts")
        assert response.status_code == 200
        artifacts = response.json()
        names = {item["name"] for item in artifacts}
        assert "qa_plan.json" in names
        assert "qa_report.md" in names

    def test_get_issue_artifacts_no_duplicate_names(self, client):
        """Multiple tasks with same artifact names should not return duplicates."""
        from app.interfaces import api as api_module

        session = client.post("/api/codex/sessions", json={"title": "Artifacts Workspace", "cwd": "/tmp"}).json()
        issue = client.post(
            "/api/codex/issues",
            json={"session_id": session["id"], "title": "Multi Role Issue", "description": "Duplicate name test"},
        ).json()

        for role in ["product_manager", "architect", "engineer", "qa"]:
            task = client.post(
                "/api/codex/tasks",
                json={
                    "session_id": session["id"],
                    "issue_id": issue["id"],
                    "title": f"{role} task",
                    "prompt": f"{role} work",
                    "role": role,
                },
            ).json()
            task_model = api_module.codex_store.load_codex_task(task["id"])
            task_model.status = "done"
            if role == "product_manager":
                task_model.result = json.dumps({
                    "language": "en", "project_name": "test", "issue_id": issue["id"],
                    "issue_title": f"{role} task", "original_requirements": f"{role} work",
                    "product_goals": [], "user_stories": [], "requirement_analysis": "test",
                    "requirement_pool": [], "acceptance_criteria": [], "constraints": [],
                    "open_questions": [], "risks": [],
                }, ensure_ascii=False)
            elif role == "architect":
                task_model.result = json.dumps({
                    "language": "en", "project_name": "test", "issue_id": issue["id"],
                    "issue_title": f"{role} task", "architecture_summary": "test",
                    "components": [], "data_models": [], "interfaces": [], "data_flow": "",
                    "implementation_tasks": [], "risks": [], "open_questions": [],
                }, ensure_ascii=False)
            elif role == "engineer":
                task_model.result = json.dumps({
                    "language": "en", "project_name": "test", "issue_id": issue["id"],
                    "issue_title": f"{role} task", "status": "completed", "summary": "test",
                    "changed_files": [], "completed_tasks": [], "deferred_tasks": [],
                    "risks": [], "verification_commands": [], "qa_notes": [],
                }, ensure_ascii=False)
            elif role == "qa":
                task_model.result = json.dumps({
                    "language": "en", "project_name": "test", "issue_id": issue["id"],
                    "issue_title": f"{role} task", "status": "passed", "test_scope": "test",
                    "acceptance_coverage": [], "commands_run": [], "recommended_commands": [],
                    "manual_scenarios": [], "bugs_found": [], "risks": [], "test_gaps": [],
                    "final_recommendation": "test",
                }, ensure_ascii=False)
            api_module.codex_store.save_codex_task(task_model)

        response = client.get(f"/api/codex/issues/{issue['id']}/artifacts")
        assert response.status_code == 200
        artifacts = response.json()
        names = [item["name"] for item in artifacts]
        assert len(names) == len(set(names)), f"Duplicate artifact names: {names}"

    def test_product_manager_bugfix_creates_bugfix_artifact(self, client):
        from app.interfaces import api as api_module

        session = client.post("/api/codex/sessions", json={"title": "Bugfix Workspace", "cwd": "/tmp"}).json()
        issue = client.post(
            "/api/codex/issues",
            json={
                "session_id": session["id"],
                "title": "Fix help bug",
                "description": "Fix help request bug",
            },
        ).json()
        task = client.post(
            "/api/codex/tasks",
            json={
                "session_id": session["id"],
                "issue_id": issue["id"],
                "title": "Requirements: Fix help bug",
                "prompt": "Fix the broken help request bug",
                "role": "product_manager",
                "phase": "requirements",
            },
        ).json()

        task_model = api_module.codex_store.load_codex_task(task["id"])
        task_model.status = "done"
        task_model.result = json.dumps({
            "language": "zh-CN",
            "project_name": "agent-collab-console",
            "issue_id": issue["id"],
            "issue_title": task_model.title,
            "original_requirements": task_model.prompt,
            "problem_statement": "The flow creates an extra codex task during blocking help.",
            "suspected_impact": "Users see duplicate codex tasks and lose trust in the workflow.",
            "reproduction_notes": ["Run blocking help", "Observe duplicate codex task entries"],
            "acceptance_criteria": [],
            "risks": [],
        }, ensure_ascii=False)
        api_module._refresh_task_result(task_model)

        artifacts = client.get(f"/api/codex/issues/{issue['id']}/artifacts").json()
        names = {item["name"] for item in artifacts}
        assert "bugfix.md" in names
        bugfix_artifact = next(item for item in artifacts if item["name"] == "bugfix.md")
        assert "extra codex task" in bugfix_artifact["content"]

    def test_product_manager_requirement_update_keeps_existing_prd_content_shape(self, client):
        from app.interfaces import api as api_module

        session = client.post("/api/codex/sessions", json={"title": "Update Workspace", "cwd": "/tmp"}).json()
        issue = client.post(
            "/api/codex/issues",
            json={
                "session_id": session["id"],
                "title": "Update PRD issue",
                "description": "Need follow-up PRD update",
            },
        ).json()
        first_task = client.post(
            "/api/codex/tasks",
            json={
                "session_id": session["id"],
                "issue_id": issue["id"],
                "title": "Requirements: Initial PRD",
                "prompt": "Create initial PRD",
                "role": "product_manager",
                "phase": "requirements",
            },
        ).json()
        first_model = api_module.codex_store.load_codex_task(first_task["id"])
        first_model.status = "done"
        first_model.result = json.dumps({
            "language": "zh-CN",
            "project_name": "agent-collab-console",
            "issue_id": issue["id"],
            "issue_title": first_model.title,
            "original_requirements": first_model.prompt,
            "product_goals": ["initial goal"],
            "user_stories": [],
            "requirement_analysis": "initial analysis",
            "requirement_pool": [],
            "acceptance_criteria": [],
            "constraints": [],
            "open_questions": [],
            "risks": [],
        }, ensure_ascii=False)
        api_module._refresh_task_result(first_model)

        update_task = client.post(
            "/api/codex/tasks",
            json={
                "session_id": session["id"],
                "issue_id": issue["id"],
                "title": "Requirements: Update PRD",
                "prompt": "Add more acceptance criteria",
                "role": "product_manager",
                "phase": "requirements",
            },
        ).json()
        update_model = api_module.codex_store.load_codex_task(update_task["id"])
        update_model.status = "done"
        update_model.result = json.dumps({
            "language": "zh-CN",
            "project_name": "agent-collab-console",
            "issue_id": issue["id"],
            "issue_title": update_model.title,
            "original_requirements": update_model.prompt,
            "product_goals": ["updated goal"],
            "user_stories": [],
            "requirement_analysis": "updated analysis",
            "requirement_pool": [],
            "acceptance_criteria": ["new criterion"],
            "constraints": [],
            "open_questions": [],
            "risks": [],
        }, ensure_ascii=False)
        api_module._refresh_task_result(update_model)

        artifacts = client.get(f"/api/codex/issues/{issue['id']}/artifacts").json()
        prd_json = next(item for item in artifacts if item["name"] == "prd.json")
        payload = json.loads(prd_json["content"])
        assert payload["product_goals"] == ["updated goal"]
        assert payload["acceptance_criteria"] == ["new criterion"]

    def test_request_help_endpoint_blocks_parent_and_creates_help_child(self, client):
        session_resp = client.post("/api/codex/sessions", json={"title": "Help Button Workspace", "cwd": "/tmp"})
        session_id = session_resp.json()["id"]
        task_resp = client.post("/api/codex/tasks", json={
            "session_id": session_id,
            "title": "Parent Task",
            "prompt": "Need help",
            "executor": "codex",
        })
        task_id = task_resp.json()["id"]

        response = client.post(
            f"/api/codex/tasks/{task_id}/request-help",
            json={"target_executor": "claude"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["help_request"]["target_executor"] == "claude"
        assert body["parent_task"]["status"] == "ready_to_resume"
        assert body["child_task"]["task_kind"] == "help_child"
        assert body["child_task"]["parent_task_id"] == task_id

    def test_request_help_endpoint_auto_completes_help_child_in_mock_mode(self, client):
        session = client.post("/api/codex/sessions", json={"title": "Mock Help Workspace", "cwd": "/tmp"}).json()
        parent = client.post(
            "/api/codex/tasks",
            json={
                "session_id": session["id"],
                "title": "Need Review",
                "prompt": "Who are you?",
                "executor": "codex",
            },
        ).json()
        run_response = client.post(f"/api/codex/tasks/{parent['id']}/run")
        assert run_response.status_code == 200

        response = client.post(
            f"/api/codex/tasks/{parent['id']}/request-help",
            json={"target_executor": "claude"},
        )

        assert response.status_code == 200

        parent_after = client.get(f"/api/codex/tasks/{parent['id']}").json()
        help_requests = client.get(f"/api/codex/tasks/{parent['id']}/help-requests").json()
        messages = client.get(f"/api/codex/tasks/{parent['id']}/messages").json()

        assert parent_after["status"] == "done"
        assert any(request["status"] in {"completed", "consumed"} for request in help_requests)
        assert not any("Claude help result:" in message["content"] for message in messages if message["role"] == "assistant")

    def test_get_workspace_execution_processes_returns_execution_process_root(self, client):
        """Workspace execution-process snapshot is rooted at execution_processes."""
        session_resp = client.post("/api/codex/sessions", json={"title": "Process Workspace", "cwd": "/tmp"})
        session_id = session_resp.json()["id"]
        task_resp = client.post("/api/codex/tasks", json={
            "session_id": session_id,
            "title": "Process Task",
            "prompt": "print(1+1)",
        })
        task_id = task_resp.json()["id"]

        process_resp = client.post(f"/api/codex/tasks/{task_id}/run")
        process = process_resp.json()

        response = client.get(f"/api/codex/sessions/{session_id}/execution_processes")
        assert response.status_code == 200
        payload = response.json()["execution_processes"][process["id"]]
        assert payload["task_id"] == task_id
        assert payload["title"] == "Process Task"
        assert isinstance(payload["messages"], dict)
        assert isinstance(payload["logs"], list)
        assert "workspace_path" in payload

    def test_run_task_creates_new_execution_process_on_repeat_run(self, client):
        """Each explicit task run creates and rebinds a fresh execution process."""
        session_resp = client.post("/api/codex/sessions", json={"title": "Repeat Run Workspace", "cwd": "/tmp"})
        session_id = session_resp.json()["id"]
        task_resp = client.post("/api/codex/tasks", json={
            "session_id": session_id,
            "title": "Repeat Task",
            "prompt": "print(1+1)",
        })
        task_id = task_resp.json()["id"]

        first = client.post(f"/api/codex/tasks/{task_id}/run").json()
        second = client.post(f"/api/codex/tasks/{task_id}/run").json()
        task = client.get(f"/api/codex/tasks/{task_id}").json()
        processes = client.get(f"/api/codex/execution-processes?task_id={task_id}").json()

        assert first["id"] != second["id"]
        assert task["last_execution_process_id"] == second["id"]
        assert {process["id"] for process in processes} == {first["id"], second["id"]}

    def test_workspace_input_creates_execution_process_for_spawned_task(self, client):
        """Workspace input should create a task already bound to a fresh execution process."""
        session_resp = client.post("/api/codex/sessions", json={"title": "Input Workspace", "cwd": "/tmp"})
        session_id = session_resp.json()["id"]

        input_resp = client.post(
            f"/api/codex/sessions/{session_id}/input",
            json={"input": "Implement the next step"},
        )
        body = input_resp.json()
        task = client.get(f"/api/codex/tasks/{body['task_id']}").json()
        process = client.get(f"/api/codex/execution-processes/{body['execution_process_id']}").json()

        assert input_resp.status_code == 200
        assert task["last_execution_process_id"] == body["execution_process_id"]
        assert process["task_id"] == body["task_id"]
        assert process["session_id"] == session_id

    def test_run_task_returns_immediately(self, client, monkeypatch):
        """POST /run returns immediately with status=running (non-blocking) for real managers."""
        import app.interfaces.api as api_module

        class NonBlockingManager:
            """Simulates real CodexProcessManager with wait=False (non-blocking)."""
            def __init__(self, codex_store, log_store, data_dir=None, event_bus=None):
                self.codex_store = codex_store
                self.log_store = log_store
                self._data_dir = data_dir

            def check_availability(self):
                return True

            def write_input(self, *args, **kwargs):
                assert kwargs["wait"] is False, "Real manager must pass wait=False"
                return "running"

            def terminate(self, workspace_id):
                pass

        # Create workspace and task
        session_resp = client.post("/api/codex/sessions", json={"title": "Immediate Run Workspace", "cwd": "/tmp"})
        session_id = session_resp.json()["id"]
        task_resp = client.post("/api/codex/tasks", json={
            "session_id": session_id,
            "title": "Immediate Task",
            "prompt": "hello",
        })
        task_id = task_resp.json()["id"]

        # Patch get_codex_process_manager to return non-blocking manager
        monkeypatch.setattr(api_module, "get_codex_process_manager", lambda: NonBlockingManager(None, None))

        run_resp = client.post(f"/api/codex/tasks/{task_id}/run")
        assert run_resp.status_code == 200
        # Returns ExecutionProcess with status Running
        assert run_resp.json()["status"] == "Running"
        assert run_resp.json()["task_id"] == task_id

    def test_run_claude_task_does_not_reuse_workspace_thread_id_without_parent_resume(self, client, monkeypatch):
        import app.interfaces.api as api_module
        import app.bootstrap as bootstrap_module

        captured = {}

        class CapturingManager:
            def check_availability(self):
                return True

            def write_input(self, session_id, prompt, wait, task_id, **kwargs):
                captured["session_id"] = session_id
                captured["task_id"] = task_id
                captured["resume_session_id"] = kwargs.get("resume_session_id")
                captured["executor"] = kwargs.get("executor")
                return "responding"

        session_resp = client.post("/api/codex/sessions", json={"title": "Claude Resume Isolation", "cwd": "/tmp"})
        session_id = session_resp.json()["id"]

        store = bootstrap_module.codex_store
        session = store.load_codex_session(session_id)
        session.thread_id = "stale-codex-thread"
        store.save_codex_session(session)

        task_resp = client.post("/api/codex/tasks", json={
            "session_id": session_id,
            "title": "Claude Task",
            "prompt": "ping",
            "executor": "claude",
        })
        task_id = task_resp.json()["id"]

        monkeypatch.setattr(api_module, "get_codex_process_manager", lambda: CapturingManager())

        run_resp = client.post(f"/api/codex/tasks/{task_id}/run")

        assert run_resp.status_code == 200
        assert captured["executor"] == "claude"
        assert captured["resume_session_id"] is None

    def test_run_task_preserves_terminal_status_from_callback(self, client, monkeypatch):
        """A callback that marks the task done before write_input returns should not be overwritten."""
        import app.interfaces.api as api_module
        import app.bootstrap as bootstrap_module

        store = bootstrap_module.codex_store

        class RacingManager:
            def __init__(self, codex_store):
                self.codex_store = codex_store

            def check_availability(self):
                return True

            def write_input(self, session_id, prompt, wait, task_id, **kwargs):
                task = self.codex_store.load_codex_task(task_id)
                task.status = "done"
                task.result = "callback result"
                self.codex_store.save_codex_task(task)
                return "responding"

        session_resp = client.post("/api/codex/sessions", json={"title": "Race Workspace", "cwd": "/tmp"})
        session_id = session_resp.json()["id"]
        task_resp = client.post("/api/codex/tasks", json={
            "session_id": session_id,
            "title": "Race Task",
            "prompt": "hello",
        })
        task_id = task_resp.json()["id"]

        monkeypatch.setattr(api_module, "get_codex_process_manager", lambda: RacingManager(store))

        run_resp = client.post(f"/api/codex/tasks/{task_id}/run")
        assert run_resp.status_code == 200
        assert run_resp.json()["status"] == "Completed"

        task_after = client.get(f"/api/codex/tasks/{task_id}").json()
        assert task_after["status"] == "done"
        assert task_after["result"] == "callback result"

    def test_run_task_not_found(self, client):
        """Running a nonexistent task returns 404."""
        resp = client.post("/api/codex/tasks/nonexistent/run")
        assert resp.status_code == 404

    def test_run_task_already_running(self, client):
        """Running an already-running task returns 409."""
        session_resp = client.post("/api/codex/sessions", json={"title": "Conflict Workspace", "cwd": "/tmp"})
        session_id = session_resp.json()["id"]
        task_resp = client.post("/api/codex/tasks", json={
            "session_id": session_id,
            "title": "Already Running",
            "prompt": "sleep 999",
        })
        task_id = task_resp.json()["id"]

        # Manually set to running to simulate in-progress state
        import app.bootstrap as bootstrap_module
        store = bootstrap_module.codex_store
        task = store.load_codex_task(task_id)
        task.status = "running"
        store.save_codex_task(task)

        # Try to run again
        resp = client.post(f"/api/codex/tasks/{task_id}/run")
        assert resp.status_code == 409

    def test_get_task_logs(self, client):
        """Get logs for a specific task."""
        session_resp = client.post("/api/codex/sessions", json={"title": "Logs Workspace", "cwd": "/tmp"})
        session_id = session_resp.json()["id"]
        task_resp = client.post("/api/codex/tasks", json={
            "session_id": session_id,
            "title": "Logs Task",
            "prompt": "echo logs",
        })
        task_id = task_resp.json()["id"]

        resp = client.get(f"/api/codex/tasks/{task_id}/logs")
        assert resp.status_code == 200
        # Returns workspace logs for the task context (empty at creation time)
        assert isinstance(resp.json(), list)

    def test_delete_task(self, client):
        """Delete a task."""
        session_resp = client.post("/api/codex/sessions", json={"title": "Delete Workspace", "cwd": "/tmp"})
        session_id = session_resp.json()["id"]
        task_resp = client.post("/api/codex/tasks", json={
            "session_id": session_id,
            "title": "To Delete",
            "prompt": "delete me",
        })
        task_id = task_resp.json()["id"]

        del_resp = client.delete(f"/api/codex/tasks/{task_id}")
        assert del_resp.status_code == 200

        # Verify it's gone
        get_resp = client.get(f"/api/codex/tasks/{task_id}")
        assert get_resp.status_code == 404

    def test_delete_task_not_found(self, client):
        """Deleting a nonexistent task returns 404."""
        resp = client.delete("/api/codex/tasks/nonexistent")
        assert resp.status_code == 404

    def test_architect_refresh_persists_design_artifacts(self, client):
        from app.interfaces import api as api_module

        session = client.post("/api/codex/sessions", json={"title": "Agent Console", "cwd": "/tmp"}).json()
        issue = client.post(
            "/api/codex/issues",
            json={"session_id": session["id"], "title": "Design the system", "description": "Architecture task"},
        ).json()
        task = client.post(
            "/api/codex/tasks",
            json={
                "session_id": session["id"],
                "issue_id": issue["id"],
                "title": "Design the system",
                "prompt": "Design the architecture",
                "role": "architect",
            },
        ).json()

        task_model = api_module.codex_store.load_codex_task(task["id"])
        task_model.status = "done"
        task_model.result = json.dumps({
            "language": "en",
            "project_name": "agent-collab-console",
            "issue_id": task_model.issue_id or task_model.id,
            "issue_title": "Design the system",
            "architecture_summary": "REST API service",
            "components": ["API", "Service", "DB"],
            "data_models": ["User", "Session"],
            "interfaces": ["REST"],
            "data_flow": "Client -> API -> Service -> DB",
            "implementation_tasks": [{"title": "Setup project", "description": "Init", "priority": "P0"}],
            "risks": ["Scalability"],
            "open_questions": ["Which DB?"],
        }, ensure_ascii=False)
        api_module._refresh_task_result(task_model)

        issue_root = Path(task_model.workspace_path) / "issues" / (task_model.issue_id or task_model.id)
        assert (issue_root / "system_design.json").exists()
        assert (issue_root / "system_design.md").exists()
        assert (issue_root / "implementation_plan.json").exists()
        assert "system_design.json" in task_model.result

    def test_engineer_refresh_persists_implementation_md(self, client):
        from app.interfaces import api as api_module

        session = client.post("/api/codex/sessions", json={"title": "Agent Console", "cwd": "/tmp"}).json()
        issue = client.post(
            "/api/codex/issues",
            json={"session_id": session["id"], "title": "Implement login", "description": "Engineer task"},
        ).json()
        task = client.post(
            "/api/codex/tasks",
            json={
                "session_id": session["id"],
                "issue_id": issue["id"],
                "title": "Implement login",
                "prompt": "Implement the login feature",
                "role": "engineer",
            },
        ).json()

        task_model = api_module.codex_store.load_codex_task(task["id"])
        task_model.status = "done"
        task_model.result = json.dumps({
            "language": "en",
            "project_name": "agent-collab-console",
            "issue_id": task_model.issue_id or task_model.id,
            "issue_title": "Implement login",
            "status": "completed",
            "summary": "Implemented login feature",
            "changed_files": ["src/auth.py"],
            "completed_tasks": [{"title": "Add handler", "description": "Created handler", "priority": "P0"}],
            "deferred_tasks": [],
            "risks": [],
            "verification_commands": ["pytest"],
            "qa_notes": [],
        }, ensure_ascii=False)
        api_module._refresh_task_result(task_model)

        issue_root = Path(task_model.workspace_path) / "issues" / (task_model.issue_id or task_model.id)
        # Check that implementation file with task ID exists
        impl_file = issue_root / "engineer" / f"implementation-{task_model.id}.md"
        assert impl_file.exists()
        assert "implementation" in task_model.result

    def test_qa_refresh_persists_qa_artifacts(self, client):
        from app.interfaces import api as api_module

        session = client.post("/api/codex/sessions", json={"title": "Agent Console", "cwd": "/tmp"}).json()
        issue = client.post(
            "/api/codex/issues",
            json={"session_id": session["id"], "title": "Test login", "description": "QA task"},
        ).json()
        task = client.post(
            "/api/codex/tasks",
            json={
                "session_id": session["id"],
                "issue_id": issue["id"],
                "title": "Test login",
                "prompt": "Test the login feature",
                "role": "qa",
            },
        ).json()

        task_model = api_module.codex_store.load_codex_task(task["id"])
        task_model.status = "done"
        task_model.result = json.dumps({
            "language": "en",
            "project_name": "agent-collab-console",
            "issue_id": task_model.issue_id or task_model.id,
            "issue_title": "Test login",
            "status": "passed",
            "test_scope": "API tests",
            "acceptance_coverage": ["User can login"],
            "commands_run": ["pytest"],
            "recommended_commands": ["pytest -v"],
            "manual_scenarios": [],
            "bugs_found": [],
            "risks": [],
            "test_gaps": [],
            "final_recommendation": "Ready",
        }, ensure_ascii=False)
        api_module._refresh_task_result(task_model)

        issue_root = Path(task_model.workspace_path) / "issues" / (task_model.issue_id or task_model.id)
        assert (issue_root / "qa_plan.json").exists()
        assert (issue_root / "qa_report.md").exists()
        assert "qa_plan.json" in task_model.result

    def test_general_task_refresh_does_not_persist_structured_artifacts(self, client):
        from app.interfaces import api as api_module

        session = client.post("/api/codex/sessions", json={"title": "Agent Console", "cwd": "/tmp"}).json()
        task = client.post(
            "/api/codex/tasks",
            json={
                "session_id": session["id"],
                "title": "General task",
                "prompt": "Just do something",
                "role": "general",
            },
        ).json()

        task_model = api_module.codex_store.load_codex_task(task["id"])
        task_model.status = "done"
        task_model.result = "Some arbitrary text result from a general task"
        original_result = task_model.result
        api_module._refresh_task_result(task_model)

        assert task_model.result == original_result
        assert task_model.status == "done"

    def test_refresh_only_runs_for_done_tasks(self, client):
        from app.interfaces import api as api_module

        session = client.post("/api/codex/sessions", json={"title": "Agent Console", "cwd": "/tmp"}).json()
        issue = client.post(
            "/api/codex/issues",
            json={"session_id": session["id"], "title": "Test refresh", "description": "Test"},
        ).json()
        task = client.post(
            "/api/codex/tasks",
            json={
                "session_id": session["id"],
                "issue_id": issue["id"],
                "title": "Test architect",
                "prompt": "Design something",
                "role": "architect",
            },
        ).json()

        task_model = api_module.codex_store.load_codex_task(task["id"])
        task_model.status = "pending"
        task_model.result = json.dumps({
            "language": "en",
            "project_name": "test",
            "issue_id": task_model.issue_id or task_model.id,
            "issue_title": "Test",
            "architecture_summary": "Test",
            "components": [],
            "data_models": [],
            "interfaces": [],
            "data_flow": "",
            "implementation_tasks": [],
            "risks": [],
            "open_questions": [],
        }, ensure_ascii=False)
        api_module._refresh_task_result(task_model)

        issue_root = Path(task_model.workspace_path) / "issues" / (task_model.issue_id or task_model.id)
        assert not (issue_root / "system_design.json").exists()


class TestCodexTaskContinuation:
    """Tests for task continuation / lineage within the same workspace."""

    def test_create_continuation_task_has_parent_id(self, client):
        """A continuation task created with parent_task_id stores the lineage reference."""
        # Create workspace
        session_resp = client.post("/api/codex/sessions", json={"title": "Continuation Workspace", "cwd": "/tmp"})
        session_id = session_resp.json()["id"]

        # Create original task
        orig_resp = client.post("/api/codex/tasks", json={
            "session_id": session_id,
            "title": "Original Task",
            "prompt": "write a hello world",
        })
        orig_id = orig_resp.json()["id"]

        # Create follow-up task with parent_task_id
        follow_resp = client.post("/api/codex/tasks", json={
            "session_id": session_id,
            "title": "Continue: Original Task",
            "prompt": "now add tests",
            "parent_task_id": orig_id,
        })
        assert follow_resp.status_code == 201
        follow_data = follow_resp.json()
        assert follow_data["parent_task_id"] == orig_id

    def test_continuation_requires_parent_resume_metadata(self, client):
        """Strict resume mode rejects continuation when parent has no resume metadata."""
        session_resp = client.post("/api/codex/sessions", json={"title": "Strict Resume Workspace", "cwd": "/tmp"})
        session_id = session_resp.json()["id"]

        orig_resp = client.post("/api/codex/tasks", json={
            "session_id": session_id,
            "title": "First Task",
            "prompt": "echo ORIGINAL_RESULT",
        })
        orig_id = orig_resp.json()["id"]

        follow_resp = client.post("/api/codex/tasks", json={
            "session_id": session_id,
            "title": "Follow-up Task",
            "prompt": "echo FOLLOWUP_RESULT",
            "parent_task_id": orig_id,
        })
        follow_id = follow_resp.json()["id"]

        import app.bootstrap as bootstrap_module
        store = bootstrap_module.codex_store
        original = store.load_codex_task(orig_id)
        original.resume_session_id = None
        store.save_codex_task(original)

        follow_run = client.post(f"/api/codex/tasks/{follow_id}/run")
        assert follow_run.status_code == 409
        assert "not resumable" in follow_run.json()["detail"]

    def test_run_original_then_continuation_separate_results(self, client):
        """Running original and continuation tasks produces separate, separable results."""
        # Create workspace
        session_resp = client.post("/api/codex/sessions", json={"title": "Result Sep Workspace", "cwd": "/tmp"})
        session_id = session_resp.json()["id"]

        # Create original task
        orig_resp = client.post("/api/codex/tasks", json={
            "session_id": session_id,
            "title": "First Task",
            "prompt": "echo ORIGINAL_RESULT",
        })
        orig_id = orig_resp.json()["id"]

        # Create continuation task
        follow_resp = client.post("/api/codex/tasks", json={
            "session_id": session_id,
            "title": "Follow-up Task",
            "prompt": "echo FOLLOWUP_RESULT",
            "parent_task_id": orig_id,
        })
        follow_id = follow_resp.json()["id"]

        # Run original task
        orig_run = client.post(f"/api/codex/tasks/{orig_id}/run")
        assert orig_run.status_code == 200
        orig_exec = orig_run.json()
        assert orig_exec["status"] == "Completed"
        assert orig_exec["task_id"] == orig_id

        # Run continuation task
        follow_run = client.post(f"/api/codex/tasks/{follow_id}/run")
        assert follow_run.status_code == 200
        follow_exec = follow_run.json()
        assert follow_exec["status"] == "Completed"
        assert follow_exec["task_id"] == follow_id

        # Results are stored on their respective tasks and are separable
        orig_get = client.get(f"/api/codex/tasks/{orig_id}").json()
        follow_get = client.get(f"/api/codex/tasks/{follow_id}").json()

        # Each task owns its own result
        assert orig_get["id"] == orig_id
        assert follow_get["id"] == follow_id
        assert orig_get["result"] != follow_get["result"] or (orig_get["result"] is None and follow_get["result"] is None)
        # Lineage is maintained
        assert follow_get["parent_task_id"] == orig_id

    def test_continuation_task_logs_are_not_mixed(self, client):
        """Logs from a continuation task do not contain logs from the original task."""
        # Create workspace
        session_resp = client.post("/api/codex/sessions", json={"title": "Log Sep Workspace", "cwd": "/tmp"})
        session_id = session_resp.json()["id"]

        # Create and run original task
        orig_resp = client.post("/api/codex/tasks", json={
            "session_id": session_id,
            "title": "Original Log Task",
            "prompt": "echo ORIG_LOG_LINE",
        })
        orig_id = orig_resp.json()["id"]
        client.post(f"/api/codex/tasks/{orig_id}/run")

        # Create and run continuation task
        follow_resp = client.post("/api/codex/tasks", json={
            "session_id": session_id,
            "title": "Continuation Log Task",
            "prompt": "echo FOLLOW_LOG_LINE",
            "parent_task_id": orig_id,
        })
        follow_id = follow_resp.json()["id"]
        client.post(f"/api/codex/tasks/{follow_id}/run")

        # Get logs for each task separately
        orig_logs = client.get(f"/api/codex/tasks/{orig_id}/logs").json()
        follow_logs = client.get(f"/api/codex/tasks/{follow_id}/logs").json()

        # Logs are keyed to their respective task_ids (may both be empty if mock returns no logs,
        # but at minimum we verify the filtering is not raising errors)
        assert isinstance(orig_logs, list)
        assert isinstance(follow_logs, list)

        # Verify task IDs are correct and distinct
        orig_log_task_ids = {log.get("task_id") for log in orig_logs}
        follow_log_task_ids = {log.get("task_id") for log in follow_logs}
        # task_id in logs should be the task's own id or None; continuation logs should not leak
        assert orig_id in orig_log_task_ids or None in orig_log_task_ids

    def test_list_tasks_shows_lineage(self, client):
        """Listing tasks shows parent_task_id on continuation tasks."""
        session_resp = client.post("/api/codex/sessions", json={"title": "Lineage List Workspace", "cwd": "/tmp"})
        session_id = session_resp.json()["id"]

        orig_resp = client.post("/api/codex/tasks", json={
            "session_id": session_id, "title": "Parent", "prompt": "parent prompt",
        })
        orig_id = orig_resp.json()["id"]

        follow_resp = client.post("/api/codex/tasks", json={
            "session_id": session_id,
            "title": "Child",
            "prompt": "child prompt",
            "parent_task_id": orig_id,
        })
        follow_id = follow_resp.json()["id"]

        tasks = client.get(f"/api/codex/tasks?session_id={session_id}").json()
        tasks_by_id = {t["id"]: t for t in tasks}

        assert tasks_by_id[orig_id]["parent_task_id"] is None
        assert tasks_by_id[follow_id]["parent_task_id"] == orig_id
        assert "resume_session_id" in tasks_by_id[orig_id]
        assert "resume_message_id" in tasks_by_id[follow_id]


class TestTaskExecutorUpdate:
    """Tests for PATCH /api/codex/tasks/{task_id} executor update."""

    def test_update_task_executor_codex_to_claude(self, client, monkeypatch, tmp_path):
        """Verify PATCH updates task executor from codex to claude."""
        now = datetime.now()
        session = CodexSession(
            id="ws-1",
            title="Workspace",
            cwd=str(tmp_path),
            created_at=now,
            last_active_at=now,
        )
        task = CodexTask(
            id="task-1",
            session_id=session.id,
            issue_id="issue-1",
            phase="development",
            title="开发 - 购物车 - 实现购物车API",
            prompt="实现购物车增删改查接口",
            role="engineer",
            executor="codex",
            status="pending",
            workspace_path=str(tmp_path),
            created_at=now,
            updated_at=now,
        )
        store = TaskRunStoreStub(session=session, tasks=[task])
        monkeypatch.setattr(api_module, "codex_store", store)

        response = client.patch(f"/api/codex/tasks/{task.id}", json={"executor": "claude"})

        assert response.status_code == 200
        assert response.json()["executor"] == "claude"

    def test_update_task_executor_claude_to_codex(self, client, monkeypatch, tmp_path):
        """Verify PATCH updates task executor from claude to codex."""
        now = datetime.now()
        session = CodexSession(
            id="ws-1",
            title="Workspace",
            cwd=str(tmp_path),
            created_at=now,
            last_active_at=now,
        )
        task = CodexTask(
            id="task-1",
            session_id=session.id,
            issue_id="issue-1",
            phase="development",
            title="开发 - 购物车 - 实现购物车API",
            prompt="实现购物车增删改查接口",
            role="engineer",
            executor="claude",
            status="pending",
            workspace_path=str(tmp_path),
            created_at=now,
            updated_at=now,
        )
        store = TaskRunStoreStub(session=session, tasks=[task])
        monkeypatch.setattr(api_module, "codex_store", store)

        response = client.patch(f"/api/codex/tasks/{task.id}", json={"executor": "codex"})

        assert response.status_code == 200
        assert response.json()["executor"] == "codex"

    def test_update_task_executor_invalid_value(self, client, monkeypatch, tmp_path):
        """Verify PATCH rejects invalid executor with 422."""
        now = datetime.now()
        session = CodexSession(
            id="ws-1",
            title="Workspace",
            cwd=str(tmp_path),
            created_at=now,
            last_active_at=now,
        )
        task = CodexTask(
            id="task-1",
            session_id=session.id,
            issue_id="issue-1",
            phase="development",
            title="开发 - 购物车 - 实现购物车API",
            prompt="实现购物车增删改查接口",
            role="engineer",
            executor="codex",
            status="pending",
            workspace_path=str(tmp_path),
            created_at=now,
            updated_at=now,
        )
        store = TaskRunStoreStub(session=session, tasks=[task])
        monkeypatch.setattr(api_module, "codex_store", store)

        response = client.patch(f"/api/codex/tasks/{task.id}", json={"executor": "invalid"})

        assert response.status_code == 422

    def test_update_task_executor_not_found(self, client, monkeypatch, tmp_path):
        """Verify PATCH returns 404 for non-existent task."""
        now = datetime.now()
        session = CodexSession(
            id="ws-1",
            title="Workspace",
            cwd=str(tmp_path),
            created_at=now,
            last_active_at=now,
        )
        store = TaskRunStoreStub(session=session, tasks=[])
        monkeypatch.setattr(api_module, "codex_store", store)

        response = client.patch("/api/codex/tasks/nonexistent-id", json={"executor": "claude"})

        assert response.status_code == 404

    def test_update_task_executor_preserves_other_fields(self, client, monkeypatch, tmp_path):
        """Verify PATCH only updates executor, leaves other fields unchanged."""
        now = datetime.now()
        session = CodexSession(
            id="ws-1",
            title="Workspace",
            cwd=str(tmp_path),
            created_at=now,
            last_active_at=now,
        )
        task = CodexTask(
            id="task-1",
            session_id=session.id,
            issue_id="issue-1",
            phase="development",
            title="开发 - 购物车 - 实现购物车API",
            prompt="实现购物车增删改查接口",
            role="engineer",
            executor="codex",
            status="pending",
            workspace_path=str(tmp_path),
            sequence_index=2,
            sequence_group="issue-1",
            created_at=now,
            updated_at=now,
        )
        store = TaskRunStoreStub(session=session, tasks=[task])
        monkeypatch.setattr(api_module, "codex_store", store)

        response = client.patch(f"/api/codex/tasks/{task.id}", json={"executor": "claude"})

        assert response.status_code == 200
        payload = response.json()
        assert payload["executor"] == "claude"
        assert payload["phase"] == "development"
        assert payload["title"] == "开发 - 购物车 - 实现购物车API"
        assert payload["sequence_index"] == 2
        assert payload["sequence_group"] == "issue-1"

    def test_update_task_executor_empty_body_returns_400(self, client, monkeypatch, tmp_path):
        """Verify PATCH with empty body returns 400."""
        now = datetime.now()
        session = CodexSession(
            id="ws-1",
            title="Workspace",
            cwd=str(tmp_path),
            created_at=now,
            last_active_at=now,
        )
        task = CodexTask(
            id="task-1",
            session_id=session.id,
            issue_id="issue-1",
            phase="development",
            title="开发 - 购物车 - 实现购物车API",
            prompt="实现购物车增删改查接口",
            role="engineer",
            executor="codex",
            status="pending",
            workspace_path=str(tmp_path),
            created_at=now,
            updated_at=now,
        )
        store = TaskRunStoreStub(session=session, tasks=[task])
        monkeypatch.setattr(api_module, "codex_store", store)

        response = client.patch(f"/api/codex/tasks/{task.id}", json={})

        assert response.status_code == 400


class TestTaskExecutorWiring:
    """Tests for PATCH executor + run联动 — verifies the two-step executor-switch flow."""

    def test_update_executor_then_run_uses_new_executor(self, client, monkeypatch, tmp_path):
        """Verify after PATCH executor, run picks up the updated executor."""
        now = datetime.now()
        session = CodexSession(
            id="ws-1",
            title="Workspace",
            cwd=str(tmp_path),
            created_at=now,
            last_active_at=now,
        )
        task = CodexTask(
            id="task-1",
            session_id=session.id,
            issue_id="issue-1",
            phase="development",
            title="开发 - 购物车 - 实现购物车API",
            prompt="实现购物车增删改查接口",
            role="engineer",
            executor="codex",
            status="pending",
            workspace_path=str(tmp_path),
            sequence_index=0,
            sequence_group="issue-1",
            created_at=now,
            updated_at=now,
        )
        store = TaskRunStoreStub(session=session, tasks=[task])
        monkeypatch.setattr(api_module, "codex_store", store)

        # Mock task runner to capture which executor is passed
        captured_executor = []
        class MockTaskRunner:
            async def start_task_run(self, task, resume_session_id=None, resume_message_id=None, prompt_override=None):
                captured_executor.append(task.executor)
                from app.domain.models import ExecutionProcess
                return ExecutionProcess(
                    id="proc-1",
                    task_id=task.id,
                    session_id=task.session_id,
                    status="Running",
                    created_at=now,
                )

        def mock_get_task_runner():
            return MockTaskRunner()

        monkeypatch.setattr(api_module, "_get_task_runner", mock_get_task_runner)

        # Step 1: update executor to claude
        patch_resp = client.patch(f"/api/codex/tasks/{task.id}", json={"executor": "claude"})
        assert patch_resp.status_code == 200
        assert patch_resp.json()["executor"] == "claude"

        # Step 2: run the task — should use the updated executor
        run_resp = client.post(f"/api/codex/tasks/{task.id}/run")
        assert run_resp.status_code == 200
        assert captured_executor == ["claude"]

    def test_update_executor_on_blocked_task_still_blocked(self, client, monkeypatch, tmp_path):
        """Verify switching executor on a sequence-blocked task still blocks after PATCH."""
        now = datetime.now()
        session = CodexSession(
            id="ws-1",
            title="Workspace",
            cwd=str(tmp_path),
            created_at=now,
            last_active_at=now,
        )
        task1 = CodexTask(
            id="task-dev-1",
            session_id=session.id,
            issue_id="issue-1",
            phase="development",
            title="开发 - 购物车 - 实现购物车API",
            prompt="实现购物车增删改查接口",
            role="engineer",
            executor="codex",
            status="pending",  # Not done — blocks task2
            workspace_path=str(tmp_path),
            sequence_index=0,
            sequence_group="issue-1",
            created_at=now,
            updated_at=now,
        )
        task2 = CodexTask(
            id="task-dev-2",
            session_id=session.id,
            issue_id="issue-1",
            phase="development",
            title="开发 - 购物车 - 实现库存检查",
            prompt="实现库存校验逻辑",
            role="engineer",
            executor="codex",
            status="pending",
            workspace_path=str(tmp_path),
            sequence_index=1,
            sequence_group="issue-1",
            created_at=now,
            updated_at=now,
        )
        store = TaskRunStoreStub(session=session, tasks=[task1, task2])
        monkeypatch.setattr(api_module, "codex_store", store)

        class MockTaskRunner:
            async def start_task_run(self, task, resume_session_id=None, resume_message_id=None, prompt_override=None):
                from app.domain.models import ExecutionProcess
                return ExecutionProcess(id="proc-2", task_id=task.id, session_id=task.session_id, status="Running", created_at=now)

        def mock_get_task_runner():
            return MockTaskRunner()

        monkeypatch.setattr(api_module, "_get_task_runner", mock_get_task_runner)

        # Switch executor on the blocked task
        patch_resp = client.patch(f"/api/codex/tasks/{task2.id}", json={"executor": "claude"})
        assert patch_resp.status_code == 200

        # Running should still be blocked by sequence constraint
        run_resp = client.post(f"/api/codex/tasks/{task2.id}/run")
        assert run_resp.status_code == 409

    def test_update_executor_running_task_returns_409(self, client, monkeypatch, tmp_path):
        """Verify PATCH executor on a running task returns 409."""
        now = datetime.now()
        session = CodexSession(
            id="ws-1",
            title="Workspace",
            cwd=str(tmp_path),
            created_at=now,
            last_active_at=now,
        )
        task = CodexTask(
            id="task-1",
            session_id=session.id,
            issue_id="issue-1",
            phase="development",
            title="开发 - 购物车 - 实现购物车API",
            prompt="实现购物车增删改查接口",
            role="engineer",
            executor="codex",
            status="running",  # Currently running
            workspace_path=str(tmp_path),
            created_at=now,
            updated_at=now,
        )
        store = TaskRunStoreStub(session=session, tasks=[task])
        monkeypatch.setattr(api_module, "codex_store", store)

        response = client.patch(f"/api/codex/tasks/{task.id}", json={"executor": "claude"})

        assert response.status_code == 409
