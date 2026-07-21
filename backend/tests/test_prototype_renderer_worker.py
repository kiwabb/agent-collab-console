from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from structured_prototype_fixtures import fixture_id, procurement_document

from app.adapters.prototype_object_store import canonical_json_bytes
from app.adapters.prototype_renderer_worker import (
    PrototypeRendererWorker,
    PrototypeRendererWorkerError,
)
from app.application.structured_prototype_contracts import document_hash, document_payload


def _input_manifest(worker: PrototypeRendererWorker) -> dict[str, object]:
    identity = worker.identity
    return {
        "rendererVersion": identity.renderer_version,
        "rendererEnvironmentVersion": identity.renderer_environment_version,
        "runtimeCoreVersion": identity.runtime_core_version,
        "runtimeCoreSourceHash": identity.runtime_core_source_hash,
        "runtimeCoreBundleHash": identity.runtime_core_bundle_hash,
        "stateMachineKernelVersion": identity.state_machine_kernel_version,
        "renderRuntimeImageHash": identity.render_runtime_image_hash,
        "browserVersion": identity.browser_version,
        "fontPackHash": identity.font_pack_hash,
        "viewportProfileHash": identity.viewport_profile_hash,
        "documentObjectHash": document_hash(procurement_document()),
        "documentSchemaVersion": 1,
        "assetObjectHashes": [],
        "sandboxPolicyVersion": identity.sandbox_policy_version,
        "outputLocale": "zh-CN",
    }


@pytest.mark.asyncio
async def test_renderer_describe_and_render_are_deterministic() -> None:
    worker = PrototypeRendererWorker()
    described = await worker.describe(fixture_id("renderer-describe"))
    manifest = _input_manifest(worker)
    document = document_payload(procurement_document())

    first = await worker.render(
        request_id=fixture_id("renderer-first"),
        artifact_id=fixture_id("renderer-artifact"),
        input_manifest=manifest,
        document=document,
    )
    second = await worker.render(
        request_id=fixture_id("renderer-second"),
        artifact_id=fixture_id("renderer-artifact"),
        input_manifest=manifest,
        document=document,
    )

    assert described == worker.identity
    assert first == second
    assert tuple(file.relative_path for file in first.files) == (
        "document.json",
        "index.html",
        "runtime.js",
        "styles.css",
    )
    assert first.visual_preflight_report["pageCount"] == 3
    checks = first.visual_preflight_report["checks"]
    assert isinstance(checks, list)
    for check in checks:
        assert isinstance(check, dict)
        assert check["status"] == "passed"
    index = next(file.content for file in first.files if file.relative_path == "index.html")
    assert b'<meta name="prototype-document-hash" content="sha256:' in index
    assert b'data-prototype-page-id="' in index
    assert b'<script src="./runtime.js" defer></script>' in index


@pytest.mark.asyncio
async def test_renderer_rejects_document_that_does_not_match_frozen_hash() -> None:
    worker = PrototypeRendererWorker()
    manifest = _input_manifest(worker)
    document = document_payload(procurement_document())
    document["title"] = "tampered"

    with pytest.raises(PrototypeRendererWorkerError) as error:
        await worker.render(
            request_id=fixture_id("renderer-tampered-document"),
            artifact_id=fixture_id("renderer-tampered-artifact"),
            input_manifest=manifest,
            document=document,
        )

    assert error.value.code == "renderer_document_hash_mismatch"


@pytest.mark.asyncio
async def test_renderer_rejects_duplicate_view_binding_targets_like_preview() -> None:
    worker = PrototypeRendererWorker()
    manifest = _input_manifest(worker)
    document = document_payload(procurement_document())
    runtime = document["runtime"]
    assert isinstance(runtime, dict)
    runtime["viewBindings"] = [
        {
            "id": fixture_id("renderer-binding-first"),
            "nodeId": fixture_id("title-list"),
            "target": "textContent",
            "value": {"kind": "literal", "value": {"type": "string", "value": "first"}},
        },
        {
            "id": fixture_id("renderer-binding-duplicate"),
            "nodeId": fixture_id("title-list"),
            "target": "textContent",
            "value": {"kind": "literal", "value": {"type": "string", "value": "second"}},
        },
    ]
    manifest["documentObjectHash"] = (
        "sha256:" + hashlib.sha256(canonical_json_bytes(document)).hexdigest()
    )

    with pytest.raises(PrototypeRendererWorkerError) as error:
        await worker.render(
            request_id=fixture_id("renderer-duplicate-view-binding"),
            artifact_id=fixture_id("renderer-duplicate-view-binding-artifact"),
            input_manifest=manifest,
            document=document,
        )

    assert error.value.code == "renderer_document_invalid"
    assert "duplicate node target" in str(error.value)


@pytest.mark.asyncio
async def test_renderer_accepts_absolute_positioned_child_inside_stack() -> None:
    worker = PrototypeRendererWorker()
    manifest = _input_manifest(worker)
    document = document_payload(procurement_document())
    pages = document["pages"]
    assert isinstance(pages, list)
    root = pages[0]["root"]
    assert isinstance(root, dict)
    assert root["type"] == "Stack"
    title = root["children"][0]
    assert isinstance(title, dict)
    title["layoutItem"]["position"] = {"x": "24", "y": "32"}
    manifest["documentObjectHash"] = (
        "sha256:" + hashlib.sha256(canonical_json_bytes(document)).hexdigest()
    )

    rendered = await worker.render(
        request_id=fixture_id("renderer-stack-absolute-child"),
        artifact_id=fixture_id("renderer-stack-absolute-artifact"),
        input_manifest=manifest,
        document=document,
    )

    styles = next(file.content for file in rendered.files if file.relative_path == "styles.css")
    assert b"position:absolute;left:24px;top:32px" in styles
    assert b"position:relative" in styles


def test_renderer_refuses_a_tampered_bundle_manifest(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[1] / "app" / "runtime_assets"
    target = tmp_path / "runtime-assets"
    target.mkdir()
    for name in (
        "prototype_public_runtime.js",
        "prototype_renderer_worker.mjs",
        "prototype_renderer_worker.manifest.json",
    ):
        (target / name).write_bytes((source / name).read_bytes())
    bundle = target / "prototype_renderer_worker.mjs"
    bundle.write_bytes(bundle.read_bytes() + b"\n// tampered")

    with pytest.raises(PrototypeRendererWorkerError) as error:
        PrototypeRendererWorker(manifest_path=target / "prototype_renderer_worker.manifest.json")

    assert error.value.code == "renderer_worker_asset_hash_mismatch"


@pytest.mark.asyncio
async def test_renderer_renders_divider_and_badge_nodes() -> None:
    from app.application.structured_prototype_contracts import (
        execute_command_batch,
        parse_command_batch_json,
    )

    def _layout() -> dict[str, object]:
        auto = {"unit": "auto", "value": None}
        return {
            "width": auto,
            "minWidth": None,
            "maxWidth": None,
            "height": auto,
            "minHeight": None,
            "maxHeight": None,
            "grow": 0,
            "shrink": 1,
            "alignSelf": "stretch",
        }

    import json

    batch = parse_command_batch_json(
        json.dumps(
            {
                "commandContractVersion": 1,
                "summary": "插入分隔线与徽章",
                "commands": [
                    {
                        "kind": "insertNode",
                        "parent": {"kind": "existing", "nodeId": fixture_id("root-list")},
                        "slot": None,
                        "index": 1,
                        "node": {
                            "newNodeKey": "render-divider",
                            "type": "Divider",
                            "name": "分隔线",
                            "visibility": "visible",
                            "layoutItem": _layout(),
                            "responsive": [],
                            "spacing": 20,
                            "tone": "muted",
                        },
                    },
                    {
                        "kind": "insertNode",
                        "parent": {"kind": "existing", "nodeId": fixture_id("root-list")},
                        "slot": None,
                        "index": 2,
                        "node": {
                            "newNodeKey": "render-badge",
                            "type": "Badge",
                            "name": "状态徽章",
                            "visibility": "visible",
                            "layoutItem": _layout(),
                            "responsive": [],
                            "label": "待审批",
                            "tone": "warning",
                            "iconName": None,
                        },
                    },
                ],
            }
        )
    )
    result = execute_command_batch(
        procurement_document(),
        batch,
        draft_id=fixture_id("draft"),
        client_request_id=fixture_id("render-divider-badge"),
    )
    worker = PrototypeRendererWorker()
    manifest = _input_manifest(worker)
    manifest["documentObjectHash"] = document_hash(result.document)

    rendered = await worker.render(
        request_id=fixture_id("renderer-divider-badge"),
        artifact_id=fixture_id("renderer-divider-badge-artifact"),
        input_manifest=manifest,
        document=document_payload(result.document),
    )

    index = next(file.content for file in rendered.files if file.relative_path == "index.html")
    styles = next(file.content for file in rendered.files if file.relative_path == "styles.css")
    allocated = dict(result.allocated_entity_ids)
    assert (
        f'data-prototype-node-id="{allocated["render-divider"]}" '
        'data-prototype-node-type="Divider" '
        'class="prototype-divider" role="separator">'
        '<span class="prototype-divider-line prototype-divider-line-muted"></span>'
    ).encode() in index
    assert (
        f'data-prototype-node-id="{allocated["render-badge"]}" '
        'data-prototype-node-type="Badge" '
        'class="prototype-badge prototype-badge-warning">待审批</span>'
    ).encode() in index
    assert f'[data-prototype-node-id="{allocated["render-divider"]}"]'.encode() in styles
    assert b"padding:20px 0" in styles
    assert b".prototype-divider{width:100%}" in styles
    assert (
        b".prototype-divider-line{display:block;width:100%;height:1px;background:#c9d2ce}" in styles
    )
    assert b".prototype-divider-line-muted{background:#e6eae8}" in styles
    assert b".prototype-badge-warning{background:#fff2d8;color:#936221}" in styles
