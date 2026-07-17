# Structured Prototype Snap Attestation

> Executable cross-layer contract for Freeform move evidence, the checked
> TypeScript snap worker, durable command apply, and draft recovery.

## Scenario: Replayable Freeform Move Attestation

### 1. Scope / Trigger

- Trigger: changing Freeform move projection, alignment/equal-spacing/grid
  snapping, evidence serialization, command apply/recovery, snap worker build
  inputs, or snap worker timeout/resource limits.
- The browser preview, persisted evidence, and backend recovery must use one
  geometry authority. A Python reimplementation or solve-then-round pipeline
  is forbidden because it can accept a move that cannot replay to the same
  position and hash.

### 2. Signatures

Frontend replay and worker protocol:

```typescript
replayStructuredPrototypeFreeformMove(
  input: StructuredPrototypeFreeformMoveReplayInput,
): StructuredPrototypeFreeformMoveReplayResult

attestStructuredPrototypeFreeformMoveEvidenceJson(
  evidenceJson: string,
): Promise<{ evidenceHash: string }>

type SnapWorkerAction = "describe" | "attest" | "attestMany";
const SNAP_WORKER_ATTEST_MANY_LIMIT = 200;
const SNAP_WORKER_MAX_REQUEST_BYTES = 32 * 1024 * 1024;
```

Backend adapter and policy injection:

```python
PrototypeSnapWorker(
    *,
    attest_timeout_s: float,
    attest_many_timeout_s: float,
    manifest_path: Path | None = None,
    node_executable: str | None = None,
)

await worker.attest(request_id=..., evidence_json=...)
await worker.attest_many(request_id=..., evidence_jsons=...)

timeouts.prototype_snap_worker_attest_timeout_s() -> float
timeouts.prototype_snap_worker_attest_many_timeout_s() -> float
```

Durable boundaries:

- Live apply: `POST /api/structured-prototype-drafts/{draft_id}/commands`.
- Recovery: `GET /api/projects/{project_id}/structured-prototype-documents/current`.
- Journal authority: `prototype_command_batches.commands_json` contains the
  sealed command envelope and optional `freeformMove` evidence.
- Checked assets:
  `backend/app/runtime_assets/prototype_snap_worker.mjs` and
  `prototype_snap_worker.manifest.json`.

### 3. Contracts

- Canonicalize every solver input to four decimal places before solving:
  selection bounds, requested delta, sibling frames, container dimensions,
  and preview scale. Canonical zero is `0`, never `-0`.
- Sort selected IDs and direct siblings by lexical ID. Preserve Freeform grid
  document order because grid order is part of the captured input.
- Pointer preview, exact pointer-up projection, evidence construction, and
  worker replay call the same TypeScript replay boundary.
- Evidence is `evidenceVersion=2`, `kind="freeformMove"`, and includes
  `snapSolverVersion` plus `snapSolverSourceHash`.
- Evidence contains at most six candidates. Every candidate `sortKey` contains
  at most 512 Unicode characters in both TypeScript and Pydantic validation.
- The worker accepts one live evidence object or one ordered list of 1..200
  evidence objects. The complete UTF-8 request is bounded to 32 MiB.
- `attestMany` is atomic. Validate every evidence entry before executing any
  stored command from the recovery tail.
- Python verifies worker protocol/solver identity, response order and count,
  and every evidence hash. Python does not calculate snap geometry.
- The checked worker manifest pins the ordered source inventory, source hash,
  bundle hash/size, protocol, solver version, build tool, and Node target.
  Rebuild checked assets whenever a listed solver source changes.
- Timeout policy lives in `application/timeouts.py`, never in the adapter:
  - `PROTOTYPE_SNAP_WORKER_ATTEST_TIMEOUT_S`, default `5.0`, for `describe`
    and live `attest`.
  - `PROTOTYPE_SNAP_WORKER_ATTEST_MANY_TIMEOUT_S`, default `60.0`, for recovery
    `attestMany`.
  - Invalid or non-positive env values follow the existing timeout accessor
    convention and fall back to the positive default.
  - `bootstrap.py` injects both values explicitly; the adapter constructor
    requires positive values.
- A command batch without Freeform move evidence does not launch the snap
  worker. Undo/Redo replay sealed inverse/forward commands and do not invent
  new snap evidence.

### 4. Validation & Error Matrix

| Condition | Live apply | Recovery | HTTP / retry |
|---|---|---|---|
| Evidence differs from deterministic replay | Refuse before execute/append; preserve active draft | Refuse before replay and mark the exact draft head corrupt | `command_evidence_mismatch`, 422, non-retryable |
| Evidence shape/version/identity is invalid | Refuse before execute/append | Refuse before replay | Deterministic validation error, non-retryable |
| Worker missing, spawn failure, timeout, protocol/identity drift, bad response, or resource limit | Refuse and append no command | Refuse and do not mark an unproven draft corrupt | `snap_worker_*`, 503, retryable |
| `attestMany` response count/order/hash differs | Refuse | Execute zero stored commands | `snap_worker_*`, 503, retryable |
| Recovery tail has no evidence-bearing forward batch | No worker required | Replay validated commands without launching worker | Normal success |
| Recovery tail exceeds 200 entries | Not applicable | Refuse before worker spawn/replay | Bounded recovery error |

Infrastructure error codes are centralized in
`SNAP_WORKER_INFRASTRUCTURE_ERROR_CODES`; do not duplicate partial 503 or
retryable sets in the API layer.

### 5. Good/Base/Bad Cases

- Good: a raw move at `x=76.8592` snaps to a column line at `x=80.6667`,
  persists `axisWinners.x="grid"`, passes worker attestation, reloads to the
  same document hash, and Undo restores the prior hash.
- Good: the same drag with Ctrl/Meta persists `bypassSnapping=true`, no
  candidates, and `rawPosition == finalPosition`.
- Base: a command batch without move evidence applies and recovers without a
  snap worker process.
- Base: a 200-entry dense recovery tail uses one `attestMany` process and the
  60-second recovery deadline, not 200 live `attest` processes.
- Bad: solve against continuous browser coordinates and round only when
  serializing evidence.
- Bad: validate evidence shape in Python and trust the recorded winner without
  replaying the pinned TypeScript solver.
- Bad: use the five-second live deadline for a legal 200-entry dense recovery
  tail.

### 6. Tests Required

- Frontend replay/evidence tests assert canonical rounding, negative-zero
  removal, ID ordering, grid document order, threshold boundaries, Ctrl/Meta
  bypass, candidate count, 512-character `sortKey`, and exact evidence hash.
- Worker protocol tests assert `describe`, `attest`, ordered `attestMany`,
  atomic mismatch refusal, 200-entry limit, 32-MiB input bound, and bounded
  response output.
- Backend contract tests reject candidate/grid/sibling/identity/position and
  command tampering before apply or recovery.
- Backend adapter tests assert manifest/bundle verification, explicit timeout
  injection, live vs recovery timeout routing, request-size refusal before
  spawn, ordered hashes, and one process for `attestMany`.
- Service/API tests assert attest-before-command execution/journal append,
  attestMany-before-replay, live draft preservation, corruption classification,
  retryable 503 infrastructure mapping, and empty-tail worker bypass.
- Timeout tests assert defaults, valid float env values, invalid/non-positive
  fallback, bootstrap injection, Ruff, and Mypy.
- Browser acceptance on `admin-demo` records the pre-move sequence/hash, makes
  one grid-winning drag, verifies evidence v2 and a succeeded operation,
  reloads to the same position/hash, then Undo restores the baseline. Repeat
  once with Ctrl/Meta and assert raw/final equality. Finish with zero browser
  console errors and no test mutation left in the document state.

### 7. Wrong vs Correct

Wrong:

```typescript
const result = solveFreeformMove(rawDomMeasurements);
return roundEvidence(result); // Replay can choose a different winner.
```

Correct:

```typescript
const replay = replayStructuredPrototypeFreeformMove(input);
const evidence = await buildStructuredPrototypeFreeformMoveEvidence(input);
// Both paths canonicalize through the shared replay boundary before solving.
```

Wrong:

```python
worker = PrototypeSnapWorker()  # Adapter silently owns policy defaults.
await worker.attest_many(request_id=request_id, evidence_jsons=evidence_jsons)
```

Correct:

```python
worker = PrototypeSnapWorker(
    attest_timeout_s=timeouts.prototype_snap_worker_attest_timeout_s(),
    attest_many_timeout_s=timeouts.prototype_snap_worker_attest_many_timeout_s(),
)
await worker.attest_many(request_id=request_id, evidence_jsons=evidence_jsons)
```
