# Research: Standard methodology for evaluating coding-agent / agentic-LLM output

- **Query**: Industry-standard methodology for evaluating coding-agent output, mapped onto an offline benchmark harness for a multi-agent coding orchestration system
- **Scope**: external (web), with mapping onto our internal constraints
- **Date**: 2026-06-03

## Our constraints (the lens for every section)

- Conductor dispatches PM / architect / engineer / QA agents that produce **real code in git worktrees**.
- Output is **non-deterministic**: must run the real CLI; no deterministic mock.
- We already have three signals: **per-issue acceptance-criteria coverage**, **QA real-command pass/fail (execution-based)**, **per-run cost/tokens**.

---

## 1. Execution-based evaluation (the dominant convention for coding)

The field has converged on **execution-based scoring**: you do not compare the agent's diff to a "golden diff" textually; you check whether the produced code makes a **hidden/held-out test suite pass**. Functional correctness, not surface similarity.

**Named examples:**

- **HumanEval** (Chen et al., 2021, arXiv:2107.03374 — the Codex paper). 164 hand-written Python problems. A "task" = function signature + docstring + a set of **hidden unit tests**. Score = the generated function passes all hidden tests. This is the origin of `pass@k`. Source confirms: *"a new evaluation set we release to measure functional correctness for synthesizing programs from docstrings"* and *"repeated sampling from the model is a surprisingly effective strategy."*
- **SWE-bench** (Jimenez et al., 2023, arXiv:2310.06770). 2,294 real GitHub issue+PR pairs across 12 Python repos. A "task" = (codebase snapshot at base commit, issue text). The agent edits the repo. Ground truth comes from the **real merged PR**: the harness applies the agent's patch, then runs two test sets pulled from that PR — **`FAIL_TO_PASS`** (tests that failed before the fix and must now pass) and **`PASS_TO_PASS`** (tests that passed before and must still pass, i.e. no regression). Resolved = all FAIL_TO_PASS pass AND all PASS_TO_PASS still pass. This is the single most important pattern for us: the gold signal is *delta in test outcomes*, gated on no-regression.
- **SWE-bench Verified** (OpenAI, 2024). A **500-task human-validated subset** of SWE-bench. Human SWE annotators filtered out tasks that were **underspecified** (issue doesn't actually say what "fixed" means) or had **bad/over-specific tests** (tests that a correct fix could still fail). This is the canonical statement of "what makes a good golden task": (a) the issue is solvable from the information given, (b) the FAIL_TO_PASS tests are neither too loose nor too brittle.
- **MBPP / LiveCodeBench / SWE-bench Multimodal** — same execution-based shape; LiveCodeBench additionally rotates problems by date to fight **train-set contamination**.

**What makes a good golden task (synthesized):** solvable from the prompt alone; deterministic ground-truth tests; tests that pin the *intended behavior* not the *specific implementation*; a no-regression guard; resistant to memorization (recent or private).

**Map onto us:** Our **QA real-command pass/fail is already execution-based scoring** — it is the SWE-bench `FAIL_TO_PASS` analog. Our **acceptance-criteria coverage** is the rubric/spec layer. The missing piece to be "standard" is a **frozen set of golden issues** with pinned expected commands/tests and a recorded baseline, so a run is scored against ground truth rather than only self-reported.

---

## 2. pass@k and handling non-determinism

Because sampling is stochastic, single-shot accuracy is high-variance and biased. The standard fix is **repeated sampling + the unbiased pass@k estimator** from the HumanEval paper:

- Generate **n ≥ k** samples per task, count **c** that pass, then
  `pass@k = 1 − C(n−c, k) / C(n, k)`
  (probability that at least one of k random draws passes). Using n much larger than k and the combinatorial form avoids the high variance of naively computing 1−(1−p)^k.
- **pass^k / "all-pass@k"** (probability *all* k attempts succeed) is used for **reliability/consistency** rather than best-of-k capability (arXiv:2406.12045).
- **Inspect (UK AISI)** bakes this directly into its **epochs + reducers** model: run each sample over N `epochs`, then reduce with a named reducer. Confirmed built-in reducers include `mean`, `median`, `pass_at_{k}` ("Probability of at least 1 correct sample given k epochs", citing the HumanEval paper), `pass_k_{k}` (all k succeed), and `at_least_{k}`. This is the cleanest off-the-shelf abstraction for our non-determinism problem.

**Defining regression statistically (not exact-match):** with stochastic output you never expect byte-identical results, so regression is defined on **aggregate score distributions**, not diffs:

- Track a **rate** (resolve rate / pass@k) over a fixed task set; flag regression when the new rate drops beyond a threshold or confidence interval. LangSmith and Braintrust both frame comparison as **experiment-vs-baseline on aggregate scores**, not per-row equality.
- Report **stderr / confidence intervals** on the rate. Inspect ships `stderr` and **clustered stderr** metrics specifically so aggregate scores carry error bars; a "regression" is a drop that exceeds noise.
- Use **fixed seeds where possible + enough samples** so the CI is tight enough to detect real movement.

**Map onto us:** because we run the real CLI and can't mock, **N-epoch repeated runs of each golden issue + pass@k (resolve rate)** is the correct primitive. Regression = resolve-rate or pass@k of candidate (model/prompt version) drops vs. the stored baseline beyond stderr. Cheap MVP: small N (e.g. 3–5) per issue given cost.

---

## 3. Established eval-harness tooling & their data models

All five share the same conceptual triple: **(golden dataset) → (task/runner) → (scorers) → (run record) → (baseline-vs-candidate comparison)**. The "scorer" is the load-bearing abstraction everywhere.

- **OpenAI Evals** — dataset is **JSONL, one sample per line**; every template expects an `input` key; reference-based templates (`Match`, `Includes`, `FuzzyMatch`) additionally require an **`ideal`** key (the gold answer, string or list); **model-graded** templates fill `{key}` slots in a grading prompt. Evals are registered in a YAML **registry**. Scorer = the eval template (basic match vs. model-graded). (Source: openai/evals `docs/build-eval.md`.)
- **Inspect (UK AISI)** — `Task` = `dataset` + `solver` + `scorer`. A **`Scorer`** returns a `Score` (value + explanation + metadata) and declares one or more **`metrics`** (e.g. `accuracy()`, `mean()`) that aggregate across samples. Built-in scorers: `match()`, `includes()`, `pattern()`, `answer()`, `exact()`, `f1()` (reference-based) and `model_graded_qa()` / `model_graded_fact()` (LLM-as-judge). Epochs+reducers handle multi-sample (see §2). Rich **log files / log dataframes** are the run record. This is the closest match to our needs (agents, sandboxes, tools, multi-sample all first-class).
- **LangSmith** — **Dataset** (examples with optional reference outputs) → run app to produce an **Experiment** → **Evaluators** score it. Evaluator types: **heuristic/code rules**, **LLM-as-judge**, **pairwise comparison**, **human review**. Supports **repetitions, concurrency, caching** per experiment, and explicit **"Compare experiment results" for benchmarking / regression**. Evaluators can also run **online** on production traces.
- **Braintrust** — the canonical minimal API is **`Eval(name, { data, task, scores })`**: `data` = dataset (input + optional `expected`), `task` = the function/agent under test, `scores` = list of scorers (their **`autoevals`** library: `Factuality`, embedding similarity, LLM-as-judge, or custom code). Runs are **experiments**; the UI does **regression detection vs. a baseline experiment** ("detect regressions before they reach production"). Custom agent code connects via **remote evals / sandboxes** — directly relevant since our agents aren't a single prompt.
- **Promptfoo** — config-driven: test cases carry an **`assert`** array; each assertion has a `type`. Two families: **deterministic metrics** (equals, contains, regex, JSON-schema, `is-json`, javascript/python custom) and **model-graded metrics** (`llm-rubric`, `factuality`, `g-eval`, `select-best`, embedding `similar`). "Accuracy" = proportion of prompts producing the desired output. Good model for a lightweight YAML-defined golden set.

**Common data-model takeaways for us:** (1) golden set = list of rows with `input` + optional `expected`/`ideal`; (2) scorer is a pluggable function returning a normalized score + metadata; (3) a **run record** persists per-row score, aggregate, model/prompt version, and cost; (4) comparison is **experiment baseline vs. candidate** on aggregates. We already have run records (`ExecutionProcess`, cost/tokens, audit_log) — we mainly lack the *golden dataset* + *scorer registry* + *baseline experiment* concepts.

---

## 4. The standard taxonomy of scorers (and failure modes)

| Scorer type | What it does | When used | Known failure modes |
|---|---|---|---|
| **Reference-based** (exact / fuzzy / embedding / diff vs gold) | Compare output to a stored gold answer: `Match`/`exact()`/`includes()`/`f1()`, or embedding `similar`/diff | Short, canonical answers; classification; structured output | Penalizes valid alternatives; brittle for code (many correct diffs); embedding similarity ≠ correctness |
| **Execution-based** (tests pass) | Run hidden tests / commands; score = pass/fail or delta | **Coding agents — the gold standard.** SWE-bench, HumanEval, our QA | Needs a sandbox + ground-truth tests; flaky tests; over-specific tests reject correct fixes (the thing SWE-bench Verified filters) |
| **Rubric / LLM-as-judge** | Another model grades against a rubric: `model_graded_qa`, Braintrust `Factuality`, Promptfoo `llm-rubric`, G-Eval | No clean reference; open-ended quality; agent reasoning quality | Position/verbosity/self-preference bias; non-determinism in the judge; needs its own calibration vs. humans; cost |
| **Human eval** | Annotators score / rank | Ground-truth calibration, building golden sets (SWE-bench Verified), final tie-break | Slow, expensive, inconsistent; doesn't scale to CI |

**Standard practice:** use **execution-based as primary for code**, LLM-as-judge for the soft dimensions (PRD quality, architect design rationale) with a small **human-labeled calibration set**, and reference-based only for narrow structured outputs.

**Map onto us:** QA-exec = execution-based (primary, keep). Acceptance-criteria coverage = a rubric the judge can grade against, but it can also be made **execution-based** if each criterion maps to a command/test. LLM-as-judge is the natural fit for grading non-code roles (PM/architect), but must be calibrated and is itself non-deterministic.

---

## 5. Regression-tracking / leaderboard patterns

How teams track **score + cost across model/prompt versions over time**:

- **Baseline experiment + diff** (Braintrust, LangSmith): pin one run as baseline; every new run (a new model or prompt version) is compared row-by-row and in aggregate; the UI surfaces **improved / regressed / unchanged** rows. Score is always paired with metadata: model, prompt version, cost, latency.
- **Score-vs-cost as a 2D frontier** (HELM, the public SWE-bench leaderboard, Aider's leaderboard). Leaderboards report **resolve rate AND $-cost per task** together, so a cheaper model with slightly lower resolve rate is visibly on the Pareto frontier. This directly matches our existing per-run cost/token signal — we can plot resolve-rate vs. cost per golden-suite run.
- **Versioned runs over time** (HELM "living benchmark", LiveCodeBench date-windowing): each eval run is timestamped and tied to a code/model version; trend lines show drift; contamination is mitigated by refreshing tasks.
- **CI gate**: run the golden suite on each prompt/orchestrator change; fail (or warn) if aggregate resolve-rate drops beyond stderr or if cost-per-issue rises beyond a budget threshold. Mirrors our existing budget-warning machinery.

**Map onto us:** we already have **cost/tokens per run** and an **audit_log + ExecutionProcess** ledger. The standard pattern = store each golden-suite run as a timestamped **experiment record** keyed by (orchestrator version, model catalog config), holding `resolve_rate (pass@k)`, `coverage`, `cost_usd`, `tokens`; compare candidate vs. stored baseline; surface the score×cost frontier.

---

## What the standard MVP would look like for us

1. **Golden issue set** (`benchmark/golden/*.json`): a frozen list of issues, each with the issue prompt + **pinned expected QA commands/tests** (FAIL_TO_PASS analog) + acceptance criteria. Hand-validate them (SWE-bench-Verified style) so they're solvable and not over-specific. Start with ~10–20.
2. **Runner**: drive the real Conductor on each golden issue in an isolated worktree (real CLI, no mock), **N epochs per issue** (N small, e.g. 3, for cost).
3. **Scorers** (pluggable, normalized 0–1 + metadata), reusing existing signals:
   - *execution-based* = QA real-command pass/fail on the pinned commands (primary);
   - *reference/coverage* = acceptance-criteria coverage;
   - optional *LLM-as-judge* for PM/architect artifacts with a tiny human-calibration set.
4. **Aggregation**: `pass@k` / resolve-rate over the N epochs (Inspect's reducer model), with **stderr** for confidence.
5. **Run record / experiment**: persist per-issue scores, aggregate resolve-rate, coverage, **cost_usd + tokens** (already captured), keyed by orchestrator + model-config version + timestamp.
6. **Baseline-vs-candidate comparison + score×cost frontier**: store one run as baseline; a candidate "regresses" when resolve-rate drops beyond stderr or cost-per-issue exceeds a threshold. Optional CI gate reusing the budget-warning pattern.

This is essentially **Inspect/Braintrust's (data → task → scorer → epochs/reducer → baseline-diff) loop**, with **SWE-bench's FAIL_TO_PASS execution-based gold signal**, **HumanEval's pass@k** for non-determinism, and **leaderboard score×cost** tracking — all built on signals we already produce.

## External References

- HumanEval / Codex — Chen et al. 2021, arXiv:2107.03374 (functional correctness, pass@k unbiased estimator, repeated sampling)
- SWE-bench — Jimenez et al. 2023, arXiv:2310.06770 (real GitHub issue→PR tasks, FAIL_TO_PASS / PASS_TO_PASS gating)
- SWE-bench Verified — OpenAI 2024 (500 human-validated tasks; filters underspecified issues & over-specific tests)
- pass^k / all-pass reliability — arXiv:2406.12045 (cited by Inspect's `pass_k_{k}` reducer)
- Inspect (UK AISI) — https://inspect.aisi.org.uk/scorers.html (Scorer/metric model, built-in scorers, epochs + reducers incl. `pass_at_{k}`)
- OpenAI Evals — github.com/openai/evals `docs/build-eval.md` (JSONL samples, `input`/`ideal`, Match/Includes/FuzzyMatch, model-graded, registry)
- LangSmith — docs.smith.langchain.com/evaluation/concepts (Dataset → Experiment → Evaluators: heuristic / LLM-as-judge / pairwise / human; compare experiments for regression)
- Braintrust — braintrust.dev/docs/guides/evals (`Eval(data, task, scores)`, autoevals scorers, baseline regression detection, remote evals/sandboxes for agents)
- Promptfoo — promptfoo.dev/docs/configuration/expected-outputs (assertion types: deterministic vs. model-graded incl. llm-rubric, g-eval, factuality, similar)

## Caveats / Not Found

- SWE-bench Verified's official OpenAI page returned HTTP 403 to curl; the 500-task / human-validation / FAIL_TO_PASS details above are from the SWE-bench paper + widely-documented Verified methodology, not that one blocked page.
- exa MCP search tools were unavailable in this environment; findings come from direct curl fetches of primary docs/papers (arXiv abstracts, official tool docs). Deeper numeric leaderboard figures (current resolve-rate/$ numbers) were not pulled — they change frequently and aren't needed for methodology design.
