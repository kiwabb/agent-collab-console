from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.application.prototype_version_artifacts import (
    PrototypeVersionArtifactError,
    read_project_version,
    write_project_version,
)
from app.domain.models import Project, PrototypeVersion

HTML_ONE = "<!DOCTYPE html><html><body>one</body></html>"
HTML_TWO = "<!DOCTYPE html><html><body>two</body></html>"


def _project(tmp_path: Path) -> Project:
    root = tmp_path / "project"
    root.mkdir()
    return Project(id="project-1", name="Project", repo_path=str(root))


def _version(
    *,
    version_id: str = "version-1",
    html: str = HTML_ONE,
    disk_path: str | None = None,
) -> PrototypeVersion:
    return PrototypeVersion(
        id=version_id,
        prototype_id="prototype-1",
        version_no=1,
        instruction="restore the page",
        html=html,
        disk_path=disk_path,
    )


def test_write_uses_resolved_project_prototypes_directory(tmp_path: Path) -> None:
    project = _project(tmp_path)

    persisted = write_project_version(project, _version())

    output_root = (Path(project.repo_path) / "prototypes").resolve(strict=True)
    expected = output_root / "prototype-1" / "version-1" / "index.html"
    assert persisted.disk_path == str(expected)
    assert expected.read_text(encoding="utf-8") == HTML_ONE
    assert expected.resolve(strict=True).is_relative_to(output_root)


def test_write_rejects_nested_directory_symlink_before_creating_outside_file(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    output_root = Path(project.repo_path) / "prototypes"
    output_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (output_root / "prototype-1").symlink_to(outside, target_is_directory=True)

    with pytest.raises(PrototypeVersionArtifactError, match="contains a symlink"):
        write_project_version(project, _version())

    assert list(outside.iterdir()) == []


def test_write_rejects_symlinked_output_root(tmp_path: Path) -> None:
    project = _project(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (Path(project.repo_path) / "prototypes").symlink_to(outside, target_is_directory=True)

    with pytest.raises(PrototypeVersionArtifactError, match="output directory is a symlink"):
        write_project_version(project, _version())

    assert list(outside.iterdir()) == []


def test_read_prefers_persisted_disk_file(tmp_path: Path) -> None:
    project = _project(tmp_path)
    persisted = write_project_version(project, _version())
    disk_only = persisted.model_copy(update={"html": ""})

    assert read_project_version(project, disk_only) == HTML_ONE


def test_read_falls_back_to_legacy_database_only_html(tmp_path: Path) -> None:
    project = _project(tmp_path)

    assert read_project_version(project, _version()) == HTML_ONE


def test_read_accepts_legacy_agent_collab_disk_path(tmp_path: Path) -> None:
    project = _project(tmp_path)
    legacy_path = (
        Path(project.repo_path)
        / ".agent-collab"
        / "prototypes"
        / "prototype-1"
        / "v1"
        / "index.html"
    )
    legacy_path.parent.mkdir(parents=True)
    legacy_path.write_text(HTML_ONE, encoding="utf-8")

    assert read_project_version(project, _version(disk_path=str(legacy_path.resolve()))) == HTML_ONE


def test_read_does_not_fall_back_when_persisted_file_is_missing(tmp_path: Path) -> None:
    project = _project(tmp_path)
    missing = Path(project.repo_path) / "prototypes" / "prototype-1" / "version-1" / "index.html"

    with pytest.raises(PrototypeVersionArtifactError, match="file is missing"):
        read_project_version(project, _version(disk_path=str(missing)))


def test_read_rejects_path_outside_project(tmp_path: Path) -> None:
    project = _project(tmp_path)
    outside = tmp_path / "outside.html"
    outside.write_text(HTML_ONE, encoding="utf-8")

    with pytest.raises(PrototypeVersionArtifactError, match="outside the project"):
        read_project_version(project, _version(disk_path=str(outside)))


def test_read_rejects_disk_and_database_mismatch(tmp_path: Path) -> None:
    project = _project(tmp_path)
    persisted = write_project_version(project, _version())
    mismatched = persisted.model_copy(update={"html": HTML_TWO})

    with pytest.raises(PrototypeVersionArtifactError, match="does not match"):
        read_project_version(project, mismatched)


def test_read_rejects_path_bound_to_another_version(tmp_path: Path) -> None:
    project = _project(tmp_path)
    first = write_project_version(project, _version(version_id="version-1"))
    second = write_project_version(project, _version(version_id="version-2"))
    assert second.disk_path is not None
    wrong_identity = first.model_copy(update={"disk_path": second.disk_path})

    with pytest.raises(PrototypeVersionArtifactError, match="does not match its version identity"):
        read_project_version(project, wrong_identity)


def test_read_rejects_symlinked_version_directory(tmp_path: Path) -> None:
    project = _project(tmp_path)
    first = write_project_version(project, _version(version_id="version-1"))
    second = write_project_version(project, _version(version_id="version-2"))
    assert first.disk_path is not None
    assert second.disk_path is not None
    first_path = Path(first.disk_path)
    second_directory = Path(second.disk_path).parent
    first_path.unlink()
    first_path.parent.rmdir()
    first_path.parent.symlink_to(second_directory, target_is_directory=True)

    with pytest.raises(PrototypeVersionArtifactError, match="contains a symlink"):
        read_project_version(project, first)


def test_read_rejects_invalid_utf8_file(tmp_path: Path) -> None:
    project = _project(tmp_path)
    invalid_path = (
        Path(project.repo_path) / "prototypes" / "prototype-1" / "version-invalid" / "index.html"
    )
    invalid_path.parent.mkdir(parents=True)
    invalid_path.write_bytes(b"\xff\xfe")
    version = _version(
        version_id="version-invalid",
        html="",
        disk_path=str(invalid_path.resolve()),
    )

    with pytest.raises(PrototypeVersionArtifactError, match="could not be read"):
        read_project_version(project, version)


def test_duplicate_version_id_does_not_overwrite_existing_file(tmp_path: Path) -> None:
    project = _project(tmp_path)
    first = write_project_version(project, _version())

    with pytest.raises(PrototypeVersionArtifactError, match="already exists"):
        write_project_version(project, _version(html=HTML_TWO))

    assert first.disk_path is not None
    assert Path(first.disk_path).read_text(encoding="utf-8") == HTML_ONE


def test_concurrent_versions_use_distinct_version_id_paths(tmp_path: Path) -> None:
    project = _project(tmp_path)
    versions = (
        _version(version_id="version-a", html=HTML_ONE),
        _version(version_id="version-b", html=HTML_TWO),
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        persisted = tuple(
            executor.map(lambda version: write_project_version(project, version), versions)
        )

    paths = {Path(version.disk_path) for version in persisted if version.disk_path is not None}
    assert len(paths) == 2
    assert {path.parent.name for path in paths} == {"version-a", "version-b"}
    assert {path.read_text(encoding="utf-8") for path in paths} == {HTML_ONE, HTML_TWO}
