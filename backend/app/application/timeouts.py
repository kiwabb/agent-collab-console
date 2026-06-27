from __future__ import annotations

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
import logging  # noqa: E402
import os  # noqa: E402

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
DEFAULT_PROJECT_REVIEW_INTERVAL_S = 3600.0
DEFAULT_PROJECT_REVIEW_LIMIT = 25
DEFAULT_SELF_IMPROVEMENT_PROPOSAL_INTERVAL_S = 3600.0
DEFAULT_SELF_IMPROVEMENT_PROPOSAL_LIMIT = 25
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


def _env_str(name: str, default: str) -> str:
    raw = os.getenv(name)
    return raw if raw else default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_optional_str(name: str) -> str | None:
    return os.getenv(name)


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


# --- Project review scheduler ---------------------------------------------
def project_review_interval_s() -> float:
    raw = _env_float("PROJECT_REVIEW_INTERVAL_S", DEFAULT_PROJECT_REVIEW_INTERVAL_S)
    return raw if raw > 0 else DEFAULT_PROJECT_REVIEW_INTERVAL_S


def project_review_limit() -> int:
    raw = _env_int("PROJECT_REVIEW_LIMIT", DEFAULT_PROJECT_REVIEW_LIMIT)
    return max(1, raw)


# --- Self-improvement proposal scheduler ----------------------------------
def self_improvement_proposal_interval_s() -> float:
    raw = _env_float(
        "SELF_IMPROVEMENT_PROPOSAL_INTERVAL_S",
        DEFAULT_SELF_IMPROVEMENT_PROPOSAL_INTERVAL_S,
    )
    return raw if raw > 0 else DEFAULT_SELF_IMPROVEMENT_PROPOSAL_INTERVAL_S


def self_improvement_proposal_limit() -> int:
    raw = _env_int("SELF_IMPROVEMENT_PROPOSAL_LIMIT", DEFAULT_SELF_IMPROVEMENT_PROPOSAL_LIMIT)
    return max(1, raw)


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
        violations.append(f"BUDGET_SOFT_WARN_RATIO ({ratio}) must be in (0, 1].")
    budget = default_issue_budget_usd()
    if budget < 0:
        violations.append(f"DEFAULT_ISSUE_BUDGET_USD ({budget}) must be >= 0 (0 == no ceiling).")
    est_agent = est_cost_per_agent_usd()
    if est_agent <= 0:
        violations.append(f"EST_COST_PER_AGENT_USD ({est_agent}) must be > 0.")
    for name, value in (
        ("CONDUCTOR_RECOVERY_INTERVAL_S", recovery_interval_s()),
        ("CODEX_STALL_THRESHOLD_S", stall_threshold_s()),
        ("CODEX_STALL_INTERVAL_S", stall_interval_s()),
        ("CODEX_STALL_COOLDOWN_S", stall_cooldown_s()),
        ("PROJECT_REVIEW_INTERVAL_S", project_review_interval_s()),
        ("PROJECT_REVIEW_LIMIT", project_review_limit()),
        ("SELF_IMPROVEMENT_PROPOSAL_INTERVAL_S", self_improvement_proposal_interval_s()),
        ("SELF_IMPROVEMENT_PROPOSAL_LIMIT", self_improvement_proposal_limit()),
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


# --- Runtime / executor / cost knobs (Phase 2b) ------------------------
# These were scattered ``os.getenv`` calls in feature code. Per spec
# ('feature code never reaches into env vars directly'), all reads go
# through the accessors below. The accessor is the only place that knows
# the env-var name; callers pass the typed value into services.


def real_cli_enabled() -> bool:
    return _env_bool("REAL_CLI", True)


def codex_launch_enabled() -> bool:
    return _env_bool("CODEX_LAUNCH_ENABLED", True)


def use_sqlite() -> bool:
    return _env_bool("USE_SQLITE", True)


def sqlite_db_path() -> str:
    return _env_str("SQLITE_DB_PATH", "console.db")


def sqlite_db_path_configured() -> bool:
    return bool(os.getenv("SQLITE_DB_PATH"))


def codex_workspace_root_configured() -> bool:
    return bool(os.getenv("CODEX_WORKSPACE_ROOT"))


def codex_workspace_root() -> str | None:
    return os.getenv("CODEX_WORKSPACE_ROOT")


def codex_data_dir() -> str:
    return _env_str("CODEX_DATA_DIR", "/tmp")


def codex_cmd() -> str:
    return _env_str("CODEX_CMD", "codex")


def claude_cmd() -> str:
    return _env_str("CLAUDE_CMD", "claude")


def codex_app_server_cmd() -> str | None:
    return os.getenv("CODEX_APP_SERVER_CMD")


def codex_app_server_model() -> str | None:
    return os.getenv("CODEX_APP_SERVER_MODEL")


def codex_auto_approve() -> bool:
    return _env_bool("CODEX_AUTO_APPROVE", False)


def workflow_dag_enabled() -> bool:
    return _env_bool("WORKFLOW_DAG_ENABLED", True)


def workflow_orchestrator_executor_id() -> str | None:
    return os.getenv("WORKFLOW_ORCHESTRATOR_EXECUTOR_ID")


def workflow_orchestrator_model() -> str | None:
    return os.getenv("WORKFLOW_ORCHESTRATOR_MODEL")


def workflow_orchestrator_max_tokens() -> int | None:
    raw = os.getenv("WORKFLOW_ORCHESTRATOR_MAX_TOKENS")
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def workflow_orchestrator_timeout() -> float | None:
    raw = os.getenv("WORKFLOW_ORCHESTRATOR_TIMEOUT")
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def cost_usd_per_m_input() -> float:
    return _env_float("COST_USD_PER_M_INPUT", 0.30)


def cost_usd_per_m_output() -> float:
    return _env_float("COST_USD_PER_M_OUTPUT", 1.20)


def cost_usd_per_m_cache_read() -> float:
    return _env_float("COST_USD_PER_M_CACHE_READ", 0.075)


def openai_api_key() -> str | None:
    return os.getenv("OPENAI_API_KEY")


def openai_base_url() -> str | None:
    return os.getenv("OPENAI_BASE_URL")


def anthropic_api_key() -> str | None:
    return os.getenv("ANTHROPIC_API_KEY")


def anthropic_base_url() -> str | None:
    return os.getenv("ANTHROPIC_BASE_URL")


def conductor_max_dispatches_per_role() -> int:
    return _env_int("CONDUCTOR_MAX_DISPATCHES_PER_ROLE", 3)


def conductor_max_relaunches() -> int:
    return _env_int("CONDUCTOR_MAX_RELAUNCHES", 3)


def conductor_recovery_enabled() -> bool:
    return _env_bool("CONDUCTOR_RECOVERY_ENABLED", True)


def conductor_llm_executor_id() -> str | None:
    return os.getenv("CONDUCTOR_LLM_EXECUTOR_ID")


def conductor_llm_model() -> str | None:
    return os.getenv("CONDUCTOR_LLM_MODEL")


def conductor_llm_protocol() -> str | None:
    return os.getenv("CONDUCTOR_LLM_PROTOCOL")


def conductor_llm_max_tokens() -> int | None:
    raw = os.getenv("CONDUCTOR_LLM_MAX_TOKENS")
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def conductor_llm_timeout() -> float | None:
    raw = os.getenv("CONDUCTOR_LLM_TIMEOUT")
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def embedding_provider_type() -> str | None:
    return os.getenv("EMBEDDING_PROVIDER_TYPE")


def embedding_model() -> str | None:
    return os.getenv("EMBEDDING_MODEL")


def embedding_api_endpoint() -> str | None:
    return os.getenv("EMBEDDING_API_ENDPOINT")


def embedding_api_key() -> str | None:
    return os.getenv("EMBEDDING_API_KEY")


def embedding_disabled() -> bool:
    return _env_bool("EMBEDDING_DISABLED", False)


def embedding_timeout_s() -> float:
    return _env_float("EMBEDDING_TIMEOUT_S", 30.0)


def event_bus_buffer_size() -> int:
    return _env_int("EVENT_BUS_BUFFER_SIZE", 1024)


def process_idle_timeout() -> float:
    return _env_float("PROCESS_IDLE_TIMEOUT", 1800.0)


def process_max_timeout() -> float:
    return _env_float("PROCESS_MAX_TIMEOUT", 14400.0)


def qa_execute_commands() -> bool:
    return _env_bool("QA_EXECUTE_COMMANDS", True)


def qa_command_timeout_s() -> float:
    return _env_float("QA_COMMAND_TIMEOUT_S", 120.0)


def qa_total_budget_s() -> float:
    return _env_float("QA_TOTAL_BUDGET_S", 300.0)


def audit_log_max_queue() -> int:
    return _env_int("AUDIT_LOG_MAX_QUEUE", 4096)
