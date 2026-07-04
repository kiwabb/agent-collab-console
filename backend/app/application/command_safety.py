"""Shared shell-command safety filter.

A small allow-by-default / refuse-known-foot-guns check reused by both the QA
verification runner (`qa_workflow.py`) and the project dev-server runner
(`project_run_manager.py`). The sandbox is never bet on the caller picking safe
commands — these patterns catch the obvious destructive / privilege-escalating
shapes before we ever spawn a subprocess.
"""

from __future__ import annotations  # noqa: I001

import re
import shlex


# Patterns we refuse to run. These are the obvious foot-guns; callers run in a
# git worktree / project repo but should never assume the input is safe.
REFUSED_COMMAND_PATTERNS = [
    re.compile(r"\brm\s+-[rRf]"),
    re.compile(r"\bsudo\b"),
    re.compile(r"\b(curl|wget)\b[^|;]*\|\s*(sh|bash|zsh|python|node)\b"),
    re.compile(r":\(\)\s*\{"),  # fork bomb prefix
    re.compile(r"\bdd\s+if=.*\bof="),
    re.compile(r"\bmkfs\b|\bfdisk\b|\bformat\b"),
    re.compile(r"\bshutdown\b|\breboot\b|\bhalt\b|\bpoweroff\b"),
    re.compile(r"\bgit\s+push\b"),  # the agent should NOT push; user merges.
    re.compile(r"\bgit\s+reset\s+--hard\b"),
    re.compile(r"\b(npm|yarn|pnpm)\s+publish\b"),
    re.compile(r"\bpip\s+install\b.*--user"),  # force into the system env
]

_SHELL_META = re.compile(r"[;&|`$<>]")

ALLOWED_COMMANDS: tuple[tuple[str, ...], ...] = (
    ("pytest",),
    ("python", "-m", "pytest"),
    ("python3", "-m", "pytest"),
    ("ruff", "check"),
    ("ruff", "format", "--check"),
    ("mypy",),
    ("npm", "test"),
    ("npm", "run", "test"),
    ("npm", "run", "lint"),
    ("npm", "run", "typecheck"),
    ("npm", "run", "build"),
    ("pnpm", "test"),
    ("pnpm", "run", "test"),
    ("pnpm", "run", "lint"),
    ("pnpm", "run", "typecheck"),
    ("pnpm", "run", "build"),
    ("yarn", "test"),
    ("yarn", "run", "test"),
    ("yarn", "run", "lint"),
    ("yarn", "run", "typecheck"),
    ("yarn", "run", "build"),
    ("tsc",),
    ("go", "test"),
    ("cargo", "test"),
    ("make", "test"),
)


def refuse_reason(cmd: str) -> str | None:
    """Return the matching refused-pattern source, or None if the command is allowed."""
    for pat in REFUSED_COMMAND_PATTERNS:
        if pat.search(cmd):
            return pat.pattern
    return None


def parse_allowed_command(cmd: str) -> tuple[list[str] | None, str | None]:
    """Parse and validate a QA command against a narrow allowlist.

    Returns ``(argv, None)`` when allowed, otherwise ``(None, reason)``.
    """
    if not cmd.strip():
        return None, "empty"
    if _SHELL_META.search(cmd):
        return None, "shell metacharacters are not allowed"
    try:
        argv = shlex.split(cmd)
    except ValueError as exc:
        return None, f"invalid shell syntax: {exc}"
    if not argv:
        return None, "empty"
    for prefix in ALLOWED_COMMANDS:
        if tuple(argv[: len(prefix)]) == prefix:
            return argv, None
    return None, "command is not in the QA allowlist"
