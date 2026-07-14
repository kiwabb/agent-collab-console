# Information, settings, and analytics structural layouts

## Goal

Apply the pane/section language to Settings, Knowledge, and Benchmarks: replace dashboard-like structural card stacks with sectioned documents, command bars, result lists, summary strips, and bounded analytical fields.

## Requirements

### Settings

- Treat Settings as one sectioned document instead of a grid of preference cards.
- Present theme, locale, typography, motion, and density as semantic grouped rows/fieldsets with clear labels and control focus states.
- Remove redundant outer `Card` containers around Runtime, Agents, and MCP where the pane itself provides containment.
- Flatten nested tier/option containers while retaining separate save/error lifecycle boundaries for executor definitions and other independently edited records.
- Preserve dialogs, errors, schemas/code blocks, and Base UI control semantics.

### Knowledge

- Replace rounded tab, search/filter, and result wrappers with line tabs, one command bar, and one continuous results pane.
- Preserve the existing divided result rows, loading/empty/error states, search behavior, and keyboard navigation.
- Use full pane width for results while constraining long prose metadata to a readable measure.

### Benchmarks

- Reconcile the route with the chosen global shell/navigation model instead of assuming `WorkbenchShell` changes apply automatically.
- Replace repeated 24px rounded panels and nested metric tiles with a stable analytics toolbar/tab strip, summary strip, continuous table/analysis surfaces, and contextual detail where appropriate.
- Retain bounded chart plots, selected-run details, regression alerts, calibration/diff artifacts, dialogs, and exports when containment communicates a real coordinate or lifecycle boundary.
- Keep loading, empty, and error states in the same structural skeleton to avoid layout jumps.

## Acceptance Criteria

- [ ] Settings reads as one document with grouped rows/sections, not a dashboard tile grid.
- [ ] Runtime, Agent, and MCP management retain all save/error/control behavior without redundant outer cards.
- [ ] Knowledge exposes line navigation, a single command bar, and a continuous divided result list.
- [ ] Benchmarks uses the same app-shell language and no longer nests summary tiles inside repeated enterprise panels.
- [ ] Charts and independently selected analytical artifacts remain properly bounded.
- [ ] All three routes work at 1440px, 900px, and 390px without clipped controls or unintended body overflow.
- [ ] i18n parity, focus visibility, disabled/invalid states, compact mode, and theme behavior remain intact.

## Technical Approach

Reuse the global pane graph and existing Base UI line tabs, inputs, selects, separators, tables, and dialogs. Prefer semantic fieldsets/tables/lists and feature-local sections; promote a shared primitive only after confirming repeated use across these routes. No new charting, resizable-panel, or UI dependency is required.

## Dependencies

- Blocked by `07-14-global-pane-graph-foundation`.
- Can proceed in parallel with `07-14-projects-workspace-continuous-layouts` after the foundation lands.

## Out of Scope

- Settings behavior, runtime catalog schema, search API, or benchmark calculation changes.
- New benchmark navigation/product capabilities beyond shell consistency.
- Flattening chart plots, alerts, dialogs, or independently saved records that need containment.

## Validation

- Relevant Settings, Knowledge, Benchmarks, i18n, and source-hygiene tests.
- Typecheck and targeted node:test suites.
- Browser walkthrough at 1440px, 900px, and 390px, including light/dark and compact modes.
