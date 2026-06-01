"""Shared, parameterized query builder for the `audit_log` read path (PR3).

Both the async (`async_sqlite_store`) and sync (`sqlite_store`) stores call this
single builder so their `list_audit_logs` SQL stays byte-identical. The builder
is pure and fully parameterized — every user-controllable value is bound via a
`?` placeholder, never string-interpolated, so `q`/`category`/cursor inputs
containing `%`, `_`, `'`, or `;` are inert (no SQL injection, no LIKE-wildcard
escalation: the LIKE pattern is bound as a value so `%`/`_` inside `q` are
treated literally only insofar as SQLite's LIKE allows — and crucially cannot
break out of the parameter).

Pagination is cursor-based on the composite key `(created_at, id)` which the
`ORDER BY` already sorts on. For descending (newest-first) order the keyset
predicate is `(created_at, id) < (cursor_created_at, cursor_id)`; SQLite
supports row-value comparison directly, so this is a clean keyset page that is
immune to offset drift when new rows arrive mid-pagination.
"""

from __future__ import annotations

_LIMIT_HARD_CAP = 5000


def _normalize_categories(
    category: str | None, categories: list[str] | None
) -> list[str]:
    """Merge the legacy single `category` arg with the multi-value `categories`.

    De-dupes while preserving order and drops blanks. Keeping the singular
    `category` keyword preserves backward compatibility with PR1/PR2 callers and
    existing tests.
    """
    merged: list[str] = []
    seen: set[str] = set()
    for value in [category, *(categories or [])]:
        if value is None:
            continue
        value = value.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        merged.append(value)
    return merged


def build_audit_log_query(
    *,
    category: str | None = None,
    categories: list[str] | None = None,
    issue_id: str | None = None,
    task_id: str | None = None,
    since: str | None = None,
    until: str | None = None,
    q: str | None = None,
    cursor_created_at: str | None = None,
    cursor_id: str | None = None,
    limit: int = 200,
    descending: bool = True,
) -> tuple[str, list[object]]:
    """Return `(sql, params)` for a filtered/paginated audit_log query.

    All values are bound parameters. `created_at` is stored as an ISO-8601
    string, so the `since`/`until` range and the cursor keyset both compare
    lexicographically (ISO-8601 sorts chronologically as text).
    """
    sql = "SELECT * FROM audit_log"
    clauses: list[str] = []
    params: list[object] = []

    cat_list = _normalize_categories(category, categories)
    if cat_list:
        placeholders = ", ".join("?" for _ in cat_list)
        clauses.append(f"category IN ({placeholders})")
        params.extend(cat_list)

    if issue_id is not None:
        clauses.append("issue_id = ?")
        params.append(issue_id)
    if task_id is not None:
        clauses.append("task_id = ?")
        params.append(task_id)

    # Inclusive lower / upper bound on the ISO-8601 created_at string.
    if since is not None:
        clauses.append("created_at >= ?")
        params.append(since)
    if until is not None:
        clauses.append("created_at <= ?")
        params.append(until)

    # Case-insensitive keyword search across the human-meaningful text columns.
    # Bound as a value (never interpolated); LOWER() on both sides makes the
    # match case-insensitive regardless of column collation.
    if q is not None and q.strip() != "":
        like = f"%{q.lower()}%"
        clauses.append(
            "("
            "LOWER(payload_json) LIKE ? OR "
            "LOWER(COALESCE(actor, '')) LIKE ? OR "
            "LOWER(COALESCE(category, '')) LIKE ? OR "
            "LOWER(COALESCE(error, '')) LIKE ?"
            ")"
        )
        params.extend([like, like, like, like])

    # Keyset cursor. Both halves of the composite key must be present to apply
    # it; a partial/garbage cursor is simply ignored (treated as page 1) so a
    # malformed cursor degrades gracefully instead of erroring.
    if cursor_created_at is not None and cursor_id is not None:
        if descending:
            clauses.append("(created_at, id) < (?, ?)")
        else:
            clauses.append("(created_at, id) > (?, ?)")
        params.extend([cursor_created_at, cursor_id])

    if clauses:
        sql += " WHERE " + " AND ".join(clauses)

    order = "DESC" if descending else "ASC"
    sql += f" ORDER BY created_at {order}, id {order}"

    if limit > 0:
        sql += " LIMIT ?"
        params.append(max(1, min(int(limit), _LIMIT_HARD_CAP)))

    return sql, params
