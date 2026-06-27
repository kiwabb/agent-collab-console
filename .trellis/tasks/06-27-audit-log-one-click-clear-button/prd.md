# PRD: Audit Log One-Click Clear Button

## Goal
Add a one-click button on the Audit Log page that clears all audit log rows. Because deletion is destructive, it must be gated behind a confirmation dialog and give clear success/failure feedback.

## Background
The audit log already has a read path end-to-end:
- Store: `AsyncSQLiteStore.list_audit_logs` / `save_audit_log`
- Route: `GET /codex/audit-log` (`backend/app/interfaces/api.py`)
- Frontend: `getAuditLog` (`frontend/src/lib/api.ts`) + `AuditLogPage.tsx`

There is no delete path. Other entities already follow a delete pattern (e.g. `delete_codex_session`).

## Requirements

### Backend
1. Add `clear_audit_logs()` to `AsyncSQLiteStore` - runs `DELETE FROM audit_log`, commits, returns count of deleted rows.
2. Add matching method to the sync `sqlite_store.py` if it exposes the same audit-log surface (keep parity).
3. Add `DELETE /codex/audit-log` route that calls `clear_audit_logs()` and returns `{ "deleted": <count> }`. Guard with the same `codex_store is None` -> 503 check used by the GET route.
4. Add a backend test covering: clears rows, returns count, works on empty table.

### Frontend
1. Add `clearAuditLog()` to `frontend/src/lib/api.ts` - `DELETE ${API_BASE}/codex/audit-log`, returns `{ deleted: number }`.
2. In `AuditLogPage.tsx`, add a destructive "Clear" button next to the existing "Refresh" button in the `PageFrame` actions.
3. Use the existing `ConfirmDialog` (`variant="destructive"`, `isLoading`) to confirm before clearing.
4. Use `useToast` (`addToast`) for success/error feedback.
5. After a successful clear, reset list state (clear items, nextCursor, expanded) and reload.

### i18n
Add keys (zh + en): `auditLog.clear`, `auditLog.clearConfirmTitle`, `auditLog.clearConfirmDescription`, `auditLog.cleared`, `auditLog.clearFailed`.

## Out of scope
- Clearing only the currently-filtered subset (one-click = clear all).
- Retention/export before delete.
- Soft delete / tombstoning.

## Non-goals / risks
- This is a hard delete with no undo. The confirm dialog mitigates accidental loss; that is the accepted tradeoff for a one-click control.
