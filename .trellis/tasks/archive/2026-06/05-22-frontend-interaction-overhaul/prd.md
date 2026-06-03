# brainstorm: frontend interaction overhaul

## Goal

Create a major interaction-design upgrade for the frontend so the product feels like an enterprise-grade multi-agent operations console, not just a visually polished dashboard. The next version should make it obvious what is happening, what needs human attention, what the agents are doing, and what the user can safely do next.

## What I already know

* The previous visual overhaul established a modern light/dark hybrid enterprise style.
* The product is a dense multi-agent workbench with Inbox, Projects, Issues, Tasks/Runs, Conductor, Approvals, Artifacts, Knowledge, Settings, and Help.
* Current interaction hotspots include command palette, sidebar navigation, issue workflow tabs, conductor messaging/logs, task execution sheet, approvals, artifacts, and knowledge search.
* The interface already has live events, WebSocket-driven updates, toasts, keyboard command palette, tabs, sheets, dialogs, and status indicators.
* The next improvement should focus on interaction quality rather than another pure styling pass.

## Assumptions (temporary)

* Keep backend API contracts unchanged for this version.
* Keep existing routes and core data flow unchanged.
* Prefer local component state and existing stores/hooks over adding new state libraries.
* Improve perceived continuity and control without requiring a new onboarding product flow.

## Recommended Direction

Use a "mission control" interaction model:

* Global actions and navigation should be commandable from one place.
* Issue pages should expose a clear next-best action and state explanation.
* Agent/conductor activity should be inspectable without forcing page jumps.
* Loading, empty, error, disabled, and success states should explain why and how to recover.
* Keyboard and accessibility support should be treated as first-class enterprise UX.

## Requirements

* Add a coherent interaction layer across the workbench shell and dense pages.
* Upgrade command/navigation flows so users can jump, search, act, and resume faster.
* Make the issue detail page behave like a workflow cockpit with clear next actions.
* Improve task execution UX: process selection, rerun, stop, submit, review, and recovery.
* Make Conductor and live-agent activity easier to understand and less interruptive.
* Improve empty/loading/error states across top-level pages.
* Preserve deep links and avoid breaking existing navigation behavior.
* Maintain keyboard operability for core actions.
* Respect reduced motion and avoid animation that blocks user input.

## Acceptance Criteria

* [x] The command palette supports action-oriented results, not only navigation/search.
* [x] The shell surfaces current human attention items and live agent state without forcing the user to hunt.
* [x] Issue detail has a clear next-action strip explaining what can be done, why disabled actions are disabled, and where to inspect details.
* [x] Conductor/live-agent interactions are accessible from the issue page without visual or workflow interruption.
* [x] Task execution surfaces have visible recovery paths for failure, cancellation, rerun, and review.
* [x] Major empty/loading/error states contain specific guidance and at least one useful action.
* [x] Keyboard users can open the command palette, navigate results, trigger major actions, close overlays, and recover focus.
* [x] Existing route behavior, live updates, and tests remain green.

## Definition of Done

* Implementation plan exists and is specific enough to execute.
* Tests added or updated for new pure interaction utilities and state derivation.
* Lint, typecheck, and frontend tests pass.
* Browser smoke test covers Inbox, Projects, Issue detail, Approvals, Artifacts, Knowledge, Settings, and Help.
* Trellis specs updated if a reusable interaction convention is introduced.

## Out of Scope

* Backend API or database schema changes.
* New agent orchestration behavior.
* Authentication, billing, or permissions redesign.
* Mobile-native app behavior.
* A second visual redesign unrelated to interaction clarity.

## Technical Notes

* Inspected `frontend/src/features/workbench/components/CommandPalette.tsx`.
* Inspected `frontend/src/features/workbench/components/TaskExecutionSheet.tsx`.
* Inspected `frontend/src/features/inbox/InboxDashboard.tsx`.
* Inspected `frontend/src/features/issues/IssueDetailPage.tsx`.
* Inspected `frontend/src/features/issues/components/ConductorChatBar.tsx`.
* Inspected `frontend/src/features/issues/components/FloatingIssueChip.tsx`.
* Relevant existing mechanisms: `useWorkbenchStore`, `ExecutionProcessesContext`, `useBusEventEffect`, `CommandPalette`, `TaskExecutionSheet`, `ConductorLogPanel`, `LiveThinkingDock`.
