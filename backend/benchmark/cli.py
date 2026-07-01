"""CLI entry point for the benchmark runner.

Usage (from the repo root):

    cd backend
    .venv/bin/python -m benchmark.cli \\
        --epochs 3 \\
        --label "v0.6 candidate" \\
        --fixture-ids add-backend-echo-endpoint,add-backend-ping-endpoint \\
        --max-budget-usd 5.00

Flags:

  --db PATH                benchmark DB file (default: backend/benchmark.db)
  --epochs N               epochs per fixture (default: 3)
  --label TEXT             human-readable label for the run
  --fixture-ids A,B,C      optional whitelist of golden fixture ids
  --baseline               pin the run as the new baseline
  --max-budget-usd USD     abort the run if cumulative spend exceeds this
  --project-id ID          (real path) project to anchor the issues under
  --workspace-id ID        (real path) workspace for the codex store
  --dry-run                run with FakeExecutor; no real Conductor calls

The ``--dry-run`` flag swaps in a ``FakeExecutor`` that returns
pre-canned empty artifacts. It is the way to smoke-test the runner
plumbing (loop order, store writes, aggregation) without paying
for a real CLI run.

When ``--dry-run`` is NOT set, the CLI uses ``RealConductorExecutor``,
which requires ``--project-id`` and ``--workspace-id`` and will spend
real CLI cycles. Operators run it manually; the benchmark harness
is offline batch, not CI (per the task PRD's hard constraint).
"""

from __future__ import annotations  # noqa: I001

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .runner import (
    BenchmarkRunner,
    FakeExecutor,
    RealConductorExecutor,
    RunOptions,
)
from .scorers_impl import default_registry
from .store import SqliteStore


DEFAULT_DB = Path(__file__).parent.parent / "benchmark.db"


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m benchmark.cli",
        description="Run the agent-output benchmark over the golden set.",
    )
    p.add_argument("--db", type=Path, default=DEFAULT_DB, help="benchmark DB file")
    p.add_argument("--epochs", type=int, default=3, help="epochs per fixture")
    p.add_argument("--label", type=str, default=None, help="run label")
    p.add_argument(
        "--fixture-ids",
        type=str,
        default=None,
        help="comma-separated whitelist of fixture ids (default: all)",
    )
    p.add_argument(
        "--baseline",
        action="store_true",
        help="pin the resulting run as the new baseline",
    )
    p.add_argument(
        "--max-budget-usd",
        type=float,
        default=None,
        help="abort the run when cumulative spend exceeds this",
    )
    p.add_argument(
        "--project-id",
        type=str,
        default=None,
        help="(real path) codex project id to anchor issues under",
    )
    p.add_argument(
        "--workspace-id",
        type=str,
        default=None,
        help="(real path) codex workspace id",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="use FakeExecutor; no real Conductor calls",
    )
    p.add_argument(
        "--catalog-snapshot",
        type=str,
        default=None,
        help="path to a JSON file with the model catalog snapshot",
    )
    p.add_argument(
        "--orchestrator-version",
        type=str,
        default=None,
        help="git SHA or version string for the orchestrator",
    )
    return p


async def _async_main(args: argparse.Namespace) -> int:
    fixture_ids = (
        [s.strip() for s in args.fixture_ids.split(",") if s.strip()] if args.fixture_ids else None
    )
    catalog_snapshot: str | None = None
    if args.catalog_snapshot:
        catalog_snapshot = Path(args.catalog_snapshot).read_text(encoding="utf-8")
    elif args.dry_run:
        catalog_snapshot = json.dumps({"dry_run": True})

    if args.dry_run:
        executor = FakeExecutor()
    else:
        if not (args.project_id and args.workspace_id):
            print(
                "error: --project-id and --workspace-id are required for real (non --dry-run) runs",
                file=sys.stderr,
            )
            return 2
        executor = RealConductorExecutor(project_id=args.project_id, workspace_id=args.workspace_id)

    with SqliteStore(args.db) as store:
        runner = BenchmarkRunner(store, executor, registry=default_registry())
        run = await runner.run(
            RunOptions(
                label=args.label,
                epochs=args.epochs,
                fixture_ids=fixture_ids,
                is_baseline=args.baseline,
                max_budget_usd=args.max_budget_usd,
                catalog_snapshot=catalog_snapshot,
                orchestrator_version=args.orchestrator_version,
            )
        )

    # Summary line: human-readable on stdout, JSON-friendly for piping.
    print(
        f"completed run {run.id} ({run.label!r}) — "
        f"pass@1 = {run.aggregate_pass_at_1:.3f} "
        f"± {run.aggregate_pass_at_1_stderr:.3f}, "
        f"cost = ${run.cost_total_usd:.4f} "
        f"(${run.cost_per_issue_usd:.4f}/issue), "
        f"{run.total_input_tokens} in / {run.total_output_tokens} out tokens"
    )
    return 0


def main() -> int:
    args = _build_argparser().parse_args()
    return asyncio.run(_async_main(args))


if __name__ == "__main__":
    sys.exit(main())
