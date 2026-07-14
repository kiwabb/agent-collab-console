# Bug Analysis: Recursive MCP Page Payload Corruption

Date: 2026-07-14

## 1. Root Cause Category

- **Category**: B/D - Cross-layer contract and test coverage gap
- **Specific cause**: The recursive `GeneratedPageV1` object schema was valid
  JSON Schema and passed local descriptor/Pydantic tests, but the configured
  Claude provider's tool adapter did not preserve the recursive discriminated
  union. It converted `children` arrays into object wrappers and eventually
  converted child objects into empty strings before the MCP server received
  them.

## 2. Why Earlier Fixes Failed

1. Moving from staged files to direct object submission removed shell/file
   overhead but exposed the recursive schema to provider tool coercion.
2. Moving `$defs` to the input-schema root fixed reference resolution but did
   not prove the provider could serialize recursive union arrays.
3. Adding a full required page skeleton improved semantic guidance but did not
   change the adapter's serialization behavior.
4. Normalizing numeric, boolean, JSON-string array, and exact `{item: [...]}`
   wrappers fixed lossless type drift only. It correctly refused
   `{item: ["", ""]}` because the original child objects were already lost.

## 3. Prevention Mechanisms

| Priority | Mechanism | Specific action | Status |
|---|---|---|---|
| P0 | Architecture | Page finalization accepts one bounded `payloadJson` string; MCP parses strict JSON before validation | Done |
| P0 | Runtime evidence | Preserve original argument hash, raw trajectory, canonical object, and normalization paths | Done |
| P0 | Integration test | Run the real project-bound Claude executor through context, finalization, process terminal, assembly, replay, render, and Accept | Done |
| P1 | Unit test | Cover exact array wrapper, extra-key refusal, invalid JSON, missing nodes, raw hash, and normalized storage | Done |
| P1 | Documentation | Add recursive agent-tool schema guidance to the shared cross-layer guide | Done |

## 4. Systematic Expansion

- **Similar issues**: Any agent tool exposing recursive ASTs, nested command
  unions, workflow graphs, or component trees through provider-generated
  object arguments.
- **Design improvement**: Keep simple non-recursive contracts as typed tool
  objects. Use bounded JSON-string transport for recursive artifacts when the
  configured provider cannot preserve the schema, then validate once at the
  external boundary.
- **Process improvement**: Treat provider wire-shape smoke tests as part of a
  tool contract, not as optional end-to-end QA after implementation.

## 5. Knowledge Capture

- [x] Updated `.trellis/spec/guides/cross-layer-thinking-guide.md`.
- [x] Added focused MCP/runtime regressions.
- [x] Preserved both failed real jobs and the successful comparison job.
- [x] Recorded the completed vertical slice in
  `reports/ai-generation-vertical-slice.md`.
- [ ] Commit with the task's work batch after the user approves the Trellis
  Phase 3 commit plan.

The repository has no `src/templates/` tree, so there is no generated spec
template copy to synchronize.
