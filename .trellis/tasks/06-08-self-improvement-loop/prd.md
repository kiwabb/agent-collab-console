# Brainstorm: Self Improvement Loop

## Goal

Turn issue completion into a productized self-improvement loop: after an issue
finishes, the system should extract lessons from the actual execution evidence,
classify which lessons are actionable, and produce auditable improvement
proposals for memory/spec/policy/tooling. This is the next step from "we can
manually update Trellis specs after a session" toward an autonomous engineering
organization that learns from every issue without relying on a human operator to
remember the lesson.

## What I Already Know

* The Moonshot requires a measurable self-improvement curve: every issue should
  feed back into prompts, policies, tools, and eventually the system's own code.
* Current backend has deterministic cross-issue project memory in
  `backend/app/application/project_memory_service.py`.
* Current issue Conductor calls `record_project_memory(...)` when a workflow
  graph reaches `done`, then best-effort updates `.agent-collab/team_notes.md`.
* `ProjectConductor` already has hot/warm/cold memory state and lexical cold
  retrieval in `backend/app/application/project_conductor.py`.
* Trellis already has a manual code-spec capture workflow in
  `.agents/skills/trellis-update-spec/SKILL.md`; it requires concrete
  executable contracts, signatures, matrices, and tests.
* Current memory summaries are mostly project/team notes. They are not yet
  structured improvement records, do not propose spec/policy/tool changes, and
  do not measure whether later issues benefited from earlier lessons.
* The last completed slice added a deterministic Conductor orchestration policy,
  a UI decision explanation panel, runtime hardening, and code-spec memory. That
  work exposed the exact manual behavior this task should begin automating.

## Assumptions (Temporary)

* The MVP should create reviewable improvement proposals, not silently mutate
  prompts, specs, policies, or code.
* The backend should own extraction and persistence; the frontend may later show
  proposals, but the first useful slice can be API/test driven.
* Extraction should be evidence-first: conductor tasks, QA reports, changed
  files, test commands, failures, retries, and final status are stronger inputs
  than a final LLM summary alone.
* The proposal model should be useful even without an LLM. A deterministic first
  pass can classify obvious lessons; optional LLM distillation can come later.

## Open Questions

* For MVP, should improvement proposals stay review-only, or should low-risk
  memory/spec updates be applied automatically after QA passes?

## Requirements (Evolving)

* Add a structured self-improvement artifact produced after issue completion.
* Extract lessons from actual issue evidence, including:
  * final issue / workflow status;
  * Conductor task results and tool events;
  * QA verdict and commands run;
  * implementation artifacts and changed files when available;
  * failures/retries/stalls encountered during the issue.
* Classify lessons by target:
  * project memory / team notes;
  * code-spec update;
  * conductor policy / prompt rule;
  * runtime/tooling hardening;
  * benchmark/evaluation gap.
* Store proposals durably with enough metadata to review, deduplicate, and audit:
  issue id, project id, evidence pointers, recommendation text, target kind,
  confidence/severity, status, created/updated timestamps.
* Do not silently modify code, specs, or policy in the first slice.
* Surface enough API/UI shape for a future reviewer workflow, even if the first
  implementation only includes backend tests and a minimal endpoint.
* Keep the loop best-effort: proposal extraction failure must not fail a
  completed issue.
* Make the output measurable: track count of proposals produced, accepted,
  rejected, and later referenced by similar issues.
* Keep proposal extraction idempotent. Re-running terminal sealing or recovery
  for the same issue must update/skip existing proposals instead of producing
  unbounded duplicates.
* Keep `record_project_memory(...)` as a separate existing memory path. This
  task can share evidence readers, but should not collapse structured proposals
  into plain team notes.

## Acceptance Criteria (Evolving)

* [ ] A completed issue can trigger a self-improvement extraction step.
* [ ] Extraction produces at least one durable proposal when evidence includes a
      QA failure, runtime failure, repeated retry, or newly learned contract.
* [ ] A clean trivial issue can produce no proposal without being treated as an
      error.
* [ ] Proposals include evidence pointers and a target kind.
* [ ] Proposal extraction is idempotent per issue and target lesson.
* [ ] Backend tests cover done issue, failed issue, no-op issue, and duplicate
      extraction.
* [ ] The feature does not break existing `record_project_memory(...)` behavior.

## Candidate Approaches

### Approach A: Review-Only Proposal Ledger (Recommended)

Create a `self_improvement_proposals` store/API surface and write proposals
after issue terminal state. This gives auditability and lets humans/agents
approve before mutating specs or policy. It is the safest path toward recursive
self-improvement because every proposed change has evidence and status.

Trade-off: it adds one more review queue before changes become active.

### Approach B: Extend `team_notes.md` Only

Append structured "lessons" into `.agent-collab/team_notes.md` and rely on the
existing memory injection path. This is cheap and keeps all memory in-repo.

Trade-off: it cannot distinguish accepted/rejected proposals, target code-spec
contracts, or measure improvement outcomes cleanly.

### Approach C: Auto-Apply Spec/Policy Patches

Let the loop generate and apply `.trellis/spec/` or policy changes immediately
for high-confidence lessons.

Trade-off: closer to the Moonshot, but too risky before there is a proposal
ledger, review semantics, rollback, and tests proving idempotence.

## Recommended MVP

Build Approach A first. Persist a review-only proposal ledger and trigger it
from the issue terminal seal after `record_project_memory(...)`. Use
deterministic extraction rules for obvious cases and leave LLM-assisted proposal
writing for a later phase. This creates the control plane needed for the system
to improve itself without making unaudited mutations.

## Design References

* `docs/superpowers/specs/2026-06-08-self-improvement-loop-design.md` — formal
  review-only proposal ledger design. This is pending user confirmation of the
  safety boundary before implementation planning begins.

## Implementation Readiness Notes

* Current git branch is `main`, ahead of `origin/main`; the working tree was
  clean before this PRD note was added.
* Existing terminal completion hook lives at
  `backend/app/application/conductor_main_loop.py::_seal_graph_and_issue_status`.
  It already calls `record_project_memory(...)` on `done` graphs and wraps the
  seal path in a best-effort `except Exception` block.
* Both stores need parity: the product runtime uses
  `backend/app/adapters/async_sqlite_store.py`, while tests and one-off scripts
  also use `backend/app/adapters/sqlite_store.py`.
* The backend test root is `backend/tests`, not a repository-level `tests`
  directory. Targeted verification should use commands such as
  `pytest backend/tests/test_<feature>.py`.
* Existing nearby test patterns:
  * `backend/tests/test_project_conductor.py` covers async store save/list
    parity for project memory rows.
  * `backend/tests/test_audit_log_api.py` covers sync store query parity and
    API response shape.
  * `backend/tests/test_swarm_integration.py` covers the terminal seal path
    calling best-effort cleanup from `_seal_graph_and_issue_status`.
  * `backend/tests/test_run_issue_conductor_loop.py` patches
    `record_project_memory` in Conductor loop tests, so the new hook will need
    similar patch-safe behavior.

## Proposed Backend Shape

### Domain Model

Add a domain model such as `SelfImprovementProposal` in
`backend/app/domain/models.py` with fields:

* `id: str`
* `project_id: str`
* `issue_id: str`
* `target_kind: str` (`project_memory`, `code_spec`, `conductor_policy`,
  `runtime_tooling`, `benchmark_eval`)
* `title: str`
* `recommendation: str`
* `evidence_json: str` (list of evidence pointers / snippets)
* `severity: str` (`info`, `medium`, `high`)
* `confidence: float`
* `status: str` (`proposed`, `accepted`, `rejected`, `applied`)
* `fingerprint: str` (stable idempotence key)
* `created_at`, `updated_at`

The exact enum typing can stay string-based at first, matching existing backend
models that treat status strings as storage contracts.

### Persistence

Add a SQLite table in `backend/app/adapters/sqlite_store.py`:

* `self_improvement_proposals`
* indexes on `(project_id, created_at)`, `(issue_id)`, `(status)`, and a unique
  `fingerprint`

Store methods should follow the existing direct store style:

* `save_self_improvement_proposal(proposal)`
* `list_self_improvement_proposals(project_id: str | None = None, issue_id:
  str | None = None, status: str | None = None, limit: int | None = None)`

### Extraction Service

Add an application service, likely
`backend/app/application/self_improvement_service.py`, responsible for:

* loading issue / workflow graph / conductor tasks / QA artifacts;
* applying deterministic extraction rules;
* computing stable fingerprints;
* persisting proposals;
* swallowing/logging extraction errors when called from terminal issue sealing.

Initial deterministic rules can be intentionally narrow:

* QA failed or `needs_follow_up` with `bugs_found` -> `code_spec` or
  `runtime_tooling` proposal depending on evidence text.
* Conductor/task failure with traceback or repeated retry -> `runtime_tooling`
  proposal.
* New policy/prompt override or illegal transition evidence -> `conductor_policy`
  proposal.
* Missing benchmark/evaluation evidence after a capability-related issue ->
  `benchmark_eval` proposal.

### Completion Hook

Call extraction from
`backend/app/application/conductor_main_loop.py::_seal_graph_and_issue_status`
after `record_project_memory(...)`, only when a workflow graph is terminal.
Like project memory, this must be best-effort: failures log and do not change
the completed issue status.

### Minimal API

Expose a read endpoint for future review surfaces:

* `GET /api/codex/projects/{project_id}/self-improvement-proposals`
* Optional query filters: `issue_id`, `status`, `limit`

Mutation endpoints for accept/reject/apply are out of scope for the first slice
unless implementation remains smaller than expected.

## Testing Plan

* Unit-test deterministic extraction with fake evidence:
  * QA failure creates proposal with evidence pointer.
  * Runtime/conductor failure creates proposal.
  * Clean trivial done issue creates no proposal.
  * Duplicate extraction for the same lesson is idempotent.
* Store tests:
  * save/list by project, issue, and status.
  * unique fingerprint prevents duplicate rows.
* Integration-style loop test:
  * terminal issue sealing calls extraction best-effort.
  * extraction exception does not prevent issue/graph terminal status.
* API test:
  * list endpoint returns stable JSON and filters by project/issue/status.
* Regression:
  * existing `record_project_memory(...)` behavior still runs for completed
    graphs.

## Definition Of Done (Team Quality Bar)

* Tests added/updated for backend extraction, storage, and endpoint behavior.
* Lint / typecheck / focused backend tests green.
* Docs/spec notes updated if new persistence/API contracts are introduced.
* Rollout/rollback considered: extraction is best-effort and can be disabled or
  ignored without breaking issue completion.

## Out Of Scope (Explicit)

* Fully autonomous code/spec modification.
* SWE-bench evaluation changes.
* A complete frontend review inbox, unless needed to validate the backend shape.
* Vector embeddings or semantic retrieval improvements.
* Replacing existing `team_notes.md` project memory.

## Technical Notes

* Existing completion hook:
  `backend/app/application/conductor_main_loop.py::_seal_graph_and_issue_status`.
* Existing deterministic project memory:
  `backend/app/application/project_memory_service.py`.
* Existing tiered ProjectConductor memory:
  `backend/app/application/project_conductor.py`.
* Existing manual code-spec update contract:
  `.agents/skills/trellis-update-spec/SKILL.md`.
* Existing SQLite table/index pattern:
  `backend/app/adapters/sqlite_store.py::_init_db`.
* Existing store methods use direct sync sqlite methods in
  `backend/app/adapters/sqlite_store.py`; new proposal methods should match the
  local style instead of adding an ORM or repository abstraction.
* Existing domain model file:
  `backend/app/domain/models.py`.
* Likely backend package specs:
  `.trellis/spec/vibe-kanban/backend/index.md`,
  `.trellis/spec/vibe-kanban/backend/database-guidelines.md`,
  `.trellis/spec/vibe-kanban/backend/quality-guidelines.md`,
  `.trellis/spec/vibe-kanban/backend/error-handling.md`.
