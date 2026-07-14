from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.adapters.prototype_object_store import canonical_json_bytes
from app.adapters.prototype_render_artifact_store import (
    PrototypeRenderArtifactStore,
    PrototypeRenderArtifactStoreError,
)
from app.domain.structured_prototype import PrototypeRenderedFile, PrototypeRendererWorkerResult


def _hash(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _render_result() -> PrototypeRendererWorkerResult:
    files = tuple(
        PrototypeRenderedFile(
            relative_path=path,
            content=content,
            byte_size=len(content),
            content_hash=_hash(content),
        )
        for path, content in (
            ("document.json", b"{}"),
            ("index.html", b"<!doctype html><title>prototype</title>"),
            ("runtime.js", b"void 0;"),
            ("styles.css", b"html{background:#fff}"),
        )
    )
    descriptors = [
        {
            "relativePath": file.relative_path,
            "byteSize": file.byte_size,
            "contentHash": file.content_hash,
        }
        for file in files
    ]
    return PrototypeRendererWorkerResult(
        input_manifest_hash=_hash(b"input"),
        output_manifest={},
        output_manifest_hash=_hash(b"output"),
        visual_preflight_report={},
        visual_preflight_report_hash=_hash(b"preflight"),
        bundle_hash=_hash(canonical_json_bytes(descriptors)),
        files=files,
    )


def test_artifact_bundle_is_idempotent_readable_and_immutable(tmp_path: Path) -> None:
    store = PrototypeRenderArtifactStore(tmp_path / "managed-data")
    result = _render_result()

    first = store.write_bundle(
        project_id="project-1",
        document_id="document-1",
        artifact_id="artifact-1",
        result=result,
    )
    second = store.write_bundle(
        project_id="project-1",
        document_id="document-1",
        artifact_id="artifact-1",
        result=result,
    )

    assert second == first
    assert store.read_file(first, "index.html") == result.files[1].content
    artifact_path = tmp_path / "managed-data" / first.storage_key / "index.html"
    artifact_path.write_bytes(b"tampered")
    with pytest.raises(PrototypeRenderArtifactStoreError) as error:
        store.read_file(first, "index.html")
    assert error.value.code == "render_artifact_hash_mismatch"


def test_artifact_store_rejects_unregistered_paths(tmp_path: Path) -> None:
    store = PrototypeRenderArtifactStore(tmp_path / "managed-data")
    descriptor = store.write_bundle(
        project_id="project-1",
        document_id="document-1",
        artifact_id="artifact-1",
        result=_render_result(),
    )

    with pytest.raises(PrototypeRenderArtifactStoreError) as error:
        store.read_file(descriptor, "../console.db")

    assert error.value.code == "render_artifact_path_invalid"
