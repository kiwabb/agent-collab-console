"""Tests for the benchmark API route handlers (PR3).

We exercise the handlers through the in-process FastAPI app
(TestClient). The benchmark package is wired with an
InMemoryStore + a fresh JobRegistry so the test surface is
fully isolated from the production sqlite file.

The tests cover the full HTTP contract:

  - POST /codex/benchmark/runs        trigger, 202 + job id
  - GET  /codex/benchmark/jobs/{id}   poll, status transitions
  - GET  /codex/benchmark/runs/{id}   fetch run + aggregate
  - GET  /codex/benchmark/runs        list
  - GET  /codex/benchmark/baseline    read baseline (none yet)
  - POST /codex/benchmark/baseline/{id}  pin baseline
  - GET  /codex/benchmark/runs/{id}/diff  diff against baseline
  - GET  /codex/benchmark/calibration  shipped calibration set loads
"""

from __future__ import annotations  # noqa: I001

import asyncio  # noqa: F401
import json  # noqa: F401
import time  # noqa: F401
from pathlib import Path  # noqa: F401

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import benchmark.api as benchmark_api  # noqa: F401
from benchmark import api as benchmark_handlers
from benchmark.job import (
    JOB_STATUS_COMPLETED,
    JOB_STATUS_FAILED,
    JOB_STATUS_PENDING,
    JOB_STATUS_RUNNING,
    JobRegistry,
)
from benchmark.runner import (
    BenchmarkRunner,  # noqa: F401
    FakeExecutor,  # noqa: F401
    RunOptions,  # noqa: F401
)
from benchmark.scorers_impl import default_registry  # noqa: F401
from benchmark.store import InMemoryStore, SqliteStore  # noqa: F401
from benchmark.types import CommandResult, IssueArtifacts  # noqa: F401


# ---------------------------------------------------------------------------
# Test app + setup
# ---------------------------------------------------------------------------


def _make_test_app(*, store: InMemoryStore | None = None) -> FastAPI:
    """Build a minimal FastAPI app with only the benchmark routes
    wired in. Avoids the heavyweight app.main / app.bootstrap import
    chain in the test, but exercises the same route decorators
    from app/interfaces/api.py (we mirror them here for the
    test)."""
    from app.interfaces.api import (  # noqa: I001
        trigger_benchmark_run,
        list_benchmark_runs,
        get_benchmark_run,
        get_benchmark_run_diff,
        get_benchmark_baseline,
        set_benchmark_baseline,
        get_benchmark_job,
        get_benchmark_calibration,
    )

    app = FastAPI()
    app.post("/codex/benchmark/runs", status_code=202)(trigger_benchmark_run)
    app.get("/codex/benchmark/runs")(list_benchmark_runs)
    app.get("/codex/benchmark/runs/{run_id}")(get_benchmark_run)
    app.get("/codex/benchmark/runs/{run_id}/diff")(get_benchmark_run_diff)
    app.get("/codex/benchmark/baseline")(get_benchmark_baseline)
    app.post("/codex/benchmark/baseline/{run_id}")(set_benchmark_baseline)
    app.get("/codex/benchmark/jobs/{job_id}")(get_benchmark_job)
    app.get("/codex/benchmark/calibration")(get_benchmark_calibration)
    return app


@pytest.fixture
def client():
    """In-memory store + fresh JobRegistry, mounted in a minimal
    FastAPI app. Each test gets a clean slate."""
    store = InMemoryStore()
    registry = JobRegistry()
    benchmark_handlers.init_for_app(store, registry)
    # Swap the executor used by the dry-run path so the run
    # completes quickly with deterministic outputs. The API
    # builds its own FakeExecutor; for full control we route
    # trigger_run through a custom runner via a fixture-level
    # monkey-patch (see below).
    yield TestClient(_make_test_app()), store, registry
    # Best-effort close in case a SqliteStore was used.
    try:
        if hasattr(store, "close"):
            store.close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Calibration report
# ---------------------------------------------------------------------------


def test_calibration_report_loads_shipped_set(client):
    c, _s, _r = client
    res = c.get("/codex/benchmark/calibration")
    assert res.status_code == 200
    body = res.json()
    assert body["n"] == 8
    assert body["floor"] == 0.7
    assert body["is_calibrated"] is False  # judge hasn't run on the set
    assert all(item["judge_score"] is None for item in body["items"])
    assert all(0.0 <= item["human_score"] <= 1.0 for item in body["items"])


def test_calibration_report_floor_query_param(client):
    c, _s, _r = client
    res = c.get("/codex/benchmark/calibration?floor=0.5")
    assert res.status_code == 200
    assert res.json()["floor"] == 0.5


# ---------------------------------------------------------------------------
# Baseline pin
# ---------------------------------------------------------------------------


def test_baseline_starts_empty(client):
    c, _s, _r = client
    res = c.get("/codex/benchmark/baseline")
    assert res.status_code == 200
    assert res.json() == {"baseline": None}


def test_set_baseline_unknown_run_returns_404(client):
    c, _s, _r = client
    res = c.post("/codex/benchmark/baseline/nope")
    assert res.status_code == 404


def test_set_baseline_then_get_returns_it(client):
    c, store, _r = client
    # Seed a run via the store directly (faster than going
    # through the async trigger).
    from benchmark.store import make_run_row, BenchmarkEpoch  # noqa: F401, I001

    run = make_run_row(
        run_id="r1",
        label="v0.5",
        fixture_ids=["a"],
        epoch_count=1,
    )
    run.status = "completed"
    run.aggregate_pass_at_1 = 0.8
    store.create_run(run)
    # Pin it.
    res = c.post("/codex/benchmark/baseline/r1")
    assert res.status_code == 200
    assert res.json() == {"ok": True, "run_id": "r1"}
    # GET baseline returns it.
    res = c.get("/codex/benchmark/baseline")
    assert res.status_code == 200
    body = res.json()
    assert body["baseline"]["id"] == "r1"
    assert body["baseline"]["is_baseline"] is True


# ---------------------------------------------------------------------------
# Run list / fetch
# ---------------------------------------------------------------------------


def test_list_runs_empty(client):
    c, _s, _r = client
    res = c.get("/codex/benchmark/runs")
    assert res.status_code == 200
    assert res.json() == {"runs": []}


def test_list_and_get_run_round_trip(client):
    c, store, _r = client
    from benchmark.store import make_run_row

    store.create_run(make_run_row(run_id="r1", label="v0.5", fixture_ids=["a", "b"], epoch_count=2))
    res = c.get("/codex/benchmark/runs")
    assert res.status_code == 200
    body = res.json()
    assert len(body["runs"]) == 1
    assert body["runs"][0]["id"] == "r1"

    res = c.get("/codex/benchmark/runs/r1")
    assert res.status_code == 200
    assert res.json()["id"] == "r1"
    assert res.json()["n_epochs"] == 0  # no epochs added


def test_get_unknown_run_returns_404(client):
    c, _s, _r = client
    res = c.get("/codex/benchmark/runs/nope")
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------


def test_diff_with_no_baseline(client):
    c, store, _r = client
    from benchmark.store import make_run_row

    store.create_run(make_run_row(run_id="r1", label="candidate", fixture_ids=[], epoch_count=1))
    res = c.get("/codex/benchmark/runs/r1/diff")
    assert res.status_code == 200
    body = res.json()
    assert body["diff"] is None
    assert "no baseline pinned" in body["note"]


def test_diff_candidate_is_baseline_returns_polite_message(client):
    c, store, _r = client
    from benchmark.store import make_run_row

    store.create_run(
        make_run_row(
            run_id="r1",
            label="baseline",
            fixture_ids=[],
            epoch_count=1,
        )
    )
    # Pin r1 as the baseline so the diff endpoint can detect that
    # the candidate IS the baseline.
    store.set_baseline("r1")
    res = c.get("/codex/benchmark/runs/r1/diff")
    assert res.status_code == 200
    body = res.json()
    assert body["diff"] is None
    assert "IS the baseline" in body["note"]


# ---------------------------------------------------------------------------
# Job polling
# ---------------------------------------------------------------------------


def test_get_unknown_job_returns_404(client):
    c, _s, _r = client
    res = c.get("/codex/benchmark/jobs/nope")
    assert res.status_code == 404


def test_job_initial_state_is_pending(client):
    c, _s, registry = client
    job = registry.create("benchmark_run", meta={"label": "test"})
    res = c.get(f"/codex/benchmark/jobs/{job.id}")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == JOB_STATUS_PENDING
    assert body["kind"] == "benchmark_run"
    assert body["progress"] == 0.0


def test_job_transitions_to_running_and_completed(client):
    c, _s, registry = client
    job = registry.create("benchmark_run", meta={"label": "test"})
    # Simulate a runner.
    job.status = JOB_STATUS_RUNNING
    job.started_at = "2026-06-03T10:00:00"
    job.progress = 0.5
    registry.update(job)
    res = c.get(f"/codex/benchmark/jobs/{job.id}")
    body = res.json()
    assert body["status"] == JOB_STATUS_RUNNING
    assert body["progress"] == 0.5

    job.status = JOB_STATUS_COMPLETED
    job.completed_at = "2026-06-03T10:01:00"
    job.result_ref = "run-1"
    job.progress = 1.0
    registry.update(job)
    res = c.get(f"/codex/benchmark/jobs/{job.id}")
    body = res.json()
    assert body["status"] == JOB_STATUS_COMPLETED
    assert body["result_ref"] == "run-1"


def test_job_failed_records_error(client):
    c, _s, registry = client
    job = registry.create("benchmark_run")
    job.status = JOB_STATUS_FAILED
    job.error = "RuntimeError: conductor crashed"
    registry.update(job)
    res = c.get(f"/codex/benchmark/jobs/{job.id}")
    body = res.json()
    assert body["status"] == JOB_STATUS_FAILED
    assert "RuntimeError" in body["error"]


# ---------------------------------------------------------------------------
# Trigger → poll → fetch round trip (in-process)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trigger_run_creates_job_in_pending_then_running(monkeypatch):
    """Smoke-test the trigger flow through the FastAPI app.

    The trigger creates a job in PENDING and schedules a
    background task. We don't wait for completion (the dry-run
    path would still spin FakeExecutor over every fixture for
    every epoch, which is slow in a test). Instead we verify:
      - POST returns 202 with a job id
      - The job is observable via GET
      - The handler does not block on the run
    """
    from app.interfaces.api import (  # noqa: I001
        trigger_benchmark_run,
        get_benchmark_job,
    )

    store = InMemoryStore()
    registry = JobRegistry()
    benchmark_handlers.init_for_app(store, registry)
    app = FastAPI()
    app.post("/codex/benchmark/runs", status_code=202)(trigger_benchmark_run)
    app.get("/codex/benchmark/jobs/{job_id}")(get_benchmark_job)
    c = TestClient(app)

    res = c.post(
        "/codex/benchmark/runs",
        json={"label": "pr3-smoke", "dry_run": True, "epochs": 1},
    )
    assert res.status_code == 202
    body = res.json()
    assert "job_id" in body
    job_id = body["job_id"]
    # The handler returns immediately; the job exists in the
    # registry and is observable.
    res = c.get(f"/codex/benchmark/jobs/{job_id}")
    assert res.status_code == 200
    j = res.json()
    # The job is either pending (handler returned before the
    # background task started) or running (background task already
    # grabbed the slot). Both are valid intermediate states.
    assert j["status"] in (JOB_STATUS_PENDING, JOB_STATUS_RUNNING, JOB_STATUS_COMPLETED)
    assert j["kind"] == "benchmark_run"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_trigger_with_epochs_zero_rejected(client):
    """Pydantic rejects epochs=0 at the body parse layer (422,
    not 400). The point is the same: the request never reaches
    the handler."""
    c, _s, _r = client
    res = c.post("/codex/benchmark/runs", json={"epochs": 0})
    assert res.status_code == 422
    detail = res.json().get("detail", [])
    # Pydantic surfaces the constraint as a structured error; we
    # only assert the request was rejected (the exact message is
    # an implementation detail of Pydantic).
    assert detail
