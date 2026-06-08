# Self Improvement Proposal Review API

## Goal

Close the next loop in the self-improvement system: proposals are already extracted and stored after issue completion, but operators and later automation cannot record whether a proposal was accepted, rejected, or applied. Add a safe review API so the ledger becomes measurable feedback instead of a write-only inbox.

This moves the Moonshot self-improvement ladder forward without crossing into unsafe recursive self-modification. The system remains review-only: it updates proposal status and audit metadata, but does not automatically edit memory, specs, policies, tools, or code.

## What I Already Know

* The first self-improvement slice is merged and archived in `06-08-self-improvement-loop`.
* The approved design in `docs/superpowers/specs/2026-06-08-self-improvement-loop-design.md` explicitly made accept/reject/apply mutation endpoints out of scope for the first slice.
* Current backend has:
  * `SelfImprovementProposal` domain model in `backend/app/domain/models.py`;
  * `self_improvement_proposals` SQLite tables in sync and async stores;
  * `save_self_improvement_proposal(...)` and `list_self_improvement_proposals(...)`;
  * deterministic extraction in `backend/app/application/self_improvement_service.py`;
  * terminal sealing hook after `record_project_memory(...)`;
  * `GET /api/codex/projects/{project_id}/self-improvement-proposals`;
  * tests for extraction, persistence, API shape/filtering, and seal behavior.
* Existing `SelfImprovementProposal.status` values already include observed examples of `proposed` and `accepted`; the design lists `proposed`, `accepted`, `rejected`, and `applied`.
* There is currently no API to transition proposal status or persist reviewer feedback.

## Assumptions

* The MVP should add backend review/status transitions only; no frontend inbox in this slice.
* The API should be project-scoped to avoid changing a proposal from the wrong project.
* Status transitions should be conservative:
  * `proposed -> accepted`;
  * `proposed -> rejected`;
  * `accepted -> applied`;
  * idempotent repeat of the current status is allowed;
  * reverting `rejected` or `applied` is out of scope.
* Reviewer notes are valuable, but adding a new column is not required for the first safe slice if the API can update status and `updated_at`. If notes are added, sync and async stores need migration tests.

## Open Questions

* Should the first mutation API store a reviewer note now, or keep this slice status-only?

Recommended answer: status-only for this slice. It unlocks measurable accept/reject/apply counts with no schema migration and keeps the change small. A follow-up can add reviewer notes/audit rows once the status contract is in place.

## Requirements

* Add a backend API to update one self-improvement proposal's status.
* Validate project ownership and proposal existence.
* Enforce safe status transitions.
* Keep response shape consistent with the existing proposal list endpoint.
* Preserve the review-only boundary: status updates do not mutate team notes, `.trellis/spec`, conductor policy, tools, or code.
* Cover sync/async store behavior and API behavior with tests.

## Acceptance Criteria

* [ ] `PATCH /api/codex/projects/{project_id}/self-improvement-proposals/{proposal_id}` can move a proposal from `proposed` to `accepted`.
* [ ] The same endpoint can move a proposal from `proposed` to `rejected`.
* [ ] The same endpoint can move a proposal from `accepted` to `applied`.
* [ ] Invalid transitions return `409`.
* [ ] Unknown project/proposal returns the existing API style (`404`), and unavailable store returns `503`.
* [ ] Response body is the same proposal object shape as the list endpoint.
* [ ] Store-level tests prove status updates preserve all non-status fields and update `updated_at`.
* [ ] No automatic memory/spec/policy/tool/code mutation happens in this slice.

## Proposed Design

### Recommended Approach: Status-Only Review Mutation

Add store methods to get and update proposals:

* `load_self_improvement_proposal(proposal_id: str)`;
* `update_self_improvement_proposal_status(proposal_id: str, status: str)`.

Add an API request body:

```json
{"status": "accepted"}
```

The API validates:

* project exists;
* proposal exists and belongs to the project;
* requested status is one of `accepted`, `rejected`, `applied`;
* transition is legal.

The API returns `_self_improvement_proposal_to_dict(updated_proposal)`.

Why this approach: it creates a measurable feedback loop with minimal blast radius and no schema migration.

### Alternatives Considered

1. Add reviewer notes in the same slice.
   This is useful but requires schema/migration changes across sync and async stores. It can follow once status transitions are proven.

2. Auto-apply accepted `project_memory` proposals into team notes.
   This moves closer to recursive self-improvement, but it crosses the confirmed first-slice safety boundary and needs rollback/audit semantics.

3. Add frontend review UI first.
   Backend mutation is the missing contract. UI can be layered on after the API is stable.

## Definition of Done

* Backend tests cover valid and invalid transitions.
* Store tests cover load/update behavior for sync and async stores.
* Existing self-improvement proposal list endpoint tests still pass.
* `python3 -m py_compile` passes for changed backend modules.
* Relevant backend test subset passes.
* `.trellis/spec/vibe-kanban/backend/quality-guidelines.md` records the review mutation contract if implementation changes backend API/store behavior.

## Out of Scope

* Frontend proposal inbox.
* Reviewer notes/audit trail columns.
* Auto-applying proposals to memory/spec/policy/tool/code.
* LLM-based proposal ranking or deduplication.
* Benchmark harness scoring changes.

## Technical Notes

* Existing API code: `backend/app/interfaces/api.py::_self_improvement_proposal_to_dict` and `codex_project_self_improvement_proposals`.
* Existing stores: `backend/app/adapters/async_sqlite_store.py` and `backend/app/adapters/sqlite_store.py`.
* Existing tests: `backend/tests/test_self_improvement_api.py`, `backend/tests/test_self_improvement_store.py`, `backend/tests/test_self_improvement_service.py`.
* Relevant design: `docs/superpowers/specs/2026-06-08-self-improvement-loop-design.md`.
