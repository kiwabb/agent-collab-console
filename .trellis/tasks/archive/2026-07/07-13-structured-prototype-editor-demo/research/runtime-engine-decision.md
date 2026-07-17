# Prototype Runtime Engine Decision

## Local Dependency Check

The current frontend has Zustand, Immer, and React Flow. It does not have XState, JSON Logic, Robot, or another workflow/statechart engine.

- Zustand owns UI/application state containers; it is not a rule or transition engine.
- Immer provides immutable update ergonomics; it does not define event ordering, guards, or statechart semantics.
- React Flow renders/edit graphs; its edges and node positions must not become executable authority.

## Decision

Use exactly pinned XState `5.32.4` as the event/transition kernel inside the shared TypeScript `prototype-runtime-core` package. A future XState version change must also change `runtimeCoreVersion` and its compatibility fixtures.

The product still owns a strict domain AST for values, predicates, effects, forms, mock entities, roles, and scenarios. A controlled compiler maps this AST to allowlisted pure XState guards/actions. Prototype documents never contain JavaScript functions or arbitrary XState config.

## Persistence Boundary

Do not persist XState private snapshots. Persist only the product-owned `PrototypeRuntimeStateV1`, semantic event batches, transition reports, state hashes, runtime-core bundle hash, and exact XState package version.

This keeps durable state stable across library upgrades while using a proven engine for event sequencing and transition execution.

## Excluded XState Features

- Invoked services and network actors
- Delayed transitions and real system clocks
- Asynchronous actions
- User-provided guards/actions
- Persisted internal actor snapshots

## Verification Gate

Before implementation proceeds beyond the runtime core spike:

1. Browser and pinned Node worker must run the same compiled machine fixtures.
2. Both surfaces must produce identical domain transition/state hashes.
3. XState internal metadata must not appear in canonical state objects.
4. Upgrading the exact XState version must require a runtime-core version change and compatibility fixtures.
