# Diagnostics Supervisor Health

## Problem

`GET /api/diagnostics` exposes project review scheduler and GitHub PR
follow-up status snapshots, but the top-level `status` only degrades on
`last_error`. A supervisor can be visibly running/stuck while the global health
still reads as otherwise healthy. Autonomous operation needs a sharper health
signal for unattended loops.

## Scope

Add derived diagnostics checks for supervisor status snapshots.

## Requirements

- `GET /api/diagnostics` marks the `github_pr_followup` check as degraded when
  its snapshot has `last_error` or `running=true`.
- `GET /api/diagnostics` marks the `project_review_scheduler` check as degraded
  when its snapshot has `last_error` or `running=true`.
- The top-level diagnostics `status` becomes `"degraded"` when either
  supervisor check is degraded.
- Check `detail` remains safe: use existing safe `last_error` text when
  present; otherwise use a short generic running-state message.
- Diagnostics must not expose secrets, repo paths, project names, issue titles,
  prompts, or tracebacks.

## Non-Goals

- No auto-restart behavior.
- No stale-time threshold.
- No persistence or history table.
- No frontend changes.

## Acceptance Criteria

- Focused diagnostics tests cover PR follow-up failure and running states.
- Focused diagnostics tests cover project review scheduler running state.
- Existing diagnostics secret-redaction behavior remains covered.
- Backend focused tests pass.
