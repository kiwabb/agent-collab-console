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

from __future__ import annotations  # noqa: I001

import json
import sys
from types import SimpleNamespace
from typing import Iterable  # noqa: F401, UP035

import pytest

from benchmark.runner import (
    BenchmarkRunner,
    ExecutorResult,  # noqa: F401
    FakeExecutor,
    RealConductorExecutor,
    RunOptions,
    _is_benchmark_runtime_store,
)
from benchmark.golden_schema import GoldenIssue, PinnedCommand
from benchmark.scorers_impl import ExecutionScorer
from benchmark.store import (
    BenchmarkEpoch,  # noqa: F401
    BenchmarkRun,  # noqa: F401
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
        qa_results=[
            CommandResult(
                command="python3 -c 'print(1)'",
                argv=["python3", "-c", "print(1)"],
                cwd="backend",
                exit_code=0,
                expected_exit_code=0,
                duration_s=0.1,
                stdout_tail="1\n",
            )
        ],
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
        f.id: [_fail_artifacts(f.id), _ok_artifacts(f.id), _ok_artifacts(f.id)] for f in fixtures
    }


class _AsyncRuntimeStore:
    def __init__(self):
        self.graph = None

    async def load_codex_workspace(self, workspace_id: str):
        return None

    async def load_project(self, project_id: str):
        return None

    async def load_workflow_graph_for_issue(self, issue_id: str):
        return self.graph

    async def save_workflow_graph(self, graph, nodes=None, edges=None):
        self.graph = graph

    async def list_codex_tasks(
        self,
        session_id: str | None = None,
        issue_id: str | None = None,
        project_id: str | None = None,
    ) -> list[dict[str, object]]:
        return []

    async def list_execution_processes(
        self, session_id: str | None = None, task_id: str | None = None
    ) -> list[object]:
        return []


class _SyncRuntimeStore:
    def __init__(self):
        self.graph = None

    def load_codex_workspace(self, workspace_id: str):
        return None

    def load_project(self, project_id: str):
        return None

    def load_workflow_graph_for_issue(self, issue_id: str):
        return self.graph

    def save_workflow_graph(self, graph, nodes=None, edges=None):
        self.graph = graph

    def list_codex_tasks(
        self,
        session_id: str | None = None,
        issue_id: str | None = None,
        project_id: str | None = None,
    ) -> list[dict[str, object]]:
        return []

    def list_execution_processes(
        self, session_id: str | None = None, task_id: str | None = None
    ) -> list[object]:
        return []


def test_benchmark_runtime_store_guard_accepts_async_store() -> None:
    assert _is_benchmark_runtime_store(_AsyncRuntimeStore()) is True


def test_benchmark_runtime_store_guard_rejects_sync_or_missing_store() -> None:
    assert _is_benchmark_runtime_store(_SyncRuntimeStore()) is False
    assert _is_benchmark_runtime_store(None) is False


def _fixture_with_commands(commands: list[PinnedCommand]) -> GoldenIssue:
    return GoldenIssue(
        id="structured.commands",
        title="Run structured benchmark commands",
        description="Execute every pinned command inside the isolated issue worktree.",
        acceptance_criteria=["Every structured command result is captured"],
        pinned_qa_commands=commands,
    )


@pytest.mark.asyncio
async def test_real_executor_runs_pinned_argv_in_issue_worktree(tmp_path):
    worktree = tmp_path / "issue-worktree"
    command_cwd = worktree / "nested"
    command_cwd.mkdir(parents=True)
    fixture = _fixture_with_commands(
        [
            PinnedCommand(
                argv=[
                    "{python}",
                    "-c",
                    "from pathlib import Path; print(Path.cwd().name); print('first', file=__import__('sys').stderr)",
                ],
                cwd="nested",
            ),
            PinnedCommand(
                argv=["{python}", "-c", "raise SystemExit(7)"],
                cwd=".",
                expected_exit_code=7,
            ),
        ]
    )
    executor = RealConductorExecutor(project_id="project-1", workspace_id="workspace-1")

    results = await executor._run_pinned_commands(fixture, str(worktree))

    assert [result.exit_code for result in results] == [0, 7]
    assert results[0].cwd == "nested"
    assert results[0].argv == [sys.executable, "-c", fixture.pinned_qa_commands[0].argv[2]]
    assert results[0].stdout_tail == "nested\n"
    assert results[0].stderr_tail == "first\n"
    assert results[1].expected_exit_code == 7
    score = ExecutionScorer().score(IssueArtifacts(issue_id="issue-1", qa_results=results))
    assert score.passed is True
    assert score.value == 1.0


@pytest.mark.asyncio
async def test_real_executor_refuses_symlink_cwd_that_escapes_worktree(tmp_path):
    worktree = tmp_path / "issue-worktree"
    outside = tmp_path / "outside"
    worktree.mkdir()
    outside.mkdir()
    (worktree / "escape").symlink_to(outside, target_is_directory=True)
    fixture = _fixture_with_commands(
        [PinnedCommand(argv=["{python}", "-c", "print('must not run')"], cwd="escape")]
    )
    executor = RealConductorExecutor(project_id="project-1", workspace_id="workspace-1")

    results = await executor._run_pinned_commands(fixture, str(worktree))

    assert len(results) == 1
    assert results[0].exit_code == 126
    assert "outside the issue worktree" in results[0].stderr_tail


@pytest.mark.asyncio
async def test_real_executor_confirms_fixture_criteria_and_checks_after_conductor_error(
    tmp_path,
    monkeypatch,
):
    import app.application.conductor_main_loop as conductor_module
    import app.bootstrap as bootstrap_module
    import app.interfaces.api as api_module

    worktree = tmp_path / "issue-worktree"
    worktree.mkdir()

    class Store(_AsyncRuntimeStore):
        async def load_codex_workspace(self, workspace_id: str):
            return SimpleNamespace(id=workspace_id, project_id="project-1")

        async def load_project(self, project_id: str):
            return SimpleNamespace(id=project_id, repo_path=str(tmp_path / "primary"))

    captured = {}

    async def create_issue(request):
        captured["request"] = request
        return SimpleNamespace(
            id="benchmark-issue",
            project_id="project-1",
            git_worktree_path=str(worktree),
        )

    async def fail_conductor(*_args, **kwargs):
        captured["dispatcher"] = kwargs.get("task_dispatcher_fn")
        (worktree / "implemented").write_text("done")
        raise RuntimeError("conductor stopped after editing")

    monkeypatch.setattr(bootstrap_module, "codex_store", Store())
    monkeypatch.setattr(api_module, "create_codex_issue", create_issue)
    monkeypatch.setattr(conductor_module, "run_issue_conductor_loop", fail_conductor)
    fixture = _fixture_with_commands(
        [
            PinnedCommand(
                argv=[
                    "{python}",
                    "-c",
                    "from pathlib import Path; print('checked'); raise SystemExit(0 if Path('implemented').exists() else 1)",
                ]
            )
        ]
    )

    result = await RealConductorExecutor(
        project_id="project-1",
        workspace_id="workspace-1",
    ).execute(fixture, 0)

    request = captured["request"]
    assert request.acceptance_criteria == fixture.acceptance_criteria
    assert request.acceptance_criteria_confirmed is True
    assert result.error == "RuntimeError: conductor stopped after editing"
    assert captured["dispatcher"] is not None
    assert isinstance(bootstrap_module.codex_store, Store)
    assert bootstrap_module.codex_store.graph is not None
    assert bootstrap_module.codex_store.graph.issue_id == "benchmark-issue"
    assert result.artifacts.precondition_results[0].exit_code == 1
    assert result.artifacts.qa_results[0].exit_code == 0
    assert result.artifacts.qa_results[0].stdout_tail == "checked\n"


@pytest.mark.asyncio
async def test_real_executor_treats_non_done_conductor_result_as_epoch_error(
    tmp_path,
    monkeypatch,
):
    import app.application.conductor_main_loop as conductor_module
    import app.bootstrap as bootstrap_module
    import app.interfaces.api as api_module

    worktree = tmp_path / "issue-worktree"
    worktree.mkdir()

    class Store(_AsyncRuntimeStore):
        async def load_codex_workspace(self, workspace_id: str):
            return SimpleNamespace(id=workspace_id, project_id="project-1")

        async def load_project(self, project_id: str):
            return SimpleNamespace(id=project_id, repo_path=str(tmp_path / "primary"))

    async def create_issue(_request):
        return SimpleNamespace(
            id="benchmark-issue",
            project_id="project-1",
            git_worktree_path=str(worktree),
        )

    async def blocked_conductor(*_args, **_kwargs):
        (worktree / "implemented").write_text("done")
        return SimpleNamespace(status="blocked")

    monkeypatch.setattr(bootstrap_module, "codex_store", Store())
    monkeypatch.setattr(api_module, "create_codex_issue", create_issue)
    monkeypatch.setattr(conductor_module, "run_issue_conductor_loop", blocked_conductor)
    fixture = _fixture_with_commands(
        [
            PinnedCommand(
                argv=[
                    "{python}",
                    "-c",
                    "from pathlib import Path; raise SystemExit(0 if Path('implemented').exists() else 1)",
                ]
            )
        ]
    )

    result = await RealConductorExecutor(
        project_id="project-1",
        workspace_id="workspace-1",
    ).execute(fixture, 0)

    assert result.error == "conductor finished with status 'blocked'"
    assert result.artifacts.precondition_results[0].exit_code == 1
    assert result.artifacts.qa_results[0].exit_code == 0


@pytest.mark.asyncio
async def test_real_executor_refuses_fixture_that_passes_before_conductor(
    tmp_path,
    monkeypatch,
):
    import app.application.conductor_main_loop as conductor_module
    import app.bootstrap as bootstrap_module
    import app.interfaces.api as api_module

    worktree = tmp_path / "issue-worktree"
    worktree.mkdir()

    class Store(_AsyncRuntimeStore):
        async def load_codex_workspace(self, workspace_id: str):
            return SimpleNamespace(id=workspace_id, project_id="project-1")

        async def load_project(self, project_id: str):
            return SimpleNamespace(id=project_id, repo_path=str(tmp_path / "primary"))

    async def create_issue(_request):
        return SimpleNamespace(
            id="benchmark-issue",
            project_id="project-1",
            git_worktree_path=str(worktree),
        )

    conductor_called = False

    async def conductor(*_args, **_kwargs):
        nonlocal conductor_called
        conductor_called = True
        return SimpleNamespace(status="done")

    monkeypatch.setattr(bootstrap_module, "codex_store", Store())
    monkeypatch.setattr(api_module, "create_codex_issue", create_issue)
    monkeypatch.setattr(conductor_module, "run_issue_conductor_loop", conductor)
    fixture = _fixture_with_commands([PinnedCommand(argv=["{python}", "-c", "print('done')"])])

    result = await RealConductorExecutor(
        project_id="project-1",
        workspace_id="workspace-1",
    ).execute(fixture, 0)

    assert conductor_called is False
    assert result.error is not None
    assert "already passes before the Conductor runs" in result.error
    assert result.artifacts.precondition_results[0].exit_code == 0
    assert result.artifacts.qa_results == []


def test_real_executor_accepts_only_trusted_frontend_dependency_links(tmp_path):
    primary = tmp_path / "primary"
    worktree = tmp_path / "worktree"
    dependencies = primary / "frontend" / "node_modules"
    (dependencies / "vite").mkdir(parents=True)
    (dependencies / ".bin").mkdir()
    (primary / ".env").write_text("SECRET=must-not-copy")
    linked = worktree / "frontend" / "node_modules"
    linked.mkdir(parents=True)
    for entry in dependencies.iterdir():
        (linked / entry.name).symlink_to(
            entry.resolve(),
            target_is_directory=entry.is_dir(),
        )
    fixture = _fixture_with_commands([PinnedCommand(argv=["npm", "test"], cwd="frontend")])

    RealConductorExecutor._prepare_trusted_dependencies(
        fixture=fixture,
        primary_repo_path=str(primary),
        worktree_path=str(worktree),
    )

    assert linked.is_dir()
    assert linked.is_symlink() is False
    assert {entry.name for entry in linked.iterdir()} == {".bin", "vite"}
    assert all(entry.is_symlink() for entry in linked.iterdir())
    assert not (worktree / ".env").exists()


def test_real_executor_rejects_root_node_modules_symlink(tmp_path):
    primary = tmp_path / "primary"
    worktree = tmp_path / "worktree"
    dependencies = primary / "frontend" / "node_modules"
    dependencies.mkdir(parents=True)
    target = worktree / "frontend" / "node_modules"
    target.parent.mkdir(parents=True)
    target.symlink_to(dependencies.resolve(), target_is_directory=True)
    fixture = _fixture_with_commands([PinnedCommand(argv=["npm", "test"], cwd="frontend")])

    with pytest.raises(RuntimeError, match="unexpected node_modules symlink"):
        RealConductorExecutor._prepare_trusted_dependencies(
            fixture=fixture,
            primary_repo_path=str(primary),
            worktree_path=str(worktree),
        )


@pytest.mark.asyncio
async def test_real_executor_rejects_workspace_project_mismatch_before_issue_creation(
    monkeypatch,
):
    import app.bootstrap as bootstrap_module
    import app.interfaces.api as api_module

    class Store(_AsyncRuntimeStore):
        async def load_codex_workspace(self, workspace_id: str):
            return SimpleNamespace(id=workspace_id, project_id="other-project")

    created = False

    async def create_issue(_request):
        nonlocal created
        created = True

    monkeypatch.setattr(bootstrap_module, "codex_store", Store())
    monkeypatch.setattr(api_module, "create_codex_issue", create_issue)
    fixture = _fixture_with_commands([PinnedCommand(argv=["{python}", "-c", "print(1)"])])

    result = await RealConductorExecutor(
        project_id="project-1",
        workspace_id="workspace-1",
    ).execute(fixture, 0)

    assert created is False
    assert result.error is not None
    assert "different project" in result.error
    assert result.artifacts.qa_results == []


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
    assert run.cost_total_usd is not None
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
async def test_completed_baseline_run_replaces_existing_baseline():
    store = InMemoryStore()
    executor = FakeExecutor(per_fixture_results=_all_pass_results())
    runner = BenchmarkRunner(store, executor)
    first = await runner.run(RunOptions(epochs=1, is_baseline=True))

    second = await runner.run(RunOptions(epochs=1, is_baseline=True))

    baseline = store.get_baseline()
    assert baseline is not None
    assert baseline.id == second.id
    first_stored = store.get_run(first.id)
    assert first_stored is not None
    assert first_stored.is_baseline is False


@pytest.mark.asyncio
async def test_run_rejects_synthetic_baseline_before_persisting():
    store = InMemoryStore()
    runner = BenchmarkRunner(store, FakeExecutor(per_fixture_results=_all_pass_results()))

    with pytest.raises(ValueError, match="synthetic benchmark runs cannot be baselines"):
        await runner.run(RunOptions(epochs=1, is_baseline=True, is_synthetic=True))

    assert store.list_runs() == []


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

    run = await runner.run(
        RunOptions(
            epochs=1,
            fixture_ids=[
                "add-backend-echo-endpoint",
                "add-backend-ping-endpoint",
            ],
        )
    )
    # Sum = 0.30 across 2 fixtures × 1 epoch.  # noqa: RUF003
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
    # 3 fixtures × 2 epochs = 6 calls.  # noqa: RUF003
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
        await runner.run(RunOptions(epochs=1, fixture_ids=["does-not-exist"]))


@pytest.mark.asyncio
async def test_run_artifacts_json_is_persisted():
    store = InMemoryStore()
    executor = FakeExecutor(per_fixture_results=_all_pass_results())
    runner = BenchmarkRunner(store, executor)

    await runner.run(RunOptions(epochs=1, fixture_ids=["add-backend-echo-endpoint"]))
    eps = store.list_epochs(store.list_runs()[0].id)
    assert eps[0].artifacts_json is not None
    blob = json.loads(eps[0].artifacts_json)
    assert blob["issue_id"] == "codex-add-backend-echo-endpoint"
    assert "Add the endpoint" in blob["tasks"]
    assert blob["qa"] == [
        {
            "command": "python3 -c 'print(1)'",
            "argv": ["python3", "-c", "print(1)"],
            "cwd": "backend",
            "exit_code": 0,
            "expected_exit_code": 0,
            "duration_s": 0.1,
            "timed_out": False,
            "stdout_tail": "1\n",
            "stderr_tail": "",
        }
    ]


# ---------------------------------------------------------------------------
# Error path — executor returns error result, runner persists it
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_persists_executor_error_as_failed_epoch():
    store = InMemoryStore()
    executor = FakeExecutor(
        per_fixture_results={
            "add-backend-echo-endpoint": [_ok_artifacts("add-backend-echo-endpoint")]
        },
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
    assert by_id["add-backend-ping-endpoint"].pass_execution is False
    assert by_id["add-backend-ping-endpoint"].score_execution == 0.0
    # The failed epoch is counted as a failure in the aggregate.
    assert run.aggregate_pass_at_1 is not None
    assert run.aggregate_pass_at_1 < 1.0
