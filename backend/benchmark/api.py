"""HTTP route handlers for the benchmark harness (PR3).

This module holds the **handler bodies** — pure functions that
take parsed inputs and return JSON-serializable dicts. The actual
``@router.post``/``@router.get`` declarations live in
``app/interfaces/api.py`` so the project's single FastAPI router
stays consolidated. Tests import the handler functions directly;
the API tests wrap the module with FastAPI's ``TestClient``.

Routes:

  - POST /codex/benchmark/runs        trigger a new run (async; 202)
  - GET  /codex/benchmark/runs/{id}   fetch one run (status + aggregate)
  - GET  /codex/benchmark/runs        list runs (with optional baseline filter)
  - GET  /codex/benchmark/baseline    current baseline
  - POST /codex/benchmark/baseline/{id}  pin a run as the new baseline
  - GET  /codex/benchmark/runs/{id}/diff  candidate-vs-baseline diff

The handlers deliberately do *not* run the benchmark themselves
— they mutate the job + store and (for POST) schedule a
background task via :mod:`benchmark.job`.
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from .aggregations import diff
from .correlation import CalibrationSet, calibration_report
from .runner import run_aggregate_from_store
from .job import (
    JOB_STATUS_COMPLETED,
    JOB_STATUS_FAILED,
    JOB_STATUS_PENDING,
    JOB_STATUS_RUNNING,
    Job,
    JobRegistry,
    make_progress_updater,
    start_job,
)
from .runner import (
    BenchmarkRunner,
    FakeExecutor,
    RealConductorExecutor,
    RunOptions,
)
from .scorers_impl import default_registry
from .store import BenchmarkStore, SqliteStore


DEFAULT_DB_PATH = "benchmark.db"


# ---------------------------------------------------------------------------
# Module-level singletons
# ---------------------------------------------------------------------------


def get_store() -> BenchmarkStore:
    """Module-level benchmark store (singleton).

    Mirrors the project's ``codex_store`` pattern in
    ``app.bootstrap``. Lazy: the DB file is created on first
    access. The store is closed only at process exit (the
    in-process benchmark DB is short-lived per CLI invocation
    anyway, so explicit close is not strictly needed).
    """
    global _store
    try:
        return _store  # type: ignore[name-defined]
    except NameError:
        _store = SqliteStore(DEFAULT_DB_PATH)
        return _store


# --- store + job registry (module-singletons) ----------------------------

# Test code can replace these with an InMemoryStore + a fresh
# JobRegistry before exercising the handlers. Production code
# uses the defaults set up by ``init_for_app``.
_store: BenchmarkStore | None = None
_registry = JobRegistry()


def init_for_app(store: BenchmarkStore, registry: JobRegistry) -> None:
    """Wire the singletons used by the route handlers. Called from
    the API lifespan / bootstrap step. Idempotent.

    Note: we swap the module-level ``_registry`` (not mutate it in
    place) so handlers reading ``get_registry()`` see exactly the
    registry the caller passed in. A test that calls
    ``init_for_app(InMemoryStore(), JobRegistry())`` then
    ``registry.create(...)`` expects the *same* registry to be
    visible from the handler.
    """
    global _store, _registry
    _store = store
    _registry = registry


def get_registry() -> JobRegistry:
    return _registry


# ---------------------------------------------------------------------------
# Request / response models (Pydantic-shaped dicts; FastAPI serializes)
# ---------------------------------------------------------------------------


class TriggerRunBody:
    """Pydantic model body for POST /codex/benchmark/runs.

    We re-declare the model here (rather than importing from
    :mod:`benchmark.api` into :mod:`app.interfaces.api`) to keep
    the FastAPI router file dependencies one-way: app/ does
    not import from benchmark/. The handler unpacks the body
    via ``body.<field>``.
    """

    label: str | None = None
    epochs: int = 3  # NB: the FastAPI-facing TriggerRunRequest below uses Field(ge=1); this class is for in-process use.
    fixture_ids: list[str] | None = None
    is_baseline: bool = False
    max_budget_usd: float | None = None
    project_id: str | None = None
    workspace_id: str | None = None
    dry_run: bool = False


# A second, properly-Pydantic version for the FastAPI body.
# Defined here so the route in app/interfaces/api.py can
# reference it via import.
try:
    from pydantic import BaseModel as _BaseModel, Field as _Field
except ImportError:  # pragma: no cover — pydantic is a hard dep
    _BaseModel = object  # type: ignore[assignment,misc]
    _Field = lambda default=None, **_: default  # type: ignore[assignment]


class TriggerRunRequest(_BaseModel):  # type: ignore[misc]
    """Pydantic request body for POST /codex/benchmark/runs.

    ``epochs`` is gated at the Pydantic layer (``ge=1``) so the
    route never receives a bad body. The earlier ``epochs: int =
    3`` default is what FastAPI surfaces in the auto-generated
    schema; the Field-based version validates at parse time.
    """

    label: str | None = None
    epochs: int = _Field(3, ge=1)
    fixture_ids: list[str] | None = None
    is_baseline: bool = False
    max_budget_usd: float | None = None
    project_id: str | None = None
    workspace_id: str | None = None
    dry_run: bool = False


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


async def trigger_run(body: dict[str, Any]) -> dict[str, Any]:
    """POST /codex/benchmark/runs handler.

    Returns 202 with the job id. The actual run proceeds in the
    background.

    Body validation is done via the ``TriggerRunRequest`` Pydantic
    model (epochs >= 1, etc.) before any work happens. Pydantic
    errors surface as 422 (the standard FastAPI shape); a missing
    or unknown field is 422, not 400.
    """
    # Validate body shape (epochs >= 1, types, etc.) before
    # touching the store or the registry. Import lazily to keep
    # the module-singleton pattern working.
    from pydantic import ValidationError as _ValidationError

    TriggerRunRequest = globals().get("TriggerRunRequest")
    if TriggerRunRequest is None:
        # Defensive — the module-level import failed earlier.
        from benchmark.api import TriggerRunRequest as _R  # type: ignore
        TriggerRunRequest = _R
    try:
        req = TriggerRunRequest.model_validate(body)
    except _ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    store = get_store()
    registry = get_registry()
    epochs = req.epochs
    is_baseline = req.is_baseline
    label = req.label
    fixture_ids = req.fixture_ids
    max_budget_usd = req.max_budget_usd
    project_id = req.project_id
    workspace_id = req.workspace_id
    dry_run = req.dry_run

    job = registry.create(
        "benchmark_run",
        meta={
            "label": label,
            "epochs": epochs,
            "fixture_ids": fixture_ids,
            "is_baseline": is_baseline,
        },
    )

    async def _coro():
        # Build the executor. Dry-run uses FakeExecutor so
        # the API can be exercised in a dev env without
        # spending on real CLI cycles.
        if dry_run or not (project_id and workspace_id):
            executor = FakeExecutor()
        else:
            executor = RealConductorExecutor(
                project_id=project_id, workspace_id=workspace_id
            )
        progress_cb = make_progress_updater(registry, job)
        # total_epochs is also written to meta so the leaderboard
        # can compute a progress hint without recomputing.
        registry.update(job)
        runner = BenchmarkRunner(store, executor, registry=default_registry())
        run_row = await runner.run(
            RunOptions(
                label=label,
                epochs=epochs,
                fixture_ids=fixture_ids,
                is_baseline=is_baseline,
                max_budget_usd=max_budget_usd,
            )
        )
        return run_row.id

    async def _on_complete(j: Job, _result, _exc) -> None:
        # Re-fetch the latest job from the registry (it may
        # have been mutated by progress callbacks).
        latest = registry.get(j.id) or j
        if latest.status == JOB_STATUS_COMPLETED and latest.result_ref is None:
            # result_ref is set in the wrapper below; this
            # branch is for cases where the coroutine returned
            # before the wrapper could set it. Unreachable in
            # the current implementation, kept defensive.
            latest.result_ref = (latest.meta or {}).get("run_id")

    # Wrap so we can stamp the run id on the job.
    async def _wrapped() -> str:
        run_id = await _coro()
        job.result_ref = run_id
        registry.update(job)
        return run_id

    await start_job(registry, job, _wrapped, on_complete=_on_complete)
    return {
        "job_id": job.id,
        "status": job.status,
        "status_url": f"/codex/benchmark/jobs/{job.id}",
    }


def _serialize_run(run, epochs: list | None = None) -> dict[str, Any]:
    return {
        "id": run.id,
        "created_at": run.created_at,
        "label": run.label,
        "orchestrator_version": run.orchestrator_version,
        "epoch_count": run.epoch_count,
        "fixture_ids": list(run.fixture_ids),
        "is_baseline": run.is_baseline,
        "status": run.status,
        "notes": run.notes,
        "aggregate_pass_at_1": run.aggregate_pass_at_1,
        "aggregate_pass_at_1_stderr": run.aggregate_pass_at_1_stderr,
        "cost_total_usd": run.cost_total_usd,
        "cost_per_issue_usd": run.cost_per_issue_usd,
        "total_input_tokens": run.total_input_tokens,
        "total_output_tokens": run.total_output_tokens,
        "total_duration_s": run.total_duration_s,
        "n_epochs": len(epochs) if epochs is not None else None,
    }


def get_run(run_id: str) -> dict[str, Any]:
    store = get_store()
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run {run_id!r} not found")
    epochs = store.list_epochs(run_id)
    return _serialize_run(run, epochs=epochs)


def get_run_diff(run_id: str) -> dict[str, Any]:
    store = get_store()
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run {run_id!r} not found")
    baseline = store.get_baseline()
    if baseline is None:
        return {
            "candidate": _serialize_run(run, epochs=store.list_epochs(run_id)),
            "baseline": None,
            "diff": None,
            "note": "no baseline pinned yet; set one with POST /codex/benchmark/baseline/{run_id}",
        }
    if baseline.id == run_id:
        return {
            "candidate": _serialize_run(baseline, epochs=store.list_epochs(run_id)),
            "baseline": None,
            "diff": None,
            "note": "the requested run IS the baseline; pick a candidate to diff against",
        }
    cand_agg = run_aggregate_from_store(store, run_id)
    base_agg = run_aggregate_from_store(store, baseline.id)
    d = diff(cand_agg, base_agg, baseline_label=baseline.label or baseline.id, candidate_label=run.label or run.id)
    return {
        "candidate": _serialize_run(run, epochs=store.list_epochs(run_id)),
        "baseline": _serialize_run(baseline, epochs=store.list_epochs(baseline.id)),
        "diff": {
            "aggregate_delta": d.aggregate_delta,
            "aggregate_status": d.aggregate_status,
            "candidate_stderr": d.candidate_stderr,
            "baseline_stderr": d.baseline_stderr,
            "regressed_fixtures": [x.fixture_id for x in d.regressed_fixtures()],
            "improved_fixtures": [x.fixture_id for x in d.improved_fixtures()],
            "per_fixture": [
                {
                    "fixture_id": x.fixture_id,
                    "candidate_pass_at_1": x.candidate_pass_at_1,
                    "baseline_pass_at_1": x.baseline_pass_at_1,
                    "delta": x.delta,
                    "status": x.status,
                }
                for x in d.per_fixture
            ],
        },
    }


def list_runs(*, limit: int = 50) -> dict[str, Any]:
    store = get_store()
    runs = store.list_runs()[:limit]
    return {"runs": [_serialize_run(r) for r in runs]}


def get_baseline() -> dict[str, Any]:
    store = get_store()
    baseline = store.get_baseline()
    if baseline is None:
        return {"baseline": None}
    return {"baseline": _serialize_run(baseline, epochs=store.list_epochs(baseline.id))}


def set_baseline(run_id: str) -> dict[str, Any]:
    store = get_store()
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run {run_id!r} not found")
    store.set_baseline(run_id)
    return {"ok": True, "run_id": run_id}


# ---------------------------------------------------------------------------
# Calibration (PR3 methodology artifact)
# ---------------------------------------------------------------------------


def get_calibration_report(*, floor: float = 0.7) -> dict[str, Any]:
    """GET /codex/benchmark/calibration.

    Loads the on-disk calibration set, fills the judge scores
    by re-running the FixedResponseBackend over each item's
    excerpt (the calibration JSON stores the *excerpt* — the
    judge text is constructed at call time), and reports the
    correlation.
    """
    from .judge import FixedResponseBackend
    from pathlib import Path

    cal_root = Path(__file__).parent / "calibration"
    cs = CalibrationSet.from_dir(cal_root)
    # The shipped calibration set's items have judge_score=null
    # (they are hand-labeled; the judge hasn't run on them yet).
    # For the API surface we let the operator pick a calibration
    # backend (e.g. a fixed response for smoke). For now we
    # simply report the items with their human scores and
    # explicitly return judge_score=null so the caller knows
    # the judge has not been run on this set.
    report = calibration_report(cs.all(), floor=floor)
    return {
        "n": report.n,
        "pearson": report.pearson,
        "spearman": report.spearman,
        "floor": report.floor,
        "is_calibrated": report.is_calibrated,
        "weakest_item": report.weakest_item,
        "summary": report.summary,
        "items": [
            {
                "id": it.id,
                "fixture_id": it.fixture_id,
                "human_score": it.human_score,
                "judge_score": it.judge_score,
                "note": it.note,
            }
            for it in cs.all()
        ],
    }


def get_job(job_id: str) -> dict[str, Any]:
    registry = get_registry()
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"job {job_id!r} not found")
    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
        "result_ref": job.result_ref,
        "error": job.error,
        "progress": job.progress,
        "meta": job.meta,
    }
