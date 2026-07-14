# Startup configuration UX findings

## Existing flow

- The project configuration page owns the Operations Engineer trigger beside the run-command editor.
- The resulting environment variables live under the project workspace `/projects/:id/env` route.
- Completion feedback only says that scripts were updated, so users cannot discover the environment-variable result or the next action.
- Project start/stop controls currently live on the workspace list page, creating a third location in the same flow.

## UX guidance applied

The UI/UX design-system search classified this as an operations-console flow and recommended a flat, status-first interface with one primary action. The detailed UX search emphasized progress indicators, explicit loading/success/error feedback, and a continuous multi-step path.

Applied principles:

- Keep analysis, configuration validation, and project start in one deep-linkable project page.
- Use one primary CTA per state: analyze/reanalyze while idle, stop while running.
- Show a compact three-step status model: analyze, configure, run.
- Preserve manual script editing in project configuration, but replace the analysis action there with a secondary shortcut to Startup Config.
- Keep the existing `/env` URL for compatibility while renaming the visible destination to Startup Config.
- Use existing semantic tokens and Lucide icons; do not introduce a new visual language.

## Implementation constraints

- Reuse the existing background `project_script_suggestion` task endpoint and task polling contract.
- Reuse the existing project run APIs rather than introducing a second backend execution path.
- The persisted `Project` record provides setup and run commands; the latest completed task result supplies access URL and operational notes when available.
- Environment variables remain managed through the existing GET/PUT/DELETE endpoints.
