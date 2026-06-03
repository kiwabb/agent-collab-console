# Complete frontend internationalization

## Goal

Replace the remaining user-facing hard-coded frontend copy (zh-CN literals
embedded in JSX) with i18n keys routed through `useI18n().t()` and the
`frontend/src/lib/i18n.ts` dictionaries, and add en-US translations for any
new keys so the toggle in Settings actually flips the copy.

## Scope (post audit, 2026-06-03)

A fresh scan across `frontend/src/**/*.{ts,tsx}` found **13 hard-coded
zh-CN literals** across 3 files after the 2026-05-22 batch wired Settings,
ProjectConductor, and AgentCatalog:

- `frontend/src/features/workflow/AgentDagNode.tsx` — 6 role tagline literals
  (编排器 / 需求分解 / 系统设计 / 代码实现 / 前端实现 / 后端实现).
- `frontend/src/features/issues/components/TasksOverviewBar.tsx` — 4 role
  descriptions (需求分解 / 系统设计 / 代码实现 / 验证). Conductor kept its
  English "auto-plan" label intentionally.
- `frontend/src/features/issues/components/IssueActivityTimelineHorizontal.tsx`
  — 2 literals (活动 header, "X 个事件" count).

## Out of scope (handled elsewhere or not yet needed)

- Editing `budget_usd` from the UI (a separate future phase).
- A general zh-CN→i18n sweep of *internal* strings (logs, console output,
  error toasts) — those are developer-facing only.
- en-US copy review of *existing* (pre-2026-06-03) keys — covered by the
  existing i18n coverage test in `frontend/tests/`.

## Approach

For each touched file, add a `<prefix>.<section>.<key>` namespace to the
zh-CN + en-US dictionaries, wire `useI18n()` if absent, and replace the
literal with `t("key")` (or `t("key", { param })` for interpolation). Reuse
the existing `issue.stage.summary.*` keys for role descriptions (they already
exist for both locales); only add new keys for the genuinely missing entries
(`role.conductor`, `role.engineer_frontend`, `role.engineer_backend`,
`issue.activity.timelineTitle`, `issue.activity.timelineEventCount`).

## Acceptance Criteria

- [x] Frontend re-scan finds **0** hard-coded user-visible zh-CN literals
      (excluding `i18n.ts`, `I18nProvider.tsx`, and tests).
- [x] Each new key is registered in **both** zh-CN and en-US dictionaries.
- [x] `npm test` green, `npm run lint` clean, `npm run build` green.
- [x] No new "only-zh" or "only-en" key drift (validated by the i18n
      coverage test in `frontend/tests/`).
