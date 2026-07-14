from __future__ import annotations

"""In-memory dev-server runner for project repos.

Deliberately ephemeral: nothing is persisted. One running process per project service,
spawned in its own process group so `stop` can `killpg` the whole tree
(dev servers fork children). Logs land in a bounded ring buffer with a
monotonic sequence so the polling frontend can fetch incremental tail slices.

Out of scope (see PRD): WS streaming, cross-restart recovery, multiple
instances, auto-restart. The app shutdown hook calls `shutdown_all()` so we
never leak orphan processes.
"""
import asyncio  # noqa: E402
import collections  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import signal  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from typing import TypedDict  # noqa: E402

from app.application.project_command import (  # noqa: E402
    ProjectCommandError,
    build_project_child_env,
    parse_project_command,
)
from app.application.qa_output_redaction import (  # noqa: E402
    SecretOutputRedactionError,
    SecretOutputRedactor,
)

logger = logging.getLogger(__name__)

# Ring-buffer cap (lines) and per-line clamp (chars). Keep logs cheap; the
# frontend only tails the recent output.
_LOG_RING_MAXLEN = 2000
_LINE_MAX_CHARS = 2000
# Grace period between SIGTERM and SIGKILL when stopping a process group.
_STOP_GRACE_S = 5.0

class RunLogLine(TypedDict):
    seq: int
    stream: str
    line: str
    ts: str


class RunStatus(TypedDict):
    running: bool
    command: str | None
    pid: int | None
    started_at: str | None
    exit_code: int | None


class RunLogs(TypedDict):
    lines: list[RunLogLine]
    last_seq: int
    running: bool
    exit_code: int | None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()  # noqa: UP017


class ProjectRunError(RuntimeError):
    """Raised by `start` for a known, machine-distinguishable refusal.

    `reason` is one of: no_run_command | already_running | refused.
    For `refused`, `pattern` carries the matching safety pattern.
    """

    def __init__(self, reason: str, *, pattern: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.pattern = pattern


class _RunEntry:
    def __init__(
        self,
        command: str,
        cwd: str,
        proc: asyncio.subprocess.Process,
        redactor: SecretOutputRedactor,
    ) -> None:
        self.command = command
        self.cwd = cwd
        self.proc = proc
        self.redactor = redactor
        self.pid = proc.pid
        self.started_at = _now_iso()
        self.exit_code: int | None = None
        self.logs: collections.deque[RunLogLine] = collections.deque(maxlen=_LOG_RING_MAXLEN)
        self._seq = 0
        self.readers: list[asyncio.Task[None]] = []

    def append_log(self, stream: str, line: str) -> None:
        self._seq += 1
        safe_line = self.redactor.redact(line)
        self.logs.append(
            {
                "seq": self._seq,
                "stream": stream,
                "line": safe_line[:_LINE_MAX_CHARS],
                "ts": _now_iso(),
            }
        )

    @property
    def last_seq(self) -> int:
        return self._seq

    @property
    def running(self) -> bool:
        return self.exit_code is None and self.proc.returncode is None

    def status_dict(self) -> RunStatus:
        # Reconcile in case the process exited but the waiter hasn't fired yet.
        if self.exit_code is None and self.proc.returncode is not None:
            self.exit_code = self.proc.returncode
        running = self.exit_code is None and self.proc.returncode is None
        return {
            "running": running,
            "command": self.command,
            "pid": self.pid,
            "started_at": self.started_at,
            "exit_code": self.exit_code,
        }


class ProjectRunManager:
    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], _RunEntry] = {}
        self._lock = asyncio.Lock()

    async def start(
        self,
        project_id: str,
        command: str,
        cwd: str,
        *,
        service_id: str = "legacy",
    ) -> RunStatus:
        command = (command or "").strip()
        if not command:
            raise ProjectRunError("no_run_command")
        try:
            parsed = parse_project_command(command, cwd)
        except ProjectCommandError as exc:
            raise ProjectRunError("refused", pattern=exc.reason) from exc

        async with self._lock:
            key = (project_id, service_id)
            existing = self._entries.get(key)
            if existing is not None and existing.running:
                raise ProjectRunError("already_running")

            child_env = build_project_child_env()
            try:
                redactor = SecretOutputRedactor.from_workspace(cwd, child_env)
            except SecretOutputRedactionError as exc:
                logger.warning(
                    "project run output redaction unavailable; refusing launch: project_id=%s",
                    project_id,
                    exc_info=True,
                )
                raise ProjectRunError("refused", pattern="redaction_unavailable") from exc

            try:
                proc = await asyncio.create_subprocess_exec(
                    *parsed.argv,
                    cwd=str(parsed.cwd),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=child_env,
                    start_new_session=True,
                )
            except FileNotFoundError as exc:
                raise ProjectRunError("refused", pattern="executable_not_found") from exc
            except PermissionError as exc:
                raise ProjectRunError("refused", pattern="executable_not_executable") from exc
            except OSError as exc:
                raise ProjectRunError("refused", pattern="process_spawn_failed") from exc
            entry = _RunEntry(
                command=parsed.display,
                cwd=str(parsed.cwd),
                proc=proc,
                redactor=redactor,
            )
            entry.readers = [
                asyncio.create_task(self._drain(entry, proc.stdout, "stdout")),
                asyncio.create_task(self._drain(entry, proc.stderr, "stderr")),
            ]
            asyncio.create_task(self._wait_exit(entry))  # noqa: RUF006
            self._entries[key] = entry
            return entry.status_dict()

    async def _drain(
        self, entry: _RunEntry, stream: asyncio.StreamReader | None, tag: str
    ) -> None:
        if stream is None:
            return
        try:
            while True:
                raw = await stream.readline()
                if not raw:
                    break
                entry.append_log(tag, raw.decode("utf-8", errors="replace").rstrip("\n"))
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001, RUF100
            logger.debug("project run %s reader (%s) error", tag, entry.pid, exc_info=True)

    async def _wait_exit(self, entry: _RunEntry) -> None:
        try:
            rc = await entry.proc.wait()
            entry.exit_code = rc
        except Exception:  # noqa: BLE001, RUF100
            logger.debug("project run waiter error pid=%s", entry.pid, exc_info=True)

    async def stop(self, project_id: str, *, service_id: str = "legacy") -> RunStatus:
        async with self._lock:
            entry = self._entries.get((project_id, service_id))
            if entry is None:
                return {
                    "running": False,
                    "command": None,
                    "pid": None,
                    "started_at": None,
                    "exit_code": None,
                }
            await self._terminate(entry)
            return entry.status_dict()

    async def _terminate(self, entry: _RunEntry) -> None:
        proc = entry.proc
        pid = entry.pid
        # Signal + reap at the OS level rather than awaiting `proc.wait()`. The
        # asyncio subprocess transport binds its waiter Future to the loop that
        # created the process; under TestClient each request runs on a fresh
        # loop, so awaiting the transport across loops raises. killpg + waitpid
        # is loop-agnostic and reaps the whole process group (dev servers fork).
        if proc.returncode is None and not self._already_reaped(entry):
            self._signal_pg(pid, signal.SIGTERM)
            if not await self._await_pid_exit(entry, _STOP_GRACE_S):
                self._signal_pg(pid, signal.SIGKILL)
                await self._await_pid_exit(entry, _STOP_GRACE_S)
        if entry.exit_code is None:
            entry.exit_code = proc.returncode if proc.returncode is not None else -1
        # Cancel the stdout/stderr readers. These tasks may live on another loop
        # (TestClient); only await ones bound to the current running loop.
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None
        for task in entry.readers:
            task.cancel()
        for task in entry.readers:
            if current_loop is not None and task.get_loop() is current_loop:
                try:  # noqa: SIM105
                    await task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001, RUF100
                    pass
        entry.readers = []

    @staticmethod
    def _signal_pg(pid: int, sig: int) -> None:
        try:
            os.killpg(os.getpgid(pid), sig)
        except ProcessLookupError:
            pass
        except Exception:  # noqa: BLE001, RUF100
            logger.debug("killpg %s failed pid=%s", sig, pid, exc_info=True)

    @staticmethod
    def _already_reaped(entry: _RunEntry) -> bool:
        return entry.exit_code is not None

    async def _await_pid_exit(self, entry: _RunEntry, timeout: float) -> bool:
        """Poll for process exit via non-blocking waitpid. Returns True if exited."""
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            if entry.proc.returncode is not None:
                return True
            try:
                wpid, wstatus = os.waitpid(entry.pid, os.WNOHANG)
            except ChildProcessError:
                # Already reaped by the transport's SIGCHLD handler.
                return True
            except Exception:  # noqa: BLE001, RUF100
                return True
            if wpid == entry.pid:
                entry.exit_code = os.waitstatus_to_exitcode(wstatus)
                return True
            await asyncio.sleep(0.05)
        return entry.proc.returncode is not None or entry.exit_code is not None

    def status(self, project_id: str, *, service_id: str = "legacy") -> RunStatus:
        entry = self._entries.get((project_id, service_id))
        if entry is None:
            return {
                "running": False,
                "command": None,
                "pid": None,
                "started_at": None,
                "exit_code": None,
            }
        return entry.status_dict()

    def get_logs(
        self, project_id: str, after: int = 0, *, service_id: str = "legacy"
    ) -> RunLogs:
        entry = self._entries.get((project_id, service_id))
        if entry is None:
            return {"lines": [], "last_seq": 0, "running": False, "exit_code": None}
        status = entry.status_dict()
        lines = [item for item in entry.logs if item["seq"] > after]
        return {
            "lines": lines,
            "last_seq": entry.last_seq,
            "running": status["running"],
            "exit_code": status["exit_code"],
        }

    async def shutdown_all(self) -> None:
        async with self._lock:
            entries = list(self._entries.values())
        for entry in entries:
            try:
                await self._terminate(entry)
            except Exception:  # noqa: BLE001, RUF100
                logger.debug("shutdown_all terminate failed pid=%s", entry.pid, exc_info=True)


# Module-level singleton (mirrors `git_service = GitService()` export style).
project_run_manager = ProjectRunManager()
