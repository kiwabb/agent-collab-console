"""
Common utilities for Trellis workflow scripts.

This module provides shared functionality used by other Trellis scripts.
"""

import io
import sys

# =============================================================================
# Windows Encoding Fix (MUST be at top, before any other output)
# =============================================================================
# On Windows, stdout defaults to the system code page (often GBK/CP936).
# This causes UnicodeEncodeError when printing non-ASCII characters.
#
# Any script that imports from common will automatically get this fix.
# =============================================================================


def _configure_stream(stream: object) -> object:
    """Configure a stream for UTF-8 encoding on Windows."""
    # Try reconfigure() first (Python 3.7+, more reliable)
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        return stream
    # Fallback: detach and rewrap with TextIOWrapper
    elif hasattr(stream, "detach"):
        return io.TextIOWrapper(
            stream.detach(),  # type: ignore[union-attr]
            encoding="utf-8",
            errors="replace",
        )
    return stream


if sys.platform == "win32":
    sys.stdout = _configure_stream(sys.stdout)  # type: ignore[assignment]
    sys.stderr = _configure_stream(sys.stderr)  # type: ignore[assignment]
    sys.stdin = _configure_stream(sys.stdin)  # type: ignore[assignment]


def configure_encoding() -> None:
    """
    Configure stdout/stderr/stdin for UTF-8 encoding on Windows.

    This is automatically called when importing from common,
    but can be called manually for scripts that don't import common.

    Safe to call multiple times.
    """
    global sys
    if sys.platform == "win32":
        sys.stdout = _configure_stream(sys.stdout)  # type: ignore[assignment]
        sys.stderr = _configure_stream(sys.stderr)  # type: ignore[assignment]
        sys.stdin = _configure_stream(sys.stdin)  # type: ignore[assignment]


from .paths import (  # noqa: E402
    DIR_WORKFLOW,  # noqa: F401
    DIR_WORKSPACE,  # noqa: F401
    DIR_TASKS,  # noqa: F401
    DIR_ARCHIVE,  # noqa: F401
    DIR_SPEC,  # noqa: F401
    DIR_SCRIPTS,  # noqa: F401
    FILE_DEVELOPER,  # noqa: F401
    FILE_CURRENT_TASK,  # noqa: F401
    FILE_TASK_JSON,  # noqa: F401
    FILE_JOURNAL_PREFIX,  # noqa: F401
    get_repo_root,  # noqa: F401
    get_developer,  # noqa: F401
    check_developer,  # noqa: F401
    get_tasks_dir,  # noqa: F401
    get_workspace_dir,  # noqa: F401
    get_active_journal_file,  # noqa: F401
    count_lines,  # noqa: F401
    get_current_task,  # noqa: F401
    get_current_task_abs,  # noqa: F401
    normalize_task_ref,  # noqa: F401
    resolve_task_ref,  # noqa: F401
    set_current_task,  # noqa: F401
    clear_current_task,  # noqa: F401
    has_current_task,  # noqa: F401
    generate_task_date_prefix,  # noqa: F401
)

from .active_task import (  # noqa: E402
    ActiveTask,  # noqa: F401
    clear_active_task,  # noqa: F401
    resolve_active_task,  # noqa: F401
    resolve_context_key,  # noqa: F401
    set_active_task,  # noqa: F401
)
