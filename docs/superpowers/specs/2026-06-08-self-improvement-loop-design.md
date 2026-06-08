# Self Improvement Loop Design

## Status

Proposed. This design uses a review-only proposal ledger as the first safe
slice. It must be approved before implementation planning starts.

## Objective

Make every completed issue produce structured learning signals. The system
should inspect the evidence from the run, classify actionable lessons, and
persist auditable self-improvement proposals for memory, code-spec, conductor
policy, runtime tooling, or benchmark/evaluation gaps.

This is not full recursive self-modification yet. It is the control plane that
makes later recursive self-improvement reviewable, measurable, and reversible.

## Chosen Approach

Use a review-only proposal ledger.

The system writes durable `self_improvement_proposals` after issue completion.
Each proposal contains a target kind, recommendation, evidence pointers,
confidence, severity, status, and a stable fingerprint for idempotence.

The first slice does not silently mutate `.trellis/spec/`, prompts, policy, or
code. Existing `.agent-collab/team_notes.md` project memory remains separate and
continues to work as it does today.

## Alternatives Considered

### Extend Team Notes Only

This would append structured lessons into `.agent-collab/team_notes.md`.
It is cheap and immediately prompt-visible, but it cannot track accepted versus
rejected ideas, support review workflows, or measure whether a lesson later
improved outcomes.

### Auto-Apply Low-Risk Changes

This is closer to the long-term Moonshot, but too early for the first slice.
Without a proposal ledger, review status, fingerprints, and rollback semantics,
automatic spec or policy changes would be hard to audit and easy to distrust.

## Backend Architecture

### Domain Model

Add `SelfImprovementProposal` in `backend/app/domain/models.py`.

Fields:

- `id: str`
- `project_id: str`
- `issue_id: str`
- `target_kind: str`
- `title: str`
- `recommendation: str`
- `evidence_json: str`
- `severity: str`
- `confidence: float`
- `status: str`
- `fingerprint: str`
- `created_at: datetime | None`
- `updated_at: datetime | None`

Allowed `target_kind` values:

- `project_memory`
- `code_spec`
- `conductor_policy`
- `runtime_tooling`
- `benchmark_eval`

Allowed `status` values:

- `proposed`
- `accepted`
- `rejected`
- `applied`

### Persistence

Add a SQLite table in `backend/app/adapters/sqlite_store.py`:

```sql
CREATE TABLE IF NOT EXISTS self_improvement_proposals (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    issue_id TEXT NOT NULL,
    target_kind TEXT NOT NULL,
    title TEXT NOT NULL,
    recommendation TEXT NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '[]',
    severity TEXT NOT NULL DEFAULT 'info',
    confidence REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'proposed',
    fingerprint TEXT NOT NULL UNIQUE,
    created_at TEXT,
    updated_at TEXT
)
```

Indexes:

- `idx_self_improvement_project_created` on `(project_id, created_at)`
- `idx_self_improvement_issue` on `(issue_id)`
- `idx_self_improvement_status` on `(status)`

Store methods:

- `save_self_improvement_proposal(proposal)`
- `list_self_improvement_proposals(project_id=None, issue_id=None, status=None, limit=None)`

The store should follow the existing direct SQLite style. Do not introduce an
ORM or a separate repository abstraction.

### Extraction Service

Add `backend/app/application/self_improvement_service.py`.

Responsibilities:

- Load issue, workflow graph, conductor tasks, QA artifacts, and implementation
  artifacts.
- Extract deterministic proposal candidates.
- Attach evidence pointers, not just prose.
- Compute a stable fingerprint.
- Persist proposals idempotently.
- Fail best-effort when called from terminal issue sealing.

Initial extraction rules:

- QA failure or `needs_follow_up` with `bugs_found` creates a `code_spec` or
  `runtime_tooling` proposal.
- Conductor failure, traceback, stalled task, or repeated retry creates a
  `runtime_tooling` proposal.
- Illegal transition or policy override evidence creates a `conductor_policy`
  proposal.
- Capability issue without benchmark/evaluation evidence creates a
  `benchmark_eval` proposal.
- Clean trivial completions can produce no proposal.

### Completion Hook

Call extraction from
`backend/app/application/conductor_main_loop.py::_seal_graph_and_issue_status`
after the existing `record_project_memory(...)` call.

The hook must only run for terminal workflow graphs. It must never block issue
completion. Errors should log at warning/debug level and preserve existing graph
and issue status behavior.

## API Design

Add a read endpoint:

`GET /api/codex/projects/{project_id}/self-improvement-proposals`

Query filters:

- `issue_id`
- `status`
- `limit`

Response shape:

```json
{
  "proposals": [
    {
      "id": "proposal-id",
      "project_id": "project-id",
      "issue_id": "issue-id",
      "target_kind": "runtime_tooling",
      "title": "Capture LLM HTTP proxy failures",
      "recommendation": "Add a runtime contract...",
      "evidence": [
        {"kind": "conductor_task", "id": "task-id"},
        {"kind": "qa_report", "path": "issues/.../qa/qa_plan.json"}
      ],
      "severity": "medium",
      "confidence": 0.8,
      "status": "proposed",
      "fingerprint": "stable-key",
      "created_at": "2026-06-08T00:00:00",
      "updated_at": "2026-06-08T00:00:00"
    }
  ]
}
```

Accept/reject/apply mutation endpoints are out of scope for the first slice.

## Idempotence

Fingerprints should be stable across repeated terminal sealing and recovery.
A reasonable first key is:

`project_id | issue_id | target_kind | normalized_title_or_rule_id`

If a duplicate fingerprint is saved, the service should update the existing row
or skip it. It must not produce unbounded duplicates.

## Error Handling

Self-improvement extraction is best-effort.

Required behavior:

- Store unavailable during API read: return the existing project API style for
  unavailable stores.
- Extraction failure during issue seal: log and continue.
- Missing artifacts: produce fewer proposals, not an exception.
- Malformed artifact JSON: ignore that artifact and continue.

## Testing

Backend tests should cover:

- QA failure evidence creates a proposal with target kind and evidence.
- Runtime/conductor failure creates a proposal.
- Clean trivial completion creates no proposal and no error.
- Duplicate extraction is idempotent.
- Store save/list filters by project, issue, and status.
- API endpoint returns stable JSON and respects filters.
- Terminal issue sealing still calls `record_project_memory(...)`.
- Extraction exceptions do not prevent graph/issue terminal state.

## Rollout

This feature can ship dark: backend extraction and read API first, no frontend
inbox required. Operators can inspect proposals through tests/API while the
product review workflow is designed in a later slice.

## Open Decision

The recommended safety boundary is review-only. The user still needs to confirm
whether the MVP should:

1. stay review-only;
2. auto-apply project memory only;
3. auto-apply low-risk spec updates.

Implementation planning should not start until this is confirmed.
