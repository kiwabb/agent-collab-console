# Budget visualization UI for per-issue spend

## Goal

Surface the existing per-issue budget governance (spent / budget / remaining,
soft-warn, over-budget) in the frontend so a user can see at a glance how much
of an issue's USD ceiling has been consumed and whether the Conductor is in a
warning / over-budget state. Today the backend *computes and acts on* the budget
(steers model choice, downscales swarm concurrency, emits steering events) but
the user has **no UI window** into any of it.

## Corrected premise (verified 2026-06-03)

This is **NOT** a frontend-only phase. The budget *computation* exists
(`budget_service.compute_issue_budget_status`) but:
1. **No read endpoint** exposes `IssueBudgetStatus` (only called inside the
   conductor loop).
2. `budget_usd` is only a create-time input (`api.py:2672`); persisted on
   `codex_issues.budget_usd` and returned by issue load, but no general issue
   PATCH endpoint can change it (only phase/pin).
3. `budget_warning`/`budget_exceeded` exist only as transient WS events.

→ Minimum backend work: one budget-status **read** endpoint reusing
`compute_issue_budget_status` (so the UI matches the Conductor's gating number).

## Decisions (ADR-lite)

- **(Q1 → A) Dedicated read endpoint** `GET /codex/issues/{id}/budget` serializing
  `compute_issue_budget_status`. Matches the gating number; avoids conflating the
  two cost sources (log-scan `/cost-stats` vs completed-process `spent_usd`).
- **(Q2 → A) Issue-detail only (MVP)**: budget meter in `IssueSideStack` +
  consume this issue's `budget_warning`/`budget_exceeded` events. Issue-list badge
  is a reserved extension; global rollup stays out of scope.
- **(Q5 → A) Hybrid live update**: fetch on mount; instant update from event
  payloads (carry spent/budget/remaining/used_ratio); lightweight poll ONLY while
  the issue is running/active (stop when done/idle) to cover happy-path growth
  (no event is emitted under the soft-warn threshold).
- **(Q4 → A) Read-only**: visualize only; editing `budget_usd` from the UI is a
  separate future phase (would need a new write endpoint + validation).
- **(Q3 → A) Unlimited (`budget_usd <= 0`)**: show accumulated spend + an explicit
  "no ceiling / 无上限" label, **no progress bar** (no misleading full/empty bar).

## Requirements

- Backend: `GET /codex/issues/{id}/budget` returns the serialized
  `IssueBudgetStatus`: `spent_usd, budget_usd, remaining_usd, used_ratio,
  soft_warn, over_budget, soft_warn_ratio, has_ceiling, budget_source`.
- Frontend: a budget meter in `IssueSideStack` showing spent / budget / remaining
  with three visual states: healthy / soft-warn / over-budget (color-coded,
  reusing existing status color tokens).
- Unlimited issue: spent + "no ceiling" label, no bar (per Q3).
- Live: mount fetch + event-driven instant update + running-state-only poll (Q5).
- i18n keys (zh-CN / en-US) for all new copy.

## Acceptance Criteria

- [ ] `GET /codex/issues/{id}/budget` returns correct status for: ceiling issue,
      unlimited issue (`budget_usd <= 0`), and a non-existent issue (404/empty).
- [ ] Endpoint's `spent_usd` matches `compute_issue_budget_status` (completed
      `ExecutionProcess.total_cost_usd`), NOT the `/cost-stats` log-scan number.
- [ ] Issue with a ceiling shows spent/budget/remaining + a bar that color-shifts
      at soft-warn and over-budget thresholds.
- [ ] Unlimited issue shows spend + "no ceiling" label and renders **no** bar.
- [ ] A `budget_warning`/`budget_exceeded` event for the open issue updates the
      meter without a full page reload.
- [ ] Meter stops polling once the issue is done/idle.

## Definition of Done

- Backend endpoint has tests (ceiling / unlimited / missing).
- Frontend has i18n (zh/en) + a unit test for the meter's state/derivation logic.
- Lint / typecheck / build green.
- No new "two conflicting cost numbers" confusion: the budget meter is clearly
  the gating number; the existing raw cost cell stays labeled as-is.

## Technical Approach

1. **Backend endpoint**: add `GET /codex/issues/{id}/budget` in `api.py` near the
   other `/codex/issues/...` routes. Load the issue, call
   `compute_issue_budget_status(codex_store, issue)`, serialize the dataclass
   (add a small `to_dict()` or inline dict). 404 when issue missing.
2. **Frontend API + types**: add `getIssueBudget(issueId)` in `lib/api.ts` and an
   `IssueBudgetStatus` type in `lib/types.ts`.
3. **Meter component**: a `BudgetMeter` (co-located under issues components),
   pure-derivation logic (state from used_ratio/soft_warn/over_budget) unit-tested.
   Render into `IssueSideStack` beside the existing cost cell.
4. **Live update hook**: fetch on mount; subscribe to the global WS
   `/api/ws/events`, filter `budget_warning`/`budget_exceeded` by `issue_id` and
   patch state from payload; poll the endpoint on an interval only while the issue
   status is running/active.

## Out of Scope (explicit)

- Editing `budget_usd` from the UI (Q4 → read-only).
- Issue-list budget badge (Q2 reserved extension) and project-level rollups.
- Changing budget enforcement semantics (stays soft, prompt/event-driven).

## Technical Notes

- `backend/app/application/budget_service.py:38` `IssueBudgetStatus`; `:265`
  `budget_steering_event` (event payload shape).
- `backend/app/interfaces/api.py:1824` `/codex/cost-stats`; `:2670` create input;
  issue routes around `:2761`.
- `backend/app/adapters/async_sqlite_store.py:1255` issue load includes budget_usd.
- `frontend/src/features/issues/components/IssueSideStack.tsx` existing cost cell.
- Global WS envelope `{v, ts, event_id, type, payload}` via `EventBus`.
