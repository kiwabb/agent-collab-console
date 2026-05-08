from __future__ import annotations

from app.application.architect_workflow import ArchitectWorkflow
from app.application.engineer_workflow import EngineerWorkflow
from app.application.product_manager_service import ProductManagerService
from app.application.qa_workflow import QAWorkflow


MANAGED_ROLES = frozenset({"product_manager", "architect", "engineer", "qa"})


class RoleWorkflowService:
    """Dispatches role-specific prompt building and result persistence."""

    def __init__(self) -> None:
        self._pm_service = ProductManagerService()
        self._architect_service = ArchitectWorkflow()
        self._engineer_service = EngineerWorkflow()
        self._qa_service = QAWorkflow()

    def is_managed_role(self, role: str) -> bool:
        return role in MANAGED_ROLES

    def build_prompt(self, task, workspace_title: str | None = None) -> str | None:
        """Build a managed role prompt. Returns None for unmanaged roles."""
        role = getattr(task, "role", None)
        if role == "product_manager":
            return self._pm_service.build_prompt(task, workspace_title)
        if role == "architect":
            return self._architect_service.build_prompt(task, workspace_title)
        if role == "engineer":
            return self._engineer_service.build_prompt(task, workspace_title)
        if role == "qa":
            return self._qa_service.build_prompt(task, workspace_title)
        # general — handled in later steps
        return None

    def persist_result(self, task, workspace_title: str | None = None) -> any:
        """Persist artifacts for a completed managed role task. No-op for unmanaged roles."""
        role = getattr(task, "role", None)
        if role == "product_manager":
            return self._pm_service.persist_prd_from_result(task, workspace_title)
        elif role == "architect":
            return self._architect_service.persist_result(task, workspace_title)
        elif role == "engineer":
            return self._engineer_service.persist_result(task, workspace_title)
        elif role == "qa":
            return self._qa_service.persist_result(task, workspace_title)
        return None
