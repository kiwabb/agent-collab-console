from __future__ import annotations  # noqa: I001

import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Protocol

from app.application.architect_workflow import ArchitectWorkflow
from app.application.clarification import (
    CLARIFICATION_PROMPT_INSTRUCTION,
    apply_clarification_if_needed,
)
from app.application.engineer_workflow import EngineerWorkflow
from app.application.agent_catalog.generic_specialist_workflow import GenericSpecialistWorkflow
from app.application.product_manager_service import ProductManagerService
from app.application.project_memory_service import project_memory
from app.application.qa_workflow import QAWorkflow
from app.application.specialist_requests import SpecialistCallRequest
from app.application.knowledge_index_service import KnowledgeStore
from app.application.specialist_orchestrator import SpecialistStore
from app.application.team_notes_service import TeamNotesStore

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.application.embedding_service import EmbeddingService
    from app.application.knowledge_index_service import ArtifactRow
    from app.application.project_script_suggestions import ProjectScriptSuggestion
    from app.domain.models import CodexTask, Project


class RoleWorkflowStore(KnowledgeStore, SpecialistStore, TeamNotesStore, Protocol):
    async def save_artifact(self, artifact: ArtifactRow) -> None: ...

    async def load_project(self, project_id: str) -> Project | None: ...

    async def save_project(self, project: Project) -> None: ...

ENGINEER_ROLES = frozenset({"engineer", "engineer_frontend", "engineer_backend"})
OPERATIONS_ROLES = frozenset({"operations_engineer"})
MANAGED_ROLES = frozenset({"product_manager", "architect", "qa"}) | ENGINEER_ROLES | OPERATIONS_ROLES


class RoleWorkflowService:
    """Dispatches role-specific prompt building and result persistence."""

    def __init__(self, codex_store: RoleWorkflowStore | None = None) -> None:
        self._pm_service = ProductManagerService()
        self._architect_service = ArchitectWorkflow()
        self._engineer_service = EngineerWorkflow()
        self._qa_service = QAWorkflow()
        self._specialist_service = GenericSpecialistWorkflow()
        self.codex_store = codex_store

    def is_managed_role(self, role: str | None) -> bool:
        return role in MANAGED_ROLES or self._is_specialist_role(role)

    async def build_prompt(
        self,
        task: CodexTask,
        workspace_title: str | None = None,
        project_repo_path: str | None = None,
    ) -> str | None:
        """Build a managed role prompt. Returns None for unmanaged roles.

        If ``project_repo_path`` is supplied AND a team_notes.md memory file
        exists for that project, the prompt is prepended with a TEAM CONTEXT
        block so every role gets the lessons accumulated from prior issues.
        Soft-deleted blocks (via team_notes_state) are filtered out.

        If the issue's worktree carries a `_steer.md`, those mid-run hints
        (written via POST /codex/issues/{id}/steer) are injected at the top
        so they win against any other context.
        """
        role = task.role
        if role == "product_manager":
            base = self._pm_service.build_prompt(task, workspace_title)
        elif role == "architect":
            base = self._architect_service.build_prompt(task, workspace_title)
        elif role == "operations_engineer":
            base = await self._build_operations_engineer_prompt(task)
        elif role in ENGINEER_ROLES:
            # All engineer-like variants share the same workflow; scope hint
            # (frontend/backend only) is added inside EngineerWorkflow
            # based on task.role.
            base = self._engineer_service.build_prompt(task, workspace_title)
        elif role == "qa":
            base = self._qa_service.build_prompt(task, workspace_title)
        elif self._is_specialist_role(role):
            base = self._specialist_service.build_prompt(task, workspace_title)
        else:
            return None  # general — handled elsewhere

        # Always tell every role about the clarification escape hatch so it
        # has a structured way to ask a question instead of guessing.
        prompt_with_escape = CLARIFICATION_PROMPT_INSTRUCTION + "\n" + base

        # Layer steer notes on top of the prompt — they're user overrides
        # so they win against accumulated team_notes context.
        steer_text = self._read_steer_notes(task)
        if steer_text:
            prompt_with_escape = self._format_steer(steer_text) + "\n" + prompt_with_escape

        memory_text = None
        project_id = task.project_id
        if project_id and self.codex_store is not None:
            try:
                from app.application.team_notes_service import team_notes

                memory_text = await team_notes.format_for_prompt(
                    self.codex_store, project_id, project_repo_path
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "team notes prompt context unavailable: project_id=%s error=%s",
                    project_id,
                    exc,
                )
        if not memory_text:
            memory_text = project_memory.read_for_prompt(project_repo_path)
        prompt_text = str(prompt_with_escape)
        if memory_text:
            return str(project_memory.format_for_prompt(memory_text)) + "\n" + prompt_text
        return prompt_text

    @staticmethod
    def _read_steer_notes(task: CodexTask) -> str | None:
        workspace_path = task.workspace_path
        issue_id = task.issue_id
        if not workspace_path or not issue_id:
            return None
        from pathlib import Path

        p = Path(workspace_path) / "issues" / issue_id / "_steer.md"
        if not p.exists():
            return None
        try:
            content = p.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return content or None

    @staticmethod
    def _format_steer(text: str) -> str:
        return (
            "USER STEER NOTES — read first, apply with high priority:\n"
            "---\n"
            f"{text}\n"
            "---\n"
            "These are mid-flight corrections from the user. Treat them as authoritative; "
            "they override prior assumptions, the PRD, and team_notes if they conflict.\n"
        )

    async def persist_result(
        self,
        task: CodexTask,
        workspace_title: str | None = None,
    ) -> object | None:
        """Persist artifacts for a completed managed role task. No-op for unmanaged roles."""
        role = task.role
        doc: object | None = None
        if role == "product_manager":
            doc = self._pm_service.persist_prd_from_result(task, workspace_title)
        elif role == "architect":
            doc = self._architect_service.persist_result(task, workspace_title)
        elif role == "operations_engineer":
            doc = await self._persist_operations_engineer_result(task)
        elif role in ENGINEER_ROLES:
            doc = self._engineer_service.persist_result(task, workspace_title)
        elif role == "qa":
            doc = self._qa_service.persist_result(task, workspace_title)
        elif self._is_specialist_role(role):
            doc = self._specialist_service.persist_result(task, workspace_title)

        # P2: clarification flow. If the role surfaced a critical question,
        # transition the task into awaiting_review with the question text,
        # so the scheduler pauses and the Approvals UI surfaces it.
        if doc is not None:
            apply_clarification_if_needed(task, doc)

        # Phase 2: peer critique flow. If an Engineer surfaced an architect_critique,
        # persist it as an AgentMessage and let the scheduler handle resetting Architect.
        if doc is not None and role in ENGINEER_ROLES:
            critique = getattr(doc, "architect_critique", None)
            if critique and isinstance(critique, str) and critique.strip():
                await self._record_critique(task, critique.strip())

        # Phase 4: specialist mesh call. If Engineer/QA set call_specialist, spawn a specialist child.
        # The scheduler will handle pausing parent, running specialist, and resuming parent.
        if doc is not None and role in (ENGINEER_ROLES | {"qa"}):
            call_specialist = getattr(doc, "call_specialist", None)
            if isinstance(call_specialist, SpecialistCallRequest):
                await self._request_specialist(
                    task,
                    call_specialist.role_key,
                    call_specialist.prompt,
                    call_specialist.why,
                )
            elif call_specialist and isinstance(call_specialist, dict):
                specialist_role_key = call_specialist.get("role_key")
                specialist_prompt = call_specialist.get("prompt")
                why = call_specialist.get("why", "")
                if isinstance(specialist_role_key, str) and isinstance(specialist_prompt, str):
                    await self._request_specialist(
                        task,
                        specialist_role_key,
                        specialist_prompt,
                        why if isinstance(why, str) else "",
                    )

        # If store is available and document has written_files, persist to DB
        written_files = getattr(doc, "written_files", None) if doc is not None else None
        store = self.codex_store
        if store and doc and isinstance(written_files, list):
            import asyncio  # noqa: I001
            from app.application import knowledge_index_service
            from app.application.embedding_service import get_embedding_service

            for f in written_files:
                if not isinstance(f, dict):
                    continue
                name = f.get("name")
                path = f.get("path")
                kind = f.get("kind")
                if not isinstance(name, str) or not isinstance(path, str):
                    continue
                artifact_row: ArtifactRow = {
                    "id": f"{task.issue_id}:{name}",
                    "issue_id": task.issue_id,
                    "task_id": task.id,
                    "name": name,
                    "path": path,
                    "kind": kind if isinstance(kind, str) else "",
                    "created_at": datetime.now().isoformat(),
                }
                await store.save_artifact(artifact_row)
                # FTS index: synchronous in-band (cheap).
                try:
                    await knowledge_index_service.index_artifact(store, artifact_row)
                except Exception as exc:
                    import logging

                    logging.getLogger(__name__).warning(
                        "Failed to index artifact %s for task_id=%s: %s",
                        artifact_row["id"],
                        task.id,
                        exc,
                    )
                # Embedding: fire-and-forget, never blocks the task.
                emb = get_embedding_service()
                if emb.enabled:

                    async def _embed(
                        row: ArtifactRow = artifact_row,
                        emb: EmbeddingService = emb,
                    ) -> None:
                        try:
                            path_value = row.get("path")
                            text = knowledge_index_service._read_artifact_text(
                                path_value if isinstance(path_value, str) else None
                            )
                            if not text:
                                return
                            vec = await emb.embed_one(text[:8000])
                            if vec:
                                artifact_id = row.get("id")
                                if not isinstance(artifact_id, str):
                                    return
                                await knowledge_index_service.store_artifact_embedding(
                                    store, artifact_id, vec, emb.model_label
                                )
                        except Exception:  # noqa: BLE001, RUF100
                            logger.debug("artifact embedding side task failed", exc_info=True)

                    asyncio.create_task(_embed())  # noqa: RUF006

        return doc

    @staticmethod
    def _is_specialist_role(role: str | None) -> bool:
        return bool(role and (role.startswith("specialist:") or role.startswith("custom:")))

    async def _record_critique(self, task: CodexTask, critique: str) -> None:
        """Persist an Engineer→Architect critique as an AgentMessage and emit the bus event."""
        if not self.codex_store or not task.issue_id:
            return
        try:
            from uuid import uuid4  # noqa: I001
            from datetime import datetime
            from app.domain.models import AgentMessage
            from app.application.event_bus import event_bus

            # Look up the graph so we can attach graph_id.
            graph = await self.codex_store.load_workflow_graph_for_issue(task.issue_id)

            msg = AgentMessage(
                id=str(uuid4()),
                issue_id=task.issue_id,
                graph_id=graph.id if graph else "",
                from_node_key=task.role,
                to_node_key="architect",
                message_type="critique",
                body=critique,
                created_at=datetime.now(),
            )
            await self.codex_store.save_agent_message(msg)
            await event_bus.append(
                {
                    "type": "agent_message_posted",
                    "issue_id": task.issue_id,
                    "session_id": task.session_id,
                    "workspace_id": task.session_id,
                    "message": {
                        "id": msg.id,
                        "issue_id": msg.issue_id,
                        "graph_id": msg.graph_id,
                        "from_node_key": msg.from_node_key,
                        "to_node_key": msg.to_node_key,
                        "message_type": msg.message_type,
                        "body": msg.body,
                        "created_at": msg.created_at.isoformat() if msg.created_at else None,
                    },
                }
            )
        except Exception as exc:  # noqa: BLE001, RUF100
            logger.warning("_record_critique failed: %s", exc)

    async def _request_specialist(
        self,
        task: CodexTask,
        specialist_role_key: str,
        specialist_prompt: str,
        why: str,
    ) -> None:
        """Phase 4: Request specialist help from Engineer/QA task."""
        if not self.codex_store:
            raise RuntimeError("Cannot request specialist without a codex store")
        try:
            from app.application.event_bus import event_bus
            from app.application.specialist_orchestrator import SpecialistOrchestrator
            from app.bootstrap import get_task_runner

            async def _noop_refresh(_task: CodexTask) -> object | None:
                return None

            orchestrator = SpecialistOrchestrator(
                self.codex_store,
                event_bus,
                get_task_runner(_noop_refresh),
            )
            await orchestrator.request_specialist(
                parent_task=task,
                specialist_role_key=specialist_role_key,
                specialist_prompt=specialist_prompt,
                why=why,
            )
        except Exception as exc:  # noqa: BLE001, RUF100
            logger.warning("_request_specialist setup failed: %s", exc)
            raise

    async def _build_operations_engineer_prompt(self, task: CodexTask) -> str:
        project_id = task.project_id
        if not self.codex_store or not project_id:
            return self._fallback_operations_prompt(task)
        try:
            project = await self.codex_store.load_project(project_id)
        except Exception:  # noqa: BLE001, RUF100
            project = None
        if project is None:
            return self._fallback_operations_prompt(task)
        try:
            from app.application.project_script_suggestions import (
                build_project_script_suggestion_prompt,
                collect_project_script_context,
            )

            repo_context = collect_project_script_context(project.repo_path)
            request_context = self._read_operations_request_context(task)
            return str(
                build_project_script_suggestion_prompt(
                    project=project,
                    repo_context=repo_context,
                    existing_setup_script=request_context.get("setup_script", project.setup_script),
                    existing_run_command=request_context.get("run_command", project.run_command),
                )
            )
        except Exception:  # noqa: BLE001, RUF100
            return self._fallback_operations_prompt(task)

    @staticmethod
    def _read_operations_request_context(task: CodexTask) -> dict[str, str]:
        prompt = task.prompt or ""
        marker = "Operations request context JSON:"
        if marker not in prompt:
            return RoleWorkflowService._read_legacy_operations_request_context(prompt)
        raw = prompt.split(marker, 1)[1].strip()
        try:
            parsed, _ = json.JSONDecoder().raw_decode(raw)
        except (json.JSONDecodeError, TypeError):
            return RoleWorkflowService._read_legacy_operations_request_context(prompt)
        if not isinstance(parsed, dict):
            return RoleWorkflowService._read_legacy_operations_request_context(prompt)
        out: dict[str, str] = {}
        for key in ("setup_script", "run_command"):
            value = parsed.get(key)
            if isinstance(value, str):
                out[key] = value
        return out

    @staticmethod
    def _read_legacy_operations_request_context(prompt: str) -> dict[str, str]:
        out: dict[str, str] = {}
        lines = prompt.splitlines()
        prefixes = {
            "Existing setup_script:": "setup_script",
            "Existing run_command:": "run_command",
        }
        for line in lines:
            for prefix, key in prefixes.items():
                if line.startswith(prefix):
                    value = line.removeprefix(prefix).strip()
                    out[key] = "" if value == "(empty)" else value
        return out

    @staticmethod
    def _fallback_operations_prompt(task: CodexTask) -> str:
        return (
            "You are an Operations Engineer. Inspect the current project and output exactly one "
            "raw JSON object with this schema:\n"
            '{"setup_script":"one-time setup command(s), or empty string",'
            '"run_command":"long-running local dev command, or empty string",'
            '"access_url":"local URL or null","notes":["short note"]}\n'
            "Do not wrap the JSON in markdown. Do not add extra prose.\n\n"
            f"User/project request:\n{task.prompt or ''}"
        )

    async def _persist_operations_engineer_result(
        self, task: CodexTask
    ) -> ProjectScriptSuggestion:
        from app.application.project_script_suggestions import parse_project_script_suggestion

        raw_result = task.result or ""
        suggestion = parse_project_script_suggestion(raw_result) if raw_result.strip() else None
        if suggestion is None:
            from app.application.project_script_suggestions import infer_project_script_suggestion

            workspace_path = task.workspace_path
            suggestion = infer_project_script_suggestion(workspace_path) if workspace_path else None
        if suggestion is None:
            raise ValueError("Operations Engineer could not produce a project script suggestion")

        project_id = task.project_id
        if self.codex_store and project_id:
            project = await self.codex_store.load_project(project_id)
            if project is not None:
                suggestion = suggestion.model_copy(
                    update={
                        "setup_script": suggestion.setup_script or (project.setup_script or ""),
                        "run_command": suggestion.run_command or (project.run_command or ""),
                    }
                )
                project.setup_script = suggestion.setup_script
                project.run_command = suggestion.run_command
                project.updated_at = datetime.now()
                await self.codex_store.save_project(project)
                try:
                    from app.application.event_bus import event_bus

                    await event_bus.append(
                        {
                            "type": "project_updated",
                            "project_id": project.id,
                            "session_id": project.id,
                            "project": {
                                "id": project.id,
                                "name": project.name,
                                "repo_path": project.repo_path,
                                "default_branch": project.default_branch,
                                "origin_url": project.origin_url,
                                "setup_script": project.setup_script,
                                "run_command": project.run_command,
                                "created_at": (
                                    project.created_at.isoformat()
                                    if project.created_at
                                    else None
                                ),
                                "updated_at": (
                                    project.updated_at.isoformat()
                                    if project.updated_at
                                    else None
                                ),
                            },
                            "setup_script": project.setup_script,
                            "run_command": project.run_command,
                        }
                    )
                    await event_bus.append(
                        {
                            "type": "project_script_updated",
                            "project_id": project.id,
                            "session_id": project.id,
                            "task_id": task.id,
                            "role": task.role,
                            "task_kind": task.task_kind,
                            "execution_process_id": task.last_execution_process_id,
                            "trace_id": task.trace_id,
                            "span_id": task.span_id,
                            "parent_span_id": task.parent_span_id,
                            "setup_script": project.setup_script,
                            "run_command": project.run_command,
                        }
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("project script update events failed: %s", exc, exc_info=True)
        task.result = suggestion.model_dump_json()
        note_lines = [
            "[OPERATIONS SCRIPT UPDATED]",
            f"setup_script: {suggestion.setup_script or '(empty)'}",
            f"run_command: {suggestion.run_command or '(empty)'}",
        ]
        if suggestion.access_url:
            note_lines.append(f"access_url: {suggestion.access_url}")
        if suggestion.notes:
            note_lines.append("notes:")
            note_lines.extend(f"- {note}" for note in suggestion.notes)
        task.review_comment = "\n".join(note_lines)
        task.updated_at = datetime.now()
        if self.codex_store:
            await self.codex_store.save_codex_task(task)
        return suggestion
