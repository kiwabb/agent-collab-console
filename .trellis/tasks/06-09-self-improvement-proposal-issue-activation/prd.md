# brainstorm: self improvement proposal issue activation

## Goal

Close the next self-improvement loop gap by letting an accepted non-memory
self-improvement proposal create a concrete Codex issue/worktree that can enter
the existing autonomous engineering pipeline. Today non-memory proposals only
return an `open_pr_task` dry-run candidate, so the system can identify lessons
but cannot yet schedule them as executable work.

## What I already know

* The Moonshot requires self-improvement to move from extracted lessons to
  recursively fixing the system itself.
* Current proposal extraction, review, apply-plan, project-memory apply, and
  rollback APIs are merged and CI-green.
* `build_self_improvement_apply_plan()` returns `open_pr_task` for
  non-`project_memory` target kinds.
* `POST /api/codex/issues` already creates an issue, materializes an issue
  worktree, emits `issue_created`, and appends project audit.
* A real self-improvement proposal references a source `issue_id`; using that
  issue lets the activation inherit the correct `session_id`, project, executor
  settings, and base branch.
* `self_improvement_application_events` already gives us an audit ledger for
  apply-like actions without inventing another table.

## Assumptions

* Activation should only be allowed for `status == "accepted"` proposals.
* Activation should be limited to non-`project_memory` targets; project memory
  continues to use the reviewed hash-gated apply endpoint.
* Creating a follow-up issue is not the same as applying the proposal, so the
  proposal should remain `accepted` rather than becoming `applied`.
* Repeating activation should be idempotent: if an `open_pr_task` activation
  event already points to a follow-up issue, return that issue instead of
  creating duplicates.

## Requirements

* Add a reviewed activation API:
  `POST /api/codex/projects/{project_id}/self-improvement-proposals/{proposal_id}/activate-task`.
* The endpoint validates the project and proposal with the same project-scoped
  hiding rules as the existing review/apply-plan/apply APIs.
* The endpoint requires proposal `status == "accepted"`.
* The endpoint rejects `target_kind == "project_memory"` because project memory
  has its own reviewed apply endpoint.
* The endpoint requires the proposal's source `CodexIssue` to exist and belong
  to the same project.
* On first activation, the endpoint creates a new `CodexIssue` using the source
  issue's `session_id`, project id, executor/provider/model, and default base
  branch; it prepares an issue worktree using the existing worktree manager.
* The created issue title comes from the `open_pr_task` candidate title.
* The created issue description includes the candidate body, proposal id,
  target kind, source issue id, severity, confidence, and evidence lines.
* The endpoint records one `self_improvement_application_events` row with
  `action="open_pr_task"`, `status="succeeded"`, `path="codex_issues/{issue_id}"`,
  and result metadata including `issue_id`, `issue_title`, `git_branch`,
  `git_base_branch`, and `git_worktree_path`.
* If activation is repeated and a prior successful `open_pr_task` event points
  to an existing issue for the same project/proposal, return that issue and the
  prior event without creating a new issue.
* Worktree or store failure after project/proposal resolution records a failed
  application event with safe error text and does not change proposal status.
* The endpoint must not write `.trellis/spec/`, project memory, prompts,
  policies, tools, source patches, or proposal status.

## Acceptance Criteria

* [ ] API test covers accepted non-memory proposal -> new Codex issue,
  worktree metadata, project audit/event, application event, proposal remains
  accepted.
* [ ] API test covers repeated activation -> returns the existing issue and
  does not create another issue/event.
* [ ] API test covers `project_memory` activation rejected with `409`.
* [ ] API test covers non-accepted statuses rejected with `409`.
* [ ] API test covers missing/cross-project proposal/project returns `404`.
* [ ] API test covers missing source issue rejected with `409`.
* [ ] Backend spec documents signatures, contracts, validation matrix,
  good/base/bad cases, tests, and wrong/correct examples.

## Definition of Done

* TDD red/green evidence for activation behavior.
* Focused self-improvement API tests pass.
* Full backend fast-lane test suite is run, or an environment blocker is
  documented.
* `compileall`, app import smoke, and `git diff --check` pass.
* `ruff` is run if available; if unavailable, record the exact failure.
* PR is opened, CI passes, merged, and Trellis task is archived with a journal
  entry.

## Out of Scope

* Automatically starting the conductor on the follow-up issue.
* Automatically creating or merging a GitHub PR for the follow-up issue.
* Direct application of `code_spec`, `conductor_policy`, `runtime_tooling`, or
  `benchmark_eval` proposals.
* Marking a proposal `applied` when only the follow-up issue was created.
* Frontend UI changes for the new endpoint.

## Technical Notes

* API file: `backend/app/interfaces/api.py`.
* Apply-plan service: `backend/app/application/self_improvement_apply_service.py`.
* Domain models: `CodexIssue`, `SelfImprovementProposal`,
  `SelfImprovementApplicationEvent` in `backend/app/domain/models.py`.
* Existing API tests: `backend/tests/test_self_improvement_api.py`.
* Existing issue creation API path: `POST /api/codex/issues`.
* Relevant spec: `.trellis/spec/vibe-kanban/backend/database-guidelines.md`,
  scenario "Review-Only Self-Improvement Proposal Ledger".
