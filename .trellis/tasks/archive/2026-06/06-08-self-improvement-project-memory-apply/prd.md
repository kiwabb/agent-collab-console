# brainstorm: reviewed self-improvement project memory apply

## Goal

Advance the self-improvement loop from dry-run planning to the first reviewed,
auditable application path. Accepted `project_memory` proposals should be able
to append their reviewed markdown candidate into `.agent-collab/team_notes.md`
and mark the proposal `applied`, while preserving the existing non-mutating
`apply-plan` contract and refusing direct application for higher-risk targets.

## What I already know

* The active Moonshot goal requires recursive self-improvement with review,
  testing, auditability, and operational trust.
* PR #25 added a non-mutating `apply-plan` API for accepted proposals.
* The existing approved self-improvement design says the first slice is
  review-only; later recursive self-improvement must be reviewable,
  measurable, and reversible.
* The backend spec explicitly forbids `apply-plan` from writing files or
  changing proposal status.
* Existing proposal review already allows `accepted -> applied`, but it records
  status only and does not tie application to an exact reviewed change.

## Assumptions

* The next safe increment is not auto-applying specs, prompts, policies, tools,
  or code. It is a hash-gated application path for low-risk project memory only.
* The caller reviews the dry-run `append_markdown` candidate first, then sends a
  hash of that exact content to the apply endpoint.
* Appending the same proposal twice should be idempotent when the marker already
  exists in `team_notes.md`.

## Requirements

* Add a reviewed apply API for accepted `project_memory` proposals:
  `POST /api/codex/projects/{project_id}/self-improvement-proposals/{proposal_id}/apply`.
* The request must include the reviewed candidate content hash.
* The backend must rebuild the current apply plan, compute the candidate content
  hash, and reject the request if it does not match.
* The endpoint must append the reviewed markdown candidate to
  `.agent-collab/team_notes.md` and mark the proposal `applied`.
* Repeating the same apply request after the marker is already present must not
  duplicate the markdown.
* Non-`project_memory` target kinds must not write files; they should return a
  conflict telling the caller to use a reviewed PR/task flow.
* Existing `apply-plan` behavior must remain non-mutating.
* Existing review status transitions must remain conservative.

## Acceptance Criteria

* [ ] Accepted `project_memory` proposal + matching content hash appends to
  `.agent-collab/team_notes.md` and returns the updated `applied` proposal.
* [ ] Repeating the request does not append a duplicate block and remains
  stable.
* [ ] Mismatched content hash returns `409` and writes nothing.
* [ ] `proposed`, `rejected`, or already `applied` proposal returns `409` and
  writes nothing.
* [ ] Unknown project, unknown proposal, and cross-project proposal keep the
  existing `404` behavior.
* [ ] Store unavailable returns `503`.
* [ ] Non-memory proposal returns `409` and writes nothing.
* [ ] Project repo path missing/unusable returns a server error without marking
  the proposal applied.
* [ ] Focused backend tests pass.
* [ ] Full backend suite is run before PR/merge unless an environment blocker is
  documented.

## Definition of Done

* Tests added or updated for the apply service and API endpoint.
* Existing dry-run apply-plan tests still prove no mutation.
* Backend spec documents the reviewed memory-apply contract and its wrong/correct
  examples.
* Lint/type-check/test gates are attempted; unavailable tools are reported.
* PR is opened, CI is green, merged, and the Trellis task is archived with a
  journal entry.

## Out of Scope

* Directly applying `code_spec`, `conductor_policy`, `runtime_tooling`, or
  `benchmark_eval` proposals.
* Editing `.trellis/spec/`, prompts, policies, tools, source code, or benchmark
  manifests from this endpoint.
* Creating a frontend inbox or review UI.
* Persisting a separate application-audit table. This slice relies on proposal
  status, team-notes marker, returned hash/path metadata, tests, and reviewed PR
  history; richer audit rows can be the next increment.

## Technical Notes

* Existing apply-plan builder:
  `backend/app/application/self_improvement_apply_service.py`.
* Existing self-improvement API routes:
  `backend/app/interfaces/api.py`.
* Existing project memory constants and trimming behavior:
  `backend/app/application/project_memory_service.py`.
* Backend self-improvement contracts:
  `.trellis/spec/vibe-kanban/backend/database-guidelines.md`.
* The dry-run candidate already includes a stable marker:
  `<!-- self-improvement-proposal:{proposal.id} -->`.
* The service should use the existing candidate content rather than recomputing
  markdown in a second format.
