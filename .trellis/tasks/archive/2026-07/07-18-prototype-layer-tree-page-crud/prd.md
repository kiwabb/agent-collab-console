# Penpot-style prototype layer tree and page CRUD

## Goal

Turn the prototype Studio's left rail into a real document navigator. Users must be able to inspect
and manipulate the active page's node hierarchy and manage pages without leaving the structured,
journaled document model. This is the first platform milestone after faithful canvas dragging.

## What I Already Know

* The document already stores recursive node trees for each page.
* Canvas selection, node removal, visibility changes, nested canvas drag-and-drop, page reorder,
  Undo/Redo, recovery, and publication already use durable structured commands.
* The left rail currently renders only a flat sortable page list.
* The command contract can reorder pages but cannot add, duplicate, rename, or remove them.
* `componentDefinitions` exist in the schema, but component instances are not part of this task.

## Requirements

### Document navigator

* The left workspace region exposes separate Pages and Layers sections without nesting decorative
  cards.
* The Layers section renders the complete active-page node hierarchy, including hidden nodes.
* Container nodes can be expanded and collapsed. Expansion is local editor state and does not alter
  the document hash.
* Clicking a layer selects the same node on the canvas; canvas selection reveals and highlights the
  corresponding layer.
* A layer can be renamed inline. Enter commits, Escape cancels, and an empty name is rejected with a
  visible error.
* A layer visibility control persists through the existing structured visibility command.
* Layer drag-and-drop supports deterministic before, after, and inside-container destinations and
  persists through the existing node move command.
* Invalid hierarchy drops are visibly refused. A node cannot be moved into itself or a descendant.
* Reordering within a Freeform preserves the node's canonical position. Cross-parent tree drops into
  a Freeform are refused in this milestone because a layer-tree pointer has no canvas coordinate.
* Deleting a selected layer continues to work from the keyboard and Inspector and immediately
  updates the layer tree.

### Page management

* Users can add a blank page, duplicate the active page, rename a page, and delete a page from the
  page rail.
* A blank page uses the active/default viewport and a Freeform root so palette and canvas placement
  work immediately.
* Generated page keys and routes are deterministic and unique within the document.
* Renaming a page updates its title and the labels of navigation items targeting that page; its
  route remains stable.
* Duplicating a page creates new IDs for the page, every node, Freeform grid, and Table row; copies
  node-bound view bindings and trigger rules using remapped IDs; and duplicates every navigation
  item targeting the source page.
* Duplicated outgoing navigation keeps its original destination. A self-navigation rule is remapped
  to the duplicated page.
* Deleting the final remaining page is refused.
* Deleting a page used as a runtime Scenario start page is refused and names the blocking Scenario.
* Deleting a page removes its navigation items, node-bound view bindings, trigger rules, flow
  records owned by those rules, and the runtime page entry.
* Deletion is refused when a rule triggered outside the page navigates to the page. The UI names the
  blocking rule instead of silently weakening business behavior.
* If the active page is deleted, the nearest surviving page becomes active.

### Durable command contract

* Page create, duplicate, rename, and delete are first-class structured commands, not client-side
  document replacement.
* `runtime.pageIds` always equals the ordered `pages[].id` list after create, duplicate, delete, and
  existing page reorder commands.
* Every accepted layer or page operation advances the document hash and command journal once.
* Undo, Redo, request recovery, checkpointing, AI command application, replay, and publication all
  observe the same result.
* Contract validation is fail-closed for stale hashes, duplicate keys/routes, invalid references,
  last-page deletion, and externally referenced page deletion.
* Server-generated IDs remain deterministic under idempotent retry and replay.

## Acceptance Criteria

* [x] The active page's complete hierarchy is visible and keyboard-accessible in the left rail.
* [x] Canvas and layer-tree selection remain synchronized for nested and hidden nodes.
* [x] Renaming and hiding a node persist, Undo, Redo, and survive a reload.
* [x] Valid same-parent and cross-container layer drops persist with an accurate drop indicator.
* [x] Invalid self/descendant and cross-parent Freeform drops show a visible refusal.
* [x] Add page creates a selectable, editable, uniquely routed Freeform page.
* [x] Duplicate page preserves visuals and remaps node-bound runtime references without duplicate IDs.
* [x] Rename page synchronizes page and navigation labels while preserving route identity.
* [x] Delete page performs the documented cascade, refuses the final page, and refuses Scenario
      start-page or external inbound navigation references.
* [x] Page order and `runtime.pageIds` remain byte-for-byte aligned through command, inverse, replay,
      Undo, and Redo.
* [x] Page CRUD and layer operations pass Undo/Redo and operation-recovery tests.
* [x] Browser QA covers nested layer selection, inline rename, visibility, hierarchy drag, all four
      page actions, Undo, and reload persistence.

## Definition of Done

* Focused frontend and backend tests cover command validation, deterministic replay, UI derivation,
  drag projection, and error states.
* TypeScript, targeted ESLint/Prettier, and focused pytest checks pass.
* Browser QA verifies the integrated Studio at desktop and mobile widths.
* New user-visible copy exists in both zh-CN and en-US dictionaries.
* Any reusable command or tree-navigation contract learned here is recorded in Trellis specs.

## Decision (ADR-lite)

**Context**: Page and layer changes could be implemented by mutating the draft JSON in the browser,
but that would bypass observability, deterministic replay, AI editing, and recovery.

**Decision**: Extend the existing structured command language. Keep tree expansion and temporary
rename state local, but persist every document change through the same backend command journal.

**Consequences**: The milestone touches frontend, command codec/domain logic, API validation, replay,
and tests. It takes longer than a UI-only layer panel but preserves the product's core requirement
that every step is observable and reproducible.

## Expansion Sweep

* Future evolution: the navigator structure must leave room for lock state, components/instances,
  z-order commands, search, and multi-selection without storing view-only expansion state.
* Related scenarios: Claude UI Engineer proposals and manual edits must converge on the same command
  contract; published previews must never observe editor-only partial state.
* Failure and edge cases: stale hashes, idempotent retries, last-page deletion, inbound navigation,
  nested self-drops, hidden-node selection, mobile drawer interaction, and active-page fallback are
  part of this milestone.

## Out of Scope

* Persisted layer locking, z-index controls, layer search, and multi-layer tree drag.
* Component instances, overrides, variants, or shared libraries.
* Rotation, vector shapes, image asset support, masks, boolean operations, or advanced styling.
* Editing page routes, viewports, shell settings, or design tokens in the navigator.
* Cross-parent layer-tree drops into Freeform containers.
* Real-time multi-user collaboration, comments, and presence.

## Technical Notes

* Primary frontend entry points:
  * `frontend/src/features/prototype/structured/StructuredPrototypePageRail.tsx`
  * `frontend/src/features/prototype/structured/StructuredPrototypeStudioPage.tsx`
  * `frontend/src/features/prototype/structured/structuredPrototypeCommands.ts`
  * `frontend/src/features/prototype/structured/types.ts`
* The server command interpreter and renderer codec must remain the schema authorities; the browser
  must not synthesize accepted document JSON independently.
* Penpot references used for interaction vocabulary:
  * https://help.penpot.app/user-guide/designing/workspace-basics/
  * https://help.penpot.app/user-guide/designing/layers/
