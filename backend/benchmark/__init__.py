"""Benchmark harness for evaluating agent output (PR1 — foundation).

This package implements the **load-bearing pure logic** of the benchmark
harness. It is fully testable in isolation (no real CLI, no DB, no API
endpoints) so the deterministic pieces are locked down before the runner
in PR2.

Layered stack (from the task research/eval-methodology.md):

  - golden fixtures (frozen issue + pinned expected commands, SWE-bench style)
  - scorer registry (pluggable, normalized 0..1 + metadata)
  - execution-based scorer (PRIMARY, FAIL_TO_PASS analog)
  - acceptance-coverage scorer (secondary rubric layer)
  - aggregation (weighted average)
  - pass@k over N epochs + stderr (PR2 — runner)
  - run record + baseline diff (PR2 — persistence)
  - LLM-as-judge (PR3, optional + calibrated)

The boundary between scorers and the runner is the ``IssueArtifacts`` value
object: scorers consume it and return a ``Score``. The runner (PR2) produces
it from the real Conductor run; for unit tests we hand-construct it from
fixed inputs (this is the determinism contract the methodology requires).
"""
