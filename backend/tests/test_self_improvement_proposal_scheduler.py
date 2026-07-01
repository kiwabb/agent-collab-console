from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from app.application.self_improvement_proposal_scheduler import (
    SelfImprovementProposalSchedulerResult,
    SelfImprovementProposalSchedulerSummary,
    get_self_improvement_proposal_scheduler_status,
    reset_self_improvement_proposal_scheduler_status,
    run_self_improvement_proposal_scheduler_loop,
    run_self_improvement_proposal_tick,
)
from app.domain.models import SelfImprovementApplicationEvent, SelfImprovementProposal


def _proposal(
    proposal_id: str,
    *,
    project_id: str = "project-1",
    target_kind: str = "runtime_tooling",
    status: str = "accepted",
) -> SelfImprovementProposal:
    return SelfImprovementProposal(
        id=proposal_id,
        project_id=project_id,
        issue_id=f"issue-{proposal_id}",
        target_kind=target_kind,
        title=f"Proposal {proposal_id}",
        recommendation="Open a follow-up task.",
        status=status,
        fingerprint=f"{project_id}|issue-{proposal_id}|{target_kind}|rule",
        created_at=datetime(2026, 6, 9, 9, 0, 0),
    )


def _event(
    proposal: SelfImprovementProposal,
    *,
    action: str = "start_conductor",
    status: str = "succeeded",
) -> SelfImprovementApplicationEvent:
    return SelfImprovementApplicationEvent(
        id=f"event-{proposal.id}",
        proposal_id=proposal.id,
        project_id=proposal.project_id,
        issue_id=proposal.issue_id,
        target_kind=proposal.target_kind,
        action=action,
        status=status,
        result_json="{}",
        created_at=datetime(2026, 6, 9, 9, 1, 0),
    )


class _Store:
    def __init__(self, proposals: list[SelfImprovementProposal], events=None) -> None:
        self.proposals = list(proposals)
        self.events = events or {}
        self.list_calls: list[dict] = []

    async def list_self_improvement_proposals(
        self, *, project_id=None, issue_id=None, status=None, limit=None
    ):
        self.list_calls.append(
            {"project_id": project_id, "issue_id": issue_id, "status": status, "limit": limit}
        )
        rows = [
            proposal for proposal in self.proposals if status is None or proposal.status == status
        ]
        return rows[:limit] if limit is not None else rows

    async def list_self_improvement_application_events(
        self, *, project_id=None, proposal_id=None, limit=None
    ):
        rows = list(self.events.get(proposal_id, []))
        return rows[:limit] if limit is not None else rows


@pytest.mark.asyncio
async def test_self_improvement_proposal_tick_activates_eligible_accepted_non_memory_proposals():
    proposal = _proposal("proposal-1")
    calls: list[tuple[str, str, bool]] = []

    async def activate(project_id: str, proposal_id: str, *, start_conductor: bool):
        calls.append((project_id, proposal_id, start_conductor))
        return {"activation": {"conductor": {"started": True, "already_running": False}}}

    summary = await run_self_improvement_proposal_tick(
        _Store([proposal]), activate_fn=activate, limit=10
    )

    assert calls == [("project-1", "proposal-1", True)]
    assert summary.to_dict()["counts"] == {"started": 1}
    assert summary.results[0].proposal_id == "proposal-1"


@pytest.mark.asyncio
async def test_self_improvement_proposal_tick_skips_project_memory_proposals():
    proposal = _proposal("proposal-memory", target_kind="project_memory")
    calls: list[str] = []

    async def activate(project_id: str, proposal_id: str, *, start_conductor: bool):
        calls.append(proposal_id)
        return {}

    summary = await run_self_improvement_proposal_tick(
        _Store([proposal]), activate_fn=activate, limit=10
    )

    assert calls == []
    assert summary.to_dict()["counts"] == {"skipped_project_memory": 1}
    assert summary.results[0].proposal_id == "proposal-memory"


@pytest.mark.asyncio
async def test_self_improvement_proposal_tick_skips_already_started_proposals():
    proposal = _proposal("proposal-started")
    calls: list[str] = []
    store = _Store([proposal], events={proposal.id: [_event(proposal)]})

    async def activate(project_id: str, proposal_id: str, *, start_conductor: bool):
        calls.append(proposal_id)
        return {}

    summary = await run_self_improvement_proposal_tick(store, activate_fn=activate, limit=10)

    assert calls == []
    assert summary.to_dict()["counts"] == {"skipped_already_started": 1}
    assert summary.results[0].proposal_id == "proposal-started"


@pytest.mark.asyncio
async def test_self_improvement_proposal_tick_isolates_activation_failures_and_continues():
    first = _proposal("proposal-fail")
    second = _proposal("proposal-ok")
    calls: list[str] = []

    async def activate(project_id: str, proposal_id: str, *, start_conductor: bool):
        calls.append(proposal_id)
        if proposal_id == first.id:
            raise RuntimeError("synthetic activation failure")
        return {"activation": {"conductor": {"started": True, "already_running": False}}}

    summary = await run_self_improvement_proposal_tick(
        _Store([first, second]), activate_fn=activate, limit=10
    )

    assert calls == ["proposal-fail", "proposal-ok"]
    assert summary.to_dict()["counts"] == {"failed": 1, "started": 1}
    assert summary.results[0].proposal_id == "proposal-fail"
    assert summary.results[0].error == "synthetic activation failure"
    assert summary.results[1].proposal_id == "proposal-ok"


@pytest.mark.asyncio
async def test_self_improvement_proposal_tick_honors_limit():
    proposals = [_proposal("proposal-1"), _proposal("proposal-2"), _proposal("proposal-3")]
    calls: list[str] = []
    store = _Store(proposals)

    async def activate(project_id: str, proposal_id: str, *, start_conductor: bool):
        calls.append(proposal_id)
        return {"activation": {"conductor": {"already_running": True}}}

    summary = await run_self_improvement_proposal_tick(store, activate_fn=activate, limit=2)

    assert store.list_calls == [
        {"project_id": None, "issue_id": None, "status": "accepted", "limit": 2}
    ]
    assert calls == ["proposal-1", "proposal-2"]
    assert summary.to_dict()["counts"] == {"already_running": 2}


@pytest.mark.asyncio
async def test_self_improvement_proposal_scheduler_loop_repeats_after_each_sleep():
    reset_self_improvement_proposal_scheduler_status()
    ticks = 0
    sleeps: list[float] = []

    async def tick(store, *, activate_fn, limit=None):
        nonlocal ticks
        ticks += 1
        return SelfImprovementProposalSchedulerSummary()

    async def sleep(interval: float) -> None:
        sleeps.append(interval)
        if len(sleeps) == 2:
            raise asyncio.CancelledError

    async def activate(project_id: str, proposal_id: str, *, start_conductor: bool):
        return {}

    with pytest.raises(asyncio.CancelledError):
        await run_self_improvement_proposal_scheduler_loop(
            _Store([]),
            interval_s=12.5,
            limit=3,
            tick_fn=tick,
            sleep_fn=sleep,
            activate_fn=activate,
        )

    assert ticks == 2
    assert sleeps == [12.5, 12.5]


@pytest.mark.asyncio
async def test_self_improvement_proposal_scheduler_loop_survives_tick_exception():
    reset_self_improvement_proposal_scheduler_status()
    attempts = 0
    sleeps = 0

    async def tick(store, *, activate_fn, limit=None):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("store temporarily unavailable")
        return SelfImprovementProposalSchedulerSummary()

    async def sleep(interval: float) -> None:
        nonlocal sleeps
        sleeps += 1
        if sleeps == 2:
            raise asyncio.CancelledError

    async def activate(project_id: str, proposal_id: str, *, start_conductor: bool):
        return {}

    with pytest.raises(asyncio.CancelledError):
        await run_self_improvement_proposal_scheduler_loop(
            _Store([]),
            interval_s=1,
            tick_fn=tick,
            sleep_fn=sleep,
            activate_fn=activate,
        )

    assert attempts == 2
    assert sleeps == 2


@pytest.mark.asyncio
async def test_self_improvement_proposal_scheduler_loop_propagates_cancellation_from_tick():
    reset_self_improvement_proposal_scheduler_status()

    async def tick(store, *, activate_fn, limit=None):
        raise asyncio.CancelledError

    async def sleep(interval: float) -> None:
        raise AssertionError("sleep should not run after cancellation")

    async def activate(project_id: str, proposal_id: str, *, start_conductor: bool):
        return {}

    with pytest.raises(asyncio.CancelledError):
        await run_self_improvement_proposal_scheduler_loop(
            _Store([]),
            tick_fn=tick,
            sleep_fn=sleep,
            activate_fn=activate,
        )


@pytest.mark.asyncio
async def test_self_improvement_proposal_scheduler_status_records_successful_tick():
    reset_self_improvement_proposal_scheduler_status()

    async def tick(store, *, activate_fn, limit=None):
        assert limit == 3
        return SelfImprovementProposalSchedulerSummary(
            results=[
                SelfImprovementProposalSchedulerResult(
                    proposal_id="proposal-1",
                    project_id="project-1",
                    target_kind="runtime_tooling",
                    status="started",
                )
            ]
        )

    async def sleep(interval: float) -> None:
        raise asyncio.CancelledError

    async def activate(project_id: str, proposal_id: str, *, start_conductor: bool):
        return {}

    with pytest.raises(asyncio.CancelledError):
        await run_self_improvement_proposal_scheduler_loop(
            _Store([]),
            interval_s=9,
            limit=3,
            tick_fn=tick,
            sleep_fn=sleep,
            activate_fn=activate,
        )

    status = get_self_improvement_proposal_scheduler_status()
    assert status["configured"] is True
    assert status["interval_s"] == 9
    assert status["limit"] == 3
    assert status["running"] is False
    assert status["tick_count"] == 1
    assert status["last_started_at"]
    assert status["last_completed_at"]
    assert status["last_error"] is None
    assert status["last_summary_counts"] == {"started": 1}


@pytest.mark.asyncio
async def test_self_improvement_proposal_scheduler_status_records_failed_tick():
    reset_self_improvement_proposal_scheduler_status()

    async def tick(store, *, activate_fn, limit=None):
        raise RuntimeError("store temporarily unavailable")

    async def sleep(interval: float) -> None:
        raise asyncio.CancelledError

    async def activate(project_id: str, proposal_id: str, *, start_conductor: bool):
        return {}

    with pytest.raises(asyncio.CancelledError):
        await run_self_improvement_proposal_scheduler_loop(
            _Store([]),
            interval_s=5,
            limit=2,
            tick_fn=tick,
            sleep_fn=sleep,
            activate_fn=activate,
        )

    status = get_self_improvement_proposal_scheduler_status()
    assert status["running"] is False
    assert status["tick_count"] == 1
    assert status["last_completed_at"]
    assert status["last_error"] == "RuntimeError: store temporarily unavailable"
    assert status["last_summary_counts"] == {}


@pytest.mark.asyncio
async def test_self_improvement_proposal_scheduler_status_clears_running_on_tick_cancellation():
    reset_self_improvement_proposal_scheduler_status()

    async def tick(store, *, activate_fn, limit=None):
        raise asyncio.CancelledError

    async def sleep(interval: float) -> None:
        raise AssertionError("sleep should not run after cancellation")

    async def activate(project_id: str, proposal_id: str, *, start_conductor: bool):
        return {}

    with pytest.raises(asyncio.CancelledError):
        await run_self_improvement_proposal_scheduler_loop(
            _Store([]),
            interval_s=5,
            limit=2,
            tick_fn=tick,
            sleep_fn=sleep,
            activate_fn=activate,
        )

    status = get_self_improvement_proposal_scheduler_status()
    assert status["running"] is False
    assert status["tick_count"] == 0
    assert status["last_completed_at"] is None
