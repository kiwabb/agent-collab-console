"""Project-level Conductor runtime with tiered memory.

Phase 5 keeps this deterministic by default: compaction and retrieval are
local summaries so the feature works without adding a vector service or extra
LLM spend. The storage model is ready for a richer embedding backend later.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from app.application.github_pr_followup import sweep_project_github_prs
from app.domain.models import (
    ConductorTask,
    ProjectConductorState,
    ProjectMemoryEmbedding,
    SubAgentResult,
)

logger = logging.getLogger(__name__)


def estimate_tokens(text: str) -> int:
    """Cheap token estimate used for budget gates."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def _safe_json_list(raw: str | None) -> list:
    try:
        parsed = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _tokenize(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[\w\u4e00-\u9fff]+", text.lower())
        if len(token) >= 3
    }


async def _run_subprocess(args: list[str], *, cwd: str, timeout_s: int = 30) -> subprocess.CompletedProcess[str]:
    def _run() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )

    return await asyncio.get_running_loop().run_in_executor(None, _run)


class ProjectConductor:
    """Long-lived per-project Conductor facade.

    It owns hot/warm/cold context and can answer ad-hoc project questions even
    when no issue workflow is active.
    """

    def __init__(
        self,
        *,
        project_id: str,
        store,
        event_bus=None,
        hot_token_limit: int = 60_000,
        warm_token_limit: int = 30_000,
    ) -> None:
        self.project_id = project_id
        self.store = store
        self.event_bus = event_bus
        self.hot_token_limit = hot_token_limit
        self.warm_token_limit = warm_token_limit

    async def handle_task(self, task: ConductorTask) -> dict:
        task.status = "running"
        task.updated_at = datetime.now()
        if task.created_at is None:
            task.created_at = task.updated_at
        await self.store.save_conductor_task(task)

        state = await self.get_or_create_state()
        question = str(task.payload.get("question") or task.payload.get("prompt") or "").strip()
        if task.task_kind == "scheduled_review" and not question:
            question = "Run a scheduled project health review."
        answer = await self.answer_question(question, state=state)
        github_pr_followup = await self._run_scheduled_pr_followup(task)
        await self._append_hot_without_compaction(
            state,
            {"role": "user", "kind": task.task_kind, "content": question, "task_id": task.id},
        )
        answer_event = {"role": "project_conductor", "kind": "answer", "content": answer, "task_id": task.id}
        if github_pr_followup is not None:
            answer_event["github_pr_followup"] = github_pr_followup
        await self._append_hot_without_compaction(
            state,
            answer_event,
        )
        state.total_tasks_handled += 1
        await self._ensure_token_budget(state)
        await self.store.save_project_conductor_state(state)

        result = {"status": "done", "answer": answer, "task_id": task.id}
        if github_pr_followup is not None:
            result["github_pr_followup"] = github_pr_followup
        task.status = "done"
        task.result_json = json.dumps(result, ensure_ascii=False)
        task.updated_at = datetime.now()
        await self.store.save_conductor_task(task)
        return result

    async def _run_scheduled_pr_followup(self, task: ConductorTask) -> dict[str, object] | None:
        if task.task_kind != "scheduled_review":
            return None
        try:
            summary = await sweep_project_github_prs(
                self.project_id,
                store=self.store,
                event_bus=self.event_bus,
                run_subprocess=_run_subprocess,
                auto_merge=True,
            )
        except Exception as exc:  # noqa: BLE001 - scheduled reviews are best-effort supervisor work.
            logger.exception("scheduled GitHub PR follow-up failed project_id=%s task_id=%s", self.project_id, task.id)
            return {"status": "failed", "error": str(exc)}
        return summary.to_dict()

    async def notify_subagent_complete(
        self,
        result: SubAgentResult,
        *,
        project_id: str | None = None,
        issue_id: str | None = None,
    ) -> None:
        if project_id is not None and project_id != self.project_id:
            return
        await self.append_hot_event(
            role=result.role,
            content=result.summary,
            issue_id=issue_id,
            extra={
                "node_key": result.node_key,
                "task_id": result.task_id,
                "status": result.status,
                "files_changed": result.files_changed,
            },
        )

    async def append_hot_event(
        self,
        *,
        role: str,
        content: str,
        issue_id: str | None = None,
        extra: dict | None = None,
    ) -> ProjectConductorState:
        state = await self.get_or_create_state()
        event = {
            "role": role,
            "content": content,
            "issue_id": issue_id,
            "created_at": datetime.now().isoformat(),
        }
        if extra:
            event.update(extra)
        await self._append_hot_without_compaction(state, event)
        await self._ensure_token_budget(state)
        await self.store.save_project_conductor_state(state)
        return state

    async def answer_question(self, question: str, *, state: ProjectConductorState | None = None) -> str:
        state = state or await self.get_or_create_state()
        warm = _safe_json_list(state.warm_summaries_json)
        warm_text = "\n".join(
            f"- {item.get('summary', item)}" if isinstance(item, dict) else f"- {item}"
            for item in warm[-5:]
        )
        cold = await self.retrieve_cold(question, top_k=3)
        cold_text = "\n".join(f"- {item}" for item in cold)
        parts = [
            "ProjectConductor context answer.",
            f"Question: {question or '(scheduled review)'}",
        ]
        if state.pinned_text:
            parts.append(f"Pinned:\n{state.pinned_text}")
        if warm_text:
            parts.append(f"Warm summaries:\n{warm_text}")
        if cold_text:
            parts.append(f"Relevant cold memory:\n{cold_text}")
        if not any([state.pinned_text, warm_text, cold_text]):
            parts.append("No project memory has been recorded yet.")
        return "\n\n".join(parts)

    async def retrieve_cold(self, query: str, top_k: int = 3) -> list[str]:
        memories = await self.store.list_project_memory_embeddings(self.project_id)
        query_tokens = _tokenize(query)
        ranked: list[tuple[int, str]] = []
        for memory in memories:
            tokens = _tokenize(memory.summary_text)
            score = len(query_tokens & tokens)
            if score or not query_tokens:
                ranked.append((score, memory.summary_text))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [text for _, text in ranked[:top_k]]

    async def get_or_create_state(self) -> ProjectConductorState:
        state = await self.store.load_project_conductor_state(self.project_id)
        if state is not None:
            if not state.pinned_text:
                pinned = await self._read_pinned_text()
                if pinned:
                    state.pinned_text = pinned
                    state.updated_at = datetime.now()
                    await self.store.save_project_conductor_state(state)
            return state

        pinned = await self._read_pinned_text()
        state = ProjectConductorState(
            project_id=self.project_id,
            pinned_text=pinned,
            updated_at=datetime.now(),
        )
        await self.store.save_project_conductor_state(state)
        return state

    async def _read_pinned_text(self) -> str:
        project = await self.store.load_project(self.project_id)
        if project is None:
            return ""
        path = Path(project.repo_path) / ".agent-collab" / "team_notes.md"
        try:
            return path.read_text(encoding="utf-8")[:2_000]
        except OSError:
            return ""

    async def _append_hot_without_compaction(self, state: ProjectConductorState, event: dict) -> None:
        hot = _safe_json_list(state.hot_thread_json)
        hot.append(event)
        state.hot_thread_json = json.dumps(hot, ensure_ascii=False, default=str)
        state.hot_tokens = estimate_tokens(state.hot_thread_json)
        state.updated_at = datetime.now()

    async def _ensure_token_budget(self, state: ProjectConductorState) -> None:
        if state.hot_tokens > self.hot_token_limit:
            await self._compact_hot_to_warm(state)
        if state.warm_tokens > self.warm_token_limit:
            await self._compact_warm_to_cold(state)

    async def _compact_hot_to_warm(self, state: ProjectConductorState) -> None:
        hot = _safe_json_list(state.hot_thread_json)
        if not hot:
            return
        summary = self._summarize_events(hot)
        warm = _safe_json_list(state.warm_summaries_json)
        warm.append({
            "id": str(uuid4()),
            "summary": summary,
            "event_count": len(hot),
            "created_at": datetime.now().isoformat(),
        })
        state.hot_thread_json = "[]"
        state.hot_tokens = 0
        state.warm_summaries_json = json.dumps(warm, ensure_ascii=False)
        state.warm_tokens = estimate_tokens(state.warm_summaries_json)
        state.last_compaction_at = datetime.now()
        state.updated_at = state.last_compaction_at

    async def _compact_warm_to_cold(self, state: ProjectConductorState) -> None:
        warm = _safe_json_list(state.warm_summaries_json)
        if not warm:
            return
        remaining: list = []
        for item in warm:
            summary = item.get("summary") if isinstance(item, dict) else str(item)
            source_id = item.get("id") if isinstance(item, dict) else str(uuid4())
            memory = ProjectMemoryEmbedding(
                id=str(uuid4()),
                project_id=self.project_id,
                source_kind="warm_summary",
                source_id=str(source_id),
                summary_text=str(summary),
                vector_json="[]",
                created_at=datetime.now(),
            )
            await self.store.save_project_memory_embedding(memory)
        state.warm_summaries_json = json.dumps(remaining, ensure_ascii=False)
        state.warm_tokens = 0
        state.last_compaction_at = datetime.now()
        state.updated_at = state.last_compaction_at

    @staticmethod
    def _summarize_events(events: list) -> str:
        fragments: list[str] = []
        for event in events:
            if isinstance(event, dict):
                role = event.get("role", "event")
                content = str(event.get("content", "")).strip()
                fragments.append(f"{role}: {content}")
            else:
                fragments.append(str(event))
        return " | ".join(fragment for fragment in fragments if fragment)[:4_000]
