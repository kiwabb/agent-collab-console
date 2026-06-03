# Benchmark harness (PR1 — foundation)

The benchmark harness evaluates agent output against a frozen set of
golden issues. It implements the methodology contract from
`research/eval-methodology.md`:

  - **Execution-based scoring** (PRIMARY, FAIL_TO_PASS analog) — the
    runner executes the golden issue's pinned QA commands in the
    worktree and the scorer judges each on exit code.
  - **Acceptance-coverage** (secondary rubric) — the scorer checks
    whether the agent's completed-task titles mention the
    golden-issue's acceptance criteria tokens.
  - **Weighted aggregation** — `aggregate_weighted` averages scorer
    values, normalized by total weight.

PR1 is **pure logic only** — no real CLI, no DB, no API endpoint. The
runner (PR2), persistence (PR2), API/job (PR3), and frontend page (PR4)
are follow-up work.

## Layout

```
backend/benchmark/
├── __init__.py
├── types.py             # Score, CommandResult, IssueArtifacts, aggregate_weighted
├── scorers.py           # Scorer protocol, ScorerEntry, ScorerRegistry
├── scorers_impl.py      # ExecutionScorer, AcceptanceCoverageScorer, default_registry
├── golden_schema.py     # Pydantic models: PinnedCommand, GoldenIssue
├── golden_loader.py     # load + validate fixtures (loud failure on malformed)
├── golden/              # checked-in JSON fixtures, one file per golden issue
│   └── *.json
└── README.md
```

## How to add a golden task

1. Pick a small, well-scoped, deterministic agent task. The task must
   be **solvable from the description alone** (SWE-bench-Verified rule)
   and the QA commands must be **safe** (no `rm -rf`, no `sudo`, no
   `curl | sh` — the schema validator rejects these patterns at
   load time).
2. Author `backend/benchmark/golden/<id>.json` with the
   ``GoldenIssue`` shape (see ``golden_schema.py`` for the full
   schema). The id is the file stem; the loader keys fixtures by it.
3. Verify the schema validates:
   ```bash
   cd backend && .venv/bin/python -c "from benchmark import ids; print(ids())"
   ```
4. Add at least one ``acceptance_criteria`` entry (the coverage
   scorer matches on token overlap) and at least one
   ``pinned_qa_commands`` entry (the execution scorer grades on exit
   code).
5. Run the test suite:
   ```bash
   cd backend && .venv/bin/python -m pytest tests/test_benchmark_fixtures.py -v
   ```

## How to write a custom scorer

A scorer is any object that satisfies the ``Scorer`` protocol
(``name: str``, ``weight: float``, ``score(artifacts) -> Score``).
Plain functions work too — wrap them in a class to give them a
stable ``name``:

```python
class WordCountScorer:
    name = "word_count"
    weight = 0.1
    def score(self, artifacts):
        joined = " ".join(artifacts.completed_engineer_tasks)
        n = len(joined.split())
        return Score(value=min(1.0, n / 100), passed=n >= 50,
                     metadata={"word_count": n})

reg = default_registry()
reg.register(WordCountScorer())
scores = reg.score(my_artifacts)
```

## Determinism contract

Every scorer must be **deterministic given fixed input artifacts**.
This is the methodology contract — the runner in PR2 will run the
golden set over N epochs and aggregate pass@k + stderr. A
non-deterministic scorer makes the aggregation meaningless.

If you need a stochastic component (e.g. an LLM-as-judge in PR3),
wrap the random scorer in epochs and report the **mean** + **stderr**
across epochs; do not let the raw scorer value be the source of
variance.

## Tests

```bash
cd backend
.venv/bin/python -m pytest tests/test_benchmark_fixtures.py tests/test_benchmark_scorers.py -v
```

Coverage:

- 11 checked-in fixtures, all valid against the schema
- Schema rejects malformed shapes, dangerous shell patterns
- Loader: stable order, whitelist, missing dir, malformed file
- ExecutionScorer: all-pass / one-fail / all-fail / no-results
- AcceptanceCoverageScorer: full / partial / none / no-criteria
- Token helpers: stopword filter, alphanumeric normalization
- Aggregation: weighted average, missing scorer, zero weights
- ScorerRegistry: register / get / weight override / error paths
- Determinism: same artifacts → same Score, every time

## Out of scope (future PRs)

- **PR2** — runner (drive real Conductor over golden set, N=3 epochs,
  pass@k + stderr aggregation), `benchmark_run` persistence, baseline
  pin.
- **PR3** — API endpoints + async job + LLM-as-judge scorer with a
  human-labeled calibration set.
- **PR4** — frontend Benchmarks page (trigger / leaderboard /
  score×cost frontier / baseline diff) + i18n.
