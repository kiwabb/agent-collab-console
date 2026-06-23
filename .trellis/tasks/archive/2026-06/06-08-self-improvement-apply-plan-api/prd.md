# Self Improvement Accepted Proposal Apply Plan API

## Goal

Move the self-improvement loop one step closer to safe recursive self-application. Proposals can now be extracted, listed, and reviewed, but an accepted proposal still has no structured path toward becoming a concrete change. Add a backend dry-run apply-plan API that turns an accepted proposal into an auditable, machine-readable plan without mutating memory, specs, prompts, tools, or code.

This keeps the current safety boundary intact while creating the next control-plane contract needed for future autonomous PR creation.

## What I Already Know

* The merged proposal ledger creates `SelfImprovementProposal` rows from terminal issue evidence.
* PR #23 added project-scoped status review:
  * `proposed -> accepted`;
  * `proposed -> rejected`;
  * `accepted -> applied`;
  * idempotent repeats.
* The current backend contract explicitly says the review API is status-only and must not auto-apply changes.
* Existing project memory writes to `<repo>/.agent-collab/team_notes.md` through `ProjectMemoryService`.
* Team notes are prompt-visible, block-aware, soft-deletable, and pinned through `TeamNotesService`, but proposal review is not connected to a safe apply path yet.

## Assumptions

* This slice should not change proposal status to `applied`; it only produces a dry-run plan.
* The first apply plan should be deterministic and safe enough for tests. LLM drafting/ranking can follow later.
* `project_memory` proposals can expose a concrete candidate markdown block and target path.
* `code_spec`, `conductor_policy`, `runtime_tooling`, and `benchmark_eval` proposals should return a PR/task-oriented plan rather than guessing which source file to edit.

## Recommended Design

Add:

`POST /api/codex/projects/{project_id}/self-improvement-proposals/{proposal_id}/apply-plan`

The endpoint:

* verifies the store and project as existing endpoints do;
* loads the proposal and hides cross-project proposals as `404`;
* requires `proposal.status == "accepted"`;
* returns `409` for `proposed`, `rejected`, or `applied`;
* returns no filesystem or database mutations.

Response shape:

```json
{
  "proposal": { "...same shape as proposal list item..." },
  "plan": {
    "mode": "dry_run",
    "target_kind": "project_memory",
    "can_auto_apply": false,
    "summary": "Append a reviewed lesson to team notes.",
    "steps": ["..."],
    "candidate_changes": [
      {
        "kind": "append_markdown",
        "path": ".agent-collab/team_notes.md",
        "content": "..."
      }
    ],
    "risk": "low",
    "next_action": "review_then_apply"
  }
}
```

For non-`project_memory` target kinds, the plan should produce `kind: "open_pr_task"` candidate changes with a task title/body, evidence, and suggested verification angle. The API should not pretend it can safely patch `.trellis/spec` or runtime code yet.

## Alternatives Considered

1. Auto-append accepted `project_memory` proposals to `team_notes.md`.
   This is tempting, but it crosses the current review-only boundary and creates rollback/editorial questions. The apply-plan contract should land first.

2. Add a full audit/apply table now.
   Useful eventually, but this slice can produce a deterministic dry-run plan without another schema migration.

3. Build a frontend inbox first.
   Operators need a backend contract before UI can safely offer an "apply" button.

## Requirements

* Add an application-layer helper that builds apply plans from accepted proposals.
* Add a project-scoped dry-run apply-plan API endpoint.
* Preserve the existing proposal object serialization in the response.
* Do not mutate proposal status, team notes, `.trellis/spec`, prompts, policies, tools, code, or other memory rows.
* Cover API behavior and plan helper behavior with tests.
* Update backend Trellis spec to record the apply-plan contract.

## Acceptance Criteria

* [ ] Accepted `project_memory` proposal returns a dry-run plan with `.agent-collab/team_notes.md` append markdown content.
* [ ] Accepted non-memory proposals return a dry-run PR/task plan and do not guess a direct file patch.
* [ ] `proposed`, `rejected`, and `applied` proposals return `409`.
* [ ] Unknown project/proposal or cross-project proposal returns `404`.
* [ ] Store unavailable returns `503`.
* [ ] The endpoint does not change proposal status or write files.
* [ ] The response includes the same proposal object shape as existing list/PATCH endpoints.

## Definition of Done

* Focused backend tests pass.
* Existing self-improvement proposal API tests still pass.
* `py_compile`, import smoke, and `git diff --check` pass.
* Full backend test suite considered before PR.
* `.trellis/spec/vibe-kanban/backend/database-guidelines.md` documents the apply-plan boundary.

## Out of Scope

* Actually writing `team_notes.md`.
* Changing proposal status to `applied`.
* Editing `.trellis/spec`, prompts, tools, policies, or source code.
* LLM-generated patches.
* Frontend inbox or apply button.
* New database table for apply attempts.

## Technical Notes

* Existing API area: `backend/app/interfaces/api.py` near self-improvement proposal routes.
* Existing proposal model: `backend/app/domain/models.py::SelfImprovementProposal`.
* Existing stores: `load_self_improvement_proposal(...)` and status update methods already exist.
* Existing team notes target constants:
  * `backend/app/application/project_memory_service.py::MEMORY_DIR_NAME`
  * `backend/app/application/project_memory_service.py::MEMORY_FILE_NAME`
* Existing tests to extend:
  * `backend/tests/test_self_improvement_api.py`
  * new focused service test if the plan builder is factored into `backend/app/application/self_improvement_apply_service.py`.
