# Global pane graph foundation

## Goal

Replace the desktop workbench's detached rounded sidebar and route-content panels with one edge-to-edge pane graph, and establish the shared surface, divider, radius, spacing, and page-frame rules that every later layout task will reuse.

## Requirements

- Refactor `WorkbenchShell`, desktop `AppSidebar`, `AppHeader`, and `PageFrame` so global navigation, header, route content, and contextual areas are sibling panes joined by subtle one-sided dividers.
- Remove the desktop shell's decorative 22/30px rounded frames, ambient grouping gradients, backdrop blur, large gutters, and structural shadows.
- Preserve the full-height containment chain (`h-dvh`, `min-h-0`, `min-w-0`, local scroll owners) so routes do not force viewport overflow.
- Preserve the existing mobile navigation sheet and legitimate floating surfaces such as dialogs, menus, popovers, alerts, and sheets.
- Define/reuse a coherent hierarchy using existing tokens: app ground, structural pane, row/grouped control, independent object, real preview boundary, and floating overlay.
- Structural panes have radius 0 and no shadow; active/focus/status signals use the existing brand and semantic colors.
- Expose reusable page-section, command-strip, summary-strip, and divider patterns only when repeated consumers justify promotion; avoid a parallel component system.
- Keep all user-visible strings in i18n and retain Base UI semantics/focus behavior.

## Acceptance Criteria

- [ ] At desktop widths, the sidebar and route content touch as sibling panes with a single subtle divider and no detached rounded outer frames.
- [ ] Mobile navigation still opens through the existing sheet/drawer model and remains keyboard accessible.
- [ ] Existing routes keep correct independent scrolling with no body-level horizontal or vertical overflow caused by the shell.
- [ ] Light/dark themes, compact mode, large text/zoom, and reduced motion retain legible hierarchy and focus visibility.
- [ ] Structural regions do not use `Card`, `enterprise-panel`, hover lift, or decorative shadow as their grouping mechanism.
- [ ] True overlays and independent domain objects remain visually distinguishable from structural panes.
- [ ] Relevant source-contract tests are updated and pass.

## Technical Approach

Use CSS Grid/Flex and existing semantic tokens rather than a new dependency. Desktop shell geometry is fixed and responsive in this phase; do not introduce draggable splitters or width persistence. `PageFrame` should express route header/content structure through strips, spacing, and dividers, with density variants only if current routes require them.

## Dependencies

- Parent decision and research in `07-14-refactor-frontend-card-layout`.
- Must land before the page-specific child tasks.

## Working-tree protection

- Preserve the current `ProjectShell` workspace mode and all structured-prototype continuous-layout changes.
- Do not reset, clean, broad-rewrite, or stage unrelated files.
- Do not read or touch `examples/admin-demo/.env`.

## Out of Scope

- Page-specific de-cardification beyond what is necessary to adapt to the new shell.
- Root `/` workbench object-card redesign; it uses a separate shell and is handled in the final consistency sweep.
- Resizable panes, splitter keyboard controls, or persisted pane widths.
- Backend/API changes or a new UI framework.

## Validation

- Targeted shell/source tests.
- `cd frontend && npm run typecheck` and relevant `node --import tsx --test ...` suites.
- Browser verification at 1440px, 900px, and 390px before dependent tasks proceed.
