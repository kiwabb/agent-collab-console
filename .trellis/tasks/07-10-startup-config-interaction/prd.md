# Refactor project startup configuration interaction

## Goal

Turn the fragmented project-startup experience into one continuous, project-scoped flow: analyze the repository, review generated scripts and environment variables, fill missing values, and start or stop the project from the same page.

## Requirements

- Rename the visible project navigation destination from Environment Config to Startup Config while preserving the existing `/projects/:id/env` route.
- Make Startup Config the primary home of the Operations Engineer analysis action.
- Change the project configuration page's current Operations Engineer button into a secondary shortcut to Startup Config; keep manual setup-script and run-command editing intact.
- On Startup Config, show:
  - analysis progress and terminal success/failure feedback;
  - a compact Analyze -> Configure -> Run step indicator;
  - current setup script and run command;
  - latest analysis metadata when available, including access URL, notes, and analysis time;
  - environment-variable count and missing-value count;
  - the existing environment-variable editor;
  - project start/stop status and action;
  - incremental startup logs plus explicit terminal exit feedback.
- Refresh project data, task result, environment variables, and run status after relevant actions without destroying previously loaded data on transient errors.
- Re-entering the page while an analysis task is active must recover the running state and continue polling.
- If no variables are detected, show an actionable empty state that offers analysis.
- If variables are missing, make the missing state visible and prevent a misleading ready state.
- Use existing semantic theme tokens, shared buttons/inputs, Lucide icons, i18n, and accessibility semantics.

## Acceptance Criteria

- [ ] The project shell displays `Startup Config` / `启动配置` instead of `Env Config` / `环境配置`.
- [ ] The project configuration page no longer starts analysis directly and provides a link to `/projects/:id/env`.
- [ ] The Startup Config header starts or restarts the Operations Engineer task and shows a busy state while it runs.
- [ ] A completed analysis refreshes scripts and environment variables in place and shows an explicit summary.
- [ ] Failed or long-running analysis has a clear state and recovery path.
- [ ] Existing analysis results are reconstructed from the latest project script task after a reload.
- [ ] Environment variables remain editable, saveable, and deletable.
- [ ] The same page can start a ready project and stop a running project.
- [ ] A successful start request is presented as command submission/running, not service readiness.
- [ ] A process that exits non-zero shows a failed state, exit code, actionable log line, retained full logs, and a retry action.
- [ ] Reloading the page reconstructs the latest run status and logs without starting a new process.
- [ ] Missing environment values are counted and surfaced before start.
- [ ] Chinese and English dictionaries remain in parity.
- [ ] Focused frontend tests and TypeScript checks pass.
- [ ] The page is verified in the running local browser at desktop width and a narrow viewport.

## Definition of Done

- Frontend source and focused tests are updated.
- TypeScript typecheck and relevant node tests pass.
- The running app is visually and behaviorally verified.
- No unrelated dirty files are modified.

## Technical Approach

- Refactor `ProjectEnvConfigPage` into the unified Startup Config page and pass the loaded `Project` record from its route component.
- Use the existing project-script task API and task API to recover/poll the latest Operations Engineer task.
- Add a pure parser/selector for the latest startup-analysis result so persisted task JSON is handled at the API-data boundary and is unit tested.
- Reuse the existing project run API contract for start/stop/status.
- Simplify `ProjectsPage` by removing its analysis-task state machine and replacing the current button with a route link.
- Keep `/env` as the stable URL to avoid a routing migration in this task.

## Decision (ADR-lite)

**Context:** The action starts in global project configuration, environment results appear inside the project workspace, and execution controls live on another page.

**Decision:** Consolidate the complete workflow in the existing `/env` destination, rename it Startup Config, and leave only a secondary shortcut on the project configuration page.

**Consequences:** The primary workflow becomes continuous and deep-linkable. The route name remains legacy (`/env`) for compatibility. Workspace run controls remain available as a secondary operational surface for now.

## Expansion and edge cases included

- Recover active background analysis after navigation/reload.
- Preserve stale visible data during refresh failures.
- Distinguish never analyzed, analyzing, ready, incomplete, failed, and running states.
- Keep manual script editing available for advanced users.

## Out of Scope

- Changing backend environment-variable detection or encryption/materialization behavior.
- Renaming `/env` to a new URL or adding redirects.
- Removing existing run controls from the workspace list page.
- Persisting new analysis fields on the `projects` database table.
- Redesigning unrelated project configuration cards.

## Research References

- [`research/startup-config-ux.md`](research/startup-config-ux.md) — repo-specific interaction findings and applied operations-console UX principles.

## Technical Notes

- Primary files: `ProjectEnvConfigPage.tsx`, `ProjectEnvConfigRoutePage.tsx`, `ProjectShell.tsx`, `ProjectsPage.tsx`, project/task API clients, shared types, i18n dictionaries, and focused frontend tests.
- Frontend guidelines: `.trellis/spec/ccgui/frontend/index.md` and its linked component, hooks, state, quality, and type-safety guides.
- Existing user changes in `frontend/tsconfig.tsbuildinfo` must remain untouched.
