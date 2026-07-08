# Fix Over-Defensive Programming Patterns

## Goal

Remove verified over-defensive programming patterns that hide real failures, silently degrade agent/user experience, or add redundant runtime/type-system noise. The goal is not cosmetic minimalism; it is to make critical failures visible, trust internal typed contracts, and keep error handling at the correct system boundaries.

## What I already know

* The user asked to fix the over-defensive patterns found in the current project after a backend + frontend scan.
* The project now has AGENTS.md guidance banning the recurring patterns: fail-open governance gates, `getattr` on typed model fields, silent frontend catches, destructive error recovery, redundant nullish guards, duplicate validation, and `Object.values()` on arrays.
* Backend critical findings include budget/rework/concurrency gates that fail open when their own checks raise unexpectedly.
* Frontend critical findings include silent `.catch(() => {})`, primary page fetches falling back to empty data, destructive log/message clearing on transient errors, `Object.values()` over arrays, and a cast-then-defend payload parser.
* The codebase already has backend error-handling guidance: typed errors at service boundaries, HTTP mapping in routers, and background loop supervision at explicit loop boundaries.
* The frontend type-safety guidance says the frontend trusts `frontend/src/lib/types.ts`; runtime validation belongs at untrusted boundaries such as user input, JSON parsing, SSE, WS, and browser storage.

## Assumptions

* "These issues" means the verified findings listed in `research/defensive-programming-scan.md`, not an open-ended repository-wide cleanup of every defensive-looking line.
* The implementation should prioritize safety and observability over preserving silent degradation behavior.
* Existing legitimate boundary checks should remain: raw JSON parsing, external process output, browser storage, SSE/WS frames, DB legacy rows, and user input.
* New user-visible frontend errors should be modest and localized; this task should not redesign the whole error UI system.

## Requirements

### Backend

* Change governance gates to fail closed where failing open can launch more work or bypass limits:
  * Budget gate failures in conductor tools must refuse dispatch/batch dispatch with a structured error result.
  * Rework-limit graph load failures must not be treated as "no limit applies" unless that state is explicitly distinguishable from an actual absent graph.
  * Specialist concurrency/budget checks must not silently skip enforcement on unexpected exceptions.
* Replace `getattr(..., default)` with direct attribute access for declared dataclass/Pydantic/runtime catalog fields identified in the scan.
* Collapse stacked defensive checks around known internal interfaces where the type/interface contract guarantees the method or field exists.
* Narrow overly broad try/except blocks around internally-safe code; wrap only genuinely fallible calls and log at an appropriate level when best-effort behavior is intended.
* Remove dead try/except code around operations that cannot throw, such as UTF-8 decode with `errors="ignore"`.
* Reduce duplicate validation/duplicate DB fetches only for the verified low-risk cases in the scan, preserving clear ownership between route and service.

### Frontend

* Replace the cast-then-defend budget event handling with explicit narrowing/normalization at the event boundary.
* Remove redundant `Object.values()` calls on arrays in WorkbenchPage.
* Replace silent `.catch(() => {})` with visible or stateful error handling in the verified call sites.
* Preserve previously loaded data on transient process log/message load failures; do not clear data just because a reload failed.
* Remove redundant `?? []`, `|| []`, `?? {}`, optional chaining, and fallback defaults where the declared TypeScript type is non-null/non-optional.
* Remove dead try/catch around date formatting and handle invalid dates explicitly if needed.
* Keep fallbacks where the type actually allows `null` or `undefined`.

### Tests and validation

* Add or update targeted backend tests for fail-closed budget/concurrency/rework behavior where current behavior changes.
* Add or update targeted frontend tests for primary error-state behavior where silent failures are made visible/stateful.
* Run backend checks with pytest wrapped in `timeout` to avoid orphaned tests.
* For frontend validation, prefer `npm run typecheck` over `npm run build` if a dev server may be running, per project memory.

## Acceptance Criteria

* [ ] A bug/exception in budget gate evaluation no longer allows `dispatch_subagent` or `dispatch_batch` to proceed unchecked.
* [ ] A bug/exception in specialist concurrency/budget gating no longer silently bypasses those gates.
* [ ] Verified typed model `getattr(..., default)` call sites are replaced with direct access or moved to an explicit boundary helper if truly untyped.
* [ ] Verified frontend silent catches either set an error state, log with context, rethrow to a boundary, or intentionally degrade with an explicit comment and non-empty UI behavior.
* [ ] Workbench process log/message reload failure no longer clears existing logs/messages.
* [ ] Workbench no longer uses `Object.values()` on `executionProcessesAll` arrays.
* [ ] Verified redundant non-null fallbacks are removed without weakening TypeScript strictness.
* [ ] Targeted tests cover the changed critical behavior.
* [ ] Relevant backend and frontend checks pass, or failures are reported with exact commands/output.

## Definition of Done

* Tests added/updated for behavior changes.
* Backend targeted pytest commands are run via `timeout`.
* Frontend typecheck/test/lint or targeted tests are run as appropriate; avoid `npm run build` while `dev-local.sh` / Next dev is using the same `.next` directory.
* No new broad silent swallowing is introduced.
* AGENTS.md and/or Trellis specs capture any new prevention rules if implementation reveals better project-wide guidance.

## Out of Scope

* Full repository-wide automated rewrite of every `getattr`, `try/except`, `??`, or `?.` occurrence outside the verified scan.
* Introducing a new global frontend toast/error framework.
* Redesigning backend error taxonomy beyond the targeted gate/context fixes.
* Changing database schema.
* Changing conductor architecture or runtime catalog behavior beyond fail-closed error handling.

## Technical Approach

Implement as a focused hardening cleanup in priority order:

1. **Backend gate safety first** — change fail-open governance gates to return explicit refusal results or raise typed errors at the correct boundary; add tests that simulate gate calculation failures.
2. **Backend contract cleanup** — replace verified typed-field `getattr` usage and collapse stacked defenses around known interfaces.
3. **Frontend error visibility** — replace silent catches and destructive empty-state fallbacks with local error state while preserving stale data.
4. **Frontend mechanical type cleanup** — remove redundant fallbacks/optional chaining and `Object.values()` over arrays.
5. **Verification** — run targeted tests first, then broader backend/frontend checks as time permits and as safe for the active dev-server state.

## Decision (ADR-lite)

**Context**: The scan showed that AI-written defensive code made important failures invisible: budget/concurrency gates could silently disable, context could be dropped from agent prompts, and frontend pages could become empty without any error. This is especially risky in an agent orchestration product because silent degradation affects cost, execution safety, and debugging.

**Decision**: Treat typed internal contracts as trusted and move defensive handling to real boundaries. Governance gates must fail closed. Frontend errors must be observable through state/UI or logged context rather than swallowed. Redundant type fallbacks are removed where the type system already guarantees the value.

**Consequences**: Some previously silent failures will now surface as explicit errors or refused dispatches. This may expose latent bugs sooner, but that is intended. Legitimate best-effort paths remain allowed when they log with context and do not mask critical behavior.

## Research References

* [`research/defensive-programming-scan.md`](research/defensive-programming-scan.md) — verified backend/frontend findings and recommended fix directions from the defensive-programming scan.

## Technical Notes

* Relevant prevention guidance was added to root `AGENTS.md` outside the Trellis-managed block.
* Backend spec references:
  * `.trellis/spec/vibe-kanban/backend/index.md`
  * `.trellis/spec/vibe-kanban/backend/error-handling.md`
  * `.trellis/spec/vibe-kanban/backend/quality-guidelines.md`
  * `.trellis/spec/vibe-kanban/backend/logging-guidelines.md`
  * `.trellis/spec/vibe-kanban/backend/database-guidelines.md`
* Frontend spec references:
  * `.trellis/spec/ccgui/frontend/index.md`
  * `.trellis/spec/ccgui/frontend/quality-guidelines.md`
  * `.trellis/spec/ccgui/frontend/type-safety.md`
  * `.trellis/spec/ccgui/frontend/state-management.md`
* Shared thinking reference:
  * `.trellis/spec/guides/index.md`
