# Hook Guidelines

> How hooks are used in this project.

---

## Overview

The ccgui frontend has a small set of cross-feature hooks in
`frontend/src/hooks/` (notably `useBusEventEffect` for WS event
subscription and `useExecutionProcessesContext` for live process
state), plus a growing number of feature-local hooks next to the
component that owns them. Naming follows the standard
`useXxx` prefix; data fetching is a small `async` helper in the
hook body, with the response stored in `useState`; stateful logic
is shared through refs (for imperative handles) or named-tuple
returns (for declarative state).

---

## Custom Hook Patterns

<!-- How to create and structure custom hooks -->

### Pattern: WebSocket lifecycle hooks

**What**: WebSocket hooks that support reconnects should keep socket, timer, retry, and completion state in refs, and expose UI state through React state.

**Why**: The socket lifecycle is imperative while the UI is declarative. Refs prevent reconnect timers and event handlers from capturing stale render state or retriggering effects unnecessarily.

**Example**:
```tsx
const wsRef = useRef<WebSocket | null>(null);
const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
const finishedRef = useRef(false);
```

**Required cleanup**: On effect cleanup, clear pending timers, detach socket event handlers, close the socket, and reset `wsRef.current` to `null`.

---

## Data Fetching

<!-- How data fetching is handled (React Query, SWR, etc.) -->

### Pattern: Split fetch completion from derived detail rebuilds

**What**: When a hook fetches base records and also derives a combined view from external live state, store the fetched records first, then rebuild the derived view in a separate effect.

**Why**: Building derived detail inside the fetch callback can capture stale external state and creates noisy dependency arrays. A second effect that depends on both the fetched records and live state keeps the dataflow explicit.

**Correct**:
```tsx
useEffect(() => {
  getMessages(taskId).then(setTaskMessages);
}, [taskId]);

useEffect(() => {
  setDetail(buildTaskConversationDetail(taskMessages, executionProcesses));
}, [taskMessages, executionProcesses]);
```

---

## Naming Conventions

- **Cross-feature hook**: `useXxx.ts` in `frontend/src/hooks/`,
  exported and consumed via `@/hooks/useXxx`. The hook is the
  only public surface; the underlying provider (if any) is
  detail.
- **Feature-local hook**: `useXxx.ts` next to the component
  that owns it (`frontend/src/features/<area>/components/`).
  Promoted to `frontend/src/hooks/` only when a second feature
  imports it.
- **Test file**: `<hook-stem>.test.ts` in `frontend/tests/`,
  using `node:test` (not Jest, not Vitest). Coverage focuses on
  the hook's contract — return shape, ref-isolation of
  imperative handles, cleanup behavior.
- **Return shape**: named tuple `{ data, loading, refresh }` for
  data hooks; `{ ref, value }` for imperative handles; bare
  value for trivial hooks.
- **Verb naming**: prefer the effect over the noun —
  `useIssueBudget` (the value) over `useBudgetState` (the bag).
  This keeps the consumer's call site readable:
  `const { budget, loading, refresh } = useIssueBudget(id, active)`.

---

## Common Mistakes

<!-- Hook-related mistakes your team has made -->

### Mistake: Self-referential `useCallback` dependencies

**Wrong**: Adding `connect` to the dependency array of the `connect` callback itself, directly or indirectly.

```tsx
const connect = useCallback(() => {
  ...
}, [processId, connect]);
```

This can pass casual review but fails TypeScript with self-reference errors such as `Block-scoped variable 'connect' used before its declaration`.

**Correct**: Keep `connect` dependent only on the values it uses, and use a ref when another stable callback or timer needs to call the latest `connect`.

```tsx
const connectRef = useRef<() => void>(() => {});

const scheduleReconnect = useCallback(() => {
  retryTimerRef.current = setTimeout(() => {
    connectRef.current();
  }, delay);
}, []);

const connect = useCallback(() => {
  ...
  scheduleReconnect();
}, [processId, scheduleReconnect]);

useEffect(() => {
  connectRef.current = connect;
}, [connect]);
```

**Check**: After changing hook dependencies, run both `npm run lint` and `npx tsc --noEmit --pretty false`. React hook lint can be green while TypeScript still catches a closure cycle.
