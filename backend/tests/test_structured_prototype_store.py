from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite
import pytest

from app.adapters.prototype_object_store import PrototypeObjectStore
from app.adapters.structured_prototype_store import (
    AsyncStructuredPrototypeStore,
    StructuredPrototypeStoreError,
)
from app.domain.structured_prototype import (
    PrototypeObjectDescriptor,
    PrototypeObjectReference,
)


def _reference(descriptor: PrototypeObjectDescriptor) -> PrototypeObjectReference:
    return PrototypeObjectReference(
        project_id=descriptor.project_id,
        owner_kind="checkpoint",
        owner_id="checkpoint-1",
        role="draft-checkpoint",
        content_hash=descriptor.content_hash,
        payload_type="prototype_document",
        schema_version=1,
        created_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_registers_only_descriptor_and_owner_reference(tmp_path: Path) -> None:
    object_store = PrototypeObjectStore(tmp_path / "objects")
    descriptor = object_store.write_json("project-1", {"schemaVersion": 1, "pages": []})
    reference = _reference(descriptor)
    store = AsyncStructuredPrototypeStore(tmp_path / "console.db")

    try:
        await store.register_object_reference(descriptor, reference)

        assert await store.load_object("project-1", descriptor.content_hash) == descriptor
        assert await store.list_object_references("project-1", "checkpoint", "checkpoint-1") == [
            reference
        ]
        async with (
            aiosqlite.connect(tmp_path / "console.db") as conn,
            conn.execute("PRAGMA table_info(prototype_objects)") as cursor,
        ):
            columns = [str(row[1]) for row in await cursor.fetchall()]
        assert "document_json" not in columns
        assert "payload_json" not in columns
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_registration_is_idempotent(tmp_path: Path) -> None:
    descriptor = PrototypeObjectStore(tmp_path / "objects").write_json(
        "project-1", {"schemaVersion": 1}
    )
    reference = _reference(descriptor)
    store = AsyncStructuredPrototypeStore(tmp_path / "console.db")

    try:
        await store.register_object_reference(descriptor, reference)
        await store.register_object_reference(descriptor, reference)

        assert await store.list_object_references("project-1", "checkpoint", "checkpoint-1") == [
            reference
        ]
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_conflicting_descriptor_rolls_back_new_reference(tmp_path: Path) -> None:
    descriptor = PrototypeObjectStore(tmp_path / "objects").write_json(
        "project-1", {"schemaVersion": 1}
    )
    store = AsyncStructuredPrototypeStore(tmp_path / "console.db")
    conflict = replace(descriptor, stored_byte_size=descriptor.stored_byte_size + 1)
    conflict_reference = replace(_reference(descriptor), owner_id="checkpoint-conflict")

    try:
        await store.register_object_reference(descriptor, _reference(descriptor))
        with pytest.raises(StructuredPrototypeStoreError) as error:
            await store.register_object_reference(conflict, conflict_reference)

        assert error.value.code == "object_descriptor_conflict"
        assert (
            await store.list_object_references("project-1", "checkpoint", "checkpoint-conflict")
            == []
        )
        assert await store.load_object("project-1", descriptor.content_hash) == descriptor
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_reference_identity_mismatch_is_rejected_before_sql(tmp_path: Path) -> None:
    descriptor = PrototypeObjectStore(tmp_path / "objects").write_json(
        "project-1", {"schemaVersion": 1}
    )
    store = AsyncStructuredPrototypeStore(tmp_path / "console.db")
    mismatched = replace(_reference(descriptor), project_id="project-2")

    try:
        with pytest.raises(StructuredPrototypeStoreError) as error:
            await store.register_object_reference(descriptor, mismatched)

        assert error.value.code == "object_reference_identity_mismatch"
        assert not (tmp_path / "console.db").exists()
    finally:
        await store.close()
