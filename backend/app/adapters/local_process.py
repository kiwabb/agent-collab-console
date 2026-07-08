"""Helpers for trusted local CLI subprocess calls.

The console is a local-first developer tool: git, osascript, codex, and claude
are expected local executables. Keep those calls centralized so Bandit
subprocess suppressions live at the I/O boundary instead of being copied across
application services.
"""

from __future__ import annotations

import subprocess  # nosec B404
from collections.abc import Mapping, Sequence
from pathlib import Path

# Trusted local CLI integration boundary; all callers pass argv with shell disabled.
CalledProcessError = subprocess.CalledProcessError
CompletedProcess = subprocess.CompletedProcess
TimeoutExpired = subprocess.TimeoutExpired


def run_trusted_local(
    args: Sequence[str],
    *,
    cwd: str | Path | None = None,
    capture_output: bool = True,
    text: bool = True,
    check: bool = False,
    timeout: float | None = None,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a trusted local executable with shell disabled.

    Args are assembled by the application from trusted executable names and
    fixed option strings. User content may appear only as normal argv values;
    `shell=False` prevents shell interpolation.
    """
    # Trusted local argv; shell is explicitly disabled.
    return subprocess.run(  # nosec B603
        list(args),
        shell=False,
        cwd=cwd,
        capture_output=capture_output,
        text=text,
        check=check,
        timeout=timeout,
        env=dict(env) if env is not None else None,
    )
