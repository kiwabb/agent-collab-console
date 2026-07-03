# Code-Driven Generate All Prototypes

## Goal

Add a project-level flow that scans a project's codebase, discovers UI pages/components, and generates prototype entries for all discovered candidates. This fills the gap left by the existing "regenerate all existing prototypes" feature, which only reruns prototypes that already have manual briefs.

## What I Already Know

- User wants actual generation of all prototypes based on code and asked to reference Axhub Make.
- Current repo already implements project-level batch regeneration from existing seed briefs via `PrototypeService.regenerate_all_stream(project_id)` and `/api/projects/{id}/prototypes/regenerate-all/stream`.
- Current manual prototype model stores the original brief as synthetic `PrototypeVersion(version_no=0)` and generates single-file HTML through `stream_events(pid, instruction=None)`.
- Current `PrototypeService` references store methods such as `save_prototype`, `load_prototype`, `list_prototypes`, and `save_prototype_version`, but the checked-out `AsyncSQLiteStore` does not currently expose those prototype persistence methods. Implementation must repair this before adding code-driven generation.
- Axhub Make treats prototypes as discoverable project resources with stable IDs, source paths, artifact metadata, generation status, and preview URLs.
- Axhub Make's client template uses `src/prototypes/<slug>/index.tsx` as the prototype boundary and syncs metadata from filesystem structure.

## Assumptions

- MVP should generate single-file HTML prototypes using the existing LLM streaming path, not introduce a full React/Vite prototype runtime.
- MVP should be read-only against the target codebase except for writing generated prototype artifacts under `.agent-collab/prototypes/`.
- MVP should prioritize React/Next/Vite-style frontend projects because those are easiest to discover from page/component files.
- Design-review HTML prototypes in this task cover the new feature's user-facing pages/states. Runtime output of the implemented feature must still generate one HTML prototype per discovered source page candidate.

## Design Deliverables

- Detailed technical and product design: [`info.md`](info.md).
- Axhub Make reference research: [`research/axhub-make-code-prototype-design.md`](research/axhub-make-code-prototype-design.md).
- Static HTML prototypes for every user-facing page/state introduced by this feature:
  - [`prototypes/01-prototype-hub.html`](prototypes/01-prototype-hub.html) — project prototype hub with code coverage.
  - [`prototypes/02-scan-review.html`](prototypes/02-scan-review.html) — scan confirmation and candidate review.
  - [`prototypes/03-generation-progress.html`](prototypes/03-generation-progress.html) — SSE generation progress.
  - [`prototypes/04-generated-detail.html`](prototypes/04-generated-detail.html) — generated prototype detail with source traceability.
  - [`prototypes/05-empty-unsupported.html`](prototypes/05-empty-unsupported.html) — empty, unsupported, and diagnostic states.
- Prototype visuals must match the actual `/projects/:id/prototypes` route structure: `ProjectShell` header/tabs, `ProjectPrototypesPage` two-column workbench, compact `DialogContent` flows, and `PrototypeCanvas` preview/code/version controls. Do not wrap these route prototypes in the global `WorkbenchShell`, and do not use standalone dashboard/showcase/landing-page layouts.

## Requirements

- Add a code discovery layer that scans `Project.repo_path` for UI candidates while ignoring heavy or unsafe folders such as `.git`, `node_modules`, `dist`, `build`, `.next`, `.venv`, and `.agent-collab`.
- Restore or implement the prototype persistence methods already required by the existing prototype service before adding code-backed metadata or generation flows.
- Produce stable candidate records with `id`, `title`, `kind`, `route`, `source_paths`, `source_hash`, `framework_hint`, and short source/context snippets.
- Support at least these MVP discovery patterns:
  - Next App Router: `app/**/page.{tsx,jsx}`.
  - Next Pages Router: `pages/**/*.{tsx,jsx}` excluding API routes.
  - Vite/React fallback: `src/pages/**/*.{tsx,jsx}`, `src/routes/**/*.{tsx,jsx}`, and route-like components under `src/features/**`.
- Add source metadata to prototypes so code-generated prototypes can be matched on later runs:
  - `source_kind`: `manual` or `code`.
  - `source_ref`: stable candidate ID or primary source path.
  - `source_hash`: hash of the candidate source context.
  - `source_meta`: JSON payload for route, paths, framework hint, and last scan notes.
- Add a project-level "generate all from code" SSE flow:
  - Scan candidates.
  - Create missing code-backed prototypes.
  - Skip unchanged candidates by default.
  - Regenerate changed candidates as new versions.
  - Continue after per-candidate failures and summarize at the end.
- Reuse the existing prototype HTML generator where possible by building a source-backed seed brief and calling `stream_events(pid, instruction=None)`.
- Add frontend controls on the project prototype page:
  - A "Generate from code" button distinct from "Regenerate all".
  - A confirmation/preview dialog showing discovered candidates and counts.
  - A progress dialog with per-candidate states: pending, skipped, generating, done, failed.
- Match existing frontend styling and density: dark Console v2 surfaces, orange brand primary actions, compact Base UI buttons/dialogs/tabs, muted monospaced source paths, and existing progress/status semantics. Keep counts and source metadata as chips, rows, or small inline panels rather than marketing-style metric cards.
- Add zh-CN and en-US i18n keys for the new controls and status messages.
- For this repo as a scanner target, cover all current Next App Router page files listed in [`info.md`](info.md), including `/`, `/agents`, `/approvals`, `/artifacts`, `/audit`, `/benchmarks`, `/conductor`, `/help`, `/issues/:id`, `/issues/:id/workflow`, `/knowledge`, `/projects`, `/projects/:id`, `/projects/:id/conductor`, `/projects/:id/prototypes`, `/settings`, `/skills`, and `/workspaces/:wsId`.

## Acceptance Criteria

- [ ] A project with several route/page files can generate prototype entries without manually creating briefs first.
- [ ] The current repo's 18 discovered Next App Router pages are either generated as code-backed prototypes or explicitly reported as unsupported with a reason.
- [ ] Re-running the flow skips unchanged code-backed prototypes and reports skipped counts.
- [ ] Changing a candidate source file causes that candidate to generate a new prototype version on the next run.
- [ ] Existing manual prototypes are not overwritten or reclassified.
- [ ] Per-candidate failure does not stop the remaining candidates.
- [ ] Empty or unsupported codebases return a clear "no candidates found" state instead of an error.
- [ ] Backend tests cover scanner detection, idempotency, changed-source regeneration, empty project, and failure continuation.
- [ ] Frontend typecheck passes.
- [ ] Design review has static HTML coverage for all new user-facing feature pages/states listed in Design Deliverables.

## Technical Approach

### Backend

Prerequisite:

- Repair existing prototype persistence in `AsyncSQLiteStore` so the current manual prototype flow works before source metadata is added.

Add `backend/app/application/code_prototype_discovery.py`:

- `CodePrototypeCandidate` dataclass/Pydantic model.
- `CodePrototypeDiscoveryService.scan_project(project) -> list[CodePrototypeCandidate]`.
- Bounded file reads with max files/max bytes and ignored directories.
- Deterministic candidate hashing from normalized source snippets plus nearby style/dependency context.

Extend `Prototype` persistence:

- Add nullable source metadata columns to `prototypes`.
- Backfill existing rows as `source_kind="manual"`.
- Add typed store helpers to find code-backed prototypes by `project_id + source_ref`.

Extend `PrototypeService`:

- `generate_all_from_code_stream(project_id) -> AsyncIterator[StreamEvent]`.
- Event sequence: `scan_meta`, `candidate_start`, `candidate_skip`, `prototype_created`, `prototype_delta`, `prototype_done`, `prototype_error`, `all_done`.
- `all_done` summary includes `{created, regenerated, skipped, failed}`.

Add API:

- `GET /api/projects/{id}/prototypes/code-candidates` for preview.
- `GET /api/projects/{id}/prototypes/generate-from-code/stream` for one-shot EventSource generation.

### Frontend

Extend `frontend/src/features/prototype/ProjectPrototypesPage.tsx`:

- Keep current "Regenerate all" behavior intact.
- Add a code-generation button and dialogs.
- Use `EventSource` and close on terminal events, mirroring the existing batch regenerate pattern.
- Refresh prototype list and active detail after `all_done`.

Extend API/types/i18n:

- `listPrototypeCodeCandidates(projectId)`.
- `getGenerateFromCodeStreamUrl(projectId)`.
- `Prototype.source_kind/source_ref/source_hash/source_meta`.
- New translation keys under `prototype.generateFromCode.*`.

## Decision Options

### Approach A: Deterministic Scanner + Existing HTML Generator (Recommended)

- Scan source files, build source-backed briefs, create/update DB prototypes, and reuse the current single-file HTML generation stream.
- Pros: smallest change, no dev-server dependency, safer on arbitrary repos, leverages existing versioning/tests/UI.
- Cons: generated prototypes infer UI from source snippets, so fidelity may be lower than running the app and inspecting DOM/screenshots.

### Approach B: Runtime/Screenshot-Assisted Generation

- Start the project's dev server, crawl routes, capture screenshots/DOM, then generate prototypes from visual/runtime context.
- Pros: higher visual fidelity for runnable apps.
- Cons: much more fragile; requires install/run commands, ports, auth/data state, browser automation, and longer failures.

### Approach C: Axhub-Style Client Runtime

- Generate real React prototype directories and metadata similar to Axhub Make.
- Pros: better long-term editing/export story.
- Cons: large architecture change; duplicates or replaces the current HTML prototype model.

## Out Of Scope For MVP

- Pixel-perfect reconstruction from a live browser.
- Running arbitrary project code during scan.
- Full Vue/Svelte/Angular discovery.
- Selective candidate editing before generation.
- Axhub canvas, annotation, export, or publish pipeline.
- Replacing the existing manual prototype flow.

## Research References

- [`research/axhub-make-code-prototype-design.md`](research/axhub-make-code-prototype-design.md) — Axhub Make patterns and how they map to this repo.
- [`info.md`](info.md) — detailed design, current business-code findings, route inventory, backend/frontend architecture, edge cases, and rollout plan.

## Technical Notes

- Existing implementation files inspected: `backend/app/application/prototype_service.py`, `backend/app/interfaces/sse.py`, `backend/app/domain/models.py`, `frontend/src/features/prototype/ProjectPrototypesPage.tsx`, `frontend/src/lib/api/prototypes.ts`, `frontend/src/lib/types/prototypes.ts`.
- Existing active task `06-23-prototype-batch-regenerate` covers batch regeneration of existing prototypes, not code-driven prototype creation.
- The new flow should be a separate task to avoid changing the meaning of the completed regenerate-all behavior.
- `implement.jsonl` and `check.jsonl` should include `info.md` plus the Axhub research note so implementation and verification agents get the design context after this planning phase.
