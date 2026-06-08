# brainstorm: self improvement activation auto start

## Goal

Move the self-improvement loop one step closer to unattended execution by
letting an accepted non-memory proposal activate a follow-up Codex issue and,
when explicitly requested, immediately start the existing issue Conductor loop
for that follow-up issue.

Today `activate-task` creates a concrete issue/worktree but still requires a
second human/API action (`POST /api/codex/issues/{issue_id}/graph/auto-start`)
before autonomous engineering begins. This task closes that handoff gap without
changing the reviewed/proposal safety boundary.

## What I already know

* PR #33 added
  `POST /api/codex/projects/{project_id}/self-improvement-proposals/{proposal_id}/activate-task`.
* The endpoint is accepted-only, rejects `project_memory`, creates an issue
  worktree, records `action="open_pr_task"`, and is idempotent when a prior
  successful activation points to an existing issue.
* `POST /api/codex/issues/{issue_id}/graph/auto-start` already creates a
  minimal `WorkflowGraph`, launches `run_issue_conductor_loop(...)` in the
  background, and uses `ConductorSessionRegistry.try_start(...)` to avoid two
  live conductor sessions for the same issue.
* The previous activation PR intentionally left auto-start out of scope.
* The Moonshot requires the system to move from lesson/proposal extraction to
  actually scheduling and running follow-up engineering work.

## Assumptions

* Auto-start should be opt-in for this slice, not default, because starting a
  conductor can spend model budget and run tools.
* The existing issue Conductor path should be reused rather than creating a
  new self-improvement runner.
* Repeated activation with `start_conductor=true` should be idempotent:
  return the existing activation issue and start/return the existing graph
  rather than creating duplicate issues or duplicate live conductor sessions.
* Starting the conductor is an execution handoff, not proposal application; the
  proposal should remain `accepted`.
* If conductor start fails after activation succeeds, the issue activation
  should remain durable and audited. The API should surface the start failure
  without deleting the issue/worktree or mutating proposal status.

## Requirements

* Extend the activation request with an optional body:
  `{"start_conductor": true | false}`.
* Preserve backwards compatibility:
  * no body and `{}` mean `start_conductor=false`;
  * the response shape remains `{proposal, activation}`.
* When `start_conductor=false`, behavior stays the same as PR #33.
* When `start_conductor=true`, the endpoint starts Conductor orchestration for
  the follow-up issue using the same semantics as
  `POST /api/codex/issues/{issue_id}/graph/auto-start`.
* The activation response includes conductor metadata when requested:
  `activation.conductor = {"started": bool, "graph": <WorkflowGraph JSON> |
  null, "already_running": bool}`.
* If an existing successful activation is reused and `start_conductor=true`,
  the endpoint starts or returns the existing follow-up issue graph.
* The conductor start path must use `ConductorSessionRegistry` so duplicate
  activation requests cannot launch duplicate live conductors.
* A conductor start failure records a failed self-improvement application event
  with `action="start_conductor"`, safe error text, and
  `path="codex_issues/{issue_id}"`.
* A successful conductor start records a succeeded application event with
  `action="start_conductor"`, `path="codex_issues/{issue_id}"`, and
  result metadata including `issue_id`, `graph_id`, `graph_status`, and
  `already_running`.
* Repeated `start_conductor=true` calls may record another
  `start_conductor` event for the operator-visible start attempt, but must not
  create another follow-up issue or duplicate live conductor session.
* The endpoint must not:
  * apply project memory;
  * mark the proposal `applied`;
  * merge a PR;
  * change `.trellis/spec/`, prompts, policies, tools, or source patches
    directly.

## Acceptance Criteria

* [ ] API test covers `start_conductor=false` preserving the existing response
  and creating no workflow graph.
* [ ] API test covers accepted non-memory proposal with
  `start_conductor=true` creating one follow-up issue, one graph, one live
  conductor start attempt, one `open_pr_task` event, and one succeeded
  `start_conductor` event.
* [ ] API test covers repeated `start_conductor=true` returning the existing
  follow-up issue/graph and creating no duplicate issue or live conductor.
* [ ] API test covers `start_conductor=true` on an already activated proposal
  that was first activated without starting the conductor.
* [ ] API test covers conductor start failure preserving the activated issue,
  leaving proposal status `accepted`, and recording failed
  `start_conductor` event.
* [ ] Existing activation guard tests still pass: non-accepted statuses,
  `project_memory`, missing/cross-project source issue, unknown project or
  proposal, and store unavailable.
* [ ] Backend ledger spec documents the request body, response conductor
  fields, start event audit rows, idempotence, validation matrix, and tests.

## Definition of Done

* TDD red/green evidence for activation auto-start behavior.
* Focused self-improvement API tests pass.
* Full backend fast-lane tests run, or an environment blocker is documented.
* `compileall`, app import smoke, and `git diff --check` pass.
* `ruff` is run if available; if unavailable, record the exact failure.
* PR is opened, CI passes, merged, and Trellis task is archived with a journal
  entry.

## Out of Scope

* Automatically accepting proposals.
* Starting Conductor by default on every activation.
* Auto-creating or merging GitHub PRs.
* Applying `code_spec`, `conductor_policy`, `runtime_tooling`, or
  `benchmark_eval` proposals directly.
* Frontend UI changes for the new request body/response field.
* New scheduler/daemon for scanning accepted proposals.

## Technical Notes

* API file: `backend/app/interfaces/api.py`.
* Existing activation endpoint:
  `codex_project_self_improvement_proposal_activate_task(...)`.
* Existing issue start endpoint: `auto_start_issue_graph(issue_id)`.
* Existing conductor idempotence: `ConductorSessionRegistry.try_start(...)`.
* Relevant tests: `backend/tests/test_self_improvement_api.py`,
  `backend/tests/test_conductor_session_registry.py`,
  `backend/tests/test_project_conductor.py`.
* Relevant spec:
  `.trellis/spec/vibe-kanban/backend/database-guidelines.md`, scenario
  "Review-Only Self-Improvement Proposal Ledger".
