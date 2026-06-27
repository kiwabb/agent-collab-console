from __future__ import annotations

import tempfile
from pathlib import Path


class IssueArtifactDocuments:
    """Shared issue artifact path helpers for all managed roles.

    Artifacts live under: <workspace_path>/issues/<issue_id>/
    """

    # -------------------------------------------------------------------------
    # Root helpers
    # -------------------------------------------------------------------------

    def issue_root(self, workspace_path: str | None, issue_id: str) -> Path:
        # When the issue has no git worktree yet, fall back to a temp dir so
        # artifact reads return empty (path won't exist) without crashing.
        base = workspace_path if workspace_path else tempfile.gettempdir()
        return Path(base) / "issues" / issue_id

    def ensure_issue_root(self, workspace_path: str, issue_id: str) -> Path:
        issue_root = self.issue_root(workspace_path, issue_id)
        issue_root.mkdir(parents=True, exist_ok=True)
        return issue_root

    # -------------------------------------------------------------------------
    # Product Manager artifacts
    # -------------------------------------------------------------------------

    def pm_requirement_path(self, workspace_path: str, issue_id: str) -> Path:
        p = self.issue_root(workspace_path, issue_id) / "pm" / "requirement.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def pm_bugfix_path(self, workspace_path: str, issue_id: str) -> Path:
        p = self.issue_root(workspace_path, issue_id) / "pm" / "bugfix.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def pm_prd_json_path(self, workspace_path: str, issue_id: str) -> Path:
        p = self.issue_root(workspace_path, issue_id) / "pm" / "prd.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def pm_prd_md_path(self, workspace_path: str, issue_id: str) -> Path:
        p = self.issue_root(workspace_path, issue_id) / "pm" / "prd.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def pm_find_prd_files(self, workspace_path: str, issue_id: str) -> list[Path]:
        prd_path = self.pm_prd_json_path(workspace_path, issue_id)
        return [prd_path] if prd_path.exists() else []

    # -------------------------------------------------------------------------
    # Architect artifacts
    # -------------------------------------------------------------------------

    def architect_system_design_json_path(self, workspace_path: str, issue_id: str) -> Path:
        p = self.issue_root(workspace_path, issue_id) / "architect" / "system_design.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def architect_system_design_md_path(self, workspace_path: str, issue_id: str) -> Path:
        p = self.issue_root(workspace_path, issue_id) / "architect" / "system_design.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def architect_implementation_plan_path(self, workspace_path: str, issue_id: str) -> Path:
        p = self.issue_root(workspace_path, issue_id) / "architect" / "implementation_plan.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def architect_development_task_list_path(self, workspace_path: str, issue_id: str) -> Path:
        p = self.issue_root(workspace_path, issue_id) / "architect" / "development_task_list.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def architect_find_artifacts(self, workspace_path: str, issue_id: str) -> list[Path]:
        paths = [
            self.architect_system_design_json_path(workspace_path, issue_id),
            self.architect_system_design_md_path(workspace_path, issue_id),
            self.architect_implementation_plan_path(workspace_path, issue_id),
            self.architect_development_task_list_path(workspace_path, issue_id),
        ]
        return [p for p in paths if p.exists()]

    # -------------------------------------------------------------------------
    # Engineer artifacts
    # -------------------------------------------------------------------------

    def engineer_implementation_md_path(
        self,
        workspace_path: str,
        issue_id: str,
        task_id: str | None = None,
        subdir: str = "engineer",
    ) -> Path:
        """Path for an engineer implementation report.

        Phase 1: when two specialist engineers (engineer_frontend +
        engineer_backend) run in parallel, each writes to its own subdir
        (e.g. `engineer_frontend/implementation-<task_id>.md`) so the two
        don't overwrite each other. Default subdir is `engineer` for the
        single-engineer flow.
        """
        if task_id:  # noqa: SIM108
            filename = f"implementation-{task_id}.md"
        else:
            filename = "implementation.md"
        p = self.issue_root(workspace_path, issue_id) / subdir / filename
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def engineer_find_artifacts(self, workspace_path: str, issue_id: str) -> list[Path]:
        """Union of implementation reports across every engineer subdir.

        Scans the legacy `engineer/` directory plus any specialist subdirs
        (`engineer_frontend/`, `engineer_backend/`, ...) so downstream
        consumers (QA prompt, artifact backfill) see the full picture.
        """
        root = self.issue_root(workspace_path, issue_id)
        if not root.exists():
            return []
        artifacts: list[Path] = []
        for subdir in root.iterdir():
            if not subdir.is_dir() or not subdir.name.startswith("engineer"):
                continue
            artifacts.extend(subdir.glob("implementation*.md"))
        return sorted(artifacts)

    # -------------------------------------------------------------------------
    # QA artifacts
    # -------------------------------------------------------------------------

    def qa_plan_json_path(self, workspace_path: str, issue_id: str) -> Path:
        p = self.issue_root(workspace_path, issue_id) / "qa" / "qa_plan.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def qa_report_md_path(self, workspace_path: str, issue_id: str) -> Path:
        p = self.issue_root(workspace_path, issue_id) / "qa" / "qa_report.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def qa_find_artifacts(self, workspace_path: str, issue_id: str) -> list[Path]:
        paths = [
            self.qa_plan_json_path(workspace_path, issue_id),
            self.qa_report_md_path(workspace_path, issue_id),
        ]
        return [p for p in paths if p.exists()]

    # -------------------------------------------------------------------------
    # Specialist artifacts
    # -------------------------------------------------------------------------

    def specialist_artifact_path(
        self,
        workspace_path: str,
        issue_id: str,
        role_key: str,
        task_id: str,
    ) -> Path:
        p = self.issue_root(workspace_path, issue_id) / "specialists" / role_key / f"{task_id}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    # -------------------------------------------------------------------------
    # Aggregate listing
    # -------------------------------------------------------------------------

    def find_all_artifacts(self, workspace_path: str, issue_id: str) -> list[Path]:
        """Return all managed role artifacts for an issue, in deterministic order."""
        seen_names: set[str] = set()
        result: list[Path] = []

        # PM artifacts (order matters for backfill)
        for path in self.pm_find_prd_files(workspace_path, issue_id):
            if path.name not in seen_names:
                seen_names.add(path.name)
                result.append(path)
        for path in [
            self.pm_requirement_path(workspace_path, issue_id),
            self.pm_bugfix_path(workspace_path, issue_id),
            self.pm_prd_md_path(workspace_path, issue_id),
        ]:
            if path.exists() and path.name not in seen_names:
                seen_names.add(path.name)
                result.append(path)

        # Architect
        for path in self.architect_find_artifacts(workspace_path, issue_id):
            if path.name not in seen_names:
                seen_names.add(path.name)
                result.append(path)

        # Engineer
        for path in self.engineer_find_artifacts(workspace_path, issue_id):
            if path.name not in seen_names:
                seen_names.add(path.name)
                result.append(path)

        # QA
        for path in self.qa_find_artifacts(workspace_path, issue_id):
            if path.name not in seen_names:
                seen_names.add(path.name)
                result.append(path)

        return result
