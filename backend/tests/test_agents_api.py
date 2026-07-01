"""PR1: Agent CRUD endpoints + built-in seed.

These tests share the session-scoped TestClient from conftest.py. The
`reset_sqlite_store` autouse fixture wipes user-created rows between tests,
but built-in agents are re-seeded by the FastAPI lifespan handler.
"""

import pytest

from app.application.agent_seed import seed_builtin_agents


def _run_async(coro):
    """Run an async coroutine in a one-shot loop (Py3.14-safe — no get_event_loop)."""
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture(autouse=True)
def reseed_builtins():
    """Reset wipes the agents table along with everything else, so reseed
    before each test (lifespan only runs once for the session-scoped client)."""
    import app.bootstrap as bootstrap_module

    if bootstrap_module.async_store is not None:
        _run_async(seed_builtin_agents(bootstrap_module.async_store))
    yield


def test_seed_creates_managed_and_specialist_builtin_agents(client):
    resp = client.get("/api/agents")
    assert resp.status_code == 200
    agents = resp.json()
    builtins = [a for a in agents if a["is_builtin"]]
    role_keys = {a["role_key"] for a in builtins}
    assert {"architect", "engineer", "product_manager", "qa"} <= role_keys
    assert "specialist:security_reviewer" in role_keys
    assert "specialist:performance_reviewer" in role_keys
    assert {a["agent_tier"] for a in builtins} == {"managed", "specialist"}


def test_seed_is_idempotent(client):
    """Running seed twice should not create duplicates."""
    import app.bootstrap as bootstrap_module

    _run_async(seed_builtin_agents(bootstrap_module.async_store))
    _run_async(seed_builtin_agents(bootstrap_module.async_store))
    resp = client.get("/api/agents")
    builtins = [a for a in resp.json() if a["is_builtin"]]
    assert len(builtins) == 16


def test_builtin_pm_and_architect_trigger_replan_on_done(client):
    resp = client.get("/api/agents")
    by_role = {a["role_key"]: a for a in resp.json()}
    assert by_role["product_manager"]["triggers_replan_on_done"] is True
    assert by_role["architect"]["triggers_replan_on_done"] is True
    assert by_role["engineer"]["triggers_replan_on_done"] is False
    assert by_role["qa"]["triggers_replan_on_done"] is False


def test_builtin_qa_triggers_replan_on_fail(client):
    resp = client.get("/api/agents")
    by_role = {a["role_key"]: a for a in resp.json()}
    assert by_role["qa"]["triggers_replan_on_fail"] is True
    assert by_role["engineer"]["triggers_replan_on_fail"] is False


def test_create_custom_agent(client):
    payload = {
        "name": "Security Reviewer",
        "role_key": "custom_security_reviewer",
        "description": "Audits code for security issues.",
        "system_prompt_template": "Review {issue_title} for security vulnerabilities.",
    }
    resp = client.post("/api/agents", json=payload)
    assert resp.status_code == 201, resp.text
    agent = resp.json()
    assert agent["role_key"] == "custom_security_reviewer"
    assert agent["is_builtin"] is False
    assert agent["agent_tier"] == "custom"
    assert agent["artifact_subdir"] == "node_custom_security_reviewer"
    # Listing should now surface it
    listing = client.get("/api/agents").json()
    assert any(a["role_key"] == "custom_security_reviewer" for a in listing)


def test_create_agent_rejects_duplicate_role_key_in_same_scope(client):
    payload = {
        "name": "Sec1",
        "role_key": "duplicate_scope_reviewer",
        "system_prompt_template": "x",
    }
    assert client.post("/api/agents", json=payload).status_code == 201
    # Same role_key, same scope (workspace_id None) → 409
    dup_resp = client.post("/api/agents", json=payload)
    assert dup_resp.status_code == 409


def test_update_custom_agent(client):
    payload = {
        "name": "Perf Analyst",
        "role_key": "perf_analyst",
        "system_prompt_template": "Original",
    }
    created = client.post("/api/agents", json=payload).json()
    updated = client.patch(
        f"/api/agents/{created['id']}",
        json={"system_prompt_template": "Revised template"},
    )
    assert updated.status_code == 200
    assert updated.json()["system_prompt_template"] == "Revised template"


def test_builtin_agent_only_allows_editing_replan_flags(client):
    listing = client.get("/api/agents").json()
    pm = next(a for a in listing if a["role_key"] == "product_manager")
    # Allowed: flip the flag
    resp_ok = client.patch(f"/api/agents/{pm['id']}", json={"triggers_replan_on_done": False})
    assert resp_ok.status_code == 200
    assert resp_ok.json()["triggers_replan_on_done"] is False
    # Forbidden: rename a built-in
    resp_no = client.patch(f"/api/agents/{pm['id']}", json={"name": "Renamed PM"})
    assert resp_no.status_code == 400


def test_delete_custom_agent(client):
    payload = {
        "name": "Throwaway",
        "role_key": "throwaway_role",
        "system_prompt_template": "x",
    }
    created = client.post("/api/agents", json=payload).json()
    resp = client.delete(f"/api/agents/{created['id']}")
    assert resp.status_code == 204
    assert client.get(f"/api/agents/{created['id']}").status_code == 404


def test_delete_builtin_agent_forbidden(client):
    listing = client.get("/api/agents").json()
    pm = next(a for a in listing if a["role_key"] == "product_manager")
    resp = client.delete(f"/api/agents/{pm['id']}")
    assert resp.status_code == 400
