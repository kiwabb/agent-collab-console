# Projects workspace continuous layouts

## Goal

Turn the complete project path—project selection, project overview, Conductor, startup/environment configuration, and structured workspace navigation—into a coherent continuous tool surface, while fixing the confirmed project-page mobile overflows.

## Requirements

### Projects configuration (`/projects`)

- Replace the floating selector plus stacked equal-weight cards with a continuous master/detail layout.
- Make the project list a structural navigation rail and the selected project a single detail pane with a compact identity/action strip, summary strip, and divider-separated sections.
- Remove the duplicated branch collection and keep one authoritative branch list.
- Present setup script and run command as configuration sections with bounded readable width, not hover-lifting cards.
- Reflow project actions on narrow screens so no control is clipped or unreachable.

### Project workspaces (`/projects/[id]`)

- Convert the four KPI tiles into one compact summary/status strip.
- Preserve the existing divided workspace-row collection and legitimate log/terminal boundary.
- Make the toolbar responsive and replace the fixed six-column mobile overflow with deliberate column hiding/reflow or a mobile row composition.
- Keep default and workspace `ProjectShell` modes consistent with the new global pane graph while preserving route state and active navigation semantics.

### Project Conductor, startup, and environment configuration

- Flatten structural rounded parents and KPI/progress card grids into continuous project panes, summary strips, fieldsets, rows, and section dividers.
- Preserve the existing divided environment-variable collection and all run/env validation behavior.
- Keep forms within a readable width while allowing operational tables/logs to use the pane width.

## Acceptance Criteria

- [ ] `/projects` has one rail and one continuous detail pane, not a panel plus five peer cards.
- [ ] Branches render once; setup/run/branch/activity hierarchy is unambiguous.
- [ ] At 390px, project header actions fit or wrap without horizontal clipping.
- [ ] `/projects/[id]` retains scan-friendly workspace rows and has no toolbar/table body overflow at 390px.
- [ ] Project Conductor, startup, and environment pages use the same structural page language without losing any controls or state.
- [ ] Project navigation exposes current location through visible non-color cues and ARIA.
- [ ] Existing project/prototype routing and structured-studio tests remain green.

## Technical Approach

Build on the global pane-graph foundation and existing feature-local components. Use CSS Grid for master/detail and responsive row templates, `minmax(0, 1fr)`, `min-w-0`, section dividers, and semantic tables/lists where comparison benefits from aligned columns. Keep true lifecycle boundaries—terminal/log, destructive confirmation, error/empty state, and independently saved editor—contained.

## Dependencies

- Blocked by `07-14-global-pane-graph-foundation`.
- Can proceed in parallel with `07-14-knowledge-benchmarks-structural-layouts` after the foundation lands.

## Working-tree protection

- Preserve current `ProjectShell` and structured-prototype layout/deletion changes.
- Preserve the unrelated startup-service-identity task and its research; do not absorb or rewrite that work.
- Do not touch `examples/admin-demo/.env`.

## Out of Scope

- Backend project/run/env API changes.
- New workspace list/board product modes.
- Draggable project rails or persisted widths.

## Validation

- Relevant project routing/source tests and project feature tests.
- Typecheck and targeted node:test suites.
- Browser walkthrough at 1440px, 900px, and 390px for every project route listed above.
