from __future__ import annotations

import pytest

from app.application.git_service import GENERATION_SNAPSHOT_REF_PREFIX, GitError
from app.application.structured_prototype_deletion_cleanup import (
    StructuredPrototypeDeletionCleanupError,
    StructuredPrototypeDeletionResourceCleaner,
)
from app.domain.models import Project


class _ProjectStore:
    def __init__(self, project: Project | None, trace: list[str]) -> None:
        self._project = project
        self._trace = trace

    async def load_project(self, project_id: str) -> Project | None:
        self._trace.append(f"project:{project_id}")
        return self._project


class _OwnerStore:
    def __init__(self, owner_ids: frozenset[str], trace: list[str]) -> None:
        self._owner_ids = owner_ids
        self._trace = trace

    async def list_generation_snapshot_owner_ids(self) -> frozenset[str]:
        self._trace.append("owners")
        return self._owner_ids


class _SourceControl:
    def __init__(
        self,
        refs: list[tuple[str, str]],
        trace: list[str],
        *,
        fail_delete: bool = False,
    ) -> None:
        self._refs = refs
        self._trace = trace
        self._fail_delete = fail_delete
        self.deleted: list[tuple[str, str, str]] = []

    async def list_generation_snapshot_refs(self, repo_path: str) -> list[tuple[str, str]]:
        self._trace.append(f"refs:{repo_path}")
        return self._refs

    async def delete_generation_snapshot_ref(
        self,
        repo_path: str,
        *,
        snapshot_ref: str,
        expected_object_id: str,
    ) -> None:
        self._trace.append(f"delete:{snapshot_ref}")
        if self._fail_delete:
            raise GitError("snapshot ref changed")
        self.deleted.append((repo_path, snapshot_ref, expected_object_id))


@pytest.mark.asyncio
async def test_deletion_cleaner_removes_only_unowned_snapshot_refs_after_observing_refs() -> None:
    trace: list[str] = []
    retained_job_id = "11111111-1111-1111-1111-111111111111"
    deleted_job_id = "22222222-2222-2222-2222-222222222222"
    retained_ref = f"{GENERATION_SNAPSHOT_REF_PREFIX}{retained_job_id}"
    deleted_ref = f"{GENERATION_SNAPSHOT_REF_PREFIX}{deleted_job_id}"
    source = _SourceControl(
        [(retained_ref, "a" * 40), (deleted_ref, "b" * 40)],
        trace,
    )
    cleaner = StructuredPrototypeDeletionResourceCleaner(
        project_store=_ProjectStore(
            Project(id="project-1", name="Project", repo_path="/repo"),
            trace,
        ),
        owner_store=_OwnerStore(frozenset({retained_job_id}), trace),
        source_control=source,
    )

    await cleaner.purge_generation_resources("project-1")

    assert trace == [
        "project:project-1",
        "refs:/repo",
        "owners",
        f"delete:{deleted_ref}",
    ]
    assert source.deleted == [("/repo", deleted_ref, "b" * 40)]


@pytest.mark.asyncio
async def test_deletion_cleaner_fails_closed_when_snapshot_ref_cas_fails() -> None:
    trace: list[str] = []
    job_id = "22222222-2222-2222-2222-222222222222"
    source = _SourceControl(
        [(f"{GENERATION_SNAPSHOT_REF_PREFIX}{job_id}", "b" * 40)],
        trace,
        fail_delete=True,
    )
    cleaner = StructuredPrototypeDeletionResourceCleaner(
        project_store=_ProjectStore(
            Project(id="project-1", name="Project", repo_path="/repo"),
            trace,
        ),
        owner_store=_OwnerStore(frozenset(), trace),
        source_control=source,
    )

    with pytest.raises(StructuredPrototypeDeletionCleanupError) as exc_info:
        await cleaner.purge_generation_resources("project-1")

    assert exc_info.value.code == "prototype_cleanup_pending"
    assert source.deleted == []
