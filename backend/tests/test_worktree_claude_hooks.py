"""Tests for worktree_claude_hooks: injection and the limit_read hook script."""

from __future__ import annotations  # noqa: I001

import json
import subprocess
import sys
import textwrap  # noqa: F401
from pathlib import Path

import pytest

from app.application.worktree_claude_hooks import inject_worktree_claude_hooks


# ---------------------------------------------------------------------------
# inject_worktree_claude_hooks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inject_creates_settings_and_hook(tmp_path):
    await inject_worktree_claude_hooks(tmp_path)

    settings_file = tmp_path / ".claude" / "settings.json"
    assert settings_file.exists(), "settings.json must be created"

    hook_file = tmp_path / ".claude" / "hooks" / "limit_read.py"
    assert hook_file.exists(), "limit_read.py must be created"
    assert hook_file.stat().st_mode & 0o111, "hook must be executable"


@pytest.mark.asyncio
async def test_inject_settings_content(tmp_path):
    await inject_worktree_claude_hooks(tmp_path)

    data = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    hooks = data["hooks"]["PreToolUse"]
    assert any(h.get("matcher") == "Read" for h in hooks)

    read_hook = next(h for h in hooks if h.get("matcher") == "Read")
    cmd_hooks = read_hook["hooks"]
    assert any("limit_read.py" in h.get("command", "") for h in cmd_hooks), (
        "settings must reference limit_read.py"
    )


@pytest.mark.asyncio
async def test_inject_idempotent(tmp_path):
    await inject_worktree_claude_hooks(tmp_path)
    await inject_worktree_claude_hooks(tmp_path)  # second call must not raise
    assert (tmp_path / ".claude" / "settings.json").exists()


@pytest.mark.asyncio
async def test_inject_excludes_managed_hooks_from_git_status(tmp_path):
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    await inject_worktree_claude_hooks(tmp_path)

    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert not any(path.startswith(".claude/") for path in untracked)
    assert ".claude/" in (tmp_path / ".git" / "info" / "exclude").read_text()


# ---------------------------------------------------------------------------
# limit_read.py hook behaviour — run via subprocess so we test the real script
# ---------------------------------------------------------------------------


def _invoke_hook(
    hook_path: Path, tool_name: str, file_path: str, offset=None
) -> subprocess.CompletedProcess:
    tool_input: dict = {"file_path": file_path}
    if offset is not None:
        tool_input["offset"] = offset
    payload = json.dumps({"tool_name": tool_name, "tool_input": tool_input})
    return subprocess.run(
        [sys.executable, str(hook_path)],
        input=payload.encode(),
        capture_output=True,
    )


@pytest.fixture
def hook_dir(tmp_path):
    """Return a tmp dir with the hook injected."""
    import asyncio

    # asyncio.run creates and owns its own loop — robust regardless of whether a
    # prior async test left the thread's loop closed (Python 3.14 removed the
    # implicit get_event_loop() fallback).
    asyncio.run(inject_worktree_claude_hooks(tmp_path))
    return tmp_path


@pytest.fixture
def hook_path(hook_dir):
    return hook_dir / ".claude" / "hooks" / "limit_read.py"


def _make_file(tmp_path: Path, lines: int, name: str = "big.py") -> Path:
    p = tmp_path / name
    p.write_text("\n".join(f"line {i}" for i in range(lines)))
    return p


def test_hook_allows_non_read_tool(hook_path):
    result = _invoke_hook(hook_path, "Bash", "/nonexistent/path.sh")
    assert result.returncode == 0, "Non-Read tools must always pass"


def test_hook_allows_small_file(hook_path, tmp_path):
    small = _make_file(tmp_path, lines=10)
    result = _invoke_hook(hook_path, "Read", str(small))
    assert result.returncode == 0, "Small file must be allowed"


def test_hook_blocks_large_file(hook_path, tmp_path):
    big = _make_file(tmp_path, lines=300)
    result = _invoke_hook(hook_path, "Read", str(big))
    assert result.returncode == 2, "Large file with no offset must be blocked (exit 2)"
    assert b"BLOCKED" in result.stderr, "Stderr must contain BLOCKED message"
    assert b"grep" in result.stderr, "Stderr must suggest grep alternative"


def test_hook_allows_large_file_with_offset(hook_path, tmp_path):
    big = _make_file(tmp_path, lines=300)
    result = _invoke_hook(hook_path, "Read", str(big), offset=150)
    assert result.returncode == 0, "Large file with positive offset must be allowed"


def test_hook_allows_nonexistent_file(hook_path):
    result = _invoke_hook(hook_path, "Read", "/no/such/file.py")
    assert result.returncode == 0, "Non-existent file must pass through (let CLI handle it)"


def test_hook_allows_exactly_200_line_file(hook_path, tmp_path):
    boundary = _make_file(tmp_path, lines=200)
    result = _invoke_hook(hook_path, "Read", str(boundary))
    assert result.returncode == 0, "Exactly 200 lines must be allowed"


def test_hook_blocks_201_line_file(hook_path, tmp_path):
    over = _make_file(tmp_path, lines=201)
    result = _invoke_hook(hook_path, "Read", str(over))
    assert result.returncode == 2, "201 lines must be blocked"


# ---------------------------------------------------------------------------
# Timeout ladder invariant: idle > stall + 120
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inject_merges_with_existing_settings(tmp_path):
    existing = {"hooks": {"SessionStart": [{"type": "command", "command": "echo hi"}]}}
    settings_file = tmp_path / ".claude" / "settings.json"
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(json.dumps(existing))

    await inject_worktree_claude_hooks(tmp_path)

    result = json.loads(settings_file.read_text())
    assert "SessionStart" in result["hooks"], "existing SessionStart hook must be preserved"
    assert "PreToolUse" in result["hooks"], "PreToolUse must be added"
    pre_tool = result["hooks"]["PreToolUse"]
    assert any(
        any("limit_read.py" in h.get("command", "") for h in entry.get("hooks", []))
        for entry in pre_tool
        if entry.get("matcher") == "Read"
    ), "limit_read hook must be present in merged result"


@pytest.mark.asyncio
async def test_inject_does_not_duplicate_hook(tmp_path):
    await inject_worktree_claude_hooks(tmp_path)
    await inject_worktree_claude_hooks(tmp_path)  # second call

    data = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    read_entries = [
        e for e in data["hooks"]["PreToolUse"] if isinstance(e, dict) and e.get("matcher") == "Read"
    ]
    limit_read_hooks = [
        h
        for e in read_entries
        for h in e.get("hooks", [])
        if "limit_read.py" in h.get("command", "")
    ]
    assert len(limit_read_hooks) == 1, (
        f"limit_read hook must appear exactly once, found {len(limit_read_hooks)}"
    )


def test_timeout_invariant_passes_with_new_defaults():
    from app.application.timeouts import (  # noqa: I001
        check_invariants,
        DEFAULT_SUBAGENT_IDLE_S,
        DEFAULT_STALL_THRESHOLD_S,
    )  # noqa: I001, RUF100

    assert DEFAULT_SUBAGENT_IDLE_S > DEFAULT_STALL_THRESHOLD_S + 120, (
        f"DEFAULT_SUBAGENT_IDLE_S ({DEFAULT_SUBAGENT_IDLE_S}) must be > "
        f"DEFAULT_STALL_THRESHOLD_S+120 ({DEFAULT_STALL_THRESHOLD_S + 120})"
    )
    violations = check_invariants()
    stall_violations = [v for v in violations if "STALL_THRESHOLD" in v]
    assert not stall_violations, (
        f"Unexpected stall-related invariant violations: {stall_violations}"
    )
