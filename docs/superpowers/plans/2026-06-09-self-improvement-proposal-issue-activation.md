# Self-Improvement Proposal Issue Activation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reviewed activation API that turns an accepted non-memory self-improvement proposal into a concrete Codex issue/worktree.

**Architecture:** Reuse the existing dry-run apply-plan service to obtain the single `open_pr_task` candidate, then reuse the issue worktree creation path from `POST /api/codex/issues`. Persist activation audit through `self_improvement_application_events` so repeated calls can be idempotent by returning the existing issue/event.

**Tech Stack:** FastAPI, Pydantic v2, async SQLite store, existing `WorktreeManager`, pytest integration tests.

---

## File Map

- Modify `backend/tests/test_self_improvement_api.py`
  - Add a source issue seeding helper.
  - Add RED API tests for successful activation, idempotence, target/status/source/project guards, and store unavailable.
- Modify `backend/app/interfaces/api.py`
  - Add small serialization/description/idempotence helpers near the existing self-improvement helpers.
  - Add `POST /api/codex/projects/{project_id}/self-improvement-proposals/{proposal_id}/activate-task`.
- Modify `.trellis/spec/vibe-kanban/backend/database-guidelines.md`
  - Extend the "Review-Only Self-Improvement Proposal Ledger" contract with the activation API.

---

### Task 1: Baseline Existing Self-Improvement Tests

**Files:**
- Read: `backend/tests/test_self_improvement_api.py`
- Read: `backend/app/interfaces/api.py`
- Read: `backend/app/application/self_improvement_apply_service.py`

- [ ] **Step 1: Run existing focused tests before changing code**

Run:

```bash
cd backend && python3 -m pytest tests/test_self_improvement_api.py tests/test_self_improvement_apply_service.py -v
```

Expected: Existing tests pass, or any environment blocker is recorded before adding RED tests.

---

### Task 2: Add RED Tests For Activation API

**Files:**
- Modify: `backend/tests/test_self_improvement_api.py`

- [ ] **Step 1: Import `CodexIssue`**

Change:

```python
from app.domain.models import SelfImprovementApplicationEvent, SelfImprovementProposal
```

To:

```python
from app.domain.models import CodexIssue, SelfImprovementApplicationEvent, SelfImprovementProposal
```

- [ ] **Step 2: Add source issue helper after `_seed_proposal`**

```python
def _source_issue(
    project_id: str,
    issue_id: str = "issue-1",
    *,
    session_id: str = "workspace-1",
) -> CodexIssue:
    return CodexIssue(
        id=issue_id,
        session_id=session_id,
        project_id=project_id,
        title="Original runtime failure",
        description="The source issue that produced the proposal.",
        current_phase="done",
        status="completed",
        executor="codex",
        provider="openai",
        model="gpt-5",
        created_at=datetime(2026, 6, 8, 9, 0, 0),
        updated_at=datetime(2026, 6, 8, 9, 1, 0),
    )


def _seed_issue(issue: CodexIssue) -> None:
    import app.bootstrap as bootstrap_module

    assert bootstrap_module.store is not None
    bootstrap_module.store.save_codex_issue(issue)
```

- [ ] **Step 3: Add success test after apply-plan tests**

```python
def test_project_self_improvement_proposal_activate_task_creates_issue_worktree_and_event(client, tmp_path):
    project = _create_project(client, tmp_path, name="self-improvement-activate-task")
    source_issue = _source_issue(project["id"])
    proposal = _proposal(project["id"], target_kind="code_spec", status="accepted")
    _seed_issue(source_issue)
    _seed_proposal(proposal)

    resp = client.post(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/activate-task"
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    activation = body["activation"]
    issue = activation["issue"]
    application = activation["application"]
    assert body["proposal"]["status"] == "accepted"
    assert activation["already_created"] is False
    assert issue["id"] != source_issue.id
    assert issue["project_id"] == project["id"]
    assert issue["session_id"] == source_issue.session_id
    assert issue["title"] == "Apply self-improvement proposal: Harden runtime failure handling"
    assert issue["current_phase"] == "requirements"
    assert issue["status"] == "open"
    assert issue["executor"] == source_issue.executor
    assert issue["provider"] == source_issue.provider
    assert issue["model"] == source_issue.model
    assert issue["git_branch"].startswith(f"issue/{issue['id'][:8]}-")
    assert issue["git_base_branch"] == "main"
    assert issue["git_worktree_path"]
    assert Path(issue["git_worktree_path"]).is_dir()
    assert "Proposal ID: `proposal-1`" in issue["description"]
    assert "Target kind: `code_spec`" in issue["description"]
    assert "Source issue ID: `issue-1`" in issue["description"]
    assert "conductor_task: task-1" in issue["description"]
    assert application["action"] == "open_pr_task"
    assert application["status"] == "succeeded"
    assert application["path"] == f"codex_issues/{issue['id']}"
    assert application["error"] is None
    assert application["result"]["issue_id"] == issue["id"]
    assert application["result"]["git_branch"] == issue["git_branch"]
    assert application["result"]["git_base_branch"] == "main"
    assert application["result"]["git_worktree_path"] == issue["git_worktree_path"]

    proposals = client.get(f"/api/codex/projects/{project['id']}/self-improvement-proposals").json()["proposals"]
    assert proposals[0]["status"] == "accepted"
    events = client.get(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/applications"
    ).json()["applications"]
    assert len(events) == 1
    assert events[0]["action"] == "open_pr_task"
```

- [ ] **Step 4: Add idempotence test**

```python
def test_project_self_improvement_proposal_activate_task_is_idempotent(client, tmp_path):
    project = _create_project(client, tmp_path, name="self-improvement-activate-idempotent")
    _seed_issue(_source_issue(project["id"]))
    _seed_proposal(_proposal(project["id"], target_kind="runtime_tooling", status="accepted"))

    first = client.post(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/activate-task"
    )
    second = client.post(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/activate-task"
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    first_activation = first.json()["activation"]
    second_activation = second.json()["activation"]
    assert first_activation["already_created"] is False
    assert second_activation["already_created"] is True
    assert second_activation["issue"]["id"] == first_activation["issue"]["id"]
    events = client.get(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/applications"
    ).json()["applications"]
    assert len(events) == 1
    issues = client.get(f"/api/codex/issues?project_id={project['id']}").json()
    assert len([issue for issue in issues if issue["title"].startswith("Apply self-improvement proposal:")]) == 1
```

- [ ] **Step 5: Add guard tests**

```python
def test_project_self_improvement_proposal_activate_task_rejects_project_memory(client, tmp_path):
    project = _create_project(client, tmp_path, name="self-improvement-activate-memory")
    _seed_issue(_source_issue(project["id"]))
    _seed_proposal(_proposal(project["id"], target_kind="project_memory", status="accepted"))

    resp = client.post(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/activate-task"
    )

    assert resp.status_code == 409
    assert "project_memory" in resp.json()["detail"]


@pytest.mark.parametrize("status", ["proposed", "rejected", "applied"])
def test_project_self_improvement_proposal_activate_task_requires_accepted_status(client, tmp_path, status):
    project = _create_project(client, tmp_path, name=f"self-improvement-activate-{status}")
    _seed_issue(_source_issue(project["id"]))
    _seed_proposal(_proposal(project["id"], target_kind="runtime_tooling", status=status))

    resp = client.post(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/activate-task"
    )

    assert resp.status_code == 409
    assert "accepted" in resp.json()["detail"]


def test_project_self_improvement_proposal_activate_task_returns_404_for_unknown_or_cross_project(client, tmp_path):
    source_project = _create_project(client, tmp_path, name="self-improvement-activate-source")
    other_project = _create_project(client, tmp_path, name="self-improvement-activate-other")
    _seed_issue(_source_issue(source_project["id"]))
    _seed_proposal(_proposal(source_project["id"], target_kind="runtime_tooling", status="accepted"))

    missing_project_resp = client.post(
        "/api/codex/projects/missing-project/self-improvement-proposals/proposal-1/activate-task"
    )
    missing_proposal_resp = client.post(
        f"/api/codex/projects/{source_project['id']}/self-improvement-proposals/missing/activate-task"
    )
    cross_project_resp = client.post(
        f"/api/codex/projects/{other_project['id']}/self-improvement-proposals/proposal-1/activate-task"
    )

    assert missing_project_resp.status_code == 404
    assert missing_project_resp.json()["detail"] == "Project not found"
    assert missing_proposal_resp.status_code == 404
    assert missing_proposal_resp.json()["detail"] == "Self-improvement proposal not found"
    assert cross_project_resp.status_code == 404
    assert cross_project_resp.json()["detail"] == "Self-improvement proposal not found"


def test_project_self_improvement_proposal_activate_task_rejects_missing_source_issue(client, tmp_path):
    project = _create_project(client, tmp_path, name="self-improvement-activate-missing-source")
    _seed_proposal(_proposal(project["id"], target_kind="runtime_tooling", status="accepted"))

    resp = client.post(
        f"/api/codex/projects/{project['id']}/self-improvement-proposals/proposal-1/activate-task"
    )

    assert resp.status_code == 409
    assert "source issue" in resp.json()["detail"]


def test_project_self_improvement_proposal_activate_task_returns_503_when_store_unavailable(client, monkeypatch):
    from app.interfaces import api as api_module

    monkeypatch.setattr(api_module, "codex_store", None)

    resp = client.post(
        "/api/codex/projects/project-1/self-improvement-proposals/proposal-1/activate-task"
    )

    assert resp.status_code == 503
    assert resp.json()["detail"] == "SQLite store not available"
```

- [ ] **Step 6: Run RED tests**

Run:

```bash
cd backend && python3 -m pytest tests/test_self_improvement_api.py::test_project_self_improvement_proposal_activate_task_creates_issue_worktree_and_event -v
```

Expected: FAIL with `404 Not Found` because `/activate-task` does not exist yet.

---

### Task 3: Implement Activation Endpoint

**Files:**
- Modify: `backend/app/interfaces/api.py`

- [ ] **Step 1: Add helper to serialize a `CodexIssue`**

Add near `_self_improvement_application_event_to_dict`:

```python
def _codex_issue_to_dict(issue: CodexIssue) -> dict:
    if hasattr(issue, "model_dump"):
        return issue.model_dump(mode="json")
    return issue.dict()
```

- [ ] **Step 2: Add helper to parse proposal evidence lines**

```python
def _self_improvement_proposal_evidence_lines(proposal) -> list[str]:
    try:
        evidence = json.loads(proposal.evidence_json or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(evidence, list):
        return []
    lines: list[str] = []
    for item in evidence:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "evidence")
        pointer = item.get("path") or item.get("id") or item.get("summary") or item.get("value")
        if pointer is None:
            pointer = json.dumps(item, sort_keys=True)
        lines.append(f"- {kind}: {pointer}")
    return lines
```

- [ ] **Step 3: Add helper to build activation issue description**

```python
def _build_self_improvement_activation_issue_description(*, proposal, candidate: dict) -> str:
    candidate_body = str(candidate.get("body") or "").strip()
    lines = [
        candidate_body,
        "",
        "---",
        "",
        "Self-improvement activation:",
        f"- Proposal ID: `{proposal.id}`",
        f"- Target kind: `{proposal.target_kind}`",
        f"- Source issue ID: `{proposal.issue_id}`",
        f"- Severity: `{proposal.severity}`",
        f"- Confidence: `{proposal.confidence:.2f}`",
    ]
    evidence_lines = _self_improvement_proposal_evidence_lines(proposal)
    if evidence_lines:
        lines.extend(["", "Evidence:", *evidence_lines])
    return "\n".join(lines).strip()
```

- [ ] **Step 4: Add helper to find the single open PR task candidate**

```python
def _open_pr_task_candidate_from_apply_plan(proposal) -> dict:
    from app.application.self_improvement_apply_service import build_self_improvement_apply_plan

    plan = build_self_improvement_apply_plan(proposal)
    candidates = plan.get("candidate_changes")
    if not isinstance(candidates, list):
        raise ValueError("Self-improvement apply plan does not include candidate changes")
    open_pr_candidates = [
        candidate
        for candidate in candidates
        if isinstance(candidate, dict) and candidate.get("kind") == "open_pr_task"
    ]
    if len(open_pr_candidates) != 1:
        raise ValueError("Self-improvement apply plan must contain exactly one open_pr_task candidate")
    title = open_pr_candidates[0].get("title")
    body = open_pr_candidates[0].get("body")
    if not isinstance(title, str) or not title.strip() or not isinstance(body, str):
        raise ValueError("Self-improvement open_pr_task candidate is invalid")
    return open_pr_candidates[0]
```

- [ ] **Step 5: Add helper to find an existing successful activation**

```python
async def _load_existing_self_improvement_activation(*, project_id: str, proposal_id: str):
    events = await codex_store.list_self_improvement_application_events(
        project_id=project_id,
        proposal_id=proposal_id,
        limit=100,
    )
    for event in events:
        if event.action != "open_pr_task" or event.status != "succeeded":
            continue
        try:
            result = json.loads(event.result_json or "{}")
        except json.JSONDecodeError:
            continue
        if not isinstance(result, dict):
            continue
        issue_id = result.get("issue_id")
        if not isinstance(issue_id, str) or not issue_id:
            continue
        issue = await codex_store.load_codex_issue(issue_id)
        if issue is not None and issue.project_id == project_id:
            return issue, event
    return None
```

- [ ] **Step 6: Add endpoint after `apply-plan` and before `applications`**

```python
@router.post("/codex/projects/{project_id}/self-improvement-proposals/{proposal_id}/activate-task")
async def codex_project_self_improvement_proposal_activate_task(project_id: str, proposal_id: str):
    if codex_store is None:
        raise HTTPException(status_code=503, detail="SQLite store not available")
    project = await codex_store.load_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    proposal = await codex_store.load_self_improvement_proposal(proposal_id)
    if proposal is None or proposal.project_id != project_id:
        raise HTTPException(status_code=404, detail="Self-improvement proposal not found")
    if proposal.status != "accepted":
        raise HTTPException(
            status_code=409,
            detail=(
                "Self-improvement proposal must be accepted before a task can be activated; "
                f"current status is {proposal.status}"
            ),
        )
    if proposal.target_kind == "project_memory":
        raise HTTPException(
            status_code=409,
            detail="project_memory proposals must use the reviewed project-memory apply endpoint",
        )

    source_issue = await codex_store.load_codex_issue(proposal.issue_id)
    if source_issue is None or source_issue.project_id != project_id:
        raise HTTPException(
            status_code=409,
            detail="Self-improvement proposal source issue is unavailable for this project",
        )

    existing = await _load_existing_self_improvement_activation(project_id=project_id, proposal_id=proposal_id)
    if existing is not None:
        existing_issue, existing_event = existing
        return {
            "proposal": _self_improvement_proposal_to_dict(proposal),
            "activation": {
                "issue": _codex_issue_to_dict(existing_issue),
                "application": _self_improvement_application_event_to_dict(existing_event),
                "already_created": True,
            },
        }

    try:
        candidate = _open_pr_task_candidate_from_apply_plan(proposal)
        now = datetime.now()
        issue = CodexIssue(
            id=str(uuid4()),
            session_id=source_issue.session_id,
            project_id=project.id,
            title=str(candidate["title"]).strip(),
            description=_build_self_improvement_activation_issue_description(
                proposal=proposal,
                candidate=candidate,
            ),
            current_phase="requirements",
            status="open",
            executor=source_issue.executor,
            provider=source_issue.provider,
            model=source_issue.model,
            created_at=now,
            updated_at=now,
        )
        branch, worktree_path, base = await worktree_manager.prepare_issue_worktree(project, issue)
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
            "issue": _codex_issue_to_dict(issue),
        })
        event = await _record_self_improvement_application_event(
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
    except (GitError, WorktreeError, ValueError) as exc:
        error = str(exc)
        await _record_self_improvement_application_event(
            proposal=proposal,
            action="open_pr_task",
            status="failed",
            error=error,
        )
        raise HTTPException(
            status_code=500,
            detail=f"failed to activate self-improvement proposal task: {error}",
        ) from exc
    except Exception as exc:  # noqa: BLE001 - store failures lack typed errors
        error = str(exc) or exc.__class__.__name__
        await _record_self_improvement_application_event(
            proposal=proposal,
            action="open_pr_task",
            status="failed",
            error=error,
        )
        raise HTTPException(
            status_code=500,
            detail=f"failed to activate self-improvement proposal task: {error}",
        ) from exc

    return {
        "proposal": _self_improvement_proposal_to_dict(proposal),
        "activation": {
            "issue": _codex_issue_to_dict(issue),
            "application": _self_improvement_application_event_to_dict(event),
            "already_created": False,
        },
    }
```

- [ ] **Step 7: Run activation tests**

Run:

```bash
cd backend && python3 -m pytest tests/test_self_improvement_api.py -k "activate_task" -v
```

Expected: All activation tests pass.

---

### Task 4: Update Backend Ledger Spec

**Files:**
- Modify: `.trellis/spec/vibe-kanban/backend/database-guidelines.md`

- [ ] **Step 1: Extend Signatures**

Add to the API list:

```markdown
- Activation API:
  - `POST /api/codex/projects/{project_id}/self-improvement-proposals/{proposal_id}/activate-task`
  - Response body: `{proposal, activation}` where `activation.issue` is the created or existing Codex issue, `activation.application` is the `open_pr_task` event, and `activation.already_created` marks idempotent reuse.
```

- [ ] **Step 2: Extend Contracts**

Add:

```markdown
- The activation API is limited to `status == "accepted"` and non-`project_memory` target kinds.
- The activation API creates a follow-up `CodexIssue` from the single `open_pr_task` candidate. It inherits the source issue's `session_id`, `executor`, `provider`, and `model`, prepares an issue worktree, appends project audit, emits `issue_created`, and leaves proposal status unchanged.
- Activation records `action="open_pr_task"` application events. Success uses `status="succeeded"`, `path="codex_issues/{issue_id}"`, and `result_json` with `issue_id`, `issue_title`, `git_branch`, `git_base_branch`, and `git_worktree_path`.
- Activation is idempotent: an existing successful `open_pr_task` event that points to an existing same-project issue is returned instead of creating another issue or event.
- Activation failures after project/proposal resolution record `status="failed"` with safe error text and must not mutate proposal status.
```

- [ ] **Step 3: Extend Validation Matrix**

Add:

```markdown
- `codex_store is None` on the activation API -> HTTP `503`, detail `"SQLite store not available"`.
- Unknown `project_id` on the activation API -> HTTP `404`, detail `"Project not found"`.
- Unknown or cross-project proposal on the activation API -> HTTP `404`, detail `"Self-improvement proposal not found"`.
- Activation request for `proposed`, `rejected`, or `applied` proposal -> HTTP `409`, detail states that the proposal must be accepted.
- Activation request for `project_memory` target kind -> HTTP `409`, detail states that project-memory proposals use the reviewed apply endpoint.
- Activation request whose source issue is missing or belongs to another project -> HTTP `409`, proposal status remains unchanged.
- Worktree or store failure while creating the follow-up issue -> HTTP `500`, records a failed `open_pr_task` event, and proposal status remains unchanged.
```

- [ ] **Step 4: Extend Tests Required**

Add activation test bullets matching Task 2.

---

### Task 5: Verification

**Files:**
- Verify: `backend/tests/test_self_improvement_api.py`
- Verify: `backend/tests/test_self_improvement_apply_service.py`
- Verify: `backend/app/interfaces/api.py`
- Verify: `.trellis/spec/vibe-kanban/backend/database-guidelines.md`

- [ ] **Step 1: Run focused tests**

```bash
cd backend && python3 -m pytest tests/test_self_improvement_api.py tests/test_self_improvement_apply_service.py -v
```

Expected: Pass.

- [ ] **Step 2: Run backend fast lane**

```bash
cd backend && python3 -m pytest -v
```

Expected: Pass, with slow tests skipped by default.

- [ ] **Step 3: Run compile smoke**

```bash
cd backend && python3 -m compileall -q app
```

Expected: No output and exit 0.

- [ ] **Step 4: Run app import smoke**

```bash
cd backend && python3 -c "from app.main import app; print(bool(app))"
```

Expected: `True`.

- [ ] **Step 5: Run ruff if available**

```bash
cd backend && python3 -m ruff check .
```

Expected: Pass, or record exact environment failure such as `No module named ruff`.

- [ ] **Step 6: Run diff whitespace check**

```bash
git diff --check
```

Expected: No output and exit 0.

---

### Task 6: Commit And PR

**Files:**
- Commit code/spec/task files changed in this slice only.

- [ ] **Step 1: Inspect dirty state**

```bash
git status --porcelain
```

- [ ] **Step 2: Commit implementation**

```bash
git add backend/tests/test_self_improvement_api.py backend/app/interfaces/api.py .trellis/spec/vibe-kanban/backend/database-guidelines.md docs/superpowers/plans/2026-06-09-self-improvement-proposal-issue-activation.md .trellis/tasks/06-09-self-improvement-proposal-issue-activation
git commit -m "feat: activate self-improvement proposals as tasks"
```

- [ ] **Step 3: Push and open PR**

```bash
git push -u origin codex/self-improvement-pr-task-activation
gh pr create --title "Activate self-improvement proposals as tasks" --body-file <prepared-body>
```

Expected: Ready PR URL is produced.

- [ ] **Step 4: Merge after CI**

Use the existing PR workflow after CI is green, then archive the Trellis task in a separate bookkeeping PR from latest `origin/main`.
