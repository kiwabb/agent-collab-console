# brainstorm: github pr follow-up automation

## Goal

Make GitHub PR follow-up autonomous enough that an issue can keep moving after
the branch is pushed and the PR is opened: the system should refresh PR state,
record audit evidence, detect reviewer changes/CI failures/merged state, and
feed actionable review feedback back into the existing rework loop without a
human repeatedly clicking "Refresh PR".

## What I already know

* The Moonshot target requires end-to-end unattended issue handling through PR
  review, merge, and memory writeback.
* Current backend has manual endpoints:
  * `POST /codex/issues/{issue_id}/pr/create`
  * `POST /codex/issues/{issue_id}/pr/refresh`
  * `POST /codex/issues/{issue_id}/merge`
* `refresh_github_pr(...)` already reads `gh pr view`, updates
  `github_pr_state`, marks remotely merged PRs as merged, and copies the latest
  changes-requested review body into the latest engineer task.
* The frontend Diff/Merge tab exposes a manual Refresh PR button.
* PR #1 added a review-only self-improvement proposal ledger.
* PR #2 added deterministic Conductor policy evidence.

## Assumptions

* This slice should be backend-first and deterministic; frontend polish can
  follow later.
* The first version should not auto-merge GitHub PRs unless the PR is already
  marked `MERGED` remotely. Merging an open PR should remain out of scope until
  CI/review/branch protection semantics are explicitly modeled.
* The existing `gh` CLI dependency is acceptable for this app because PR create
  and refresh already rely on it.

## Requirements

* Add a reusable service/function that refreshes GitHub PR state for one issue
  without depending on a manual API click.
* Add a project-level sweep that finds issues with `github_pr_url` and
  non-merged `git_merge_status`, refreshes each PR, and returns structured
  results.
* Record audit/event evidence for each sweep result so unattended follow-up is
  observable.
* Preserve current manual refresh endpoint behavior by routing it through the
  same reusable logic.
* When GitHub review requests changes, keep using the existing rework path:
  latest engineer task becomes `pending` with review feedback.
* When the PR is already `MERGED` on GitHub, mark the local issue
  `git_merge_status="merged"` and lifecycle `status="completed"`.
* Failures for one issue must not stop the project sweep from refreshing other
  issues.
* Add focused backend tests for single issue refresh, sweep behavior, requested
  changes, merged PR state, and failure isolation.

## Acceptance Criteria

* [x] Manual `refresh_github_pr(...)` and automated project sweep share the same
      refresh implementation.
* [x] A project-level endpoint or conductor-accessible function can refresh all
      open PR-backed issues for a project.
* [x] Refresh results include stable statuses such as `updated`, `changes_requested`,
      `merged`, and `failed`.
* [x] Changes-requested reviews enqueue rework via existing engineer task
      fields/events.
* [x] Failed GitHub status checks are detected as `checks_failed` with
      structured message/audit evidence.
* [x] Remotely merged PRs update both `git_merge_status` and issue lifecycle
      status.
* [x] Sweep failures are best-effort and isolated per issue.
* [x] Focused backend tests pass.

## Definition of Done

* Tests added/updated.
* Focused backend tests pass.
* Broader affected backend tests pass.
* PR opened against `main`.
* CI green before merge.

## Out of Scope

* Automatically merging open GitHub PRs.
* Implementing GitHub App/webhook authentication.
* Frontend redesign of the Diff/Merge tab.
* Replacing `gh` with direct REST/GraphQL calls.

## Technical Notes

* Existing code lives in `backend/app/interfaces/api.py` around
  `create_github_pr(...)`, `refresh_github_pr(...)`, and
  `merge_codex_issue(...)`.
* Current frontend manual refresh wiring lives in
  `frontend/src/features/issues/tabs/DiffMergeTab.tsx`.
* Likely extraction target: a new application-layer module so API endpoints and
  conductor/scheduled review code can reuse the same logic.
