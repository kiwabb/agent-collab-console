"""Benchmark runner — orchestrates a multi-epoch run over the golden set.

The runner is the layer that:

  1. Loads the golden fixtures.
  2. For each fixture, runs ``N`` epochs in isolated worktrees,
     capturing one ``IssueArtifacts`` per epoch.
  3. Scores every epoch with the registered scorers.
  4. Persists the run + per-epoch rows to the store.
  5. Finalises the run with aggregate metrics and (optionally)
     pins it as the new baseline.

The runner is split into a thin orchestration layer
(:class:`BenchmarkRunner`) and a pluggable executor
(:class:`IssueExecutor`). The executor is the boundary that touches
the real Conductor; everything above it is pure orchestration that
is testable with a fake executor that returns pre-canned
``IssueArtifacts``.

Two executors ship in this PR:

  - :class:`FakeExecutor` — returns the ``IssueArtifacts`` you
    hand it. Used by the unit tests; not for production.
  - :class:`RealConductorExecutor` — thin adapter over the
    existing ``create_codex_issue`` + ``auto_start_issue_graph`` +
    ``run_issue_conductor_loop`` machinery. Reads the QA real-
    command results and the engineer's completed tasks at the end
    of each epoch to build the ``IssueArtifacts``. The CLI uses
    this in production.

The runner does **not** run executors in parallel: the conductor
itself already serializes per-issue worktree writes, and parallel
benchmarks would only multiply cost without speeding up a
sequential flaky-output study. The PR3 async job layer can layer
parallelism on top if cost analysis justifies it.
"""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import signal
import sys
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass, field  # noqa: F401
from datetime import datetime
from inspect import iscoroutinefunction
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, TypeGuard, runtime_checkable

from app.application.project_command import build_project_child_env

from .aggregations import (
    FixtureStats,  # noqa: F401
    RunAggregate,
    per_fixture,
)
from .aggregations import (
    aggregate as aggregate_stats,
)
from .golden_loader import load_all
from .golden_schema import GoldenIssue, PinnedCommand
from .scorers import ScorerRegistry
from .scorers_impl import default_registry
from .store import (
    BenchmarkEpoch,
    BenchmarkRun,
    BenchmarkStore,
    InMemoryStore,  # noqa: F401
    make_run_row,
)
from .types import CommandResult, IssueArtifacts, Score

if TYPE_CHECKING:
    from app.domain.models import (
        CodexSession,
        ExecutionProcess,
        Project,
        WorkflowEdge,
        WorkflowGraph,
        WorkflowNode,
    )


_OUTPUT_TAIL_BYTES = 16 * 1024
_PRECONDITION_INFRA_EXIT_CODES = frozenset({124, 126, 127})
_FRONTEND_PACKAGE_EXECUTABLES = frozenset({"bun", "npm", "npx", "pnpm", "yarn"})


def _decode_output_tail(data: bytes) -> str:
    return data[-_OUTPUT_TAIL_BYTES:].decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Executor protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class IssueExecutor(Protocol):
    """Runs ONE golden issue to completion and returns the artifacts.

    The runner calls ``execute(fixture, epoch_index)`` once per
    (fixture, epoch). The implementation owns the worktree, the
    conductor, and the QA pass/fail capture; it returns a
    structured ``ExecutorResult`` so the runner can score + persist.
    """

    async def execute(self, fixture: GoldenIssue, epoch_index: int) -> "ExecutorResult": ...  # noqa: UP037


@runtime_checkable
class BenchmarkRuntimeStore(Protocol):
    async def load_codex_workspace(self, workspace_id: str) -> CodexSession | None: ...

    async def load_project(self, project_id: str) -> Project | None: ...

    async def load_workflow_graph_for_issue(self, issue_id: str) -> WorkflowGraph | None: ...

    async def save_workflow_graph(
        self,
        graph: WorkflowGraph,
        nodes: list[WorkflowNode] | None = None,
        edges: list[WorkflowEdge] | None = None,
    ) -> None: ...

    async def list_codex_tasks(
        self,
        session_id: str | None = None,
        issue_id: str | None = None,
        project_id: str | None = None,
    ) -> list[dict[str, object]]: ...

    async def list_execution_processes(
        self, session_id: str | None = None, task_id: str | None = None
    ) -> list[ExecutionProcess]: ...


def _is_benchmark_runtime_store(store: object) -> TypeGuard[BenchmarkRuntimeStore]:
    return (
        isinstance(store, BenchmarkRuntimeStore)
        and iscoroutinefunction(store.load_codex_workspace)
        and iscoroutinefunction(store.load_project)
        and iscoroutinefunction(store.load_workflow_graph_for_issue)
        and iscoroutinefunction(store.save_workflow_graph)
        and iscoroutinefunction(store.list_codex_tasks)
        and iscoroutinefunction(store.list_execution_processes)
    )


@dataclass
class ExecutorResult:
    """One epoch's output. The runner turns this into an
    ``IssueArtifacts`` and then into ``BenchmarkEpoch`` + scores."""

    issue_id: str | None
    artifacts: IssueArtifacts
    spent_usd: float
    input_tokens: int
    output_tokens: int
    duration_s: float
    error: str | None = None


# ---------------------------------------------------------------------------
# Fake executor (for tests)
# ---------------------------------------------------------------------------


class FakeExecutor:
    """Returns pre-canned results. Errors are returned in the result
    rather than raised, so the runner can persist them as a
    failed epoch (the production code path should never raise
    from inside an epoch; the conductor failure handling is the
    executor's responsibility)."""

    def __init__(
        self,
        *,
        per_fixture_results: dict[str, list[IssueArtifacts]] | None = None,
        per_fixture_errors: dict[str, str] | None = None,
        per_fixture_spend: dict[str, float] | None = None,
        latency_s: float = 0.0,
    ) -> None:
        self._results = per_fixture_results or {}
        self._errors = per_fixture_errors or {}
        self._spend = per_fixture_spend or {}
        self._latency = latency_s
        self.calls: list[tuple[str, int]] = []  # for test assertions

    async def execute(self, fixture: GoldenIssue, epoch_index: int) -> ExecutorResult:
        self.calls.append((fixture.id, epoch_index))
        if self._latency > 0:
            await asyncio.sleep(self._latency)
        if fixture.id in self._errors:
            return ExecutorResult(
                issue_id=None,
                artifacts=IssueArtifacts(issue_id=fixture.id),
                spent_usd=0.0,
                input_tokens=0,
                output_tokens=0,
                duration_s=0.0,
                error=self._errors[fixture.id],
            )
        epochs = self._results.get(fixture.id, [])
        idx = min(epoch_index, len(epochs) - 1) if epochs else 0
        artifacts = epochs[idx] if epochs else IssueArtifacts(issue_id=fixture.id)
        return ExecutorResult(
            issue_id=f"fake-{fixture.id}-{epoch_index}",
            artifacts=artifacts,
            spent_usd=self._spend.get(fixture.id, 0.0),
            input_tokens=100,
            output_tokens=50,
            duration_s=0.1,
        )


# ---------------------------------------------------------------------------
# Real-conductor executor (production path)
# ---------------------------------------------------------------------------


class RealConductorExecutor:
    """Drives the real Conductor on one golden issue and captures
    the artifacts.

    Implementation strategy (PR2-only — the unit tests don't cover
    this path because the conductor is out of process and costs
    money):

      1. Open a fresh worktree via the existing
         ``worktree_manager`` (the conductor's per-issue isolation).
      2. ``create_codex_issue`` with the fixture's title /
         description / acceptance_criteria, capturing the returned
         issue id.
      3. Link only the trusted primary repo's frontend dependency directory
         when the fixture needs it, then require at least one pinned check
         to fail before spending model budget.
      4. Create the issue WorkflowGraph and run ``run_issue_conductor_loop``
         with the real workflow task dispatcher.
      5. Run every fixture-pinned command in the issue worktree with
         structured argv and capture exact ``CommandResult`` evidence.
      6. Read the engineer's completed task titles from
         ``codex_tasks``.
      7. Leave the issue/worktree in the normal console lifecycle so failed
         paid epochs remain inspectable and can be cleaned through existing
         issue controls.
    """

    def __init__(self, *, project_id: str, workspace_id: str) -> None:
        self._project_id = project_id
        self._workspace_id = workspace_id

    async def execute(self, fixture: GoldenIssue, epoch_index: int) -> ExecutorResult:
        # Defer real imports to call time so unit tests can
        # construct the class without the conductor on the path.
        from app.application.event_bus import _workflow_task_dispatcher, event_bus  # noqa: I001
        from app.application.conductor_main_loop import run_issue_conductor_loop
        from app.bootstrap import codex_store
        from app.domain.models import WorkflowGraph
        from app.interfaces.api import CreateIssueRequest, create_codex_issue

        started = time.monotonic()
        error: str | None = None
        issue_id: str | None = None
        artifacts = IssueArtifacts(issue_id=fixture.id)
        spent = 0.0
        in_tok = 0
        out_tok = 0

        try:
            if not _is_benchmark_runtime_store(codex_store):
                raise RuntimeError("benchmark real executor requires async codex store")
            workspace = await codex_store.load_codex_workspace(self._workspace_id)
            if workspace is None:
                raise RuntimeError(f"benchmark workspace not found: {self._workspace_id}")
            if workspace.project_id != self._project_id:
                raise RuntimeError(
                    "benchmark workspace belongs to a different project: "
                    f"expected {self._project_id!r}, got {workspace.project_id!r}"
                )
            project = await codex_store.load_project(self._project_id)
            if project is None:
                raise RuntimeError(f"benchmark project not found: {self._project_id}")
            description = fixture.description
            if fixture.acceptance_criteria:
                criteria = "\n".join(f"- {item}" for item in fixture.acceptance_criteria)
                description = f"{description or ''}\n\nAcceptance criteria:\n{criteria}".strip()
            issue = await create_codex_issue(
                CreateIssueRequest(
                    session_id=self._workspace_id,
                    title=fixture.title,
                    description=description,
                    acceptance_criteria=list(fixture.acceptance_criteria),
                    acceptance_criteria_confirmed=True,
                )
            )
            issue_id = issue.id

            if issue.project_id != self._project_id:
                raise RuntimeError(
                    "benchmark workspace belongs to a different project: "
                    f"expected {self._project_id!r}, got {issue.project_id!r}"
                )

            if issue.git_worktree_path is None:
                raise RuntimeError("benchmark issue has no worktree after creation")

            self._prepare_trusted_dependencies(
                fixture=fixture,
                primary_repo_path=project.repo_path,
                worktree_path=issue.git_worktree_path,
            )
            precondition_results = await self._run_pinned_commands(
                fixture,
                issue.git_worktree_path,
            )
            artifacts = IssueArtifacts(
                issue_id=issue.id,
                prd_acceptance_criteria=list(fixture.acceptance_criteria),
                precondition_results=precondition_results,
            )
            self._require_failing_precondition(precondition_results)

            graph = await codex_store.load_workflow_graph_for_issue(issue.id)
            if graph is None:
                now = datetime.now()
                graph = WorkflowGraph(
                    id=str(uuid.uuid4()),
                    issue_id=issue.id,
                    status="running",
                    dag_json=json.dumps(
                        {
                            "nodes": [],
                            "edges": [],
                            "meta": {"created_by": "benchmark"},
                        }
                    ),
                    created_by="benchmark",
                    created_at=now,
                    updated_at=now,
                )
                await codex_store.save_workflow_graph(graph, nodes=[], edges=[])

            try:
                # Pinned checks still run after a failed outcome so a paid epoch
                # retains evidence, but the epoch itself cannot score as successful.
                conductor_result = await run_issue_conductor_loop(
                    issue,
                    project_id=self._project_id,
                    store=codex_store,
                    event_bus=event_bus,
                    task_dispatcher_fn=_workflow_task_dispatcher,
                )
                if conductor_result.status != "done":
                    error = f"conductor finished with status {conductor_result.status!r}"
            except Exception as exc:  # External orchestration boundary; evidence must persist.
                error = f"{type(exc).__name__}: {exc}"

            artifacts = await self._collect_artifacts(
                codex_store,
                fixture,
                issue.id,
                issue.git_worktree_path,
                precondition_results,
            )
            spent, in_tok, out_tok = await self._collect_cost(codex_store, issue.id)
        # This is the executor boundary: conductor, store, git, and process-launch
        # failures must become persisted epoch evidence instead of losing the run.
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"

        return ExecutorResult(
            issue_id=issue_id,
            artifacts=artifacts,
            spent_usd=spent,
            input_tokens=in_tok,
            output_tokens=out_tok,
            duration_s=time.monotonic() - started,
            error=error,
        )

    async def _collect_artifacts(
        self,
        codex_store: BenchmarkRuntimeStore,
        fixture: GoldenIssue,
        issue_id: str,
        worktree_path: str,
        precondition_results: list[CommandResult],
    ) -> IssueArtifacts:
        """Run pinned checks and collect the completed task titles."""
        qa_results = await self._run_pinned_commands(fixture, worktree_path)
        tasks = await codex_store.list_codex_tasks(issue_id=issue_id)
        completed = [
            title
            for t in tasks
            if t.get("status") in ("done", "completed") and isinstance(title := t.get("title"), str)
        ]

        return IssueArtifacts(
            issue_id=issue_id,
            prd_acceptance_criteria=list(fixture.acceptance_criteria),
            precondition_results=precondition_results,
            qa_results=qa_results,
            completed_engineer_tasks=completed,
        )

    @staticmethod
    def _require_failing_precondition(results: list[CommandResult]) -> None:
        infrastructure_failures = [
            result
            for result in results
            if result.timed_out or result.exit_code in _PRECONDITION_INFRA_EXIT_CODES
        ]
        if infrastructure_failures:
            commands = ", ".join(result.command for result in infrastructure_failures)
            raise RuntimeError(
                "benchmark precondition could not be established because pinned "
                f"checks had infrastructure failures: {commands}"
            )
        if all(result.exit_code == result.expected_exit_code for result in results):
            raise RuntimeError(
                "benchmark fixture already passes before the Conductor runs; "
                "select a project revision where at least one pinned check fails"
            )

    @staticmethod
    def _prepare_trusted_dependencies(
        *,
        fixture: GoldenIssue,
        primary_repo_path: str,
        worktree_path: str,
    ) -> None:
        needs_frontend_dependencies = any(
            Path(command.cwd).parts[:1] == ("frontend",)
            and Path(command.argv[0]).name in _FRONTEND_PACKAGE_EXECUTABLES
            for command in fixture.pinned_qa_commands
        )
        if not needs_frontend_dependencies:
            return

        primary_root = Path(primary_repo_path).resolve()
        worktree_root = Path(worktree_path).resolve()
        if primary_root == worktree_root:
            raise RuntimeError("benchmark issue worktree must be isolated from the primary repo")

        target = worktree_root / "frontend" / "node_modules"
        target_parent = target.parent.resolve()
        try:
            target_parent.relative_to(worktree_root)
        except ValueError as exc:
            raise RuntimeError(
                "benchmark frontend directory resolves outside the issue worktree"
            ) from exc

        source_path = primary_root / "frontend" / "node_modules"
        if not source_path.exists() and not source_path.is_symlink():
            raise RuntimeError(
                "trusted primary frontend dependencies are missing; install "
                "frontend/node_modules in the selected project before this benchmark"
            )
        source = source_path.resolve()
        try:
            source.relative_to(primary_root)
        except ValueError as exc:
            raise RuntimeError(
                "trusted primary frontend dependencies resolve outside the project repo"
            ) from exc
        if not source.is_dir():
            raise RuntimeError("trusted primary frontend/node_modules is not a directory")

        if target.is_symlink():
            raise RuntimeError("benchmark worktree has an unexpected node_modules symlink")
        if not target.is_dir():
            raise RuntimeError(
                "benchmark worktree frontend dependencies were not prepared by WorktreeManager"
            )

        trusted_entries: dict[str, Path] = {}
        for entry in source.iterdir():
            resolved_entry = entry.resolve()
            try:
                resolved_entry.relative_to(primary_root)
            except ValueError as exc:
                raise RuntimeError(
                    "trusted frontend dependency entry resolves outside the project repo"
                ) from exc
            trusted_entries[entry.name] = resolved_entry

        actual_entries = {entry.name: entry for entry in target.iterdir()}
        if actual_entries.keys() != trusted_entries.keys():
            raise RuntimeError(
                "benchmark worktree frontend dependencies do not match the trusted source"
            )
        for name, entry in actual_entries.items():
            if not entry.is_symlink() or entry.resolve() != trusted_entries[name]:
                raise RuntimeError(
                    "benchmark worktree frontend dependency entry is not a trusted symlink"
                )

    async def _run_pinned_commands(
        self,
        fixture: GoldenIssue,
        worktree_path: str,
    ) -> list[CommandResult]:
        root = Path(worktree_path).resolve()
        if not root.is_dir():
            raise RuntimeError(f"benchmark issue worktree does not exist: {root}")

        results: list[CommandResult] = []
        for command in fixture.pinned_qa_commands:
            results.append(await self._run_pinned_command(root, command))
        return results

    async def _run_pinned_command(
        self,
        worktree_root: Path,
        command: PinnedCommand,
    ) -> CommandResult:
        argv = list(command.argv)
        if argv[0] == "{python}":
            argv[0] = sys.executable
        display = shlex.join(argv)
        command_cwd = (worktree_root / command.cwd).resolve()
        try:
            command_cwd.relative_to(worktree_root)
        except ValueError:
            return CommandResult(
                command=display,
                argv=argv,
                cwd=command.cwd,
                exit_code=126,
                expected_exit_code=command.expected_exit_code,
                duration_s=0.0,
                stderr_tail="refused command cwd outside the issue worktree",
            )
        if not command_cwd.is_dir():
            return CommandResult(
                command=display,
                argv=argv,
                cwd=command.cwd,
                exit_code=126,
                expected_exit_code=command.expected_exit_code,
                duration_s=0.0,
                stderr_tail=f"command cwd does not exist: {command_cwd}",
            )

        started = time.monotonic()
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                cwd=str(command_cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**build_project_child_env(), "CI": "1"},
                start_new_session=True,
            )
        except OSError as exc:
            return CommandResult(
                command=display,
                argv=argv,
                cwd=command.cwd,
                exit_code=127,
                expected_exit_code=command.expected_exit_code,
                duration_s=time.monotonic() - started,
                stderr_tail=f"{type(exc).__name__}: {exc}",
            )

        timed_out = False
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=command.timeout_s,
            )
        except TimeoutError:
            timed_out = True
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = await process.communicate()
            stderr += f"\nbenchmark command timed out after {command.timeout_s}s".encode()

        exit_code = 124 if timed_out else process.returncode
        if exit_code is None:
            raise RuntimeError(f"benchmark command did not produce an exit code: {display}")
        return CommandResult(
            command=display,
            argv=argv,
            cwd=command.cwd,
            exit_code=exit_code,
            expected_exit_code=command.expected_exit_code,
            duration_s=time.monotonic() - started,
            stdout_tail=_decode_output_tail(stdout),
            stderr_tail=_decode_output_tail(stderr),
            timed_out=timed_out,
        )

    async def _collect_cost(
        self, codex_store: BenchmarkRuntimeStore, issue_id: str
    ) -> tuple[float, int, int]:
        """Sum cost/tokens across completed ExecutionProcess rows for
        this issue. Returns (spent_usd, input_tokens, output_tokens)."""
        from app.application.budget_service import COMPLETED_PROCESS_STATES

        tasks = await codex_store.list_codex_tasks(issue_id=issue_id)
        spent = 0.0
        in_tok = 0
        out_tok = 0
        for t in tasks:
            task_id = t.get("id")
            if not isinstance(task_id, str) or not task_id:
                continue
            procs = await codex_store.list_execution_processes(task_id=task_id)
            for p in procs:
                if p.status not in COMPLETED_PROCESS_STATES:
                    continue
                if p.total_cost_usd:
                    spent += float(p.total_cost_usd)
                if p.input_tokens:
                    in_tok += int(p.input_tokens)
                if p.output_tokens:
                    out_tok += int(p.output_tokens)
        return spent, in_tok, out_tok


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


@dataclass
class RunOptions:
    """Caller-supplied knobs for a run."""

    run_id: str | None = None
    label: str | None = None
    epochs: int = 3
    fixture_ids: list[str] | None = None
    is_baseline: bool = False
    is_synthetic: bool = False
    notes: str | None = None
    catalog_snapshot: str | None = None
    orchestrator_version: str | None = None
    # If set, the run aborts when the budget would be exceeded
    # mid-run (in USD). The runner checks the running total at
    # the end of every epoch.
    max_budget_usd: float | None = None


class BenchmarkRunner:
    """Stateless orchestrator. Construct one per CLI invocation;
    reuse the same store across multiple ``run(...)`` calls."""

    def __init__(
        self,
        store: BenchmarkStore,
        executor: IssueExecutor,
        *,
        registry: ScorerRegistry | None = None,
    ) -> None:
        self._store = store
        self._executor = executor
        self._registry = registry or default_registry()

    async def run(self, options: RunOptions) -> BenchmarkRun:
        if options.is_baseline and options.is_synthetic:
            raise ValueError("synthetic benchmark runs cannot be baselines")

        # 1. Load + filter the golden set.
        fixtures = load_all(ids=options.fixture_ids) if options.fixture_ids else load_all()
        if not fixtures:
            raise ValueError("no golden fixtures selected")

        # 2. Create the run row up front so epoch rows can FK to it.
        run_id = options.run_id or f"run-{uuid.uuid4().hex[:8]}"
        run_row = make_run_row(
            run_id=run_id,
            label=options.label,
            fixture_ids=[f.id for f in fixtures],
            epoch_count=options.epochs,
            # Pin only after every epoch completed. Marking the initial row as
            # baseline would evict the current baseline before this run proved usable.
            is_baseline=False,
            is_synthetic=options.is_synthetic,
            status="running",
            notes=options.notes,
            catalog_snapshot=options.catalog_snapshot,
            orchestrator_version=options.orchestrator_version,
        )
        self._store.create_run(run_row)

        # 3. Loop: for each fixture, N epochs.
        epoch_count = 0
        spent_total = 0.0
        in_tok_total = 0
        out_tok_total = 0
        duration_total = 0.0
        epoch_records: list[BenchmarkEpoch] = []

        try:
            for fixture in fixtures:
                for epoch_index in range(options.epochs):
                    result = await self._executor.execute(fixture, epoch_index)
                    epoch_count += 1
                    spent_total += result.spent_usd
                    in_tok_total += result.input_tokens
                    out_tok_total += result.output_tokens
                    duration_total += result.duration_s

                    score_results = self._registry.score(result.artifacts)
                    epoch_row = self._build_epoch_row(
                        run_id=run_id,
                        fixture=fixture,
                        epoch_index=epoch_index,
                        result=result,
                        score_results=score_results,
                    )
                    self._store.add_epoch(epoch_row)
                    epoch_records.append(epoch_row)

                    # Optional mid-run budget cap.
                    if options.max_budget_usd is not None and spent_total > options.max_budget_usd:
                        raise RuntimeError(
                            f"run aborted: spent ${spent_total:.4f} "
                            f"exceeds max_budget_usd ${options.max_budget_usd:.4f}"
                        )
        except Exception as exc:
            run_row.status = "failed"
            run_row.notes = (run_row.notes or "") + f"\n[runner error] {exc}"
            self._store.update_run(run_row)
            raise

        # 4. Finalize: aggregate from the epoch records and write back.
        agg = self._aggregate_from_epochs(
            epoch_records,
            cost_total_usd=spent_total,
            total_input_tokens=in_tok_total,
            total_output_tokens=out_tok_total,
            total_duration_s=duration_total,
        )
        run_row.status = "completed"
        run_row.aggregate_pass_at_1 = agg.aggregate_pass_at_1
        run_row.aggregate_pass_at_1_stderr = agg.aggregate_pass_at_1_stderr
        run_row.cost_total_usd = spent_total
        run_row.cost_per_issue_usd = agg.cost_per_issue_usd
        run_row.total_input_tokens = in_tok_total
        run_row.total_output_tokens = out_tok_total
        run_row.total_duration_s = duration_total
        self._store.update_run(run_row)

        if options.is_baseline:
            self._store.set_baseline(run_row.id)
            run_row.is_baseline = True

        return run_row

    # --- internals -------------------------------------------------------

    def _build_epoch_row(
        self,
        *,
        run_id: str,
        fixture: GoldenIssue,
        epoch_index: int,
        result: ExecutorResult,
        score_results: dict[str, Score],
    ) -> BenchmarkEpoch:
        has_executor_error = result.error is not None
        effective_values = {
            name: 0.0 if has_executor_error and name == "execution" else score.value
            for name, score in score_results.items()
        }
        agg_score = sum(
            effective_values[name] * self._registry.get(name).weight for name in score_results
        ) / max(1, sum(self._registry.get(n).weight for n in score_results))
        execution_score = score_results.get("execution")
        return BenchmarkEpoch(
            id=f"ep-{run_id}-{fixture.id}-{epoch_index}",
            run_id=run_id,
            fixture_id=fixture.id,
            epoch_index=epoch_index,
            issue_id=result.issue_id,
            started_at=datetime.now().isoformat(timespec="seconds"),
            completed_at=datetime.now().isoformat(timespec="seconds"),
            pass_execution=(
                execution_score.passed
                if execution_score is not None and not has_executor_error
                else False
            ),
            pass_coverage=score_results["coverage"].passed
            if "coverage" in score_results
            else False,
            score_execution=(
                execution_score.value
                if execution_score is not None and not has_executor_error
                else 0.0
            ),
            score_coverage=score_results["coverage"].value if "coverage" in score_results else 0.0,
            score_aggregate=agg_score,
            spent_usd=result.spent_usd,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            duration_s=result.duration_s,
            error=result.error,
            artifacts_json=json.dumps(
                {
                    "issue_id": result.artifacts.issue_id,
                    "criteria": result.artifacts.prd_acceptance_criteria,
                    "precondition": [
                        {
                            "command": r.command,
                            "argv": r.argv,
                            "cwd": r.cwd,
                            "exit_code": r.exit_code,
                            "expected_exit_code": r.expected_exit_code,
                            "duration_s": r.duration_s,
                            "timed_out": r.timed_out,
                            "stdout_tail": r.stdout_tail,
                            "stderr_tail": r.stderr_tail,
                        }
                        for r in result.artifacts.precondition_results
                    ],
                    "qa": [
                        {
                            "command": r.command,
                            "argv": r.argv,
                            "cwd": r.cwd,
                            "exit_code": r.exit_code,
                            "expected_exit_code": r.expected_exit_code,
                            "duration_s": r.duration_s,
                            "timed_out": r.timed_out,
                            "stdout_tail": r.stdout_tail,
                            "stderr_tail": r.stderr_tail,
                        }
                        for r in result.artifacts.qa_results
                    ],
                    "tasks": result.artifacts.completed_engineer_tasks,
                }
            ),
        )

    def _aggregate_from_epochs(
        self,
        epochs: list[BenchmarkEpoch],
        *,
        cost_total_usd: float,
        total_input_tokens: int,
        total_output_tokens: int,
        total_duration_s: float,
    ) -> RunAggregate:
        per = per_fixture(
            ((e.fixture_id, e.pass_execution) for e in epochs),
        )
        # Per-fixture cost = mean across the fixture's epochs.
        from collections import defaultdict

        sums: dict[str, float] = defaultdict(float)
        counts: dict[str, int] = defaultdict(int)
        for e in epochs:
            sums[e.fixture_id] += e.spent_usd
            counts[e.fixture_id] += 1
        cost_per_fixture = {fid: sums[fid] / counts[fid] for fid in sums}
        return aggregate_stats(
            per,
            cost_per_fixture=cost_per_fixture,
            cost_total_usd=cost_total_usd,
            total_input_tokens=total_input_tokens,
            total_output_tokens=total_output_tokens,
            total_duration_s=total_duration_s,
        )


# ---------------------------------------------------------------------------
# Convenience: build a run from a finished store (for the API/diff layer)
# ---------------------------------------------------------------------------


def run_aggregate_from_store(store: BenchmarkStore, run_id: str) -> RunAggregate:
    """Reconstruct a ``RunAggregate`` from a stored run + its epochs.

    Used by PR3 (diff endpoint) and PR4 (leaderboard).
    """
    run = store.get_run(run_id)
    if run is None:
        raise ValueError(f"run {run_id!r} not found")
    epochs = store.list_epochs(run_id)
    per = per_fixture(((e.fixture_id, e.pass_execution) for e in epochs))  # noqa: UP034
    from collections import defaultdict

    sums: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    for e in epochs:
        sums[e.fixture_id] += e.spent_usd
        counts[e.fixture_id] += 1
    cost_per_fixture = {fid: sums[fid] / counts[fid] for fid in sums}
    return aggregate_stats(
        per,
        cost_per_fixture=cost_per_fixture,
        cost_total_usd=run.cost_total_usd or 0.0,
        total_input_tokens=run.total_input_tokens or 0,
        total_output_tokens=run.total_output_tokens or 0,
        total_duration_s=run.total_duration_s or 0.0,
    )
