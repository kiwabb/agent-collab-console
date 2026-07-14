# Issue and prototype layout consistency

## Goal

Complete the continuous-tool layout for issue detail and structured prototypes: make contextual information one inspector, flatten remaining structural prototype wrappers, and harden focus and responsive behavior without disturbing the active prototype deletion work.

## Requirements

### Issue detail

- Replace the stack of policy, criteria, Git, telemetry, activity, and similar-issue panels with one contextual inspector pane.
- Organize inspector content through compact headers, divider-separated/collapsible sections, and one clear scroll owner.
- Replace nested telemetry cells with aligned rows or a compact summary treatment.
- Preserve independent failure alerts, dispatch/diff/artifact boundaries, dialogs, and independently openable similar-issue records.

### Structured prototype

- Preserve the current uncommitted workspace `ProjectShell`, continuous three-region Studio, row-based Page Rail/Palette, restrained preview boundary, mobile pane switcher, and Generation outer-surface changes.
- Remove the remaining structural outer `enterprise-card` from Flow mode.
- Keep flow page nodes bounded when they represent graph objects, but render rules/relationships as a divided list rather than nested cards.
- Review Evidence/AI/Generation containment by semantics; retain independently addressable evidence, runtime/checkpoint states, errors, and embedded previews.
- Replace ad-hoc tab semantics with the existing Base UI Tabs model or complete the tablist/tab/panel relationships and keyboard behavior.
- Ensure local controls have visible `focus-visible` treatment consistent with shared primitives.
- Move the three-pane activation threshold to a practical width or use an intermediate pane mode so the 240 + 440 + 300 tracks cannot overflow between 1024px and the actual fit threshold.

## Acceptance Criteria

- [ ] Issue contextual information is one inspector pane with sections, not five peer cards.
- [ ] Structured prototype Design/Flow keeps stable toolbar/rail/canvas/inspector geometry across mode changes.
- [ ] Flow has no structural outer enterprise card; graph nodes remain distinguishable and relationship rules scan as rows.
- [ ] The current prototype deletion controls, storage/API behavior, i18n, and tests are unchanged except for necessary layout adaptation.
- [ ] Tabs, pane selectors, drag/drop handles, icon controls, errors, and live statuses remain keyboard accessible and correctly labelled.
- [ ] No three-pane overflow occurs at intermediate desktop widths; 900px and 390px pane switching remains usable and state-safe.

## Technical Approach

Use one bordered inspector pane with section dividers and existing semantic tokens. Keep mode content within a stable center region. Prefer Base UI Tabs/Sheet where their keep-mounted and keyboard semantics match existing state requirements. Do not introduce a resizable-panel dependency.

## Dependencies

- Blocked by the global foundation and the project-shell work.
- Runs after the two parallel page-layout workstreams to minimize shell conflicts.

## Working-tree protection

The structured-prototype files contain intertwined continuous-layout and prototype-deletion changes across frontend, backend, API, storage, i18n, and tests. Make surgical frontend layout edits only; do not reset or rewrite the deletion vertical slice.

## Out of Scope

- Prototype generation/deletion API or persistence changes.
- New design/flow features, multi-file sandboxing, or collaboration behavior.
- Draggable/persisted pane widths.

## Validation

- Existing project shell and structured-prototype API/service/source tests.
- Typecheck and targeted node:test suites.
- Browser walkthrough of issue detail plus prototype Design, Flow, AI/Properties, Generation, delete control, and mobile pane switching.
