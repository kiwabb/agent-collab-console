from __future__ import annotations

"""Per-issue cost/budget awareness (cost-aware conductor scheduling, PR2 + PR3).

Cost is recorded after the fact on every ``ExecutionProcess`` row
(``total_cost_usd``), and running processes reserve an estimated in-flight
amount. PR2 turned that record into a *decision-time* input for
the Conductor: aggregate the spend an issue has already accrued, resolve its
budget (explicit per-issue value, else the global default from ``timeouts``),
and render a short, human-readable summary that the conductor loop injects into
its system prompt so the orchestrating brain can *see* how much budget remains.

PR3 makes the budget *steer* decisions:
  - candidate model unit prices (PR1 price fields) are injected, sorted cheap →
    expensive, so the Conductor can pick a model by cost;
  - at the soft-warning threshold the block escalates to warning tone (prefer
    cheaper models / dispatch less);
  - over budget it escalates to a strong wind-down steer and conductor_tools
    applies a dispatch-time hard gate that rejects new subagents before task,
    node, execution process, or batch worktree creation. The loop is NEVER
    hard-killed here — that is the max_wall ceiling's job; only new dispatch is
    blocked.

Aggregation rule: terminal runs contribute exact spend. In-flight ``Running``
rows contribute a separate conservative reservation used for new-dispatch
decisions, while the exact terminal total remains visible as ``actual_spent``.
"""
from collections.abc import Awaitable, Mapping, Sequence  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from typing import Protocol, TypedDict  # noqa: E402

from app.application import timeouts  # noqa: E402
from app.domain.models import CodexIssue, RuntimeCatalog  # noqa: E402

# Terminal execution-process states whose cost is final and safe to sum.
COMPLETED_PROCESS_STATES = frozenset({"Completed", "Failed", "Killed", "Cancelled", "Canceled"})


type MaybeAwaitable[T] = T | Awaitable[T]


class IssueBudgetPayload(TypedDict):
    issue_id: str
    spent_usd: float
    reserved_usd: float
    effective_spend_usd: float
    budget_usd: float
    remaining_usd: float | None
    used_ratio: float | None
    soft_warn: bool
    over_budget: bool
    soft_warn_ratio: float
    has_ceiling: bool
    budget_source: str


class BudgetSteeringEvent(TypedDict, total=False):
    type: str
    issue_id: str
    spent_usd: float
    reserved_usd: float
    effective_spend_usd: float
    budget_usd: float
    remaining_usd: float
    used_ratio: float
    budget_source: str
    soft_warn_ratio: float


class BudgetTaskObject(Protocol):
    id: object


BudgetTaskRow = Mapping[str, object] | BudgetTaskObject


class BudgetExecutionProcess(Protocol):
    status: str
    total_cost_usd: float | None


class BudgetStore(Protocol):
    def list_codex_tasks(self, *, issue_id: str | None = None) -> MaybeAwaitable[Sequence[BudgetTaskRow]]: ...

    def list_execution_processes(
        self, session_id: str | None = None, task_id: str | None = None
    ) -> MaybeAwaitable[Sequence[BudgetExecutionProcess]]: ...


@dataclass
class IssueBudgetStatus:
    """A decision-time snapshot of an issue's budget vs accrued spend."""

    issue_id: str
    spent_usd: float
    budget_usd: float  # <= 0 means "no ceiling" (unlimited)
    budget_source: str  # "issue" | "default"
    soft_warn_ratio: float
    reserved_usd: float = 0.0

    @property
    def has_ceiling(self) -> bool:
        return self.budget_usd > 0

    @property
    def remaining_usd(self) -> float | None:
        """Remaining budget; ``None`` when there is no ceiling."""
        if not self.has_ceiling:
            return None
        return self.budget_usd - self.effective_spend_usd

    @property
    def effective_spend_usd(self) -> float:
        return self.spent_usd + self.reserved_usd

    @property
    def used_ratio(self) -> float | None:
        """Fraction of budget consumed; ``None`` when there is no ceiling."""
        if not self.has_ceiling:
            return None
        return self.effective_spend_usd / self.budget_usd

    @property
    def soft_warn(self) -> bool:
        """True once spend reaches the soft-warning threshold of the budget."""
        ratio = self.used_ratio
        return ratio is not None and ratio >= self.soft_warn_ratio

    @property
    def over_budget(self) -> bool:
        """True once spend meets or exceeds the hard ceiling."""
        return self.has_ceiling and self.effective_spend_usd >= self.budget_usd

    def to_dict(self) -> IssueBudgetPayload:
        """A JSON-serializable snapshot for the read endpoint.

        Mirrors the field set on the WS steering payload (``budget_steering_event``)
        so the UI sees a single shape regardless of source. ``remaining_usd`` and
        ``used_ratio`` are explicitly ``None`` (not 0) when there is no ceiling,
        so the frontend can render an "unlimited" branch without misleading bar
        math. All USD values are rounded to 6 decimals — the same precision the
        conductor uses for steering events.
        """
        return {
            "issue_id": self.issue_id,
            "spent_usd": round(self.spent_usd, 6),
            "reserved_usd": round(self.reserved_usd, 6),
            "effective_spend_usd": round(self.effective_spend_usd, 6),
            "budget_usd": round(self.budget_usd, 6),
            "remaining_usd": (None if self.remaining_usd is None else round(self.remaining_usd, 6)),
            "used_ratio": (None if self.used_ratio is None else round(self.used_ratio, 6)),
            "soft_warn": self.soft_warn,
            "over_budget": self.over_budget,
            "soft_warn_ratio": round(self.soft_warn_ratio, 6),
            "has_ceiling": self.has_ceiling,
            "budget_source": self.budget_source,
        }


async def aggregate_issue_spend_usd(store: BudgetStore, issue_id: str) -> float:
    """Sum ``total_cost_usd`` across an issue's **completed** execution runs.

    Walks the issue's tasks, then each task's execution processes, summing the
    cost of terminal runs only. No new data source: it reuses the existing
    ``list_codex_tasks`` / ``list_execution_processes`` store queries.
    """
    total = 0.0
    task_rows = await _maybe_await(store.list_codex_tasks(issue_id=issue_id))
    for row in task_rows:
        task_id = _task_id(row)
        if not task_id:
            continue
        processes = await _maybe_await(store.list_execution_processes(task_id=task_id))
        for proc in processes:
            if proc.status not in COMPLETED_PROCESS_STATES:
                continue
            if proc.total_cost_usd:
                total += float(proc.total_cost_usd)
    return total


async def estimate_issue_inflight_spend_usd(store: BudgetStore, issue_id: str) -> float:
    """Reserve estimated spend for running execution processes on an issue."""
    running = 0
    task_rows = await _maybe_await(store.list_codex_tasks(issue_id=issue_id))
    for row in task_rows:
        task_id = _task_id(row)
        if not task_id:
            continue
        processes = await _maybe_await(store.list_execution_processes(task_id=task_id))
        for proc in processes:
            if proc.status == "Running":
                running += 1
    return running * timeouts.estimated_agent_cost_usd()


async def _aggregate_issue_budget_usage_usd(
    store: BudgetStore, issue_id: str
) -> tuple[float, float]:
    """Return completed spend and in-flight reservation in one store scan."""
    spent = 0.0
    running = 0
    task_rows = await _maybe_await(store.list_codex_tasks(issue_id=issue_id))
    for row in task_rows:
        task_id = _task_id(row)
        if not task_id:
            continue
        processes = await _maybe_await(store.list_execution_processes(task_id=task_id))
        for proc in processes:
            if proc.status in COMPLETED_PROCESS_STATES and proc.total_cost_usd:
                spent += float(proc.total_cost_usd)
            elif proc.status == "Running":
                running += 1
    return spent, running * timeouts.estimated_agent_cost_usd()


async def compute_issue_budget_status(store: BudgetStore, issue: CodexIssue) -> IssueBudgetStatus:
    """Resolve an issue's budget and aggregate its accrued spend."""
    explicit = issue.budget_usd
    budget = timeouts.resolve_issue_budget_usd(explicit)
    spent, reserved = await _aggregate_issue_budget_usage_usd(store, issue.id)
    return IssueBudgetStatus(
        issue_id=issue.id,
        spent_usd=spent,
        budget_usd=budget,
        budget_source="issue" if explicit is not None else "default",
        soft_warn_ratio=timeouts.budget_soft_warn_ratio(),
        reserved_usd=reserved,
    )


@dataclass(frozen=True)
class CandidateModelPrice:
    """A flattened, browser/LLM-safe view of an enabled catalog model's price.

    Only non-secret display fields: executor / provider / model id + label and
    the per-million USD rates (which may be ``None`` when the model has no
    explicit price and falls back to the global env rate). Never carries an
    api_key or any credential.
    """

    executor_id: str
    provider_id: str
    model_id: str
    label: str
    input_usd_per_m: float | None
    output_usd_per_m: float | None
    cache_read_usd_per_m: float | None

    @property
    def sort_price(self) -> float:
        """A single number for cheap→expensive ordering.

        Output tokens dominate cost in practice, so rank primarily by output
        price, tie-broken by input price. Models with no explicit price (env
        fallback) sort last so the Conductor prefers explicitly-cheap models
        when economising.
        """
        out = self.output_usd_per_m
        inp = self.input_usd_per_m
        # Unpriced => push to the end (float('inf')) so it is never picked as
        # "cheapest" purely because its price is unknown.
        primary = out if out is not None else float("inf")
        secondary = inp if inp is not None else float("inf")
        return primary * 1_000_000 + secondary


def collect_candidate_model_prices(catalog: RuntimeCatalog | None) -> list[CandidateModelPrice]:
    """Flatten enabled executor/provider/models into priced candidates, cheap→expensive.

    Reuses the PR1 price fields on ``RuntimeModelConfig`` as the single source of
    truth (no separate tier field). Disabled executors/providers/models are
    skipped. Never reads or returns any api_key / credential.
    """
    candidates: list[CandidateModelPrice] = []
    if catalog is None:
        return candidates
    for executor in catalog.executors:
        if not executor.enabled:
            continue
        for provider in executor.providers:
            if not provider.enabled:
                continue
            for model in provider.models:
                if not model.enabled:
                    continue
                candidates.append(
                    CandidateModelPrice(
                        executor_id=executor.id,
                        provider_id=provider.id,
                        model_id=model.id,
                        label=model.label,
                        input_usd_per_m=model.input_usd_per_m,
                        output_usd_per_m=model.output_usd_per_m,
                        cache_read_usd_per_m=model.cache_read_usd_per_m,
                    )
                )
    candidates.sort(key=lambda c: c.sort_price)
    return candidates


def _render_candidate_models(candidates: list[CandidateModelPrice]) -> list[str]:
    if not candidates:
        return []
    lines = [
        "Candidate models (cheapest → most expensive, per 1M tokens; "
        "'env' = falls back to the global flat rate):"
    ]
    for cand in candidates:

        def _fmt(value: float | None) -> str:
            return "env" if value is None else f"${value:.4f}"

        lines.append(
            f"- {cand.executor_id}/{cand.provider_id}/{cand.model_id} "
            f"({cand.label}): in {_fmt(cand.input_usd_per_m)} / "
            f"out {_fmt(cand.output_usd_per_m)} / "
            f"cache_read {_fmt(cand.cache_read_usd_per_m)}"
        )
    return lines


def render_budget_summary(
    status: IssueBudgetStatus,
    candidates: list[CandidateModelPrice] | None = None,
) -> str:
    """Render the COST / BUDGET block injected into the conductor prompt.

    PR2 surfaced spend / budget / remaining. PR3 adds:
      - candidate model unit prices (sorted cheap→expensive) so the Conductor can
        pick a model by cost;
      - escalating *soft* steering: a warning tone at the soft-warn threshold and
        a stronger wind-down steer once over budget. This is guidance only — it
        never forces the loop to stop (see module docstring / task ADR).

    ``candidates`` is optional; when omitted the block degrades to the PR2 shape.
    """
    candidates = candidates or []
    lines = ["## COST / BUDGET"]

    if not status.has_ceiling:
        lines.append(
            f"Spent so far: ${status.spent_usd:.4f}"
            f" (+ ${status.reserved_usd:.4f} reserved in-flight). "
            "No budget ceiling is configured for this issue (unlimited): "
            "choose models for quality without a cost gate."
        )
        lines.extend(_render_candidate_models(candidates))
        return "\n".join(lines)

    remaining = status.remaining_usd or 0.0
    source = "per-issue override" if status.budget_source == "issue" else "global default"
    lines.append(
        f"Spent so far: ${status.spent_usd:.4f}"
        f" (+ ${status.reserved_usd:.4f} reserved in-flight)"
        f" / Effective: ${status.effective_spend_usd:.4f}"
        f" / Budget: ${status.budget_usd:.4f} "
        f"({source}) / Remaining: ${remaining:.4f}."
    )

    if status.over_budget:
        lines.append(
            "OVER BUDGET: this issue has reached or exceeded its budget ceiling. "
            "WIND DOWN now — finalize_task as soon as the work is in a deliverable "
            "state, do NOT start new expensive dispatches or large fan-outs, and "
            "prefer the cheapest model for any unavoidable remaining step. (This is "
            "guidance, not a hard stop.)"
        )
    elif status.soft_warn:
        pct = int(round((status.used_ratio or 0.0) * 100))  # noqa: RUF046
        lines.append(
            f"BUDGET WARNING: ~{pct}% of the budget is spent (soft-warn threshold "
            f"{int(round(status.soft_warn_ratio * 100))}% reached). Economise: prefer "  # noqa: RUF046
            "cheaper models from the list below, dispatch fewer agents, and avoid "
            "wide parallel fan-outs unless clearly necessary."
        )
    else:
        lines.append(
            "Budget is healthy: you may pick stronger/more expensive models when the "
            "work warrants it; switch to cheaper ones as the remaining budget shrinks."
        )

    lines.extend(_render_candidate_models(candidates))
    return "\n".join(lines)


def budget_steering_event(status: IssueBudgetStatus) -> BudgetSteeringEvent | None:
    """Build a structured budget steering event payload, or None when not needed.

    Emitted by the conductor loop for observability / the frontend. ``None`` when
    the issue is unlimited or comfortably under the soft-warn threshold (no event
    noise on the happy path).
    """
    if not status.has_ceiling:
        return None
    base: BudgetSteeringEvent = {
        "issue_id": status.issue_id,
        "spent_usd": round(status.spent_usd, 6),
        "reserved_usd": round(status.reserved_usd, 6),
        "effective_spend_usd": round(status.effective_spend_usd, 6),
        "budget_usd": round(status.budget_usd, 6),
        "remaining_usd": round(status.remaining_usd or 0.0, 6),
        "used_ratio": round(status.used_ratio or 0.0, 6),
        "budget_source": status.budget_source,
    }
    if status.over_budget:
        return {"type": "budget_exceeded", **base}
    if status.soft_warn:
        return {"type": "budget_warning", "soft_warn_ratio": status.soft_warn_ratio, **base}
    return None


async def _maybe_await[T](value: MaybeAwaitable[T]) -> T:
    if isinstance(value, Awaitable):
        return await value
    return value


def _task_id(row: BudgetTaskRow) -> str | None:
    value = row.get("id") if isinstance(row, Mapping) else row.id
    return value if isinstance(value, str) else None
