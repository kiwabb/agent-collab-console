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
