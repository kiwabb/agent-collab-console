# Structured Prototype Editor Detailed Design and Interactive Demo

## Goal

Define and demonstrate a product-manager-facing prototype studio where users can review runnable web prototypes, refine them through AI conversation, rearrange semantic UI components with constrained drag-and-drop, and visually connect pages into business flows. After validating the frontend interaction model, define the backend workflow, persistence contracts, state machines, transaction boundaries, and API surface required to implement the structured editor safely.

The locked end-state and user acceptance loop are recorded in [`final-goal.md`](final-goal.md). Production generation must remain domain-neutral: project evidence and the confirmed blueprint determine pages and optional business behavior. `examples/admin-demo` is an acceptance fixture, never a default template or production business contract.

## Users and Core Jobs

- Product managers review generated prototypes without reading source code.
- Product managers ask AI to make scoped visual or content changes and accept or reject a previewed patch.
- Product managers rearrange standard components without breaking responsive layout.
- Product managers organize pages, shared navigation, and cross-page business flows visually.

## Product Decisions

- A versioned structured prototype document is the future source of truth; HTML/CSS/JS are renderer outputs, not canonical storage.
- The page model is structured-first. Standard semantic components are draggable and inspectable; unsupported complex regions use an opaque CodeBlock that remains runnable and AI-editable but is not internally draggable.
- Page layout is constraint-first using Stack, Grid, and Form containers. Bounded free positioning is available only for direct children of an explicit Freeform container; it is never an implicit page-wide mode.
- Freeform move snapping treats a single selection or same-parent group union as one moving frame. On each axis it evaluates alignment and equal-spacing candidates in one deterministic competition: smallest client-space correction wins, existing edge/center alignment wins an exact tie, then spacing candidates are ordered by target position and stable sibling IDs. If independently valid X/Y spacing winners invalidate each other after combination, the smaller correction is retried alone, an exact tie prefers X, then the alternate axis and alignment/raw fallbacks are tried in that fixed order.
- Equal-spacing candidates use only visible, unselected direct siblings frozen at pointer-down. The moving frame plus two lane-compatible siblings may either fill the gap between adjacent siblings or extend an existing sibling gap before/after the pair; all represented gaps must be positive, the three frames must share positive cross-axis overlap, and the projected moving frame must remain in its Freeform bounds without overlapping another lane sibling.
- Equal-spacing uses the existing inclusive six-client-pixel threshold at every zoom, preserves group-internal geometry, emits paired distance segments only during move preview, and shares Ctrl/Meta bypass, RAF projection, exact pointer-up projection, one atomic command batch, and one-step Undo with edge/center snapping. Local arithmetic tails may affect acceptance but never move the authoritative equal-spacing target; logical zero gaps remain edge alignment, and both rendered segments must match the recorded gap within the same local tolerance. Equivalent blocker queries use exact final geometry as a per-projection cache key so dense overlapping siblings do not repeat the same full scan. Configurable grid snapping remains a separate later slice.
- Configurable Freeform layout grids are the next independent move-snapping slice. Each Freeform may own ordered, versioned square, column, and row grids with stable IDs, local origins, token-backed color/opacity, persisted visibility, and persisted snap enablement. The editor also has a session-level grid-snapping gate. All grid candidates start from the same raw frame as alignment and equal-spacing candidates; the smallest correction wins and exact ties use `alignment > equal-spacing > grid`.
- AI changes are expressed as validated structured patches and shown as a draft before acceptance. Rejecting or failing a patch preserves the accepted version.
- Initial AI generation is plan-first: the user confirms a multi-page blueprint before foundation and page generation begin, and only a fully validated assembled document can become an active draft.
- The confirmed blueprint is the sole scope authority for generation. Page counts, routes, navigation, roles, entities, forms, flows, and scenarios must not be fixed to a procurement or admin domain in production code.
- Roles, entities, forms, flows, and runtime scenarios are optional. The generator must not invent them when repository evidence and the confirmed product intent do not require them.
- Requirements-driven generation, repository-backed restoration, and conversational modification all invoke the project-bound Claude Code `prototype_ui_engineer`; they use different task/context protocols but submit the same strict structured contracts.
- Every AI request creates a fresh `CodexTask` and execution process in an isolated project worktree. Conversation continuity comes from persisted threads, messages, context manifests, and the current structured draft rather than hidden Claude session memory.
- The product backend never calls a generic LLM API for prototype generation or editing. If the project UI Engineer runtime is unavailable, the operation fails closed without fallback.
- Canonical prototype state uses an in-memory active document, a monotonic SQLite command journal, and immutable compressed checkpoints in a managed content-addressed object store. Full documents and large AI outputs are not stored as SQLite JSON columns or in the source repository.
- Every state-changing step is durably observable before downstream effects begin: it has an operation/step identity, lifecycle state, timestamps, input/output hashes, fixed contract/runtime versions, stable error code, and completion evidence. Logs alone are not completion evidence.
- Reproducibility has two explicit meanings: deterministic document/command/assembly/render steps must replay to the same hash, while Claude executions preserve frozen inputs and exact submitted outputs for historical reconstruction and create a separate comparison run when re-executed.
- Business flow is an executable runtime model, not a second set of decorative canvas edges. The MVP covers typed variables, simple guard predicates, forms/validation, deterministic mock entities, simulated roles, scenarios, navigation, overlays, drawers, tabs, and ordered state effects.
- Browser preview and backend replay use one pinned TypeScript runtime core. The backend does not reimplement rule semantics in Python.
- Studio and recorded-review runtime sessions pin a document object, scenario and runtime version, then append semantic event batches with state hashes. Keypresses remain transient; committed field changes, submit and click events are observable and replayable.
- Real APIs, real authentication/authorization, arbitrary expressions/scripts, production data and full BPMN remain deferred.
- The editor targets web application prototypes, not vector illustration or production code authoring.

## Canonical Document Contract

- `PrototypeDocument` contains `schemaVersion`, project settings, tokens, component definitions, pages, navigation, flows, runtime definitions, and asset references.
- Every document entity and UI node has a stable opaque ID.
- `PrototypePage` contains a route, title, viewport settings, root node, and flow metadata.
- `UINode` uses a discriminated type union for Freeform, Stack, Grid, Form, Text, Button, Input, Select, Table, Image, ComponentInstance, Overlay, and CodeBlock.
- Layout values use explicit units and typed responsive overrides; arbitrary style dictionaries are forbidden for structured nodes. Freeform child coordinates use bounded canonical decimal strings and are forbidden at the page root, under ordinary containers, and in responsive overrides.
- Freeform grid geometry uses the same canonical bounded decimal-string boundary. Missing or empty `grids` is the backward-compatible no-grid value and remains omitted from canonical JSON so historical document/checkpoint hashes do not change. Unknown grid versions, kinds, fields, token references, duplicate grid IDs, or invalid geometry fail closed.
- Component instances reference a definition and store only permitted property and slot overrides.
- Runtime rules and bindings reference entity IDs rather than URLs or handlers embedded in HTML.
- Runtime behavior uses typed trigger/guard/effect ASTs. Flow edges reference behavior-rule IDs; screen/state/decision canvas nodes and coordinates are projections, not executable authority.
- Typed view bindings map runtime state back to Text, Table, Select, visibility and disabled node properties; derived view-model hashes are replay evidence, not a second mutable state.
- Every document has at least one deterministic scenario with an initial simulated role, start page, initial variables, mock entity fixtures and fixed clock; Studio-only role-switch events support multi-actor walkthroughs without pretending to implement authentication.
- Deleting an entity with inbound references is refused until references are removed or explicitly retargeted.

## Command and Version Contract

- User and AI edits use the same command vocabulary for nodes/pages/navigation plus runtime variables, mock entity schemas, forms, scenarios, behavior rules, node-field bindings and flow layout.
- A command batch is atomic: validation failure rejects the complete batch.
- Every mutation includes the expected draft head sequence; stale heads are refused with an explicit conflict result.
- Command batches are append-only and use a gap-free monotonic sequence. Undo and redo append compensation/replay batches and never modify or delete historical batches.
- Moving into Freeform writes the target position in the same Move command; moving out clears it. Freeform west/north/center Resize writes position and dimensions in one `setNodeLayout` command so Undo cannot observe a half-applied frame.
- Adding, editing, removing, or reordering Freeform grids uses one `setNodeProperty/freeformGrids` batch. The complete prior grid list is captured by the existing inverse-command path, so one save is one journal sequence and one Undo/Redo unit.
- Recovery loads the latest verified checkpoint and deterministically replays the bounded command tail. Missing sequence, unsupported version, object corruption, or hash mismatch marks the draft corrupt and fails closed.
- Publishing a draft creates an immutable document revision that references a verified document object. Rendered artifacts record document object hash, revision, renderer version, and output hash.
- Assets are content-addressed and referenced by ID; large binaries are never embedded into document JSON.
- Deleting a project prototype is an explicit, confirmed, idempotent project-level operation. It atomically removes drafts, publications, generation records, runtime sessions, and AI conversations, releases object references for later GC, and retains deletion operation evidence.

## AI Editing Contract

- The backend creates a project UI Engineer task for each generation or conversation run; Claude Code may use its configured model internally, but that model is not an application-level routing target.
- AI context includes the active page, selected node subtree, relevant component definitions, tokens, and directly connected flow targets rather than the entire project by default.
- AI returns a command batch plus a user-facing change summary; raw document replacement is not accepted.
- AI generation blueprint declares role/entity/form/behavior/scenario intents, page outputs bind node local keys to confirmed behavior intents, and the service deterministically assembles runtime definitions.
- A validated batch renders into an isolated preview. Apply writes it to the active draft; Reject discards it; explicit Publish creates the public revision.
- CodeBlock edits may replace only the selected block payload and cannot mutate host runtime, navigation, or unrelated nodes.
- AI errors, invalid commands, timeouts, or render failures preserve the last accepted preview and show a recoverable error.

## Workbench Information Architecture

- The production Studio uses one application shell and divider-based editor regions. Project navigation, page rail, canvas and inspector must not be nested as floating cards inside one another.
- Top bar: project identity, saved/draft state, responsive viewport control, Design/Flow mode switch, preview, scenario/simulated-role/reset controls, and share action.
- Left rail in Design mode: page tree with shared-navigation order, then draggable component palette.
- Center in Design mode: dominant runnable preview with selection outlines, insertion indicators, and responsive viewport framing.
- Left rail in Flow mode: screens, business states, decisions, scenarios and simulated roles.
- Center in Flow mode: draggable projection nodes, rule-backed ports/connections, zoom controls, and selected-path emphasis.
- Flow inspector edits the selected rule's trigger, guard and ordered effects; moving nodes only changes flow layout.
- Right inspector: AI conversation as the default tab, selected-node properties, and selected Flow rule/view-binding runtime properties.
- Selecting a Freeform exposes a compact layout-grid editor for add/remove, kind, visibility, snapping, origin, size/count, item size, gutter, margin, alignment, token color, and opacity. Grid chrome is pointer-transparent and visible only in Design mode.
- AI patch review remains visible until accepted or rejected and states exactly which nodes/pages will change.
- Mobile collapses side regions into explicit drawers; preview and mode switching remain operable without horizontal overflow.

## Interactive Demo Scope

- Deliver one standalone HTML artifact that opens without a build step.
- Demonstrate Design and Flow modes.
- Allow pages to be reordered by drag-and-drop and keep the preview navigation synchronized.
- Allow Button, Input, Metric, and Table blocks to be dragged from the palette into a constrained page stack.
- Allow canvas blocks to be selected and edited through a small property inspector.
- Simulate AI conversation with at least three meaningful patch types and explicit Apply/Discard controls.
- Allow flow nodes to be moved and a connection to be created by dragging between ports.
- Allow preview navigation between at least four related application pages.
- Provide desktop and mobile-safe layouts, visible focus states, reduced-motion handling, and non-color-only status indicators.

## Backend Design Scope

- Define a clean structured-prototype aggregate without requiring migration of historical HTML prototypes.
- Define the durable models for document metadata, immutable object references/checkpoints, active drafts, append-only command batches, AI edit runs, render runs/artifacts, and content-addressed assets.
- Define atomic optimistic-concurrency behavior for drag-and-drop, property edits, undo/redo, AI patch application, and publication.
- Define checkpoint triggers, a hard replay-tail limit, deterministic recovery, write-before-reference ordering, orphan collection, and corruption handling.
- Define durable state machines and restart behavior for AI edit and render work.
- Define deterministic prototype runtime contracts, shared browser/backend runtime core, session/event/checkpoint persistence, Flow projection rules and runtime replay.
- Define the initial AI generation pipeline: frozen context, editable blueprint, shared foundation, parallel page items, deterministic assembly, bounded repair, preview, and draft acceptance.
- Define durable AI conversation threads, visible messages, context selection, answer/clarification outcomes, and command-proposal application.
- Define typed HTTP and SSE contracts, idempotency keys, error mapping, and validation ownership across interface, application, and store layers.
- Define a durable operation/step/event evidence model and replay manifest covering HTTP, context freeze, governance, Claude task/process, MCP/staging, validation, repair, command application, checkpoint, rendering, publication, recovery, and GC.
- Define how the new subsystem coexists with the current HTML prototype service during a later implementation rollout; production wiring is not part of this task.

## Acceptance Criteria

- [x] The artifact opens locally and presents the actual editor as the first screen.
- [x] Design/Flow mode switching changes the central workspace without shifting the global shell.
- [x] Reordering a page updates both the page rail and preview menu in one operation.
- [x] Dropping a palette component adds a selectable block to the preview without absolute positioning.
- [x] A simulated AI request produces a scoped draft summary; Apply changes the preview and Discard leaves it unchanged.
- [x] Flow nodes can be repositioned and a new directed connection can be created using visible ports.
- [x] Preview menu actions switch the active page and preserve the shared shell.
- [x] No desktop or mobile viewport has incoherent overlap or document-level horizontal overflow.
- [x] Keyboard focus is visible and primary controls expose accessible labels.
- [x] Visual QA screenshots are captured at desktop and mobile widths.
- [x] Production Studio chrome is full-width and divider-based; no page-level card is nested inside the project surface, and palette/page items render as compact rows.
- [x] A confirmed project-level delete removes all editable/published prototype state atomically, returns the Studio to generation, and preserves all data on failure.
- [x] The backend aggregate and SQLite table responsibilities are defined without treating HTML as canonical storage.
- [x] Draft, AI edit, and publication/render state machines have explicit legal transitions and restart behavior.
- [x] API contracts include optimistic concurrency, idempotency, typed errors, snapshots, and SSE recovery.
- [x] Multi-row publication and AI patch application transaction boundaries preserve the last published revision on every failure path.
- [x] A phased backend implementation plan and focused test matrix are documented.
- [x] Initial AI generation and conversational AI editing use one project-bound Claude Code UI Engineer runtime, separate task contracts, and one shared validation/rendering boundary.
- [x] AI generation persistence, retry, cancellation, budget, observability, and source-integrity behavior are defined.
- [x] Conversation history is durable but never replaces the current structured document as the source of truth.
- [x] Full canonical documents and large AI JSON are stored as immutable compressed content-addressed objects; SQLite stores command journals, workflow metadata, hashes, and object references.
- [x] Checkpoint triggers, the 200-batch hard replay tail, write/fsync/read-back-before-reference ordering, orphan GC, and fail-closed recovery are defined.
- [x] Undo/Redo append immutable compensation/replay commands and never rewrite command history.
- [x] Every workflow step has durable identity, input/output hashes, exact versions, error codes, and completion evidence; every successful state change has a terminal replay manifest, while pre-effect failures retain durable failure evidence.
- [x] Deterministic replay and non-deterministic Claude diagnostic reruns are explicitly separated and have testable acceptance rules.
- [x] Business-flow runtime definitions cover scenarios, roles, typed state, forms, guards, mock entity effects and navigation without arbitrary scripts or real APIs.
- [x] Flow edges are projections of executable behavior rules and cannot drift from runtime behavior.
- [x] Runtime sessions pin document/scenario/core versions and persist semantic event/state hashes for deterministic recovery and replay.
- [x] Browser preview and backend replay share one versioned TypeScript runtime core; Python does not implement a second evaluator.
- [x] Explicit Freeform containers support bounded direct-child placement, pointer movement, west/north Resize, center Resize modifiers, deterministic drop coordinates, persistence, and Undo without enabling page-wide arbitrary positioning.
- [x] Freeform move projection snaps single or grouped selections to container and visible direct-sibling edges/centers, renders zoom-stable smart guides only during preview, supports Ctrl/Meta bypass, and preserves exact-tail one-batch persistence and Undo.
- [x] Freeform Resize snaps all eight active handle edges for single or grouped selections, preserves Shift/Alt/Shift+Alt semantics, supports Ctrl/Meta bypass, recovers but never worsens existing overflow, keeps every projected child field within the canonical `0..4096` range, and keeps guides, exact-tail persistence, and Undo atomic across zoom levels.
- [x] Freeform move snaps single or grouped selections into positive equal horizontal or vertical gaps formed with two visible same-parent siblings, chooses deterministically against edge/center snaps within the same six-client-pixel threshold, and never snaps across unrelated visual lanes or through another sibling.
- [x] An equal-spacing preview renders the two compared distance segments with stable metadata and one-physical-pixel strokes across zoom; Ctrl/Meta, Escape, pointer cancellation, and a non-winning spacing candidate leave no distance guide or document mutation.
- [x] Pointer-up recomputes the exact final equal-spacing projection and persists the whole single/group move in one command batch and one Undo unit, while preview frames leave the document sequence unchanged.
- [x] Legacy Freeforms without `grids` retain their canonical hashes; non-empty square/column/row configurations round-trip through the frontend codec, backend strict model, command journal, checkpoint recovery, and one-step Undo/Redo.
- [x] Design mode renders frame-local square/column/row overlays without intercepting pointer or runtime events; per-grid visibility and snapping plus the editor grid-snapping gate have distinct, deterministic effects.
- [x] Freeform move evaluates grid lines from the same continuous raw single/group frame as alignment and equal-spacing, keeps the six-client-pixel threshold at every zoom, and resolves exact ties as `alignment > equal-spacing > grid` independent of grid order.
- [x] Pointer-up recomputes the exact final grid projection into the existing one-batch move transaction; Ctrl/Meta, Escape, cancellation, disabled grids, and the session gate leave no grid guide or document mutation.
- [x] Initial AI generation includes at least one scripted business scenario whose event batches and milestone predicates pass in the pinned runtime core before candidate readiness.
- [x] Production generation contains no procurement-specific prompt, page set, route, role, entity, form, scenario, store ordering, or runtime replay requirement.
- [x] Generation work items and deterministic assembly derive entirely from the confirmed blueprint and strict generation artifacts.
- [x] `examples/admin-demo` produces editable dashboard, user-management, and order-management pages from repository evidence.
- [x] A second non-admin fixture passes generation contract tests, proving the implementation is not specialized to `admin-demo`.

Generality evidence is pinned in
[`admin-demo-accepted-v12-audit.json`](artifacts/admin-demo-accepted-v12-audit.json) and its
canonical candidate document. The accepted Claude UI Engineer run produced `/dashboard`,
`/users`, and `/orders` with root child counts `3/3/2`, a source fingerprint and terminal replay
manifest. The older `admin-demo-v11-ec07ae12-candidate-document.json` remains preserved as failed
evidence for the empty-page regression. `test_structured_prototype_generation_generality.py`
supplies the independent City Weekends fixture and runtime replay proof.

## Implementation Plan

1. Create the standalone document shell, semantic tokens, stable responsive grid, and realistic sample project data.
2. Implement Design mode page rail, shared preview shell, component palette, constrained drop targets, selection, and inspector edits.
3. Implement AI chat simulation with draft patch review and apply/discard behavior.
4. Implement Flow mode page nodes, draggable positioning, SVG connections, and port-to-port connection creation.
5. Add mobile drawers, keyboard/focus treatment, reduced-motion behavior, and visual QA fixes.
6. Design the production backend workflow and persist the decisions in `backend-design.md` without implementing routes, migrations, or services yet.
7. Detail initial AI generation and conversational editing in `ai-generation-design.md`, including project Agent boundaries, task protocols, contracts, lifecycle, recovery, and tests.
8. Lock storage/recovery in `checkpoint-journal-design.md` and the cross-workflow evidence contract in `observability-reproducibility-design.md` before production schema or service implementation.
9. Lock exact document/command/HTTP/MCP/renderer boundaries and compatibility fixtures in `executable-contracts.md` so implementation does not reinterpret the design.
10. Define executable business state, scenarios, rule-backed Flow semantics, runtime sessions and deterministic event replay in `prototype-runtime-design.md`.
11. Implement frame-local Freeform layout grids and grid snapping from the pinned Penpot interaction study, preserving historical hashes and the existing move transaction.

## Out of Scope

- Production database migrations, backend API implementation, or changes to the existing prototype runtime.
- Importing or converting existing arbitrary HTML into structured nodes.
- Real model calls, multi-user collaboration, comments, approval workflows, or production code export.
- Direct generic LLM API integration or fallback for prototype generation and conversational editing.
- Real APIs/databases, real authentication/authorization, production data, arbitrary expressions/scripts, full BPMN, timers, parallel gateways, or production-grade application state.
- Pen tools, vector editing, arbitrary layer transforms, or Figma-compatible file import/export.
- Page-level grid presets, rotation-aware grids, infinite-canvas pixel grids, and a Penpot/Figma file interchange format.

## Technical Notes

- The current frontend already includes `@dnd-kit`, React Flow, `fast-json-patch`, Immer, Lucide React, and Zustand; production implementation should evaluate and reuse those dependencies rather than add parallel libraries.
- The current route bridge proves page-to-page preview navigation but does not provide a shared menu or canonical flow model.
- The current interactive Flow artifact validates the workbench shell and edge gestures only. It does not yet demonstrate the runtime rule/state inspector and must not be presented as complete business-flow execution.
- Follow the repository fail-closed rules: invalid document operations and failed governance or rendering checks must refuse publication.
- Managed prototype objects live under the application data root. Exporting a prototype into the project directory is a separate derivative operation and never changes canonical storage.
- The interactive artifact is exploratory design evidence. It must not be wired into the production route in this task.
- Penpot grid behavior was inspected at commit `167aa7410f95bce91b9a80059624a3e3d9307f1e`; only interaction/data contracts are reused. No MPL implementation code is copied. See `research/penpot-grid-snapping-patterns.md`.
