# Global layout consistency and regression verification

## Goal

Finish the repository-wide de-cardification program with a route consistency sweep, targeted corrections for lower-impact structural containers, and comprehensive automated plus browser verification across the completed workstreams.

## Requirements

### Consistency sweep

- Audit root `/`, Help, Audit, Artifacts, and Conductor Monitor against the final pane/object hierarchy.
- Remember that root `/` uses a separate `WorkbenchPage`; apply shell-language corrections explicitly rather than assuming `WorkbenchShell` coverage.
- Remove only structural cardification from these secondary surfaces.
- Preserve object cards for independently selectable/actionable workspaces, issues, Kanban tasks, artifact issue groups, and conductor records.
- Convert document sequences and audit collections to sections/rows when evidence supports it, without creating a new product mode.
- Confirm no mounted route still uses enterprise panels/cards merely as page, toolbar, navigation, filter, inspector-section, or KPI wrappers.

### Automated verification

- Run focused tests after each targeted correction, then the full frontend test suite.
- Run strict TypeScript typecheck, lint, and format check.
- Run `npm run build` only after stopping the live dev server or from an isolated temporary copy with its own `.next`; never clobber an active development server.
- Update/add stable source-contract tests for the global pane and selective-containment rules without brittle whole-markup snapshots.

### Browser verification

- Exercise primary routes at 1440px, 900px, and 390px.
- Verify light/dark themes, compact mode, large text/zoom, and reduced motion.
- Check keyboard focus, active/selected/non-color cues, mobile sheets/pane switchers, local scroll ownership, empty/loading/error states, and console/network regressions.
- Recheck the previously confirmed `/projects` and `/projects/[id]` mobile overflow failures.

## Acceptance Criteria

- [ ] All routes use a coherent edge-to-edge structural language while legitimate domain-object and overlay containment remains intact.
- [ ] No audited route has body-level horizontal overflow at 390px or clipped critical controls at 900px.
- [ ] Root workbench object cards retain their independent-object semantics and are not flattened indiscriminately.
- [ ] Focus, selection, status, disabled, loading, empty, and error states remain perceivable and accessible.
- [ ] Typecheck, full frontend tests, lint, and format checks pass.
- [ ] Build passes under a safe non-colliding procedure.
- [ ] Browser walkthrough results and any unavoidable exceptions are recorded accurately.

## Dependencies

- Final child task; blocked by all four implementation workstreams.

## Working-tree protection

- Do not reset, clean, stage, or overwrite unrelated concurrent work.
- Preserve the structured-prototype deletion vertical slice and startup-service-identity task.
- Never inspect or touch `examples/admin-demo/.env`.

## Out of Scope

- New list/table modes for root workspace/issue/task cards.
- Changes to unmounted `InboxDashboard` unless a real route is discovered.
- Backend behavior, new product functionality, or new dependencies.

## Deliverables

- Targeted consistency fixes where required.
- Updated stable tests/specs.
- A verification record covering commands, viewports, themes/preferences, observed results, and any remaining limitations.
