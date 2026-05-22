# Frontend Interaction Overhaul Design

## Purpose

This design defines the next large frontend upgrade after the visual redesign. The goal is to make the app feel operationally intelligent: users should always know where they are, what the agents are doing, what requires attention, and what action is safest to take next.

## Product Model

The interface should behave like a multi-agent mission control surface.

* The shell answers: "What needs my attention?"
* The command palette answers: "Where can I go or what can I do now?"
* The issue page answers: "What is the workflow state and what is the next best action?"
* The task execution sheet answers: "What happened in this run, and how do I recover or continue?"
* Conductor/live-agent surfaces answer: "Why did the system make this decision?"

## Approach Options

### Option A: Local Polish Only

Upgrade individual buttons, empty states, and tab interactions inside existing pages. This is low risk, but it will not solve cross-page confusion or workflow continuity.

### Option B: Shared Interaction Layer

Create shared interaction primitives and state derivation helpers, then apply them across the shell, command palette, issue page, task sheet, and top-level pages. This is the recommended path because it gives users consistent affordances while keeping backend contracts unchanged.

### Option C: Product Flow Redesign

Redesign routes and workflows around a new end-to-end user journey. This could be powerful later, but it is too risky for this version because the current app already has working routes, live events, and tests.

## Recommended Design

Use Option B: a shared interaction layer.

The first layer is a set of pure interaction-state utilities. These derive next actions, disabled reasons, attention counts, recovery affordances, and command entries from existing data. Keeping these pure makes them testable without browser-heavy tests.

The second layer is shared UI primitives: `ActionStrip`, `AttentionRail`, `CommandActionRow`, `InteractionEmptyState`, `RecoveryPanel`, and a small motion/focus convention for overlays.

The third layer applies those primitives to the real surfaces:

* Workbench shell: persistent attention rail and richer command palette.
* Inbox: action-oriented dashboard with "resume", "review", "inspect failed", and "open live" paths.
* Issue detail: workflow cockpit with next-action strip and explainable disabled actions.
* Task execution sheet: clearer run lifecycle, recovery actions, and process timeline.
* Conductor/live-agent surfaces: less disruptive live dock, clearer activity summary, and action handoff into logs/chat.
* Utility pages: empty/loading/error states with specific recovery actions.

## Interaction Principles

* One primary next action per surface.
* Disabled controls must explain why they are disabled.
* Every async action needs pending, success, and failure feedback.
* Keyboard support is required for overlays and major action flows.
* Live updates should inform without stealing focus.
* Users should be able to resume work from the shell, Inbox, command palette, or issue page.
* Motion should show continuity, not decoration, and must respect reduced motion.

## Key User Flows

### Flow 1: Resume Work

User opens the app and sees an attention rail summarizing awaiting approvals, running agents, failed runs, and recent live updates. They can jump directly to the relevant issue, task run, or approval.

### Flow 2: Act From Command Palette

User presses Command/Ctrl-K, searches an issue, and sees both destinations and actions: open issue, open tasks, open artifacts, review pending approval, rerun failed task, or search knowledge.

### Flow 3: Operate an Issue

Issue detail shows a next-action strip above tabs: current phase, readiness, primary action, disabled reason, and a link to inspect evidence. The user can steer Conductor, approve/reject, rerun failed work, or inspect artifacts without guessing which tab matters.

### Flow 4: Recover From Failure

When a run fails, the task sheet shows what failed, likely recovery actions, and a safe rerun path. The user sees "rerun same executor", "change executor", "open logs", and "send message" in one place.

### Flow 5: Understand Agent Activity

Live agent output stays visible but non-blocking. The user can expand it, switch roles, jump to the full conductor log, or dismiss completed streams without losing page context.

## Component Boundaries

* `frontend/src/features/workbench/interaction/interactionState.ts` derives attention and command/action state.
* `frontend/src/features/workbench/components/AttentionRail.tsx` renders shell-level live and attention items.
* `frontend/src/features/workbench/components/CommandPalette.tsx` becomes action-aware.
* `frontend/src/features/issues/components/IssueActionStrip.tsx` renders the issue cockpit next-action model.
* `frontend/src/features/runs/components/RunRecoveryPanel.tsx` renders failure/retry/review recovery actions.
* `frontend/src/components/ui/interaction-empty-state.tsx` standardizes empty/loading/error states.
* Existing pages consume these primitives without changing backend API contracts.

## Data Flow

Existing API and live-event sources remain unchanged.

* `ExecutionProcessesContext` provides live process status.
* `useWorkbenchStore` provides selected task/issue/process context.
* `getCodexIssues`, `getCodexTasks`, `getPendingApprovals`, and knowledge search provide command and attention candidates.
* Pure derivation helpers convert raw data into typed interaction models.
* Components render those models and call existing API functions.

## Error Handling

* Async actions show local pending state and toast on failure.
* Disabled actions expose a visible reason in tooltip or inline helper text.
* Failed run recovery panel avoids destructive default actions.
* Command palette actions close only after navigation/action succeeds where practical.
* If live data is unavailable, the UI degrades to cached or page-local state with a "refresh" action.

## Accessibility

* Command palette keeps ArrowUp, ArrowDown, Enter, Escape, and focus restore.
* Action strips and rails use real buttons/links and visible focus states.
* Icon-only actions require aria labels.
* Live updates use polite announcements and do not steal focus.
* Motion respects reduced motion settings.

## Testing Strategy

* Unit tests for pure interaction-state derivation.
* Existing frontend test suite for API wiring and i18n guardrails.
* Component-source tests for critical i18n/action wiring where browser tests are not available.
* Manual/browser smoke across main routes.

## Non-Goals

* No backend contract changes.
* No new route architecture.
* No replacement of existing task/conductor stores.
* No broad mobile redesign beyond making interactions responsive and non-overflowing.

