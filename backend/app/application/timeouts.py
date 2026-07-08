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
    CODEX_STALL_THRESHOLD_S (900s)  Stall watchdog: a task silent this long is
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

Env-var names and defaults are unchanged from the pre-refactor call sites, so
this module is behaviour-preserving on its own.
"""
from __future__ import annotations

import logging
import os
import tempfile

logger = logging.getLogger(__name__)

# --- Defaults (kept identical to the historical inline values) -------------
DEFAULT_LEASE_TTL_S = 180
DEFAULT_RECOVERY_INTERVAL_S = 30
DEFAULT_CONDUCTOR_RECOVERY_ENABLED = True
DEFAULT_CONDUCTOR_MAX_RELAUNCHES = 3
DEFAULT_SUBAGENT_IDLE_S = 1200.0
DEFAULT_SUBAGENT_MAX_S = 3600.0
DEFAULT_CODEX_TURN_TIMEOUT_S = 480
DEFAULT_CODEX_IDLE_TIMEOUT_S = 180
DEFAULT_CODEX_APP_SERVER_CMD = "codex app-server"
DEFAULT_CODEX_APP_SERVER_MODEL = "gpt-5.4-mini"
DEFAULT_CODEX_AUTO_APPROVE = True
DEFAULT_WORKFLOW_DAG_ENABLED = True
DEFAULT_SQLITE_DB_PATH = "console.db"
DEFAULT_USE_SQLITE = True
DEFAULT_CODEX_LAUNCH_ENABLED = True
DEFAULT_REAL_CLI = True
DEFAULT_CLAUDE_CLI_CMD = "claude"
DEFAULT_CODEX_CLI_CMD = "codex"
DEFAULT_CODEX_DATA_DIR = tempfile.gettempdir()
DEFAULT_CLAUDE_CMD = "claude -p --output-format=stream-json --verbose"
DEFAULT_PROCESS_IDLE_TIMEOUT_S = 180
DEFAULT_PROCESS_MAX_TIMEOUT_S = 1800
DEFAULT_WORKFLOW_ORCHESTRATOR_LLM_ENABLED = True
DEFAULT_WORKFLOW_ORCHESTRATOR_TIMEOUT_S = 28.0
DEFAULT_WORKFLOW_ORCHESTRATOR_MAX_TOKENS = 8192
DEFAULT_CONDUCTOR_LLM_TIMEOUT_S = 120.0
DEFAULT_CONDUCTOR_LLM_MAX_TOKENS = 8192
DEFAULT_EMBEDDING_PROVIDER_TYPE = "openai"
DEFAULT_EMBEDDING_TIMEOUT_S = 20.0
# Bound on the JSON-RPC startup handshake. A broken app-server (bad model id,
# missing binary, dyld crash) exits within milliseconds; initialize() would then
# wait forever for a response. This caps that wait so we fail fast (GAP K).
DEFAULT_CODEX_HANDSHAKE_TIMEOUT_S = 30
DEFAULT_STALL_WATCHDOG_ENABLED = True
DEFAULT_STALL_THRESHOLD_S = 900
DEFAULT_STALL_INTERVAL_S = 30
DEFAULT_STALL_COOLDOWN_S = 900
DEFAULT_MAX_PARALLEL_DISPATCH_PER_BATCH = 4
DEFAULT_CONDUCTOR_MAX_DISPATCHES_PER_ROLE = 4
DEFAULT_ISSUE_BUDGET_USD = 25.0
DEFAULT_BUDGET_SOFT_WARN_RATIO = 0.8
DEFAULT_COST_USD_PER_M_INPUT = 0.30
DEFAULT_COST_USD_PER_M_OUTPUT = 1.20
DEFAULT_COST_USD_PER_M_CACHE_READ = 0.075
DEFAULT_ESTIMATED_AGENT_COST_USD = 1.0
DEFAULT_EST_COST_PER_AGENT_USD = DEFAULT_ESTIMATED_AGENT_COST_USD
DEFAULT_QA_COMMAND_TIMEOUT_S = 120
DEFAULT_QA_TOTAL_BUDGET_S = 300
DEFAULT_QA_EXECUTE_COMMANDS = False
DEFAULT_PROJECT_REVIEW_INTERVAL_S = 3600
DEFAULT_PROJECT_REVIEW_LIMIT = 25
DEFAULT_SELF_IMPROVEMENT_PROPOSAL_INTERVAL_S = 3600
DEFAULT_SELF_IMPROVEMENT_PROPOSAL_LIMIT = 25
DEFAULT_PROJECT_SCRIPT_SUGGESTION_TIMEOUT_S = 60
DEFAULT_PROJECT_SCRIPT_VERIFICATION_TIMEOUT_S = 180
DEFAULT_EVENT_BUS_BUFFER_SIZE = 1000
DEFAULT_AUDIT_LOG_MAX_QUEUE = 10000
DEFAULT_WS_WORKSPACE_QUEUE_MAXSIZE = 256
DEFAULT_WS_LOG_QUEUE_MAXSIZE = 2048
DEFAULT_WS_MESSAGE_QUEUE_MAXSIZE = 512
DEFAULT_MAX_CONCURRENT_INSTANCES_PER_ROLE = 2
DEFAULT_ROLE_SLOT_WAIT_S = 30
DEFAULT_CONDUCTOR_LOOP_MAX_S = 7200

# Minimum lease-pulse cadence floor (mirrors the historical
# ``max(15, lease_ttl // 3)`` expression in conductor_main_loop).
LEASE_PULSE_FLOOR_S = 15


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


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _env_str(name: str) -> str | None:
    raw = os.getenv(name)
    if raw is None:
        return None
    value = raw.strip()
    return value or None


def _coerce_float(value: float | int | str | None, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_int(value: int | str | None, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# --- Conductor lease / recovery --------------------------------------------
def lease_ttl_s() -> int:
    return _env_int("CONDUCTOR_LEASE_TTL_S", DEFAULT_LEASE_TTL_S)


def recovery_interval_s() -> int:
    return _env_int("CONDUCTOR_RECOVERY_INTERVAL_S", DEFAULT_RECOVERY_INTERVAL_S)


def conductor_recovery_enabled() -> bool:
    return _env_bool("CONDUCTOR_RECOVERY_ENABLED", DEFAULT_CONDUCTOR_RECOVERY_ENABLED)


def conductor_max_relaunches() -> int:
    return max(0, _env_int("CONDUCTOR_MAX_RELAUNCHES", DEFAULT_CONDUCTOR_MAX_RELAUNCHES))


def lease_pulse_interval_s() -> int:
    """Cadence for the background heartbeat pulse that renews the lease.

    Must stay well under :func:`lease_ttl_s` and :func:`subagent_idle_s` so the
    lease never expires while the loop is blocked awaiting a slow subagent.
    """
    return max(LEASE_PULSE_FLOOR_S, lease_ttl_s() // 3)


def conductor_loop_max_s() -> int:
    return max(1, _env_int("CONDUCTOR_LOOP_MAX_S", DEFAULT_CONDUCTOR_LOOP_MAX_S))


# --- Conductor dispatch_subagent wait --------------------------------------
def subagent_idle_s() -> float:
    return _env_float("CONDUCTOR_SUBAGENT_IDLE_S", DEFAULT_SUBAGENT_IDLE_S)


def subagent_max_s() -> float:
    return _env_float("CONDUCTOR_SUBAGENT_MAX_S", DEFAULT_SUBAGENT_MAX_S)


# --- Codex app-server turn / idle ------------------------------------------
def codex_turn_timeout_s() -> int:
    return _env_int("CODEX_TURN_TIMEOUT_S", DEFAULT_CODEX_TURN_TIMEOUT_S)


def codex_idle_timeout_s() -> int:
    return _env_int("CODEX_IDLE_TIMEOUT_S", DEFAULT_CODEX_IDLE_TIMEOUT_S)


def codex_handshake_timeout_s() -> int:
    return _env_int("CODEX_HANDSHAKE_TIMEOUT_S", DEFAULT_CODEX_HANDSHAKE_TIMEOUT_S)


def codex_app_server_cmd() -> str:
    return _env_str("CODEX_APP_SERVER_CMD") or DEFAULT_CODEX_APP_SERVER_CMD


def codex_app_server_model() -> str | None:
    return _env_str("CODEX_APP_SERVER_MODEL") or DEFAULT_CODEX_APP_SERVER_MODEL


def codex_auto_approve() -> bool:
    return _env_bool("CODEX_AUTO_APPROVE", DEFAULT_CODEX_AUTO_APPROVE)


def workflow_dag_enabled() -> bool:
    return _env_bool("WORKFLOW_DAG_ENABLED", DEFAULT_WORKFLOW_DAG_ENABLED)


def sqlite_db_path() -> str:
    return _env_str("SQLITE_DB_PATH") or DEFAULT_SQLITE_DB_PATH


def use_sqlite() -> bool:
    return _env_bool("USE_SQLITE", DEFAULT_USE_SQLITE)


def codex_launch_enabled() -> bool:
    return _env_bool("CODEX_LAUNCH_ENABLED", DEFAULT_CODEX_LAUNCH_ENABLED)


def real_cli_enabled() -> bool:
    return _env_bool("REAL_CLI", DEFAULT_REAL_CLI)


def claude_cli_cmd() -> str:
    return _env_str("CLAUDE_CMD") or DEFAULT_CLAUDE_CLI_CMD


def codex_cli_cmd() -> str:
    return _env_str("CODEX_CMD") or DEFAULT_CODEX_CLI_CMD


def codex_data_dir() -> str:
    return _env_str("CODEX_DATA_DIR") or DEFAULT_CODEX_DATA_DIR


def claude_cmd() -> str:
    return _env_str("CLAUDE_CMD") or DEFAULT_CLAUDE_CMD


def anthropic_api_key_configured() -> bool:
    return _env_str("ANTHROPIC_API_KEY") is not None


# --- Generic process runtime reader / watchdog -----------------------------
def process_idle_timeout_s() -> int:
    return _env_int("PROCESS_IDLE_TIMEOUT", DEFAULT_PROCESS_IDLE_TIMEOUT_S)


def process_max_timeout_s() -> int:
    return _env_int("PROCESS_MAX_TIMEOUT", DEFAULT_PROCESS_MAX_TIMEOUT_S)


def workflow_orchestrator_executor_id() -> str | None:
    return _env_str("WORKFLOW_ORCHESTRATOR_EXECUTOR_ID")


def workflow_orchestrator_llm_enabled() -> bool:
    return _env_bool(
        "WORKFLOW_ORCHESTRATOR_LLM",
        DEFAULT_WORKFLOW_ORCHESTRATOR_LLM_ENABLED,
    )


def workflow_orchestrator_model() -> str | None:
    return _env_str("WORKFLOW_ORCHESTRATOR_MODEL")


def workflow_orchestrator_timeout_s() -> float:
    return _env_float(
        "WORKFLOW_ORCHESTRATOR_TIMEOUT",
        DEFAULT_WORKFLOW_ORCHESTRATOR_TIMEOUT_S,
    )


def workflow_orchestrator_max_tokens() -> int:
    return max(
        1,
        _env_int(
            "WORKFLOW_ORCHESTRATOR_MAX_TOKENS",
            DEFAULT_WORKFLOW_ORCHESTRATOR_MAX_TOKENS,
        ),
    )


def conductor_llm_executor_id() -> str | None:
    return _env_str("CONDUCTOR_LLM_EXECUTOR_ID")


def conductor_llm_model() -> str | None:
    return _env_str("CONDUCTOR_LLM_MODEL")


def conductor_llm_protocol() -> str | None:
    value = _env_str("CONDUCTOR_LLM_PROTOCOL")
    return value.lower() if value is not None else None


def conductor_llm_timeout_s(fallback: float | int | str | None = None) -> float:
    return _env_float(
        "CONDUCTOR_LLM_TIMEOUT",
        _coerce_float(fallback, DEFAULT_CONDUCTOR_LLM_TIMEOUT_S),
    )


def conductor_llm_max_tokens(fallback: int | str | None = None) -> int:
    return max(
        1,
        _env_int(
            "CONDUCTOR_LLM_MAX_TOKENS",
            _coerce_int(fallback, DEFAULT_CONDUCTOR_LLM_MAX_TOKENS),
        ),
    )


def embedding_api_endpoint() -> str:
    return _env_str("EMBEDDING_API_ENDPOINT") or ""


def embedding_api_key() -> str:
    return _env_str("EMBEDDING_API_KEY") or ""


def embedding_model() -> str:
    return _env_str("EMBEDDING_MODEL") or ""


def embedding_provider_type() -> str:
    return _env_str("EMBEDDING_PROVIDER_TYPE") or DEFAULT_EMBEDDING_PROVIDER_TYPE


def embedding_timeout_s() -> float:
    return _env_float("EMBEDDING_TIMEOUT_S", DEFAULT_EMBEDDING_TIMEOUT_S)


def embedding_disabled() -> bool:
    return _env_bool("EMBEDDING_DISABLED", False)


# --- Stall watchdog --------------------------------------------------------
def stall_watchdog_enabled() -> bool:
    return _env_bool("CODEX_STALL_WATCHDOG", DEFAULT_STALL_WATCHDOG_ENABLED)


def stall_threshold_s() -> int:
    return _env_int("CODEX_STALL_THRESHOLD_S", DEFAULT_STALL_THRESHOLD_S)


def stall_interval_s() -> int:
    return _env_int("CODEX_STALL_INTERVAL_S", DEFAULT_STALL_INTERVAL_S)


def stall_cooldown_s() -> int:
    return _env_int("CODEX_STALL_COOLDOWN_S", DEFAULT_STALL_COOLDOWN_S)


# --- Budget / concurrency ---------------------------------------------------
def max_parallel_dispatch_per_batch() -> int:
    return max(1, _env_int("MAX_PARALLEL_DISPATCH_PER_BATCH", DEFAULT_MAX_PARALLEL_DISPATCH_PER_BATCH))


def conductor_max_dispatches_per_role() -> int:
    return max(
        1,
        _env_int("CONDUCTOR_MAX_DISPATCHES_PER_ROLE", DEFAULT_CONDUCTOR_MAX_DISPATCHES_PER_ROLE),
    )


def resolve_issue_budget_usd(explicit: float | None = None) -> float:
    if explicit is not None:
        try:
            return max(0.0, float(explicit))
        except (TypeError, ValueError):
            return 0.0
    return default_issue_budget_usd()


def default_issue_budget_usd() -> float:
    return max(0.0, _env_float("DEFAULT_ISSUE_BUDGET_USD", DEFAULT_ISSUE_BUDGET_USD))


def budget_soft_warn_ratio() -> float:
    return min(1.0, max(0.0, _env_float("BUDGET_SOFT_WARN_RATIO", DEFAULT_BUDGET_SOFT_WARN_RATIO)))


def cost_usd_per_m_input() -> float:
    return max(0.0, _env_float("COST_USD_PER_M_INPUT", DEFAULT_COST_USD_PER_M_INPUT))


def cost_usd_per_m_output() -> float:
    return max(0.0, _env_float("COST_USD_PER_M_OUTPUT", DEFAULT_COST_USD_PER_M_OUTPUT))


def cost_usd_per_m_cache_read() -> float:
    return max(
        0.0,
        _env_float("COST_USD_PER_M_CACHE_READ", DEFAULT_COST_USD_PER_M_CACHE_READ),
    )


def event_bus_buffer_size() -> int:
    return max(1, _env_int("EVENT_BUS_BUFFER_SIZE", DEFAULT_EVENT_BUS_BUFFER_SIZE))


def audit_log_max_queue() -> int:
    return max(1, _env_int("AUDIT_LOG_MAX_QUEUE", DEFAULT_AUDIT_LOG_MAX_QUEUE))


def ws_workspace_queue_maxsize() -> int:
    return max(1, _env_int("WS_WORKSPACE_QUEUE_MAXSIZE", DEFAULT_WS_WORKSPACE_QUEUE_MAXSIZE))


def ws_log_queue_maxsize() -> int:
    return max(1, _env_int("WS_LOG_QUEUE_MAXSIZE", DEFAULT_WS_LOG_QUEUE_MAXSIZE))


def ws_message_queue_maxsize() -> int:
    return max(1, _env_int("WS_MESSAGE_QUEUE_MAXSIZE", DEFAULT_WS_MESSAGE_QUEUE_MAXSIZE))


def estimated_agent_cost_usd() -> float:
    legacy = os.getenv("EST_COST_PER_AGENT_USD")
    if legacy is not None and legacy != "":
        try:
            value = float(legacy)
        except ValueError:
            return DEFAULT_ESTIMATED_AGENT_COST_USD
        return value if value > 0 else DEFAULT_ESTIMATED_AGENT_COST_USD
    return max(0.01, _env_float("ESTIMATED_AGENT_COST_USD", DEFAULT_ESTIMATED_AGENT_COST_USD))


def est_cost_per_agent_usd() -> float:
    return estimated_agent_cost_usd()


def budget_supported_concurrency(
    remaining_usd: float | None,
    configured_cap: int,
    *,
    soft_warn: bool = False,
    over_budget: bool = False,
) -> int:
    """Return a conservative concurrency cap based on remaining budget."""
    cap = max(1, configured_cap)
    if over_budget:
        return 1
    if remaining_usd is None:
        return cap
    affordable = int(max(0.0, remaining_usd) // estimated_agent_cost_usd())
    if affordable <= 0:
        return 1
    if not soft_warn and cap <= 3 and affordable >= 2:
        return cap
    if soft_warn:
        return max(1, min(cap, affordable, 2))
    return max(1, min(cap, affordable))


def max_concurrent_instances_per_role() -> int:
    return max(
        1,
        _env_int("MAX_CONCURRENT_INSTANCES_PER_ROLE", DEFAULT_MAX_CONCURRENT_INSTANCES_PER_ROLE),
    )


def role_slot_wait_s() -> int:
    return max(1, _env_int("ROLE_SLOT_WAIT_S", DEFAULT_ROLE_SLOT_WAIT_S))


# --- QA command execution ---------------------------------------------------
def qa_command_timeout_s() -> int:
    return max(1, _env_int("QA_COMMAND_TIMEOUT_S", DEFAULT_QA_COMMAND_TIMEOUT_S))


def qa_total_budget_s() -> int:
    return max(1, _env_int("QA_TOTAL_BUDGET_S", DEFAULT_QA_TOTAL_BUDGET_S))


def qa_execute_commands() -> bool:
    return _env_bool("QA_EXECUTE_COMMANDS", DEFAULT_QA_EXECUTE_COMMANDS)


# --- Background schedulers --------------------------------------------------
def project_review_interval_s() -> float:
    value = _env_float("PROJECT_REVIEW_INTERVAL_S", DEFAULT_PROJECT_REVIEW_INTERVAL_S)
    return value if value > 0 else DEFAULT_PROJECT_REVIEW_INTERVAL_S


def project_review_limit() -> int:
    return max(1, _env_int("PROJECT_REVIEW_LIMIT", DEFAULT_PROJECT_REVIEW_LIMIT))


def self_improvement_proposal_interval_s() -> float:
    value = _env_float(
        "SELF_IMPROVEMENT_PROPOSAL_INTERVAL_S",
        DEFAULT_SELF_IMPROVEMENT_PROPOSAL_INTERVAL_S,
    )
    return value if value > 0 else DEFAULT_SELF_IMPROVEMENT_PROPOSAL_INTERVAL_S


def self_improvement_proposal_limit() -> int:
    return max(
        1,
        _env_int("SELF_IMPROVEMENT_PROPOSAL_LIMIT", DEFAULT_SELF_IMPROVEMENT_PROPOSAL_LIMIT),
    )


def project_script_suggestion_timeout_s() -> int:
    return max(
        1,
        _env_int("PROJECT_SCRIPT_SUGGESTION_TIMEOUT_S", DEFAULT_PROJECT_SCRIPT_SUGGESTION_TIMEOUT_S),
    )


def project_script_verification_timeout_s() -> int:
    return max(
        1,
        _env_int(
            "PROJECT_SCRIPT_VERIFICATION_TIMEOUT_S",
            DEFAULT_PROJECT_SCRIPT_VERIFICATION_TIMEOUT_S,
        ),
    )


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
    raw_budget = _env_float("DEFAULT_ISSUE_BUDGET_USD", DEFAULT_ISSUE_BUDGET_USD)
    if raw_budget < 0:
        violations.append(f"DEFAULT_ISSUE_BUDGET_USD ({raw_budget}) must be >= 0.")
    raw_warn = _env_float("BUDGET_SOFT_WARN_RATIO", DEFAULT_BUDGET_SOFT_WARN_RATIO)
    if raw_warn <= 0 or raw_warn > 1:
        violations.append(f"BUDGET_SOFT_WARN_RATIO ({raw_warn}) must be > 0 and <= 1.")
    for name, value in (
        ("CONDUCTOR_RECOVERY_INTERVAL_S", recovery_interval_s()),
        ("CONDUCTOR_LOOP_MAX_S", conductor_loop_max_s()),
        ("CONDUCTOR_MAX_DISPATCHES_PER_ROLE", conductor_max_dispatches_per_role()),
        ("PROCESS_IDLE_TIMEOUT", process_idle_timeout_s()),
        ("PROCESS_MAX_TIMEOUT", process_max_timeout_s()),
        ("WORKFLOW_ORCHESTRATOR_TIMEOUT", workflow_orchestrator_timeout_s()),
        ("WORKFLOW_ORCHESTRATOR_MAX_TOKENS", workflow_orchestrator_max_tokens()),
        ("CONDUCTOR_LLM_TIMEOUT", conductor_llm_timeout_s()),
        ("CONDUCTOR_LLM_MAX_TOKENS", conductor_llm_max_tokens()),
        ("EMBEDDING_TIMEOUT_S", embedding_timeout_s()),
        ("CODEX_STALL_THRESHOLD_S", stall_threshold_s()),
        ("CODEX_STALL_INTERVAL_S", stall_interval_s()),
        ("CODEX_STALL_COOLDOWN_S", stall_cooldown_s()),
        ("MAX_PARALLEL_DISPATCH_PER_BATCH", max_parallel_dispatch_per_batch()),
        ("EST_COST_PER_AGENT_USD", est_cost_per_agent_usd()),
        ("MAX_CONCURRENT_INSTANCES_PER_ROLE", max_concurrent_instances_per_role()),
        ("ROLE_SLOT_WAIT_S", role_slot_wait_s()),
        ("QA_COMMAND_TIMEOUT_S", qa_command_timeout_s()),
        ("QA_TOTAL_BUDGET_S", qa_total_budget_s()),
        ("PROJECT_REVIEW_INTERVAL_S", project_review_interval_s()),
        ("PROJECT_REVIEW_LIMIT", project_review_limit()),
        (
            "SELF_IMPROVEMENT_PROPOSAL_INTERVAL_S",
            self_improvement_proposal_interval_s(),
        ),
        ("SELF_IMPROVEMENT_PROPOSAL_LIMIT", self_improvement_proposal_limit()),
        ("PROJECT_SCRIPT_SUGGESTION_TIMEOUT_S", project_script_suggestion_timeout_s()),
        ("PROJECT_SCRIPT_VERIFICATION_TIMEOUT_S", project_script_verification_timeout_s()),
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
