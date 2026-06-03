# Agent output evaluation & benchmark harness

## Goal

The system has full **audit observability** ("what happened" — audit_log,
ExecutionProcess cost/tokens, events) but **zero evaluation** ("was the output
good"). Build a harness that runs a fixed set of golden tasks, scores the agent
output, and tracks score/cost regressions across model & prompt changes — so any
future change can be objectively validated instead of judged by feel.

## Reusable foundations (inventoried in code, 2026-06-03 — not assumed)

- **Acceptance-criteria coverage = ready-made score signal**: `GET
  /codex/issues/{id}/checklist` (api.py:1303) reads PM `acceptance_criteria`
  (pm/prd.json) and matches against QA `acceptance_coverage` (qa/qa_plan.json) +
  engineer completed tasks → `{text, covered, source}`. → covered/total ratio.
- **QA real-command results**: `qa_workflow.py` runs `recommended_commands` in
  the worktree; any non-zero exit forces `failed` (never trusts LLM self-report).
  Objective pass/fail signal.
- **ExecutionProcess** (models.py:305): per-run `model`, `input/output/
  cache_read_tokens`, `total_cost_usd`, `status`, `exit_code`, `started/
  completed_at` → cost & efficiency metrics.
- **End-to-end run path**: `create_codex_issue` (api.py:2688) →
  `auto_start_issue_graph` (api.py:5422) → `run_issue_conductor_loop`
  (conductor_main_loop.py:541). A "golden task" is a re-creatable issue spec.
- **Artifacts on disk** per issue worktree: `issues/{id}/pm/prd.json`,
  `qa/qa_plan.json`, `engineer/implementation-*.md`.
- **audit_log**: full event/cost trail already persisted + queryable.

## Hard constraint (decisive — verified)

- **Mock mode is a no-op** (`bootstrap.py` MockCodexProcessManager: logs input,
  returns "done" instantly, produces NO real PM/QA/engineer artifacts). →
  Evaluation MUST run **REAL CLI** to get real output to score. Therefore eval
  runs are **non-deterministic, cost money, and are slow** → the harness is an
  **offline batch tool**, NOT per-commit CI. Scores must be treated
  statistically (variance across runs), not as exact pass/fail gates.

## Research References

- [`research/eval-methodology.md`](research/eval-methodology.md) — industry-standard
  coding-agent eval: execution-based scoring (SWE-bench FAIL_TO_PASS gated on
  PASS_TO_PASS), pass@k over N epochs for non-determinism, the shared
  (dataset→task→scorer→reducer→baseline-diff) data model across Inspect/Braintrust/
  LangSmith/OpenAI-Evals/Promptfoo, the scorer taxonomy, and score×cost frontier.

## Standard mechanism (from research) — the layered stack, not a single scorer

The field's convention maps cleanly onto our existing signals:
- **Execution-based = PRIMARY** for code. Our QA real-command pass/fail IS the
  SWE-bench FAIL_TO_PASS analog; we lack only a frozen golden issue set with
  pinned expected commands + a stored baseline.
- **Coverage = secondary rubric layer** (acceptance-criteria covered ratio).
- **LLM-as-judge = optional layer** for soft roles (PM/architect artifacts);
  needs human calibration + is itself non-deterministic → defer.
- **Non-determinism → pass@k over small N epochs** (Inspect epochs+reducers; cheap N=3).
- **Tracking = baseline-vs-candidate + score×cost 2D frontier** (we already
  capture per-run cost/tokens via ExecutionProcess/audit_log).
- **New concepts we actually lack**: golden dataset, pluggable scorer registry,
  baseline experiment record. Run records/cost already exist.

## Decisions (ADR-lite)

- **(Q1 → B) Scorer stack includes LLM-judge from the start**: execution-based
  (QA pinned commands) PRIMARY + acceptance-coverage secondary + LLM-as-judge for
  soft roles (PM/architect artifacts) + pass@k over N epochs. **Accepted cost**:
  the judge needs a small **human-labeled calibration set** to verify it
  correlates with human judgment (else judge scores aren't trustworthy), and the
  judge is itself non-deterministic (run it over epochs too / report variance).

- **(Q2 → A) Checked-in fixtures**: `backend/benchmark/golden/*.json`, one file per
  golden issue `{title, description, acceptance_criteria, pinned_qa_commands,
  expected_outcome}`. Frozen, PR-reviewable, hand-validated (SWE-bench-Verified
  style). Past real issues (console.db) may be *source material* for authoring
  fixtures, but the landed form is checked-in files.

- **(Q3 → A) N epochs + pass@k + stderr**: each golden task runs N=3 epochs;
  aggregate resolve-rate (pass@k) carries stderr; a candidate regresses when
  resolve-rate drops beyond stderr OR cost-per-issue exceeds a threshold. Never
  byte-equality. Baseline = one stored run, pinned explicitly.

- **(Q4 → A) Full score×cost metrics**: quality (resolve-rate/pass@k + coverage +
  judge) + cost_usd + tokens + duration per run (cost/tokens/duration already on
  ExecutionProcess → near-free) → enables the score×cost frontier.

- **(Q5 → C) Frontend Benchmarks page**: trigger + leaderboard + score×cost
  frontier + baseline-vs-candidate diff. **Architectural implication**: C subsumes
  B — the page needs an **API layer + async job** to trigger the slow/expensive
  real-CLI batch and fetch run records. The CLI runner remains the engine core
  underneath. → MVP is four layers: runner core → run-record persistence → API/job
  → frontend page. This is a genuine multi-PR phase (largest of the options).
- (Q2) Golden task format & where they live (DB seed vs checked-in fixtures).
- (Q3) What a "run" compares against (baseline snapshot) and how regression is
  defined given non-determinism (N repeats + threshold? single run?).
- (Q4) Scope of metrics for MVP (quality score only vs + cost/tokens + duration).
- (Q5) Trigger / surface: CLI script vs API endpoint vs a frontend "Benchmarks" page.

## Requirements (final)

- **Golden fixtures**: `backend/benchmark/golden/*.json`, hand-validated, one issue
  each: `{title, description, acceptance_criteria, pinned_qa_commands, expected_outcome}`.
  Seed ~10 to start.
- **Scorer registry** (pluggable, each returns normalized 0–1 + metadata):
  execution-based (QA pinned commands, PRIMARY) + acceptance-coverage + LLM-judge
  (soft roles). Scorers unit-tested on fixed input artifacts (deterministic).
- **Judge calibration set**: a small human-labeled set verifying judge↔human correlation.
- **Runner**: drives the real Conductor on each golden issue in an isolated worktree
  (real CLI), N=3 epochs; aggregates pass@k / resolve-rate + stderr.
- **Run-record persistence**: per-issue scores + aggregate resolve-rate + coverage +
  judge + cost_usd + tokens + duration, keyed by (orchestrator version, model-config,
  timestamp). One run pinnable as baseline.
- **API + async job**: trigger a benchmark run (async; long/expensive), fetch runs,
  fetch baseline-vs-candidate diff.
- **Frontend Benchmarks page**: trigger, leaderboard, score×cost frontier,
  baseline-vs-candidate diff (improved/regressed/unchanged), i18n zh/en.

## Acceptance Criteria (final)

- [ ] A golden fixture set (~10) is checked in and schema-validated.
- [ ] Each scorer returns a normalized score + metadata; unit-tested on fixed artifacts.
- [ ] Runner executes the golden set on real CLI over N epochs and computes
      pass@k/resolve-rate + stderr per task and in aggregate.
- [ ] A run persists all metrics (quality + cost/tokens/duration) + version keys.
- [ ] A run can be pinned as baseline; a later run shows per-issue + aggregate
      improved/regressed/unchanged, with regression defined as resolve-rate drop
      beyond stderr OR cost-per-issue over threshold (never byte-equality).
- [ ] Frontend Benchmarks page triggers a run, shows the leaderboard + score×cost
      frontier + baseline diff; copy is i18n zh/en.
- [ ] LLM-judge has a calibration check documenting its correlation with the human set.

## Technical Approach

Four layers (Inspect/Braintrust's data→task→scorer→reducer→baseline-diff loop, with
SWE-bench's execution-based gold signal + HumanEval pass@k + leaderboard score×cost):
1. **Golden fixtures + scorer registry** (pure, testable core).
2. **Runner** reusing `create_codex_issue`→`auto_start_issue_graph`→
   `run_issue_conductor_loop` in an isolated worktree per epoch; pull QA pass/fail,
   coverage (checklist endpoint logic), cost/tokens (ExecutionProcess) as signals.
3. **Persistence + API/async-job** (new `benchmark_run` table; reuse EventBus for
   progress; baseline pin).
4. **Frontend Benchmarks page** (leaderboard + score×cost + baseline diff).

## Implementation Plan (small PRs)

- **PR1**: golden fixture JSON schema + ~10 hand-validated fixtures + scorer registry
  (execution/coverage/judge) with unit tests on fixed artifacts.
- **PR2**: runner (drive real Conductor over golden set, N epochs) + pass@k/stderr
  aggregation + `benchmark_run` persistence + baseline pin.
- **PR3**: API endpoints + async job (trigger/fetch/baseline-diff) + judge
  calibration set + correlation check.
- **PR4**: frontend Benchmarks page (trigger / leaderboard / score×cost frontier /
  baseline diff) + i18n.

## Definition of Done (team quality bar)

- Tests for the scorer (deterministic given fixed input artifacts).
- Lint / typecheck / CI green.
- Docs: how to add a golden task + run a benchmark.
- Non-determinism handled explicitly (no flaky exact-match gate).

## Out of Scope (explicit / candidate)

- Per-commit CI gating (eval is offline batch — see hard constraint).
- Auto-tuning prompts/models from eval results (future; this phase only measures).

## Technical Notes

- `backend/app/interfaces/api.py:1303` checklist (coverage scoring source).
- `backend/app/application/qa_workflow.py` real-command pass/fail.
- `backend/app/domain/models.py:305` ExecutionProcess (cost/token fields).
- `backend/app/interfaces/api.py:2688/5422` issue create + auto_start.
- `backend/app/application/conductor_main_loop.py:541` conductor loop.
- `backend/app/bootstrap.py` MockCodexProcessManager (no-op → eval needs real CLI).
