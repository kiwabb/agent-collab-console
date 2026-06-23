# brainstorm: self improvement application audit and rollback

## Goal

Make reviewed self-improvement application trustworthy enough to operate: every
project-memory apply/rollback should leave a durable event record, operators
should be able to list those events by project/proposal, and applied
project-memory proposals should be reversible by removing their exact marker
block from `.agent-collab/team_notes.md`.

## What I already know

* PR #25 added dry-run apply plans.
* PR #27 added a hash-gated reviewed apply endpoint for accepted
  `project_memory` proposals.
* The Moonshot requires self-improvement that is not just powerful, but
  auditable, reversible, and safe to expose.
* Existing `apply-plan` remains non-mutating and should stay that way.
* Existing non-memory targets (`code_spec`, `conductor_policy`,
  `runtime_tooling`, `benchmark_eval`) must not be directly applied or rolled
  back by this slice.

## Requirements

* Add a durable `self_improvement_application_events` table.
* Add a domain model for application events with:
  `id`, `proposal_id`, `project_id`, `issue_id`, `target_kind`, `action`,
  `status`, `path`, `content_sha256`, `result_json`, `error`, `created_at`.
* Add async and sync store methods:
  `save_self_improvement_application_event(event)` and
  `list_self_improvement_application_events(project_id=None, proposal_id=None, limit=None)`.
* Record a successful `apply` event when the reviewed project-memory apply
  endpoint appends or detects the marker and marks the proposal `applied`.
* Record a failed `apply` event when the apply service rejects or cannot write
  after proposal/project resolution.
* Add `GET /api/codex/projects/{project_id}/self-improvement-proposals/{proposal_id}/applications`.
* Add `POST /api/codex/projects/{project_id}/self-improvement-proposals/{proposal_id}/rollback`.
* Rollback is allowed only for `status == "applied"` and
  `target_kind == "project_memory"`.
* Rollback removes the block marked
  `<!-- self-improvement-proposal:{proposal.id} -->` from
  `.agent-collab/team_notes.md`, records a rollback event, and marks the
  proposal back to `accepted` so it can be reviewed/reapplied.
* Rollback must be idempotent when the marker is already absent: record
  `already_absent: true`, mark the proposal accepted, and do not fail.
* Failed rollback requests must not change proposal status.

## Acceptance Criteria

* [ ] Store tests cover async and sync save/list/filter events.
* [ ] Apply endpoint success records a `succeeded` apply event with path, hash,
  and result metadata.
* [ ] Apply endpoint failure after proposal/project resolution records a
  `failed` apply event and leaves proposal/file state unchanged.
* [ ] Applications list endpoint returns project-scoped event JSON in newest
  first order and hides cross-project proposals.
* [ ] Rollback endpoint removes the project-memory marker block, marks proposal
  accepted, and records a `succeeded` rollback event.
* [ ] Rollback endpoint is idempotent when the marker block is already absent.
* [ ] Rollback rejects non-memory targets and non-applied statuses with `409`.
* [ ] Store unavailable returns `503`; unknown project/proposal/cross-project
  proposal returns existing `404` shapes.
* [ ] Existing dry-run apply-plan remains non-mutating.

## Definition of Done

* TDD red/green evidence for store, service, and API behavior.
* Backend spec updated with executable contracts, error matrix, and wrong/correct
  examples.
* Focused self-improvement tests pass.
* Full backend suite is run before PR/merge unless an environment blocker is
  documented.
* PR is opened, CI passes, merged, and this Trellis task is archived with a
  journal entry.

## Out of Scope

* Applying or rolling back non-memory target kinds.
* A frontend UI for application event history.
* General-purpose file patch rollback.
* Deleting application event rows.
* Marking the full Moonshot complete.

## Technical Notes

* Existing apply service:
  `backend/app/application/self_improvement_apply_service.py`.
* Existing API routes:
  `backend/app/interfaces/api.py`.
* Existing proposal persistence:
  `backend/app/adapters/async_sqlite_store.py` and
  `backend/app/adapters/sqlite_store.py`.
* Existing self-improvement tests:
  `backend/tests/test_self_improvement_api.py`,
  `backend/tests/test_self_improvement_apply_service.py`,
  `backend/tests/test_self_improvement_store.py`.
* Existing backend spec:
  `.trellis/spec/vibe-kanban/backend/database-guidelines.md`.
