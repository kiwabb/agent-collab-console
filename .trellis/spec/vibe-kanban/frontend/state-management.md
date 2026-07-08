# State Management

> How state is managed in the vibe-kanban frontend package.

---

## Overview

The project does **not** use Redux, Zustand, Jotai, or any other external
state library. State lives in three places, in this priority order:

1. **Local component state** (`useState`, `useReducer`) — the default.
2. **React context** — a small number of app-wide providers
   (`I18nProvider`, `ThemeProvider`, `PreferencesProvider`,
   `ExecutionProcessesContext`). New providers are an exception, not the
   rule.
3. **Server state** — re-fetched on mount, kept in local state, patched
   by `useBusEventEffect` for live updates. No client cache.

A component reaches for `useContext` only when a value is genuinely
needed by siblings in different subtrees (e.g. workspace id, theme,
live event stream). Anything else stays in local state and travels
through props or composition.

---

## State Categories

| Category | Where it lives | Examples |
|----------|---------------|----------|
| **Component UI** | `useState` inside the component | form values, accordion open/closed, hover state |
| **Cross-component feature state** | React context provider in `providers/` | workspace id, current user prefs, live event stream |
| **Server / network data** | Local `useState`, refreshed on mount and on relevant WS events | issue detail, task list, cost stats, budget snapshot |
| **URL state** | `useSearchParams` / `usePathname` from `next/navigation` | active tab, command-palette query, project sort |
| **Persistence** | `localStorage` via `usePreferencesProvider` (theme, language) | user-preference toggles |
| **Global short-lived** | `EventBus` (server) + `useBusEventEffect` (client) | per-issue cost growth, budget warning, task status |

Rule of thumb: if only one component reads it, it's local. If two
siblings read it, lift to a parent. If two features in different trees
read it, context. If two browser tabs need to see the same value, the
server.

---

## When to Use Global State

A new piece of state belongs in a **React context** only if all of the
following are true:

- It is read by components in **two or more unrelated subtrees** (not
  just parent → child).
- It is **inherently app-wide** (theme, locale, workspace id, live
  event stream). Per-feature concerns stay in the feature.
- It is **not** a snapshot of server data — server data is re-fetched
  on mount and patched via `useBusEventEffect`, not stored in a
  long-lived context.

A new context provider requires a corresponding hook in `hooks/`
(`useXxx`) that re-throws if used outside the provider — this is the
mechanism that keeps "where do I read this from?" obvious.

**Do not** introduce Zustand / Redux / Jotai for the convenience of one
component. The existing tree is the source of truth.

---

## Server State

Server data follows a uniform pattern:

1. **Fetch on mount** (and on `reloadKey` change) via a small async
   helper. Multiple fetches in a panel are combined in a single
   `Promise.all` so the page does not serialize them.
2. **Cache the response in local `useState`**. Refresh by re-running
   the same fetch.
3. **Patch from the live event bus** using `useBusEventEffect`:
   - match by `issueId` / `taskId` / `type` via `busEventMatchers`
   - throttle to `>= 600ms` when the same panel re-renders many cards
     in a burst (the standard case is the conductor settling 3 stages
     in 200ms)
   - cleanup is mandatory: the hook itself handles timer cleanup, but
     callers must not add their own long-lived subscriptions on top
4. **Polling** is reserved for the active-state-only cases (e.g. the
   budget meter polls every 30s while the issue is running, and stops
   the moment the issue is done/idle). The default is **no polling** —
   if the WS event stream can keep a value current, do not add a poll.

A typed return is mandatory: `Promise<MyType | null>` where `null` is
the failure case. Callers branch on `null`, never on thrown errors.

---

## Common Mistakes

- **Adding `useEffect` to "sync" two pieces of state.** If component A
  sets state and component B re-derives it from A's state in an effect,
  the derivation should be a `useMemo` (or a plain inline expression),
  not an effect. The "derived in render" pattern is the correct one.
- **Storing a snapshot of server data in a context provider.** The
  page that owns the fetch owns the state. If two pages need the same
  snapshot, they each fetch it (the request is deduped at the
  `dedupedFetch` layer in `lib/api.ts`).
- **Mutating state in place.** `useState` is reference-comparison; if
  you push into an array, React will not re-render. Always return a
  new array/object.
- **Forgetting event-bus cleanup.** `useBusEventEffect` handles
  internal timer cleanup, but if you add a `useEffect` with
  `addEventListener` outside it, you must return a cleanup that
  removes the listener. Stale listeners leak memory and double-fire.
- **Polling a value the WS already streams.** If the server emits an
  event for a value change, do not also poll it. The poll is for
  values whose growth is silent below a threshold (budget spend before
  soft-warn, for example) — not a substitute for the event stream.

---

### Server reload failures preserve stale data

When a component already has server data on screen, a refresh/reload failure must
not clear that data unless the user explicitly requested a destructive reset.
Keep the stale data, set an error state, and log with context.

```tsx
// Wrong — transient reload error wipes the user's view.
.catch(() => {
  setProcessLogs([]);
  setProcessMessages([]);
});

// Correct — stale data remains visible and the UI can show the failure.
.catch((err) => {
  const msg = err instanceof Error ? err.message : "Failed to load process output";
  console.error("workbench process output reload failed:", err);
  setError(msg);
});
```

This applies to command palette/project sync loads too: `.catch(() => {})` is not
acceptable for primary navigation or visible panels. Use a local `loadError` /
`error` state and render a small visible message.

---

## Scenario: Active task feedback on routes without a live-event provider

### 1. Scope / Trigger

- Trigger: adding task-start buttons or loading/toast state to routes
  that may be mounted outside `ExecutionProcessesProvider`.
- Example routes: standalone project settings pages such as
  `/projects`, where the page is not always wrapped in
  `WorkbenchShell`.

### 2. Signatures

- Optional context:
  `const ctx = useContext(ExecutionProcessesContext)`.
- Task lookup fallback:
  `getCodexTask(taskId: string) -> Promise<CodexTask>`.
- Task status events:
  `BusTaskStatusEvent` includes `task_id`, `project_id`, `status`,
  and may include `role` / `task_kind`.

### 3. Contracts

- Components may use `useExecutionProcessesContext()` only when the
  route is guaranteed to be inside `ExecutionProcessesProvider`.
- Components that can render outside the provider must use
  `useContext(ExecutionProcessesContext)` and handle `null`.
- If a user action starts a task and the route lacks reliable live
  events, store the returned `task_id` and poll that exact task until a
  terminal status.
- Terminal handling must be task-specific. Do not clear a button's
  loading state only because another task in the same project finished.
- De-duplicate terminal handling by `task_id` when both WS events and
  polling can arrive.

### 4. Validation & Error Matrix

- No provider + `useExecutionProcessesContext()` -> route throws at
  render time. Use optional context instead.
- Task polling reaches `done` / `completed` -> clear loading, refresh
  server state, show success only if the user action expects visible
  feedback.
- Task polling reaches `failed` / `cancelled` / `killed` -> clear
  loading, refresh, show failure feedback.
- Polling exceeds its bounded window -> clear loading and show visible
  feedback; never silently stop. For long-running background tasks that may
  still be healthy (for example Operations Engineer startup-script
  generation), the feedback must say the task is still running in the
  background rather than reporting failure.
- Duplicate WS + poll terminal notifications for the same task id ->
  handle once.

### 5. Good/Base/Bad Cases

- Good: a `/projects` button starts `task_id=abc`, records `abc`, polls
  `getCodexTask("abc")`, and ignores terminal events for unrelated
  tasks in the same project.
- Base: a Workbench route inside the provider receives `task_status`
  through `lastEvent` and never needs the polling fallback.
- Bad: using `useExecutionProcessesContext()` in a standalone route and
  crashing with "must be used within ExecutionProcessesProvider".
- Bad: clearing loading when any task with the same `project_id`
  finishes.
- Bad: stopping a polling timeout without a toast or visible failure
  state.

### 6. Tests Required

- Component test: standalone route without provider renders and the
  task-start button does not throw.
- Component test: terminal status for the tracked `task_id` clears
  loading; terminal status for a different task id does not.
- Component test: duplicate WS/poll terminal notifications produce one
  toast.
- Component test: polling timeout clears loading and shows failure
  feedback.

### 7. Wrong vs Correct

Wrong:

```tsx
const { lastEvent } = useExecutionProcessesContext();
if (lastEvent?.project_id === projectId && lastEvent.status === "done") {
  setLoading(false);
}
```

Correct:

```tsx
const ctx = useContext(ExecutionProcessesContext);
const lastEvent = ctx?.lastEvent ?? null;
const [taskId, setTaskId] = useState<string | null>(null);
const handledIdsRef = useRef(new Set<string>());

if (
  lastEvent?.type === "task_status" &&
  lastEvent.task_id === taskId &&
  !handledIdsRef.current.has(lastEvent.task_id)
) {
  handledIdsRef.current.add(lastEvent.task_id);
  setLoading(false);
}
```

---

## Scenario: Project Script Task Tracking

### 1. Scope / Trigger

- Trigger: changing the Projects page Operations Engineer startup-script button or `startProjectScriptTask` handling.

### 2. Signatures

- API call: `startProjectScriptTask(projectId, body) -> ProjectScriptTaskResponse`.
- State fields: `suggestingProjectId`, `suggestingTaskId`, `handledScriptTaskIdsRef`.

### 3. Contracts

- After the API returns, always store `task.task_id` in `suggestingTaskId`, regardless of whether `task.reused` is true or false.
- Before tracking the returned task id, delete it from `handledScriptTaskIdsRef` so a previous terminal notification for the same reused task cannot suppress the current run's UI feedback.
- Terminal handling must match `lastEvent.task_id === suggestingTaskId`; project-id fallback is not allowed for script task completion.
- The current Projects page implementation tracks one script-generation task at
  a time. While `suggestingProjectId` is set, starting another project's script
  generation is refused instead of overwriting `suggestingTaskId`.

### 4. Validation & Error Matrix

- Fresh task -> set `suggestingTaskId`, poll exact task, and handle matching websocket terminal event once.
- Reused active task -> set the reused `task_id`, clear prior handled marker, and show already-running copy.
- Terminal event for another task in the same project -> ignored.
- Duplicate websocket + poll terminal event for same task -> handled once through `handledScriptTaskIdsRef`.
- Another project is selected while a script task is already tracked -> the
  generate button remains in the generating state and `handleGenerateOperationsScripts`
  returns without starting or tracking a second task.
- Polling exceeds `SCRIPT_TASK_POLL_LIMIT_MS` while the task is still
  non-terminal or temporarily unavailable -> clear loading, refresh project
  data, and show `projects.scriptSuggestionStillRunning`; do not show
  `projects.scriptSuggestionFailed` unless a terminal failed/cancelled/killed
  status is observed.

> Project script task terminal-status addendum: frontend script-task tracking
> treats `done` / `completed` as successful terminal statuses and `failed`,
> `error`, `cancelled`, `canceled`, and `killed` as failed terminal statuses.
> Websocket terminal handling must first match the exact tracked `task_id`,
> then narrow by `project_id`, `task_kind="project_script_suggestion"`, and
> `role="operations_engineer"`; project-id matching is a narrowing guard, not a
> fallback completion rule.

### 5. Good/Base/Bad Cases

- Good: user clicks button, API returns reused task `abc`, frontend tracks `abc` and ignores project task `xyz` finishing.
- Base: API returns new task `def`, frontend tracks `def` and polls `getCodexTask("def")`.
- Bad: clearing loading when any `project_id` task finishes before `task_id` is known.
- Bad: leaving `abc` in `handledScriptTaskIdsRef`, causing the reused task's terminal update to be ignored.
- Bad: overwriting `suggestingTaskId` with project B while project A's
  Operations Engineer task is still running.
- Bad: treating the bounded polling window as proof that the Operations
  Engineer failed; the backend may still be running and will return
  `reused=true` on the next click.

### 6. Tests Required

- Source/component test: `setSuggestingTaskId(task.task_id)` is wired after the API response.
- Source/component test: `handledScriptTaskIdsRef.current.delete(task.task_id)` occurs before terminal tracking.
- Source/component test: no `project_id` terminal fallback remains in script task terminal handling.
- Source/component test: `handleGenerateOperationsScripts` returns when any
  `suggestingProjectId` is already active, not only when it matches the current
  project.
- Source/component test: script-task poll timeout uses
  `projects.scriptSuggestionStillRunning` and does not call
  `projects.scriptSuggestionFailed`.

### 7. Wrong vs Correct

Wrong:

```tsx
if (lastEvent.project_id === suggestingProjectId) setSuggestingProjectId(null);
```

Correct:

```tsx
handledScriptTaskIdsRef.current.delete(task.task_id);
setSuggestingTaskId(task.task_id);
if (lastEvent.task_id !== suggestingTaskId) return;
```
