"""Process-local Conductor lease identity and timing helpers.

The lease *timing* values live in :mod:`app.application.timeouts` (the single
source of truth for the whole timeout ladder); the getters here delegate to it
so the lease identity (owner) and timing stay in one import for callers.
"""

from __future__ import annotations

import os
from uuid import uuid4

from app.application import timeouts

_LEASE_OWNER = f"pid:{os.getpid()}:{uuid4()}"


def get_conductor_lease_owner() -> str:
    return _LEASE_OWNER


def get_conductor_lease_ttl_s() -> int:
    return timeouts.lease_ttl_s()


def get_conductor_recovery_interval_s() -> int:
    return timeouts.recovery_interval_s()


def conductor_recovery_enabled() -> bool:
    raw = (os.getenv("CONDUCTOR_RECOVERY_ENABLED") or "").strip().lower()
    if raw in {"0", "false", "no", "off"}:  # noqa: SIM103
        return False
    return True
