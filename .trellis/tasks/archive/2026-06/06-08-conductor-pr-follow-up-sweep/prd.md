# Conductor PR Follow-Up Sweep

## Goal

Move GitHub PR follow-up from a manually-invoked endpoint toward autonomous operation by wiring the existing project PR follow-up sweep into the project review/conductor path.

## Requirements

1. When a project-level autonomous review/scheduling pass runs for a GitHub-backed project, it invokes the existing `sweep_project_github_prs` service with `auto_merge=True`.
2. The sweep result is observable in the review/conductor output so operators can see how many PRs were updated, blocked, failed, or merged.
3. A sweep failure is best-effort: it is captured in the review/conductor output and logged, but it does not crash or prevent the rest of the project review path from completing.
4. The HTTP follow-up endpoint added earlier keeps its existing opt-in behavior and remains unchanged unless a test proves the shared service contract needs tightening.

## Acceptance Criteria

- A focused backend test proves the autonomous project review path calls `sweep_project_github_prs(..., auto_merge=True)`.
- A focused backend test proves sweep failures are reported without raising from the review path.
- Existing GitHub PR follow-up tests still pass.
- Backend import smoke succeeds.

## Non-Goals

- Do not add a new scheduler process in this slice.
- Do not loosen the auto-merge gates implemented in the previous task.
- Do not change frontend behavior.
