# Generation-to-Studio Integration

Date: 2026-07-14

## Completed

- Added a project-current structured draft recovery API. The response is the
  normal replay-verified draft response or `null`; browser storage is not a
  project ownership source.
- Added a project-current generation job API so refresh can recover planning,
  blueprint review, page generation, preview, failure, or accepted state.
- Added the production requirements generation UI: requirements input,
  blueprint review/confirm, durable item progress, task/process/hash evidence,
  candidate iframe, Accept, and automatic Studio adoption.
- Removed the production fixture fallback from Studio bootstrap.
- Replaced fixed procurement UUID usage in Studio, Canvas, runtime session
  creation, forms, tables, submit, and approve actions with document-derived
  semantic bindings.
- Added common visibility, grow, and cross-axis alignment editing for all six
  node types; Text/Input/Button retain their type-specific content controls.
- Kept browser storage only for idempotency/session recovery hints. The server
  current-draft endpoint remains authoritative.

## Cross-Layer Flow

```text
project route
  -> GET project current draft
  -> draft exists: replay + create/recover pinned runtime session -> Studio
  -> draft absent: GET current generation job -> requirements/blueprint/progress/preview
  -> Accept candidate atomically
  -> GET project current draft and verify returned draft ID
  -> create pinned runtime session -> Studio
```

## Real Browser Evidence

- Direct URL:
  `/projects/d26a7a4a-9c4b-4da2-a84f-c029416a3351/prototypes/studio`.
- The page restored document `47941524-bbc1-5856-a9e3-b77d6c9f496e`, three
  pages, applicant role, runtime controls, publication link, and durable AI
  history without manually writing draft/runtime/thread IDs.
- Project `09cca906-b5e1-4601-aa7a-14fb58f9f06b`, which has no structured
  document, opened the requirements generation UI. Filling the brief enabled
  the blueprint action; no generation was started during this read/UI check.
- Desktop document width equaled scroll width (`1600`); the narrow viewport
  check also had equal client and scroll widths. Browser error logs were empty
  for Studio and generation entry.

## Verification

- Backend structured-prototype suite: `98 passed`.
- Backend targeted Ruff: passed.
- Frontend full tests: `494 passed`.
- Frontend strict TypeScript: passed.
- Frontend ESLint: passed.
- Frontend Prettier check: passed.
- Browser: current-draft Studio recovery, empty-project generation entry,
  requirements interaction, desktop/narrow overflow, and console errors passed.
- `npm run build` was intentionally not run while the live Next dev server owned
  `frontend/.next`, per the repository quality guideline.
