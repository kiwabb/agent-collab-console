# GitHub PR Follow-Up Diagnostics

## Problem

The autonomous PR follow-up sweep can refresh review, CI, and merge state, but
operators cannot see whether that supervisor path is configured, currently
running, recently succeeded, or recently failed from `GET /api/diagnostics`.
That leaves unattended operation with a blind spot after "open PR".

## Scope

Add a safe in-memory operational status snapshot for GitHub PR follow-up sweeps
and expose it in diagnostics.

## Requirements

- `sweep_project_github_prs(...)` records a status snapshot for project sweep
  executions.
- The snapshot includes only safe fields:
  - `configured`
  - `running`
  - `sweep_count`
  - `last_started_at`
  - `last_completed_at`
  - `last_error`
  - `last_summary_counts`
  - `auto_merge_enabled`
- Successful sweeps increment `sweep_count`, clear `last_error`, set
  `last_completed_at`, and store the summary `counts`.
- Sweep exceptions record safe error text, increment `sweep_count`, clear
  `running`, and re-raise so existing callers keep their current error handling.
- Manual single-issue refresh does not update the project sweep snapshot.
- `GET /api/diagnostics` exposes the snapshot as a top-level
  `github_pr_followup` object.
- Diagnostics must not expose GitHub tokens, repository paths, prompts, raw
  tracebacks, or issue/project titles.

## Non-Goals

- No persistent history table.
- No new scheduler loop.
- No change to auto-merge gating rules.
- No new GitHub API calls.

## Acceptance Criteria

- Focused tests prove diagnostics includes `github_pr_followup`.
- Focused tests prove a successful project sweep updates the snapshot.
- Focused tests prove a failed project sweep updates `last_error` and clears
  `running` while preserving existing exception behavior.
- Existing follow-up and diagnostics tests remain green.
