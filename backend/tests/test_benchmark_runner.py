"""Tests for the benchmark runner (PR2).

The runner is tested end-to-end against a :class:`FakeExecutor`
(no real Conductor calls, no cost). The goal is to lock the
orchestration contract:

  - Loops over (fixture, epoch_index) in stable order.
  - Persists the run + every epoch row.
  - Aggregates the right metrics.
  - Honors ``--epochs``, ``--fixture-ids``, ``--is-baseline``.
  - Returns the right error on missing fixtures / executor raise.
"""
from __future__ import annotations

import json
from typing import Iterable

import pytest

from benchmark.runner import (
    BenchmarkRunner,
    ExecutorResult,
    FakeExecutor,
    RunOptions,
)
from benchmark.store import (
    BenchmarkEpoch,
    BenchmarkRun,
    InMemoryStore,
)
from benchmark.types import CommandResult, IssueArtifacts


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ok_artifacts(fixture_id: str) -> IssueArtifacts:
    """An IssueArtifacts that the ExecutionScorer grades as passed."""
    return IssueArtifacts(
        issue_id=f"codex-{fixture_id}",
        prd_acceptance_criteria=["the endpoint exists", "returns 200"],
        qa_results=[CommandResult(command="x", exit_code=0, duration_s=0.1)],
        completed_engineer_tasks=[
            "Add the endpoint",
            "Returns 200",
        ],
    )


def _fail_artifacts(fixture_id: str) -> IssueArtifacts:
    """An IssueArtifacts that the ExecutionScorer grades as failed."""
    return IssueArtifacts(
        issue_id=f"codex-{fixture_id}",
        prd_acceptance_criteria=["the endpoint exists"],
        qa_results=[CommandResult(command="x", exit_code=1, duration_s=0.1)],
        completed_engineer_tasks=[],
    )


def _all_pass_results() -> dict[str, list[IssueArtifacts]]:
    """Per-fixture results: every epoch passes."""
    from benchmark.golden_loader import load_all

    fixtures = load_all()
    return {f.id: [_ok_artifacts(f.id) for _ in range(3)] for f in fixtures}


def _mixed_results() -> dict[str, list[IssueArtifacts]]:
    """Per-fixture results: 1st epoch fails, 2nd and 3rd pass → pass@1 = 2/3."""
    from benchmark.golden_loader import load_all

    fixtures = load_all()
    return {
        f.id: [_fail_artifacts(f.id), _ok_artifacts(f.id), _ok_artifacts(f.id)]
        for f in fixtures
    }


# ---------------------------------------------------------------------------
# run() — orchestration contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_with_all_pass_aggregates_to_one():
    store = InMemoryStore()
    executor = FakeExecutor(per_fixture_results=_all_pass_results())
    runner = BenchmarkRunner(store, executor)

    run = await runner.run(RunOptions(epochs=3))

    assert run.status == "completed"
    assert run.aggregate_pass_at_1 == pytest.approx(1.0)
    assert run.aggregate_pass_at_1_stderr == 0.0
    assert run.cost_total_usd >= 0
    # Every fixture should have 3 epochs.
    epochs = store.list_epochs(run.id)
    assert len(epochs) == len(_all_pass_results()) * 3


@pytest.mark.asyncio
async def test_run_with_mixed_results_aggregates_correctly():
    store = InMemoryStore()
    executor = FakeExecutor(per_fixture_results=_mixed_results())
    runner = BenchmarkRunner(store, executor)

    run = await runner.run(RunOptions(epochs=3))

    # Each fixture's pass@1 = 2/3; aggregate = 2/3.
    assert run.aggregate_pass_at_1 == pytest.approx(2 / 3)
    # All fixtures agree on the rate → stderr = 0.
    assert run.aggregate_pass_at_1_stderr == 0.0


@pytest.mark.asyncio
async def test_run_persists_per_epoch_rows():
    store = InMemoryStore()
    executor = FakeExecutor(per_fixture_results=_all_pass_results())
    runner = BenchmarkRunner(store, executor)

    run = await runner.run(RunOptions(epochs=2))

    eps = store.list_epochs(run.id)
    # Every epoch has pass_execution=True, pass_coverage=True, score_aggregate=1.0
    for e in eps:
        assert e.pass_execution is True
        assert e.pass_coverage is True
        assert e.score_aggregate == pytest.approx(1.0)
        assert e.error is None
        assert e.issue_id is not None


@pytest.mark.asyncio
async def test_run_with_whitelist_only_runs_those_fixtures():
    store = InMemoryStore()
    executor = FakeExecutor(per_fixture_results=_all_pass_results())
    runner = BenchmarkRunner(store, executor)

    whitelist = ["add-backend-echo-endpoint", "add-backend-ping-endpoint"]
    run = await runner.run(RunOptions(epochs=1, fixture_ids=whitelist))

    epochs = store.list_epochs(run.id)
    fixture_ids = {e.fixture_id for e in epochs}
    assert fixture_ids == set(whitelist)


@pytest.mark.asyncio
async def test_run_baseline_flag_pins_after_completion():
    store = InMemoryStore()
    executor = FakeExecutor(per_fixture_results=_all_pass_results())
    runner = BenchmarkRunner(store, executor)

    run = await runner.run(RunOptions(epochs=1, is_baseline=True))
    assert run.is_baseline is True
    baseline = store.get_baseline()
    assert baseline is not None
    assert baseline.id == run.id


@pytest.mark.asyncio
async def test_run_records_cost_and_tokens():
    store = InMemoryStore()
    executor = FakeExecutor(
        per_fixture_results=_all_pass_results(),
        per_fixture_spend={
            "add-backend-echo-endpoint": 0.10,
            "add-backend-ping-endpoint": 0.20,
        },
    )
    runner = BenchmarkRunner(store, executor)

    run = await runner.run(RunOptions(epochs=1, fixture_ids=[
        "add-backend-echo-endpoint",
        "add-backend-ping-endpoint",
    ]))
    # Sum = 0.30 across 2 fixtures × 1 epoch.
    assert run.cost_total_usd == pytest.approx(0.30)
    assert run.cost_per_issue_usd == pytest.approx(0.15)


@pytest.mark.asyncio
async def test_run_caller_supplied_run_id_is_honoured():
    store = InMemoryStore()
    executor = FakeExecutor(per_fixture_results=_all_pass_results())
    runner = BenchmarkRunner(store, executor)

    run = await runner.run(RunOptions(epochs=1, run_id="my-custom-id"))
    assert run.id == "my-custom-id"
    assert store.get_run("my-custom-id") is not None


@pytest.mark.asyncio
async def test_run_label_propagates():
    store = InMemoryStore()
    executor = FakeExecutor(per_fixture_results=_all_pass_results())
    runner = BenchmarkRunner(store, executor)

    run = await runner.run(RunOptions(epochs=1, label="v0.6 candidate"))
    assert run.label == "v0.6 candidate"


@pytest.mark.asyncio
async def test_run_fake_executor_sees_one_call_per_epoch():
    store = InMemoryStore()
    executor = FakeExecutor(per_fixture_results=_all_pass_results())
    runner = BenchmarkRunner(store, executor)

    fixtures = _all_pass_results()
    await runner.run(RunOptions(epochs=2, fixture_ids=list(fixtures)[:3]))
    # 3 fixtures × 2 epochs = 6 calls.
    assert len(executor.calls) == 6
    # Every call has a (fixture_id, epoch_index) tuple.
    for fid, idx in executor.calls:
        assert fid in fixtures
        assert 0 <= idx < 2


@pytest.mark.asyncio
async def test_run_with_no_fixtures_raises():
    store = InMemoryStore()
    executor = FakeExecutor()
    runner = BenchmarkRunner(store, executor)

    with pytest.raises(ValueError):
        await runner.run(
            RunOptions(epochs=1, fixture_ids=["does-not-exist"])
        )


@pytest.mark.asyncio
async def test_run_artifacts_json_is_persisted():
    store = InMemoryStore()
    executor = FakeExecutor(per_fixture_results=_all_pass_results())
    runner = BenchmarkRunner(store, executor)

    await runner.run(RunOptions(epochs=1, fixture_ids=["add-backend-echo-endpoint"]))
    eps = store.list_epochs(store.list_runs()[0].id)
    blob = json.loads(eps[0].artifacts_json)
    assert blob["issue_id"] == "codex-add-backend-echo-endpoint"
    assert "Add the endpoint" in blob["tasks"]


# ---------------------------------------------------------------------------
# Error path — executor returns error result, runner persists it
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_persists_executor_error_as_failed_epoch():
    store = InMemoryStore()
    executor = FakeExecutor(
        per_fixture_results={"add-backend-echo-endpoint": [_ok_artifacts("add-backend-echo-endpoint")]},
        per_fixture_errors={"add-backend-ping-endpoint": "boom: conductor crashed"},
    )
    runner = BenchmarkRunner(store, executor)

    run = await runner.run(
        RunOptions(
            epochs=1,
            fixture_ids=["add-backend-echo-endpoint", "add-backend-ping-endpoint"],
        )
    )
    # Status is still "completed" — the run finished, one of the
    # epochs just failed. (The runner does not treat per-epoch
    # errors as run-level aborts; the user wants to see which
    # fixtures broke.)
    assert run.status == "completed"
    eps = store.list_epochs(run.id)
    by_id = {e.fixture_id: e for e in eps}
    assert by_id["add-backend-echo-endpoint"].error is None
    assert by_id["add-backend-ping-endpoint"].error == "boom: conductor crashed"
    # The failed epoch is counted as a failure in the aggregate.
    assert run.aggregate_pass_at_1 < 1.0
