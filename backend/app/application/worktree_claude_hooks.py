"""Inject a PreToolUse hook into every worktree to guard against large file reads.

When an engineer runs inside a worktree, the claude CLI has no hook protection
by default. A Read of a large file (e.g. 6281-line api.py) sends hundreds of KB
as a tool result to the upstream LLM, which can cause a multi-minute timeout or
connection drop. The hook below blocks that Read and guides the engineer to use
grep + targeted Read with offset instead.
"""
from __future__ import annotations

import contextlib
import json
from pathlib import Path

from app.json_safety import object_dict

_HOOK_SCRIPT = '''\
#!/usr/bin/env python3
import json, sys
from pathlib import Path

data = json.loads(sys.stdin.read())
tool_name = data.get("tool_name", "")
if tool_name != "Read":
    sys.exit(0)

tool_input = data.get("tool_input", {})
offset = tool_input.get("offset") or 0
try:
    if int(offset) > 0:
        sys.exit(0)
except (TypeError, ValueError):
    pass

file_path = tool_input.get("file_path", "")
p = Path(file_path)
if not p.exists():
    sys.exit(0)

try:
    line_count = sum(1 for _ in p.open(errors="replace"))
except Exception:
    sys.exit(0)

MAX_LINES = 200
if line_count > MAX_LINES:
    print(
        f"BLOCKED: {file_path} has {line_count} lines (limit {MAX_LINES}).\\n"
        f"Use grep to locate the section first:\\n"
        f"  grep -n \\'your_pattern\\' {file_path} | head -20\\n"
        f"Then: Read {file_path} offset=<line> limit=40",
        file=sys.stderr,
    )
    sys.exit(2)
sys.exit(0)
'''

_SETTINGS = {
    "hooks": {
        "PreToolUse": [
            {
                "matcher": "Read",
                "hooks": [
                    {
                        "type": "command",
                        "command": "python3 .claude/hooks/limit_read.py",
                        "timeout": 5,
                    }
                ],
            }
        ]
    }
}


async def inject_worktree_claude_hooks(worktree_path: Path | str) -> None:
    """Merge the limit_read PreToolUse hook into .claude/settings.json in *worktree_path*.

    Reads any existing settings.json (e.g. committed by the project) and merges
    our hook entry in rather than overwriting, so project-owned hooks survive.
    """
    root = Path(worktree_path)
    hooks_dir = root / ".claude" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)

    hook_file = hooks_dir / "limit_read.py"
    hook_file.write_text(_HOOK_SCRIPT)
    hook_file.chmod(0o755)

    settings_file = root / ".claude" / "settings.json"
    existing: dict[str, object] = {}
    if settings_file.exists():
        with contextlib.suppress(json.JSONDecodeError, OSError):
            existing = object_dict(json.loads(settings_file.read_text()))

    hooks = object_dict(existing.get("hooks"))
    existing["hooks"] = hooks
    raw_pre_tool = hooks.get("PreToolUse")
    pre_tool = raw_pre_tool if isinstance(raw_pre_tool, list) else []
    hooks["PreToolUse"] = pre_tool
    our_cmd = "python3 .claude/hooks/limit_read.py"
    already = False
    for raw_entry in pre_tool:
        entry = object_dict(raw_entry)
        if entry.get("matcher") != "Read":
            continue
        raw_hooks = entry.get("hooks")
        hook_entries = raw_hooks if isinstance(raw_hooks, list) else []
        if any(object_dict(hook).get("command") == our_cmd for hook in hook_entries):
            already = True
            break
    if not already:
        pre_tool.append(_SETTINGS["hooks"]["PreToolUse"][0])

    settings_file.write_text(json.dumps(existing, indent=2))

    exclude_file = root / ".git" / "info" / "exclude"
    if exclude_file.exists():
        try:
            current = exclude_file.read_text()
        except OSError:
            current = ""
        if ".claude/" not in current.splitlines():
            suffix = "" if current.endswith("\n") or not current else "\n"
            exclude_file.write_text(f"{current}{suffix}.claude/\n")
