# Structured Prototype Reusable Components

## Scenario: Detached Reusable Component Definitions

### 1. Scope / Trigger

- Trigger: changing structured-prototype component definitions, component save/insert/delete UI,
  component drag projection, document validation, AI edit scope, or external prototype Agent
  command capabilities.
- Components are structured document data. They are not stored HTML fragments and they do not
  create a second persistence or mutation path outside the command journal.

### 2. Signatures

Backend document and command contracts:

```python
class ComponentDefinitionV1(StrictPrototypeModel):
    id: EntityId
    key: TechnicalKey
    root: UINodeV1

class DefineComponentCommandV1(StrictPrototypeModel):
    kind: Literal["defineComponent"]
    key: TechnicalKey
    source_node: NodeRefV1

class RemoveComponentDefinitionCommandV1(StrictPrototypeModel):
    kind: Literal["removeComponentDefinition"]
    component_id: EntityId

class InstantiateComponentCommandV1(StrictPrototypeModel):
    kind: Literal["instantiateComponent"]
    component_id: EntityId
    parent: NodeRefV1
    index: int
    target_position: FreeformPositionV1 | None  # explicit only when supplied
```

`RestoreComponentDefinitionCommandV1` is an internal sealed-history command used by Undo/Redo; it
is not accepted from the public command batch union.

Frontend command builders:

```typescript
defineComponentBatch(key, nodeId)
removeComponentDefinitionBatch(componentId)
instantiateComponentBatch(componentId, parent, index, targetPosition?)

resolveStructuredPrototypeFreeformPointerPlacement({
  pointerClientX,
  pointerClientY,
  containerRect,
  containerClientLeft,
  containerClientTop,
  previewScale,
  nodeWidth,
  nodeHeight,
  containerWidth,
  containerHeight,
}) -> { x, y }
```

External Agent capability discovery includes exactly the public command kinds above in
`supportedCommandKinds` when write permission is present.

### 3. Contracts

- `document.componentDefinitions` owns at most 50 definitions. Definition keys are unique and all
  definition, node, Table row, and Freeform grid IDs share the document's global entity namespace.
- Define resolves its node reference after earlier commands in the same batch, then snapshots the
  resulting page subtree as a detached template. It recursively clones
  Stack, Grid, Form, and Freeform children, remaps every node ID, Table row ID, and Freeform grid
  ID, and clears only the cloned root's `layoutItem.position`.
- Definition and instance IDs are deterministic UUIDv5 values derived from `draftId`,
  `clientRequestId`, command identity, and source entity ID. The command result records the
  allocation map so replay, recovery, Undo, and Redo reproduce the same graph and hashes.
- Instantiate deep-clones the definition again with a fresh deterministic namespace. Instances
  are detached copies: later definition edits or deletion never mutate existing instances.
- Inserting into a Freeform parent requires an explicit `targetPosition`. Inserting into Stack,
  Grid, or Form uses normal container order and the instance root has no Freeform position.
- Studio click insertion targets the active page root when it is any supported container. Drag
  insertion uses the shared recursive drop projection, so nested Stack, Grid, Form, and Freeform
  targets use the same command path as ordinary node movement.
- Pointer insertion into Freeform treats the current pointer as the requested node top-left. Hover
  and pointer-up use one placement resolver against the actual persistent Freeform DOM container,
  frozen preview scale, border origin, and measured transient-node size. The resolver keeps the
  complete node in bounds through the normal Freeform move clamp. Keyboard insertion retains the
  deterministic fallback position; pointer-up refuses the command when container or node geometry
  cannot be measured instead of persisting a guessed position.
- The first hover may need one deterministic fallback only to mount the transient node. After that
  projection commits to the DOM, schedule one session-owned animation-frame reprojection when the
  node has just entered a new Freeform. Do not wait for another pointer movement, and do not loop
  retries once the transient node is already a direct child of that target.
- Component-definition nodes are template-only and cannot participate in navigation flows,
  runtime view bindings, or behavior-rule triggers. Define refuses a source subtree already
  referenced by that runtime graph instead of creating an instance that appears interactive but
  has no cloned behavior graph.
- Studio disables Save as component for page roots, multi-selection, and runtime-referenced
  subtrees. The backend repeats the runtime-reference check because AI and MCP are independent
  mutation boundaries.
- AI `defineComponent` and `removeComponentDefinition` require document scope.
  `instantiateComponent` is allowed in page or selection scope only when its existing target
  parent is inside that scope. Unknown command kinds remain fail-closed during scope validation.
- The external collaboration supported-command list, the Pydantic command union, the TypeScript
  command union, and command-builder tests must change together.

### 4. Validation & Error Matrix

| Condition                                                                 | Result                                                                |
| ------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| Duplicate definition key                                                  | `command_target_invalid`; append no command                           |
| Missing source node or component ID                                       | `command_target_missing`; append no command                           |
| Duplicate allocation key, entity ID collision, or invalid cloned document | Deterministic command validation error; append no command             |
| Source subtree is referenced by a flow, view binding, or behavior rule    | `command_target_in_use`; append no command                            |
| Target is not a container or index is outside its child range             | `command_target_invalid` / `command_index_invalid`; append no command |
| Freeform target omits `targetPosition`                                    | Frontend builder refuses; backend returns `command_target_invalid`    |
| Pointer-up lacks current pointer, direct target container, or node size   | Cancel drag, show invalid-drop feedback, append no command            |
| Definition node is targeted by a runtime rule/view binding or flow        | Document validation fails before persistence/rendering                |
| Define/remove requested from page, selection, or flow AI scope            | `scope_violation`; no proposal is accepted                            |
| Unsupported command reaches narrow AI scope validation                    | `scope_validation_unsupported`; fail closed                           |

### 5. Good/Base/Bad Cases

- Good: save a nested Grid containing a Table, then insert it twice into Freeform at two explicit
  positions. Every node, row, and grid ID differs across source, definition, and both instances;
  reload and replay preserve the same document hash.
- Good: drag a component into a nested Freeform at 75% zoom. The current collision pointer is
  converted from the target container's scaled content origin, and the complete rendered instance
  is clamped inside that Freeform before `targetPosition` is encoded.
- Base: save a static Button group, insert it into a Stack, delete the definition, and Undo. The
  existing instance remains unchanged and Undo restores the definition at its original index.
- Base: use KeyboardSensor to insert into Freeform; the deterministic index-based fallback remains
  available because no pointer geometry exists by design.
- Bad: copy only node IDs while preserving Table row IDs, causing global ID collisions on the
  second instance.
- Bad: preserve a Freeform source position in the definition root, causing click inserts to
  overlap or non-Freeform inserts to retain irrelevant geometry.
- Bad: allow a runtime-bound subtree to be saved while cloning only UI nodes; the instance looks
  interactive but rules still target the source subtree.
- Bad: let a page-scoped AI command remove a document-global component definition.
- Bad: use `event.over.rect` or the pointerdown coordinates as the Freeform position. `over` may be
  a child or slot, and the initial pointer is not the final drop location.

### 6. Tests Required

- Backend command tests cover define/instantiate/remove plus Undo/Redo, deterministic allocation,
  nested Grid/Form/Freeform cloning, Table row and Freeform grid remapping, duplicate/missing
  targets, index errors, global ID collisions, and source runtime-reference refusal.
- Backend serialization tests prove explicit `targetPosition` presence is preserved and Freeform
  insertion without it is refused.
- AI service tests prove define/remove are document-only, instantiate checks only the target
  parent against page/selection scope, and unknown commands remain fail-closed.
- External collaboration tests assert all three public command kinds are advertised and validated
  through the normal proposal path.
- Frontend builder tests cover Stack/Grid/Form insertion, required Freeform position, and removal.
- Frontend source/interaction tests prove recursive component previews, nested drop projection,
  definition deletion, Inspector Save as component gates, scaled pointer placement, boundary
  clamping, drag-move reprojection, keyboard fallback, and missing-geometry refusal.
- Renderer codec tests validate definitions recursively while published page HTML renders only
  instantiated page nodes.

### 7. Wrong vs Correct

Wrong:

```python
# Reuses source IDs and keeps the source Freeform position.
definition = ComponentDefinitionV1(id=new_id, key=key, root=source)
```

Correct:

```python
root = _clone_subtree_with_fresh_ids(source, deterministic_clone_id)
root = root.model_copy(
    update={"layout_item": root.layout_item.model_copy(update={"position": None})}
)
definition = ComponentDefinitionV1(id=definition_id, key=key, root=root)
```

Wrong:

```typescript
// A Freeform insert without persisted geometry cannot replay faithfully.
instantiateComponentBatch(componentId, freeform, index);
```

Correct:

```typescript
instantiateComponentBatch(componentId, freeform, index, { x: "48", y: "72" });
```

Wrong:

```typescript
const targetPosition = {
  x: String(event.over.rect.left),
  y: String(event.over.rect.top),
};
```

Correct:

```typescript
const targetPosition = resolveStructuredPrototypeFreeformPointerPlacement({
  pointerClientX: currentPointer.x,
  pointerClientY: currentPointer.y,
  containerRect: freeform.getBoundingClientRect(),
  containerClientLeft: freeform.clientLeft,
  containerClientTop: freeform.clientTop,
  previewScale: frozenPreviewScale,
  nodeWidth: transientNode.offsetWidth,
  nodeHeight: transientNode.offsetHeight,
  containerWidth: freeform.clientWidth,
  containerHeight: freeform.clientHeight,
});
```
