"""Standalone CLI for the workflow orchestrator.

Usage:
    python -m scripts.plan_issue --title "Fix login regression" --description "..."
    python -m scripts.plan_issue --issue-id <id>   # loads from console.db

Prints the proposed DAG as pretty JSON to stdout.
"""
import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

# Ensure backend/app is importable when invoked as `python -m scripts.plan_issue`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.domain.models import CodexIssue  # noqa: E402


async def _from_args(args) -> dict:
    from app.bootstrap import async_store
    from app.application.agent_seed import seed_builtin_agents
    from app.application.workflow_orchestrator import WorkflowOrchestrator

    if async_store is None:
        raise SystemExit("SQLite store unavailable — set SQLITE_DB_PATH or enable USE_SQLITE")

    await seed_builtin_agents(async_store)
    agents = await async_store.list_agents(workspace_id=None)
    if args.issue_id:
        issue = await async_store.load_codex_issue(args.issue_id)
        if issue is None:
            raise SystemExit(f"Issue {args.issue_id} not found")
    else:
        if not args.title:
            raise SystemExit("--title is required when --issue-id is omitted")
        issue = CodexIssue(
            id=str(uuid4()),
            session_id="cli-ephemeral",
            title=args.title,
            description=args.description or "",
            created_at=datetime.now(),
        )
    orchestrator = WorkflowOrchestrator(store=async_store)
    return await orchestrator.propose_graph(issue, agents=agents)


def main() -> None:
    p = argparse.ArgumentParser(description="Propose a DAG for an issue (heuristic).")
    p.add_argument("--issue-id", help="Load an existing issue from the database")
    p.add_argument("--title", help="Ephemeral issue title (when --issue-id is omitted)")
    p.add_argument("--description", help="Ephemeral issue description")
    args = p.parse_args()
    dag = asyncio.run(_from_args(args))
    json.dump(dag, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
