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


MANAGED_ROLES = frozenset({"product_manager", "architect", "engineer", "qa"})


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

    def build_prompt(
        self,
        task,
        workspace_title: str | None = None,
        project_repo_path: str | None = None,
    ) -> str | None:
        """Build a managed role prompt. Returns None for unmanaged roles.

        If ``project_repo_path`` is supplied AND a team_notes.md memory file
        exists for that project, the prompt is prepended with a TEAM CONTEXT
        block so every role gets the lessons accumulated from prior issues.

        If the issue's worktree carries a `_steer.md`, those mid-run hints
        (written via POST /codex/issues/{id}/steer) are injected at the top
        so they win against any other context.
        """
        role = getattr(task, "role", None)
        if role == "product_manager":
            base = self._pm_service.build_prompt(task, workspace_title)
        elif role == "architect":
            base = self._architect_service.build_prompt(task, workspace_title)
        elif role == "engineer":
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
        elif role == "engineer":
            doc = self._engineer_service.persist_result(task, workspace_title)
        elif role == "qa":
            doc = self._qa_service.persist_result(task, workspace_title)

        # P2: clarification flow. If the role surfaced a critical question,
        # transition the task into awaiting_review with the question text,
        # so the scheduler pauses and the Approvals UI surfaces it.
        if doc is not None:
            apply_clarification_if_needed(task, doc)

        # If store is available and document has written_files, persist to DB
        if self.codex_store and doc and hasattr(doc, "written_files"):
            for f in doc.written_files:
                await self.codex_store.save_artifact({
                    "id": f"{task.issue_id}:{f['name']}",
                    "issue_id": task.issue_id,
                    "task_id": task.id,
                    "name": f["name"],
                    "path": f["path"],
                    "kind": f["kind"],
                    "created_at": datetime.now().isoformat(),
                })

        return doc
