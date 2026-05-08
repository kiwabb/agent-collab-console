from __future__ import annotations

from pathlib import Path

from app.application.issue_artifact_documents import IssueArtifactDocuments


class ProductManagerDocuments:
    """Delegates to IssueArtifactDocuments for shared path logic.

    Kept as a separate class to preserve the existing public API
    (requirement_path, bugfix_path, prd_json_path, prd_md_path,
    find_issue_prd_files) for backward compatibility with existing code.
    """

    def __init__(self) -> None:
        self._shared = IssueArtifactDocuments()

    def issue_root(self, workspace_path: str, issue_id: str) -> Path:
        return self._shared.issue_root(workspace_path, issue_id)

    def ensure_issue_root(self, workspace_path: str, issue_id: str) -> Path:
        return self._shared.ensure_issue_root(workspace_path, issue_id)

    def requirement_path(self, workspace_path: str, issue_id: str) -> Path:
        return self._shared.pm_requirement_path(workspace_path, issue_id)

    def bugfix_path(self, workspace_path: str, issue_id: str) -> Path:
        return self._shared.pm_bugfix_path(workspace_path, issue_id)

    def prd_json_path(self, workspace_path: str, issue_id: str) -> Path:
        return self._shared.pm_prd_json_path(workspace_path, issue_id)

    def prd_md_path(self, workspace_path: str, issue_id: str) -> Path:
        return self._shared.pm_prd_md_path(workspace_path, issue_id)

    def find_issue_prd_files(self, workspace_path: str, issue_id: str) -> list[Path]:
        return self._shared.pm_find_prd_files(workspace_path, issue_id)
