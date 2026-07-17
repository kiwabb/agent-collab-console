# Runtime Core Spike Evidence

Date: 2026-07-13

## Completed Scope

- Added the shared TypeScript runtime core under `frontend/src/features/prototype/runtime/`.
- Pinned XState to exactly `5.32.4`; persisted state records both the runtime-core and kernel versions.
- Added typed runtime values, forms, mock entities, roles, rules, guards, ordered effects, view bindings and semantic event batches.
- Added strict canonical JSON, SHA-256 state/view-model hashes and deterministic UUIDv5 entity allocation.
- Added a strict runtime-state JSON codec. Shape, unknown fields, runtime versions and definition references fail closed before XState starts.
- Added the locked procurement scenario: applicant enters and submits a request, switches to manager, approves it, and observes synchronized table/detail status.
- Added per-event/per-effect hash evidence and explicit stale-sequence, validation and guard-false outcomes.

## Compatibility Fixture

Runtime core: `0.1.0-spike`

XState kernel: `5.32.4`

Session: `compatibility-runtime-session`

Entity UUID: `d1a600e6-855f-5ad0-8b8b-56e87a48de90`

| Sequence | Result state hash | Result view-model hash |
| --- | --- | --- |
| 1 | `sha256:dc52aef9d3b808020a4eee0156d53fe83d280dafacbcf22024b86d4b14d46194` | `sha256:8a08372298a0bffdc8540c54e5f00f83baeda4e17f6c02337cf27cb478dfcb6c` |
| 2 | `sha256:0f746c88f7b4aa7226047f6ac7e3f6c08d4f031a8e40a1d70c555e074af4be54` | `sha256:9bbcc45f6f923ece4e461f3ec96af5e6a6a9a4201a46e0d229effa8fc0d7fd43` |
| 3 | `sha256:fdfa2274b2a58f387a527cabd5517e7b5d33cdb5373c168d3e6d5a79da66ff4c` | `sha256:83ad5001aa21d47d77b6e521263fd8754d040305dee8f89bfd20612b693e7646` |

The fixture is asserted by `frontend/tests/prototypeRuntimeCore.test.ts`. An XState or runtime-core upgrade must intentionally update the version and fixture together.

## Verification

All commands ran from `frontend/`:

```text
npm run typecheck                                      PASS
npm run lint                                           PASS
npm run format:check                                   PASS
npm audit --registry=https://registry.npmjs.org        PASS, 0 vulnerabilities
npm audit --omit=dev --registry=https://registry.npmjs.org  PASS, 0 vulnerabilities
npm test                                               PASS, 462/462
npm run build                                          PASS, Next.js 15.5.20
```

The focused runtime suite contains 12 passing cases for cross-language canonical JSON, validation refusal, deterministic allocation, role switching, synchronized approval state, JSON replay parity, pinned hashes, guard refusal, stale sequence, incompatible kernel refusal, invalid view bindings and strict codec behavior.

The Python and TypeScript canonicalizers also pin the same non-BMP Unicode fixture to `sha256:13b8db984e15a32f530afbda948a2f354b9fb276e6e73c16c45e0427a26cbfd5`.

## Browser Parity Gate

Completed on 2026-07-13 through the client-only Next.js diagnostic route `/prototype-runtime-parity` in the Codex in-app browser.

```text
Browser probe status             passed
matchesPinnedFixture             true
runtimeCoreVersion               0.1.0-spike
stateMachineKernelVersion        5.32.4
deterministic entity UUID        d1a600e6-855f-5ad0-8b8b-56e87a48de90
browser console warnings/errors  0
```

The browser returned the same three state and view-model hash pairs listed in the compatibility table above. The route runs `runProcurementApprovalScenario(...)` inside a `"use client"` component and exposes the result only as diagnostic `data-*` evidence; it does not use a server route or a Node-computed response.

Frontend verification after adding the probe:

```text
npm run typecheck                                             PASS
npm run lint -- --quiet                                      PASS
runtime core + browser parity node tests                     PASS, 13/13
real in-app browser parity and console inspection            PASS
```

This clears the browser/Node parity prerequisite for persistent runtime sessions. The probe does not yet persist a session or connect the Studio preview to the draft API.
