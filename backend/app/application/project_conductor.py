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
from datetime import datetime
from pathlib import Path
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from app.adapters.local_process import CompletedProcess, run_trusted_local
from app.application.github_pr_followup import (
    EventBusLike,
    GitHubPRFollowupStore,
    sweep_project_github_prs,
)
from app.domain.models import (
    ConductorTask,
    Project,
    ProjectConductorState,
    ProjectMemoryEmbedding,
    SubAgentResult,
)

logger = logging.getLogger(__name__)


PROJECT_CONDUCTOR_INPUT_MAX_CHARS = 4_000
PROJECT_CONDUCTOR_ANSWER_MAX_CHARS = 6_000
PROJECT_CONDUCTOR_EVENT_CONTENT_MAX_CHARS = 1_200
PROJECT_CONDUCTOR_SUMMARY_MAX_CHARS = 1_600
PROJECT_CONDUCTOR_HOT_EVENT_LIMIT = 48
PROJECT_CONDUCTOR_WARM_SUMMARY_LIMIT = 24
PROJECT_CONDUCTOR_COLD_SEARCH_LIMIT = 200
PROJECT_CONDUCTOR_STATE_HOT_LIMIT = 20
PROJECT_CONDUCTOR_STATE_WARM_LIMIT = 8
PROJECT_CONDUCTOR_STATE_COLD_LIMIT = 20
PROJECT_CONDUCTOR_STATE_WRITE_RETRIES = 8

_SCHEDULED_REVIEW_QUESTION = "Run a scheduled project health review."
_LEGACY_ANSWER_PREFIX = "ProjectConductor context answer."
_RENDERED_MEMORY_MARKERS = ("\n\nPinned:", "\n\nWarm summaries:", "\n\nRelevant cold memory:")


class ProjectConductorStateError(ValueError):
    """Persisted Project Conductor memory does not satisfy its JSON contract."""


class ProjectConductorStateConflictError(RuntimeError):
    """Concurrent state writers exhausted the bounded compare-and-swap retry budget."""


def _parse_memory_list(raw: str, *, field: str) -> list[object]:
    try:
        parsed: object = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProjectConductorStateError(f"{field} contains invalid JSON") from exc
    if not isinstance(parsed, list):
        raise ProjectConductorStateError(f"{field} must contain a JSON array")
    return parsed


def _bounded_text(value: object, *, limit: int) -> str:
    text = str(value).strip()
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1].rstrip()}…"


def _without_rendered_memory(answer: str) -> str:
    text = answer.strip()
    if not text.startswith(_LEGACY_ANSWER_PREFIX):
        return text
    marker_offsets = [
        offset for marker in _RENDERED_MEMORY_MARKERS if (offset := text.find(marker)) >= 0
    ]
    if marker_offsets:
        text = text[: min(marker_offsets)].rstrip()
    return text


def _compact_github_pr_followup(payload: dict[str, object]) -> dict[str, object]:
    compact: dict[str, object] = {}
    for key in (
        "status",
        "project_id",
        "counts",
        "issues_seen",
        "issues_with_pr",
        "skipped_no_pr",
        "skipped_merged",
        "checked_prs",
    ):
        value = payload.get(key)
        if value is not None:
            compact[key] = value
    error = payload.get("error")
    if error is not None:
        compact["error"] = _bounded_text(error, limit=300)
    return compact


def _normalize_hot_event(event: object) -> dict[str, object]:
    if not isinstance(event, dict):
        return {
            "role": "event",
            "content": _bounded_text(
                _without_rendered_memory(str(event)),
                limit=PROJECT_CONDUCTOR_EVENT_CONTENT_MAX_CHARS,
            ),
        }

    role = _bounded_text(event.get("role", "event"), limit=80) or "event"
    content = _without_rendered_memory(str(event.get("content", "")))
    normalized: dict[str, object] = {
        "role": role,
        "content": _bounded_text(content, limit=PROJECT_CONDUCTOR_EVENT_CONTENT_MAX_CHARS),
    }
    for key in ("kind", "task_id", "issue_id", "created_at", "node_key", "status"):
        value = event.get(key)
        if value is not None and isinstance(value, (str, int, float, bool)):
            normalized[key] = value
    files_changed = event.get("files_changed")
    if isinstance(files_changed, list):
        normalized["files_changed"] = [
            _bounded_text(item, limit=240) for item in files_changed[:20]
        ]
    followup = event.get("github_pr_followup")
    if isinstance(followup, dict):
        normalized["github_pr_followup"] = _compact_github_pr_followup(followup)
    return normalized


def _normalize_warm_item(project_id: str, item: object) -> dict[str, object] | None:
    summary = str(item.get("summary", "")) if isinstance(item, dict) else str(item)
    summary = _bounded_text(
        _without_rendered_memory(summary), limit=PROJECT_CONDUCTOR_SUMMARY_MAX_CHARS
    )
    if not summary:
        return None
    source_id = (
        str(item.get("id"))
        if isinstance(item, dict) and item.get("id")
        else str(uuid5(NAMESPACE_URL, f"project-conductor-warm:{project_id}:{summary}"))
    )
    normalized: dict[str, object] = {"id": source_id, "summary": summary}
    if isinstance(item, dict):
        event_count = item.get("event_count")
        created_at = item.get("created_at")
        if isinstance(event_count, int) and event_count >= 0:
            normalized["event_count"] = event_count
        if isinstance(created_at, str) and created_at:
            normalized["created_at"] = created_at
    return normalized


def estimate_tokens(text: str) -> int:
    """Cheap token estimate used for budget gates."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def _prefix_count_to_compact(
    items: list[object],
    *,
    count_limit: int,
    token_limit: int,
) -> int:
    compact_count = max(0, len(items) - count_limit)
    while compact_count < len(items):
        remaining = items[compact_count:]
        remaining_json = json.dumps(remaining, ensure_ascii=False, default=str)
        remaining_tokens = 0 if not remaining else estimate_tokens(remaining_json)
        if remaining_tokens <= token_limit:
            break
        compact_count += 1
    return compact_count


def _tokenize(text: str) -> set[str]:
    return {token for token in re.findall(r"[\w\u4e00-\u9fff]+", text.lower()) if len(token) >= 3}


async def _run_subprocess(
    args: list[str], *, cwd: str, timeout_s: int = 30
) -> CompletedProcess[str]:
    def _run() -> CompletedProcess[str]:
        return run_trusted_local(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )

    return await asyncio.get_running_loop().run_in_executor(None, _run)


class ProjectConductorStore(GitHubPRFollowupStore, Protocol):
    async def save_conductor_task(self, task: ConductorTask) -> None: ...

    async def load_project_conductor_state(
        self, project_id: str
    ) -> ProjectConductorState | None: ...

    async def save_project_conductor_state(self, state: ProjectConductorState) -> bool: ...

    async def list_project_memory_embeddings(
        self,
        project_id: str,
        limit: int | None = None,
        *,
        descending: bool = False,
    ) -> list[ProjectMemoryEmbedding]: ...

    async def count_project_memory_embeddings(self, project_id: str) -> int: ...

    async def load_project(self, project_id: str) -> Project | None: ...

    async def save_project_memory_embedding(self, memory: ProjectMemoryEmbedding) -> None: ...


class ProjectConductor:
    """Long-lived per-project Conductor facade.

    It owns hot/warm/cold context and can answer ad-hoc project questions even
    when no issue workflow is active.
    """

    def __init__(
        self,
        *,
        project_id: str,
        store: ProjectConductorStore,
        event_bus: EventBusLike | None = None,
        hot_token_limit: int = 60_000,
        warm_token_limit: int = 30_000,
    ) -> None:
        self.project_id = project_id
        self.store = store
        self.event_bus = event_bus
        self.hot_token_limit = hot_token_limit
        self.warm_token_limit = warm_token_limit

    async def handle_task(self, task: ConductorTask) -> dict[str, object]:
        task.status = "running"
        task.updated_at = datetime.now()
        if task.created_at is None:
            task.created_at = task.updated_at
        await self.store.save_conductor_task(task)

        question = str(task.payload.get("question") or task.payload.get("prompt") or "").strip()
        if task.task_kind == "scheduled_review" and not question:
            question = _SCHEDULED_REVIEW_QUESTION

        github_pr_followup: dict[str, object] | None = None
        events: list[dict[str, object]]
        if task.task_kind == "scheduled_review":
            github_pr_followup = await self._run_scheduled_pr_followup(task)
            answer = self._scheduled_review_answer(github_pr_followup)
            events = [
                {
                    "role": "project_conductor",
                    "kind": "scheduled_review",
                    "content": answer,
                    "task_id": task.id,
                    "github_pr_followup": github_pr_followup,
                }
            ]
        else:
            state = await self.get_or_create_state()
            answer = await self.answer_question(question, state=state)
            events = [
                {
                    "role": "user",
                    "kind": task.task_kind,
                    "content": question,
                    "task_id": task.id,
                },
                {
                    "role": "project_conductor",
                    "kind": "answer",
                    "content": answer,
                    "task_id": task.id,
                },
            ]
        await self._mutate_state(events=events, task_increment=1)

        result: dict[str, object] = {"status": "done", "answer": answer, "task_id": task.id}
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
        except Exception as exc:  # External PR supervisor boundary; record the review failure.
            logger.exception(
                "scheduled GitHub PR follow-up failed project_id=%s task_id=%s",
                self.project_id,
                task.id,
            )
            return {"status": "failed", "error": str(exc)}
        return _compact_github_pr_followup(summary.to_dict())

    @staticmethod
    def _scheduled_review_answer(github_pr_followup: dict[str, object] | None) -> str:
        if github_pr_followup is None:
            return "Scheduled project review completed."
        if github_pr_followup.get("status") == "failed":
            error = _bounded_text(github_pr_followup.get("error", "unknown error"), limit=240)
            return f"Scheduled project review completed; PR follow-up failed: {error}"

        checked = github_pr_followup.get("checked_prs")
        counts = github_pr_followup.get("counts")
        details: list[str] = []
        if isinstance(checked, int):
            details.append(f"{checked} PRs checked")
        if isinstance(counts, dict):
            details.extend(
                f"{_bounded_text(status, limit=40)}={count}"
                for status, count in sorted(counts.items())
                if isinstance(count, int)
            )
        suffix = f" ({', '.join(details)})" if details else ""
        return _bounded_text(
            f"Scheduled project review completed{suffix}.",
            limit=PROJECT_CONDUCTOR_EVENT_CONTENT_MAX_CHARS,
        )

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
        extra: dict[str, object] | None = None,
    ) -> ProjectConductorState:
        event: dict[str, object] = {
            "role": role,
            "content": content,
            "issue_id": issue_id,
            "created_at": datetime.now().isoformat(),
        }
        if extra:
            event.update(extra)
        return await self._mutate_state(events=[event])

    async def _mutate_state(
        self,
        *,
        events: list[dict[str, object]],
        task_increment: int = 0,
    ) -> ProjectConductorState:
        for _attempt in range(PROJECT_CONDUCTOR_STATE_WRITE_RETRIES):
            state = await self.get_or_create_state()
            for event in events:
                await self._append_hot_without_compaction(state, event)
            state.total_tasks_handled += task_increment
            await self._ensure_token_budget(state)
            if await self.store.save_project_conductor_state(state):
                return state
        raise ProjectConductorStateConflictError(
            f"project conductor state remained busy for project {self.project_id}"
        )

    async def answer_question(
        self, question: str, *, state: ProjectConductorState | None = None
    ) -> str:
        state = state or await self.get_or_create_state()
        warm = _parse_memory_list(state.warm_summaries_json, field="warm_summaries_json")
        warm_text = "\n".join(
            f"- {_bounded_text(item.get('summary', item), limit=600)}"
            if isinstance(item, dict)
            else f"- {_bounded_text(item, limit=600)}"
            for item in warm[-5:]
        )
        cold = await self.retrieve_cold(question, top_k=3)
        cold_text = "\n".join(f"- {_bounded_text(item, limit=600)}" for item in cold)
        parts = [
            _LEGACY_ANSWER_PREFIX,
            f"Question: {_bounded_text(question or '(empty question)', limit=PROJECT_CONDUCTOR_INPUT_MAX_CHARS)}",
        ]
        if state.pinned_text:
            parts.append(f"Pinned:\n{_bounded_text(state.pinned_text, limit=2_000)}")
        if warm_text:
            parts.append(f"Warm summaries:\n{warm_text}")
        if cold_text:
            parts.append(f"Relevant cold memory:\n{cold_text}")
        if not any([state.pinned_text, warm_text, cold_text]):
            parts.append("No project memory has been recorded yet.")
        return _bounded_text("\n\n".join(parts), limit=PROJECT_CONDUCTOR_ANSWER_MAX_CHARS)

    async def retrieve_cold(self, query: str, top_k: int = 3) -> list[str]:
        memories = await self.store.list_project_memory_embeddings(
            self.project_id,
            PROJECT_CONDUCTOR_COLD_SEARCH_LIMIT,
            descending=True,
        )
        query_tokens = _tokenize(query)
        ranked: list[tuple[int, str]] = []
        for memory in memories:
            tokens = _tokenize(memory.summary_text)
            score = len(query_tokens & tokens)
            if score or not query_tokens:
                ranked.append((score, memory.summary_text))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [text for _, text in ranked[:top_k]]

    async def list_recent_cold_memories(self) -> list[ProjectMemoryEmbedding]:
        return await self.store.list_project_memory_embeddings(
            self.project_id,
            PROJECT_CONDUCTOR_STATE_COLD_LIMIT + 1,
            descending=True,
        )

    async def count_cold_memories(self) -> int:
        return await self.store.count_project_memory_embeddings(self.project_id)

    async def get_or_create_state(self) -> ProjectConductorState:
        for _attempt in range(PROJECT_CONDUCTOR_STATE_WRITE_RETRIES):
            state = await self.store.load_project_conductor_state(self.project_id)
            if state is not None:
                changed = self._normalize_state(state)
                before_compaction = (
                    state.hot_thread_json,
                    state.warm_summaries_json,
                    state.hot_tokens,
                    state.warm_tokens,
                )
                await self._ensure_token_budget(state)
                changed = changed or before_compaction != (
                    state.hot_thread_json,
                    state.warm_summaries_json,
                    state.hot_tokens,
                    state.warm_tokens,
                )
                if not state.pinned_text:
                    pinned = await self._read_pinned_text()
                    if pinned:
                        state.pinned_text = pinned
                        state.updated_at = datetime.now()
                        changed = True
                if not changed or await self.store.save_project_conductor_state(state):
                    return state
                continue

            pinned = await self._read_pinned_text()
            state = ProjectConductorState(
                project_id=self.project_id,
                pinned_text=pinned,
                updated_at=datetime.now(),
            )
            if await self.store.save_project_conductor_state(state):
                return state
        raise ProjectConductorStateConflictError(
            f"project conductor state remained busy for project {self.project_id}"
        )

    def _normalize_state(self, state: ProjectConductorState) -> bool:
        raw_hot = _parse_memory_list(state.hot_thread_json, field="hot_thread_json")
        hot = [_normalize_hot_event(event) for event in raw_hot]

        raw_warm = _parse_memory_list(state.warm_summaries_json, field="warm_summaries_json")
        warm: list[dict[str, object]] = []
        seen_summaries: set[str] = set()
        for item in raw_warm:
            normalized = _normalize_warm_item(self.project_id, item)
            if normalized is None:
                continue
            summary = str(normalized["summary"])
            if summary in seen_summaries:
                continue
            seen_summaries.add(summary)
            warm.append(normalized)

        hot_json = json.dumps(hot, ensure_ascii=False, default=str)
        warm_json = json.dumps(warm, ensure_ascii=False, default=str)
        hot_tokens = 0 if not hot else estimate_tokens(hot_json)
        warm_tokens = 0 if not warm else estimate_tokens(warm_json)
        changed = (
            state.hot_thread_json != hot_json
            or state.warm_summaries_json != warm_json
            or state.hot_tokens != hot_tokens
            or state.warm_tokens != warm_tokens
        )
        if changed:
            state.hot_thread_json = hot_json
            state.warm_summaries_json = warm_json
            state.hot_tokens = hot_tokens
            state.warm_tokens = warm_tokens
            state.updated_at = datetime.now()
        return changed

    async def _read_pinned_text(self) -> str:
        project = await self.store.load_project(self.project_id)
        if project is None:
            return ""
        path = Path(project.repo_path) / ".agent-collab" / "team_notes.md"
        try:
            return path.read_text(encoding="utf-8")[:2_000]
        except OSError:
            return ""

    async def _append_hot_without_compaction(
        self, state: ProjectConductorState, event: dict[str, object]
    ) -> None:
        hot = _parse_memory_list(state.hot_thread_json, field="hot_thread_json")
        hot.append(_normalize_hot_event(event))
        state.hot_thread_json = json.dumps(hot, ensure_ascii=False, default=str)
        state.hot_tokens = 0 if not hot else estimate_tokens(state.hot_thread_json)
        state.updated_at = datetime.now()

    async def _ensure_token_budget(self, state: ProjectConductorState) -> None:
        self._normalize_state(state)
        hot = _parse_memory_list(state.hot_thread_json, field="hot_thread_json")
        if len(hot) > PROJECT_CONDUCTOR_HOT_EVENT_LIMIT or state.hot_tokens > self.hot_token_limit:
            await self._compact_hot_to_warm(state)
        warm = _parse_memory_list(state.warm_summaries_json, field="warm_summaries_json")
        if (
            len(warm) > PROJECT_CONDUCTOR_WARM_SUMMARY_LIMIT
            or state.warm_tokens > self.warm_token_limit
        ):
            await self._compact_warm_to_cold(state)

    async def _compact_hot_to_warm(self, state: ProjectConductorState) -> None:
        hot = _parse_memory_list(state.hot_thread_json, field="hot_thread_json")
        if not hot:
            return
        compact_count = _prefix_count_to_compact(
            hot,
            count_limit=PROJECT_CONDUCTOR_HOT_EVENT_LIMIT,
            token_limit=self.hot_token_limit,
        )
        if compact_count == 0:
            return
        compacted_hot = hot[:compact_count]
        retained_hot = hot[compact_count:]
        summary = self._summarize_events(compacted_hot)
        warm = _parse_memory_list(state.warm_summaries_json, field="warm_summaries_json")
        if summary:
            warm.append(
                {
                    "id": str(
                        uuid5(
                            NAMESPACE_URL,
                            f"project-conductor-warm:{self.project_id}:{summary}",
                        )
                    ),
                    "summary": summary,
                    "event_count": len(compacted_hot),
                    "created_at": datetime.now().isoformat(),
                }
            )
        state.hot_thread_json = json.dumps(retained_hot, ensure_ascii=False, default=str)
        state.hot_tokens = 0 if not retained_hot else estimate_tokens(state.hot_thread_json)
        state.warm_summaries_json = json.dumps(warm, ensure_ascii=False)
        state.warm_tokens = 0 if not warm else estimate_tokens(state.warm_summaries_json)
        state.last_compaction_at = datetime.now()
        state.updated_at = state.last_compaction_at

    async def _compact_warm_to_cold(self, state: ProjectConductorState) -> None:
        warm = _parse_memory_list(state.warm_summaries_json, field="warm_summaries_json")
        if not warm:
            return
        compact_count = _prefix_count_to_compact(
            warm,
            count_limit=PROJECT_CONDUCTOR_WARM_SUMMARY_LIMIT,
            token_limit=self.warm_token_limit,
        )
        if compact_count == 0:
            return
        compacted_warm = warm[:compact_count]
        retained_warm = warm[compact_count:]
        existing = await self.store.list_project_memory_embeddings(
            self.project_id,
            PROJECT_CONDUCTOR_COLD_SEARCH_LIMIT,
            descending=True,
        )
        existing_summaries = {memory.summary_text for memory in existing}
        for item in compacted_warm:
            normalized = _normalize_warm_item(self.project_id, item)
            if normalized is None:
                continue
            summary = str(normalized["summary"])
            source_id = str(normalized["id"])
            if summary in existing_summaries:
                continue
            memory = ProjectMemoryEmbedding(
                id=str(
                    uuid5(
                        NAMESPACE_URL,
                        f"project-conductor-cold:{self.project_id}:warm_summary:{source_id}",
                    )
                ),
                project_id=self.project_id,
                source_kind="warm_summary",
                source_id=source_id,
                summary_text=summary,
                vector_json="[]",
                created_at=datetime.now(),
            )
            await self.store.save_project_memory_embedding(memory)
            existing_summaries.add(summary)
        state.warm_summaries_json = json.dumps(retained_warm, ensure_ascii=False)
        state.warm_tokens = 0 if not retained_warm else estimate_tokens(state.warm_summaries_json)
        state.last_compaction_at = datetime.now()
        state.updated_at = state.last_compaction_at

    @staticmethod
    def _summarize_events(events: list[object]) -> str:
        fragments: list[str] = []
        seen: set[str] = set()
        for event in events:
            normalized = _normalize_hot_event(event)
            role = normalized["role"]
            content = _bounded_text(normalized["content"], limit=320)
            fragment = f"{role}: {content}".strip()
            if not content or fragment in seen:
                continue
            seen.add(fragment)
            fragments.append(fragment)
        return _bounded_text(
            " | ".join(fragments),
            limit=PROJECT_CONDUCTOR_SUMMARY_MAX_CHARS,
        )
