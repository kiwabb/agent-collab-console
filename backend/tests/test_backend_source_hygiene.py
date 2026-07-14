from __future__ import annotations

import ast
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = BACKEND_ROOT / "app"
BENCHMARK_ROOT = BACKEND_ROOT / "benchmark"
LOCAL_PROCESS_ADAPTER = APP_ROOT / "adapters" / "local_process.py"
SYNC_SUBPROCESS_CALLS = {
    "call",
    "check_call",
    "check_output",
    "Popen",
    "run",
}
LOCAL_JSON_SAFETY = APP_ROOT / "json_safety.py"
INLINE_JSON_OBJECT_GUARD_NAMES = {
    "_object_dict",
    "_object_mapping",
    "object_dict",
}
STREAMING_JSON_BOUNDARY_FILES = {
    APP_ROOT / "application" / "llm_runner.py",
}
SAFE_READ_JSON_BOUNDARY_FILES = {
    APP_ROOT / "application" / "conductor_policy.py",
    APP_ROOT / "application" / "knowledge_index_service.py",
    APP_ROOT / "application" / "project_memory_service.py",
    APP_ROOT / "application" / "review_guard.py",
    APP_ROOT / "application" / "self_improvement_apply_service.py",
    APP_ROOT / "application" / "self_improvement_service.py",
}
TYPE_ESCAPE_TEXT_PATTERNS = {
    "type: ignore",
    "# type: ignore",
    "from typing import Any",
    "dict[str, Any]",
    "list[dict[str, Any]]",
    "Awaitable[Any]",
    "cast(Any",
}
EXPECTED_BARE_EXCEPT_PASS = [
    "app/adapters/async_sqlite_store.py:AsyncSQLiteStore.load_session.load_artifacts:JSONDecodeError|TypeError",
    "app/adapters/sqlite_store.py:SQLiteStore.load_session:JSONDecodeError|TypeError",
    "app/application/audit/writer.py:AuditLogger.shutdown:CancelledError|Exception",
    "app/application/codex_process_manager.py:CodexProcessManager.terminate:KeyError",
    "app/application/engineer_workflow.py:git_changed_files:FileNotFoundError|TimeoutExpired",
    "app/application/json_rpc_client.py:AsyncJsonRpcPeer._async_reader_loop:CancelledError",
    "app/application/process_runtime_common.py:BaseProcessRuntime._list_task_messages:TypeError",
    "app/application/process_runtime_common.py:BaseProcessRuntime._watchdog:CancelledError",
    "app/application/project_run_manager.py:ProjectRunManager._signal_pg:ProcessLookupError",
    "app/application/project_run_manager.py:ProjectRunManager._terminate:CancelledError|Exception",
    "app/application/review_guard.py:git_diff_summary:FileNotFoundError|TimeoutExpired",
    "app/application/tolerant_json.py:tolerant_json_loads:JSONDecodeError",
    "app/application/tolerant_json.py:tolerant_json_loads:JSONDecodeError",
    "app/application/worktree_manager.py:WorktreeManager._cleanup_path:GitError",
    "app/application/worktree_manager.py:WorktreeManager._collect_conflict:GitError",
    "app/application/worktree_manager.py:WorktreeManager.cleanup_issue_swarm_worktrees:GitError",
    "app/application/worktree_manager.py:WorktreeManager.cleanup_issue_worktree_for_reset:GitError",
    "app/application/worktree_manager.py:WorktreeManager.cleanup_issue_worktree_for_reset:GitError",
    "app/application/worktree_manager.py:WorktreeManager.merge_agent_worktrees:GitError",
    "app/interfaces/api.py:_list_task_messages:TypeError",
    "app/interfaces/codex_ws.py:_serve_subscriber:WebSocketDisconnect",
    "app/interfaces/ws_events.py:global_events_ws:WebSocketDisconnect",
]


def _python_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)


def _exception_names(handler: ast.ExceptHandler) -> str:
    if handler.type is None:
        return "<bare>"
    if isinstance(handler.type, ast.Name):
        return handler.type.id
    if isinstance(handler.type, ast.Attribute):
        return handler.type.attr
    if isinstance(handler.type, ast.Tuple):
        names: list[str] = []
        for item in handler.type.elts:
            if isinstance(item, ast.Name):
                names.append(item.id)
            elif isinstance(item, ast.Attribute):
                names.append(item.attr)
            else:
                names.append(ast.unparse(item))
        return "|".join(names)
    return ast.unparse(handler.type)


def _enclosing_scope(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str:
    names: list[str] = []
    cursor = node
    while cursor in parents:
        cursor = parents[cursor]
        if isinstance(cursor, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.append(cursor.name)
    return ".".join(reversed(names)) or "<module>"


def test_backend_app_uses_logger_instead_of_print_calls() -> None:
    matches: list[str] = []
    for path in _python_files(APP_ROOT):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "print"
            ):
                rel = path.relative_to(BACKEND_ROOT)
                matches.append(f"{rel}:{node.lineno}: print(...)")

    assert matches == []


def test_backend_app_logger_calls_do_not_use_fstrings() -> None:
    matches: list[str] = []
    for path in _python_files(APP_ROOT):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "logger"
                and node.func.attr
                in {"critical", "debug", "error", "exception", "info", "warning"}
                and node.args
                and isinstance(node.args[0], ast.JoinedStr)
            ):
                continue
            rel = path.relative_to(BACKEND_ROOT)
            matches.append(f"{rel}:{node.lineno}: logger.{node.func.attr}(f...)")

    assert matches == []


def test_sync_subprocess_calls_stay_behind_local_process_adapter() -> None:
    matches: list[str] = []
    for root in (APP_ROOT, BENCHMARK_ROOT):
        for path in _python_files(root):
            if path == LOCAL_PROCESS_ADAPTER:
                continue
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "subprocess"
                    and node.func.attr in SYNC_SUBPROCESS_CALLS
                ):
                    continue
                rel = path.relative_to(BACKEND_ROOT)
                matches.append(f"{rel}:{node.lineno}: subprocess.{node.func.attr}(...)")

    assert matches == []


def test_json_object_guards_stay_behind_shared_json_safety_helper() -> None:
    matches: list[str] = []
    for path in _python_files(APP_ROOT):
        if path == LOCAL_JSON_SAFETY:
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
                and node.name in INLINE_JSON_OBJECT_GUARD_NAMES
            ):
                continue
            rel = path.relative_to(BACKEND_ROOT)
            matches.append(f"{rel}:{node.lineno}: def {node.name}(...)")

    assert matches == []


def test_streaming_json_boundaries_use_shared_json_safety_parser() -> None:
    matches: list[str] = []
    for path in sorted(STREAMING_JSON_BOUNDARY_FILES):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "json"
                and node.func.attr == "loads"
            ):
                continue
            rel = path.relative_to(BACKEND_ROOT)
            matches.append(f"{rel}:{node.lineno}: json.loads(...)")

    assert matches == []


def test_safe_read_json_boundaries_use_shared_json_safety_parser() -> None:
    matches: list[str] = []
    for path in sorted(SAFE_READ_JSON_BOUNDARY_FILES):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "json"
                and node.func.attr == "loads"
            ):
                continue
            rel = path.relative_to(BACKEND_ROOT)
            matches.append(f"{rel}:{node.lineno}: json.loads(...)")

    assert matches == []


def test_api_json_row_types_do_not_use_any() -> None:
    source = (APP_ROOT / "interfaces" / "api.py").read_text()

    assert "dict[str, Any]" not in source
    assert "from typing import Any" not in source


def test_backend_sources_do_not_reintroduce_explicit_type_escapes() -> None:
    matches: list[str] = []
    this_file = Path(__file__).resolve()
    for root in (APP_ROOT, BENCHMARK_ROOT, BACKEND_ROOT / "tests"):
        for path in _python_files(root):
            if path == this_file:
                continue
            rel = path.relative_to(BACKEND_ROOT)
            for lineno, line in enumerate(path.read_text().splitlines(), start=1):
                for pattern in TYPE_ESCAPE_TEXT_PATTERNS:
                    if pattern in line:
                        matches.append(f"{rel}:{lineno}: {pattern}")

    assert matches == []


def test_bare_except_pass_sites_stay_explicitly_allowlisted() -> None:
    matches: list[str] = []
    for root in (APP_ROOT, BENCHMARK_ROOT):
        for path in _python_files(root):
            tree = ast.parse(path.read_text(), filename=str(path))
            parents = {
                child: node
                for node in ast.walk(tree)
                for child in ast.iter_child_nodes(node)
            }
            for node in ast.walk(tree):
                if not (
                    isinstance(node, ast.ExceptHandler)
                    and len(node.body) == 1
                    and isinstance(node.body[0], ast.Pass)
                ):
                    continue
                rel = path.relative_to(BACKEND_ROOT)
                matches.append(
                    f"{rel}:{_enclosing_scope(node, parents)}:{_exception_names(node)}"
                )

    assert sorted(matches) == sorted(EXPECTED_BARE_EXCEPT_PASS)
