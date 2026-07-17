# Bug Analysis: Studio Fixture Identity Coupling

Date: 2026-07-14

## 1. Root Cause Category

- **Category**: B/E/D - Cross-layer contract, implicit assumption, and test gap
- **Specific Cause**: Studio chose its canonical draft from browser storage and
  created a procurement fixture when no draft ID existed. Runtime controls also
  imported fixture UUIDs. The generation assembler happened to allocate the same
  deterministic UUIDs, so the real generated document looked compatible while
  the frontend remained coupled to test data rather than the persisted project
  aggregate.

## 2. Why Earlier Fixes Failed

1. Backend generation acceptance proved the document/checkpoint contract but did
   not prove a fresh frontend could discover that accepted document.
2. Browser checks manually seeded draft, runtime session, and AI thread IDs, so
   they bypassed the missing project-current recovery contract.
3. Deterministic assembler UUIDs matched the fixture and masked every production
   import of `STRUCTURED_PROCUREMENT_IDS`.
4. Runtime replay tests proved state semantics but did not vary opaque document
   IDs or inspect frontend identity resolution.

## 3. Prevention Mechanisms

| Priority | Mechanism | Specific action | Status |
|---|---|---|---|
| P0 | Architecture | Add server-owned current draft and current generation job reads | Done |
| P0 | Architecture | Derive runtime action IDs from semantic keys and rule triggers | Done |
| P0 | Fail closed | Refuse runtime startup when semantic mapping is missing or ambiguous | Done |
| P1 | Test coverage | Add API, pure binding, full frontend, and direct browser recovery checks | Done |
| P1 | Documentation | Record backend/frontend recovery and identity contracts in Trellis specs | Done |

## 4. Systematic Expansion

- **Similar Issues**: Any generated aggregate whose UI happens to share IDs with
  a seed, storybook fixture, test namespace, or cached browser selection.
- **Design Improvement**: Project ownership must be resolved by a typed server
  read. Opaque IDs may be transported, but behavioral discovery uses explicit
  semantic keys and validated references.
- **Process Improvement**: End-to-end acceptance must begin with direct route
  navigation in a browser that has not been manually supplied resource IDs.

## 5. Knowledge Capture

- [x] Updated backend database guidelines with project-current recovery.
- [x] Updated canonical and mirrored frontend state-management specs.
- [x] Added focused regressions and full browser evidence.
- [x] Recorded integration completion in the task reports.
- [ ] Commit only after the user approves the Trellis Phase 3 commit plan.

The repository has no `src/templates/` spec tree to synchronize. The
vibe-kanban frontend alias was updated together with the canonical ccgui spec.
