# Self-Improvement Activation Auto-Start Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let accepted non-memory self-improvement proposal activation optionally start the follow-up issue's existing Conductor loop.

**Architecture:** Keep `activate-task` backwards-compatible by adding an optional request body with `start_conductor: false` by default. Extract the existing issue graph auto-start logic into a reusable private API helper, then have activation call it only when requested and record separate `start_conductor` application events.

**Tech Stack:** FastAPI, Pydantic v2, async SQLite store, existing `ConductorSessionRegistry`, existing `run_issue_conductor_loop`, pytest.

---

## File Map

- Modify `backend/tests/test_self_improvement_api.py`
  - Add RED tests for no-body compatibility, opt-in start response/event, repeated start idempotence, late start on an already activated proposal, start failure audit, and helper-level registry idempotence.
- Modify `backend/app/interfaces/api.py`
  - Add `SelfImprovementProposalActivateTaskRequest`.
  - Extract `_start_issue_conductor_graph(...)` from `auto_start_issue_graph(...)`.
  - Add activation-side conductor response/event helpers.
- Modify `.trellis/spec/vibe-kanban/backend/database-guidelines.md`
  - Document activation request body, response conductor field, `start_conductor` events, validation, and tests.

---

### Task 1: Baseline

**Files:**
- Read: `backend/tests/test_self_improvement_api.py`
- Read: `backend/app/interfaces/api.py`

- [ ] **Step 1: Run current focused tests**

```bash
cd backend && python3 -m pytest tests/test_self_improvement_api.py tests/test_self_improvement_apply_service.py -v
```

Expected: current tests pass before adding RED tests.

---

### Task 2: RED Tests

**Files:**
- Modify: `backend/tests/test_self_improvement_api.py`

- [ ] **Step 1: Add imports for async helper testing**

```python
import asyncio

from app.adapters.async_sqlite_store import AsyncSQLiteStore
from app.application.conductor_session_registry import ConductorSessionRegistry
from app.domain.models import CodexIssue, Project, SelfImprovementApplicationEvent, SelfImprovementProposal
```

- [ ] **Step 2: Add test helper to inspect application events**

```python
def _applications(client, project_id: str, proposal_id: str = "proposal-1") -> list[dict]:
    return client.get(
        f"/api/codex/projects/{project_id}/self-improvement-proposals/{proposal_id}/applications"
    ).json()["applications"]
```

- [ ] **Step 3: Add no-body compatibility test**

```python
def test_project_self_improvement_proposal_activate_task_without_body_does_not_start_conductor(
    client,
    tmp_path,
    monkeypatch,
):
    from app.interfaces import api as api_module

    project = _create_project(client, tmp_path, name="self-improvement-activate-no-body")
    _seed_issue(_source_issue(project["id"]))
    _seed_proposal(_proposal(project["id"], target_kind="runtime_tooling", status="accepted"))

    async def fail_if_called(*_args, **_kwargs):
        raise AssertionError("conductor should not start without explicit opt-in")

    monkeypatch.setattr(api_module, "_start_issue_conductor_graph", fail_if_called)

    resp = client.post(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/activate-task"
    )

    assert resp.status_code == 200, resp.text
    activation = resp.json()["activation"]
    assert "conductor" not in activation
    assert [event["action"] for event in _applications(client, project["id"])] == ["open_pr_task"]
```

- [ ] **Step 4: Add opt-in start test**

```python
def test_project_self_improvement_proposal_activate_task_can_start_conductor(client, tmp_path, monkeypatch):
    from app.interfaces import api as api_module

    project = _create_project(client, tmp_path, name="self-improvement-activate-start")
    _seed_issue(_source_issue(project["id"]))
    _seed_proposal(_proposal(project["id"], target_kind="runtime_tooling", status="accepted"))
    calls: list[str] = []

    async def fake_start(issue_id: str, *, store):
        calls.append(issue_id)
        return {
            "started": True,
            "already_running": False,
            "graph": {
                "id": "graph-1",
                "issue_id": issue_id,
                "status": "running",
                "nodes": [],
                "edges": [],
            },
        }

    monkeypatch.setattr(api_module, "_start_issue_conductor_graph", fake_start)

    resp = client.post(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/activate-task",
        json={"start_conductor": True},
    )

    assert resp.status_code == 200, resp.text
    activation = resp.json()["activation"]
    assert calls == [activation["issue"]["id"]]
    assert activation["conductor"]["started"] is True
    assert activation["conductor"]["already_running"] is False
    assert activation["conductor"]["graph"]["id"] == "graph-1"
    events = _applications(client, project["id"])
    assert [event["action"] for event in events] == ["start_conductor", "open_pr_task"]
    assert events[0]["status"] == "succeeded"
    assert events[0]["path"] == f"codex_issues/{activation['issue']['id']}"
    assert events[0]["result"]["graph_id"] == "graph-1"
    assert events[0]["result"]["started"] is True
```

- [ ] **Step 5: Add repeated activation start test**

```python
def test_project_self_improvement_proposal_activate_task_reuses_issue_when_starting_conductor_twice(
    client,
    tmp_path,
    monkeypatch,
):
    from app.interfaces import api as api_module

    project = _create_project(client, tmp_path, name="self-improvement-activate-start-repeat")
    _seed_issue(_source_issue(project["id"]))
    _seed_proposal(_proposal(project["id"], target_kind="runtime_tooling", status="accepted"))
    starts: list[str] = []

    async def fake_start(issue_id: str, *, store):
        starts.append(issue_id)
        return {
            "started": len(starts) == 1,
            "already_running": len(starts) > 1,
            "graph": {"id": "graph-1", "issue_id": issue_id, "status": "running", "nodes": [], "edges": []},
        }

    monkeypatch.setattr(api_module, "_start_issue_conductor_graph", fake_start)

    first = client.post(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/activate-task",
        json={"start_conductor": True},
    )
    second = client.post(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/activate-task",
        json={"start_conductor": True},
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["activation"]["already_created"] is True
    assert second.json()["activation"]["issue"]["id"] == first.json()["activation"]["issue"]["id"]
    assert starts == [first.json()["activation"]["issue"]["id"], first.json()["activation"]["issue"]["id"]]
    issues = client.get(f"/api/codex/issues?project_id={project['id']}").json()
    assert len([issue for issue in issues if issue["title"].startswith("Apply self-improvement proposal:")]) == 1
```

- [ ] **Step 6: Add late start and failure tests**

```python
def test_project_self_improvement_proposal_activate_task_can_start_existing_activation(
    client,
    tmp_path,
    monkeypatch,
):
    from app.interfaces import api as api_module

    project = _create_project(client, tmp_path, name="self-improvement-activate-late-start")
    _seed_issue(_source_issue(project["id"]))
    _seed_proposal(_proposal(project["id"], target_kind="runtime_tooling", status="accepted"))
    first = client.post(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/activate-task"
    )
    issue_id = first.json()["activation"]["issue"]["id"]

    async def fake_start(issue_id_arg: str, *, store):
        assert issue_id_arg == issue_id
        return {
            "started": True,
            "already_running": False,
            "graph": {"id": "graph-late", "issue_id": issue_id_arg, "status": "running", "nodes": [], "edges": []},
        }

    monkeypatch.setattr(api_module, "_start_issue_conductor_graph", fake_start)

    second = client.post(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/activate-task",
        json={"start_conductor": True},
    )

    assert second.status_code == 200, second.text
    assert second.json()["activation"]["already_created"] is True
    assert second.json()["activation"]["conductor"]["graph"]["id"] == "graph-late"


def test_project_self_improvement_proposal_activate_task_records_failed_start_event(
    client,
    tmp_path,
    monkeypatch,
):
    from app.interfaces import api as api_module

    project = _create_project(client, tmp_path, name="self-improvement-activate-start-fail")
    _seed_issue(_source_issue(project["id"]))
    _seed_proposal(_proposal(project["id"], target_kind="runtime_tooling", status="accepted"))

    async def fail_start(*_args, **_kwargs):
        raise RuntimeError("synthetic conductor start failure")

    monkeypatch.setattr(api_module, "_start_issue_conductor_graph", fail_start)

    resp = client.post(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/activate-task",
        json={"start_conductor": True},
    )

    assert resp.status_code == 500
    assert "synthetic conductor start failure" in resp.json()["detail"]
    proposals = client.get(f"/api/codex/projects/{project['id']}/self-improvement-proposals").json()["proposals"]
    assert proposals[0]["status"] == "accepted"
    events = _applications(client, project["id"])
    assert [event["action"] for event in events] == ["start_conductor", "open_pr_task"]
    assert events[0]["status"] == "failed"
    assert "synthetic conductor start failure" in events[0]["error"]
```

- [ ] **Step 7: Add helper-level registry idempotence test**

```python
async def test_start_issue_conductor_graph_is_idempotent_while_session_is_alive(monkeypatch, tmp_path):
    from app.application import conductor_main_loop
    from app.interfaces import api as api_module

    store = AsyncSQLiteStore(tmp_path / "conductor-start.db")
    project = Project(
        id="project-1",
        name="project",
        repo_path=str(tmp_path / "repo"),
        default_branch="main",
        created_at=datetime(2026, 6, 9, 9, 0, 0),
        updated_at=datetime(2026, 6, 9, 9, 0, 0),
    )
    issue = _source_issue(project.id, issue_id="issue-start-helper")
    issue.git_worktree_path = str(tmp_path / "repo-worktree")
    await store.save_project(project)
    await store.save_codex_issue(issue)

    async def sleep_forever(**_kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(conductor_main_loop, "run_issue_conductor_loop", sleep_forever)

    try:
        first = await api_module._start_issue_conductor_graph(issue.id, store=store)
        second = await api_module._start_issue_conductor_graph(issue.id, store=store)
        assert first["started"] is True
        assert first["already_running"] is False
        assert second["started"] is False
        assert second["already_running"] is True
        assert second["graph"]["id"] == first["graph"]["id"]
        assert ConductorSessionRegistry.instance().is_alive(issue.id)
    finally:
        await ConductorSessionRegistry.instance().stop(issue.id)
        await store.close()
```

- [ ] **Step 8: Run one RED test**

```bash
cd backend && python3 -m pytest tests/test_self_improvement_api.py::test_project_self_improvement_proposal_activate_task_can_start_conductor -v
```

Expected: fail because `start_conductor` is ignored and no `conductor` response/event exists.

---

### Task 3: Implementation

**Files:**
- Modify: `backend/app/interfaces/api.py`

- [ ] **Step 1: Add activation request model**

```python
class SelfImprovementProposalActivateTaskRequest(BaseModel):
    start_conductor: bool = False
```

- [ ] **Step 2: Extract issue conductor start helper**

Create `_start_issue_conductor_graph(issue_id: str, *, store) -> dict` near
`auto_start_issue_graph(...)`. Move the current `auto_start_issue_graph` body
into it, returning:

```python
{
    "graph": _graph_to_dict(graph),
    "started": handle is not None,
    "already_running": handle is None or was_alive_before_start,
}
```

Then make `auto_start_issue_graph(issue_id)` call the helper and return only
`result["graph"]`.

- [ ] **Step 3: Add activation conductor helpers**

Add:

```python
def _self_improvement_conductor_result(issue_id: str, start_result: dict) -> dict:
    graph = start_result.get("graph")
    return {
        "issue_id": issue_id,
        "graph_id": graph.get("id") if isinstance(graph, dict) else None,
        "graph_status": graph.get("status") if isinstance(graph, dict) else None,
        "started": bool(start_result.get("started")),
        "already_running": bool(start_result.get("already_running")),
    }
```

Add async helpers to record `start_conductor` succeeded/failed events through
`_record_self_improvement_application_event(...)`.

- [ ] **Step 4: Update activation endpoint signature and flow**

Change endpoint signature to:

```python
async def codex_project_self_improvement_proposal_activate_task(
    project_id: str,
    proposal_id: str,
    request: SelfImprovementProposalActivateTaskRequest | None = Body(default=None),
):
```

Use `start_conductor = bool(request.start_conductor) if request else False`.
For both existing and new activation branches, if `start_conductor` is true:

```python
start_result = await _start_issue_conductor_graph(issue.id, store=codex_store)
event = await _record_self_improvement_application_event(...)
activation["conductor"] = start_result
```

On start failure:

```python
await _record_self_improvement_application_event(
    proposal=proposal,
    action="start_conductor",
    status="failed",
    path=f"codex_issues/{issue.id}",
    error=safe_error,
)
raise HTTPException(status_code=500, detail=f"failed to start self-improvement conductor: {safe_error}") from exc
```

- [ ] **Step 5: Run activation auto-start tests**

```bash
cd backend && python3 -m pytest tests/test_self_improvement_api.py -k "activate_task" -v
```

Expected: pass.

---

### Task 4: Spec Update

**Files:**
- Modify: `.trellis/spec/vibe-kanban/backend/database-guidelines.md`

- [ ] **Step 1: Extend activation signature**

Document the optional request body and the optional `activation.conductor`
response field.

- [ ] **Step 2: Extend activation contracts**

Document explicit opt-in, proposal status preservation, reuse of the issue
Conductor path, `start_conductor` succeeded/failed events, and duplicate
session prevention through `ConductorSessionRegistry`.

- [ ] **Step 3: Extend validation matrix and tests**

Document start failures, no-body compatibility, repeated starts, and helper
idempotence coverage.

---

### Task 5: Verification

**Files:**
- Verify: `backend/tests/test_self_improvement_api.py`
- Verify: `backend/tests/test_self_improvement_apply_service.py`
- Verify: `backend/app/interfaces/api.py`
- Verify: `.trellis/spec/vibe-kanban/backend/database-guidelines.md`

- [ ] **Step 1: Focused tests**

```bash
cd backend && python3 -m pytest tests/test_self_improvement_api.py tests/test_self_improvement_apply_service.py -v
```

- [ ] **Step 2: Backend fast lane**

```bash
cd backend && python3 -m pytest -v
```

- [ ] **Step 3: Compile and import smoke**

```bash
cd backend && python3 -m compileall -q app
cd backend && python3 -c "from app.main import app; print(bool(app))"
```

- [ ] **Step 4: Ruff and diff checks**

```bash
cd backend && python3 -m ruff check .
git diff --check
```

Record `No module named ruff` if local ruff is unavailable.
