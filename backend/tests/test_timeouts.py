"""Timeout ladder single-source-of-truth: defaults + invariant assertions."""
from __future__ import annotations

import pytest

from app.application import timeouts


def test_defaults_pass_invariants():
    """The shipped defaults must satisfy every invariant."""
    assert timeouts.validate(strict=True) == []
    assert timeouts.check_invariants() == []


def test_default_values_match_shipped_ladder():
    # These are the shipped defaults. subagent_idle was raised 600→1200 so the
    # stall watchdog (900s) can reap a hung subprocess before the conductor
    # gives up and re-dispatches; idle must stay > stall_threshold + 120.
    assert timeouts.lease_ttl_s() == 180
    assert timeouts.recovery_interval_s() == 30
    assert timeouts.subagent_idle_s() == 1200.0
    assert timeouts.subagent_max_s() == 3600.0
    assert timeouts.codex_turn_timeout_s() == 480
    assert timeouts.codex_idle_timeout_s() == 180
    assert timeouts.stall_threshold_s() == 900
    assert timeouts.stall_interval_s() == 30
    assert timeouts.stall_cooldown_s() == 900


def test_lease_pulse_interval_formula(monkeypatch):
    # Default: max(15, 180 // 3) == 60
    assert timeouts.lease_pulse_interval_s() == 60
    # Small TTL clamps to the 15s floor: max(15, 30 // 3) == 15
    monkeypatch.setenv("CONDUCTOR_LEASE_TTL_S", "30")
    assert timeouts.lease_pulse_interval_s() == 15


def test_lease_ttl_must_be_under_subagent_idle(monkeypatch):
    # A lease TTL >= subagent idle is the classic orphan-relaunch trap.
    # (idle default is 1200, so use a TTL above it to trip the invariant.)
    monkeypatch.setenv("CONDUCTOR_LEASE_TTL_S", "1300")
    violations = timeouts.check_invariants()
    assert any("CONDUCTOR_LEASE_TTL_S" in v for v in violations)
    with pytest.raises(timeouts.TimeoutConfigError):
        timeouts.validate(strict=True)


def test_subagent_idle_must_exceed_stall_threshold(monkeypatch):
    # The stall watchdog must get a chance to terminate a hung subprocess
    # before the conductor's idle timeout re-dispatches.
    monkeypatch.setenv("CONDUCTOR_SUBAGENT_IDLE_S", "600")  # < stall(900)+120
    violations = timeouts.check_invariants()
    assert any("CODEX_STALL_THRESHOLD_S" in v for v in violations)


def test_codex_idle_must_not_exceed_turn_budget(monkeypatch):
    monkeypatch.setenv("CODEX_IDLE_TIMEOUT_S", "9999")
    violations = timeouts.check_invariants()
    assert any("CODEX_IDLE_TIMEOUT_S" in v for v in violations)


def test_subagent_idle_must_not_exceed_hard_ceiling(monkeypatch):
    monkeypatch.setenv("CONDUCTOR_SUBAGENT_IDLE_S", "99999")
    violations = timeouts.check_invariants()
    assert any("CONDUCTOR_SUBAGENT_IDLE_S" in v for v in violations)


def test_non_positive_cadence_rejected(monkeypatch):
    monkeypatch.setenv("CODEX_STALL_INTERVAL_S", "0")
    violations = timeouts.check_invariants()
    assert any("CODEX_STALL_INTERVAL_S" in v for v in violations)


def test_invalid_env_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("CONDUCTOR_LEASE_TTL_S", "not-a-number")
    assert timeouts.lease_ttl_s() == 180
    monkeypatch.setenv("CONDUCTOR_SUBAGENT_IDLE_S", "garbage")
    assert timeouts.subagent_idle_s() == 1200.0


def test_validate_non_strict_returns_without_raising(monkeypatch):
    monkeypatch.setenv("CONDUCTOR_LEASE_TTL_S", "1300")  # >= idle(1200) → violation
    # Non-strict must not raise even when invariants are violated.
    violations = timeouts.validate(strict=False)
    assert violations  # non-empty
