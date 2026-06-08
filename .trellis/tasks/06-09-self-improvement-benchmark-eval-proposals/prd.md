# brainstorm: self improvement benchmark eval proposals

## Goal

Close the next gap in the self-improvement loop by making completed capability
issues produce reviewable `benchmark_eval` proposals when the run evidence
shows no benchmark/evaluation coverage. This moves the system toward the
Moonshot requirement that self-improvement is measurable, not just a memory or
policy note.

## What I already know

* The approved self-improvement design says: "Capability issue without
  benchmark/evaluation evidence creates a `benchmark_eval` proposal."
* Current `backend/app/application/self_improvement_service.py` creates
  `code_spec`, `runtime_tooling`, and `conductor_policy` proposals, but not
  `benchmark_eval`.
* The backend already has a benchmark harness under `backend/benchmark/` with
  golden fixtures, pass@k aggregation, baseline/diff APIs, and frontend
  leaderboard UI.
* The proposal ledger is review-only for non-memory targets. A
  `benchmark_eval` proposal should produce an `open_pr_task` apply plan, not a
  direct file patch.
* Extraction is best-effort during terminal issue sealing and must not block
  issue completion.

## Assumptions

* "Capability issue" can be detected deterministically from issue title,
  description, and task result text using benchmark/capability/autonomy/eval
  keywords.
* "Without benchmark/evaluation evidence" means the issue/task evidence does
  not mention benchmark runs, benchmark fixture IDs, benchmark artifacts,
  calibration reports, or explicit eval/pass@k evidence.
* This slice should only create proposals; it should not create benchmark
  fixtures or run benchmarks automatically.

## Requirements

* Add deterministic extraction for `benchmark_eval` proposals.
* A completed capability issue with no benchmark/evaluation evidence creates
  one `benchmark_eval` proposal.
* The proposal should include evidence from the issue and relevant conductor
  task(s), a stable fingerprint, `severity="medium"` or stronger, and a
  recommendation that asks for a reviewed benchmark fixture/eval.
* Clean non-capability issues should still create no proposal.
* Capability issues with explicit benchmark/evaluation evidence should not
  create a redundant `benchmark_eval` proposal.
* Existing proposal kinds and idempotence behavior must remain unchanged.
* `apply-plan` for an accepted `benchmark_eval` proposal must remain an
  `open_pr_task` candidate and must not return a direct patch.
* Update backend spec/design docs with the executable contract for
  benchmark-eval proposal extraction.

## Acceptance Criteria

* [ ] Service tests cover capability issue without eval evidence -> one
  `benchmark_eval` proposal.
* [ ] Service tests cover explicit benchmark/eval evidence -> no
  `benchmark_eval` proposal.
* [ ] Service tests cover clean non-capability issue remains no proposal.
* [ ] Service tests cover duplicate benchmark-eval evidence saves once per
  issue/rule fingerprint.
* [ ] Apply-plan service/API behavior for accepted `benchmark_eval` remains
  `open_pr_task`, not `patch_file`.
* [ ] Backend spec captures signatures, contracts, error/validation matrix,
  good/bad cases, tests, and wrong/correct examples.

## Definition of Done

* TDD red/green evidence for the new extraction behavior.
* Focused self-improvement tests pass.
* Full backend test suite is run, or an environment blocker is documented.
* `compileall`, app import smoke, and `git diff --check` pass.
* `ruff` is run if available; if unavailable, record the exact failure.
* PR is opened, CI passes, merged, and the Trellis task is archived with a
  journal entry.

## Out of Scope

* Creating benchmark golden fixture files automatically.
* Running benchmark jobs automatically after every issue.
* Directly applying `benchmark_eval` proposals.
* Changing frontend benchmark UI.
* Marking the full Moonshot complete.

## Technical Notes

* Extraction service:
  `backend/app/application/self_improvement_service.py`.
* Existing extraction tests:
  `backend/tests/test_self_improvement_service.py`.
* Apply-plan service:
  `backend/app/application/self_improvement_apply_service.py`.
* Apply-plan API tests:
  `backend/tests/test_self_improvement_api.py`.
* Benchmark harness:
  `backend/benchmark/`, especially `backend/benchmark/README.md` and
  `backend/benchmark/golden_schema.py`.
* Backend spec:
  `.trellis/spec/vibe-kanban/backend/database-guidelines.md`.
