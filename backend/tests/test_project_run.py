"""Integration tests for the project dev-server runner endpoints."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(shutil.which("git") is None, reason="git binary not available"),
]

# A harmless repo-owned Python command that emits predictable "tick-N" lines.
_TICK_CMD = "python3 -u tick_server.py"


def _make_git_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@e"], cwd=path, check=True, capture_output=True
    )
    subprocess.run(["git", "config", "user.name", "T"], cwd=path, check=True, capture_output=True)
    (path / "README.md").write_text("hello")
    (path / "tick_server.py").write_text(
        "import time\nfor i in range(100):\n    print(f'tick-{i}', flush=True)\n    time.sleep(0.1)\n",
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "add", "README.md", "tick_server.py"],
        cwd=path,
        check=True,
        capture_output=True,
    )
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
    from app.application.project_run_manager import ProjectRunManager, RunLogs

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
        logs: RunLogs = {"lines": [], "last_seq": 0, "running": True, "exit_code": None}
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


def test_manager_isolates_processes_and_logs_by_service(tmp_path):
    from app.application.project_run_manager import ProjectRunManager

    async def scenario():
        repo = _make_git_repo(tmp_path / "multi-service-mgr")
        mgr = ProjectRunManager()
        project_id = "project-1"
        await mgr.start(
            project_id,
            _TICK_CMD,
            str(repo),
            service_id="backend",
        )
        await mgr.start(
            project_id,
            _TICK_CMD,
            str(repo),
            service_id="frontend",
        )
        try:
            assert mgr.status(project_id, service_id="backend")["running"] is True
            assert mgr.status(project_id, service_id="frontend")["running"] is True
            await mgr.stop(project_id, service_id="backend")
            assert mgr.status(project_id, service_id="backend")["running"] is False
            assert mgr.status(project_id, service_id="frontend")["running"] is True
        finally:
            await mgr.stop(project_id, service_id="frontend")

    asyncio.run(scenario())


@pytest.mark.parametrize("exit_code", [0, 7])
def test_project_run_redacts_success_and_failure_output(tmp_path, exit_code):
    from app.application.env_materializer import build_env_file_content
    from app.application.project_run_manager import ProjectRunManager, RunLogs

    plaintext = "abc"
    ciphertext = "gAAAAA" + "A" * 80 + "=="
    repo = tmp_path / f"redacted-{exit_code}"
    repo.mkdir()
    (repo / ".env").write_text(
        build_env_file_content(
            [
                {
                    "name": "DISPLAY_VALUE",
                    "value": plaintext,
                    "secret": True,
                }
            ]
        ),
        encoding="utf-8",
    )
    (repo / "emit_output.py").write_text(
        "import sys\n"
        f"print({f'stdout={plaintext} cipher={ciphertext}'!r}, flush=True)\n"
        f"print({f'stderr={plaintext} cipher={ciphertext}'!r}, file=sys.stderr, flush=True)\n"
        f"raise SystemExit({exit_code})\n",
        encoding="utf-8",
    )

    async def scenario() -> RunLogs:
        manager = ProjectRunManager()
        await manager.start("project-redacted", "python3 -u emit_output.py", str(repo))
        logs: RunLogs = {
            "lines": [],
            "last_seq": 0,
            "running": True,
            "exit_code": None,
        }
        for _ in range(50):
            logs = manager.get_logs("project-redacted")
            if len(logs["lines"]) >= 2 and logs["exit_code"] is not None:
                break
            await asyncio.sleep(0.02)
        return logs

    logs = asyncio.run(scenario())
    persisted = "\n".join(line["line"] for line in logs["lines"])
    assert logs["exit_code"] == exit_code
    assert plaintext not in persisted
    assert ciphertext not in persisted
    assert persisted.count("[REDACTED]") >= 2


def test_project_run_refuses_when_output_redaction_is_unavailable(tmp_path, monkeypatch):
    import app.application.project_run_manager as run_manager_module
    from app.application.project_run_manager import ProjectRunError, ProjectRunManager
    from app.application.qa_output_redaction import SecretOutputRedactionError

    script = tmp_path / "server.py"
    script.write_text("print('not started')\n", encoding="utf-8")

    def unavailable(cls, workspace_path, child_env):
        raise SecretOutputRedactionError("unreadable")

    async def unexpected_spawn(*args, **kwargs):
        raise AssertionError("redaction failure must refuse before process spawn")

    monkeypatch.setattr(
        run_manager_module.SecretOutputRedactor,
        "from_workspace",
        classmethod(unavailable),
    )
    monkeypatch.setattr(
        run_manager_module.asyncio,
        "create_subprocess_exec",
        unexpected_spawn,
    )

    async def scenario() -> None:
        manager = ProjectRunManager()
        with pytest.raises(ProjectRunError) as raised:
            await manager.start("project-redaction-failed", "python3 server.py", str(tmp_path))
        assert raised.value.reason == "refused"
        assert raised.value.pattern == "redaction_unavailable"

    asyncio.run(scenario())


def test_output_redactor_covers_short_secret_from_legacy_managed_env(tmp_path):
    from app.application.env_materializer import MANAGED_ENV_MARKER
    from app.application.qa_output_redaction import SecretOutputRedactor

    plaintext = "abc"
    (tmp_path / ".env").write_text(
        f"{MANAGED_ENV_MARKER}\nDISPLAY_VALUE={plaintext}\n",
        encoding="utf-8",
    )

    redactor = SecretOutputRedactor.from_workspace(str(tmp_path), {"PATH": "/usr/bin"})

    assert redactor.redact(f"value={plaintext}") == "value=[REDACTED]"


def test_secret_delete_and_next_start_remove_managed_plaintext(
    client, tmp_path, monkeypatch
):
    import app.interfaces.api as api_module
    from app.application.env_crypto import generate_key
    from app.application.env_materializer import build_env_file_content

    monkeypatch.setenv("CONSOLE_ENCRYPTION_KEY", generate_key())
    plaintext = "only-secret-value"
    project = _create_project(
        client,
        tmp_path,
        name="secret-lifecycle",
        run_command=_TICK_CMD,
    )
    repo = Path(project["repo_path"])
    env_path = repo / ".env"

    saved = client.put(
        f"/api/projects/{project['id']}/env",
        json={
            "name": "DISPLAY_VALUE",
            "value": plaintext,
            "secret": True,
            "source": "user",
        },
    )
    assert saved.status_code == 200, saved.text
    assert plaintext in env_path.read_text(encoding="utf-8")
    listed = client.get(f"/api/projects/{project['id']}/env")
    assert listed.status_code == 200
    assert plaintext not in listed.text

    deleted = client.delete(f"/api/projects/{project['id']}/env/DISPLAY_VALUE")
    assert deleted.status_code == 200, deleted.text
    assert env_path.exists() is False

    # Simulate a legacy stale managed file from a pre-fix deletion. Start must
    # reconcile the empty store before handing control to the process manager.
    env_path.write_text(
        build_env_file_content(
            [
                {
                    "name": "DISPLAY_VALUE",
                    "value": plaintext,
                    "secret": True,
                }
            ]
        ),
        encoding="utf-8",
    )
    start_called = False

    async def checked_start(project_id, command, cwd):
        nonlocal start_called
        start_called = True
        assert project_id == project["id"]
        assert env_path.exists() is False
        return {
            "running": False,
            "command": command,
            "pid": None,
            "started_at": None,
            "exit_code": 0,
        }

    monkeypatch.setattr(api_module.project_run_manager, "start", checked_start)

    started = client.post(f"/api/projects/{project['id']}/run/start")
    assert started.status_code == 200, started.text
    assert start_called is True
    assert env_path.exists() is False
    assert plaintext not in "\n".join(path.read_text() for path in repo.iterdir() if path.is_file())


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
    assert detail["pattern"] == "executable_not_allowed"
    assert client.get(f"/api/projects/{project['id']}/run/status").json()["running"] is False
    audit = client.get(f"/api/projects/{project['id']}/audit").json()
    assert any(row["event"] == "run_refused:executable_not_allowed" for row in audit)


@pytest.mark.parametrize(
    ("command", "reason"),
    [
        ("npm explore foo -- sh -c id", "package_command_not_allowed"),
        ("yarn node -e 'process.exit(0)'", "package_command_not_allowed"),
        ("bun --eval='console.log(1)'", "interpreter_inline_code_not_allowed"),
        ("npx vite", "package_download_not_allowed"),
        ("cargo install ripgrep", "cargo_command_not_allowed"),
        ("go run example.com/evil@latest", "go_remote_module_not_allowed"),
        (
            "mvn org.codehaus.mojo:exec-maven-plugin:3.5.0:exec -Dexec.executable=sh",
            "maven_exec_not_allowed",
        ),
        ("gradle -I/tmp/evil.gradle bootRun", "gradle_init_script_not_allowed"),
        ("make '--eval=include /tmp/evil.mk' test", "make_injection_not_allowed"),
    ],
)
def test_command_bypass_refusal_is_audited_without_spawning(
    client,
    tmp_path,
    monkeypatch,
    command,
    reason,
):
    import app.application.project_run_manager as run_manager_module

    project = _create_project(
        client,
        tmp_path,
        name=f"refused-{reason}-{abs(hash(command))}",
        run_command=command,
    )

    async def unexpected_spawn(*_args, **_kwargs):
        pytest.fail("refused project command reached process spawn")

    monkeypatch.setattr(
        run_manager_module.asyncio,
        "create_subprocess_exec",
        unexpected_spawn,
    )

    response = client.post(f"/api/projects/{project['id']}/run/start")

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == {"reason": "refused", "pattern": reason}
    audit = client.get(f"/api/projects/{project['id']}/audit").json()
    assert any(row["event"] == f"run_refused:{reason}" for row in audit)


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
