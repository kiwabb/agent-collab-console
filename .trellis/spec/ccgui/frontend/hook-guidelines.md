# Hook Guidelines

> How hooks are used in this project.

---

## Overview

<!--
Document your project's hook conventions here.

Questions to answer:
- What custom hooks do you have?
- How do you handle data fetching?
- What are the naming conventions?
- How do you share stateful logic?
-->

(To be filled by the team)

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

<!-- Hook naming rules (use*, etc.) -->

(To be filled by the team)

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
