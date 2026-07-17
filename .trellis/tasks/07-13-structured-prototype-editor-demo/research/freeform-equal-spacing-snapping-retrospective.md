# Bug Analysis: Freeform Equal-Spacing Move Snapping

## Outcome and Implementation Boundary

Freeform Move now supports deterministic equal-spacing snapping without adding a document field,
command type, or second persistence transaction. The feature is limited to a direct-child move
inside one explicit `Freeform` container:

- A single selection or same-Freeform group union is one rigid moving frame. Internal group offsets
  and dimensions are preserved.
- Only visible, unselected direct siblings frozen at pointerdown are eligible. Descendants, other
  parents, hidden nodes, and live DOM changes during the gesture cannot become candidates.
- Horizontal and vertical `before | between | after` placements are supported. Every represented
  gap must be positive, all three frames must share a positive cross-axis lane, and no sibling may
  occupy the projected frame or either measured corridor.
- Equal spacing competes with existing container/sibling edge and center alignment from the same
  clamped, continuous raw frame. It is not applied after alignment as a second transform.
- Distance guides are transient controls-layer chrome. The canonical document still receives the
  existing atomic Move command batch only after pointer-up.
- Resize spacing, layout-grid preferences, and grid snapping are outside this slice.

## 1. Root Cause Category

- **Category**: B/E - Cross-Layer Contract and Implicit Assumption.
- **Specific cause**: equal spacing crosses measured DOM geometry, zoom-scaled pointer intent,
  two-axis candidate arbitration, transient guide rendering, and one persistent Move transaction.
  Treating it as a local guide-rendering concern would let preview geometry, the displayed distance,
  and the committed position disagree.
- **Coverage contributor**: D - Test Coverage Gap. Ordinary integer examples do not expose
  fractional targets, threshold tails, lane invalidation after the other axis snaps, blocker
  corridors, input-order instability, or grouped exact-tail persistence.

## 2. Key Algorithm and Determinism Contract

1. Build one already-clamped raw selection frame from the pointer delta. Preserve floating-point
   coordinates; do not round before candidate collection.
2. On each axis, sort the eligible sibling frames deterministically and enumerate every ordered
   pair. For each pair, derive `before`, `between`, and `after` target positions.
3. Reject a target unless both compared gaps are strictly positive, the three frames share a
   positive cross-axis intersection, the position remains inside the legal move envelope, and no
   same-lane sibling blocks a reference gap, target gap, or projected moving frame.
4. Compare the best spacing candidate with the best alignment candidate from that same raw frame.
   The smaller correction wins; edge/center alignment wins an exact tie. Spacing-only ties resolve
   by correction distance, outer span, placement, gap, target position, and stable reference IDs,
   so sibling input order cannot change the result.
5. Resolve X and Y independently, combine them, then revalidate each winning spacing candidate
   against the final two-axis frame. If the other axis moved the selection out of the shared lane,
   discard that spacing result and restore that axis's alignment/raw result. If both axes invalidate
   each other, retry the smaller correction alone, use X as the exact-tie winner, then try the
   alternate axis and full alignment/raw fallback in that order.
6. RAF preview and pointer-up exact-tail commit call the same projection. Ctrl/Meta returns raw
   bounded movement with no alignment or spacing guide. Cancellation clears the projection and
   submits no command.
7. Split cheap candidate construction from blocker validation. Only a candidate better than the
   current validated winner performs a blocker query, and equivalent exact queries share one
   result keyed by axis, final moving rectangle, shared lane, fixed corridor, and both segment
   intervals. Candidate reference IDs remain the real stable IDs from deterministic enumeration.

## 3. Numerical and Rendering Traps

- **Premature rounding**: rounding a raw move can accept a target that is truly more than six
  client pixels away and destroys valid half-pixel spacing. Continuous coordinates now survive
  until canonical command encoding.
- **Zoom-dependent threshold**: the threshold is `6 / frozenPreviewScale` canvas units. Tests cover
  preview scales `0.5`, `1`, `2`, and `4`, including exact-six acceptance and rejection at
  `6 + 1e-6` client pixels.
- **Machine tails**: decimal geometry can produce values such as `6.000000000000007`. A relative
  `1e-9 * max(1, local magnitudes...)` tolerance decides whether threshold/envelope comparisons are
  acceptable without rewriting the exact equal-spacing target. Fixed or derived gaps inside that
  local zero tolerance are rejected as edge alignment; `6 + 1e-6` client pixels still rejects.
- **Target/guide divergence**: normalizing a target back to a large raw canvas coordinate can change
  one measured segment by a meaningful share of a tiny gap. The solver now preserves
  `position = raw + correction`, `distance = abs(correction)`, and verifies both segment lengths
  against the logical gap before returning; the projector repeats the same invariant at its input
  boundary.
- **Independent-axis false positives**: an X candidate can be valid before a Y alignment moves the
  frame out of the common lane. Final-frame revalidation is required after axis combination.
- **Guide drift and identity**: each winning candidate owns exactly two ordered distance segments.
  Lines and caps are projected from the same Canvas-local frame, line/cap thickness remains one
  physical pixel, caps remain six client pixels, and DOM metadata plus React keys include the axis,
  placement, reference IDs, and segment index.
- **Blocker ambiguity**: an off-lane sibling is harmless, but a same-lane sibling in either gap or
  the destination invalidates the candidate. Testing rectangle overlap alone is insufficient;
  corridor occupancy must be checked explicitly.
- **Dense sibling degradation**: enumerating pairs and then rescanning every sibling for every
  equivalent candidate produced cubic behavior in overlapping-copy layouts. Exact semantic query
  caching retains full blocker correctness while collapsing the reproduced duplicate-query family
  to pair enumeration plus one scan per unique query.
- **Continuous-value labels**: raw recurring decimals widened move overlays, while two-decimal gap
  labels displayed a valid `0.0001` gap as `0 px`. Display now uses the document's four-decimal,
  trailing-zero-free formatter without rounding preview or committed geometry.

## 4. Why Partial Approaches Were Insufficient

1. **Run spacing after alignment**: this performs two corrections and makes the displayed distances
   describe a position different from the pointer's nearest legal target.
2. **Round before snapping**: this hides fractional geometry and changes inclusive-threshold
   decisions across zoom levels.
3. **Accept per-axis results without a final check**: a valid horizontal lane can become invalid
   after the vertical winner is applied.
4. **Treat group children independently**: this distorts group-internal spacing and can create
   conflicting candidates. The selection union must be solved first and its one delta applied to
   every selected child.
5. **Render generic duplicate guides**: two segments need stable participant metadata and unique
   keys; a component-type label or coordinate-only key is not enough to identify what is being
   compared.
6. **Normalize against the raw canvas position**: coordinate-scale tolerance can be larger than a
   local tiny gap, so this silently destroys equal spacing and later crashes guide projection.
7. **Cache only by target position or midpoint**: equal positions with different cross-axis lanes
   can have different blockers. The key must encode the complete effective query geometry.

## 5. Verification Evidence

Automated evidence recorded for this slice:

- The five focused suites covering the spacing solver, combined arbitration, guide projection,
  continuous Freeform geometry, and UI transaction contracts pass `73/73`.
- The complete structured-prototype suite passes `259/259`; strict frontend TypeScript, full
  ESLint, scoped Prettier, and `git diff --check` also pass.
- The full frontend test run passes `713/714`. The only failure is an existing source-contract
  check for two unregistered bare `fetch` calls in `frontend/src/lib/api/projects.ts`; it is
  unrelated to equal-spacing geometry.
- Isolated 100/200/400-sibling medians after exact blocker-query caching are
  `0.99/4.26/8.57ms` for exact overlap, `1.49/2.22/8.57ms` for unique full frames sharing one
  effective lane, and `1.09/4.12/17.29ms` with one shared blocker. The reproduced pre-fix
  400-sibling medians were `157.56ms`, `142.21ms`, and `81.63ms` respectively.
- A production build was intentionally not run while the development server owned the same
  `.next` directory; this is an environment constraint, not verification evidence.

## 6. Remaining Browser Acceptance

Automated completion does not replace the real interaction check. The following evidence is still
required in the existing in-app browser session before the three equal-spacing PRD acceptance boxes
can be marked complete:

- Drag one node and a same-Freeform group into horizontal and vertical equal gaps, including a case
  where equal spacing competes with edge/center alignment.
- Confirm the document sequence is unchanged throughout preview, increments exactly once on
  pointer-up, and one Undo restores every moved item.
- Confirm Ctrl/Meta bypass and Escape/cancellation clear both guide families and submit no command.
- At multiple zoom levels, confirm both distance segments, numeric label, six-client-pixel end caps,
  and one-physical-pixel strokes remain correctly placed.
- Repeat the smoke check on desktop and mobile layouts and verify no new console warning or error.

## 7. Prevention and Knowledge Capture

| Priority | Mechanism | Specific Action | Status |
|---|---|---|---|
| P0 | Architecture | Collect alignment and spacing from one raw frame and arbitrate once | DONE |
| P0 | Architecture | Revalidate spacing after the final X/Y frame is assembled | DONE |
| P0 | Architecture | Retry mutually invalid axes by correction distance with a stable X tie-break | DONE |
| P0 | Numerical boundary | Preserve continuous coordinates and normalize only relative-`1e-9` tails | DONE |
| P0 | Numerical boundary | Keep target/correction/gap/segment invariants aligned and reject arithmetic-zero gaps | DONE |
| P0 | Test coverage | Cover placements, lanes, blockers, groups, ties, zoom, fractional targets, and exact tail | DONE |
| P1 | Performance | Cache exact blocker queries and cover 400-node adversarial overlap families | DONE |
| P1 | Observability | Keep stable guide metadata and distinguish preview from the one persistent command | DONE |
| P1 | Browser evidence | Complete desktop/mobile interaction and transaction checks | TODO |

The executable transaction is already recorded in
`.trellis/spec/ccgui/frontend/state-management.md`; the same-raw-frame and final-axis revalidation
rule is recorded in `.trellis/spec/guides/cross-layer-thinking-guide.md`. This retrospective remains
the implementation evidence and failure-mode record for the task.

## 8. Next Independent Slice: Configurable Grid Snapping

Grid snapping should start only after the browser acceptance above is complete. Its design must
define grid origin, spacing, visibility, per-project or per-page preference ownership, modifier
bypass, and deterministic arbitration against both alignment and equal spacing. It also needs its
own zoom/fractional-boundary tests and guide semantics. Folding grid candidates into this slice
before those decisions are explicit would make a verified equal-spacing contract ambiguous.
