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
- `ProjectRunStatus.service.state` is transport/address evidence:
  `reachable`, `unreachable`, `not_configured`, `invalid_url`, or `unknown`.
  Never infer reachability from process creation, and never promote a generic
  HTTP response into expected-application identity.
- `ProjectRunStatus.readiness.state` is application evidence:
  `ready`, `unreachable`, `occupied_unknown`, `identified_unready`, or
  `invalid_config`. Only `ready` completes the **Run** step or exposes Open for
  an externally started application.
- `running=true` plus `readiness=ready` is managed and ready;
  `running=true` plus any other readiness state is starting or unhealthy;
  `running=false` plus `readiness=ready` is the correct externally started
  application; `running=false` plus transport `reachable` but non-ready is an
  occupied unknown responder.
- An external ready application exposes Open but never Stop. An occupied unknown
  responder blocks Start but exposes neither Open nor Stop as if it were the
  configured application.
- `invalid_config` is actionable: disable per-service and batch Start, show that
  startup analysis must be regenerated, and keep the Analyze Again action
  available.
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


## Scenario: Structured Generation-to-Studio Bootstrap

### 1. Scope / Trigger

- Trigger: changing the structured Studio route, requirements generation UI,
  generation polling, candidate acceptance, runtime session creation, or the
  procurement walkthrough controls.
- The structured document and durable generation job are server state. React
  and local storage may cache request/session identity but never choose the
  project's canonical draft.

### 2. Signatures

- Canonical route composition:
  `/projects/:id/prototypes -> StructuredPrototypeRoutePage -> WorkbenchShell -> ProjectShell -> StructuredPrototypeStudioPage`.
- Compatibility route:
  `/projects/:id/prototypes/studio -> redirect(/projects/:id/prototypes)`.
- Studio hook: `useStructuredPrototypeStudio(projectId)`.
- Generation hook:
  `useStructuredPrototypeGeneration({ projectId, onAccepted })`.
- Optional guidance normalization:
  `structuredPrototypeGenerationBrief(brief: string) -> non-empty string`.
- Reads: `getCurrentStructuredPrototypeDraft(projectId, clientRequestId)` and
  `getCurrentStructuredPrototypeGenerationJob(projectId)`.
- Semantic projection:
  `deriveProcurementRuntimeBindings(document) -> ProcurementRuntimeBindings | null`.
- Generation actions: create requirements job, confirm blueprint, accept
  candidate, then recover the project-current draft.

### 3. Contracts

- The canonical prototype route stays inside both `WorkbenchShell` and
  `ProjectShell`; the global sidebar, project identity, and project-section
  navigation remain available in empty, generating, and editing states.
- The historical `/prototypes/studio` URL is redirect-only. Never point a Back
  action at a route that redirects to the currently mounted page.
- Studio always asks the backend for the project-current draft. A `null` draft
  renders project analysis and generation inside the project shell; it never
  creates a fixture document or mounts a standalone full-viewport application.
- User guidance is optional. An empty or whitespace-only value is normalized to
  the pinned project-analysis brief before the versioned create-job request, so
  stored request evidence remains non-empty and reproducible.
- Prototype tool chrome uses console semantic tokens (`bg-surface`,
  `border-border-subtle`, `text-text-muted`, status families, and `bg-brand`).
  The rendered prototype canvas/iframe keeps the prototype document's own
  colors; console theming must not rewrite the artifact being reviewed.
- The generation UI exposes optional guidance, blueprint pages, durable counters,
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

- Canonical `/prototypes` navigation -> render app chrome, project chrome, and
  the structured content in one route hierarchy.
- Historical `/prototypes/studio` navigation -> redirect once to canonical
  `/prototypes`; no self-loop.
- Current draft `null` -> show project analysis/generation with no runtime session.
- Empty guidance -> send the pinned project-analysis brief; do not disable Start.
- Current generation `null` -> show the empty analysis state.
- Project title load failure -> retain the prototype surface, show a visible
  retry error, and do not silently clear already loaded project data.
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

- Good: entering Prototype Design keeps the same global sidebar, project header,
  theme, and section navigation as Workspaces and Conductor.
- Good: refresh during Claude page generation restores job progress without a
  browser-owned job ID.
- Base: a project with no structured data starts at project analysis; guidance
  may be blank.
- Good: an accepted generated document with different opaque UUIDs still runs
  because behavior is derived from semantic keys.
- Bad: `/projects/:id/prototypes` redirects to `/prototypes/studio` while the
  editor Back link points to `/prototypes`, creating a navigation loop.
- Bad: standalone prototype chrome uses hard-coded light hex colors inside the
  dark console.
- Bad: production imports `STRUCTURED_PROCUREMENT_IDS` to submit or approve.
- Bad: a poll error calls `setJob(null)` or clears the candidate preview.

### 6. Tests Required

- Pure tests cover active polling statuses, processed progress, retryable
  terminal jobs, optional-guidance normalization, semantic binding success, and
  fail-closed missing keys.
- Source tests assert the canonical route composes `WorkbenchShell` and
  `ProjectShell`, the compatibility route redirects, and Studio/generation
  chrome has no hard-coded hex colors.
- API tests cover current draft, current job, create/confirm/accept URL and body
  contracts.
- Full TypeScript, node tests, ESLint, and Prettier pass.
- Browser checks cover direct accepted-Studio recovery, document-free generation
  entry, enabled requirements action, desktop/narrow overflow, and console
  errors.

### 7. Wrong vs Correct

Wrong:

```tsx
// Standalone route plus a Back target that redirects to itself.
redirect(`/projects/${id}/prototypes/studio`);
<Link href={`/projects/${id}/prototypes`}>Back</Link>;
```

Correct:

```tsx
<WorkbenchShell breadcrumbs={breadcrumbs}>
  <ProjectShell projectId={projectId} project={project}>
    <StructuredPrototypeStudioPage projectId={projectId} />
  </ProjectShell>
</WorkbenchShell>;

const brief = structuredPrototypeGenerationBrief(optionalGuidance);
```

---

## Scenario: Structured Prototype Mutation Outcome Recovery

### 1. Scope / Trigger

- Trigger: changing a structured-prototype Studio, AI, generation, publication,
  runtime, or deletion mutation whose HTTP response can be lost after the
  backend has accepted the request.
- The browser may remember an in-flight request identity, but only durable
  operation evidence plus an authoritative resource read can prove completion.
- A stored Studio runtime-session pointer can outlive the database that created
  it, for example after switching from an isolated acceptance database back to
  the main database. That stale pointer is a lookup failure, not runtime
  corruption or proof that a reset operation failed.

### 2. Signatures

- Persist request state:
  `beginStructuredPrototypePendingOperation(projectId, descriptorInput) -> StructuredPrototypePendingOperation`.
- Resume request state:
  `loadStructuredPrototypePendingOperation(projectId) -> StructuredPrototypePendingOperation | null`.
- Outcome read:
  `GET /api/projects/{projectId}/structured-prototype-operations/outcome?operationKind={kind}&clientRequestId={uuid}`.
- Outcome wait:
  `waitForStructuredPrototypeOperationOutcome(descriptor) -> Promise<StructuredPrototypeOperationOutcome>`.
- Completion:
  `finishStructuredPrototypePendingOperation(projectId, clientRequestId) -> void`.
- Recovery owners:
  `reconcilePendingStudioOperation`, `reconcilePendingPrototypeAiOperation`, and
  `reconcilePendingPrototypeGenerationOperation`.
- Stale stored-session classifier:
  `shouldRecreateMissingStoredRuntimeSession(error, { hasCommittedReset, hasResetOutcomeError }) -> boolean`.

### 3. Contracts

- Persist the pending descriptor before sending the mutation. Re-entering the
  exact same operation returns the same `clientRequestId`; a different mutation
  is refused while that descriptor exists.
- Every structured-prototype API request has an abort deadline. A timeout,
  retryable API failure, network `TypeError`, or `operation_outcome_unknown`
  starts bounded outcome polling; it does not prove failure or success.
- `queued`, `running`, unknown outcome, exhausted polling, corrupt storage, and
  an authoritative resource read failure all retain the descriptor and keep the
  owning controller locked.
- A terminal outcome is necessary but not sufficient to clear the descriptor.
  The owning controller first re-reads and validates the current draft, runtime
  session, publication, AI thread/edit run, generation job, or deletion state.
- Resource kind, resource ID, project ID, operation kind, and request ID must
  agree across the descriptor, outcome, and authoritative resource snapshot.
- A known terminal failure clears the exact descriptor only after the expected
  post-failure resource state is readable, then surfaces
  `StructuredPrototypeOperationOutcomeError` with operation and correlation
  evidence.
- Keep the last valid draft, runtime, job, thread, and preview on recovery
  failure. Set a visible error and derive `saving` / `mutating` from whether the
  controller still owns a pending operation.
- Recreate a stored runtime session only when the typed API error is exactly
  `status=404` plus `code=runtime_session_missing`, no reset outcome has already
  committed a replacement pointer, and no reset terminal error is awaiting
  presentation. Use the normal `create_runtime_session` pending-operation path;
  keep the old pointer until the replacement session is decoded, then overwrite
  it atomically with the new session ID.

### 4. Validation & Error Matrix

- `404 operation_outcome_unknown` -> retry within the bounded poll budget; keep
  the lock if the budget expires.
- Outcome `queued` or `running` -> retry; never clear storage even when a result
  resource is already observable.
- Outcome identity differs from the descriptor -> visible recovery mismatch;
  preserve the descriptor and lock.
- Terminal success plus missing/mismatched authoritative resource -> recovery
  pending error; preserve the descriptor and lock.
- Terminal failed/interrupted/cancelled plus valid post-failure resource state ->
  clear the exact descriptor and show the terminal error evidence.
- Malformed browser storage -> visible storage error and fail-closed lock; do
  not delete the corrupt evidence automatically.
- Completion called with another `clientRequestId` -> storage error; do not
  remove either request identity.
- Stored runtime lookup returns `404 runtime_session_missing` with no committed
  or failed reset evidence -> create a fresh session pinned to the recovered
  draft, then replace the stored pointer.
- The same error code arrives with a non-404 status, or the request fails with a
  timeout, network error, 5xx, response parsing/codec error, corrupt/version
  recovery code, pending operation, committed reset, or reset terminal error ->
  do not create a session; preserve the evidence and fail closed.

### 5. Good/Base/Bad Cases

- Good: command POST times out, outcome moves from unknown to running to
  succeeded, the current draft matches, and only then does Studio unlock.
- Good: refresh during AI apply reloads the pending descriptor, verifies the
  edit run and current draft, and restores both thread and canvas state.
- Base: a direct successful response updates the authoritative controller state
  and completes the matching descriptor once.
- Good: Studio returns from an isolated database to the main database, receives
  an explicit missing-session 404 for the old pointer, creates one observable
  replacement session, and preserves the draft sequence and document hash.
- Bad: clear `pending-operation-v1` in a generic `catch` because the server did
  not answer before the deadline.
- Bad: observe a new draft or job while the operation outcome is still running
  and infer terminal success from that resource alone.
- Bad: wipe the last loaded prototype when reconciliation cannot reach the
  backend.
- Bad: treat any `runtime_session_missing` code as sufficient without checking
  HTTP status or reset ownership; a drifted 5xx response can then create a
  duplicate session and hide an infrastructure failure.

### 6. Tests Required

- Unit: exact operation re-entry reuses one request UUID; a competing mutation
  is refused.
- Unit: unknown and running outcomes precede terminal success; poll exhaustion
  leaves the descriptor and controller lock intact.
- Unit: corrupt pending storage remains stored and produces a fail-closed lock.
- API parser: reject unknown/missing fields, identity drift, inconsistent
  terminal/status pairs, invalid lifecycle timestamps, and invalid evidence
  hashes.
- Controller/source contracts: Studio, AI send/apply/reject, generation
  start/confirm/accept/delete, runtime, publish, undo/redo, and command batches
  all use the shared pending-operation recovery path.
- Browser: reload during a pending mutation preserves visible data and prevents
  a second mutation until terminal outcome plus resource reconciliation.
- Unit: the stale-session classifier accepts only 404 plus
  `runtime_session_missing`; 5xx with the same code, network errors, committed
  reset evidence, and reset outcome errors all return false.
- Browser/store: seed a pointer absent from the active database, reload Studio,
  and assert one succeeded `create_runtime_session` operation with contiguous
  events `[0,1,2]`, a new active session pinned to the original document hash,
  unchanged draft sequence/hash, no visible missing-session error, and an
  unlocked canvas.

### 7. Wrong vs Correct

Wrong:

```ts
try {
  await applyMutation();
} catch (error) {
  localStorage.removeItem(pendingKey);
  setSaving(false);
  setDraft(null);
}
```

Correct:

```ts
const descriptor = beginStructuredPrototypePendingOperation(projectId, input);
try {
  const result = await applyMutation(descriptor.clientRequestId);
  await acceptAuthoritativeResult(result);
  finishStructuredPrototypePendingOperation(projectId, descriptor.clientRequestId);
} catch {
  await reconcilePendingStudioOperation(descriptor);
}
```

Wrong stored-session recovery:

```ts
if (error.code === "runtime_session_missing") {
  localStorage.removeItem(runtimePointerKey);
  return createRuntime(draft);
}
```

Correct stored-session recovery:

```ts
if (
  shouldRecreateMissingStoredRuntimeSession(error, {
    hasCommittedReset: committedReset !== null,
    hasResetOutcomeError: resetOutcomeError !== null,
  })
) {
  return createRuntime(draft); // The decoded replacement writes the new pointer.
}
throw error;
```

---

## Scenario: Flow Rule Persisted-Draft Runtime Recovery

### 1. Scope / Trigger

- Trigger: changing Flow rule create, replace, or remove behavior in
  `StructuredPrototypeStudioPage`, where `applyCommands` persists a command
  batch before rebuilding the pinned runtime session.
- A runtime reset can fail after the draft head has already changed. Treating
  the controller's `false` result as a failed rule save remounts the inspector
  against stale input and can submit a duplicate rule.

### 2. Signatures

```ts
type StructuredPrototypeFlowRuleMutationTarget =
  | { kind: "ruleKey"; ruleKey: string }
  | { kind: "ruleId"; ruleId: string }
  | { kind: "clear" };

interface StructuredPrototypeFlowRuleMutation {
  baseDocumentHash: string;
  target: StructuredPrototypeFlowRuleMutationTarget;
  failureMessage: string;
  requestSettled: boolean;
}

resolveStructuredPrototypeFlowRuleMutationOutcome(
  mutation,
  currentDocumentHash,
  saving,
) -> { kind: "pending" | "persisted" | "failed" };
```

### 3. Contracts

- Capture `controller.draft.documentHash` and write the mutation state before
  dispatching `addBehaviorRule`, `replaceBehaviorRule`, or
  `removeBehaviorRule`.
- A different current document hash is durable proof that this Flow command
  persisted. It wins even while `saving=true`, `applyCommands` resolves
  `false`, or `runtimeRecovery` is visible.
- The request completion callback marks `requestSettled=true` only when the
  exact mutation object is still current. A stale callback must not settle or
  overwrite a later mutation.
- On `persisted`, derive the next inspector selection from the canonical
  document: rule key for creates, rule ID for replaces, and no selection for a
  removal. Do not keep the pending connection draft mounted.
- On `failed`, require both an unchanged document hash and a settled request
  with `saving=false`. Preserve the Inspector draft and show its localized
  failure message.
- `runtimeRecovery` remains a document-wide mutation lock. This local outcome
  state only disambiguates persistence; it does not permit another edit before
  the runtime is recovered.

### 4. Validation & Error Matrix

- Command batch commits, then runtime reset fails -> `persisted`; select the
  canonical rule or clear selection, show the recovery notice, and do not show
  the rule-save failure.
- Request settles with the original document hash and `saving=false` ->
  `failed`; keep the Inspector's unsaved draft visible.
- Request has not settled and the hash is unchanged -> `pending`; no success or
  failure feedback is emitted.
- A later mutation replaces the state before an earlier promise settles -> the
  earlier callback is ignored.
- Remove command changes the hash -> `persisted` with `{ kind: "clear" }`;
  the deleted rule cannot remain selected.

### 5. Good/Base/Bad Cases

- Good: a create command writes a rule, runtime reset needs manual recovery,
  and the inspector selects the newly allocated rule exactly once.
- Good: a replace command changes a navigate target; Flow counts and browser
  runtime navigation use the same rule ID after recovery.
- Base: an ordinary successful response changes the hash and selects the rule
  after the controller finishes rebuilding runtime.
- Bad: `if (!applied) setInteractionError(saveFailed)` after every command;
  it misclassifies a persisted draft with a failed runtime reset.
- Bad: select a rule immediately from the optimistic callback before the new
  document hash is visible; it can remount the Inspector with stale state.

### 6. Tests Required

- Unit: `structuredPrototypeFlowRuleMutation.test.ts` proves hash change wins
  while saving, unchanged settled hash fails, and an in-flight unchanged hash
  remains pending.
- Source/Flow test: Flow create, replace, and remove route through the shared
  mutation state rather than an `onApplied` boolean branch.
- Browser: create a Flow rule, change its navigation target, execute the
  runtime button, delete it, undo, redo, and undo again. Assert the final Flow
  projection and runtime event both reference the same rule ID.
- Store/API: command journal records `addBehaviorRule`, `replaceBehaviorRule`,
  `removeBehaviorRule`, undo, and redo as immutable batches with distinct
  document hashes.

### 7. Wrong vs Correct

Wrong:

```ts
void applyInspectorCommands(batch).then((applied) => {
  if (applied) onApplied();
  else setInteractionError(failureMessage);
});
```

Correct:

```ts
setFlowRuleMutation(mutation);
void applyInspectorCommands(batch).finally(() => {
  setFlowRuleMutation((current) =>
    current === mutation ? { ...current, requestSettled: true } : current,
  );
});
// A changed canonical document hash resolves the mutation as persisted.
```

---

## Scenario: Freeform Move Snapping Transaction

### 1. Scope / Trigger

- Trigger: changing direct-child movement, snapping, or smart-guide rendering for an explicit
  structured-prototype `Freeform` container.
- Snapping is transient editor projection. The command journal remains the only persistent
  mutation authority.

### 2. Signatures

- Pure solver:
  `resolveStructuredPrototypeFreeformMoveSnap(input) -> { position, delta, guides }`.
- Pure overlay projection:
  `projectStructuredPrototypeFreeformSnapGuides(input) -> projected guides`.
- Gesture start frame freezes selection bounds, selected node IDs, visible direct siblings,
  container dimensions, preview scale, and the Freeform's Canvas-local overlay frame.
- Hook output keeps `draft` and `guideOverlay` separate.

### 3. Contracts

- Moving `left | center | right` and `top | middle | bottom` anchors may snap independently to
  Freeform boundaries/centers or unselected visible direct siblings.
- The threshold is exactly six client pixels converted through the preview scale frozen at
  pointerdown. Candidate ordering is deterministic.
- Do not read sibling DOM geometry in RAF callbacks. Collect same-parent targets once in document
  order, require a live direct DOM child, and exclude the complete moving selection.
- A rendered child may overflow its Freeform because intrinsic DOM content can exceed the typed
  layout frame. Overflow or floating-point edge overshoot must not throw inside RAF; clamp the raw
  move and reject only snap corrections whose resulting origin is invalid.
- Editable preview scale/width changes do not use CSS interpolation. Pointer geometry must never
  freeze an in-between transform scale.
- Ctrl or Meta on the current pointer event bypasses snapping. RAF preview and pointerup exact-tail
  commit call the same projection function with that event's modifier state.
- Guides render only in the Canvas selection-controls layer during `preview`, span the owning
  Freeform, remain one physical pixel at every zoom, and never enter business DOM.
- Pointerup clears guides before the pending command, submits the existing one atomic position
  batch, and preserves one Undo item. Cancel, blur, lost capture, Escape, failed apply,
  acknowledge, and unmount clear guides without a command.

### 4. Validation & Error Matrix

- Invalid container dimensions, scale, coordinates, duplicate IDs, or non-positive measured
  frames -> pure solver/projection error in focused tests; Canvas does not construct such input.
- Hidden, runtime-hidden, detached, stale-parent, nested-descendant, or zero-size sibling -> omit
  from the frozen target set.
- Selection or sibling extends past the container -> movement remains available; only a snapped
  origin outside the legal movement range is rejected.
- Ctrl/Meta becomes active during a drag -> next preview and final pointerup use unsnapped geometry.
- Gesture cancellation -> authoritative position restored, guide count zero, sequence unchanged.
- Persistence failure -> pending projection clears through the existing visible error path; no
  stale guide remains.

### 5. Good/Base/Bad Cases

- Good: two Text children share one Freeform; moving one within six client pixels shows sibling
  X/Y guides while the document sequence is unchanged, then pointerup writes one sequence.
- Base: no target is within threshold; movement uses the existing bounded raw projection and shows
  no guide.
- Good: Meta is held only on pointerup; the exact final event bypasses snapping even if the last RAF
  preview was snapped.
- Bad: query `getBoundingClientRect()` for every sibling on every pointermove.
- Bad: attach guide elements inside the runnable prototype node or keep them visible while the
  server command is pending.

### 6. Tests Required

- Pure solver: container and sibling edges/centers, single and group bounds, six-client-pixel zoom
  invariance, deterministic ties, invalid snap origins, and overflowing rendered frames.
- Pure guide projection: nested Canvas origin, both axes, one-device-pixel thickness, metadata, and
  invalid inputs.
- Source contract: frozen targets, shared RAF/pointerup solver, event-local Ctrl/Meta bypass, guide
  cleanup paths, direct-parent filtering, and selection-controls-only rendering.
- Browser: observe guides during preview with an unchanged sequence; pointerup increments once;
  Undo restores position; Meta shows no guides; Escape clears guides and submits nothing; reload
  has no new console error.

### 7. Wrong vs Correct

Wrong:

```ts
window.addEventListener("pointermove", () => {
  const siblings = readEverySiblingRect();
  setDraft(snapWithLiveScale(siblings));
});
```

Correct:

```ts
const gesture = freezeMoveStartFrame();
const resolveProjection = (event: PointerEvent) =>
  event.ctrlKey || event.metaKey
    ? resolveRawMove(gesture, event)
    : resolveStructuredPrototypeFreeformMoveSnap(projectRawMove(gesture, event));
// RAF preview and pointerup exact tail both call resolveProjection().
```

---

## Scenario: Freeform Equal-Spacing Move Snapping Transaction

### 1. Scope / Trigger

- Trigger: changing Freeform move candidate arbitration, distance/equal-spacing guides, or another
  move snap system that competes with edge/center alignment.
- Equal spacing is transient editor projection. It does not add a document command, persistence
  field, or second move transaction.

### 2. Signatures

- Pure axis solver:
  `resolveStructuredPrototypeFreeformSpacingSnap(input) -> spacing candidate | null`.
- Combined move solver:
  `resolveStructuredPrototypeFreeformMoveSnap(input) -> { position, delta, guides, spacingGuides }`.
- Pure distance projection:
  `projectStructuredPrototypeFreeformSpacingGuides(input) -> projected spacing segments`.
- A spacing guide contains `axis`, `placement`, positive `gap`, two stable reference node IDs, and
  exactly two segments with `start`, `end`, `crossCoordinate`, endpoint node IDs, and segment index.

### 3. Contracts

- A single selection or same-Freeform group union is one rigid moving frame. Together with two
  visible, unselected direct siblings it may form `before`, `between`, or `after` equal spacing.
  Group-internal offsets never participate in the spacing calculation.
- All three frames must share a positive cross-axis intersection. Both represented gaps must be
  strictly positive; zero gap remains edge alignment. A same-lane sibling occupying either gap or
  the projected moving frame rejects the candidate.
- Alignment and spacing candidates start from the same continuous, clamped raw frame. Each axis
  chooses the smallest correction; edge/center alignment wins an exact tie. Spacing is never run
  as a second transform on an already aligned position.
- X and Y initially resolve independently. After their positions combine, every winning spacing
  candidate is re-evaluated against the final frame so another axis's alignment cannot move the
  selection out of the shared visual lane. An invalid spacing axis falls back to its original
  alignment/raw result. If both spacing axes invalidate each other, retry the smaller-correction
  axis alone, prefer X on an exact tie, then retry the alternate axis before falling back fully.
- The threshold is exactly six client pixels converted through the pointerdown preview scale.
  Geometry stays continuous before persistence. Relative `1e-9` arithmetic tails may admit a
  threshold/envelope comparison, but the derived equal-spacing target remains authoritative:
  `position = raw + correction` and `distance = abs(correction)`. Arithmetic-zero fixed/derived
  gaps are rejected as edge alignment. After a true envelope normalization, both segment lengths
  must still match the logical gap under the same local tolerance or the candidate is rejected.
- Distance guides render only for the winning spacing candidate during move preview. Each gap gets
  one line, two six-client-pixel end caps, stable participant metadata, and a numeric distance
  label formatted to at most four decimals without changing geometry. Line and cap thickness
  remain one physical pixel at every zoom.
- Candidate ranking is separated from blocker validation. Only a candidate better than the current
  validated winner performs a blocker query. Queries cache `blocked | clear` by exact axis, final
  moving rectangle, shared lane, fixed corridor, and both segment intervals; reference IDs never
  replace real candidate IDs, and different lanes must never share a cache entry.
- Ctrl/Meta bypass returns no alignment or spacing guide. RAF preview and pointerup exact tail use
  the same projection. Pointerup still calls the existing move callback once, so a grouped move is
  one command batch and one Undo item.

### 4. Validation & Error Matrix

- Fewer than two eligible siblings, no positive shared lane, zero/negative gap, occupied corridor,
  overlapping projected frame, or target outside the legal move envelope -> no spacing candidate;
  retain alignment or raw movement.
- Spacing correction farther than six client pixels -> reject. A correction that exceeds the
  boundary only by relative `1e-9` -> normalize and accept; `6 + 1e-6` client pixels -> reject.
- A cross-axis snap removes the final common lane -> discard that spacing guide and restore the
  axis's alignment/raw result.
- Both spacing axes invalidate each other -> retry the lower-distance axis alone; equal distance
  retries X first; if it remains invalid, retry Y and then return alignment/raw.
- A decimal arithmetic tail makes a fixed or derived gap effectively zero -> reject spacing and
  retain edge alignment. A positive canonical `0.0001` gap -> preserve the target and project both
  segments without throwing.
- Multiple equal candidates -> order by correction distance, outer span, placement, gap, position,
  and stable reference IDs; sibling input order cannot change the result.
- Many candidates produce one identical blocker-query geometry -> scan siblings once and reuse the
  exact result. A different shared-lane interval -> perform a distinct query.
- Ctrl/Meta, Escape, pointer cancel, lost capture, blur, failed apply, acknowledgement, or unmount
  -> clear both guide families; cancellation submits no command.

### 5. Good/Base/Bad Cases

- Good: a card moves between two same-row cards; within six client pixels it lands at two equal
  positive gaps and shows two distance segments while the document sequence stays unchanged.
- Good: X spacing and Y alignment both win from one raw frame; the final lane is rechecked before
  the X spacing guide is shown.
- Base: only one sibling exists or no spacing target is near; the established edge/center/raw move
  behavior is unchanged.
- Bad: snap to an edge first and then run spacing against that already shifted result; this creates
  a second correction and makes the guide disagree with pointer intent.
- Bad: round the raw move before threshold comparison; fractional zoom can turn a true
  `> 6 client px` correction into an accepted candidate and destroy half-pixel equal spacing.

### 6. Tests Required

- Pure spacing: `before | between | after` on both axes, single/group union, selected-ID exclusion,
  shared-lane success/failure, fixed/target/projected blockers, off-lane blockers, envelope bounds,
  input-order invariance, and deterministic ties.
- Numeric boundary: `0.5 | 1 | 2 | 4` zoom, exact six-client-pixel acceptance, `6 + 1e-6`
  rejection, fractional targets, and relative tail normalization at threshold/envelope boundaries.
- Arbitration: spacing closer than alignment, alignment exact tie, X spacing plus Y alignment,
  compatible X/Y spacing, final-lane invalidation after the other axis snaps, mutually invalid
  X/Y candidates with smaller-distance and X-tie fallback, then full fallback.
- Projection/UI: two same-axis segments keep order and metadata; lines/caps remain one physical
  pixel; React keys include axis, placement, reference IDs, and segment index; positive tiny gaps
  and continuous coordinates display at most four decimals; Resize supplies an explicit empty
  spacing-guide collection.
- Density/performance: 400 exact-overlap siblings, 400 unique full frames with one effective lane,
  a shared blocker, shuffled input, and same-midpoint/different-lane cache isolation. Record the
  100/200/400-node benchmark separately; do not use a flaky wall-clock unit-test assertion.
- Transaction source/browser: pointerup passes the exact final projection to one move callback;
  group union delta maps to every group item; browser sequence stays unchanged during preview,
  increments once on commit, and one Undo restores all items.

### 7. Wrong vs Correct

Wrong:

```ts
const aligned = resolveAlignment(raw);
const spaced = resolveSpacing({ ...input, movingBounds: aligned });
return roundPosition(spaced.position);
```

Correct:

```ts
const alignment = collectAlignmentCandidate(raw);
const spacing = collectSpacingCandidate(raw);
const projected = chooseNearestCandidate(alignment, spacing); // alignment wins a tie
return revalidateSpacingPlans(projected, {
  mutualFallback: "smaller-correction-then-x-tie",
  blockerCacheKey: "axis+final-frame+lane+corridors",
});
```

---

## Scenario: Freeform Resize Snapping Transaction

### 1. Scope / Trigger

- Trigger: changing resize geometry, snapping, modifiers, group projection, or smart-guide
  rendering for positioned direct children of a structured-prototype `Freeform` container.
- Resize snapping is a transient editor projection. The accepted document and command journal
  remain the only persistent mutation authority.

### 2. Signatures

- Pure snap solver:
  `resolveStructuredPrototypeFreeformResizeSnap(input) -> { bounds, guides }`.
- Shared bounded geometry:
  `resolveStructuredPrototypeResizeBounds(input) -> { x, y, width, height }`.
- Group projection:
  `projectStructuredPrototypeGroupItemsToBounds(items, bounds) -> projected items`.
- Gesture state is `idle -> armed -> preview -> pending -> idle`; pointerdown freezes selection
  bounds, selected node IDs, visible direct siblings, container dimensions, minimum size,
  preview scale, and the Freeform's Canvas-local guide frame.

### 3. Contracts

- All eight handles snap only their active pointer-side edges. A corner may snap independently on
  both axes; a side handle never invents a guide for its derived axis.
- Candidate targets are the Freeform's `left | center | right` and `top | middle | bottom` anchors
  plus the same anchors of visible, unselected direct siblings. Ordering and tie-breaking are
  deterministic and independent of sibling input order.
- The threshold is exactly six client pixels converted with the preview scale frozen at
  pointerdown. Fractional target coordinates remain continuous until canonical command encoding.
- Shift preserves the starting aspect ratio. For a corner, the closest compatible axis drives the
  ratio and the other axis receives a guide only when its derived edge exactly matches a target.
- Alt keeps the center fixed. Shift+Alt combines both contracts. Ctrl or Meta from the current
  pointer event bypasses snapping without disabling bounded resize geometry.
- Single and grouped selections use the same snapped selection bounds. Group children are then
  proportionally reprojected in stable caller order; no child command is committed early.
- A pre-existing right/bottom overflow frame remains editable: zero movement cannot jump it,
  resize may recover it toward the container, and no projection may worsen the existing envelope.
- Every projected `x`, `y`, `width`, and `height` must already fit the canonical Freeform field
  range `0..4096`; preview must never rely on command encoding to reject or repair geometry.
  Group minimum scale includes every projected child's coordinate cap, and group maximum scale is
  derived from every child dimension. The transient group union may exceed `4096` because it is not
  persisted; limiting the union itself would corrupt otherwise valid multi-node layouts.
- Repeated center/aspect arithmetic may create machine-precision tails at a legal boundary. Values
  within relative `1e-9` of `0`, `4096`, or a frozen start value normalize to that boundary before
  preview; meaningful out-of-range values still fail fast. Resize-only child projection owns this
  normalization, while Move/Nudge preserve their raw measured dimensions.
- RAF preview and pointerup exact tail call the same projection function with the current event's
  modifiers. Guides render only in the Canvas selection-controls layer during `preview`, remain
  one physical pixel at every zoom, and clear before `pending`.
- Pointerup persists one atomic frame/position batch for the single node or complete group and
  creates one Undo item. Cancel, blur, lost capture, Escape, rejected commit, failed apply,
  acknowledgement, and unmount clear draft guides without a partial command.

### 4. Validation & Error Matrix

- Empty or duplicate selected IDs; duplicate sibling IDs; invalid direction; non-finite values;
  non-positive scale, dimensions, minimum size, or container dimensions -> fail fast in the pure
  solver; Canvas must not construct malformed frozen input.
- Hidden, runtime-hidden, detached, stale-parent, nested-descendant, zero-size, or selected sibling
  -> omit from the frozen target set.
- Candidate violates minimum size, fixed-center envelope, aspect ratio, or active-edge equality ->
  reject that candidate and retain the legal bounded raw projection.
- Existing frame overflows right/bottom -> use the starting overflow edge as the maximum envelope;
  allow recovery but reject a result that extends farther.
- Union bounds fit `0..4096` but a proportionally projected child origin would exceed `4096` ->
  raise that axis's minimum group scale until every child field is directly canonical.
- Group union width/height exceeds `4096` while every child field is legal -> preserve the union and
  apply child-derived maximum scale; do not clamp the transient union to a document-field limit.
- Derived aspect/center value differs from a legal boundary only within relative `1e-9` -> normalize
  before coordinate clamping; a larger difference remains an error.
- Ctrl/Meta changes after the last RAF -> pointerup recomputes unsnapped exact-tail geometry from
  that event and commits no stale preview guide.
- Gesture cancellation or persistence failure -> sequence remains unchanged, authoritative bounds
  return, guide count becomes zero, and the existing visible error path owns failure reporting.

### 5. Good/Base/Bad Cases

- Good: resize the east edge within six client pixels of a sibling center; preview shows one X
  guide without changing the sequence, then pointerup writes exactly one batch.
- Good: resize a two-node group from northwest with Shift+Alt; snap shared bounds first, preserve
  the shared ratio and center, then proportionally project both children into one Undo unit.
- Base: no compatible target is within threshold; bounded raw resize remains active with no guide.
- Good: a frame already extends past the right edge; dragging inward can snap it to the container,
  while zero or outward movement cannot make overflow worse.
- Bad: snap every selected child independently, which distorts group spacing and produces
  conflicting guides.
- Bad: reuse the last RAF result on pointerup, because late Shift, Alt, Ctrl, or Meta changes would
  commit geometry the pointer event did not request.

### 6. Tests Required

- Pure solver: all eight handles; container/sibling edges and centers; exact six-client-pixel zoom
  invariance; deterministic ties; continuous coordinates; malformed frozen inputs.
- Modifier matrix: Shift, Alt, Shift+Alt, Ctrl/Meta bypass, side-handle derived-axis exclusion, and
  corner aspect-driver selection.
- Bounds and groups: minimum size, existing overflow recovery/non-worsening, shared group snap, and
  proportional child projection in stable order, including west/north/center transforms at the
  canonical `4096` field boundary.
- Boundary stress: no-op and nonzero constrained Shift/Alt cases, a legal group union wider than
  `4096`, and resize-only proportional tails at `4096`; Move/Nudge raw projection stays unchanged.
- Source contract: frozen start frame, one shared RAF/pointerup projection, event-local modifiers,
  `idle/armed/preview/pending` phases, one batch, and cleanup on every terminal path.
- Browser: sequence unchanged during preview; resize guides are visible and one physical pixel at
  multiple zooms; pointerup increments once; Undo restores every frame; Meta shows no guide;
  Escape submits nothing; desktop/mobile reloads add no console error.

### 7. Wrong vs Correct

Wrong:

```ts
const preview = snapResize(readLiveSiblingRects(), lastPointerMove);
setDraft(preview);
// Reuse stale RAF geometry and persist each group child separately.
void Promise.all(preview.children.map(updateNodeFrame));
```

Correct:

```ts
const gesture = freezeResizeStartFrame();
const resolveProjection = (event: PointerEvent) =>
  resolveStructuredPrototypeFreeformResizeSnap({
    ...gesture,
    requestedCanvasDelta: toCanvasDelta(gesture, event),
    lockAspectRatio: event.shiftKey,
    resizeFromCenter: event.altKey,
    bypassSnapping: event.ctrlKey || event.metaKey,
  });
// RAF preview and pointerup exact tail both call resolveProjection(); pointerup persists one batch.
```

---

## Scenario: Faithful Structured Prototype Drag Mirrors

### 1. Scope / Trigger

- Trigger: changing structured-prototype node dragging, dnd-kit overlay rendering, preview zoom,
  palette materialization, hover reparenting, or drag cancellation/commit cleanup.
- The drag mirror is transient editor presentation. It must not introduce a document command,
  persistence field, runtime event, or second mutation path.

### 2. Signatures

- Capture:
  `captureStructuredPrototypeDragMirror(source: HTMLElement) -> StructuredPrototypeDragMirrorSnapshot | null`.
- Geometry:
  `resolveStructuredPrototypeDragMirrorGeometry({ clientWidth, clientHeight, contentWidth, contentHeight }) -> geometry | null`.
- Root isolation:
  `resolveStructuredPrototypeDragMirrorRootStyle(contentWidth, contentHeight) -> pixel-frozen style | null`.
- Mounted scroll restoration:
  `restoreStructuredPrototypeDragMirrorScrollState(scrollStates) -> void`.
- Sortable data exposes
  `captureDragMirror: () -> StructuredPrototypeDragMirrorSnapshot | null` for existing nodes.
- Existing-node view:
  `<StructuredPrototypeDragMirrorView snapshot={snapshot} />`.
- Palette view:
  `<StructuredPrototypeNodeDragOverlay kind="palette" node={materializedNode} previewScale={scale} />`.

### 3. Contracts

- Capture the registered business-node DOM synchronously in `onDragStart`, before `isDragging`
  opacity or hover projection can move/remount it. A later RAF capture is not equivalent.
- The snapshot freezes the source's client-pixel width/height, unscaled `offsetWidth/offsetHeight`,
  X/Y scale, text/form/table state, font family, color scheme, and every inherited
  `--prototype-*` custom property needed outside the scaled preview subtree.
- Before mounting, replace parent-relative root layout with the captured pixel border box:
  `position: relative`, zero effective inset/margin, pixel `width/height`, unconstrained min/max,
  neutral flex/grid item properties, and no transform longhands or transition. Preserve the root
  as a positioning context for its absolutely positioned descendants; `position: static` is not
  equivalent.
- Copy live Input `value/checked/indeterminate`, Textarea value, Select option selection, and every
  source element's scroll offsets before sanitization. Restore scroll offsets only after the clone
  is mounted, because detached elements may clamp scrolling to zero.
- Sanitize the clone before mounting it: remove drop-intent elements, duplicate IDs and node/container
  identity attributes, label/reference ownership, autofocus/contenteditable behavior, and tab stops.
  The clone is `aria-hidden`, inert, pointer-inert, fully opaque, and has no transient transform or
  transition of its own.
- Mount the clone in a client-sized host, scale its content-sized inner host from the top-left, and
  remove the cloned element on cancel, successful drop, snapshot replacement, or unmount.
- The live source becomes transparent while retaining layout space. Selection/drop controls remain
  in the editor controls layer for ordinary selection, but the selected node's control chrome is
  visibility-hidden for an active canvas-node drag (the activator DOM stays mounted for the sensor).
  Drop indicators remain in the business-node layer and the captured mirror is the only dragged
  business presentation.
- Selection resize controls use transparent 32-client-pixel hit areas with compact 8px visual
  markers. Selection movement has no visible Grip surface: the move activator exposes four
  invisible 10-client-pixel hit bands on the selection rectangle edges. The selection interior
  stays pointer-transparent so a selected container does not block nested-child selection.
  Freeform hierarchy reparenting remains a distinct compact `Layers3` activator.
- Holding Space disables selection movement and resize before Preview handles pointer-down, so
  viewport panning cannot start a node transform from an edge hit band.
- Palette dragging uses the same materialized transient node that hover projection inserts. Render
  the real leaf/container presentation recursively with document theme variables and the frozen
  preview scale; never replace it with a component type/name card or cap child/table content.
- Page-rail sorting remains a compact page title/route preview. It represents navigation ordering,
  not a business object on the prototype canvas.
- Keep the pure DOM helper and React view on distinct module stems
  (`structuredPrototypeDragMirror.ts` and `StructuredPrototypeDragMirrorView.tsx`). Next module
  resolution on case-insensitive filesystems must not choose between `.ts` and `.tsx` siblings with
  the same stem.

### 4. Validation & Error Matrix

- Zero, negative, NaN, or infinite client/content dimension -> return `null`; do not mount a
  malformed mirror.
- Source/clone tree or form-control shape mismatch -> return `null`; partial live-state copies are
  not valid snapshots.
- Missing registered source, unavailable capture callback, invalid geometry, or live-state copy
  mismatch -> refuse the gesture before opening an interaction session and show the drag-preview
  failure message. Existing nodes never fall back to an independently reconstructed React overlay.
- Hover reparent/remount changes the live source bounds -> keep the captured mirror geometry stable
  for the gesture.
- Active palette, page-rail, and layer-tree drags -> do not hide canvas selection chrome; only a
  canvas node drag whose node is selected may hide it.
- Escape, pointer cancellation, invalid drop, or successful commit -> clear both the node snapshot
  and palette transient node; no cloned identity or focusable surface remains.
- Palette Form without a selected runtime form definition -> preserve the existing fail-closed
  insertion refusal; do not fabricate a preview-only form.

### 5. Good/Base/Bad Cases

- Good: a Button dragged at Fit, 75%, 100%, or 200% keeps the captured client bounds, label, colors,
  and theme while the source is transparent.
- Good: a four-row Table mirror contains all four rows while hover projection moves the source to a
  narrower parent.
- Good: Fit selection has no visible move icon, keeps four 10px edge hit bands and 32px transparent
  resize hit areas, renders only 8px resize markers, and hides the selected node's visual control
  chrome while its business mirror is active.
- Base: page sorting still shows its compact title and route overlay.
- Bad: reconstruct a fixed-width card headed `Button / name`; its geometry and content are not the
  object being moved.
- Bad: render `children.slice(0, 6)` or `rows.slice(0, 3)` in the overlay; the preview silently lies
  about the dragged object.
- Bad: render a visible Grip on the selected source, or keep its outline and resize buttons visible
  during node DnD; they follow the transparent source and visually compete with the mirror.

### 6. Tests Required

- Pure geometry tests cover `0.5 | 0.75 | 1 | 2` scale plus zero, negative, NaN, and infinite
  dimensions. Root-isolation tests prove pixel width/height plus neutral Freeform, flex, and grid
  item properties.
- Source contracts prove synchronous capture, `opacity-0`, clone sanitization, prototype custom
  properties, exact mount scale, cleanup, palette materialization, full recursion, and the absence
  of generic card/truncation code.
- Selection-state tests prove only a selected canvas-node drag or active Freeform move hides visual
  control chrome. Source contracts prove all four 10px edge bands, no `GripVertical`, independent
  `Layers3` reparenting, Space-owned panning, mounted activator DOM, and snap guides outside the
  hidden tools wrappers. Browser acceptance measures the edge and resize geometry and proves Escape
  restores visible, correctly measured controls.
- Browser acceptance compares source/mirror client bounds and theme at Fit, 75%, 100%, and 200%;
  verifies full Table content during hover reparenting; checks palette Button appearance; and proves
  Escape removes the overlay and restores source opacity.
- Existing move projection, nested drop, command, Undo, and recovery tests remain green because the
  mirror does not change persisted state.

### 7. Wrong vs Correct

Wrong:

```tsx
<DragOverlay>
  <div className="min-w-44 rounded-lg shadow-2xl">
    {node.type} / {node.name}
    {node.children?.slice(0, 6).map(renderApproximation)}
  </div>
</DragOverlay>
```

Correct:

```tsx
const snapshot =
  readStructuredPrototypeNodeDragMirrorCapture(event.active.data.current)?.() ?? null;
if (snapshot === null) {
  setInteractionError(t("prototype.structured.canvas.dragPreviewFailed"));
  return;
}
const sessionId = beginInteraction(/* move request */);
if (sessionId === null) return;
setActiveNodeDragMirror(snapshot);

<DragOverlay adjustScale={false}>
  {activeDrag?.kind === "node" && activeNodeDragMirror !== null ? (
    <StructuredPrototypeDragMirrorView snapshot={activeNodeDragMirror} />
  ) : null}
</DragOverlay>
```

---

## Scenario: Structured Prototype Page and Layer Navigator State

### 1. Scope / Trigger

- Trigger: changing the Studio page rail, recursive layer tree, tree keyboard
  behavior, expansion state, page CRUD, layer rename/visibility, or tree drag.
- Document mutations are durable commands; focus, expansion, inline-edit, and
  drop-indicator state are editor presentation and must not change the document
  hash.

### 2. Signatures

- Rows:
  `deriveStructuredPrototypeLayerRows(root) -> StructuredPrototypeLayerRowModel[]`.
- Expansion:
  `resolveStructuredPrototypeLayerExpandedNodeIds(rows, expanded, selectedNodeId, collapsed)`.
- Keyboard:
  `resolveStructuredPrototypeLayerTreeKeyboardAction(visibleRows, expanded, nodeId, key)`.
- Durable page actions: `addPageBatch`, `duplicatePageBatch`,
  `renamePageBatch`, `deletePageBatch`, and `reorderPageBatch`.
- Durable layer actions: `updateNodeNameBatch`, visibility
  `setNodeProperty`, and `moveNodeBatch`.

### 3. Contracts

- Derive a complete preorder hierarchy, including hidden nodes. Only rows whose
  ancestors are effectively expanded are rendered.
- Keep `expandedNodeIds`, `collapsedNodeIds`, focus, and inline rename state
  local and keyed by page root. None belongs in the structured document.
- Canvas selection automatically expands every ancestor needed to reveal the
  selected node. An explicit user collapse overrides that reveal for the
  current selection; changing selection invalidates the old collapse override
  and reveals the new path.
- Implement a real ARIA tree with one roving `tabIndex=0` treeitem. Arrow Up/Down
  move through visible rows; Home/End move to bounds; Right expands or enters a
  child; Left collapses or focuses the parent; Enter/Space selects; F2 renames;
  V toggles visibility.
- Child action buttons use `tabIndex=-1`; every operation remains available by
  pointer without adding five Tab stops per row.
- before/inside/after tree drops resolve through one typed projection. Invalid
  self, descendant, stale, and cross-parent Freeform drops leave the document
  unchanged and produce a visible error in desktop and mobile navigators.
- Every accepted page/layer mutation calls the shared Studio command controller
  once. Local state may select the created page or reveal a node only after the
  authoritative result identifies it.

### 4. Validation & Error Matrix

- Selected node is absent from the active root -> fall back focus to the root;
  do not invent a row.
- Explicitly collapsed ancestor with unchanged selection -> keep descendants
  hidden and focus on a visible row.
- Selection changes to another nested node -> discard the previous selection's
  collapse override and reveal the new ancestor path.
- Empty layer/page name -> inline visible error; no command.
- Invalid or unchanged drop -> visible refusal or no-op as classified; no
  document sequence advance.
- Accepted command returns no expected created/deleted identity -> visible
  failure; do not guess from a localized title.

### 5. Good/Base/Bad Cases

- Good: canvas selection of a fourth-level hidden node expands its ancestors,
  selects one treeitem, and keeps the node available for visibility changes.
- Good: a user collapses that ancestor, then selects another node; the new
  selection is revealed instead of inheriting stale suppression.
- Base: a one-level page root exposes one roving treeitem and no fake children.
- Bad: persist expanded IDs into the document and advance the command hash when
  the user clicks a chevron.
- Bad: put `tabIndex=0` on every row button or treat the tree as an unordered
  list with no Left/Right hierarchy semantics.

### 6. Tests Required

- Pure model tests cover complete preorder rows, hidden nodes, selection-driven
  expansion, explicit collapse override, selection change, and every keyboard
  key at first/middle/last rows.
- Drop tests cover before/inside/after, same-parent index adjustment, self,
  descendant, stale metadata, and cross-parent Freeform refusal.
- Source/component tests prove one roving treeitem, ARIA levels/selection,
  durable callbacks, local expansion, and mobile visible errors.
- Browser acceptance covers canvas/tree selection sync, F2 rename, V visibility,
  Undo/Redo, reload persistence, page CRUD/reorder, valid drops, and a refused
  descendant drop at desktop and mobile widths.

### 7. Wrong vs Correct

Wrong:

```tsx
{rows.map((row) => <button tabIndex={0}>{row.node.name}</button>)}
```

Correct:

```tsx
<div role="tree">
  {visibleRows.map((row) => (
    <div
      role="treeitem"
      aria-level={row.depth + 1}
      tabIndex={row.node.id === focusedNodeId ? 0 : -1}
      onKeyDown={(event) => dispatchTreeKeyboardAction(row, event)}
    />
  ))}
</div>
```
