# brainstorm: self improvement proposal scheduler

## Goal

Close the next self-improvement autonomy gap by running a backend scheduler
that finds accepted, non-memory self-improvement proposals and automatically
hands them to the existing reviewed activation path with `start_conductor=true`.

The previous activation slice made the execution handoff possible, but it still
requires a human or external API caller to invoke `activate-task`. This slice
turns accepted proposals into unattended follow-up engineering issues without
changing the review boundary: proposals must already be accepted, project
memory remains reviewed/manual, and scheduler activation must not mark a
proposal applied or directly edit specs, prompts, tools, policies, memory, or
source code.

## What I Already Know

* PR #35 added optional `start_conductor=true` support to
  `POST /api/codex/projects/{project_id}/self-improvement-proposals/{proposal_id}/activate-task`.
* The activation endpoint already rejects `project_memory`, requires
  `status == "accepted"`, creates/reuses one follow-up issue/worktree, and
  uses `ConductorSessionRegistry` to avoid duplicate live issue conductors.
* PR #35 explicitly left "New scheduler/daemon for scanning accepted
  proposals" out of scope.
* The backend already has a reusable scheduler pattern in
  `app.application.project_review_scheduler`: pure tick function, result
  summary, status snapshot, resilient background loop, lifespan task, and
  diagnostics integration.
* Diagnostics already treats supervisor snapshots with `running`, `last_error`,
  and stale `last_completed_at` as degraded checks.
* Scheduler/cost knobs live in `app.application.timeouts`, not in feature code
  via `os.getenv`.
* The self-improvement ledger spec requires safe audit events and forbids
  direct application of non-memory proposals.

## Assumptions

* The scheduler may run by default because it acts only after a proposal is
  already accepted. The accepted status is the review/authorization boundary.
* To avoid repeating expensive work, a proposal with a succeeded
  `start_conductor` application event should be skipped on later ticks.
* A proposal with a succeeded `open_pr_task` event but no succeeded
  `start_conductor` event should be picked up and started.
* A failed scheduler activation/start should be retried on a later tick because
  the failure may be transient. The existing activation helper records failed
  activation/start application events.
* This slice should expose operational status but does not need a frontend UI.

## Requirements

* Add an application-layer scheduler module for accepted self-improvement
  proposals.
* The scheduler tick scans accepted proposals with a configurable limit.
* The scheduler skips:
  * `target_kind == "project_memory"`;
  * proposals that already have a succeeded `start_conductor` application
    event;
  * proposals outside the accepted status because the store query asks for
    `status="accepted"`.
* For every eligible proposal, the scheduler calls the same activation behavior
  used by the HTTP endpoint with `start_conductor=true`.
* The scheduler must not:
  * accept proposals;
  * mark proposals `applied`;
  * directly mutate `.agent-collab/team_notes.md`, `.trellis/spec/`, prompts,
    policies, tools, or source code;
  * create duplicate follow-up issues for a proposal;
  * launch duplicate live conductors for a follow-up issue.
* The scheduler tick isolates proposal failures. One failed proposal must not
  stop the rest of the tick.
* The scheduler loop survives a failed tick, records status, and continues
  after sleeping, matching the project review scheduler pattern.
* Add timeout/config accessors:
  * `SELF_IMPROVEMENT_PROPOSAL_INTERVAL_S`, default `3600.0`;
  * `SELF_IMPROVEMENT_PROPOSAL_LIMIT`, default `25`.
* Add a status snapshot with fields compatible with diagnostics supervisor
  checks: `configured`, `interval_s`, `limit`, `running`, `tick_count`,
  `last_started_at`, `last_completed_at`, `last_error`, and
  `last_summary_counts`.
* Wire the loop into FastAPI lifespan as a named task:
  `self-improvement-proposal-scheduler`.
* Cancel and await the scheduler task during shutdown like the existing
  watchdog/scheduler tasks.
* Add diagnostics output:
  * top-level `self_improvement_proposal_scheduler` object;
  * `checks[]` entry named `self_improvement_proposal_scheduler`;
  * degraded state when running, errored, or stale.
* Update backend Trellis specs with the scheduler contract so future agents do
  not silently change the safety boundary.

## Acceptance Criteria

* [ ] Scheduler tick activates eligible accepted non-memory proposals and passes
  `start_conductor=True` to the activation function.
* [ ] Scheduler tick skips `project_memory` proposals and proposals with a
  succeeded `start_conductor` application event.
* [ ] Scheduler tick isolates activation failures and continues processing
  later eligible proposals.
* [ ] Scheduler tick honors the configured limit.
* [ ] Scheduler loop repeats, survives tick exceptions, propagates cancellation,
  and records success/failure/running status.
* [ ] Lifespan starts and shuts down the new named scheduler task.
* [ ] Diagnostics includes the scheduler snapshot and degraded checks for
  running, errored, and stale scheduler states.
* [ ] Timeout tests cover shipped defaults, env overrides, and invalid fallback
  for the new scheduler knobs.
* [ ] Focused backend tests pass.
* [ ] Full backend fast lane runs, or any environment blocker is documented.

## Definition of Done

* TDD red/green evidence for scheduler selection, loop/status, diagnostics, and
  lifespan wiring.
* `backend` focused tests pass for self-improvement scheduler, diagnostics,
  lifespan shutdown, and timeouts.
* `python3 -m pytest -v` backend fast lane passes, or an environment blocker is
  recorded.
* `python3 -m compileall -q app`, app import smoke, and `git diff --check`
  pass.
* `python3 -m ruff check .` is run if available; if unavailable, record the
  exact failure.
* PR is opened, CI passes, merged, and Trellis task is archived with a journal
  entry.

## Out of Scope

* Automatically accepting proposed self-improvement proposals.
* Applying project memory without the reviewed hash endpoint.
* Marking a proposal `applied` when its follow-up issue is merely created or
  started.
* Following the created PR through review/merge.
* Frontend UI for scheduler status.
* New database schema or migrations.
* New direct patching model for `code_spec`, `conductor_policy`,
  `runtime_tooling`, or `benchmark_eval`.

## Technical Notes

* Existing scheduler pattern:
  `backend/app/application/project_review_scheduler.py`.
* Existing lifespan scheduler wiring: `backend/app/main.py`.
* Existing diagnostics supervisor checks: `backend/app/interfaces/api.py`,
  `_supervisor_status_check`.
* Existing activation endpoint/helpers:
  `backend/app/interfaces/api.py`,
  `codex_project_self_improvement_proposal_activate_task(...)`.
* Existing proposal/application store APIs:
  `list_self_improvement_proposals(...)` and
  `list_self_improvement_application_events(...)`.
* Relevant specs:
  `.trellis/spec/vibe-kanban/backend/index.md`,
  `.trellis/spec/vibe-kanban/backend/database-guidelines.md`,
  `.trellis/spec/vibe-kanban/backend/error-handling.md`,
  `.trellis/spec/vibe-kanban/backend/quality-guidelines.md`,
  `.trellis/spec/vibe-kanban/backend/logging-guidelines.md`,
  `.trellis/spec/guides/cross-layer-thinking-guide.md`, and
  `.trellis/spec/guides/code-reuse-thinking-guide.md`.
