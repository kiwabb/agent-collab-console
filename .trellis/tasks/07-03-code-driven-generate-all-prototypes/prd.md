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
- Include direct local import context for route/page candidates where possible, so a thin App Router wrapper such as `<HelpPage />` carries the imported feature component's source path and excerpt into the generation brief.
- Include directly referenced i18n copy for candidate source snippets, so `t("...")` calls carry representative zh-CN/en-US text into the generation brief instead of only opaque keys.
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
  - Candidate-level selection so the user can generate only a chosen subset.
  - An optional custom instruction field that is appended to selected candidates' generation briefs.
  - Optional candidate-level instructions so each selected page can carry its own generation guidance.
  - Candidate-level editable brief override so advanced users can rewrite the generated page intent before running generation.
  - A progress dialog with per-candidate states: pending, skipped, generating, done, failed.
- Match existing frontend styling and density: dark Console v2 surfaces, orange brand primary actions, compact Base UI buttons/dialogs/tabs, muted monospaced source paths, and existing progress/status semantics. Keep counts and source metadata as chips, rows, or small inline panels rather than marketing-style metric cards.
- Add zh-CN and en-US i18n keys for the new controls and status messages.
- For this repo as a scanner target, cover all current Next App Router page files listed in [`info.md`](info.md), including `/`, `/agents`, `/approvals`, `/artifacts`, `/audit`, `/benchmarks`, `/conductor`, `/help`, `/issues/:id`, `/issues/:id/workflow`, `/knowledge`, `/projects`, `/projects/:id`, `/projects/:id/conductor`, `/projects/:id/prototypes`, `/resume`, `/settings`, `/skills`, and `/workspaces/:wsId`.
- Do not save incomplete generated HTML as a successful version. If the model stops at `max_tokens` or the cleaned output does not start with `<!DOCTYPE html>` and end with `</html>`, emit an error and leave the prototype version unchanged.
- Code-backed generation prompts must prefer a compact complete prototype over exhaustive unfinished output, with explicit guidance to prioritize first viewport, primary workflow, navigation, and representative loading/empty/error states.

## Acceptance Criteria

- [x] A project with several route/page files can generate prototype entries without manually creating briefs first. Evidence: `cd backend && .venv/bin/python -m pytest tests/test_prototype_service.py tests/test_prototypes_api.py -v -m "slow or not slow"` passed on 2026-07-04.
- [x] The current repo's discovered Next App Router pages are either generated as code-backed prototypes or explicitly reported as unsupported with a reason. Evidence: live scan against project `d26a7a4a-9c4b-4da2-a84f-c029416a3351` on 2026-07-05 found 19 candidates with counts `create=0`, `regenerate=0`, `skip=19`, `unsupported=0`, proving every discovered candidate has a successful current code-backed version: `/`, `/agents`, `/approvals`, `/artifacts`, `/audit`, `/benchmarks`, `/conductor`, `/help`, `/issues/:id`, `/issues/:id/workflow`, `/knowledge`, `/projects`, `/projects/:id`, `/projects/:id/conductor`, `/projects/:id/prototypes`, `/resume`, `/settings`, `/skills`, `/workspaces/:wsId`.
- [x] Re-running the flow skips unchanged code-backed prototypes and reports skipped counts. Evidence: `test_code_generation_creates_then_skips_unchanged` and API stream test passed on 2026-07-04.
- [x] Changing a candidate source file causes that candidate to generate a new prototype version on the next run. Evidence: `test_code_generation_changed_source_appends_new_version` passed on 2026-07-04.
- [x] Existing manual prototypes are not overwritten or reclassified. Evidence: source-backed prototypes use `source_kind="code"` and `load_prototype_by_source(project_id, candidate.id)`, while manual creation writes `source_kind="manual"`; prototype backend suite passed on 2026-07-04. A dedicated regression test is still recommended before final release.
- [x] Per-candidate failure does not stop the remaining candidates. Evidence: `test_code_generation_failure_continues_with_remaining` passed on 2026-07-04.
- [x] Empty or unsupported codebases return a clear "no candidates found" state instead of an error. Evidence: frontend scan dialog renders `prototype.generateFromCode.noCandidates`; backend returns an empty scan summary for no discovered candidates; browser verification on 2026-07-05 with an empty git project showed `0 个候选 · 新建 0 · 变更 0 · 跳过 0` and `没有发现支持的页面候选。` with no console errors.
- [x] Backend tests cover scanner detection, idempotency, changed-source regeneration, empty project, failure continuation, selected-candidate generation, and custom generation guidance.
- [x] Frontend typecheck passes. Evidence: `cd frontend && npx tsc --noEmit` passed on 2026-07-05 after compatibility type cleanup.
- [x] Design review has static HTML coverage for all new user-facing feature pages/states listed in Design Deliverables. Evidence: the five static review artifacts exist and are non-empty under `prototypes/`: `01-prototype-hub.html` (12,052 bytes), `02-scan-review.html` (14,150 bytes), `03-generation-progress.html` (11,631 bytes), `04-generated-detail.html` (13,173 bytes), and `05-empty-unsupported.html` (9,494 bytes).
- [x] User can choose a subset of discovered candidates and add per-run generation guidance. Evidence: `test_code_generation_can_target_selected_candidates_with_guidance`, `test_generate_from_code_stream_accepts_selected_candidate_and_instruction`, and frontend scan-dialog controls added on 2026-07-04.
- [x] User can add candidate-specific generation guidance. Evidence: `test_code_generation_applies_candidate_specific_guidance`, `test_generate_from_code_stream_accepts_candidate_specific_instruction`, and frontend scan-dialog per-candidate textareas added on 2026-07-04.
- [x] User can edit a candidate-level generation brief before running code generation. Evidence: frontend scan dialog exposes per-candidate `Edit brief` / `Reset brief` controls, gives candidate brief and guidance textareas explicit aria labels, displays an accessible `brief edited` chip when a candidate brief differs from the generated default, implements an accessible batch-level edited-brief count, and only sends selected candidates' non-empty guidance plus changed `candidate_brief_override` values; backend SSE parses candidate brief overrides and passes them into `build_code_backed_brief` as a primary page-intent override while preserving runtime evidence and source fallback. Browser evidence proves the editable textarea, 1,200 character limit, live counter, per-candidate modified marker, and batch-level `已修改 1 个 brief` marker: `runtime-e2e-assets/browser-candidate-brief-edit-ui-2026-07-05.json` and `runtime-e2e-assets/browser-candidate-brief-edit-ui-2026-07-05-reverify.json`. Contract validation passed on 2026-07-05: `cd backend && .venv/bin/python -m pytest tests/test_prototype_service.py tests/test_prototypes_api.py -v -m "slow or not slow"` passed 59/59 tests, including `test_build_code_backed_brief_includes_user_edited_candidate_brief`, `test_generate_from_code_stream_accepts_candidate_brief_override`, trim/blank query-param tests, runtime evidence tests, and selected-candidate guidance coverage; `cd frontend && node --import tsx --test tests/prototypeApi.test.ts tests/prototypeCandidateBriefs.test.ts && npx tsc --noEmit` passed 7/7 node tests plus TypeScript typecheck.
- [x] Candidate-level brief editing is bounded for the current EventSource transport. Evidence: frontend candidate brief and candidate instruction textareas cap edits at the same 1,200-character constant used by frontend URL construction and show live `{current}/{max}` counters; frontend URL construction and backend parsing both trim candidate-scoped text query params to 1,200 characters and omit blank candidate text so malformed or oversized guidance/brief values cannot expand generation prompts or EventSource URLs without bound. Regression validation passed on 2026-07-05: backend tests `test_generate_from_code_stream_trims_candidate_brief_override`, `test_generate_from_code_stream_ignores_blank_candidate_brief_override`, `test_generate_from_code_stream_trims_candidate_instruction`, and `test_generate_from_code_stream_ignores_blank_candidate_instruction` passed as part of the 59-test targeted backend run; frontend `prototypeApi.test.ts` and `prototypeCandidateBriefs.test.ts` passed 7/7 and document the exported URL-builder limit as 1,200 for the current EventSource transport. Browser artifact `runtime-e2e-assets/browser-candidate-brief-edit-ui-2026-07-05-reverify.json` confirms the real scan dialog rendered the edited brief textarea with `max_length=1200` and `生成 brief 161/1200 字符`.
- [x] Candidate-level brief editing is visible in the real browser scan flow. Evidence: in-app browser verification on 2026-07-05 opened `/projects/d26a7a4a-9c4b-4da2-a84f-c029416a3351/prototypes`, opened the code scan dialog, selected all 19 candidates, expanded one candidate brief, edited it, and confirmed the rendered UI shows a `maxLength=1200` textarea, a live `95/1200` character counter, and `brief 已修改` markers. Artifact: `runtime-e2e-assets/browser-candidate-brief-edit-ui-2026-07-05.json`.
- [x] Incomplete LLM HTML is rejected instead of being saved as a successful version. Evidence: live `/help` generation revealed a truncated artifact ending at `</`; backend guard added and `test_incomplete_html_response_yields_error_and_no_db_write` passed on 2026-07-04.
- [x] Code-backed prompts include compact-complete output guidance to reduce `max_tokens` truncation risk. Evidence: `test_build_code_backed_brief_prioritizes_complete_compact_output` and `test_compact_code_source_excerpt_preserves_high_signal_ui_lines` passed on 2026-07-05; live `/agents` rerun changed from `max_tokens` failure to successful v1 after compact source excerpt generation.
- [x] Thin route wrappers include direct local component context. Evidence: `test_code_discovery_includes_direct_local_import_context` passed on 2026-07-04; `source_paths`, `source_excerpt`, and `source_hash` now include directly imported local components such as `@/features/help/HelpPage`.
- [x] Referenced i18n copy is included in code-backed briefs. Evidence: `test_code_discovery_includes_referenced_i18n_copy` passed on 2026-07-04; live `/help` scan now includes `frontend/src/lib/i18n/zh-CN.ts` and `frontend/src/lib/i18n/en-US.ts` in `source_paths`.
- [x] Representative runtime-assisted E2E evidence exists for the next-phase high-fidelity path. Evidence: `reports/runtime-assisted-e2e-2026-07-05.md` records browser-collected runtime evidence for `/help` and `/issues/demo-id`, a real LLM SSE generation run for `/help`, `/issues/:id`, and `/settings`, complete preview iframe verification for successful `/issues/:id` and `/settings` v2 outputs, and safe rejection of incomplete `/help` HTML. After restarting local services, `runtime-e2e-assets/automatic-capture-reload-probe.json` also proves the live backend emits `candidate_capture` and `candidate_capture_failed`; `runtime-e2e-assets/automatic-capture-reload-preview.json` proves the fallback `/settings` v4 preview iframe loads complete HTML. After installing Python Playwright and Chromium locally, `runtime-e2e-assets/automatic-capture-success-probe.json` proves `candidate_capture_done` for `/settings`; `runtime-e2e-assets/automatic-capture-success-preview.json` proves the resulting `/settings` v5 preview iframe loads complete HTML; `.agent-collab/prototypes/runtime-captures/settings-20260704T172215Z.png` proves backend-owned screenshot capture. This does not close the full all-route runtime-assisted goal; it proves the representative path and documents remaining gaps.
- [x] Full current-project runtime-assisted E2E is complete for all discovered routes. Evidence: on 2026-07-05 the live backend scanned 19 current Next App Router candidates and captured runtime browser evidence for 19/19 with `candidate_capture_done`. The first full LLM pass generated 11/19 and safely rejected 8 incomplete HTML responses without overwriting prior versions (`runtime-e2e-assets/full-runtime-assisted-generation-summary-2026-07-05.json`, `runtime-e2e-assets/full-runtime-assisted-generation-2026-07-05.jsonl`). Prompt/source/runtime compaction was tightened, then failed candidates were retried: 5/8 succeeded in `runtime-e2e-assets/runtime-assisted-retry-after-compact-summary-2026-07-05.json`, and the remaining 3/3 succeeded in `runtime-e2e-assets/runtime-assisted-second-retry-summary-2026-07-05.json`. Browser UI verification clicked all 19 prototype rows on `/projects/d26a7a4a-9c4b-4da2-a84f-c029416a3351/prototypes` and confirmed 19/19 preview iframes use title `prototype-preview`, start with `<!DOCTYPE html>`, and end with `</html>` (`runtime-e2e-assets/browser-preview-all-runtime-assisted-2026-07-05.json`).

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
- Rich candidate editing beyond subset selection, shared guidance, per-candidate guidance, and editable candidate brief overrides.
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
