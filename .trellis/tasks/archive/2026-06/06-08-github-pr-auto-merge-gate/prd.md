# brainstorm: github pr auto merge gate

## Goal

Close the next autonomy gap after GitHub PR follow-up: when an issue's PR is
open, approved, all required status checks are green, and GitHub reports a
mergeable state, the system should merge the PR without a human clicking the
GitHub button. Unsafe or ambiguous states must remain review-only and
observable.

## What I already know

* PR #3 added `backend/app/application/github_pr_followup.py`, shared by manual
  issue refresh and project-level follow-up sweep.
* The follow-up service already reads `state`, `reviewDecision`, `reviews`,
  `mergeStateStatus`, and `statusCheckRollup`.
* The service emits stable statuses: `updated`, `changes_requested`,
  `checks_failed`, `merged`, and `failed`.
* Current behavior only marks an issue merged if GitHub already reports
  `state == "MERGED"`. It does not merge an eligible open PR.
* The Moonshot requires the system to complete the PR lifecycle unattended.

## Requirements

* Add an opt-in auto-merge mode to the project PR follow-up sweep.
* Auto-merge may run only when all of these are true:
  * PR state is `OPEN`.
  * `reviewDecision == "APPROVED"`.
  * `mergeStateStatus` is a known mergeable value.
  * All completed status checks have success/skipped/neutral conclusions.
  * No status check is still pending/in progress.
* On merge-ready PRs, run `gh pr merge <url> --merge --delete-branch`.
* After a successful merge command, refresh/mark the issue as merged and
  completed with audit/event evidence.
* If the merge command fails, return `merge_failed` for that issue, record
  audit/event evidence, and continue sweeping other issues.
* Preserve default safety: existing project follow-up endpoint must not
  auto-merge unless requested explicitly.
* Add focused backend tests for safe merge, unsafe states, merge failure, and
  endpoint opt-in behavior.

## Acceptance Criteria

* [x] Project follow-up endpoint accepts an explicit auto-merge option.
* [x] Default project follow-up remains non-merging.
* [x] Approved, mergeable, all-green PRs are merged via `gh pr merge`.
* [x] Pending checks prevent auto-merge.
* [x] Missing status checks prevent auto-merge.
* [x] Failed checks continue to produce `checks_failed`, not merge.
* [x] Non-approved reviews prevent auto-merge.
* [x] Merge command failure/exception produces `merge_failed` and does not
      stop the sweep.
* [x] Successful auto-merge marks the issue `git_merge_status="merged"` and
      lifecycle `status="completed"`.
* [x] Focused backend tests pass.

## Definition of Done

* Tests added/updated.
* Focused backend tests pass.
* Broader affected backend tests pass.
* PR opened against `main`.
* CI green before merge.

## Out of Scope

* Squash/rebase merge mode selection UI.
* Direct GitHub REST/GraphQL integration.
* Bypassing branch protection.
* Auto-merge when checks are missing or still pending.

## Technical Notes

* Implement in `backend/app/application/github_pr_followup.py` to keep API and
  future conductor/scheduled paths sharing one state machine.
* Extend `POST /api/codex/projects/{project_id}/pr/follow-up`; avoid changing
  manual single-issue refresh semantics unless tests require it.
* Existing PR follow-up tests live in `backend/tests/test_github_pr_followup.py`.
