import asyncio
import sys
from pathlib import Path

sys.path.append(str(Path.cwd() / "backend"))
from app.bootstrap import codex_store

async def run():
    issue_id = "cf0822bb-3c11-4505-8059-2d15abf4647f"
    s = await codex_store.load_codex_issue(issue_id)
    if s:
        print("Issue Phase:", s.current_phase)
    else:
        print("Issue not found")
    tasks = await codex_store.list_codex_tasks(issue_id=issue_id)
    for t in tasks:
        print("Task ID:", t.get("id"), "Title:", t.get("title"))
        print("  - Status:", t.get("status"))
        print("  - Workspace:", t.get("workspace_path"))
        print("  - Result:", t.get("result"))

asyncio.run(run())
