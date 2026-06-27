from __future__ import annotations  # noqa: I001

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
import logging
from typing import Protocol

from app.application import timeouts
from app.domain.models import SelfImprovementApplicationEvent, SelfImprovementProposal


logger = logging.getLogger(__name__)


class SelfImprovementProposalSchedulerStore(Protocol):
    async def list_self_improvement_proposals(
        self,
        *,
        project_id: str | None = None,
        issue_id: str | None = None,
        status: str | None = None,
        limit: int | None = None,
    ) -> list[SelfImprovementProposal]: ...

    async def list_self_improvement_application_events(
        self,
        *,
        project_id: str | None = None,
        proposal_id: str | None = None,
        limit: int | None = None,
    ) -> list[SelfImprovementApplicationEvent]: ...


class SelfImprovementProposalActivationFn(Protocol):
    async def __call__(
        self,
        project_id: str,
        proposal_id: str,
        *,
        start_conductor: bool,
    ) -> dict[str, object]: ...


class SelfImprovementProposalTickFn(Protocol):
    async def __call__(
        self,
        store: SelfImprovementProposalSchedulerStore,
        *,
        activate_fn: SelfImprovementProposalActivationFn,
        limit: int | None = None,
    ) -> SelfImprovementProposalSchedulerSummary: ...


class SelfImprovementProposalSleepFn(Protocol):
    async def __call__(self, interval: float) -> None: ...


@dataclass
class SelfImprovementProposalSchedulerStatus:
    configured: bool = True
    interval_s: float = field(default_factory=timeouts.self_improvement_proposal_interval_s)
    limit: int = field(default_factory=timeouts.self_improvement_proposal_limit)
    running: bool = False
    tick_count: int = 0
    last_started_at: datetime | None = None
    last_completed_at: datetime | None = None
    last_error: str | None = None
    last_summary_counts: dict[str, int] = field(default_factory=dict)

    def mark_started(self, *, interval_s: float, limit: int) -> None:
        self.configured = True
        self.interval_s = interval_s
        self.limit = limit
        self.running = True
        self.last_started_at = datetime.now()

    def mark_completed(self, summary: SelfImprovementProposalSchedulerSummary) -> None:
        self.running = False
        self.tick_count += 1
        self.last_completed_at = datetime.now()
        self.last_error = None
        self.last_summary_counts = summary.counts

    def mark_failed(self, exc: Exception) -> None:
        self.running = False
        self.tick_count += 1
        self.last_completed_at = datetime.now()
        self.last_error = f"{type(exc).__name__}: {exc}"
        self.last_summary_counts = {}

    def mark_cancelled(self) -> None:
        self.running = False

    def to_dict(self) -> dict[str, object]:
        return {
            "configured": self.configured,
            "interval_s": self.interval_s,
            "limit": self.limit,
            "running": self.running,
            "tick_count": self.tick_count,
            "last_started_at": self.last_started_at.isoformat() if self.last_started_at else None,
            "last_completed_at": self.last_completed_at.isoformat()
            if self.last_completed_at
            else None,
            "last_error": self.last_error,
            "last_summary_counts": dict(self.last_summary_counts),
        }


_scheduler_status = SelfImprovementProposalSchedulerStatus()


def reset_self_improvement_proposal_scheduler_status() -> None:
    global _scheduler_status
    _scheduler_status = SelfImprovementProposalSchedulerStatus()


def get_self_improvement_proposal_scheduler_status() -> dict[str, object]:
    return _scheduler_status.to_dict()


@dataclass(frozen=True)
class SelfImprovementProposalSchedulerResult:
    proposal_id: str
    project_id: str
    target_kind: str
    status: str
    result: dict[str, object] | None = None
    error: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "proposal_id": self.proposal_id,
            "project_id": self.project_id,
            "target_kind": self.target_kind,
            "status": self.status,
            "result": self.result or {},
            "error": self.error,
        }


@dataclass(frozen=True)
class SelfImprovementProposalSchedulerSummary:
    results: list[SelfImprovementProposalSchedulerResult] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for result in self.results:
            counts[result.status] = counts.get(result.status, 0) + 1
        return counts

    def to_dict(self) -> dict[str, object]:
        return {
            "counts": self.counts,
            "results": [result.to_dict() for result in self.results],
        }


def _activation_status(result: Mapping[str, object]) -> str:
    activation = result.get("activation")
    if not isinstance(activation, Mapping):
        return "activated"
    conductor = activation.get("conductor")
    if not isinstance(conductor, Mapping):
        return "activated"
    if conductor.get("started") is True:
        return "started"
    if conductor.get("already_running") is True:
        return "already_running"
    return "activated"


async def _has_succeeded_conductor_start(
    store: SelfImprovementProposalSchedulerStore,
    proposal: SelfImprovementProposal,
) -> bool:
    events = await store.list_self_improvement_application_events(
        project_id=proposal.project_id,
        proposal_id=proposal.id,
        limit=100,
    )
    return any(
        event.action == "start_conductor" and event.status == "succeeded" for event in events
    )


async def run_self_improvement_proposal_tick(
    store: SelfImprovementProposalSchedulerStore,
    *,
    activate_fn: SelfImprovementProposalActivationFn,
    limit: int | None = None,
) -> SelfImprovementProposalSchedulerSummary:
    proposals = await store.list_self_improvement_proposals(status="accepted", limit=limit)

    results: list[SelfImprovementProposalSchedulerResult] = []
    for proposal in proposals:
        if proposal.target_kind == "project_memory":
            results.append(
                SelfImprovementProposalSchedulerResult(
                    proposal_id=proposal.id,
                    project_id=proposal.project_id,
                    target_kind=proposal.target_kind,
                    status="skipped_project_memory",
                )
            )
            continue
        if await _has_succeeded_conductor_start(store, proposal):
            results.append(
                SelfImprovementProposalSchedulerResult(
                    proposal_id=proposal.id,
                    project_id=proposal.project_id,
                    target_kind=proposal.target_kind,
                    status="skipped_already_started",
                )
            )
            continue
        try:
            activation = await activate_fn(proposal.project_id, proposal.id, start_conductor=True)
        except Exception as exc:  # noqa: BLE001, RUF100
            logger.exception(
                "self-improvement proposal scheduler activation failed project_id=%s proposal_id=%s",
                proposal.project_id,
                proposal.id,
            )
            results.append(
                SelfImprovementProposalSchedulerResult(
                    proposal_id=proposal.id,
                    project_id=proposal.project_id,
                    target_kind=proposal.target_kind,
                    status="failed",
                    error=str(exc) or exc.__class__.__name__,
                )
            )
            continue
        results.append(
            SelfImprovementProposalSchedulerResult(
                proposal_id=proposal.id,
                project_id=proposal.project_id,
                target_kind=proposal.target_kind,
                status=_activation_status(activation),
                result=activation,
            )
        )

    return SelfImprovementProposalSchedulerSummary(results=results)


async def run_self_improvement_proposal_scheduler_loop(
    store: SelfImprovementProposalSchedulerStore,
    *,
    activate_fn: SelfImprovementProposalActivationFn,
    event_bus: object | None = None,
    interval_s: float | None = None,
    limit: int | None = None,
    tick_fn: SelfImprovementProposalTickFn = run_self_improvement_proposal_tick,
    sleep_fn: SelfImprovementProposalSleepFn = asyncio.sleep,
) -> None:
    _ = event_bus
    interval = (
        interval_s if interval_s is not None else timeouts.self_improvement_proposal_interval_s()
    )
    proposal_limit = limit if limit is not None else timeouts.self_improvement_proposal_limit()

    try:
        while True:
            _scheduler_status.mark_started(interval_s=interval, limit=proposal_limit)
            try:
                summary = await tick_fn(store, activate_fn=activate_fn, limit=proposal_limit)
            except asyncio.CancelledError:
                _scheduler_status.mark_cancelled()
                raise
            except Exception as exc:  # noqa: BLE001, RUF100
                _scheduler_status.mark_failed(exc)
                logger.exception("self-improvement proposal scheduler tick failed")
            else:
                _scheduler_status.mark_completed(summary)
            await sleep_fn(interval)
    except asyncio.CancelledError:
        raise
