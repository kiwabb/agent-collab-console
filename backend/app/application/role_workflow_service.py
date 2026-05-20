from __future__ import annotations

from datetime import datetime

from app.application.architect_workflow import ArchitectWorkflow
from app.application.clarification import (
    CLARIFICATION_PROMPT_INSTRUCTION,
    apply_clarification_if_needed,
)
from app.application.engineer_workflow import EngineerWorkflow
from app.application.product_manager_service import ProductManagerService
from app.application.project_memory_service import project_memory
from app.application.qa_workflow import QAWorkflow


ENGINEER_ROLES = frozenset({"engineer", "engineer_frontend", "engineer_backend"})
MANAGED_ROLES = frozenset({"product_manager", "architect", "qa"}) | ENGINEER_ROLES


class RoleWorkflowService:
    """Dispatches role-specific prompt building and result persistence."""

    def __init__(self, codex_store=None) -> None:
        self._pm_service = ProductManagerService()
        self._architect_service = ArchitectWorkflow()
        self._engineer_service = EngineerWorkflow()
        self._qa_service = QAWorkflow()
        self.codex_store = codex_store

    def is_managed_role(self, role: str) -> bool:
        return role in MANAGED_ROLES

    async def build_prompt(
        self,
        task,
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
        role = getattr(task, "role", None)
        if role == "product_manager":
            base = self._pm_service.build_prompt(task, workspace_title)
        elif role == "architect":
            base = self._architect_service.build_prompt(task, workspace_title)
        elif role in ENGINEER_ROLES:
            # All engineer variants share the same workflow; scope hint
            # (frontend/backend only) is added inside EngineerWorkflow
            # based on task.role.
            base = self._engineer_service.build_prompt(task, workspace_title)
        elif role == "qa":
            base = self._qa_service.build_prompt(task, workspace_title)
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
        project_id = getattr(task, "project_id", None)
        if project_id and self.codex_store is not None:
            try:
                from app.application.team_notes_service import team_notes
                memory_text = await team_notes.format_for_prompt(
                    self.codex_store, project_id, project_repo_path
                )
            except Exception:  # noqa: BLE001
                memory_text = None
        if not memory_text:
            memory_text = project_memory.read_for_prompt(project_repo_path)
        if memory_text:
            return project_memory.format_for_prompt(memory_text) + "\n" + prompt_with_escape
        return prompt_with_escape

    @staticmethod
    def _read_steer_notes(task) -> str | None:
        workspace_path = getattr(task, "workspace_path", None)
        issue_id = getattr(task, "issue_id", None)
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

    async def persist_result(self, task, workspace_title: str | None = None) -> any:
        """Persist artifacts for a completed managed role task. No-op for unmanaged roles."""
        role = getattr(task, "role", None)
        doc = None
        if role == "product_manager":
            doc = self._pm_service.persist_prd_from_result(task, workspace_title)
        elif role == "architect":
            doc = self._architect_service.persist_result(task, workspace_title)
        elif role in ENGINEER_ROLES:
            doc = self._engineer_service.persist_result(task, workspace_title)
        elif role == "qa":
            doc = self._qa_service.persist_result(task, workspace_title)

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

        # If store is available and document has written_files, persist to DB
        if self.codex_store and doc and hasattr(doc, "written_files"):
            import asyncio
            from app.application import knowledge_index_service
            from app.application.embedding_service import get_embedding_service

            for f in doc.written_files:
                artifact_row = {
                    "id": f"{task.issue_id}:{f['name']}",
                    "issue_id": task.issue_id,
                    "task_id": task.id,
                    "name": f["name"],
                    "path": f["path"],
                    "kind": f["kind"],
                    "created_at": datetime.now().isoformat(),
                }
                await self.codex_store.save_artifact(artifact_row)
                # FTS index: synchronous in-band (cheap).
                try:
                    await knowledge_index_service.index_artifact(self.codex_store, artifact_row)
                except Exception:  # noqa: BLE001
                    pass
                # Embedding: fire-and-forget, never blocks the task.
                emb = get_embedding_service()
                if emb.enabled:
                    async def _embed(row=artifact_row, emb=emb):
                        try:
                            text = knowledge_index_service._read_artifact_text(row.get("path"))
                            if not text:
                                return
                            vec = await emb.embed_one(text[:8000])
                            if vec:
                                await knowledge_index_service.store_artifact_embedding(
                                    self.codex_store, row["id"], vec, emb.model_label
                                )
                        except Exception:  # noqa: BLE001
                            pass
                    asyncio.create_task(_embed())

        return doc

    async def _record_critique(self, task, critique: str) -> None:
        """Persist an Engineer→Architect critique as an AgentMessage and emit the bus event."""
        if not self.codex_store:
            return
        try:
            from uuid import uuid4
            from datetime import datetime
            from app.domain.models import AgentMessage
            from app.application.event_bus import event_bus

            # Look up the graph so we can attach graph_id.
            graph = None
            if hasattr(self.codex_store, "load_workflow_graph_for_issue"):
                graph = await self.codex_store.load_workflow_graph_for_issue(task.issue_id)

            msg = AgentMessage(
                id=str(uuid4()),
                issue_id=task.issue_id,
                graph_id=graph.id if graph else "",
                from_node_key=getattr(task, "role", "engineer"),
                to_node_key="architect",
                message_type="critique",
                body=critique,
                created_at=datetime.now(),
            )
            await self.codex_store.save_agent_message(msg)
            await event_bus.append({
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
            })
        except Exception as exc:  # noqa: BLE001
            import logging
            logging.getLogger(__name__).warning("_record_critique failed: %s", exc)
