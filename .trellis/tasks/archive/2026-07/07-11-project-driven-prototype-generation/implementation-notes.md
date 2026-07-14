# Implementation Notes

The project-driven prototype flow is restore-first and review-first:

1. The repository is scanned deterministically into package, route, layout, navigation, style, and bounded evidence records.
2. The planner turns those records into a persisted, editable prototype plan. The first pass requires no user text; a shared instruction is optional.
3. Only explicitly selected `create` and `update` web candidates can enter a generation run. Browser-extension surfaces are diagnosed but remain unsupported.
4. Generation freezes source-backed seeds in SQLite, then runs outside the browser connection with a maximum concurrency of two. Run snapshots are reconnectable over SSE, and failed/interrupted items can be retried without repeating successful items.

The initial version is the restore baseline. Iteration through the existing prototype canvas creates later versions and never overwrites that baseline. A stale repository fingerprint rejects generation until the project is analyzed again. Manual prototypes and legacy code prototypes retain their existing provenance and lifecycle.

VideoNote validation uses the deterministic fixture in `backend/tests/test_project_evidence_service.py`: 19 logical `VideoMemo_frontend` page families and a separately diagnosed unsupported `VideoMemo_extension` surface.
