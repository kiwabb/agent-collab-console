from __future__ import annotations

from typing import Protocol

from app.application.git_service import GENERATION_SNAPSHOT_REF_PREFIX, GitError
from app.domain.models import Project


class StructuredPrototypeDeletionCleanupError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class PrototypeDeletionProjectStore(Protocol):
    async def load_project(self, project_id: str) -> Project | None: ...


class PrototypeDeletionOwnerStore(Protocol):
    async def list_generation_snapshot_owner_ids(self) -> frozenset[str]: ...


class PrototypeDeletionSourceControl(Protocol):
    async def list_generation_snapshot_refs(
        self,
        repo_path: str,
    ) -> list[tuple[str, str]]: ...

    async def delete_generation_snapshot_ref(
        self,
        repo_path: str,
        *,
        snapshot_ref: str,
        expected_object_id: str,
    ) -> None: ...


class StructuredPrototypeDeletionResourceCleaner:
    def __init__(
        self,
        *,
        project_store: PrototypeDeletionProjectStore,
        owner_store: PrototypeDeletionOwnerStore,
        source_control: PrototypeDeletionSourceControl,
    ) -> None:
        self._project_store = project_store
        self._owner_store = owner_store
        self._source_control = source_control

    async def purge_generation_resources(self, project_id: str) -> None:
        project = await self._project_store.load_project(project_id)
        if project is None:
            return
        try:
            snapshot_refs = await self._source_control.list_generation_snapshot_refs(
                project.repo_path
            )
            # Snapshot refs are observed before owners. A ref created after this read is never
            # deleted by this sweep, while an in-flight job operation already protects an older
            # observed ref before its durable job row is inserted.
            owner_ids = await self._owner_store.list_generation_snapshot_owner_ids()
            for snapshot_ref, object_id in snapshot_refs:
                job_id = snapshot_ref.removeprefix(GENERATION_SNAPSHOT_REF_PREFIX)
                if job_id in owner_ids:
                    continue
                await self._source_control.delete_generation_snapshot_ref(
                    project.repo_path,
                    snapshot_ref=snapshot_ref,
                    expected_object_id=object_id,
                )
        except GitError as exc:
            raise StructuredPrototypeDeletionCleanupError(
                "prototype_cleanup_pending",
                "prototype generation snapshot resources could not be deleted",
            ) from exc
