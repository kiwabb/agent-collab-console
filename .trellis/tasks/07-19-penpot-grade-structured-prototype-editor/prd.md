# Penpot-grade Structured Prototype Editor

## Goal

Deliver a domain-agnostic structured business-prototype editor with Penpot-grade canvas ergonomics
without turning the product into a Penpot clone. Preserve semantic DOM rendering, executable
runtime behavior, Claude UI Engineer editing, typed document commands, deterministic replay,
checkpoint recovery, and publication while making direct manipulation complete and predictable.

## Product Boundary

* Penpot is the interaction and geometry reference, not the storage or rendering architecture.
* Runnable Buttons, Inputs, Tables, Forms, and business flows remain semantic DOM and structured
  document nodes rather than an SVG-only scene graph.
* Auto-layout containers keep deterministic Stack/Grid/Form semantics. Free positioning is explicit
  through Freeform or an intentional absolute-position mode; the editor must not store cosmetic
  coordinates that the renderer ignores.
* Every persistent change uses the existing typed command journal. Transient pointer previews never
  create a second mutation path.
* Project evidence and confirmed blueprints remain the only source of business scope. No fixed
  admin, procurement, approval, or other domain template may enter production generation.

## Existing Baseline

* Multi-page structured documents, shared navigation and tokens, runtime flows, AI proposals,
  checkpoints, replay, recovery, and publication already exist.
* Page CRUD, recursive Layers, visibility, rename, deterministic before/inside/after movement,
  Undo/Redo, deletion, and reload persistence already exist.
* Fit/numeric zoom, pointer-anchored wheel zoom, pan, Marquee, Freeform movement, group alignment and
  distribution, eight-direction Freeform resize, snapping, spacing guides, and faithful DOM drag
  mirrors already exist.
* Selection movement now uses invisible 10-client-pixel edge hit bands with no visible Grip. Active
  movement hides selection chrome and resize handles while keeping activators and snap guides alive.

## Requirements

### 1. Unified Selection and Transform Model

* One selection model supports click, Shift toggle, Marquee, nested selection reveal, overlap
  cycling, primary selection, and deterministic multi-selection ordering.
* Freeform nodes support move, eight-direction resize, rotation, Shift aspect/axis constraints, Alt
  center transforms, Escape cancellation, and exact final-frame commit.
* Auto-layout children support reorder, before/inside/after reparenting, sizing and constraints;
  users can intentionally switch a supported child between auto and absolute positioning without
  creating invalid layout state.
* Multi-selection move, resize, rotate, align, distribute, duplicate, delete, lock, group, and
  ungroup operations are atomic typed command batches with one undo item.
* Transform controls remain constant in client-pixel size across Fit, 75%, 100%, 125%, 200%, and
  mobile zoom.

### 2. Layers and Stacking

* Layers expose persisted lock state, visibility, z-order, group hierarchy, component-instance
  identity, and search/filtering without storing editor-only expansion state.
* Bring forward/backward and move to front/back are deterministic commands and produce the same
  canvas, layer-tree, replay, and published result.
* Locked nodes remain selectable for inspection but reject canvas transforms, layer movement,
  deletion, and AI mutation unless explicitly unlocked.
* Invalid self/descendant/group/instance moves fail closed with a visible reason.

### 3. Precision Canvas

* Horizontal and vertical rulers reflect the canonical canvas coordinate system at every zoom.
* Users can create, move, lock, hide, and delete persistent guides from rulers.
* Alignment, equal-spacing, grid, guide, container-edge, and center snapping share one deterministic
  arbitration contract and visible metadata.
* Inspector constraints and auto-layout sizing match the renderer and published runtime exactly.
* Overlapping shapes can be selected deterministically without repeatedly moving the top shape.

### 4. Direct Canvas Editing

* Double-click edits Text content in place with commit/cancel semantics and no layout jump.
* Button labels, Input labels/placeholders, and other short semantic copy can be edited in place.
* Static Table headers and cells can be edited in place; runtime-bound cells expose their binding
  instead of pretending the fixture value is freely editable.
* Direct edits and Inspector edits produce the same typed command shape, validation behavior,
  document hash, Undo/Redo result, AI visibility, and recovery evidence.

### 5. Components, Assets, and Vector Primitives

* Component definitions can be created from selected nodes, instantiated across pages, renamed,
  updated, detached, and deleted with explicit dependency rules.
* Instances preserve a master reference plus typed overrides; master updates propagate without
  overwriting valid instance overrides.
* A project asset library manages reusable images, icons, colors, text styles, and component
  definitions with stable IDs and reference validation.
* Essential vector primitives include rectangle, ellipse, line, arrow, and path; they support fill,
  stroke, opacity, transform, grouping, selection, snapping, and publication.
* Assets and vectors remain bounded structured data. Arbitrary executable SVG/HTML/script content is
  rejected at the document boundary.

### 6. Collaboration and History

* Multiple users can observe presence, selections, and comments without changing the document hash.
* Concurrent persistent edits use explicit document-head conflict handling; no last-write-wins
  overwrite may silently discard a command.
* Comments anchor to page/node identities and survive reorder, rename, checkpoint, and publication
  without becoming runtime content.
* History can name checkpoints, inspect command authors, restore a prior version through a new
  auditable command, and reproduce the same document hash.

### 7. AI and Observability

* Claude UI Engineer can propose every supported manual command, including transforms, grouping,
  component operations, direct copy edits, guides, and constraints.
* AI proposals show a structured preview and are applied or rejected explicitly; Claude never writes
  accepted document JSON directly.
* Pointer gestures, command validation, AI proposals, conflicts, checkpoints, replay, runtime, and
  publication remain observable and reproducible end to end.

## Acceptance Criteria

* [ ] A user can manipulate every supported node without a visible drag icon and without controls
      blocking nested selection or runtime Preview interaction.
* [ ] Freeform and auto-layout transforms have explicit, deterministic semantics and complete
      keyboard/modifier behavior.
* [ ] Multi-selection, rotation, lock, z-order, group/ungroup, overlap cycling, and layer search pass
      command, inverse, replay, recovery, and browser tests.
* [ ] Rulers, persistent guides, snapping, spacing, grids, and constraints remain geometrically
      correct from Fit through 200% zoom.
* [ ] Text, semantic labels, and supported Table data are editable directly on the canvas and remain
      identical after reload, Undo/Redo, AI apply, and publication.
* [ ] Components and instances propagate master changes while preserving typed overrides and
      refusing broken references.
* [ ] Image/style assets and bounded vector primitives render identically in Studio and published
      runtime.
* [ ] Two browser sessions can show presence/comments and resolve concurrent document edits without
      silent data loss.
* [ ] A 1,000-node multi-page document remains usable for select, pan, zoom, move, resize, layer
      search, Undo, and reload under an explicit performance budget.
* [ ] The complete `admin-demo` workflow and a second non-admin fixture pass generation, editing,
      AI modification, runtime replay, recovery, and publication acceptance.

## Delivery Milestones

1. **Transform foundation**: complete selection/hit testing, modifier semantics, rotation, explicit
   auto/absolute positioning, and atomic multi-selection transforms.
2. **Layer operations**: lock, z-order, group/ungroup, overlap cycling, and layer search.
3. **Precision system**: rulers, persistent guides, unified snapping, and constraints.
4. **Direct editing**: in-canvas Text, semantic copy, and Table editing through shared commands.
5. **Reusable design system**: component definitions, instances, overrides, styles, image assets,
   and bounded vector primitives.
6. **Collaboration and scale**: presence, comments, conflict-safe edits, history UX, and performance
   hardening.
7. **End-to-end parity audit**: desktop/mobile browser matrices, multi-session verification,
   deterministic replay, AI parity, publication, and both project fixtures.

## Definition of Done

* Each milestone has executable command/schema contracts, focused unit/integration tests, browser
  interaction and visual evidence, and updated Trellis specs.
* Frontend TypeScript, scoped lint/format, relevant backend tests, deterministic replay, Undo/Redo,
  recovery, and publication checks pass after every persistent-schema change.
* No milestone is considered complete from source assertions alone; runtime behavior and rendered
  geometry must be measured in a real browser.
* Existing valid documents either remain readable or a deliberate no-migration schema break is
  recorded before implementation. This program currently assumes no historical migration burden,
  matching the user's earlier decision.

## Decision (ADR-lite)

**Context**: Penpot provides mature design interaction patterns, but this product also requires
runnable business DOM, AI editing, workflow runtime, and reproducible structured commands.

**Decision**: Reimplement Penpot interaction contracts on top of the existing structured document,
DOM renderer, React controls layer, and command journal. Use explicit layout modes rather than
making every node cosmetically absolute. Deliver in vertically complete milestones instead of a
parallel replacement editor.

**Consequences**: Geometry, command, renderer, inspector, AI, persistence, replay, and browser tests
must evolve together. The result will feel Penpot-grade for supported business-prototype objects but
will not claim Penpot file-format or full vector-editor compatibility.

**Confirmed scope**: The user's "do all of it" includes every delivery milestone in this PRD. The
milestones sequence delivery and verification; they do not redefine the final objective to a smaller
subset.

## Out of Scope

* Copying Penpot MPL source or adopting its ClojureScript/Potok/WASM architecture wholesale.
* Replacing runnable semantic DOM with a screenshot-only or SVG-only canvas.
* Penpot/Figma native file compatibility.
* Arbitrary scripts, executable SVG, unbounded expressions, or direct accepted-document writes by
  Claude.
* Production application source-code generation from the prototype document.

## Research References

* `../archive/2026-07/07-13-structured-prototype-editor-demo/final-goal.md`
* `../archive/2026-07/07-13-structured-prototype-editor-demo/research/penpot-editor-interaction-patterns.md`
* `../07-18-penpot-faithful-prototype-drag-preview/research/penpot-drag-visual-parity.md`
* `research/transform-model-audit.md`
* `research/selection-layer-stack-audit.md`
* `research/inline-assets-collaboration-audit.md`

## Technical Notes

* Existing runtime and persisted schema authorities live in frontend structured-prototype types and
  commands plus backend structured-prototype domain/contracts/services.
* The first implementation slice is explicit absolute positioning inside Stack/Grid/Form while
  preserving Freeform requirements and flow defaults. It reuses V1 `layoutItem.position`,
  `moveNode`, `setNodeLayout`, group transforms, snapping, inverse, and replay.
* The next slices are normalized selection/lock/Z-order, canvas inline editing and fine-grained
  Table commands, then versioned affine rotation.
* Preserve unrelated dirty-worktree changes. Do not batch this program into one unreviewable commit.
