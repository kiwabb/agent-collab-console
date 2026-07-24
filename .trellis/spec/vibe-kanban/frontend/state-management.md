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

## Scenario: Project Conductor Initial Load and Refresh Failure States

### 1. Scope / Trigger

- Trigger: changing the Project Conductor page, its state API client, its
  execution-loop dock, or the backend state response consumed by the page.
- The page is operational UI: an unavailable or mismatched endpoint must be
  visible, not presented as a legitimate all-zero project state.

### 2. Signatures

- API client:
  `getProjectConductorState(projectId: string) -> Promise<ProjectConductorState>`.
- Endpoint:
  `GET /api/codex/projects/{encodeURIComponent(projectId)}/conductor/state`.
- Component state:
  `state: ProjectConductorState | null`, `loading: boolean`, and
  `loadError: string | null`.
- Loop action:
  `startProjectConductorLoop(projectId, prompt?) -> ProjectConductorLoopResult`.

### 3. Contracts

- Initial mount starts with `loading=true` and `state=null`. Until a real state
  response arrives, render a loading surface; do not render metric cards with
  fabricated zero defaults.
- Initial load failure keeps `state=null`, renders a visible error surface with
  technical detail and Retry, and may also emit a toast.
- A later refresh failure preserves the last valid `state`, renders a stale-data
  warning plus Retry, and leaves the existing memory/task data visible.
- Every load and mutation result is owned by the `projectId` and request
  generation that started it. Switching projects invalidates earlier requests;
  late responses, errors, loading flags, answers, and loop history from the old
  project must not settle the new page.
- A successful retry clears `loadError` when the request starts and replaces
  state atomically with the returned typed response.
- Project IDs are URL encoded and the route is `/conductor/state`; the removed
  `/conductor-state` spelling is not compatible.
- The execution loop consumes the returned POST result directly. It must not
  open an `EventSource` for an endpoint the backend does not implement.
- Long event, memory, and tool text uses progressive disclosure; the initial
  page shows recent readable content without expanding the entire history.

### 4. Validation & Error Matrix

- Initial GET 404/500/network failure -> full visible error + Retry; no metrics.
- Refresh failure after a valid response -> stale-state banner + Retry; previous
  metrics and memory remain.
- Old-project request resolves after navigation -> ignore it completely; the
  current project's loading/error/data state remains authoritative.
- Retry success -> error disappears and the new response is rendered.
- Missing state response -> schedule-review action remains disabled.
- Loop POST failure -> visible action error; no fabricated execution event.
- Long content -> collapsed preview with an explicit expand/collapse control.

### 5. Good/Base/Bad Cases

- Good: the backend route drifts and the page names the failed request instead
  of showing four zeros.
- Good: a transient refresh error leaves the prior project memory readable.
- Base: an empty but successfully loaded project renders genuine zero metrics
  and explicit empty-memory copy.
- Bad: `state?.hot_tokens ?? 0` is rendered before the first response.
- Bad: `.catch(() => setState(null))` destroys valid data.
- Bad: opening an SSE connection to `/conductor/stream` when no such backend
  route exists.

### 6. Tests Required

- API test asserts the encoded `/conductor/state` URL and POST paths/bodies.
- Source/component contract asserts initial failures are visible, stale state is
  retained on refresh failure, and scheduled actions require loaded state.
- Source/component contract asserts request-generation and active-project
  guards exist, and the loop dock remounts by project identity.
- Presentation helper tests cover collapse thresholds, reveal bounds, hot-event
  rendering, and malformed tool-event rejection.
- i18n parity test asserts every Project Conductor key exists in both locales.
- Browser verification loads the authenticated route, refreshes it, checks no
  horizontal overflow, and confirms no console errors or business alerts.

### 7. Wrong vs Correct

Wrong:

```tsx
const [state, setState] = useState<ProjectConductorState | null>(null);
getProjectConductorState(id).then(setState).catch(() => {});
return <Metric value={state?.hot_tokens ?? 0} />;
```

Correct:

```tsx
if (loading && !state) return <InitialLoading />;
if (loadError && !state) return <LoadError retry={load} detail={loadError} />;
return <ConductorState state={state} staleError={loadError} retry={load} />;
```

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
