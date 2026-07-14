# Prototype Generation Acceptance Retrospective

## Bug Analysis: Project-driven planning and generation failed at completion boundaries

### 1. Root Cause Category

| Failure | Category | Specific cause |
|---------|----------|----------------|
| HTML stopped at the model token limit | B - Cross-Layer Contract, E - Implicit Assumption | The direct HTTP path treated a complete HTML document as ordinary assistant text. Raising `max_tokens` changed the failure frequency but did not provide a completion proof or remove the full document from the response channel. |
| Planning returned invalid or truncated JSON | B - Cross-Layer Contract, E - Implicit Assumption | Tolerant JSON repair ran at an external boundary without first proving that the response was one complete object. A truncation could therefore be confused with provider-specific quote drift. |
| Concurrent generate requests created a race | B - Cross-Layer Contract | Idempotence depended on a service-local plan lock. Two service instances with separate SQLite connections could both pass the check, and the first run could become terminal before the second freeze. |
| Legacy rows had empty evidence references or restore seeds | C - Change Propagation Failure | New columns used SQL defaults (`[]` and an empty string), but those defaults were not valid semantic values for existing retryable rows. The schema migrated while the domain contract did not. |
| Plan and generation live recovery drifted | C - Change Propagation Failure, B - Cross-Layer Contract | The two SSE flows evolved independently. Resource identity, heartbeat, silence detection, polling limits, and stale-data behavior were not one shared transport contract. |
| Progress and item status meanings diverged | C - Change Propagation Failure | Backend persistence, SSE payloads, and React rendering each interpreted terminal states and counters. The UI used successful `completed` as the progress numerator, so an 8-success/5-failure terminal run appeared incomplete. |
| zh-CN planning rejected `default` states | B - Cross-Layer Contract | The prompt defined `states` with the machine identifier `default`, while locale validation treated the same field as user-facing prose. UI-semantic planning also bypassed the UI-engineer runtime entirely. |
| Valid HTML was rejected because of Claude's tool sequence | B - Cross-Layer Contract, E - Implicit Assumption | The backend treated Write/Edit/Bash logs as the artifact contract, replayed model mutations, and rejected any equally valid file produced through a different tool strategy. Tool logs also duplicated full HTML into audit surfaces. |
| A committed version could be reported as failed | B - Cross-Layer Contract | SQLite completion could commit and then raise at the caller boundary. The worker assumed every exception meant rollback and overwrote the item as failed without reconciling the exact version ID. |

### 2. Why Earlier Fixes Failed

1. Increasing the direct generator token ceiling reduced truncation but retained the architecture that sends the entire HTML document through one bounded model response.
2. Adding tolerant JSON parsing fixed known MiniMax quote defects but did not distinguish repairable syntax drift from incomplete, fenced, prefixed, or multiple JSON documents.
3. Adding an `asyncio.Lock` serialized one service object only; it could not protect the shared SQLite state from a second service instance or process.
4. Adding nullable/defaulted columns made old rows loadable but silently created values that could not support evidence traceability or deterministic retry.
5. Adding an `EventSource` made progress look live on the happy path, but an open buffered connection was mistaken for freshness and refresh reconstruction remained incomplete.
6. Adding more frontend status labels duplicated lifecycle rules instead of establishing one persisted snapshot contract and validating it at the transport boundary.
7. Enforcing locale on every string field ignored the distinction between human copy and stable identifiers, and left UI analysis on the generic HTTP planner instead of the UI-engineer role.
8. Adding Write/Edit chunk limits and Bash inspection fixed individual audit-replay mismatches by further constraining Claude. It did not improve final artifact integrity and repeatedly converted valid autonomous work into new protocol errors.
9. Catching completion exceptions and immediately marking the item failed assumed transaction outcome was always known. That assumption fails when the commit succeeded before the exception crossed the store boundary.

### 3. Prevention Mechanisms

| Priority | Mechanism | Specific Action | Status |
|----------|-----------|-----------------|--------|
| P0 | Architecture | Use the Claude Code runtime to write HTML into an isolated staging artifact; keep the final assistant response to a strict manifest. | DONE |
| P0 | Runtime validation | Validate only the final staged file, strict manifest/path/checksum/HTML/external-resource policy, and source-tree integrity. Never inspect or replay Claude's tool sequence. | DONE |
| P0 | Boundary validation | Prove a complete single-object envelope before tolerant repair, then run strict Pydantic, candidate, evidence, and locale validation. | DONE |
| P0 | Database ownership | Freeze run, run items, source-backed prototypes, plan links, and restore seeds in one `BEGIN IMMEDIATE` transaction. | DONE |
| P0 | Commit reconciliation | Preallocate immutable version IDs and reload item/version state after an indeterminate completion exception before writing failure. | DONE |
| P0 | Migration | Backfill v7 evidence IDs and seed briefs from legacy durable data; abort migration when a retryable row cannot be reconstructed. | DONE |
| P0 | Agent trajectory | Persist complete prototype runtime frames, thinking, tools, commands, messages, results/HTML, traces, status, and audit payloads; keep them out of artifact validation. | DONE |
| P1 | Transport contract | Persist progress, emit resource-scoped snapshots and heartbeat, and use bounded REST polling after silence/disconnect while retaining stale data. | DONE |
| P1 | Type contract | Validate exact nested plan/run/item/evidence shapes and the item lifecycle matrix before React state mutation. | DONE |
| P1 | Test coverage | Cover EOF without `message_stop`, incomplete/multiple planning JSON, cross-service terminal races, v7 legacy rows, recovery exhaustion, resource mismatch, and counter invariants. | DONE |
| P2 | Documentation | Record the executable contracts in backend, frontend, and cross-layer Trellis specs. | DONE |
| P0 | Responsibility boundary | Route UI-semantic planning and HTML restoration through `prototype_ui_engineer`; validate `states` as lowercase kebab-case identifiers outside locale checks. | DONE |

### 4. Systematic Expansion

- **Similar Issues**: Any workflow that asks a model to return a large artifact or structured JSON can repeat the same truncation/repair confusion. Any in-memory lock used to protect database state has the same multi-instance gap. Any audit trace that copies tool inputs can become an unintended artifact store.
- **Design Improvement**: Treat files as artifacts, complete model/tool history as observability and continuation data, SQLite transactions as the idempotence owner, and persisted snapshots as the only recoverable lifecycle source of truth.
- **Process Improvement**: Acceptance must include a valid artifact produced through an arbitrary tool sequence, exact wire-prompt capture, commit-then-raise fault injection, complete trajectory sentinels, a terminal partial-success run, a service-instance race, a restart/legacy database, and an SSE silence path.
- **Autonomy Boundary**: A repository-capable agent owns code discovery and file creation strategy. The backend owns repository isolation, final artifact validation, source integrity, durable persistence, and safe audit metadata. A pre-tool allow/deny hook is not part of this product contract.

### 5. Knowledge Capture

- [x] Update the backend database contract for complete model envelopes, artifact staging, transactional freeze semantics, and v7 semantic backfills.
- [x] Update canonical and alias frontend state-management contracts for resource-scoped SSE plus bounded polling recovery.
- [x] Update canonical and alias frontend type-safety contracts for exact prototype snapshots and lifecycle invariants.
- [x] Update the cross-layer thinking guide with completion-proof, semantic-migration, and durable-recovery checks.
- [x] Keep regression coverage in the focused backend and frontend suites.
- [x] Add arbitrary-tool final-artifact acceptance, exact wire-prompt, commit-reconciliation, complete runtime trajectory, and v8 history-preservation tests.
- [x] Record the complete runtime/audit persistence contract and separate final-result validation boundary in backend specs.
