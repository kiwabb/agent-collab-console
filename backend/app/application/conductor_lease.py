"""Process-local Conductor lease identity and timing helpers."""
from __future__ import annotations

import os
from uuid import uuid4

_LEASE_OWNER = f"pid:{os.getpid()}:{uuid4()}"


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def get_conductor_lease_owner() -> str:
    return _LEASE_OWNER


def get_conductor_lease_ttl_s() -> int:
    return _env_int("CONDUCTOR_LEASE_TTL_S", 180)


def get_conductor_recovery_interval_s() -> int:
    return _env_int("CONDUCTOR_RECOVERY_INTERVAL_S", 30)


def conductor_recovery_enabled() -> bool:
    raw = (os.getenv("CONDUCTOR_RECOVERY_ENABLED") or "").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    return True
