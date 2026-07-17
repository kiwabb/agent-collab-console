# Freeform Snap Attestation Boundary

## Problem

The first Freeform move evidence implementation solved against continuous browser
measurements and only then rounded evidence fields to four decimal places. That is not
replayable. For example, a moving frame at `x=20`, width `10`, and a sibling at
`x=36.00004` is `6.00004` units from alignment and does not snap at scale `1`. The
persisted sibling coordinate becomes `36`, so replay sees an exact distance of `6` and
does snap.

Schema validation can prove that an evidence object is internally coherent, but it
cannot prove that the recorded candidate set and winner are what the pinned solver
would have produced. A Python reimplementation would create a second geometry engine
and eventually diverge from the browser.

## Decision

1. The browser canonicalizes every solver input to the evidence precision before
   solving: selection bounds, requested delta, direct-sibling frames, container size,
   and preview scale. Negative zero becomes zero. Selected IDs and sibling frames use
   canonical lexical ID order; Freeform grids preserve document order.
2. RAF preview, pointer-up, command construction, evidence serialization, and backend
   replay all use one pure TypeScript replay boundary around the existing arithmetic
   solver. The arithmetic solver remains independently testable and does not perform
   transport normalization itself.
3. Freeform move evidence advances to version 2 and records both the semantic snap
   solver version and its source-manifest hash. A solver identity mismatch is a hard
   refusal, never a compatibility fallback.
4. A dedicated `prototype-snap-worker` owns `describe`, `attest`, and `attestMany`.
   It is separate from the business runtime worker and renderer worker because snap
   geometry has its own version, input limit, failure domain, and release cadence.
5. `attest` reconstructs the canonical solver input from one evidence object, reruns
   the solver, reconstructs every derived evidence field, and accepts only an exact
   canonical match. `attestMany` performs the same operation for an ordered list of at
   most 200 entries in one Node process and rejects the complete request on the first
   mismatch.

## Cross-Layer Flow

```text
pointer-down frozen frame
  -> canonical four-decimal solver input
  -> browser replay wrapper
  -> preview / exact pointer-up projection
  -> one Move command batch + evidence v2
  -> Python schema and base-document context validation
  -> TypeScript snap worker attest
  -> deterministic command execution
  -> atomic journal append

checkpoint + ordered journal tail
  -> canonical envelope/hash/history validation
  -> collect evidence-bearing forward batches
  -> one snap worker attestMany (maximum 200)
  -> sequential command replay
  -> final document-head hash validation
```

The worker returns an evidence hash for each accepted entry. Python verifies response
identity, cardinality, order, and every returned hash, but does not rerun geometry.

## Failure Semantics

- Live evidence mismatch: fail the durable apply operation with
  `command_evidence_mismatch`; append no command and keep the active draft/head.
- Recovery evidence mismatch: fail recovery and mark that exact draft head corrupt.
- Worker missing, spawn failure, timeout, protocol drift, or identity drift: refuse
  live apply and recovery. These infrastructure failures remain retryable and do not
  mark an otherwise unproven draft corrupt.
- `attestMany` is atomic. No stored command is executed if any evidence entry fails.
- A batch without Freeform move evidence does not require the snap worker. Undo/Redo
  replay their already sealed inverse/forward commands and do not create new snap
  evidence.

## Capacity and Deadlines

- One live `attest` and `describe` call use a five-second deadline. Recovery
  `attestMany` uses a separate 60-second deadline because it accepts the complete
  schema-bounded 200-entry tail in one process. Policy lives in the typed
  `application/timeouts.py` accessors, `bootstrap.py` injects both values, and
  the adapter constructor requires both values to be positive.
- A 2026-07-17 checked-bundle benchmark measured a 200-entry repeated small evidence
  tail at 0.165 seconds, one legal 500-sibling evidence entry at 0.159 seconds, and a
  200-entry repeated 500-sibling tail beyond the old shared five-second deadline. The
  split deadline keeps live refusal fast while allowing the maximum recovery envelope
  to complete without weakening the 200-entry or 32-MiB bounds.
- After the split, the final checked bundle completed that same 200-entry repeated
  500-sibling `attestMany` request in 9.296 seconds under the 60-second recovery
  deadline; one dense entry completed in 0.179 seconds. This is manual capacity
  evidence, not a permanent slow test.

## Version and Build Identity

The snap worker manifest records:

- `prototype-snap-worker-manifest/v1`;
- protocol `prototype-snap-worker/v1`;
- solver `structured-prototype-freeform-snap/v1`;
- ordered source inventory with SHA-256 and byte size;
- source-manifest hash;
- Node bundle SHA-256 and byte size;
- build tool and Node target.

The source inventory includes the protocol, replay/canonical boundary, evidence
serializer/parser, alignment solver, spacing solver, grid geometry, grid helpers,
canonical JSON/hash helper, wire types, and CLI entrypoint. Changing any
solver-affecting source therefore produces a new source hash even when the semantic
version was not intentionally changed.

## Verification Matrix

- Boundary vector `20 / 10 / 36.00004 / threshold 6` agrees in browser replay and
  worker attestation.
- Exact threshold, just-over-threshold, alignment/spacing/grid ties, grid session gate,
  and Ctrl/Meta bypass replay identically.
- Dual-axis spacing fallback and candidate outcomes match exactly.
- Candidate, grid, sibling, solver-version, source-hash, final-position, and command
  tampering are rejected before journal append or replay.
- One live evidence batch launches one `attest`; a recovery tail launches one ordered
  `attestMany`; a 200-entry tail still uses one Node process.
- Live and recovery calls pass their distinct five-second and 60-second deadlines to
  the same checked worker adapter.
- Worker absence and timeout refuse without changing the active draft; deterministic
  recovery mismatch marks the draft corrupt with durable failure evidence.
