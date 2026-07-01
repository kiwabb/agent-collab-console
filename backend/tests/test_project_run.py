"""Integration tests for the project dev-server runner endpoints."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(shutil.which("git") is None, reason="git binary not available"),
]

# A harmless long-running command that emits predictable "tick-N" lines.
_TICK_CMD = "sh -c 'i=0; while [ $i -lt 100 ]; do echo tick-$i; i=$((i+1)); sleep 0.1; done'"


def _make_git_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@e"], cwd=path, check=True, capture_output=True
    )
    subprocess.run(["git", "config", "user.name", "T"], cwd=path, check=True, capture_output=True)
    (path / "README.md").write_text("hello")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True)
    return path


def _create_project(client, tmp_path: Path, name: str = "demo", run_command: str | None = None):
    repo = _make_git_repo(tmp_path / name)
    resp = client.post(
        "/api/projects",
        json={"name": name, "source": "local", "repo_path": str(repo)},
    )
    assert resp.status_code == 201, resp.text
    project = resp.json()
    if run_command is not None:
        patch = client.patch(f"/api/projects/{project['id']}", json={"run_command": run_command})
        assert patch.status_code == 200, patch.text
        assert patch.json()["run_command"] == run_command
    return project


def test_run_command_persisted_via_patch(client, tmp_path):
    project = _create_project(client, tmp_path, name="persist", run_command="echo hi")
    fetched = client.get(f"/api/projects/{project['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["run_command"] == "echo hi"


def test_run_command_round_trips_in_list(client, tmp_path):
    project = _create_project(client, tmp_path, name="listed-runcmd", run_command="echo hi")
    listing = client.get("/api/projects")
    assert listing.status_code == 200
    match = next(p for p in listing.json() if p["id"] == project["id"])
    assert match["run_command"] == "echo hi"


def test_start_status_logs_then_stop_via_manager(tmp_path):
    """Process lifecycle + log streaming exercised directly on one event loop.

    The streaming readers are background asyncio tasks; TestClient spins a fresh
    loop per request so they cannot drain across requests. Driving the manager
    inside a single `asyncio.run` loop faithfully covers the real-process path
    (start -> running status -> ordered streamed logs -> incremental tail ->
    idempotent stop) without that test harness artifact.
    """
    import asyncio

    from app.application.project_run_manager import ProjectRunManager

    async def scenario():
        repo = _make_git_repo(tmp_path / "mgr")
        mgr = ProjectRunManager()
        pid = "proj-1"
        status = await mgr.start(pid, _TICK_CMD, str(repo))
        assert status["running"] is True
        assert isinstance(status["pid"], int) and status["pid"] > 0
        assert status["command"] == _TICK_CMD
        assert status["started_at"]
        assert mgr.status(pid)["running"] is True

        # Wait for the readers to capture some "tick" output.
        logs = {"lines": []}
        for _ in range(60):
            logs = mgr.get_logs(pid)
            if any("tick" in ln["line"] for ln in logs["lines"]):
                break
            await asyncio.sleep(0.1)
        tick_lines = [ln for ln in logs["lines"] if "tick" in ln["line"]]
        assert tick_lines, f"expected tick lines, got {logs}"
        seqs = [ln["seq"] for ln in logs["lines"]]
        assert seqs == sorted(seqs)
        assert all(ln["stream"] in ("stdout", "stderr") for ln in logs["lines"])
        assert logs["running"] is True

        # Incremental tail: after=last_seq yields only newer lines.
        last_seq = logs["last_seq"]
        await asyncio.sleep(0.3)
        inc = mgr.get_logs(pid, after=last_seq)
        assert all(ln["seq"] > last_seq for ln in inc["lines"])
        assert inc["lines"], "expected new lines after waiting"

        stopped = await mgr.stop(pid)
        assert stopped["running"] is False
        # Idempotent: a second stop does not error.
        again = await mgr.stop(pid)
        assert again["running"] is False
        # Logs remain retrievable after stop.
        post = mgr.get_logs(pid)
        assert post["running"] is False
        assert any("tick" in ln["line"] for ln in post["lines"])

    asyncio.run(scenario())


def test_stop_is_idempotent(client, tmp_path):
    project = _create_project(client, tmp_path, name="idempotent", run_command=_TICK_CMD)
    pid = project["id"]
    assert client.post(f"/api/projects/{pid}/run/start").status_code == 200
    first = client.post(f"/api/projects/{pid}/run/stop")
    assert first.status_code == 200
    assert first.json()["running"] is False
    second = client.post(f"/api/projects/{pid}/run/stop")
    assert second.status_code == 200
    assert second.json()["running"] is False


def test_stop_unknown_project_returns_not_running(client, tmp_path):
    project = _create_project(client, tmp_path, name="never-started", run_command=_TICK_CMD)
    resp = client.post(f"/api/projects/{project['id']}/run/stop")
    assert resp.status_code == 200
    assert resp.json()["running"] is False


def test_start_without_run_command_is_409(client, tmp_path):
    project = _create_project(client, tmp_path, name="noruncmd")
    resp = client.post(f"/api/projects/{project['id']}/run/start")
    assert resp.status_code == 409
    assert resp.json()["detail"]["reason"] == "no_run_command"


def test_start_refused_command_is_409(client, tmp_path):
    project = _create_project(client, tmp_path, name="refused", run_command="rm -rf /tmp/x")
    resp = client.post(f"/api/projects/{project['id']}/run/start")
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["reason"] == "refused"
    assert detail.get("pattern")


def test_start_while_running_is_409(client, tmp_path):
    project = _create_project(client, tmp_path, name="already", run_command=_TICK_CMD)
    pid = project["id"]
    try:
        assert client.post(f"/api/projects/{pid}/run/start").status_code == 200
        again = client.post(f"/api/projects/{pid}/run/start")
        assert again.status_code == 409
        assert again.json()["detail"]["reason"] == "already_running"
    finally:
        client.post(f"/api/projects/{pid}/run/stop")
