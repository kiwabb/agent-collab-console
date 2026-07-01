"""Tests for the process-wide per-role concurrency limiter."""

from __future__ import annotations

import asyncio

import pytest

from app.application.role_concurrency import RoleConcurrencyLimiter


@pytest.fixture(autouse=True)
def reset_limiter():
    RoleConcurrencyLimiter._instance = None
    yield
    RoleConcurrencyLimiter._instance = None


@pytest.mark.asyncio
async def test_cap_is_enforced_per_role(monkeypatch):
    """Up to the limit acquire immediately; the next same-role acquire is refused;
    other roles are independent; releasing frees a slot."""
    monkeypatch.setenv("MAX_CONCURRENT_INSTANCES_PER_ROLE", "2")
    lim = RoleConcurrencyLimiter.instance()

    assert await lim.acquire("engineer", timeout=0)
    assert await lim.acquire("engineer", timeout=0)
    # Third engineer over the cap is refused without blocking.
    assert not await lim.acquire("engineer", timeout=0)
    # A different role has its own independent budget.
    assert await lim.acquire("qa", timeout=0)

    lim.release("engineer")
    assert await lim.acquire("engineer", timeout=0)


@pytest.mark.asyncio
async def test_acquire_blocks_then_times_out(monkeypatch):
    """When saturated, a positive-timeout acquire waits and then returns False."""
    monkeypatch.setenv("MAX_CONCURRENT_INSTANCES_PER_ROLE", "1")
    lim = RoleConcurrencyLimiter.instance()

    assert await lim.acquire("engineer", timeout=0)
    assert not await lim.acquire("engineer", timeout=0.05)


@pytest.mark.asyncio
async def test_acquire_unblocks_when_slot_freed(monkeypatch):
    """A waiter acquires as soon as a holder releases, before its timeout."""
    monkeypatch.setenv("MAX_CONCURRENT_INSTANCES_PER_ROLE", "1")
    lim = RoleConcurrencyLimiter.instance()
    assert await lim.acquire("engineer", timeout=0)

    async def _release_soon():
        await asyncio.sleep(0.02)
        lim.release("engineer")

    asyncio.create_task(_release_soon())  # noqa: RUF006
    assert await lim.acquire("engineer", timeout=2.0)


@pytest.mark.asyncio
async def test_slot_context_manager_releases_on_exit(monkeypatch):
    monkeypatch.setenv("MAX_CONCURRENT_INSTANCES_PER_ROLE", "1")
    lim = RoleConcurrencyLimiter.instance()

    async with lim.slot("engineer", timeout=0) as acquired:
        assert acquired
        # Cap reached while the slot is held.
        assert not await lim.acquire("engineer", timeout=0)
    # Exiting the context frees the slot.
    assert await lim.acquire("engineer", timeout=0)


@pytest.mark.asyncio
async def test_slot_yields_false_when_saturated(monkeypatch):
    """When no slot frees within the timeout, the context yields False and does
    NOT hold a slot (nothing to release)."""
    monkeypatch.setenv("MAX_CONCURRENT_INSTANCES_PER_ROLE", "1")
    lim = RoleConcurrencyLimiter.instance()
    assert await lim.acquire("engineer", timeout=0)

    async with lim.slot("engineer", timeout=0) as acquired:
        assert acquired is False
    # The held slot from the manual acquire is still the only one; releasing it
    # should restore full capacity (proving the context did not double-release).
    lim.release("engineer")
    assert await lim.acquire("engineer", timeout=0)
    assert not await lim.acquire("engineer", timeout=0)
