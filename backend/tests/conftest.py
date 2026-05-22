# Set CODEX_LAUNCH_ENABLED=false BEFORE any app imports
# This must be at the very top, before any other imports
import os
import shutil
import tempfile
os.environ["CODEX_LAUNCH_ENABLED"] = "false"

# Use an isolated test SQLite database so tests never touch the real console.db
_test_db_path = os.path.join(os.path.dirname(__file__), "test_console.db")
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
    Resets the SQLite store after each test, deleting all data from all tables.
    This prevents test-created sessions/runs/etc. from leaking into subsequent tests.
    """
    yield
    import app.bootstrap as bootstrap_module
    try:
        store = bootstrap_module.store
        if store is not None:
            store.reset()
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
