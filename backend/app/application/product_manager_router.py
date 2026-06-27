from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.application.product_manager_documents import ProductManagerDocuments


@dataclass(frozen=True)
class RequirementRoute:
    name: str
    issue_root: Path
    requirement_path: Path
    existing_prd_path: Path | None = None


class ProductManagerRouter:
    BUGFIX_TOKENS = ("bug", "broken", "fix", "regression", "error", "failed")

    def __init__(self, documents: ProductManagerDocuments | None = None):
        self.documents = documents or ProductManagerDocuments()

    def route_requirement(
        self, *, prompt: str, workspace_path: str, issue_id: str
    ) -> RequirementRoute:
        issue_root = self.documents.ensure_issue_root(workspace_path, issue_id)
        requirement_path = self.documents.requirement_path(workspace_path, issue_id)
        existing_prd_files = self.documents.find_issue_prd_files(workspace_path, issue_id)
        existing_prd_path = existing_prd_files[0] if existing_prd_files else None
        lowered = (prompt or "").lower()
        if any(token in lowered for token in self.BUGFIX_TOKENS):
            return RequirementRoute(
                name="bugfix",
                issue_root=issue_root,
                requirement_path=requirement_path,
                existing_prd_path=existing_prd_path,
            )
        if existing_prd_path is not None:
            return RequirementRoute(
                name="requirement_update",
                issue_root=issue_root,
                requirement_path=requirement_path,
                existing_prd_path=existing_prd_path,
            )
        return RequirementRoute(
            name="new_requirement",
            issue_root=issue_root,
            requirement_path=requirement_path,
            existing_prd_path=None,
        )
