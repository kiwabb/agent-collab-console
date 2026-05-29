"""Per-issue cost/budget awareness (cost-aware conductor scheduling, PR2).

Cost is recorded after the fact on every ``ExecutionProcess`` row
(``total_cost_usd``). PR2 turns that record into a *decision-time* input for
the Conductor: aggregate the spend an issue has already accrued, resolve its
budget (explicit per-issue value, else the global default from
``timeouts``), and render a short, human-readable summary that the conductor
loop injects into its system prompt so the orchestrating brain can *see* how
much budget remains.

This module is read-only and behaviour-neutral: it only makes cost visible.
Budget-driven selection / soft-warning enforcement / dynamic batch-concurrency
downscaling are PR3.

Aggregation rule: only **completed** runs are summed. A run is completed when
its ``ExecutionProcess.status`` is one of the terminal states
(``Completed`` / ``Failed`` / ``Killed``). In-flight ``Running`` rows are
excluded — their ``total_cost_usd`` is not yet final and would double-count
once the run lands. This matches the PRD constraint ("只算已完成 run").
"""
from __future__ import annotations

from dataclasses import dataclass

from app.application import timeouts
from app.domain.models import CodexIssue

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


def render_budget_summary(status: IssueBudgetStatus) -> str:
    """Render a compact markdown block for injection into the conductor prompt.

    PR2 is *visibility only*: this states spend / budget / remaining without
    telling the conductor what to do about it (that steering is PR3).
    """
    lines = ["## COST / BUDGET"]
    if not status.has_ceiling:
        lines.append(
            f"Spent so far: ${status.spent_usd:.4f}. "
            "No budget ceiling is configured for this issue (unlimited)."
        )
        return "\n".join(lines)

    remaining = status.remaining_usd or 0.0
    source = (
        "per-issue override" if status.budget_source == "issue" else "global default"
    )
    lines.append(
        f"Spent so far: ${status.spent_usd:.4f} / Budget: ${status.budget_usd:.4f} "
        f"({source}) / Remaining: ${remaining:.4f}."
    )
    return "\n".join(lines)


async def _maybe_await(value):
    if hasattr(value, "__await__"):
        return await value
    return value
