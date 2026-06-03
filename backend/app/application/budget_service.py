"""Per-issue cost/budget awareness (cost-aware conductor scheduling, PR2 + PR3).

Cost is recorded after the fact on every ``ExecutionProcess`` row
(``total_cost_usd``). PR2 turned that record into a *decision-time* input for
the Conductor: aggregate the spend an issue has already accrued, resolve its
budget (explicit per-issue value, else the global default from ``timeouts``),
and render a short, human-readable summary that the conductor loop injects into
its system prompt so the orchestrating brain can *see* how much budget remains.

PR3 makes the budget *steer* decisions (still as prompt guidance, not a hard
constraint — see the task ADR):
  - candidate model unit prices (PR1 price fields) are injected, sorted cheap →
    expensive, so the Conductor can pick a model by cost;
  - at the soft-warning threshold the block escalates to warning tone (prefer
    cheaper models / dispatch less);
  - over budget it escalates to a strong wind-down steer (finalize soon, no new
    expensive dispatches). The loop is NEVER hard-killed here — that is the
    max_wall ceiling's job; this is soft semantics only.

Aggregation rule: only **completed** runs are summed. A run is completed when
its ``ExecutionProcess.status`` is one of the terminal states
(``Completed`` / ``Failed`` / ``Killed``). In-flight ``Running`` rows are
excluded — their ``total_cost_usd`` is not yet final and would double-count
once the run lands. This matches the PRD constraint ("只算已完成 run").
"""
from __future__ import annotations

from dataclasses import dataclass

from app.application import timeouts
from app.domain.models import CodexIssue, RuntimeCatalog

# Terminal execution-process states whose cost is final and safe to sum.
COMPLETED_PROCESS_STATES = frozenset({"Completed", "Failed", "Killed"})


@dataclass
class IssueBudgetStatus:
    """A decision-time snapshot of an issue's budget vs accrued spend."""

    issue_id: str
    spent_usd: float
    budget_usd: float  # <= 0 means "no ceiling" (unlimited)
    budget_source: str  # "issue" | "default"
    soft_warn_ratio: float

    @property
    def has_ceiling(self) -> bool:
        return self.budget_usd > 0

    @property
    def remaining_usd(self) -> float | None:
        """Remaining budget; ``None`` when there is no ceiling."""
        if not self.has_ceiling:
            return None
        return self.budget_usd - self.spent_usd

    @property
    def used_ratio(self) -> float | None:
        """Fraction of budget consumed; ``None`` when there is no ceiling."""
        if not self.has_ceiling:
            return None
        return self.spent_usd / self.budget_usd

    @property
    def soft_warn(self) -> bool:
        """True once spend reaches the soft-warning threshold of the budget."""
        ratio = self.used_ratio
        return ratio is not None and ratio >= self.soft_warn_ratio

    @property
    def over_budget(self) -> bool:
        """True once spend meets or exceeds the hard ceiling."""
        return self.has_ceiling and self.spent_usd >= self.budget_usd

    def to_dict(self) -> dict:
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
            "budget_usd": round(self.budget_usd, 6),
            "remaining_usd": (
                None if self.remaining_usd is None
                else round(self.remaining_usd, 6)
            ),
            "used_ratio": (
                None if self.used_ratio is None
                else round(self.used_ratio, 6)
            ),
            "soft_warn": self.soft_warn,
            "over_budget": self.over_budget,
            "soft_warn_ratio": round(self.soft_warn_ratio, 6),
            "has_ceiling": self.has_ceiling,
            "budget_source": self.budget_source,
        }


async def aggregate_issue_spend_usd(store, issue_id: str) -> float:
    """Sum ``total_cost_usd`` across an issue's **completed** execution runs.

    Walks the issue's tasks, then each task's execution processes, summing the
    cost of terminal runs only. No new data source: it reuses the existing
    ``list_codex_tasks`` / ``list_execution_processes`` store queries.
    """
    total = 0.0
    task_rows = await _maybe_await(store.list_codex_tasks(issue_id=issue_id))
    for row in task_rows or []:
        task_id = row.get("id") if isinstance(row, dict) else getattr(row, "id", None)
        if not task_id:
            continue
        processes = await _maybe_await(store.list_execution_processes(task_id=task_id))
        for proc in processes or []:
            if proc.status not in COMPLETED_PROCESS_STATES:
                continue
            if proc.total_cost_usd:
                total += float(proc.total_cost_usd)
    return total


async def compute_issue_budget_status(store, issue: CodexIssue) -> IssueBudgetStatus:
    """Resolve an issue's budget and aggregate its accrued spend."""
    explicit = getattr(issue, "budget_usd", None)
    budget = timeouts.resolve_issue_budget_usd(explicit)
    spent = await aggregate_issue_spend_usd(store, issue.id)
    return IssueBudgetStatus(
        issue_id=issue.id,
        spent_usd=spent,
        budget_usd=budget,
        budget_source="issue" if explicit is not None else "default",
        soft_warn_ratio=timeouts.budget_soft_warn_ratio(),
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
    for executor in getattr(catalog, "executors", None) or []:
        if not getattr(executor, "enabled", True):
            continue
        for provider in getattr(executor, "providers", None) or []:
            if not getattr(provider, "enabled", True):
                continue
            for model in getattr(provider, "models", None) or []:
                if not getattr(model, "enabled", True):
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
            f"Spent so far: ${status.spent_usd:.4f}. "
            "No budget ceiling is configured for this issue (unlimited): "
            "choose models for quality without a cost gate."
        )
        lines.extend(_render_candidate_models(candidates))
        return "\n".join(lines)

    remaining = status.remaining_usd or 0.0
    source = (
        "per-issue override" if status.budget_source == "issue" else "global default"
    )
    lines.append(
        f"Spent so far: ${status.spent_usd:.4f} / Budget: ${status.budget_usd:.4f} "
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
        pct = int(round((status.used_ratio or 0.0) * 100))
        lines.append(
            f"BUDGET WARNING: ~{pct}% of the budget is spent (soft-warn threshold "
            f"{int(round(status.soft_warn_ratio * 100))}% reached). Economise: prefer "
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


def budget_steering_event(status: IssueBudgetStatus) -> dict | None:
    """Build a structured budget steering event payload, or None when not needed.

    Emitted by the conductor loop for observability / the frontend. ``None`` when
    the issue is unlimited or comfortably under the soft-warn threshold (no event
    noise on the happy path).
    """
    if not status.has_ceiling:
        return None
    base = {
        "issue_id": status.issue_id,
        "spent_usd": round(status.spent_usd, 6),
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


async def _maybe_await(value):
    if hasattr(value, "__await__"):
        return await value
    return value
