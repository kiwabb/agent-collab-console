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
from pathlib import Path, PureWindowsPath


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
    ("false",),
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

_COMMON_NON_EXECUTING_OPTIONS = frozenset(
    {
        "--collect-only",
        "--co",
        "--dry-run",
        "--help",
        "--list-files-only",
        "--list-tests",
        "--listTests",
        "--passWithNoTests",
        "--show-config",
        "--showConfig",
        "--version",
        "-V",
        "-h",
    }
)
_BLOCKED_OPTIONS_BY_COMMAND: dict[tuple[str, ...], frozenset[str]] = {
    ("pytest",): frozenset(
        {"--basetemp", "--override-ini", "--pdb", "--pyargs", "--trace", "-o", "-p"}
    ),
    ("python", "-m", "pytest"): frozenset(
        {"--basetemp", "--override-ini", "--pdb", "--pyargs", "--trace", "-o", "-p"}
    ),
    ("python3", "-m", "pytest"): frozenset(
        {"--basetemp", "--override-ini", "--pdb", "--pyargs", "--trace", "-o", "-p"}
    ),
    ("ruff", "check"): frozenset({"--exit-zero", "--fix", "--fix-only", "--unsafe-fixes"}),
    ("mypy",): frozenset({"--install-types"}),
    ("npm", "test"): frozenset({"--if-present"}),
    ("npm", "run", "test"): frozenset({"--if-present"}),
    ("npm", "run", "lint"): frozenset({"--if-present"}),
    ("npm", "run", "typecheck"): frozenset({"--if-present"}),
    ("npm", "run", "build"): frozenset({"--if-present"}),
    ("tsc",): frozenset({"--noCheck", "--watch", "-w"}),
    ("go", "test"): frozenset({"--exec", "-exec", "-list"}),
    ("cargo", "test"): frozenset({"--no-run"}),
    ("make", "test"): frozenset(
        {
            "--eval",
            "--include-dir",
            "--just-print",
            "--question",
            "--recon",
            "--touch",
            "-E",
            "-I",
            "-n",
            "-q",
            "-t",
        }
    ),
}
_PATH_OPTIONS_BY_COMMAND: dict[tuple[str, ...], frozenset[str]] = {
    ("pytest",): frozenset({"--basetemp", "--confcutdir", "--rootdir", "-c"}),
    ("python", "-m", "pytest"): frozenset(
        {"--basetemp", "--confcutdir", "--rootdir", "-c"}
    ),
    ("python3", "-m", "pytest"): frozenset(
        {"--basetemp", "--confcutdir", "--rootdir", "-c"}
    ),
    ("ruff", "check"): frozenset({"--cache-dir", "--config"}),
    ("ruff", "format", "--check"): frozenset({"--cache-dir", "--config"}),
    ("mypy",): frozenset({"--cache-dir", "--config-file", "--python-executable"}),
    ("npm", "test"): frozenset({"--cache", "--prefix", "--userconfig"}),
    ("npm", "run", "test"): frozenset({"--cache", "--prefix", "--userconfig"}),
    ("npm", "run", "lint"): frozenset({"--cache", "--prefix", "--userconfig"}),
    ("npm", "run", "typecheck"): frozenset({"--cache", "--prefix", "--userconfig"}),
    ("npm", "run", "build"): frozenset({"--cache", "--prefix", "--userconfig"}),
    ("pnpm", "test"): frozenset(
        {"--dir", "--prefix", "--store-dir", "--workspace-dir", "-C"}
    ),
    ("pnpm", "run", "test"): frozenset(
        {"--dir", "--prefix", "--store-dir", "--workspace-dir", "-C"}
    ),
    ("pnpm", "run", "lint"): frozenset(
        {"--dir", "--prefix", "--store-dir", "--workspace-dir", "-C"}
    ),
    ("pnpm", "run", "typecheck"): frozenset(
        {"--dir", "--prefix", "--store-dir", "--workspace-dir", "-C"}
    ),
    ("pnpm", "run", "build"): frozenset(
        {"--dir", "--prefix", "--store-dir", "--workspace-dir", "-C"}
    ),
    ("yarn", "test"): frozenset({"--cache-folder", "--cwd", "--global-folder"}),
    ("yarn", "run", "test"): frozenset({"--cache-folder", "--cwd", "--global-folder"}),
    ("yarn", "run", "lint"): frozenset({"--cache-folder", "--cwd", "--global-folder"}),
    ("yarn", "run", "typecheck"): frozenset({"--cache-folder", "--cwd", "--global-folder"}),
    ("yarn", "run", "build"): frozenset({"--cache-folder", "--cwd", "--global-folder"}),
    ("tsc",): frozenset({"--project", "-p"}),
    ("go", "test"): frozenset({"-C", "-modfile", "-overlay", "-vettool"}),
    ("cargo", "test"): frozenset({"--manifest-path", "--target-dir"}),
    ("make", "test"): frozenset({"--directory", "--file", "--include-dir", "-C", "-I", "-f"}),
}


def refuse_reason(cmd: str) -> str | None:
    """Return the matching refused-pattern source, or None if the command is allowed."""
    for pat in REFUSED_COMMAND_PATTERNS:
        if pat.search(cmd):
            return pat.pattern
    return None


def _matched_command(argv: list[str]) -> tuple[str, ...] | None:
    return next(
        (prefix for prefix in ALLOWED_COMMANDS if tuple(argv[: len(prefix)]) == prefix),
        None,
    )


def _option_name(argument: str, options: frozenset[str]) -> str | None:
    option = argument.split("=", 1)[0]
    if option in options:
        return option
    return next(
        (
            candidate
            for candidate in options
            if len(candidate) == 2
            and candidate.startswith("-")
            and argument.startswith(candidate)
            and len(argument) > len(candidate)
        ),
        None,
    )


def _path_value(argument: str) -> str:
    value = argument.split("=", 1)[1] if "=" in argument else argument
    return value.split("::", 1)[0]


def _looks_like_path(value: str, root: Path) -> bool:
    path = Path(value)
    return (
        path.is_absolute()
        or PureWindowsPath(value).is_absolute()
        or value.startswith("~")
        or ".." in path.parts
        or "/" in value
        or "\\" in value
        or (root / path).exists()
        or (root / path).is_symlink()
    )


def _workspace_path_error(value: str, root: Path) -> str | None:
    path_value = _path_value(value)
    if not path_value or path_value == "-":
        return "verification path is missing"
    candidate_path = Path(path_value).expanduser()
    if PureWindowsPath(path_value).is_absolute():
        return "verification command path is outside the worktree"
    candidate = candidate_path if candidate_path.is_absolute() else root / candidate_path
    if not candidate.resolve().is_relative_to(root):
        return "verification command path is outside the worktree"
    return None


def _validate_workspace_arguments(
    argv: list[str],
    command: tuple[str, ...],
    root: Path,
) -> str | None:
    path_options = _PATH_OPTIONS_BY_COMMAND.get(command, frozenset())
    index = len(command)
    while index < len(argv):
        argument = argv[index]
        path_option = _option_name(argument, path_options)
        if path_option is not None:
            if "=" in argument or argument != path_option:
                value = argument[len(path_option) :].lstrip("=")
            else:
                index += 1
                if index >= len(argv):
                    return "verification path option has no value"
                value = argv[index]
            error = _workspace_path_error(value, root)
            if error is not None:
                return error
        else:
            candidates = [argument]
            if "=" in argument:
                candidates.append(argument.split("=", 1)[1])
            for candidate in candidates:
                if candidate.startswith("-") and "=" not in candidate:
                    continue
                path_value = _path_value(candidate)
                if _looks_like_path(path_value, root):
                    error = _workspace_path_error(path_value, root)
                    if error is not None:
                        return error
        index += 1
    return None


def parse_allowed_command(
    cmd: str,
    *,
    workspace_root: str | Path | None = None,
) -> tuple[list[str] | None, str | None]:
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
    command = _matched_command(argv)
    if command is None:
        return None, "command is not in the QA allowlist"

    blocked_options = _BLOCKED_OPTIONS_BY_COMMAND.get(command, frozenset())
    for argument in argv[len(command) :]:
        option = argument.split("=", 1)[0]
        if argument in _COMMON_NON_EXECUTING_OPTIONS or option in _COMMON_NON_EXECUTING_OPTIONS:
            return None, "non-executing verification option is not allowed"
        if argument in blocked_options or option in blocked_options:
            return None, "verification command option is not allowed"
        if _option_name(argument, blocked_options) is not None:
            return None, "verification command option is not allowed"

    if command == ("go", "test") and any(
        argument in {"-run=^$", "-run=$^"} for argument in argv[len(command) :]
    ):
        return None, "non-executing verification option is not allowed"

    if workspace_root is not None:
        root = Path(workspace_root).resolve()
        if not root.is_dir():
            return None, "verification workspace does not exist"
        path_error = _validate_workspace_arguments(argv, command, root)
        if path_error is not None:
            return None, path_error
    return argv, None
