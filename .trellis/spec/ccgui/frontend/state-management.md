# State Management

> How state is managed in the ccgui frontend package.

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

- Trigger: changing the Startup Config Operations Engineer action, `useProjectStartupConfig`, or `startProjectScriptTask` handling.

### 2. Signatures

- API call: `startProjectScriptTask(projectId, body) -> ProjectScriptTaskResponse`.
- Recovery query: `getProjectTasks(projectId) -> CodexTask[]`.
- State fields: `analysisTaskId`, `analysisStarting`, `analysisFeedback`.

### 3. Contracts

- Startup Config owns the analysis action. `/projects` only links to that page and must not start a background analysis task.
- After the API returns, store `response.task_id` in `analysisTaskId`, regardless of `response.reused`.
- Poll only `getCodexTask(analysisTaskId)` until that exact task reaches a terminal status.
- On page load, query project tasks, select the newest `project_script_suggestion` from `operations_engineer`, and resume polling when it is non-terminal.
- Preserve the last project, task result, environment variables, and run status when a refresh fails; show a visible `loadError` instead of clearing data.
- A bounded poll timeout means the task is still running in the background, not that it failed. Clear the local busy state and show recovery copy so a later reload/click can reuse the task.

### 4. Validation & Error Matrix

- Fresh task -> set `analysisTaskId`, fetch/poll that exact task, and disable duplicate starts.
- Reused active task -> track the returned task id and show already-running copy.
- Reload during an active task -> select the newest matching project task and resume polling.
- `done` / `completed` -> refresh scripts, variables, task result, and run status in place.
- `failed` / `error` / `cancelled` / `canceled` / `killed` -> keep the prior visible configuration and show a retry path.
- Polling exceeds `ANALYSIS_POLL_LIMIT_MS` -> show `analysisStillRunning`; do not report terminal failure.
- A transient task/status request failure -> keep stale data, log with context, and expose visible retry feedback.

> Project script task terminal status is centralized in
> `describeScriptTaskTerminalStatus`; do not create a page-local status list.

### 5. Good/Base/Bad Cases

- Good: Startup Config reloads, discovers active task `abc`, and resumes `getCodexTask("abc")` polling.
- Base: a fresh response returns task `def`; the page tracks `def` and refreshes all startup data on completion.
- Bad: leaving the action on `/projects` while environment results are only visible under `/projects/:id/env`.
- Bad: interpreting any terminal task from the same project as completion of the tracked analysis.
- Bad: clearing previously loaded scripts or variables when one refresh request fails.

### 6. Tests Required

- Source contract: `/projects` links to Startup Config and does not import `startProjectScriptTask`.
- Source contract: `useProjectStartupConfig` stores `response.task_id` and polls `getCodexTask(analysisTaskId)`.
- Unit tests: latest matching project task selection ignores unrelated roles/task kinds and orders by update time.
- Unit tests: malformed task result JSON degrades to an empty summary without throwing.
- Browser check: reload reconstructs the latest completed summary and active tasks recover their busy state.

### 7. Wrong vs Correct

Wrong:

```tsx
// Fragmented ownership: the action starts outside the page that shows its result.
<Button onClick={startAnalysis}>Analyze</Button>; // on /projects
```

Correct:

```tsx
const response = await startProjectScriptTask(projectId, body);
setAnalysisTaskId(response.task_id);
const task = await getCodexTask(response.task_id);
setLatestTask(task);
```

---

## Scenario: Project Run Lifecycle Feedback

### 1. Scope / Trigger

- Trigger: changing Startup Config run controls, project process/service polling,
  or the rendering of startup results and logs.
- Process ownership and HTTP reachability are independent state dimensions. A
  process can be console-managed before its port is ready, and a reachable
  service can have been started outside the console.

### 2. Signatures

- Start: `startProjectRun(projectId) -> ProjectRunStatus | ProjectRunStartError`.
- Status: `getProjectRunStatus(projectId) -> ProjectRunStatus`.
- Incremental logs: `getProjectRunLogs(projectId, after) -> ProjectRunLogsResponse`.
- Terminal derivation: `deriveProjectRunOutcome(status) -> "idle" | "running" | "completed" | "failed" | "stopped"`.
- Service derivation:
  `deriveProjectServiceState(status) -> ProjectRunServiceState`.
- Presentation derivation:
  `deriveProjectRunPresentation(status, startupState) -> ProjectRunPresentation`.

### 3. Contracts

- `ProjectRunStatus.running` means the console owns a live child process. Only
  this field grants a Stop action.
- `ProjectRunStatus.service.state` is explicit probe evidence:
  `reachable`, `unreachable`, `not_configured`, `invalid_url`, or `unknown`.
  Never infer reachability from process creation.
- `running=true` plus `service.state=reachable` is managed and ready;
  `running=true` plus `unreachable` is managed but still starting;
  `running=false` plus `reachable` is an external/otherwise unowned service.
- An external reachable service exposes Open but never Stop, and blocks the
  normal Start action.
- A long-running process or reachable service completes the **Run** step. The
  step indicator uses `complete`; reserve a spinner for an unresolved start
  action, not a steady-state server.
- On page load, fetch both status and logs so a previous terminal result remains visible after reload.
- While `running` is true, poll incremental logs every 2 seconds, append from
  the last sequence number, and patch process `running` / `exit_code` from the
  log response. Independently poll status every 5 seconds while a configured
  service is `reachable` or `unreachable`, whether managed or external, so a
  terminal/IDE-started service can appear or disappear without a reload.
- Re-fetch status after analysis completion and start/stop actions.
- `exit_code > 0` is a failed startup, `exit_code === 0` is a normally completed command, and a negative exit code is a stopped process.
- A failed run must keep its logs, show the exit code and an actionable failure line, and offer a retry action.
- A transient status/log error preserves the last rendered status and log
  buffer, records a visible load error, and allows the next poll to recover it.
- Track status-probe and log-poll errors independently. A successful status
  request clears only the status error; a successful log request clears only
  the log error. Faster log polling must not hide a persistent probe failure,
  and a recovered log request must not leave its own stale error visible.

### 4. Validation & Error Matrix

- `running=false`, `service=reachable` -> render external-service feedback,
  Open, and no Stop/Start action.
- `running=true`, `service=unreachable` -> render starting/not-ready feedback
  and retain Stop ownership.
- `service=invalid_url` or `unknown` -> render a clear unknown/unsupported state;
  do not claim offline or ready.
- `service=not_configured` -> retain the process-only lifecycle and allow Start
  when the rest of the startup configuration is ready.
- Start refusal (`service_already_reachable`) -> refresh status, show
  informational feedback with the canonical URL, and do not enter a managed
  running state.
- Other start refusals (`already_running`, `no_run_command`, `env_incomplete`,
  `refused`) -> map the typed reason to visible feedback; do not enter a false
  running state.
- Start response with `running: true` -> reset the prior log cursor, show running state, and poll logs.
- Derived process outcome `running` or service state `reachable` ->
  `run="complete"`; keep `canStart=false` and render the ownership-appropriate
  controls.
- Log response with `running: false`, `exit_code > 0` -> stop polling and render failed state with retained logs.
- Log response with `running: false`, `exit_code === 0` -> stop polling and render completed state.
- Log response with negative `exit_code` -> render stopped state instead of startup failure.
- Transient polling error -> preserve the current status/log buffer, log with context, and expose a visible error; retry on the next active poll or explicit refresh.

### 5. Good/Base/Bad Cases

- Good: a server started in a terminal responds at the analyzed URL; Startup
  Config reports it as externally reachable and offers Open without Stop.
- Good: Docker Compose starts, then exits `1`; Startup Config changes from running to failed, shows exit code `1`, displays the registry timeout line, and enables “Start again”.
- Base: a managed dev process is live before its port responds; the UI says
  the service is starting while logs append and Stop remains available.
- Base: no analyzed access URL produces `not_configured`; existing managed
  process behavior remains available.
- Bad: mapping every `running: true` response to `run="active"`, which leaves the Run step spinning forever after a server has started.
- Base: a command exits `0`; the UI reports normal completion and retains its output.
- Bad: showing “Project started” immediately after `POST /run/start` returns 200.
- Bad: showing Stop for `running=false`, `service=reachable`; the console does
  not own that process.
- Bad: polling only status while hiding stdout/stderr, leaving the user unable to diagnose why the port is unavailable.
- Bad: clearing logs when a terminal or transient error arrives.

### 6. Tests Required

- Unit: `deriveProjectRunOutcome` maps running, positive exit, zero exit, negative exit, and no-run states.
- Unit: presentation derivation covers managed/reachable, managed/unreachable,
  external reachable, offline, and unknown states.
- Unit: a running process or reachable service maps the Run step to `complete`,
  while the start action remains unavailable.
- Unit: failure-line selection prefers a line containing `error`, `failed`, or `timeout` over trailing non-actionable output.
- Source contract: Startup Config imports `getProjectRunLogs`, tracks the last
  sequence, polls reachable and unreachable services, renders a failure detail,
  and exposes a log panel.
- Source contract: external reachability renders Open and cannot reach the Stop
  branch.
- Unit: source-keyed refresh errors prove that clearing `logs` preserves a
  `status` error and clearing `status` preserves a `logs` error.
- Browser: reload a project with a retained failed run and assert the exit code, failure line, logs, and retry button are visible without starting a new process.
- Browser: load an externally started local service and assert reachable copy,
  canonical URL, Open, and absence of Stop.

### 7. Wrong vs Correct

Wrong:

```tsx
if (status.running || status.service.state === "reachable") {
  return <Button onClick={stopProject}>Stop</Button>;
}
```

Correct:

```tsx
if (status.running) {
  return <Button onClick={stopProject}>Stop</Button>;
}
if (status.service.state === "reachable" && status.service.url) {
  return <a href={status.service.url}>Open</a>;
}
```


---

## Scenario: Recoverable Prototype Planning and Generation State

### 1. Scope / Trigger

- Trigger: changing the prototype plan review page, planning/generation SSE,
  refresh recovery, polling fallback, or progress counters.
- Planning drafts and generation activity are recoverable server workflows.
  React state renders and reconciles them; it is not the lifecycle owner.

### 2. Signatures

- Planning hook:
  `usePrototypePlanLiveRecovery({ plan, planId, projectId, onSnapshot, recoveryKey })`.
- Generation hook:
  `usePrototypeGenerationLiveRun({ run, onSnapshot, recoveryKey })`.
- Recovery reads:
  `getPrototypePlan(planId)` and `getPrototypeGenerationRun(runId)`.
- Stream identity:
  heartbeat `{ contract_version: 1, resource_id, sent_at }` plus a full
  persisted plan/run snapshot.
- Generation counters:
  `processed`, `succeeded`, `failed`, `running`, `pending`, and
  `total`.

### 3. Contracts

- The latest valid persisted snapshot is the source of truth after reload.
  Never reconstruct run/item terminal state from component-local booleans.
- Open SSE only for active plans/runs. Every snapshot and heartbeat must match
  the requested plan/run identity; planning snapshots must also match the
  project identity.
- A valid snapshot or heartbeat marks the stream healthy and resets the bounded
  recovery budget. Silence, disconnect, or an invalid frame surfaces a visible
  connection issue and activates REST reconciliation.
- Poll every 1.5 seconds only while recovery is active, for at most 20 attempts
  and 60 seconds. Exhaustion stops automatic polling and leaves an explicit
  manual recovery path; it never becomes an infinite background poll.
- A failed REST reconciliation preserves the last valid plan/run, editable
  draft, and generated results. Log with plan/run identity and set a visible
  polling error.
- `processed = done + failed + interrupted + skipped`,
  `succeeded = done`, and `failed = failed + interrupted`. The primary
  progress bar uses `processed / total`, not successful `completed / total`.
- A terminal run has `processed === total`, `running === 0`, and
  `pending === 0`. A partial 8-success/5-failure run therefore renders
  `13/13` processed and retains all five retryable failure details.

### 4. Validation & Error Matrix

- Snapshot parse failure -> keep stale data, show `invalid_snapshot`, and
  enter bounded polling.
- Snapshot/heartbeat resource mismatch -> reject the frame, keep stale data,
  show `invalid_resource`, and do not apply it to the current page.
- SSE error or 15 seconds without valid activity -> show
  `disconnected` / `silent` and enter bounded polling.
- Valid REST snapshot for the wrong resource -> reject it and stop treating the
  response as recovery.
- Poll request failure -> keep stale data, log with identity, and expose retry.
- Poll budget exhausted -> stop automatic recovery and show the explicit
  exhausted state; manual refresh increments `recoveryKey` and starts a fresh
  bounded budget.
- Terminal snapshot -> close active recovery and render its persisted counters,
  item errors, timestamps, and retry eligibility.

### 5. Good/Base/Bad Cases

- Good: SSE is buffered after an 8/13 display; silence detection polls the run,
  applies the persisted 13/13 terminal snapshot, and keeps all failure rows.
- Base: an active planning snapshot and heartbeat arrive normally, reset the
  budget, and update batch progress without polling.
- Bad: clearing the current plan or unsaved draft when one poll request fails.
- Bad: accepting a valid snapshot for another run because its shape parses.
- Bad: using `completed / total` as the progress bar for a partial terminal run.
- Bad: leaving a poll interval active forever after the recovery deadline.

### 6. Tests Required

- Pure recovery-budget tests cover attempt limit, deadline, and healthy-stream
  reset.
- Hook/source tests cover silence, disconnect, resource mismatch, REST failure,
  stale-data preservation, terminal stop, and manual recovery reset.
- Snapshot tests assert the 8-success/5-failure terminal run is 13/13 processed
  and reject counter/item contradictions.
- Browser checks at 1164, 390, and 375 CSS pixels assert first-viewport metrics,
  visible failure recovery, and no horizontal overflow.

### 7. Wrong vs Correct

Wrong:

```tsx
source.onerror = () => {
  setRun(null);
  setItems([]);
};
```

Correct:

```tsx
source.onerror = () => {
  setConnectionIssue("disconnected");
  // Keep the last snapshot and let the bounded REST reconciler refresh it.
};
```

---

## Scenario: Structured Generation-to-Studio Bootstrap

### 1. Scope / Trigger

- Trigger: changing the structured Studio route, requirements generation UI,
  generation polling, candidate acceptance, runtime session creation, or the
  procurement walkthrough controls.
- The structured document and durable generation job are server state. React
  and local storage may cache request/session identity but never choose the
  project's canonical draft.

### 2. Signatures

- Studio hook: `useStructuredPrototypeStudio(projectId)`.
- Generation hook:
  `useStructuredPrototypeGeneration({ projectId, onAccepted })`.
- Reads: `getCurrentStructuredPrototypeDraft(projectId, clientRequestId)` and
  `getCurrentStructuredPrototypeGenerationJob(projectId)`.
- Semantic projection:
  `deriveProcurementRuntimeBindings(document) -> ProcurementRuntimeBindings | null`.
- Generation actions: create requirements job, confirm blueprint, accept
  candidate, then recover the project-current draft.

### 3. Contracts

- Studio always asks the backend for the project-current draft. A `null` draft
  renders requirements generation; it never creates a fixture document.
- The generation UI exposes requirements, blueprint pages, durable counters,
  item phase/status, job/operation/task/process IDs, preview, and Accept.
- Poll only active statuses every two seconds, for at most 300 attempts. Keep
  the last valid job on request failure and expose manual recovery.
- Accept is complete only after the returned draft ID matches a fresh
  project-current draft recovery; then the same Studio controller creates the
  pinned runtime session.
- Procurement actions derive scenario, form, entity fields, table, submit, and
  approve identities from stable runtime keys and rule triggers. Form inputs
  are selected from the referenced Form subtree by their typed input roles.
- Missing or ambiguous semantic mappings return `null` and fail Studio startup;
  components never import fixture UUIDs for production interaction behavior.

### 4. Validation & Error Matrix

- Current draft `null` -> show requirements generation with no runtime session.
- Current generation `null` -> show empty requirements state.
- Generation poll failure -> retain the last job/blueprint/preview and show the
  error plus Retry.
- Poll budget exhausted -> stop automatic polling and show localized manual
  recovery.
- Missing blueprint/candidate/output hash -> disable Confirm/Accept.
- Accepted response draft ID differs from project-current recovery -> visible
  failure; do not enter Studio.
- Missing scenario/rule/form/schema key or ambiguous text/number inputs -> fail
  closed before runtime creation.

### 5. Good/Base/Bad Cases

- Good: refresh during Claude page generation restores job progress without a
  browser-owned job ID.
- Base: a project with no structured data starts at the requirements form.
- Good: an accepted generated document with different opaque UUIDs still runs
  because behavior is derived from semantic keys.
- Bad: production imports `STRUCTURED_PROCUREMENT_IDS` to submit or approve.
- Bad: a poll error calls `setJob(null)` or clears the candidate preview.

### 6. Tests Required

- Pure tests cover active polling statuses, processed progress, retryable
  terminal jobs, semantic binding success, and fail-closed missing keys.
- API tests cover current draft, current job, create/confirm/accept URL and body
  contracts.
- Full TypeScript, node tests, ESLint, and Prettier pass.
- Browser checks cover direct accepted-Studio recovery, document-free generation
  entry, enabled requirements action, desktop/narrow overflow, and console
  errors.

### 7. Wrong vs Correct

Wrong:

```tsx
const scenarioId = STRUCTURED_PROCUREMENT_IDS.scenario;
const submitNodeId = STRUCTURED_PROCUREMENT_IDS.nodes.submitRequest;
```

Correct:

```tsx
const bindings = deriveProcurementRuntimeBindings(draft.document);
if (!bindings) throw new Error("procurement runtime contract is unavailable");
await createRuntimeSession(draft.draftId, bindings.scenarioId);
```
