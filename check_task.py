import asyncio
import json
import sys
from pathlib import Path

# Add backend to path
sys.path.append(str(Path.cwd() / "backend"))

from app.bootstrap import codex_store

async def run():
    tasks = await codex_store.list_codex_tasks(issue_id="4aa1813e-49b5-495d-9adb-67ebab69a509")
    if not tasks:
        print("No tasks found")
        return
    
    for i, t in enumerate(sorted(tasks, key=lambda x: x.get("created_at", ""), reverse=True)):
        print(f"[{i}] Task ID: {t.get('id')}, Status: {t.get('status')}, Title: {t.get('title')}")
        if t.get("status") == "failed":
            print(f"--- FAILED TASK RESULT ---")
            print(t.get("result"))
            print("--------------------------")

if __name__ == "__main__":
    asyncio.run(run())
