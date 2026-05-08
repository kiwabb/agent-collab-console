from __future__ import annotations

import shutil
from pathlib import Path


class WorkspaceManager:
    def __init__(
        self,
        source_root: str | Path,
        workspace_root: str | Path,
        bundled_skill_paths: list[str | Path | None] | None = None,
    ):
        self.source_root = Path(source_root).resolve()
        self.workspace_root = Path(workspace_root).resolve()
        self.bundled_skill_paths = [Path(path) for path in (bundled_skill_paths or [])]

    def _safe_deletable_workspace_path(self, workspace_path: str | Path) -> Path:
        target = Path(workspace_path).resolve()
        if target == self.source_root:
            raise ValueError("Refusing to delete the source root")
        try:
            target.relative_to(self.workspace_root)
        except ValueError as exc:
            raise ValueError("Refusing to delete a path outside the workspace root") from exc
        return target

    def create_workspace(self, task_id: str, parent_workspace_path: str | Path | None = None) -> str:
        target = self.workspace_root / task_id
        if target.exists():
            return str(target)

        target.parent.mkdir(parents=True, exist_ok=True)
        source = Path(parent_workspace_path) if parent_workspace_path else self.source_root

        def ignore_entries(dir_path: str, names: list[str]) -> set[str]:
            ignored = set(
                shutil.ignore_patterns(
                    ".git",
                    ".worktrees",
                    "worktrees",
                ".task-workspaces",
                ".next",
                "node_modules",
                "dist",
                    "__pycache__",
                    ".pytest_cache",
                    ".DS_Store",
                    "console.db",
                    "*.db-journal",
                    "*.db-wal",
                    "*.db-shm",
                    "*.pyc",
                )(dir_path, names)
            )
            for name in names:
                try:
                    if (Path(dir_path) / name).is_symlink():
                        ignored.add(name)
                except OSError:
                    ignored.add(name)
            return ignored

        shutil.copytree(
            source,
            target,
            ignore_dangling_symlinks=True,
            ignore=ignore_entries,
        )
        self._copy_bundled_skills_into_workspace(target)
        return str(target)

    def delete_workspace(self, workspace_path: str | Path):
        target = self._safe_deletable_workspace_path(workspace_path)
        if target.exists():
            shutil.rmtree(target)

    def _copy_bundled_skills_into_workspace(self, workspace_root: Path):
        if not self.bundled_skill_paths:
            return

        skills_root = workspace_root / ".codex" / "skills"
        skills_root.mkdir(parents=True, exist_ok=True)

        for skill_path in self.bundled_skill_paths:
            if not skill_path.exists():
                continue
            target = skills_root / skill_path.name
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(skill_path, target)
