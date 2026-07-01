from datetime import datetime

import pytest

from app.adapters.async_sqlite_store import AsyncSQLiteStore
from app.adapters.sqlite_store import SQLiteStore
from app.domain.models import SelfImprovementApplicationEvent, SelfImprovementProposal


def _proposal(
    proposal_id: str = "proposal-1",
    *,
    project_id: str = "project-1",
    issue_id: str = "issue-1",
    target_kind: str = "runtime_tooling",
    status: str = "proposed",
    fingerprint: str = "project-1|issue-1|runtime_tooling|qa-failure",
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> SelfImprovementProposal:
    return SelfImprovementProposal(
        id=proposal_id,
        project_id=project_id,
        issue_id=issue_id,
        target_kind=target_kind,
        title="Capture QA command failure contract",
        recommendation="Record a backend contract when QA command execution fails.",
        evidence_json='[{"kind":"qa_report","path":"issues/issue-1/qa.json"}]',
        severity="medium",
        confidence=0.8,
        status=status,
        fingerprint=fingerprint,
        created_at=created_at or datetime(2026, 6, 8, 10, 0, 0),
        updated_at=updated_at or datetime(2026, 6, 8, 10, 0, 0),
    )


def _application_event(
    event_id: str = "event-1",
    *,
    proposal_id: str = "proposal-1",
    project_id: str = "project-1",
    issue_id: str = "issue-1",
    target_kind: str = "project_memory",
    action: str = "apply",
    status: str = "succeeded",
    path: str | None = ".agent-collab/team_notes.md",
    content_sha256: str | None = "a" * 64,
    result_json: str = '{"already_present": false}',
    error: str | None = None,
    created_at: datetime | None = None,
) -> SelfImprovementApplicationEvent:
    return SelfImprovementApplicationEvent(
        id=event_id,
        proposal_id=proposal_id,
        project_id=project_id,
        issue_id=issue_id,
        target_kind=target_kind,
        action=action,
        status=status,
        path=path,
        content_sha256=content_sha256,
        result_json=result_json,
        error=error,
        created_at=created_at or datetime(2026, 6, 8, 10, 0, 0),
    )


def _assert_preserved_except_status_and_updated_at(
    before: SelfImprovementProposal,
    after: SelfImprovementProposal,
) -> None:
    for field in (
        "id",
        "project_id",
        "issue_id",
        "target_kind",
        "title",
        "recommendation",
        "evidence_json",
        "severity",
        "confidence",
        "fingerprint",
        "created_at",
    ):
        assert getattr(after, field) == getattr(before, field)


@pytest.mark.asyncio
async def test_async_store_saves_lists_filters_and_dedupes(tmp_path):
    store = AsyncSQLiteStore(tmp_path / "console.db")
    await store.save_self_improvement_proposal(_proposal())
    await store.save_self_improvement_proposal(
        _proposal(
            "proposal-2",
            issue_id="issue-2",
            target_kind="code_spec",
            status="accepted",
            fingerprint="project-1|issue-2|code_spec|qa-failure",
        )
    )
    await store.save_self_improvement_proposal(
        _proposal(
            "proposal-1b",
            status="proposed",
            fingerprint="project-1|issue-1|runtime_tooling|qa-failure",
        )
    )

    project_rows = await store.list_self_improvement_proposals(project_id="project-1")
    issue_rows = await store.list_self_improvement_proposals(
        project_id="project-1", issue_id="issue-1"
    )
    status_rows = await store.list_self_improvement_proposals(
        project_id="project-1", status="accepted"
    )
    limited_rows = await store.list_self_improvement_proposals(project_id="project-1", limit=1)
    await store.close()

    assert len(project_rows) == 2
    assert len(issue_rows) == 1
    assert issue_rows[0].id == "proposal-1b"
    assert issue_rows[0].fingerprint == "project-1|issue-1|runtime_tooling|qa-failure"
    assert [row.status for row in status_rows] == ["accepted"]
    assert len(limited_rows) == 1


@pytest.mark.asyncio
async def test_async_store_loads_and_updates_self_improvement_proposal_status(tmp_path):
    store = AsyncSQLiteStore(tmp_path / "console.db")
    original_time = datetime(2020, 1, 1, 12, 0, 0)
    proposal = _proposal(created_at=original_time, updated_at=original_time)
    await store.save_self_improvement_proposal(proposal)

    loaded = await store.load_self_improvement_proposal("proposal-1")
    updated = await store.update_self_improvement_proposal_status("proposal-1", "accepted")
    missing = await store.update_self_improvement_proposal_status("missing", "accepted")
    await store.close()

    assert loaded == proposal
    assert missing is None
    assert updated is not None
    assert updated.status == "accepted"
    assert updated.updated_at is not None
    assert updated.updated_at > original_time
    _assert_preserved_except_status_and_updated_at(proposal, updated)


@pytest.mark.asyncio
async def test_async_store_saves_lists_filters_and_limits_self_improvement_application_events(
    tmp_path,
):
    store = AsyncSQLiteStore(tmp_path / "console.db")
    await store.save_self_improvement_application_event(
        _application_event("event-1", created_at=datetime(2026, 6, 8, 10, 0, 0))
    )
    await store.save_self_improvement_application_event(
        _application_event(
            "event-2",
            proposal_id="proposal-2",
            issue_id="issue-2",
            action="rollback",
            status="failed",
            content_sha256=None,
            result_json="{}",
            error="Self-improvement proposal must be applied before rollback",
            created_at=datetime(2026, 6, 8, 10, 1, 0),
        )
    )
    await store.save_self_improvement_application_event(
        _application_event(
            "event-3",
            proposal_id="proposal-3",
            project_id="project-2",
            issue_id="issue-3",
            created_at=datetime(2026, 6, 8, 10, 2, 0),
        )
    )

    project_rows = await store.list_self_improvement_application_events(project_id="project-1")
    proposal_rows = await store.list_self_improvement_application_events(proposal_id="proposal-1")
    limited_rows = await store.list_self_improvement_application_events(
        project_id="project-1", limit=1
    )
    await store.close()

    assert [row.id for row in project_rows] == ["event-2", "event-1"]
    assert [row.id for row in proposal_rows] == ["event-1"]
    assert [row.id for row in limited_rows] == ["event-2"]
    assert project_rows[0].action == "rollback"
    assert project_rows[0].status == "failed"
    assert project_rows[0].error == "Self-improvement proposal must be applied before rollback"
    assert project_rows[1].result_json == '{"already_present": false}'


def test_sync_store_saves_lists_filters_and_dedupes(tmp_path):
    store = SQLiteStore(tmp_path / "console.db")
    store.save_self_improvement_proposal(_proposal())
    store.save_self_improvement_proposal(
        _proposal(
            "proposal-2",
            issue_id="issue-2",
            target_kind="code_spec",
            status="accepted",
            fingerprint="project-1|issue-2|code_spec|qa-failure",
        )
    )
    store.save_self_improvement_proposal(
        _proposal(
            "proposal-1b",
            status="proposed",
            fingerprint="project-1|issue-1|runtime_tooling|qa-failure",
        )
    )

    assert len(store.list_self_improvement_proposals(project_id="project-1")) == 2
    issue_rows = store.list_self_improvement_proposals(project_id="project-1", issue_id="issue-1")
    assert len(issue_rows) == 1
    assert issue_rows[0].id == "proposal-1b"
    assert [
        row.status
        for row in store.list_self_improvement_proposals(project_id="project-1", status="accepted")
    ] == ["accepted"]


def test_sync_store_loads_and_updates_self_improvement_proposal_status(tmp_path):
    store = SQLiteStore(tmp_path / "console.db")
    original_time = datetime(2020, 1, 1, 12, 0, 0)
    proposal = _proposal(created_at=original_time, updated_at=original_time)
    store.save_self_improvement_proposal(proposal)

    loaded = store.load_self_improvement_proposal("proposal-1")
    updated = store.update_self_improvement_proposal_status("proposal-1", "accepted")
    missing = store.update_self_improvement_proposal_status("missing", "accepted")

    assert loaded == proposal
    assert missing is None
    assert updated is not None
    assert updated.status == "accepted"
    assert updated.updated_at is not None
    assert updated.updated_at > original_time
    _assert_preserved_except_status_and_updated_at(proposal, updated)


def test_sync_store_saves_lists_filters_and_limits_self_improvement_application_events(tmp_path):
    store = SQLiteStore(tmp_path / "console.db")
    store.save_self_improvement_application_event(
        _application_event("event-1", created_at=datetime(2026, 6, 8, 10, 0, 0))
    )
    store.save_self_improvement_application_event(
        _application_event(
            "event-2",
            proposal_id="proposal-2",
            issue_id="issue-2",
            action="rollback",
            status="failed",
            content_sha256=None,
            result_json="{}",
            error="Self-improvement proposal must be applied before rollback",
            created_at=datetime(2026, 6, 8, 10, 1, 0),
        )
    )
    store.save_self_improvement_application_event(
        _application_event(
            "event-3",
            proposal_id="proposal-3",
            project_id="project-2",
            issue_id="issue-3",
            created_at=datetime(2026, 6, 8, 10, 2, 0),
        )
    )

    project_rows = store.list_self_improvement_application_events(project_id="project-1")
    proposal_rows = store.list_self_improvement_application_events(proposal_id="proposal-1")
    limited_rows = store.list_self_improvement_application_events(project_id="project-1", limit=1)

    assert [row.id for row in project_rows] == ["event-2", "event-1"]
    assert [row.id for row in proposal_rows] == ["event-1"]
    assert [row.id for row in limited_rows] == ["event-2"]
    assert project_rows[0].action == "rollback"
    assert project_rows[0].status == "failed"
    assert project_rows[0].error == "Self-improvement proposal must be applied before rollback"
    assert project_rows[1].result_json == '{"already_present": false}'
