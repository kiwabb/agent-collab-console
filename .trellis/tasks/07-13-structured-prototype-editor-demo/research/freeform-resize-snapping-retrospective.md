# Bug Analysis: Freeform Resize Persistence Boundaries

### 1. Root Cause Category

- **Category**: B/E - Cross-Layer Contract and Implicit Assumption.
- **Specific Cause**: Continuous Canvas geometry, transient selection-union geometry, and canonical
  per-node document fields were treated as one range. The implementation preserved container
  overflow but did not prove that every persisted child field remained within `0..4096`, and it
  assumed repeated center/aspect arithmetic would reproduce exact boundaries.
- **Coverage contributor**: D - Test Coverage Gap. Examples covered ordinary overflow recovery but
  not west/north/center transforms at the document cap, a legal union wider than one field, or
  floating-point constrained tails.

### 2. Why Fixes Failed

1. **Cap the shared union at `4096`**: fixed single-node persistence but incorrectly rejected a
   valid group whose two canonical children formed an `8192`-wide transient union.
2. **Add group minimum scale from child positions**: protected meaningful west/north shrink but
   still allowed derived dimensions and projected children to land a few ulps outside the cap.
3. **Normalize the generic group projector**: would have applied frame persistence rules to
   Move/Nudge, where intrinsic measured dimensions are not written. Normalization had to move to a
   resize-only projector.

### 3. Prevention Mechanisms

| Priority | Mechanism | Specific Action | Status |
|---|---|---|---|
| P0 | Architecture | Pass explicit minimum/maximum size constraints into shared resize geometry | DONE |
| P0 | Architecture | Derive group limits from every persisted child; keep transient union unconstrained by one field | DONE |
| P0 | Boundary normalization | Normalize only relative-`1e-9` tails before Resize preview/command construction | DONE |
| P0 | Test coverage | Add deterministic cap, legal-wide-union, aspect, center, and projected-tail regressions | DONE |
| P1 | Stress verification | Sweep all handles and Shift/Alt combinations for single and grouped nonzero transforms | DONE |
| P1 | Documentation | Record the executable transaction and cross-layer checklist | DONE |

### 4. Systematic Expansion

- **Similar issues**: move, nudge, alignment, distribution, future rotation, distance guides, and
  grid snapping all cross continuous DOM geometry and canonical document values. Only operations
  that persist a field may apply that field's canonical range.
- **Design improvement**: transformation solvers receive explicit constraints; aggregation and
  persistence are separate named projections; exact-tail commit reuses preview projection.
- **Process improvement**: geometry work is not complete with hand-picked examples. Add seeded
  boundary sweeps and preserve any discovered counterexample as a small deterministic unit test.

### 5. Knowledge Capture

- [x] Added the seven-section Resize Snapping transaction to
  `.trellis/spec/ccgui/frontend/state-management.md`.
- [x] Added the continuous-editor-to-persistence checklist to
  `.trellis/spec/guides/cross-layer-thinking-guide.md`.
- [x] Updated the task PRD and Penpot research status.
- [x] Recorded deterministic evidence: focused structured-prototype tests `84/84`; final static
  review swept `300,000` single and `300,000` grouped nonzero transforms without an invalid field.
- [ ] Complete browser-only visual evidence after an in-app browser tab is available.
