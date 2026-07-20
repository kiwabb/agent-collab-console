# Runtime-Assisted Prototype E2E Evidence - 2026-07-05

## Scope

This report records a real browser + real LLM validation pass for the current
project `agent-collab-console`.

Project:

- `project_id`: `d26a7a4a-9c4b-4da2-a84f-c029416a3351`
- frontend runtime: `http://localhost:4000`
- backend runtime: `http://localhost:9000`

Representative cases:

- Static successful route evidence: `/help`
- Dynamic route evidence: `/issues/demo-id`, mapped to candidate `/issues/:id`
- Fallback generation case: `/settings`

## Browser Runtime Evidence Capture

The in-app browser opened the live frontend and captured safe runtime evidence
for two pages:

- `/help`
  - final URL: `http://localhost:4000/help`
  - title: `Agent Collaboration Workbench`
  - console errors: `0`
  - screenshot: `runtime-e2e-assets/help-runtime.png`
- `/issues/demo-id`
  - final URL: `http://localhost:4000/issues/demo-id`
  - title: `Agent Collaboration Workbench`
  - console errors: `0`
  - screenshot: `runtime-e2e-assets/issue-demo-runtime.png`

Evidence artifact:

- `runtime-e2e-assets/runtime-evidence.json`

The captured payload contains capped visible text and structural summaries
only. It does not include cookies, localStorage, request headers, or full page
HTML.

## Real LLM SSE Generation

Command shape:

```text
GET /api/projects/d26a7a4a-9c4b-4da2-a84f-c029416a3351/prototypes/generate-from-code/stream
candidate_id=next-app-router--help
candidate_id=next-app-router--issues-id
candidate_id=next-app-router--settings
instruction=Use runtime browser evidence when present. Keep output compact and complete.
use_runtime_evidence=true
runtime_base_url=http://localhost:4000
runtime_evidence=next-app-router--help<TAB>{browser evidence json}
runtime_evidence=next-app-router--issues-id<TAB>{browser evidence json}
```

Raw SSE artifact:

- `runtime-e2e-assets/runtime-assisted-generation.sse`

Compact summary artifact:

- `runtime-e2e-assets/runtime-assisted-generation-compact-summary.json`

Result:

```json
{
  "created": 0,
  "regenerated": 2,
  "skipped": 0,
  "failed": 1,
  "unsupported": 0
}
```

Successful generated versions:

- `next-app-router--issues-id`
  - prototype: `af53dadd-4b42-4557-a069-a56a1bb9ddde`
  - version: `v2`
  - HTML complete: `true`
  - HTML chars: `14590`
  - disk path: `.agent-collab/prototypes/af53dadd-4b42-4557-a069-a56a1bb9ddde/v2/index.html`
- `next-app-router--settings`
  - prototype: `5ca1bf8f-f58e-41f4-ae9f-cd2af6e605c3`
  - version: `v2`
  - HTML complete: `true`
  - HTML chars: `20824`
  - disk path: `.agent-collab/prototypes/5ca1bf8f-f58e-41f4-ae9f-cd2af6e605c3/v2/index.html`

Rejected generated version:

- `next-app-router--help`
  - prototype: `bf44c81d-e01c-439e-a971-df310f79bc0c`
  - message: `LLM returned an incomplete HTML document; generation was not saved`

This confirms the incomplete HTML guard is active during real LLM generation.

## Browser Preview Verification

The frontend route
`/projects/d26a7a4a-9c4b-4da2-a84f-c029416a3351/prototypes` was opened in the
browser after generation.

Preview verification artifact:

- `runtime-e2e-assets/runtime-preview-verification.json`

Observed preview state:

- `next-app-router--settings v2`
  - preview iframe count: `1`
  - iframe title: `prototype-preview`
  - `srcdoc` starts with `<!DOCTYPE html>`
  - `srcdoc` ends with `</html>`
  - `srcdoc` length: `20838`
- `next-app-router--issues-id v2`
  - preview iframe count: `1`
  - iframe title: `prototype-preview`
  - `srcdoc` starts with `<!DOCTYPE html>`
  - `srcdoc` ends with `</html>`
  - `srcdoc` length: `14602`
  - iframe HTML includes issue/runtime evidence signal

## What This Proves

- Real browser runtime evidence can be collected from the running project.
- Real LLM generation accepts runtime evidence through the SSE flow.
- Dynamic route placeholder evidence for `/issues/:id` can generate a complete
  prototype.
- The frontend preview iframe loads complete generated HTML for successful
  runtime-assisted results.
- Incomplete real LLM output is rejected and not saved as a successful version.

## Representative-Pass Gaps Later Closed

- `/help` failed in the initial representative pass due to incomplete LLM HTML;
  this was safely handled by the incomplete-HTML guard. A later compacted retry
  generated the remaining current-project runtime-assisted candidates
  successfully.
- The initial representative pass covered three candidates. The later full
  current-project pass below covered all 19 discovered Next App Router
  candidates with runtime capture, LLM generation retries, and browser preview
  verification.

## Automatic Capture Reload Probe

After restarting the local dev services through `./dev-local.sh`, the live
backend loaded the automatic capture-service code and emitted the expected
capture events for a focused `/settings` run.

Artifact:

- `runtime-e2e-assets/automatic-capture-reload-probe.json`
- `runtime-e2e-assets/automatic-capture-reload-preview.json`

Observed event sequence:

```text
scan_meta
candidate_start
candidate_capture
candidate_capture_failed
prototype_done
all_done
```

Capture failure:

```text
candidate_id: next-app-router--settings
attempted_url: http://localhost:4000/settings
message: python playwright is not installed in the backend environment
```

Generation fallback result:

- `next-app-router--settings`
  - regenerated to `v4`
  - `all_done.failed = 0`
  - browser preview showed `v4`
  - preview iframe title: `prototype-preview`
  - iframe `srcdoc` starts with `<!DOCTYPE html>`
  - iframe `srcdoc` ends with `</html>`
  - iframe `srcdoc` length: `16622`

This closes the previous stale-process caveat. The remaining runtime gap is
environmental/backend-side browser availability, not SSE plumbing.

## Automatic Playwright Capture Success Probe

Python Playwright and Chromium were installed into the local backend
environment, then the live automatic capture flow was re-run for
`next-app-router--settings`.

Artifacts:

- `runtime-e2e-assets/automatic-capture-success-probe.json`
- `runtime-e2e-assets/automatic-capture-success-preview.json`
- `.agent-collab/prototypes/runtime-captures/settings-20260704T172215Z.png`

Observed event sequence:

```text
scan_meta
candidate_start
candidate_capture
candidate_capture_done
prototype_done
all_done
```

Capture result:

- attempted URL: `http://localhost:4000/settings`
- final URL: `http://localhost:4000/settings`
- screenshot path:
  `.agent-collab/prototypes/runtime-captures/settings-20260704T172215Z.png`
- screenshot file: PNG, `1440 x 900`, `304419` bytes

Generation result:

- `next-app-router--settings`
  - regenerated to `v5`
  - HTML complete: `true`
  - HTML chars: `17164`
  - `all_done.failed = 0`

Browser preview result:

- project prototype page showed `next-app-router--settings v5`
- preview iframe title: `prototype-preview`
- iframe `srcdoc` starts with `<!DOCTYPE html>`
- iframe `srcdoc` ends with `</html>`
- iframe `srcdoc` length: `17174`
- iframe content mentions Settings

This proves successful backend-owned runtime screenshot/DOM capture, real LLM
generation, and frontend preview loading for one representative route.

## Candidate Brief Editing Validation

Targeted contract validation was run on 2026-07-05 after adding candidate-level
editable brief overrides and bounded candidate-scoped text params.

Backend command:

```bash
cd backend && .venv/bin/python -m pytest tests/test_prototype_service.py tests/test_prototypes_api.py -v -m "slow or not slow"
```

Result:

- 59 passed in 11.14s.
- Covered user-edited candidate brief inclusion in `build_code_backed_brief`.
- Covered SSE `candidate_brief_override` parsing.
- Covered 1,200-character trimming and blank omission for candidate brief
  overrides and candidate instructions.
- Covered runtime evidence generation/capture tests in the same targeted suite.

Frontend command:

```bash
cd frontend && node --import tsx --test tests/prototypeApi.test.ts tests/prototypeCandidateBriefs.test.ts && npx tsc --noEmit
```

Result:

- 7 node tests passed.
- `npx tsc --noEmit` exited successfully.
- Covered URL construction with candidate brief overrides, selected-only helper
  behavior, blank override omission, and the current 1,200-character EventSource
  transport bound.

Browser artifact:

- `runtime-e2e-assets/browser-candidate-brief-edit-ui-2026-07-05-reverify.json`

Observed real UI state:

- Live scan returned `19 个候选 · 新建 0 · 变更 0 · 跳过 19`.
- User selected all candidates: `已选择 19/19 个可生成候选`.
- Editing one candidate brief rendered `brief 已修改`.
- The footer rendered accessible batch count `已修改 1 个 brief` with matching
  text, `title`, and `aria-label`.
- The edited brief textarea had `max_length=1200`.
- The live counter showed `生成 brief 161/1200 字符`.
- The generate button became enabled after selecting all candidates.

## Full Current-Project Runtime-Assisted Pass

After adding Python Playwright as a formal backend dependency in
`backend/pyproject.toml` and `backend/requirements.txt`, the full current
project candidate set was exercised through the live backend SSE endpoint with
automatic runtime capture enabled.

Command shape:

```text
GET /api/projects/d26a7a4a-9c4b-4da2-a84f-c029416a3351/prototypes/generate-from-code/stream
candidate_id=<one current candidate>
use_runtime_evidence=true
runtime_base_url=http://localhost:4000
```

Artifacts:

- `runtime-e2e-assets/full-runtime-assisted-generation-2026-07-05.jsonl`
- `runtime-e2e-assets/full-runtime-assisted-generation-summary-2026-07-05.json`
- `runtime-e2e-assets/full-runtime-assisted-preview-summary-2026-07-05.json`

Initial full pass result:

```json
{
  "candidate_count": 19,
  "capture_done": 19,
  "capture_failed": 0,
  "generation_done": 11,
  "generation_failed": 8,
  "latest_html_complete": 19
}
```

The 8 failed candidates were all rejected by the incomplete HTML guard with:

```text
LLM returned an incomplete HTML document; generation was not saved
```

This was a valid failure mode: the backend captured runtime evidence for every
candidate and preserved previously complete versions instead of saving partial
HTML.

## Prompt Compaction and Retry Results

To reduce max-output truncation, the code-backed prompt path was tightened:

- runtime visible text excerpts are capped more aggressively;
- runtime structural summaries are capped more aggressively;
- source excerpts are capped more aggressively;
- high-signal JSX/source lines are preserved before lower-value file headers;
- system and code-backed prompts explicitly prefer a compact first-screen
  artifact over exhaustive reproduction;
- complex pages include at most one secondary loading/empty/error state.

Validation:

```text
cd backend && .venv/bin/python -m pytest tests/test_prototype_service.py tests/test_prototypes_api.py -v -m "slow or not slow"
53 passed
```

First retry artifacts:

- `runtime-e2e-assets/runtime-assisted-retry-after-compact-2026-07-05.jsonl`
- `runtime-e2e-assets/runtime-assisted-retry-after-compact-summary-2026-07-05.json`
- `runtime-e2e-assets/runtime-assisted-retry-after-compact-preview-2026-07-05.json`

First retry result:

```json
{
  "retry_count": 8,
  "capture_done": 8,
  "generation_done": 5,
  "generation_failed": 3,
  "html_complete": 8
}
```

Second retry artifacts:

- `runtime-e2e-assets/runtime-assisted-second-retry-2026-07-05.jsonl`
- `runtime-e2e-assets/runtime-assisted-second-retry-summary-2026-07-05.json`
- `runtime-e2e-assets/runtime-assisted-second-retry-preview-2026-07-05.json`

Second retry result:

```json
{
  "retry_count": 3,
  "capture_done": 3,
  "generation_done": 3,
  "generation_failed": 0,
  "html_complete": 3
}
```

Combined result after retries:

- Runtime browser capture: 19/19 candidates.
- Runtime-assisted LLM generation saved complete new versions for 19/19
  candidates.
- Incomplete outputs were rejected during intermediate runs and never saved as
  successful versions.
- Existing complete previews remained available throughout failed attempts.

## Browser UI Preview Verification for All Candidates

The project prototype page was opened in the in-app browser:

```text
http://localhost:4000/projects/d26a7a4a-9c4b-4da2-a84f-c029416a3351/prototypes
```

Browser verification clicked all 19 code-backed prototype rows and inspected
the rendered preview iframe after each selection.

Artifact:

- `runtime-e2e-assets/browser-preview-all-runtime-assisted-2026-07-05.json`

Result:

```json
{
  "candidate_count": 19,
  "clicked": 19,
  "iframe_complete": 19,
  "failures": []
}
```

Each verified iframe had:

- title `prototype-preview`;
- `srcdoc` beginning with `<!DOCTYPE html>`;
- `srcdoc` ending with `</html>`.

## Current Completion Boundary

This closes the current-project runtime-assisted route-generation and browser
preview validation gap for the 19 discovered Next App Router candidates.

The selection/editing surface is no longer limited to a bare MVP subset picker:

- the scan dialog supports subset selection;
- the scan dialog supports one shared generation instruction;
- the scan dialog supports per-candidate guidance;
- the scan dialog now supports per-candidate editable brief overrides;
- edited candidate briefs show a modified chip before generation so users can
  see which candidates will send custom prompt text;
- modified chips include title/ARIA labels so the edit state is not visual-only;
- candidate brief and per-candidate guidance textareas include explicit
  aria-labels instead of relying on placeholder text alone;
- the scan footer now implements a batch-level edited-brief count when one or
  more selected candidates have custom brief text; this was added after the
  browser artifact below and should be covered by the next targeted frontend
  check/browser reverify;
- changed candidate brief overrides are sent through the SSE URL as
  `candidate_brief_override=<candidate_id><TAB><brief>`;
- per-candidate guidance is filtered to selected candidates before URL
  construction so stale instructions for unselected candidates do not bloat the
  SSE URL;
- the backend treats an override as the primary page intent while preserving
  runtime evidence and source excerpts as grounding/fallback context.
- candidate brief overrides and per-candidate guidance are bounded to 1,200
  characters in the frontend textareas, those textareas reuse the same
  frontend constant as URL construction, frontend URL construction trims
  candidate-scoped text query params to 1,200 characters and omits blank
  candidate text, and backend parsing applies the same bound, keeping the
  current EventSource transport from accepting unbounded edited prompt text or
  per-candidate guidance;
- backend regression coverage includes
  `test_generate_from_code_stream_trims_candidate_brief_override`,
  `test_generate_from_code_stream_ignores_blank_candidate_brief_override`, and
  `test_generate_from_code_stream_trims_candidate_instruction`, and
  `test_generate_from_code_stream_ignores_blank_candidate_instruction`.
- backend trimming tests reference the backend limit constant directly, and the
  frontend URL-builder test documents its exported current EventSource transport
  limit as 1,200.

Browser UI verification for the candidate brief-editing flow:

- opened the live project prototype route in the in-app browser;
- opened the code scan dialog;
- waited for 19 candidates to render;
- selected all 19 candidates so unchanged candidates became editable;
- expanded one candidate brief;
- edited the brief text;
- confirmed the rendered UI shows a `maxLength=1200` textarea;
- confirmed the live counter renders `95/1200`;
- confirmed `brief 已修改` appears both as the row chip and near the counter.

Artifact:

- `runtime-e2e-assets/browser-candidate-brief-edit-ui-2026-07-05.json`

Validation note for the brief-editing addition: contract tests were added for
the backend prompt path, backend SSE query parsing, and frontend URL builder,
plus pure frontend helpers for selected-only candidate instructions and
changed-only brief overrides, but the targeted commands still need to be run
after this edit:

```text
cd backend && .venv/bin/python -m pytest tests/test_prototype_service.py tests/test_prototypes_api.py -v -m "slow or not slow"
cd frontend && node --import tsx --test tests/prototypeApi.test.ts tests/prototypeCandidateBriefs.test.ts && npx tsc --noEmit
```

Still intentionally out of MVP scope:

- Vue/Svelte/Angular discovery;
- export/publish flows;
- full Axhub-style editable React prototype runtime;
- arbitrary authenticated/data-seeded runtime crawls beyond the current local
  project route set.
