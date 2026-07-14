from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from app.adapters.prototype_object_store import (
    CANONICALIZER_VERSION,
    PrototypeObjectStore,
    PrototypeObjectStoreError,
    canonical_json_bytes,
)


def test_canonical_json_is_stable_across_key_order_and_unicode_keys() -> None:
    first = {"z": 2, "😀": "emoji", "\ue000": "private", "a": [True, None, "中文"]}
    second = {"a": [True, None, "中文"], "\ue000": "private", "😀": "emoji", "z": 2}

    assert CANONICALIZER_VERSION == "prototype-json-canonicalizer/1"
    assert canonical_json_bytes(first) == canonical_json_bytes(second)
    assert canonical_json_bytes(first).decode("utf-8") == (
        '{"a":[true,null,"中文"],"z":2,"\ue000":"private","😀":"emoji"}'
    )
    assert (
        "sha256:" + hashlib.sha256(canonical_json_bytes(first)).hexdigest()
        == "sha256:13b8db984e15a32f530afbda948a2f354b9fb276e6e73c16c45e0427a26cbfd5"
    )


@pytest.mark.parametrize("value", [1.5, 9_007_199_254_740_992, {1: "bad-key"}])
def test_canonical_json_rejects_unsupported_values(value: object) -> None:
    with pytest.raises(PrototypeObjectStoreError) as error:
        canonical_json_bytes(value)

    assert error.value.code == "object_canonicalization_failed"


def test_canonical_json_rejects_cycles() -> None:
    value: list[object] = []
    value.append(value)

    with pytest.raises(PrototypeObjectStoreError) as error:
        canonical_json_bytes(value)

    assert error.value.code == "object_canonicalization_failed"


def test_write_readback_and_idempotent_reuse(tmp_path: Path) -> None:
    store = PrototypeObjectStore(tmp_path / "data")
    value = {"schemaVersion": 1, "title": "采购审批", "pages": ["list", "create"]}

    first = store.write_json("project-1", value)
    second = store.write_json(
        "project-1",
        {"pages": ["list", "create"], "title": "采购审批", "schemaVersion": 1},
    )

    assert second == first
    assert first.content_hash.startswith("sha256:")
    assert first.storage_hash.startswith("sha256:")
    assert first.storage_hash != first.content_hash
    assert first.storage_key.startswith("projects/project-1/prototype-store/objects/")
    assert store.read_canonical_bytes(first) == canonical_json_bytes(value)
    object_path = tmp_path / "data" / first.storage_key
    assert object_path.is_file()
    assert not object_path.is_symlink()
    assert list((tmp_path / "data" / "projects/project-1/prototype-store/tmp").iterdir()) == []


def test_different_projects_do_not_share_storage_paths(tmp_path: Path) -> None:
    store = PrototypeObjectStore(tmp_path / "data")

    first = store.write_json("project-1", {"same": True})
    second = store.write_json("project-2", {"same": True})

    assert first.content_hash == second.content_hash
    assert first.storage_key != second.storage_key


def test_existing_corrupt_object_is_not_overwritten(tmp_path: Path) -> None:
    store = PrototypeObjectStore(tmp_path / "data")
    descriptor = store.write_json("project-1", {"value": "original"})
    object_path = tmp_path / "data" / descriptor.storage_key
    object_path.write_bytes(b"corrupt")

    with pytest.raises(PrototypeObjectStoreError) as error:
        store.write_json("project-1", {"value": "original"})

    assert error.value.code == "object_readback_failed"
    assert object_path.read_bytes() == b"corrupt"


def test_read_rejects_storage_hash_mismatch(tmp_path: Path) -> None:
    store = PrototypeObjectStore(tmp_path / "data")
    descriptor = store.write_json("project-1", {"value": "original"})
    wrong_descriptor = replace(
        descriptor,
        storage_hash="sha256:" + "0" * 64,
    )

    with pytest.raises(PrototypeObjectStoreError) as error:
        store.read_canonical_bytes(wrong_descriptor)

    assert error.value.code == "object_hash_mismatch"


def test_store_rejects_project_directory_symlink(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    projects = data_root / "projects"
    projects.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (projects / "project-1").symlink_to(outside, target_is_directory=True)
    store = PrototypeObjectStore(data_root)

    with pytest.raises(PrototypeObjectStoreError) as error:
        store.write_json("project-1", {"value": "blocked"})

    assert error.value.code == "object_path_invalid"
    assert list(outside.iterdir()) == []


def test_read_rejects_descriptor_bound_to_another_storage_key(tmp_path: Path) -> None:
    store = PrototypeObjectStore(tmp_path / "data")
    descriptor = store.write_json("project-1", {"value": "original"})
    wrong_descriptor = replace(descriptor, storage_key="projects/project-1/other.json.zst")

    with pytest.raises(PrototypeObjectStoreError) as error:
        store.read_canonical_bytes(wrong_descriptor)

    assert error.value.code == "object_path_invalid"
