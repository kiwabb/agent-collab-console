"""Single source of truth for orchestration timeout knobs.

The conductor / executor stack has several overlapping timeout layers. Before
this module they were read via scattered ``os.getenv`` calls in four different
files, which made the ladder impossible to reason about as a whole and let a
bad env combination (e.g. a lease TTL longer than the subagent idle budget)
mis-behave silently.

Centralising the reads here lets us (a) document the ladder in one place and
(b) assert the invariants between layers at startup so a bad combo fails loudly
instead of producing a subtle orphan-relaunch or premature-abort bug.

The ladder, innermost → outermost, and what each layer protects against::

    CODEX_IDLE_TIMEOUT_S    (180s)  Codex app-server stopped streaming after a
                                    tool_use and never fed the result back into
                                    the model. Activity-aware in the runtime:
                                    abort only when idle AND no token delta.
    CODEX_TURN_TIMEOUT_S    (480s)  Total budget for one Codex turn. A healthy
                                    Engineer/QA pass fits comfortably.
    CODEX_STALL_THRESHOLD_S (180s)  Stall watchdog: a task silent this long is
                                    terminated + nudged (cross-executor).
    CONDUCTOR_SUBAGENT_IDLE_S(1200s) dispatch_subagent gives up on a subagent
                                    showing no activity this long. Must be >
                                    CODEX_STALL_THRESHOLD_S+120 so the stall
                                    watchdog can terminate the hung subprocess
                                    before the conductor re-dispatches.
    CONDUCTOR_SUBAGENT_MAX_S(3600s) dispatch_subagent hard ceiling.
    CONDUCTOR_LEASE_TTL_S   (180s)  Conductor lease validity. The loop renews
                                    it on a background pulse every
                                    ``max(15, ttl // 3)`` s, so it stays fresh
                                    while blocked on a slow subagent.
    CONDUCTOR_LOOP_MAX_S    (7200s) Whole-loop wall-clock ceiling. Bounds the
                                    total runtime of one conductor session so a
                                    pathological issue (30 turns each blocking
                                    near the subagent hard ceiling) cannot run
                                    for tens of hours. 0 disables the ceiling.

There are also two non-ladder knobs documented here for discoverability:

    MAX_CONCURRENT_INSTANCES_PER_ROLE (3) Process-wide cap on how many subagents
                                    of the SAME role may run concurrently across
                                    all issues. dispatch_subagent acquires a slot
                                    before dispatching and releases it when the
                                    subagent finishes.
    CONDUCTOR_ROLE_SLOT_WAIT_S (=subagent_max) How long dispatch_subagent waits
                                    for a free role slot before giving up and
                                    returning ``status=role_busy`` so the
                                    Conductor can re-plan instead of blocking.
    MAX_PARALLEL_DISPATCH_PER_BATCH (3) Fan-out cap for a single dispatch_batch
                                    call: at most this many agents in one batch
                                    run concurrently. Orthogonal to the per-role
                                    cap above; bounds a batch that fans out
                                    several different roles at once.

Env-var names and defaults are unchanged from the pre-refactor call sites, so
this module is behaviour-preserving on its own.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# --- Defaults (kept identical to the historical inline values) -------------
DEFAULT_LEASE_TTL_S = 180
DEFAULT_RECOVERY_INTERVAL_S = 30
DEFAULT_SUBAGENT_IDLE_S = 1200.0
DEFAULT_SUBAGENT_MAX_S = 3600.0
DEFAULT_CODEX_TURN_TIMEOUT_S = 480
DEFAULT_CODEX_IDLE_TIMEOUT_S = 180
# Bound on the JSON-RPC startup handshake. A broken app-server (bad model id,
# missing binary, dyld crash) exits within milliseconds; initialize() would then
# wait forever for a response. This caps that wait so we fail fast (GAP K).
DEFAULT_CODEX_HANDSHAKE_TIMEOUT_S = 30
DEFAULT_STALL_THRESHOLD_S = 900
DEFAULT_STALL_INTERVAL_S = 30
DEFAULT_STALL_COOLDOWN_S = 900
# Whole-conductor-loop wall-clock ceiling (0 disables). Defends against a loop
# that never finalizes yet keeps each turn just under the subagent ceiling.
DEFAULT_CONDUCTOR_LOOP_MAX_S = 7200.0
# Process-wide concurrency cap per role (across all issues/conductors).
DEFAULT_MAX_CONCURRENT_INSTANCES_PER_ROLE = 3
# Batch-level fan-out cap: how many agents one dispatch_batch call may run
# concurrently. This is orthogonal to MAX_CONCURRENT_INSTANCES_PER_ROLE (which
# is per-role across the whole process): a single batch fanning out N *different*
# roles would not be bounded by the per-role cap, so this knob bounds the batch's
# own parallelism. Concurrency = cost multiplier, so this also becomes the hook
# for the cost/budget gate in the follow-up cost-aware scheduling task.
DEFAULT_MAX_PARALLEL_DISPATCH_PER_BATCH = 3

# Minimum lease-pulse cadence floor (mirrors the historical
# ``max(15, lease_ttl // 3)`` expression in conductor_main_loop).
LEASE_PULSE_FLOOR_S = 15

# --- Cost / budget (cost-aware conductor scheduling, PR2) ------------------
# Global default per-issue USD budget. An issue with no explicit budget_usd
# resolves to this value at runtime. 0 (or negative) means "no budget" /
# unlimited: budget awareness still reports accrued spend but no ceiling.
DEFAULT_ISSUE_BUDGET_USD = 5.0
# Fraction of the budget at which the Conductor should start being warned to
# economise (soft warning, PR3 acts on it). Must be in (0, 1].
DEFAULT_BUDGET_SOFT_WARN_RATIO = 0.8
# Rough per-agent cost estimate (USD) used ONLY to derive how many concurrent
# agents the remaining budget can support when dispatch_batch fans out (PR3).
# It is a deliberately coarse, explainable knob: budget_supported_concurrency =
# floor(remaining / this). It does NOT change actual billing — pricing stays
# the per-model / env path in usage_utils. Must be > 0.
DEFAULT_EST_COST_PER_AGENT_USD = 0.50


class TimeoutConfigError(ValueError):
    """Raised by :func:`validate` (strict mode) when an invariant is broken."""


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


# --- Conductor lease / recovery --------------------------------------------
def lease_ttl_s() -> int:
    return _env_int("CONDUCTOR_LEASE_TTL_S", DEFAULT_LEASE_TTL_S)


def recovery_interval_s() -> int:
    return _env_int("CONDUCTOR_RECOVERY_INTERVAL_S", DEFAULT_RECOVERY_INTERVAL_S)


def lease_pulse_interval_s() -> int:
    """Cadence for the background heartbeat pulse that renews the lease.

    Must stay well under :func:`lease_ttl_s` and :func:`subagent_idle_s` so the
    lease never expires while the loop is blocked awaiting a slow subagent.
    """
    return max(LEASE_PULSE_FLOOR_S, lease_ttl_s() // 3)


# --- Conductor dispatch_subagent wait --------------------------------------
def subagent_idle_s() -> float:
    return _env_float("CONDUCTOR_SUBAGENT_IDLE_S", DEFAULT_SUBAGENT_IDLE_S)


def subagent_max_s() -> float:
    return _env_float("CONDUCTOR_SUBAGENT_MAX_S", DEFAULT_SUBAGENT_MAX_S)


def conductor_loop_max_s() -> float:
    """Whole-loop wall-clock ceiling in seconds (0 disables)."""
    return _env_float("CONDUCTOR_LOOP_MAX_S", DEFAULT_CONDUCTOR_LOOP_MAX_S)


# --- Per-role concurrency --------------------------------------------------
def max_concurrent_instances_per_role() -> int:
    """Process-wide cap on concurrently-running subagents of the same role."""
    raw = _env_int("MAX_CONCURRENT_INSTANCES_PER_ROLE", DEFAULT_MAX_CONCURRENT_INSTANCES_PER_ROLE)
    return max(1, raw)


def max_parallel_dispatch_per_batch() -> int:
    """Max agents one dispatch_batch call may run concurrently (>= 1)."""
    raw = _env_int("MAX_PARALLEL_DISPATCH_PER_BATCH", DEFAULT_MAX_PARALLEL_DISPATCH_PER_BATCH)
    return max(1, raw)


# --- Cost / budget ---------------------------------------------------------
def default_issue_budget_usd() -> float:
    """Global default per-issue USD budget (0 or negative == no ceiling)."""
    return _env_float("DEFAULT_ISSUE_BUDGET_USD", DEFAULT_ISSUE_BUDGET_USD)


def budget_soft_warn_ratio() -> float:
    """Fraction of budget at which the soft warning kicks in (in (0, 1])."""
    return _env_float("BUDGET_SOFT_WARN_RATIO", DEFAULT_BUDGET_SOFT_WARN_RATIO)


def resolve_issue_budget_usd(issue_budget: float | None) -> float:
    """Resolve an issue's effective budget: explicit value, else global default.

    Returns a value <= 0 to signal "no ceiling" (unlimited); callers that gate
    on a budget should treat <= 0 as disabled.
    """
    if issue_budget is None:
        return default_issue_budget_usd()
    return issue_budget


def est_cost_per_agent_usd() -> float:
    """Coarse per-agent cost estimate driving budget-aware batch concurrency."""
    raw = _env_float("EST_COST_PER_AGENT_USD", DEFAULT_EST_COST_PER_AGENT_USD)
    return raw if raw > 0 else DEFAULT_EST_COST_PER_AGENT_USD


def budget_supported_concurrency(
    remaining_usd: float | None,
    configured_cap: int,
    *,
    soft_warn: bool = True,
    over_budget: bool = False,
) -> int:
    """Effective dispatch_batch fan-out the remaining budget can support.

    Simple, explainable rule:
      - unlimited budget (``remaining_usd is None``) → no downscale, returns the
        configured cap unchanged.
      - healthy budget (not in soft warning) → no downscale, returns the
        configured cap unchanged. The conductor prompt already labels this case
        "Budget is healthy"; tiny independent fan-outs should still get the full
        configured parallelism.
      - over budget → squeeze to the floor of 1 (wind-down is steered by prompt /
        events elsewhere; we never make a batch 0-wide here).
      - soft warning → ``floor(remaining / est_cost_per_agent)`` clamped into
        ``[1, configured_cap]`` so a tight budget shrinks fan-out but always
        allows at least one agent to make progress.

    The result is ``min(configured_cap, budget-supported)`` and never exceeds the
    configured cap, so this can only ever *reduce* parallelism, never raise it.
    ``soft_warn`` defaults to ``True`` for legacy direct callers that only pass a
    remaining amount; the conductor passes the real issue warning flag.
    """
    cap = max(1, int(configured_cap))
    if remaining_usd is None:
        return cap
    if not soft_warn and not over_budget:
        return cap
    if over_budget:
        return 1
    per_agent = est_cost_per_agent_usd()
    supported = int(remaining_usd // per_agent)
    if supported < 1:
        supported = 1
    return min(cap, supported)


def role_slot_wait_s() -> float:
    """Seconds dispatch_subagent waits for a free role slot before giving up.

    Defaults to the subagent hard ceiling: a slot that never frees within the
    time a single subagent could itself run is a genuine saturation signal, so
    we return ``role_busy`` and let the Conductor re-plan rather than block.
    """
    return _env_float("CONDUCTOR_ROLE_SLOT_WAIT_S", subagent_max_s())


# --- Codex app-server turn / idle ------------------------------------------
def codex_turn_timeout_s() -> int:
    return _env_int("CODEX_TURN_TIMEOUT_S", DEFAULT_CODEX_TURN_TIMEOUT_S)


def codex_idle_timeout_s() -> int:
    return _env_int("CODEX_IDLE_TIMEOUT_S", DEFAULT_CODEX_IDLE_TIMEOUT_S)


def codex_handshake_timeout_s() -> int:
    return _env_int("CODEX_HANDSHAKE_TIMEOUT_S", DEFAULT_CODEX_HANDSHAKE_TIMEOUT_S)


# --- Stall watchdog --------------------------------------------------------
def stall_threshold_s() -> int:
    return _env_int("CODEX_STALL_THRESHOLD_S", DEFAULT_STALL_THRESHOLD_S)


def stall_interval_s() -> int:
    return _env_int("CODEX_STALL_INTERVAL_S", DEFAULT_STALL_INTERVAL_S)


def stall_cooldown_s() -> int:
    return _env_int("CODEX_STALL_COOLDOWN_S", DEFAULT_STALL_COOLDOWN_S)


def check_invariants() -> list[str]:
    """Return a list of human-readable invariant violations (empty == OK)."""
    violations: list[str] = []
    ttl = lease_ttl_s()
    pulse = lease_pulse_interval_s()
    idle = subagent_idle_s()
    hard = subagent_max_s()
    codex_idle = codex_idle_timeout_s()
    codex_turn = codex_turn_timeout_s()

    # The lease must be renewable several times within a subagent wait, or the
    # recovery watchdog will declare the live conductor an orphan mid-dispatch.
    if ttl >= idle:
        violations.append(
            f"CONDUCTOR_LEASE_TTL_S ({ttl}) must be < CONDUCTOR_SUBAGENT_IDLE_S ({idle:.0f}): "
            "the lease has to be renewable while awaiting a subagent."
        )
    if pulse >= ttl:
        violations.append(
            f"lease pulse interval ({pulse}) must be < CONDUCTOR_LEASE_TTL_S ({ttl}): "
            "the heartbeat must fire before the lease expires."
        )
    if pulse >= idle:
        violations.append(
            f"lease pulse interval ({pulse}) must be << CONDUCTOR_SUBAGENT_IDLE_S ({idle:.0f})."
        )
    if idle > hard:
        violations.append(
            f"CONDUCTOR_SUBAGENT_IDLE_S ({idle:.0f}) must be <= CONDUCTOR_SUBAGENT_MAX_S ({hard:.0f})."
        )
    stall = stall_threshold_s()
    if idle <= stall + 120:
        violations.append(
            f"CONDUCTOR_SUBAGENT_IDLE_S ({idle:.0f}) must be > "
            f"CODEX_STALL_THRESHOLD_S+120 ({stall + 120:.0f}): "
            "the stall watchdog must get a chance to terminate the hung subprocess "
            "before the conductor re-dispatches."
        )
    if codex_idle > codex_turn:
        violations.append(
            f"CODEX_IDLE_TIMEOUT_S ({codex_idle}) must be <= CODEX_TURN_TIMEOUT_S ({codex_turn})."
        )
    loop_max = conductor_loop_max_s()
    if loop_max and loop_max < hard:
        violations.append(
            f"CONDUCTOR_LOOP_MAX_S ({loop_max:.0f}) must be >= CONDUCTOR_SUBAGENT_MAX_S "
            f"({hard:.0f}) or 0: the whole-loop ceiling cannot be shorter than a single "
            "subagent's hard limit, or the loop dies before its first subagent can."
        )
    if max_concurrent_instances_per_role() < 1:
        violations.append(
            f"MAX_CONCURRENT_INSTANCES_PER_ROLE ({max_concurrent_instances_per_role()}) must be >= 1."
        )
    if max_parallel_dispatch_per_batch() < 1:
        violations.append(
            f"MAX_PARALLEL_DISPATCH_PER_BATCH ({max_parallel_dispatch_per_batch()}) must be >= 1."
        )
    ratio = budget_soft_warn_ratio()
    if not (0 < ratio <= 1):
        violations.append(
            f"BUDGET_SOFT_WARN_RATIO ({ratio}) must be in (0, 1]."
        )
    budget = default_issue_budget_usd()
    if budget < 0:
        violations.append(
            f"DEFAULT_ISSUE_BUDGET_USD ({budget}) must be >= 0 (0 == no ceiling)."
        )
    est_agent = est_cost_per_agent_usd()
    if est_agent <= 0:
        violations.append(
            f"EST_COST_PER_AGENT_USD ({est_agent}) must be > 0."
        )
    for name, value in (
        ("CONDUCTOR_RECOVERY_INTERVAL_S", recovery_interval_s()),
        ("CODEX_STALL_THRESHOLD_S", stall_threshold_s()),
        ("CODEX_STALL_INTERVAL_S", stall_interval_s()),
        ("CODEX_STALL_COOLDOWN_S", stall_cooldown_s()),
    ):
        if value <= 0:
            violations.append(f"{name} ({value}) must be > 0.")
    return violations


def validate(*, strict: bool = False) -> list[str]:
    """Validate the timeout ladder.

    Logs each violation at ERROR level. In ``strict`` mode raises
    :class:`TimeoutConfigError` (used by tests); otherwise returns the list so
    startup can fail loudly without bricking the server on a bad env var.
    """
    violations = check_invariants()
    for v in violations:
        logger.error("timeout config invariant violated: %s", v)
    if strict and violations:
        raise TimeoutConfigError("; ".join(violations))
    return violations
