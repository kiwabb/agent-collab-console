from __future__ import annotations

import os
import re
from contextlib import suppress
from pathlib import Path

from app.domain.models import Project, PrototypeVersion

PROJECT_PROTOTYPES_DIRECTORY = "prototypes"
LEGACY_PROTOTYPES_DIRECTORY = Path(".agent-collab") / "prototypes"
_SAFE_PATH_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class PrototypeVersionArtifactError(RuntimeError):
    """A project-local prototype version could not be written or read safely."""


def _project_root(project: Project) -> Path:
    try:
        root = Path(project.repo_path).resolve(strict=True)
    except OSError as exc:
        raise PrototypeVersionArtifactError("prototype project root is unavailable") from exc
    if not root.is_dir():
        raise PrototypeVersionArtifactError("prototype project root is not a directory")
    return root


def _path_component(field: str, value: str) -> str:
    if _SAFE_PATH_COMPONENT.fullmatch(value) is None:
        raise PrototypeVersionArtifactError(f"prototype {field} is not safe for a file path")
    return value


def _version_path_components(version: PrototypeVersion) -> tuple[str, str]:
    return (
        _path_component("ID", version.prototype_id),
        _path_component("version ID", version.id),
    )


def _prepare_child_directory(parent: Path, name: str, output_root: Path) -> Path:
    candidate = parent / name
    try:
        candidate.mkdir(exist_ok=True)
    except OSError as exc:
        raise PrototypeVersionArtifactError(
            "prototype version directory could not be prepared"
        ) from exc
    if candidate.is_symlink():
        raise PrototypeVersionArtifactError("prototype version directory contains a symlink")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise PrototypeVersionArtifactError(
            "prototype version directory could not be prepared"
        ) from exc
    if not resolved.is_dir() or not resolved.is_relative_to(output_root):
        raise PrototypeVersionArtifactError("prototype version directory escaped its output root")
    return resolved


def write_project_version(project: Project, version: PrototypeVersion) -> PrototypeVersion:
    """Write an immutable version before DB commit; ambiguous DB failures keep the file."""
    if not version.html:
        raise PrototypeVersionArtifactError("prototype version HTML is empty")
    try:
        payload = version.html.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise PrototypeVersionArtifactError("prototype version HTML is not valid UTF-8") from exc

    project_root = _project_root(project)
    output_root = project_root / PROJECT_PROTOTYPES_DIRECTORY
    try:
        output_root.mkdir(exist_ok=True)
    except OSError as exc:
        raise PrototypeVersionArtifactError(
            "prototype version directory could not be prepared"
        ) from exc
    if output_root.is_symlink():
        raise PrototypeVersionArtifactError("prototype output directory is a symlink")
    try:
        resolved_output_root = output_root.resolve(strict=True)
    except OSError as exc:
        raise PrototypeVersionArtifactError(
            "prototype version directory could not be prepared"
        ) from exc
    if not resolved_output_root.is_dir() or not resolved_output_root.is_relative_to(project_root):
        raise PrototypeVersionArtifactError("prototype output directory escaped the project")

    prototype_id, version_id = _version_path_components(version)
    prototype_directory = _prepare_child_directory(
        resolved_output_root,
        prototype_id,
        resolved_output_root,
    )
    version_directory = _prepare_child_directory(
        prototype_directory,
        version_id,
        resolved_output_root,
    )
    target = version_directory / "index.html"
    if target.exists() or target.is_symlink():
        raise PrototypeVersionArtifactError("prototype version file already exists")

    try:
        handle = target.open("xb")
    except FileExistsError as exc:
        raise PrototypeVersionArtifactError("prototype version file already exists") from exc
    except OSError as exc:
        raise PrototypeVersionArtifactError("prototype version file could not be written") from exc
    try:
        with handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        with suppress(OSError):
            target.unlink(missing_ok=True)
        raise PrototypeVersionArtifactError("prototype version file could not be written") from exc
    return version.model_copy(update={"disk_path": str(target)})


def read_project_version(project: Project, version: PrototypeVersion) -> str:
    """Read a persisted file, falling back only for legacy DB-only versions."""
    if version.disk_path is None:
        if version.html:
            return version.html
        raise PrototypeVersionArtifactError("prototype version has no persisted HTML")

    candidate = Path(version.disk_path)
    if not candidate.is_absolute() or ".." in candidate.parts:
        raise PrototypeVersionArtifactError("prototype version path is unsafe")
    project_root = _project_root(project)
    if not candidate.is_relative_to(project_root):
        raise PrototypeVersionArtifactError("prototype version path is outside the project")
    prototype_id, version_id = _version_path_components(version)
    expected_paths = {
        project_root / PROJECT_PROTOTYPES_DIRECTORY / prototype_id / version_id / "index.html",
        project_root
        / LEGACY_PROTOTYPES_DIRECTORY
        / prototype_id
        / f"v{version.version_no}"
        / "index.html",
    }
    if candidate not in expected_paths:
        raise PrototypeVersionArtifactError(
            "prototype version path does not match its version identity"
        )
    current = candidate
    while current != project_root:
        if current.is_symlink():
            raise PrototypeVersionArtifactError("prototype version path contains a symlink")
        current = current.parent
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise PrototypeVersionArtifactError("prototype version file is missing") from exc
    if not resolved.is_file():
        raise PrototypeVersionArtifactError("prototype version path is not a file")

    if resolved != candidate:
        raise PrototypeVersionArtifactError("prototype version path is outside the project")
    try:
        html = resolved.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise PrototypeVersionArtifactError("prototype version file could not be read") from exc
    if version.html and html != version.html:
        raise PrototypeVersionArtifactError(
            "prototype version file does not match its database record"
        )
    return html
