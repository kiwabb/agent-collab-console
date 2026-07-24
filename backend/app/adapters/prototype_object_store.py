from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import zstandard

from app.domain.structured_prototype import PrototypeObjectDescriptor

CANONICALIZER_VERSION = "prototype-json-canonicalizer/1"
STORAGE_CODEC_VERSION = "zstandard/0.25.0;level=10;checksum=1;content-size=1;dict-id=0;threads=0"
ZSTD_COMPRESSION_LEVEL = 10
MAX_SAFE_INTEGER = 9_007_199_254_740_991
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
SAFE_PATH_COMPONENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class PrototypeObjectStoreError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _sha256(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _json_string(value: str, path: str) -> str:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise PrototypeObjectStoreError(
            "object_canonicalization_failed",
            f"canonical JSON string is not valid Unicode at {path}",
        ) from exc
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _canonical_json(value: object, path: str, active_containers: set[int]) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        if value < -MAX_SAFE_INTEGER or value > MAX_SAFE_INTEGER:
            raise PrototypeObjectStoreError(
                "object_canonicalization_failed",
                f"canonical JSON integer is outside the safe range at {path}",
            )
        return str(value)
    if isinstance(value, str):
        return _json_string(value, path)
    if isinstance(value, list):
        container_id = id(value)
        if container_id in active_containers:
            raise PrototypeObjectStoreError(
                "object_canonicalization_failed",
                f"canonical JSON contains a cycle at {path}",
            )
        active_containers.add(container_id)
        try:
            children = [
                _canonical_json(item, f"{path}[{index}]", active_containers)
                for index, item in enumerate(value)
            ]
        finally:
            active_containers.remove(container_id)
        return f"[{','.join(children)}]"
    if isinstance(value, dict):
        container_id = id(value)
        if container_id in active_containers:
            raise PrototypeObjectStoreError(
                "object_canonicalization_failed",
                f"canonical JSON contains a cycle at {path}",
            )
        active_containers.add(container_id)
        try:
            entries: list[tuple[str, object]] = []
            for key, item in value.items():
                if not isinstance(key, str):
                    raise PrototypeObjectStoreError(
                        "object_canonicalization_failed",
                        f"canonical JSON object key must be a string at {path}",
                    )
                _json_string(key, f"{path}.<key>")
                entries.append((key, item))
            entries.sort(key=lambda entry: entry[0])
            children = [
                f"{_json_string(key, f'{path}.<key>')}:{_canonical_json(item, f'{path}.{key}', active_containers)}"
                for key, item in entries
            ]
        finally:
            active_containers.remove(container_id)
        return f"{{{','.join(children)}}}"
    raise PrototypeObjectStoreError(
        "object_canonicalization_failed",
        f"unsupported canonical JSON value at {path}: {type(value).__name__}",
    )


def canonical_json_bytes(value: object) -> bytes:
    return _canonical_json(value, "$", set()).encode("utf-8")


def _safe_project_id(project_id: str) -> str:
    if SAFE_PATH_COMPONENT_RE.fullmatch(project_id) is None:
        raise PrototypeObjectStoreError(
            "object_path_invalid",
            "prototype object project ID is not safe for managed storage",
        )
    return project_id


def _prepare_child_directory(parent: Path, name: str, root: Path) -> Path:
    candidate = parent / name
    try:
        candidate.mkdir(exist_ok=True)
    except OSError as exc:
        raise PrototypeObjectStoreError(
            "object_write_failed",
            "prototype object directory could not be prepared",
        ) from exc
    if candidate.is_symlink():
        raise PrototypeObjectStoreError(
            "object_path_invalid",
            "prototype object directory contains a symlink",
        )
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise PrototypeObjectStoreError(
            "object_write_failed",
            "prototype object directory could not be resolved",
        ) from exc
    if not resolved.is_dir() or not resolved.is_relative_to(root):
        raise PrototypeObjectStoreError(
            "object_path_invalid",
            "prototype object directory escaped the managed data root",
        )
    return resolved


def _fsync_directory(directory: Path) -> None:
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError as exc:
        raise PrototypeObjectStoreError(
            "object_write_failed",
            "prototype object directory could not be opened for sync",
        ) from exc
    try:
        os.fsync(descriptor)
    except OSError as exc:
        raise PrototypeObjectStoreError(
            "object_write_failed",
            "prototype object directory could not be synced",
        ) from exc
    finally:
        os.close(descriptor)


def _existing_managed_directory(parent: Path, name: str, root: Path) -> Path | None:
    candidate = parent / name
    if candidate.is_symlink():
        raise PrototypeObjectStoreError(
            "object_path_invalid",
            "prototype managed storage contains a symlink",
        )
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise PrototypeObjectStoreError(
            "object_purge_failed",
            "prototype managed storage could not be resolved for deletion",
        ) from exc
    if resolved != candidate or not resolved.is_dir() or not resolved.is_relative_to(root):
        raise PrototypeObjectStoreError(
            "object_path_invalid",
            "prototype managed storage escaped the managed data root",
        )
    return resolved


def _assert_deletable_tree(directory: Path, root: Path) -> None:
    if directory.is_symlink():
        raise PrototypeObjectStoreError(
            "object_path_invalid",
            "prototype managed storage contains a symlink",
        )

    def _raise_walk_error(error: OSError) -> None:
        raise error

    try:
        for current_text, directory_names, file_names in os.walk(
            directory,
            topdown=True,
            followlinks=False,
            onerror=_raise_walk_error,
        ):
            current = Path(current_text)
            resolved = current.resolve(strict=True)
            if resolved != current or not resolved.is_relative_to(root):
                raise PrototypeObjectStoreError(
                    "object_path_invalid",
                    "prototype managed storage escaped the managed data root",
                )
            for name in (*directory_names, *file_names):
                if (current / name).is_symlink():
                    raise PrototypeObjectStoreError(
                        "object_path_invalid",
                        "prototype managed storage contains a symlink",
                    )
    except PrototypeObjectStoreError:
        raise
    except OSError as exc:
        raise PrototypeObjectStoreError(
            "object_purge_failed",
            "prototype managed storage could not be inspected for deletion",
        ) from exc


class PrototypeObjectStore:
    def __init__(self, data_root: Path) -> None:
        self._data_root = data_root

    def write_json(self, project_id: str, value: object) -> PrototypeObjectDescriptor:
        canonical_bytes = canonical_json_bytes(value)
        content_hash = _sha256(canonical_bytes)
        storage_bytes = self._compress(canonical_bytes)
        paths = self._paths(project_id, content_hash)
        temp_path = paths.tmp / f"{uuid4()}.partial"

        try:
            with temp_path.open("xb") as handle:
                handle.write(storage_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            installed = self._install_without_overwrite(temp_path, paths.target)
            if installed:
                _fsync_directory(paths.target.parent)
            actual_storage = paths.target.read_bytes()
        except PrototypeObjectStoreError:
            raise
        except OSError as exc:
            raise PrototypeObjectStoreError(
                "object_write_failed",
                "prototype object could not be written",
            ) from exc
        finally:
            with suppress(OSError):
                temp_path.unlink(missing_ok=True)

        canonical_readback = self._decompress(
            actual_storage,
            max_output_size=len(canonical_bytes),
            code="object_readback_failed",
        )
        if canonical_readback != canonical_bytes:
            code = "object_hash_collision" if not installed else "object_hash_mismatch"
            raise PrototypeObjectStoreError(
                code,
                "prototype object read-back did not match canonical bytes",
            )
        return self._descriptor(
            project_id=project_id,
            content_hash=content_hash,
            storage_bytes=actual_storage,
            target=paths.target,
            storage_key=paths.storage_key,
            canonical_byte_size=len(canonical_bytes),
        )

    def read_canonical_bytes(self, descriptor: PrototypeObjectDescriptor) -> bytes:
        paths = self._paths(descriptor.project_id, descriptor.content_hash)
        if descriptor.storage_key != paths.storage_key:
            raise PrototypeObjectStoreError(
                "object_path_invalid",
                "prototype object storage key does not match its identity",
            )
        if paths.target.is_symlink():
            raise PrototypeObjectStoreError(
                "object_path_invalid",
                "prototype object path contains a symlink",
            )
        try:
            storage_bytes = paths.target.read_bytes()
        except FileNotFoundError as exc:
            raise PrototypeObjectStoreError(
                "object_missing",
                "prototype object is missing",
            ) from exc
        except OSError as exc:
            raise PrototypeObjectStoreError(
                "object_readback_failed",
                "prototype object could not be read",
            ) from exc
        if len(storage_bytes) != descriptor.stored_byte_size:
            raise PrototypeObjectStoreError(
                "object_hash_mismatch",
                "prototype object stored byte size does not match its descriptor",
            )
        if _sha256(storage_bytes) != descriptor.storage_hash:
            raise PrototypeObjectStoreError(
                "object_hash_mismatch",
                "prototype object storage hash does not match its descriptor",
            )
        canonical_bytes = self._decompress(
            storage_bytes,
            max_output_size=descriptor.canonical_byte_size,
            code="object_hash_mismatch",
        )
        if len(canonical_bytes) != descriptor.canonical_byte_size:
            raise PrototypeObjectStoreError(
                "object_hash_mismatch",
                "prototype object canonical byte size does not match its descriptor",
            )
        if _sha256(canonical_bytes) != descriptor.content_hash:
            raise PrototypeObjectStoreError(
                "object_hash_mismatch",
                "prototype object content hash does not match its descriptor",
            )
        return canonical_bytes

    def purge_project_store(self, project_id: str, deletion_operation_id: str) -> None:
        """Remove one project's managed prototype objects, renders, and temporary files."""
        safe_project_id = _safe_project_id(project_id)
        if SAFE_PATH_COMPONENT_RE.fullmatch(deletion_operation_id) is None:
            raise PrototypeObjectStoreError(
                "object_path_invalid",
                "prototype deletion operation ID is not safe for managed storage",
            )
        if self._data_root.is_symlink():
            raise PrototypeObjectStoreError(
                "object_path_invalid",
                "prototype managed data root must not be a symlink",
            )
        try:
            root = self._data_root.resolve(strict=True)
        except FileNotFoundError:
            return
        except OSError as exc:
            raise PrototypeObjectStoreError(
                "object_purge_failed",
                "prototype managed data root could not be resolved for deletion",
            ) from exc
        if not root.is_dir():
            raise PrototypeObjectStoreError(
                "object_path_invalid",
                "prototype managed data root is not a directory",
            )
        projects = _existing_managed_directory(root, "projects", root)
        if projects is None:
            return
        project = _existing_managed_directory(projects, safe_project_id, root)
        if project is None:
            return

        active_store = project / "prototype-store"
        tombstone = project / f"prototype-store-deleting-{deletion_operation_id}"
        existing_tombstone = _existing_managed_directory(
            project,
            tombstone.name,
            root,
        )
        try:
            if existing_tombstone is not None:
                _assert_deletable_tree(existing_tombstone, root)
                shutil.rmtree(existing_tombstone)
                _fsync_directory(project)

            existing_store = _existing_managed_directory(
                project,
                active_store.name,
                root,
            )
            if existing_store is None:
                return
            _assert_deletable_tree(existing_store, root)
            existing_store.rename(tombstone)
            _fsync_directory(project)
            _assert_deletable_tree(tombstone, root)
            shutil.rmtree(tombstone)
            _fsync_directory(project)
        except PrototypeObjectStoreError:
            raise
        except OSError as exc:
            raise PrototypeObjectStoreError(
                "object_purge_failed",
                "prototype managed storage could not be deleted",
            ) from exc

    def _paths(self, project_id: str, content_hash: str) -> _ObjectPaths:
        safe_project_id = _safe_project_id(project_id)
        if SHA256_RE.fullmatch(content_hash) is None:
            raise PrototypeObjectStoreError(
                "object_hash_invalid",
                "prototype object content hash is invalid",
            )
        try:
            self._data_root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise PrototypeObjectStoreError(
                "object_write_failed",
                "prototype managed data root could not be prepared",
            ) from exc
        if self._data_root.is_symlink():
            raise PrototypeObjectStoreError(
                "object_path_invalid",
                "prototype managed data root must not be a symlink",
            )
        try:
            root = self._data_root.resolve(strict=True)
        except OSError as exc:
            raise PrototypeObjectStoreError(
                "object_write_failed",
                "prototype managed data root could not be resolved",
            ) from exc
        projects = _prepare_child_directory(root, "projects", root)
        project = _prepare_child_directory(projects, safe_project_id, root)
        store = _prepare_child_directory(project, "prototype-store", root)
        objects = _prepare_child_directory(store, "objects", root)
        tmp = _prepare_child_directory(store, "tmp", root)
        hex_hash = content_hash.removeprefix("sha256:")
        prefix = _prepare_child_directory(objects, hex_hash[:2], root)
        storage_key = (
            Path("projects")
            / safe_project_id
            / "prototype-store"
            / "objects"
            / hex_hash[:2]
            / f"{hex_hash}.json.zst"
        ).as_posix()
        return _ObjectPaths(
            tmp=tmp,
            target=prefix / f"{hex_hash}.json.zst",
            storage_key=storage_key,
        )

    @staticmethod
    def _install_without_overwrite(temp_path: Path, target: Path) -> bool:
        try:
            os.link(temp_path, target)
        except FileExistsError:
            return False
        except OSError as exc:
            raise PrototypeObjectStoreError(
                "object_write_failed",
                "prototype object could not be installed",
            ) from exc
        return True

    @staticmethod
    def _compress(payload: bytes) -> bytes:
        compressor = zstandard.ZstdCompressor(
            level=ZSTD_COMPRESSION_LEVEL,
            write_checksum=True,
            write_content_size=True,
            write_dict_id=False,
            threads=0,
        )
        return compressor.compress(payload)

    @staticmethod
    def _decompress(payload: bytes, *, max_output_size: int, code: str) -> bytes:
        try:
            return zstandard.ZstdDecompressor().decompress(
                payload,
                max_output_size=max_output_size,
            )
        except zstandard.ZstdError as exc:
            raise PrototypeObjectStoreError(
                code,
                "prototype object could not be decompressed",
            ) from exc

    @staticmethod
    def _descriptor(
        *,
        project_id: str,
        content_hash: str,
        storage_bytes: bytes,
        target: Path,
        storage_key: str,
        canonical_byte_size: int,
    ) -> PrototypeObjectDescriptor:
        try:
            modified_at = target.stat().st_mtime
        except OSError as exc:
            raise PrototypeObjectStoreError(
                "object_readback_failed",
                "prototype object metadata could not be read",
            ) from exc
        return PrototypeObjectDescriptor(
            project_id=project_id,
            content_hash=content_hash,
            media_type="application/json",
            storage_codec="zstd",
            storage_codec_version=STORAGE_CODEC_VERSION,
            canonical_byte_size=canonical_byte_size,
            stored_byte_size=len(storage_bytes),
            storage_hash=_sha256(storage_bytes),
            storage_key=storage_key,
            created_at=datetime.fromtimestamp(modified_at, tz=UTC),
        )


@dataclass(frozen=True, slots=True)
class _ObjectPaths:
    tmp: Path
    target: Path
    storage_key: str
