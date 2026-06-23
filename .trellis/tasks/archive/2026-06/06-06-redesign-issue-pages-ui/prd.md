# Redesign Issue Pages UI

## Goal

Redesign the issue-related UI so the workspace issue list and issue detail page feel like a dense, professional operations console for coordinating agents, rather than a decorative/card-heavy surface. The redesign should make status, current agent activity, artifacts, diff state, and follow-up actions easier to scan and act on.

## What I Already Know

* The user asked to redesign the issue page UI.
* The in-app browser is open on workspace `27f61ed5-36a3-4f16-80eb-8de3cb30feed`.
* The current workspace issue list is implemented by `WorkspaceConsole`, `WorkspaceConsoleHeader`, `IssueListPanel`, and `IssueRow`.
* The current issue detail page is implemented by `IssueDetailPage` plus status, timeline, artifacts, diff, mesh, git, and side-stack components.
* The frontend stack is Next.js 14 App Router, TypeScript strict mode, Tailwind v4, `@base-ui/react`, lucide-react icons, and `node:test`.
* All visible strings must use `useI18n()` with zh-CN and en-US parity.
* Pure state derivation rules should live next to their component and have unit tests.
* Current code already has tests locking the workspace console and issue command-center layout contracts.
* Current UI uses large rounded panels, gradient/glow effects, and card-heavy rows; this conflicts with the desired operational-tool direction.
* Browser observation of the workspace list shows four issue rows with filters/sort controls and a working status distribution, but the main surface still reads like stacked cards rather than a compact operational queue.
* Browser observation of issue detail `c13b189c-4da4-4627-a661-181b01d4443b` shows the feature set is strong: fixed status/control header, four-tab workbench, right-side acceptance/telemetry/similar-issues rail, and docked chat bar.
* The issue detail pain is mostly hierarchy and density: the header is visually loud, the status telemetry is oversized, right rail cards are highly decorative, and long QA JSON summaries overwhelm the timeline.

## Assumptions

* "需求页面" covers both the workspace issue list surface and `/issues/[id]` detail surface, because they are the primary issue discovery and issue execution pages.
* The redesign should preserve existing behavior and data flow: filters, sorting, opening issues, deletion confirmation, tab deep links, Conductor pause/resume/steer/reset, dispatch drawer, bottom chat bar, artifacts, diff, mesh, git controls, and side insights.
* This is a visual and interaction redesign, not a backend behavior change.

## Requirements

* Make the issue list scan-first: clear columns, compact status/agent/progress metadata, stable row dimensions, and obvious primary action.
* Make issue detail feel like a command center: compact fixed header, clear conductor state, workbench tabs, right-side insights/actions, and docked chat.
* Reduce decorative chrome: avoid nested cards, oversized radius, ambient orbs/glows, heavy gradients, and marketing-like composition.
* Use existing semantic tokens and shared UI primitives where possible.
* Preserve accessibility: semantic buttons/links, keyboard operation, focus-visible states, status text in addition to color, and no text overlap at mobile widths.
* Preserve route behavior, including `/issues/[id]?tab=diff|artifacts|mesh` deep links.
* Keep changes scoped to the issue-list/detail UI and related tests/i18n.
* Implement Approach B: Dense Operations Console.

## Acceptance Criteria

* [ ] Workspace issue list visually reads as a dense operations table/list at desktop widths.
* [ ] Workspace issue list remains usable on mobile without horizontal overflow or clipped labels.
* [ ] Issue detail header/status area is compact, less decorative, and keeps key actions visible.
* [ ] Workbench tabs remain four primary views: timeline, artifacts, diff, mesh.
* [ ] Right-side issue insights remain available on desktop and degrade sensibly on smaller viewports.
* [ ] Docked chat remains available and does not cover scrollable content.
* [ ] Existing issue routing and tab deep links still work.
* [ ] Targeted frontend tests pass.
* [ ] Browser verification covers workspace list and at least one issue detail page at desktop and mobile widths.

## Definition of Done

* User approves the design direction before implementation.
* Tests added or updated for any new derivation or UI contract rules.
* `cd frontend && npm test` passes, or any unrelated failures are documented.
* `cd frontend && npm run lint` and `cd frontend && npm run build` pass, or failures are documented with cause.
* Browser screenshots/DOM checks prove the redesigned pages render correctly without overlap.

## Verification Notes

* 2026-06-09: Browser runtime verification for the intelligent scheduling animation slice used a temporary mock backend on `localhost:9000` and `frontend` dev server on `localhost:4000`, then opened `/issues/mock-scheduling-issue`.
* The issue detail page rendered without the Next.js runtime error overlay. DOM checks found an active Conductor strip with `border-brand/35 bg-brand-muted/10`, `animate-shimmer-sweep = 1`, and `animate-orbit = 1`.
* The timeline rendered three running scheduling rows (`dispatch_batch`, tool call, and running engineer task). Each row had scheduling active chrome, `animate-shimmer-sweep = 1`, and `animate-orbit = 1`.
* A mock `conductor_turn_delta` WebSocket event rendered the live thinking card with the streamed Conductor text and `animate-shimmer-sweep = 1`.
* Follow-up fix: batch-expanded tasks now choose empty-summary copy from their actual timeline status, so a running engineer row says it is running instead of reusing the finished-task summary.
* Screenshot artifact from the local verification run: `/tmp/conductor-animation-verification-live.png`.
* 2026-06-09 current-main recheck: Browser verification on `/issues/mock-scheduling-issue` rendered without the Next.js runtime error overlay after typed mock responses included `IssueDiffResult.diff` and `CodexCostStats.pricing`.
* Current-main DOM checks found the active Conductor strip with `border-brand/35 bg-brand-muted/10`, `animate-shimmer-sweep = 1`, and `animate-orbit = 1`; three scheduling rows (`dispatch_batch`, running engineer task, and running tool call) each had `border-brand/40 bg-brand-muted/10`, `animate-shimmer-sweep = 1`, and `animate-orbit = 1`.
* The mock global WebSocket stream delivered a `conductor_turn_delta`; the live thinking card rendered "Conductor is actively comparing dispatch paths and balancing agent load." with a shimmer scan line. Screenshot artifact: `/tmp/conductor-animation-current-main.png`.

## Out of Scope

* Backend orchestration behavior changes.
* New issue lifecycle states.
* Replacing the app-wide design system or theme tokens.
* Rebuilding unrelated pages such as Inbox, Approvals, Artifacts Hub, Agents, or Settings.
* Adding a new UI dependency.

## Open Questions

* None currently blocking. User confirmed Approach B with `b`.

## Decision (ADR-lite)

**Context**: The issue pages need to support repeated operational scanning and intervention. Browser inspection showed the existing functionality is strong, but the visual treatment is too decorative and card-heavy for an agent orchestration console.

**Decision**: Use Approach B, Dense Operations Console. Preserve the current information architecture and data flow, but flatten the chrome, tighten spacing, reduce oversized radii/glows, and make issue rows and issue detail sections scan-first.

**Consequences**: This keeps implementation risk lower than a split-pane redesign while still changing the product feel materially. It requires careful responsive browser checks because denser surfaces can fail on small screens if columns and labels are not constrained.

## Feasible Approaches

### Approach A: Conservative Polish

Keep the current page structure and reduce the most distracting chrome: smaller radii, fewer glows, calmer shadows, denser row spacing, and slightly cleaner tabs.

* Pros: Lowest implementation risk; preserves most JSX structure.
* Cons: Improves polish but does not fully change the product feel; the issue list may still read as card-heavy.

### Approach B: Dense Operations Console (Recommended)

Reframe the issue list as a scan-first queue and the detail page as a compact command center. Use table-like rows, tighter status chips, fixed metric/action bands, flatter surfaces, and restrained enterprise-panel styling. Preserve the existing detail-page data flow and four-tab workbench.

* Pros: Best match for an agent orchestration tool; improves scan speed without rewriting behavior.
* Cons: Touches several UI files and tests; needs careful responsive verification.

### Approach C: Split-Pane Master/Detail

Turn the workspace issue page into a split view: left queue, right live preview/detail for the selected issue, with `/issues/[id]` remaining a deeper full-page command center.

* Pros: Powerful for triage-heavy workflows; fewer page navigations.
* Cons: Larger interaction change; more state and routing complexity; higher chance of scope creep.

## Technical Notes

* Relevant spec files:
  * `.trellis/spec/ccgui/frontend/index.md`
  * `.trellis/spec/ccgui/frontend/component-guidelines.md`
  * `.trellis/spec/ccgui/frontend/quality-guidelines.md`
  * `.trellis/spec/ccgui/frontend/type-safety.md`
* Current page files:
  * `frontend/src/features/workspaces/WorkspaceConsole.tsx`
  * `frontend/src/features/workspaces/WorkspaceConsoleHeader.tsx`
  * `frontend/src/features/workspaces/IssueListPanel.tsx`
  * `frontend/src/features/workspaces/IssueRow.tsx`
  * `frontend/src/features/issues/IssueDetailPage.tsx`
  * `frontend/src/features/issues/components/StatusStrip.tsx`
  * `frontend/src/features/issues/components/GitInfoCard.tsx`
  * `frontend/src/features/issues/components/IssueSideStack.tsx`
* Existing tests to preserve/update:
  * `frontend/tests/workspaceConsoleRedesign.test.ts`
  * `frontend/tests/workspaceConsoleState.test.ts`
  * `frontend/tests/issueCommandCenter.test.ts`
  * `frontend/tests/issueNavigationCopy.test.ts`
  * `frontend/tests/workspaceI18n.test.ts`
