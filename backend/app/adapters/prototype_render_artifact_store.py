from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from contextlib import suppress
from pathlib import Path
from uuid import uuid4

from app.adapters.prototype_object_store import canonical_json_bytes
from app.domain.structured_prototype import (
    PrototypeRenderBundleDescriptor,
    PrototypeRenderedFile,
    PrototypeRendererWorkerResult,
)

_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SAFE_FILES = frozenset({"document.json", "index.html", "runtime.js", "styles.css"})
_MANIFEST_FILE = ".artifact-manifest.json"


class PrototypeRenderArtifactStoreError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _component(value: str, field: str) -> str:
    if _SAFE_COMPONENT.fullmatch(value) is None:
        raise PrototypeRenderArtifactStoreError(
            "render_artifact_path_invalid",
            f"prototype render artifact {field} is not safe for managed storage",
        )
    return value


def _sha256(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _fsync_directory(directory: Path) -> None:
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError as exc:
        raise PrototypeRenderArtifactStoreError(
            "render_artifact_write_failed",
            "prototype render artifact directory could not be opened for sync",
        ) from exc
    try:
        os.fsync(descriptor)
    except OSError as exc:
        raise PrototypeRenderArtifactStoreError(
            "render_artifact_write_failed",
            "prototype render artifact directory could not be synced",
        ) from exc
    finally:
        os.close(descriptor)


class PrototypeRenderArtifactStore:
    def __init__(self, data_root: Path) -> None:
        self._data_root = data_root

    def write_bundle(
        self,
        *,
        project_id: str,
        document_id: str,
        artifact_id: str,
        result: PrototypeRendererWorkerResult,
    ) -> PrototypeRenderBundleDescriptor:
        paths = self._paths(project_id, document_id, artifact_id, prepare=True)
        storage_key = paths.target.relative_to(paths.root).as_posix()
        descriptor = PrototypeRenderBundleDescriptor(
            project_id=project_id,
            document_id=document_id,
            artifact_id=artifact_id,
            storage_key=storage_key,
            entrypoint="index.html",
            output_hash=result.bundle_hash,
            output_manifest_hash=result.output_manifest_hash,
            visual_preflight_report_hash=result.visual_preflight_report_hash,
            file_count=len(result.files),
        )
        expected_manifest = self._artifact_manifest(descriptor, result.files)
        if paths.target.exists():
            self._verify_bundle(paths.target, descriptor, expected_manifest)
            return descriptor
        temporary = paths.tmp / f"{artifact_id}.{uuid4()}.partial"
        try:
            temporary.mkdir(mode=0o700)
            for file in result.files:
                self._write_file(temporary, file)
            manifest_path = temporary / _MANIFEST_FILE
            with manifest_path.open("xb") as handle:
                handle.write(canonical_json_bytes(expected_manifest))
                handle.flush()
                os.fsync(handle.fileno())
            _fsync_directory(temporary)
            try:
                temporary.rename(paths.target)
            except FileExistsError:
                self._verify_bundle(paths.target, descriptor, expected_manifest)
            else:
                _fsync_directory(paths.target.parent)
        except PrototypeRenderArtifactStoreError:
            raise
        except OSError as exc:
            raise PrototypeRenderArtifactStoreError(
                "render_artifact_write_failed",
                "prototype render artifact bundle could not be installed",
            ) from exc
        finally:
            with suppress(OSError):
                if temporary.exists():
                    shutil.rmtree(temporary)
        self._verify_bundle(paths.target, descriptor, expected_manifest)
        return descriptor

    def read_file(
        self,
        descriptor: PrototypeRenderBundleDescriptor,
        relative_path: str,
    ) -> bytes:
        if relative_path not in _SAFE_FILES:
            raise PrototypeRenderArtifactStoreError(
                "render_artifact_path_invalid",
                "prototype render artifact file path is not allowed",
            )
        paths = self._paths(
            descriptor.project_id,
            descriptor.document_id,
            descriptor.artifact_id,
            prepare=False,
        )
        if descriptor.storage_key != paths.target.relative_to(paths.root).as_posix():
            raise PrototypeRenderArtifactStoreError(
                "render_artifact_path_invalid",
                "prototype render artifact storage key does not match its identity",
            )
        manifest = self._read_manifest(paths.target)
        self._assert_descriptor_manifest(descriptor, manifest)
        files = manifest["files"]
        if not isinstance(files, list):
            raise PrototypeRenderArtifactStoreError(
                "render_artifact_manifest_invalid",
                "prototype render artifact file manifest is invalid",
            )
        expected = next(
            (
                item
                for item in files
                if isinstance(item, dict) and item.get("relativePath") == relative_path
            ),
            None,
        )
        if expected is None:
            raise PrototypeRenderArtifactStoreError(
                "render_artifact_file_missing",
                "prototype render artifact file is not registered",
            )
        target = paths.target / relative_path
        self._assert_regular_file(target, paths.target)
        try:
            try:
                content = target.read_bytes()
            except OSError as exc:
                raise PrototypeRenderArtifactStoreError(
                    "render_artifact_read_failed",
                    f"prototype render artifact file {relative_path} could not be read",
                ) from exc
        except OSError as exc:
            raise PrototypeRenderArtifactStoreError(
                "render_artifact_read_failed",
                "prototype render artifact file could not be read",
            ) from exc
        if expected.get("byteSize") != len(content) or expected.get("contentHash") != _sha256(
            content
        ):
            raise PrototypeRenderArtifactStoreError(
                "render_artifact_hash_mismatch",
                "prototype render artifact file does not match its manifest",
            )
        return content

    def _paths(
        self,
        project_id: str,
        document_id: str,
        artifact_id: str,
        *,
        prepare: bool,
    ) -> _ArtifactPaths:
        safe_project = _component(project_id, "project ID")
        safe_document = _component(document_id, "document ID")
        safe_artifact = _component(artifact_id, "artifact ID")
        if prepare:
            try:
                self._data_root.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise PrototypeRenderArtifactStoreError(
                    "render_artifact_write_failed",
                    "prototype managed data root could not be prepared",
                ) from exc
        if self._data_root.is_symlink():
            raise PrototypeRenderArtifactStoreError(
                "render_artifact_path_invalid",
                "prototype managed data root must not be a symlink",
            )
        try:
            root = self._data_root.resolve(strict=True)
        except OSError as exc:
            code = "render_artifact_write_failed" if prepare else "render_artifact_missing"
            raise PrototypeRenderArtifactStoreError(
                code,
                "prototype managed data root is unavailable",
            ) from exc
        current = root
        for name in (
            "projects",
            safe_project,
            "prototype-store",
            "renders",
            safe_document,
        ):
            current = self._child_directory(current, name, root, prepare)
        target = current / safe_artifact
        tmp = root
        for name in ("projects", safe_project, "prototype-store", "tmp"):
            tmp = self._child_directory(tmp, name, root, prepare)
        return _ArtifactPaths(root=root, tmp=tmp, target=target)

    @staticmethod
    def _child_directory(parent: Path, name: str, root: Path, prepare: bool) -> Path:
        candidate = parent / name
        if prepare:
            try:
                candidate.mkdir(exist_ok=True)
            except OSError as exc:
                raise PrototypeRenderArtifactStoreError(
                    "render_artifact_write_failed",
                    "prototype render artifact directory could not be prepared",
                ) from exc
        if candidate.is_symlink():
            raise PrototypeRenderArtifactStoreError(
                "render_artifact_path_invalid",
                "prototype render artifact directory contains a symlink",
            )
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            code = "render_artifact_write_failed" if prepare else "render_artifact_missing"
            raise PrototypeRenderArtifactStoreError(
                code,
                "prototype render artifact directory is unavailable",
            ) from exc
        if not resolved.is_dir() or not resolved.is_relative_to(root):
            raise PrototypeRenderArtifactStoreError(
                "render_artifact_path_invalid",
                "prototype render artifact directory escaped the managed data root",
            )
        return resolved

    @staticmethod
    def _write_file(directory: Path, file: PrototypeRenderedFile) -> None:
        if file.relative_path not in _SAFE_FILES:
            raise PrototypeRenderArtifactStoreError(
                "render_artifact_path_invalid",
                "prototype renderer returned an unsupported artifact file path",
            )
        target = directory / file.relative_path
        try:
            with target.open("xb") as handle:
                handle.write(file.content)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            raise PrototypeRenderArtifactStoreError(
                "render_artifact_write_failed",
                f"prototype render artifact file {file.relative_path} could not be written",
            ) from exc

    @staticmethod
    def _artifact_manifest(
        descriptor: PrototypeRenderBundleDescriptor,
        files: tuple[PrototypeRenderedFile, ...],
    ) -> dict[str, object]:
        return {
            "contractVersion": 1,
            "projectId": descriptor.project_id,
            "documentId": descriptor.document_id,
            "artifactId": descriptor.artifact_id,
            "entrypoint": descriptor.entrypoint,
            "outputHash": descriptor.output_hash,
            "outputManifestHash": descriptor.output_manifest_hash,
            "visualPreflightReportHash": descriptor.visual_preflight_report_hash,
            "files": [
                {
                    "relativePath": file.relative_path,
                    "byteSize": file.byte_size,
                    "contentHash": file.content_hash,
                }
                for file in files
            ],
        }

    def _verify_bundle(
        self,
        directory: Path,
        descriptor: PrototypeRenderBundleDescriptor,
        expected_manifest: dict[str, object],
    ) -> None:
        actual = self._read_manifest(directory)
        if actual != expected_manifest:
            raise PrototypeRenderArtifactStoreError(
                "render_artifact_identity_conflict",
                "prototype render artifact identity already contains different content",
            )
        self._assert_descriptor_manifest(descriptor, actual)
        files = actual["files"]
        if not isinstance(files, list):
            raise PrototypeRenderArtifactStoreError(
                "render_artifact_manifest_invalid",
                "prototype render artifact file manifest is invalid",
            )
        for item in files:
            if not isinstance(item, dict) or not isinstance(item.get("relativePath"), str):
                raise PrototypeRenderArtifactStoreError(
                    "render_artifact_manifest_invalid",
                    "prototype render artifact file descriptor is invalid",
                )
            relative_path = item["relativePath"]
            if relative_path not in _SAFE_FILES:
                raise PrototypeRenderArtifactStoreError(
                    "render_artifact_manifest_invalid",
                    "prototype render artifact manifest contains an unsafe path",
                )
            target = directory / relative_path
            self._assert_regular_file(target, directory)
            content = target.read_bytes()
            if item.get("byteSize") != len(content) or item.get("contentHash") != _sha256(
                content
            ):
                raise PrototypeRenderArtifactStoreError(
                    "render_artifact_hash_mismatch",
                    f"prototype render artifact file {relative_path} does not match its manifest",
                )

    @staticmethod
    def _read_manifest(directory: Path) -> dict[str, object]:
        if directory.is_symlink():
            raise PrototypeRenderArtifactStoreError(
                "render_artifact_path_invalid",
                "prototype render artifact directory is a symlink",
            )
        try:
            resolved = directory.resolve(strict=True)
        except OSError as exc:
            raise PrototypeRenderArtifactStoreError(
                "render_artifact_missing",
                "prototype render artifact directory is missing",
            ) from exc
        if resolved != directory or not resolved.is_dir():
            raise PrototypeRenderArtifactStoreError(
                "render_artifact_path_invalid",
                "prototype render artifact directory is invalid",
            )
        manifest_path = resolved / _MANIFEST_FILE
        PrototypeRenderArtifactStore._assert_regular_file(manifest_path, resolved)
        try:
            raw = manifest_path.read_bytes()
            decoded = json.loads(raw)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise PrototypeRenderArtifactStoreError(
                "render_artifact_manifest_invalid",
                "prototype render artifact manifest could not be read",
            ) from exc
        if not isinstance(decoded, dict):
            raise PrototypeRenderArtifactStoreError(
                "render_artifact_manifest_invalid",
                "prototype render artifact manifest is not an object",
            )
        return decoded

    @staticmethod
    def _assert_descriptor_manifest(
        descriptor: PrototypeRenderBundleDescriptor,
        manifest: dict[str, object],
    ) -> None:
        expected = (
            1,
            descriptor.project_id,
            descriptor.document_id,
            descriptor.artifact_id,
            descriptor.entrypoint,
            descriptor.output_hash,
            descriptor.output_manifest_hash,
            descriptor.visual_preflight_report_hash,
        )
        actual = (
            manifest.get("contractVersion"),
            manifest.get("projectId"),
            manifest.get("documentId"),
            manifest.get("artifactId"),
            manifest.get("entrypoint"),
            manifest.get("outputHash"),
            manifest.get("outputManifestHash"),
            manifest.get("visualPreflightReportHash"),
        )
        if actual != expected:
            raise PrototypeRenderArtifactStoreError(
                "render_artifact_identity_conflict",
                "prototype render artifact manifest does not match its database identity",
            )

    @staticmethod
    def _assert_regular_file(path: Path, root: Path) -> None:
        if path.is_symlink():
            raise PrototypeRenderArtifactStoreError(
                "render_artifact_path_invalid",
                "prototype render artifact path contains a symlink",
            )
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise PrototypeRenderArtifactStoreError(
                "render_artifact_file_missing",
                "prototype render artifact file is missing",
            ) from exc
        if resolved != path or not resolved.is_file() or not resolved.is_relative_to(root):
            raise PrototypeRenderArtifactStoreError(
                "render_artifact_path_invalid",
                "prototype render artifact file escaped its bundle",
            )


class _ArtifactPaths:
    def __init__(self, *, root: Path, tmp: Path, target: Path) -> None:
        self.root = root
        self.tmp = tmp
        self.target = target
