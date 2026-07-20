# Prototype Generation Completion Report - 2026-07-04

## Summary

The code-driven prototype generation feature has moved from MVP toward a usable beta:

- Manual prototypes, versioning, iframe preview, and batch regeneration are implemented.
- Code-driven scanning and generation are implemented.
- Candidate-level subset generation is now implemented.
- A shared per-run custom instruction field is now implemented.
- Candidate-specific generation guidance is now implemented.
- A real LLM single-candidate run was performed and exposed an important quality bug: the model could return a truncated HTML document that the service previously saved as success.
- A second real LLM `/help` regeneration was performed after the completion guard and prompt/context improvements; it produced a complete v2 artifact that loads in the browser preview.
- The service now rejects `max_tokens` stops and cleaned HTML that does not look like a complete `<!DOCTYPE html> ... </html>` document.
- The scanner now includes direct local import context for route/page candidates, so thin App Router wrappers can carry feature component source into the generated brief.
- The scanner now includes directly referenced zh-CN/en-US i18n copy for candidates that call `t("...")`.
- Code-backed generation briefs now compact oversized source excerpts and tell the model to prefer compact complete prototypes over exhaustive unfinished output.
- Backend and API prototype tests pass.
- Frontend typecheck and split-API/source-hygiene tests pass.

This report intentionally does not claim Axhub-level product completion. Real LLM generation, functional browser preview loading, and frontend typecheck are now verified for all 19 current repo page candidates, but high-fidelity runtime/screenshot-assisted visual reconstruction remains outside the current code-driven beta architecture.

## What Changed In This Pass

- `GET /api/projects/{project_id}/prototypes/generate-from-code/stream` now accepts repeated `candidate_id` query parameters.
- The same stream accepts an optional `instruction` query parameter.
- The same stream accepts repeated `candidate_instruction` query parameters encoded as `candidate_id<TAB>instruction`.
- `PrototypeService.generate_all_from_code_stream()` can filter the latest scan to selected candidate IDs.
- Custom instructions are appended to selected candidates' code-backed generation brief.
- Candidate-specific instructions are appended only to the matching selected candidate's code-backed generation brief.
- If a selected unchanged code-backed prototype receives custom guidance, it is regenerated instead of skipped.
- `_stream_html()` now treats `stop_reason=max_tokens` as an error.
- `stream_events()` now rejects incomplete HTML before DB or disk writes.
- `CodePrototypeDiscoveryService` now resolves direct relative and `@/` local imports for each discovered candidate.
- Related local source files are appended to `source_paths`, included in `source_excerpt`, and included in `source_hash`.
- Directly referenced i18n keys are extracted from source units and matched against `frontend/src/lib/i18n/zh-CN.ts` and `frontend/src/lib/i18n/en-US.ts`.
- Matched i18n snippets are appended to `source_paths`, included in `source_excerpt`, and included in `source_hash`.
- `build_code_backed_brief()` now explicitly prioritizes first viewport, primary workflow, navigation structure, and representative loading/empty/error states, while telling the model to summarize repetitive lower-priority sections.
- `compact_code_source_excerpt()` now shrinks oversized source excerpts for generation while preserving high-signal UI lines such as JSX, `t(...)` labels, loading/empty/error branches, and key component names.
- Code-backed prompts now target concise 80-140 line first-screen slices for complex admin/workbench pages so the model can finish within the response budget.
- The frontend scan dialog now has candidate checkboxes.
- The frontend scan dialog defaults to selected `create` and `regenerate` candidates.
- The frontend scan dialog includes select-all, clear, selected-count, and custom guidance controls.

## Validation Run

Passed:

```bash
cd backend && .venv/bin/python -m pytest tests/test_prototype_service.py tests/test_prototypes_api.py -v -m "slow or not slow"
```

Result:

```text
44 passed in 8.77s
```

Passed:

```bash
cd frontend && node --import tsx --test tests/theme-i18n.test.ts tests/apiCompatibility.test.ts tests/apiCompatibilityExports.test.ts tests/sourceHygiene.test.ts
```

Result:

```text
16 passed
```

Passed after compatibility type cleanup:

```bash
cd frontend && npx tsc --noEmit
```

Result:

```text
passed
```

## Acceptance Matrix

| Requirement | Status | Evidence |
| --- | --- | --- |
| Manual prototype generation | Done | Backend prototype service/API tests passed |
| Batch regenerate existing prototypes | Done | `regenerate_all` service/API tests passed |
| Code scan discovers supported React/Next pages | Done | `test_code_discovery_detects_supported_pages_and_ignores_heavy_dirs` passed |
| Code generation creates prototypes without manual briefs | Done | Code generation service/API tests passed |
| Re-run skips unchanged generated prototypes | Done | `test_code_generation_creates_then_skips_unchanged` passed |
| Changed source creates a new generated version | Done | `test_code_generation_changed_source_appends_new_version` passed |
| Per-candidate failure continues the batch | Done | `test_code_generation_failure_continues_with_remaining` passed |
| Candidate subset generation | Done | New service/API selected-candidate tests passed |
| Per-run generation guidance | Done | New service/API guidance tests passed |
| Candidate-specific generation guidance | Done | `test_code_generation_applies_candidate_specific_guidance` and API stream test passed |
| Incomplete generated HTML rejected | Done | `test_incomplete_html_response_yields_error_and_no_db_write` passed |
| Compact-complete prompt guidance | Done | `test_build_code_backed_brief_prioritizes_complete_compact_output` and `test_compact_code_source_excerpt_preserves_high_signal_ui_lines` passed |
| Direct local import context | Done | `test_code_discovery_includes_direct_local_import_context` passed |
| Referenced i18n copy context | Done | `test_code_discovery_includes_referenced_i18n_copy` passed |
| Frontend candidate selection UI | Done | Browser check confirmed candidate checkboxes, selected count, select-all/clear, and custom guidance textarea |
| Full frontend typecheck | Done | `cd frontend && npx tsc --noEmit` passed on 2026-07-05 after compatibility type cleanup |
| Static design-review HTML coverage | Done | Five non-empty static artifacts exist under `prototypes/`: hub, scan review, generation progress, generated detail, and empty/unsupported states |
| Current repo candidate scan | Done | Live API scan found 19 supported Next App Router candidates; latest counts are 0 create, 0 regenerate, 19 skip, 0 unsupported |
| Real LLM generation | Done for current repo coverage | Live SSE generated or regenerated all 19 discovered candidates into complete code-backed versions. A first all-candidate pass produced 12 done, 2 skip, 5 failed; prompt compaction and candidate-specific ultra-compact retries recovered the 5 failures. Final scan reports all 19 as skip |
| Browser preview verification of generated outputs | Done for functional preview loading | Browser clicked all 19 generated rows; every preview iframe loaded a complete `<!DOCTYPE html> ... </html>` `srcdoc`, and the browser console error log was empty |
| Visual quality / fidelity review | Partially done | Functional preview loading is verified for all 19 pages, but human/visual quality review remains code-driven beta rather than runtime screenshot-assisted high-fidelity QA |
| Runtime/screenshot-assisted high-fidelity generation | Not done | Explicitly outside current MVP/beta architecture |
| Vue/Svelte/Angular discovery | Not done | Still outside scope |
| Export/publish/canvas collaboration | Not done | Still outside scope |

## Remaining Work To Call This Fully Complete

1. Add a dedicated regression that manual prototypes are never reclassified by code-backed generation.
2. If the product target moves beyond code-driven beta, implement the runtime DOM/screenshot-assisted phase defined in [`runtime-assisted-prototype-next-phase-2026-07-05.md`](runtime-assisted-prototype-next-phase-2026-07-05.md).
3. Optionally capture screenshots for a curated representative subset to support human design review.

## Product Quality Assessment

Current state: usable beta.

The feature is stronger than the original MVP because users can now control generation scope and steer the generated output. It is still not Axhub-level because it does not run the target app, inspect DOM, use screenshots, maintain a React prototype runtime, or support publishing/collaboration/export flows.

## Live E2E Notes

Live scan:

```text
Project: d26a7a4a-9c4b-4da2-a84f-c029416a3351
Candidate count: 19
Counts: create 19, regenerate 0, skip 0, unsupported 0
```

After generating `/help` once:

```text
Candidate count: 19
Counts: create 18, regenerate 0, skip 1, unsupported 0
Generated prototype: bf44c81d-e01c-439e-a971-df310f79bc0c
Version: v1
Disk path: .agent-collab/prototypes/bf44c81d-e01c-439e-a971-df310f79bc0c/v1/index.html
```

Important finding:

- The live `/help` model output stopped mid-document and produced an artifact ending at `</`.
- Before this pass, the backend saved that artifact as `done`.
- The new completion guard prevents future truncated artifacts from being saved as successful versions.
- The code-backed prompt now also reduces the chance of hitting that failure mode by instructing the model to produce compact complete artifacts rather than exhaustive but unfinished ones.
- The live `/help` scan also showed a fidelity gap: the original route excerpt only contained the App Router wrapper that rendered `<HelpPage />`. The scanner now includes direct local import context so future briefs can see the imported feature component source instead of only the wrapper.
- Follow-up live scan evidence: `/help` now includes `frontend/src/app/help/page.tsx`, `frontend/src/features/workbench/WorkbenchShell.tsx`, `frontend/src/features/help/HelpPage.tsx`, `frontend/src/providers/I18nProvider.tsx`, `frontend/src/lib/i18n/zh-CN.ts`, and `frontend/src/lib/i18n/en-US.ts`; excerpt length was 10,395 characters.

After regenerating `/help` with the improved guard, prompt, import context, and i18n context:

```text
Generated prototype: bf44c81d-e01c-439e-a971-df310f79bc0c
Version: v2
Disk path: .agent-collab/prototypes/bf44c81d-e01c-439e-a971-df310f79bc0c/v2/index.html
Bytes: 20,890
Starts with <!DOCTYPE html>: true
Ends with </html>: true
Representative content probes: Help=true, shortcut=true, Quick=true, page map=true
```

Browser evidence:

- `/projects/d26a7a4a-9c4b-4da2-a84f-c029416a3351/prototypes` rendered.
- The generated code-backed prototype row appeared with `next-app-router--help` and `v2`.
- The version selector showed `v2` as the active version and listed `v1` and `v2`.
- The preview iframe existed with a non-empty `srcdoc` payload of 20,867 characters in the browser.
- The preview iframe `srcdoc` started with `<!DOCTYPE html>`, ended with `</html>`, and contained representative Help, shortcut, and page-map content.
- The scan dialog showed 19 candidates: 18 selected by default and `/help` skipped.
- The scan dialog showed candidate checkboxes, selected count, select all, clear, and custom guidance textarea.
- Browser console error log was empty during these checks.

## Full Current-Repo E2E Evidence

After compacting the code-backed brief, a live all-candidate SSE run against the current repo produced:

```text
scan_meta: count=19, created_count=15, changed_count=2, unchanged_count=2, unsupported_count=0
first full pass: created=11, regenerated=1, skipped=2, failed=5, unsupported=0
failed candidates: /artifacts, /benchmarks, /conductor, /issues/:id, /projects
```

The failures were useful real feedback:

- `/agents` had previously failed with `max_tokens`; after source-excerpt compaction, a selected rerun succeeded as v1.
- A selected retry with tighter default prompt recovered `/benchmarks`, `/conductor`, and `/issues/:id`.
- Candidate-specific ultra-compact guidance recovered `/artifacts` and `/projects`.

Final successful state:

```text
scan_count: 19
scan_counts: create=0, regenerate=0, skip=19, unsupported=0
code_prototypes: 19
complete_count: 19
```

All 19 code-backed prototypes have `current_version > 0`, at least one visible user version, and current-version HTML that starts with `<!DOCTYPE html>` and ends with `</html>`.

Browser all-preview evidence:

```text
Clicked generated rows: 19
Preview iframes with complete HTML srcdoc: 19
Browser console errors: 0
```

Empty-project browser evidence:

```text
Temporary empty git project opened at /projects/:id/prototypes
Generate-from-code scan dialog opened
Displayed: 0 个候选 · 新建 0 · 变更 0 · 跳过 0
Displayed: 没有发现支持的页面候选。
Browser console errors: 0
Temporary project and repo were removed after verification
```

The 19 verified preview source comments were:

- `<!-- source: /agents frontend/src/app/agents/page.tsx -->`
- `<!-- source: /approvals frontend/src/app/approvals/page.tsx -->`
- `<!-- source: /artifacts frontend/src/app/artifacts/page.tsx -->`
- `<!-- source: /audit frontend/src/app/audit/page.tsx -->`
- `<!-- source: /benchmarks frontend/src/app/benchmarks/page.tsx -->`
- `<!-- source: /conductor frontend/src/app/conductor/page.tsx -->`
- `<!-- source: /help frontend/src/app/help/page.tsx -->`
- `<!-- source: / frontend/src/app/page.tsx -->`
- `<!-- source: /issues/:id frontend/src/app/issues/[id]/page.tsx -->`
- `<!-- source: /issues/:id/workflow frontend/src/app/issues/[id]/workflow/page.tsx -->`
- `<!-- source: /knowledge frontend/src/app/knowledge/page.tsx -->`
- `<!-- source: /projects frontend/src/app/projects/page.tsx -->`
- `<!-- source: /projects/:id frontend/src/app/projects/[id]/page.tsx -->`
- `<!-- source: /projects/:id/conductor frontend/src/app/projects/[id]/conductor/page.tsx -->`
- `<!-- source: /projects/:id/prototypes frontend/src/app/projects/[id]/prototypes/page.tsx -->`
- `<!-- source: /resume frontend/src/app/resume/page.tsx -->`
- `<!-- source: /settings frontend/src/app/settings/page.tsx -->`
- `<!-- source: /skills frontend/src/app/skills/page.tsx -->`
- `<!-- source: /workspaces/:wsId frontend/src/app/workspaces/[wsId]/page.tsx -->`
