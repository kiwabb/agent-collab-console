from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.routing import APIRoute

from app.adapters.async_sqlite_store import AsyncSQLiteStore

LEGACY_PROTOTYPE_TABLES = {
    "prototype_generation_run_items",
    "prototype_generation_runs",
    "prototype_plan_items",
    "prototype_plans",
    "prototype_versions",
    "prototypes",
}


def _table_names(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {str(row[0]) for row in rows}


@pytest.mark.asyncio
async def test_schema_v12_drops_legacy_html_prototype_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "console.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE schema_version (id INTEGER PRIMARY KEY, version INTEGER NOT NULL)"
        )
        conn.execute("INSERT INTO schema_version (id, version) VALUES (1, 11)")
        for table in LEGACY_PROTOTYPE_TABLES:
            conn.execute(f"CREATE TABLE {table} (id TEXT PRIMARY KEY)")
            conn.execute(f"INSERT INTO {table} (id) VALUES ('legacy')")

    store = AsyncSQLiteStore(db_path)
    try:
        await store._ensure_db()
        async_conn = await store._get_conn()
        version = await (
            await async_conn.execute("SELECT version FROM schema_version WHERE id = 1")
        ).fetchone()
    finally:
        await store.close()

    assert version == (17,)
    assert _table_names(db_path).isdisjoint(LEGACY_PROTOTYPE_TABLES)


@pytest.mark.asyncio
async def test_new_database_does_not_create_legacy_html_prototype_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "console.db"
    store = AsyncSQLiteStore(db_path)
    try:
        await store._ensure_db()
    finally:
        await store.close()

    assert _table_names(db_path).isdisjoint(LEGACY_PROTOTYPE_TABLES)


def test_legacy_html_prototype_routes_are_not_registered() -> None:
    from app.main import app

    registered_paths = {route.path for route in app.routes if isinstance(route, APIRoute)}
    assert registered_paths.isdisjoint(
        {
            "/api/prototype-plans/config",
            "/api/projects/{project_id}/prototype-plans",
            "/api/prototype-plans/{plan_id}",
            "/api/prototype-generation-runs/{run_id}",
            "/api/projects/{project_id}/prototypes",
            "/api/prototypes/{prototype_id}",
            "/api/prototypes/{prototype_id}/versions/{version_no}",
            "/api/prototypes/{prototype_id}/stream",
        }
    )
