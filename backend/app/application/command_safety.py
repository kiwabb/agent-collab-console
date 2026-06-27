"""Shared shell-command safety filter.

A small allow-by-default / refuse-known-foot-guns check reused by both the QA
verification runner (`qa_workflow.py`) and the project dev-server runner
(`project_run_manager.py`). The sandbox is never bet on the caller picking safe
commands — these patterns catch the obvious destructive / privilege-escalating
shapes before we ever spawn a subprocess.
"""

from __future__ import annotations  # noqa: I001

import re


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


def refuse_reason(cmd: str) -> str | None:
    """Return the matching refused-pattern source, or None if the command is allowed."""
    for pat in REFUSED_COMMAND_PATTERNS:
        if pat.search(cmd):
            return pat.pattern
    return None
