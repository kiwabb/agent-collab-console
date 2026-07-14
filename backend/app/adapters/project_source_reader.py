from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


class RepositoryBoundaryError(ValueError):
    """Raised when a project read would cross or exceed its safe boundary."""


IGNORED_DIRECTORIES = frozenset(
    {
        ".agent-collab",
        ".git",
        ".next",
        ".nuxt",
        ".turbo",
        ".venv",
        "__pycache__",
        "build",
        "coverage",
        "dist",
        "node_modules",
        "tmp",
    }
)
GENERATED_ROOT_DIRECTORIES = frozenset({"prototypes"})


@dataclass
class RepositoryBoundary:
    """Read-only repository boundary shared by all evidence providers."""

    root: Path
    max_files: int = 12_000
    max_file_bytes: int = 100_000
    max_total_bytes: int = 2_000_000
    _read_bytes: int = field(default=0, init=False)

    @classmethod
    def from_repo_path(cls, repo_path: str) -> RepositoryBoundary:
        root = Path(repo_path).expanduser().resolve()
        if not root.exists() or not root.is_dir():
            raise RepositoryBoundaryError(f"repository root is not a directory: {repo_path}")
        return cls(root=root)

    def relative_path(self, path: Path) -> str:
        resolved = self._assert_inside(path)
        return resolved.relative_to(self.root).as_posix()

    def read_text(self, path: Path) -> str:
        resolved = self._assert_inside(path)
        if not resolved.is_file():
            raise RepositoryBoundaryError(
                f"evidence path is not a file: {self.relative_path(path)}"
            )
        try:
            size = resolved.stat().st_size
            if size > self.max_file_bytes:
                raise RepositoryBoundaryError(
                    f"evidence file exceeds {self.max_file_bytes} bytes: {self.relative_path(path)}"
                )
            if self._read_bytes + size > self.max_total_bytes:
                raise RepositoryBoundaryError(
                    f"repository evidence exceeds {self.max_total_bytes} bytes"
                )
            content = resolved.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise RepositoryBoundaryError(
                f"cannot read evidence file: {self.relative_path(path)}"
            ) from exc
        self._read_bytes += size
        return content

    def iter_files(self) -> list[Path]:
        files: list[Path] = []
        for current_root, dir_names, file_names in os.walk(
            self.root, topdown=True, followlinks=False
        ):
            current = Path(current_root)
            self._prune_directories(current, dir_names)
            for file_name in sorted(file_names):
                path = current / file_name
                if path.is_symlink():
                    if not self._assert_inside(path, allow_missing=True).is_relative_to(self.root):
                        raise RepositoryBoundaryError(
                            f"repository symlink escapes root: {self.relative_path(path)}"
                        )
                    continue
                files.append(path)
                if len(files) > self.max_files:
                    raise RepositoryBoundaryError(
                        f"repository contains more than {self.max_files} readable files"
                    )
        return files

    def resolve_source(self, base: Path) -> Path | None:
        """Resolve a local source import using common TS/JS extensions."""

        candidates = [base]
        if base.suffix == "":
            candidates.extend(
                base.with_suffix(suffix) for suffix in (".tsx", ".ts", ".jsx", ".js", ".vue")
            )
            candidates.extend(
                base / f"index{suffix}" for suffix in (".tsx", ".ts", ".jsx", ".js", ".vue")
            )
        for candidate in candidates:
            try:
                resolved = self._assert_inside(candidate, allow_missing=True)
            except RepositoryBoundaryError:
                raise
            if resolved.is_file():
                return resolved
        return None

    def _prune_directories(self, current: Path, dir_names: list[str]) -> None:
        for name in list(dir_names):
            path = current / name
            if name in IGNORED_DIRECTORIES or (
                current == self.root and name in GENERATED_ROOT_DIRECTORIES
            ):
                dir_names.remove(name)
                continue
            if path.is_symlink():
                resolved = self._assert_inside(path, allow_missing=True)
                if not resolved.is_relative_to(self.root):
                    raise RepositoryBoundaryError(
                        f"repository symlink escapes root: {self.relative_path(path)}"
                    )
                dir_names.remove(name)

    def _assert_inside(self, path: Path, *, allow_missing: bool = False) -> Path:
        try:
            resolved = path.resolve(strict=not allow_missing)
        except OSError as exc:
            raise RepositoryBoundaryError(f"cannot resolve repository path: {path}") from exc
        if not resolved.is_relative_to(self.root):
            raise RepositoryBoundaryError(f"repository path escapes root: {path}")
        return resolved
