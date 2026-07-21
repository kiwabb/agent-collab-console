# Structured Prototype Drag Placement

> Executable frontend contract for pointer-faithful drops into Freeform containers and for
> remeasuring transient nodes after React mounts the projected DOM.

## Scenario: Pointer-Faithful Freeform Drop Placement

### 1. Scope / Trigger

- Trigger: changing dnd-kit collision handling, pointer capture, hover projection, transient node
  registration, or node placement inside a structured-prototype `Freeform` container.
- Drop projection is transient editor state. The accepted typed command remains the only durable
  mutation and must advance the document sequence exactly once.

### 2. Signatures

```typescript
updateStructuredPrototypeActiveDragPointerState(current, input)
  -> StructuredPrototypeActiveDragPointerState

resolveStructuredPrototypeFreeformPointerPlacement(input)
  -> { x: number; y: number }

shouldScheduleStructuredPrototypeFreeformRegistrationRemeasure(input)
  -> boolean

onNodeElementRegistered({ nodeId, parentId, element }) -> void
```

The pointer state is interaction-session scoped and stores both the latest client coordinates and
the client-space grab offset frozen from the first pointer collision rectangle.

### 3. Contracts

- The first pointer collision for an interaction freezes
  `grabOffsetClient = pointerCoordinates - collisionRect.topLeft`. Later collisions in the same
  session update only the coordinates. A new session captures a new offset.
- Resolve the dragged node's client-space top-left as `pointer - grabOffsetClient`, then convert it
  through the preview scale exactly once. Do not treat the pointer itself as the node origin.
- Keyboard dragging has no pointer/grab offset and keeps the deterministic Freeform fallback.
- A palette or component node may need one fallback hover projection before its real DOM exists.
  Mark that exact node/parent pair pending and remeasure only after its ref is registered.
- DOM ownership is the direct parent relation:
  `element.parentElement?.dataset.containerId === pending.parentId`. Never use `offsetParent` as
  ownership evidence; transforms and positioned/contained layouts can make it `null` or point at a
  different containing block even when the node is the container's direct DOM child.
- A registration may schedule remeasurement only when the active projection object, interaction
  session, projection owner, expected node ID, latest target parent, pending node/parent, registered
  node/parent, and direct DOM parent all agree.
- Registration schedules the normal single projection RAF. Do not add a blind second RAF: frame
  count is not proof that React mounted the projected node, and it can race a newer target/session.
- Hover may show the deterministic fallback while geometry is unavailable. Pointer drop without
  valid registered geometry fails closed and commits no fallback coordinate.

### 4. Validation & Error Matrix

| Condition | Result |
|---|---|
| Same pointer session, later collision | Preserve the original grab offset; update coordinates |
| New pointer session | Capture a new grab offset |
| Keyboard sensor | Use deterministic fallback placement |
| Projected transient node not mounted during hover | Publish fallback hover and wait for registration |
| Registration belongs to a stale session/projection/node/parent | Ignore it; schedule no RAF |
| Direct DOM parent does not own the registered node | Ignore it; schedule no RAF |
| Geometry is still unavailable at pointer drop | Refuse the drop; append no command |
| Non-finite coordinate, scale, size, or container measurement | Reject through the geometry helper |

### 5. Good/Base/Bad Cases

- Good: dragging an existing Stack Text into a Freeform preserves the point held by the pointer;
  persisted top-left differs from the measured expected top-left by less than one client pixel.
- Good: a palette node first renders at a deterministic hover fallback, registers under the target
  Freeform, then reprojects from the same session's pointer/grab offset before drop.
- Base: keyboard insertion uses the deterministic indexed fallback and never waits for pointer
  geometry.
- Bad: test `node.offsetParent === container`; a valid transformed preview can report
  `offsetParent === null` and permanently leave the node at the fallback position.
- Bad: queue two RAF callbacks after hover and assume the transient node must exist by then.

### 6. Tests Required

- Pure pointer-state tests prove first-collision offset capture, same-session preservation,
  new-session reset, and keyboard state.
- Pure geometry tests prove `pointer - grabOffset` conversion at multiple preview scales,
  container borders, nested canvas origins, bounds clamping, and invalid finite values.
- Registration-gate tests vary every ownership/session field independently and prove stale or
  mismatched registrations cannot schedule remeasurement.
- Source contracts prove ref-driven registration, direct `parentElement` ownership, the absence of
  `offsetParent` ownership checks, and use of the shared projection scheduler rather than a second
  blind RAF.
- Real-browser acceptance drags an existing auto-layout node into Freeform, measures expected and
  rendered top-left, verifies one durable sequence advance and persisted coordinates, then Undo
  must restore the pre-drag document hash.

### 7. Wrong vs Correct

Wrong:

```typescript
requestAnimationFrame(() => requestAnimationFrame(remeasure));
if (node.offsetParent !== container) return defaultFreeformPosition(index);
const position = clientPointToCanvas(pointerCoordinates);
```

Correct:

```typescript
const nodeTopLeft = {
  x: pointerCoordinates.x - grabOffsetClient.x,
  y: pointerCoordinates.y - grabOffsetClient.y,
};

if (element.parentElement?.dataset.containerId !== pending.parentId) return;
if (!sameInteractionAndProjectionOwner(input)) return;
scheduleActiveMoveProjection(session);
```
