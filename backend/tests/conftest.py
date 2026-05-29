# Set CODEX_LAUNCH_ENABLED=false BEFORE any app imports
# This must be at the very top, before any other imports
import os
import shutil
import tempfile
os.environ["CODEX_LAUNCH_ENABLED"] = "false"

# Use an isolated test SQLite database so tests never touch the real console.db
_test_db_path = os.path.join(os.path.dirname(__file__), "test_console.db")
# Clean up any leftover database files from previous aborted sessions to prevent FTS5 version mismatches
for suffix in ["", "-wal", "-shm"]:
    try:
        p = _test_db_path + suffix
        if os.path.exists(p):
            os.remove(p)
    except Exception:
        pass
os.environ["SQLITE_DB_PATH"] = _test_db_path

_test_workspace_root = os.path.join(tempfile.gettempdir(), "agent-collab-console-test-workspaces")
os.environ["CODEX_WORKSPACE_ROOT"] = _test_workspace_root
shutil.rmtree(_test_workspace_root, ignore_errors=True)

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient


@pytest.fixture(scope="session", autouse=True)
def clean_test_db_file():
    """Remove the test SQLite file after the test session completes."""
    yield
    try:
        os.remove(_test_db_path)
    except OSError:
        pass


@pytest.fixture(scope="session", autouse=True)
def clean_test_workspace_root():
    """Remove temporary task workspaces after the test session completes."""
    yield
    shutil.rmtree(_test_workspace_root, ignore_errors=True)
    try:
        os.remove(_test_db_path + "-wal")
    except OSError:
        pass
    try:
        os.remove(_test_db_path + "-shm")
    except OSError:
        pass


@pytest.fixture(scope="session")
def client():
    """
    Session-scoped TestClient fixture. The client is created once for the whole
    test session and shared across all tests, matching the original module-level
    pattern but with explicit fixture lifecycle control. Cross-test state cleanup
    (process manager, in-flight sessions) is handled by the per-test
    reset_process_manager autouse fixture rather than by entering/exiting the
    lifespan context on each test, which would hang on WebSocket/SSE drain.
    """
    from app.main import app
    from fastapi.testclient import TestClient
    yield TestClient(app)


@pytest.fixture(autouse=True)
def force_codex_available(monkeypatch):
    """
    Forces check_codex_available() to return True for all tests.
    This removes the ambient machine state dependency: tests no longer need
    the real 'codex' binary to be installed to run.
    """
    import app.bootstrap as bootstrap_module
    monkeypatch.setattr(bootstrap_module, "check_codex_available", lambda: True)


@pytest.fixture(autouse=True)
def reset_sqlite_store():
    """
    Resets the SQLite store after each test by deleting the database files and recreating them.
    This is extremely robust, completely avoiding any lock issues and FTS5 shadow table corruption.
    """
    yield
    import app.bootstrap as bootstrap_module
    import asyncio
    import os
    import time

    # 1. Close any persistent connections on the async_store to release locks
    try:
        async_store = bootstrap_module.async_store
        if async_store is not None:
            if async_store._conn is not None:
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = None

                if loop and loop.is_running():
                    future = asyncio.run_coroutine_threadsafe(async_store.close(), loop)
                    future.result(timeout=2.0)
                else:
                    asyncio.run(async_store.close())
            async_store._conn = None
    except Exception:
        pass

    # 2. Safely delete the database file and its WAL files
    db_path = bootstrap_module.db_path
    for attempt in range(5):
        try:
            for suffix in ["", "-wal", "-shm"]:
                p = str(db_path) + suffix
                if os.path.exists(p):
                    os.remove(p)
            break
        except Exception:
            if attempt < 4:
                time.sleep(0.1)
                continue

    # 3. Re-initialize the databases so they are ready for the next test
    try:
        store = bootstrap_module.store
        if store is not None:
            store._init_db()
    except Exception:
        pass

    try:
        async_store = bootstrap_module.async_store
        if async_store is not None:
            async_store._conn = None
    except Exception:
        pass


@pytest_asyncio.fixture(autouse=True)
async def reset_process_manager():
    """
    Resets the global codex_process_manager after each test to prevent cross-test pollution.
    Terminates all running sessions and clears _processes dict so each test
    starts with a clean MockCodexProcessManager.
    """
    yield
    import app.bootstrap as bootstrap_module
    try:
        mgr = bootstrap_module.codex_process_manager
        if mgr is not None:
            # Terminate all sessions first (while _processes still populated),
            # then clear the dict so the next test gets a clean state
            await mgr.terminate_all()
            mgr._processes.clear()
    except Exception:
        pass
    # Reset global so next get_codex_process_manager() call creates a fresh instance
    bootstrap_module.codex_process_manager = None
