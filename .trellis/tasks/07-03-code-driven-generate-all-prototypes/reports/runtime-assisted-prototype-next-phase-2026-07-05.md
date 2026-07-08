# Runtime-Assisted Prototype Generation Next Phase - 2026-07-05

## Why This Exists

The current code-driven prototype generation flow is now validated as a usable beta:

- 19/19 current repo routes were generated through real LLM calls.
- 19/19 generated rows loaded in the browser preview iframe.
- Incomplete HTML is rejected before DB/disk writes.
- Candidate selection, shared guidance, and candidate-specific guidance are implemented.
- Frontend typecheck, frontend hygiene tests, and backend prototype/API tests pass.

That still does not make the feature Axhub-level. The current generator infers UI from source excerpts, import context, and i18n strings. It does not run the target app, inspect the live DOM, capture screenshots, or preserve a React prototype runtime.

This next phase defines the smallest runtime-assisted step that would materially improve fidelity without pretending to solve export/publish/collaboration.

## Product Goal

Add an optional runtime evidence layer to code-backed prototype generation:

1. Start from the existing code-discovered route candidates.
2. For candidates whose project is runnable, capture browser evidence for the live route.
3. Feed that evidence into the generation brief alongside source excerpts.
4. Keep the current single-file HTML artifact model and versioning.
5. Degrade safely to code-only generation when runtime capture is unavailable.

## Non-Goals

- Do not replace the current HTML prototype storage model with a React/Vite prototype runtime.
- Do not crawl authenticated flows without explicit user-provided state.
- Do not require runtime capture for every project; arbitrary repos may not install or run.
- Do not implement Axhub canvas, annotation, publish, export, or collaboration.
- Do not make pixel-perfect claims from DOM text alone.

## Proposed MVP Scope

### Runtime Capture Inputs

Per selected candidate, capture:

- Final URL attempted.
- HTTP/navigation success or failure.
- Page title.
- Viewport size.
- Visible body text summary, capped.
- Landmark/heading/button/link/form-control inventory, capped.
- First viewport screenshot path or image asset reference, if browser screenshot succeeds.
- Console errors and page errors, capped.
- Capture timestamp and capture mode.

### Route Resolution

Use `candidate.route` as the initial URL path.

Dynamic routes should use deterministic placeholder values:

- `:id` -> `demo-id`
- `:wsId` -> `demo-ws`
- catch-all -> `demo`

If a route redirects or renders a not-found/auth state, record that as runtime evidence rather than treating it as a hard generation failure.

### Prompt Integration

Generation brief priority should become:

1. Runtime screenshot/DOM evidence when available.
2. Source excerpt and i18n context.
3. Candidate metadata and route/source traceability.

The model should be told to reconcile conflicts this way:

- If runtime evidence shows visible copy/layout, prefer it over source inference.
- If runtime evidence is an auth/error/not-found state, include that state only if it appears representative.
- If runtime capture failed, explain nothing in the artifact; simply fall back to code-only generation.

### UI Flow

Add an optional checkbox or toggle in the scan dialog:

- Label: `Use running app evidence when available`
- Disabled/help text when the project has no run command or the app is not running.
- Progress states: `capturing`, `capture_failed`, `generating`, `done`.

Do not make runtime capture the default until the flow is reliable across local projects.

## Safety and Failure Policy

- Never start arbitrary install commands as part of capture.
- Reuse an already running project process when possible.
- If no running app is available, do not block generation.
- Keep per-candidate capture timeouts short.
- Do not persist screenshots outside `.agent-collab/prototypes/` or task reports.
- Do not include secrets from DOM, cookies, localStorage, or request headers in prompts.
- Do not send full page HTML to the LLM; send capped visible summaries and safe structural inventory.

## Acceptance Criteria

- [ ] User can opt into runtime evidence from the generate-from-code dialog.
- [ ] A route with a successful live render includes runtime evidence in its generation brief.
- [ ] A route with capture failure still generates through the existing code-only path.
- [ ] Dynamic routes resolve to deterministic demo paths and record the attempted URL.
- [ ] Runtime evidence includes capped visible text, structural inventory, console errors, and screenshot metadata when available.
- [ ] Runtime evidence never includes cookies, localStorage, raw headers, or uncapped full HTML.
- [ ] Browser E2E verifies at least three cases: successful static route, dynamic route with placeholder, and failed capture fallback.
- [ ] Generated prototypes from runtime-assisted mode still pass complete HTML validation.

## Suggested Implementation Slices

### Slice 1: Runtime Evidence Data Model

Add an internal `RuntimePrototypeEvidence` dataclass with:

- `attempted_url`
- `final_url`
- `success`
- `title`
- `viewport`
- `visible_text_excerpt`
- `structure_summary`
- `console_errors`
- `screenshot_path`
- `failure_reason`

No DB migration is required for slice 1 if evidence is only used during generation and recorded in `source_meta` for traceability.

### Slice 2: Browser Capture Service

Add a backend application service that can ask a local browser/capture adapter for a route snapshot.

The first implementation can be conservative:

- Target local project run URL only.
- Hard timeout per route.
- Return typed failure instead of raising for normal navigation failures.

### Slice 3: Prompt Builder Integration

Extend `build_code_backed_brief()` or add a sibling helper that accepts optional runtime evidence and places it above source excerpt.

### Slice 4: Frontend Toggle and Progress

Extend existing candidate selection dialog:

- Shared runtime evidence toggle.
- Per-candidate capture status.
- Summary counts for captured vs fallback.

## Quality Bar

This phase should not be considered done just because the capture code exists. It needs real evidence:

- One live project run with capture enabled.
- At least one generated artifact demonstrably influenced by runtime evidence.
- Browser preview loading for the runtime-assisted artifact.
- A report comparing code-only vs runtime-assisted output for a representative route.

## Relationship To Current Beta

The current beta remains valuable and should stay the default:

- It works without running arbitrary project code.
- It is deterministic enough for broad route coverage.
- It already supports selection and guidance.

Runtime-assisted mode should be an enhancement path, not a replacement.

## Implementation Progress - 2026-07-05

Slice 1 and the backend/API half of Slice 3 now have a minimal plumbing path:

- Added a request-scoped `RuntimePrototypeEvidence` model with a strict allowlist of safe fields.
- Code-backed generation briefs can place runtime evidence before source excerpts when evidence is supplied.
- Failed/unavailable runtime capture is represented as fallback context and should not be mentioned in generated artifacts.
- Runtime evidence makes an unchanged code-backed candidate eligible for regeneration instead of being skipped.
- SSE accepts repeated `runtime_evidence` query parameters encoded as `candidate_id<TAB>{json}`.
- Malformed runtime evidence query values are ignored instead of failing the whole stream.
- The frontend `getGenerateFromCodeStreamUrl()` builder can include runtime evidence alongside selected candidates and guidance.

Additional progress after the first plumbing slice:

- Added `RuntimePrototypeCaptureService` for opt-in capture from an already-running app base URL.
- Runtime route resolution now replaces dynamic route placeholders deterministically, for example `/issues/:id` -> `/issues/demo-id` and `/workspaces/:wsId` -> `/workspaces/demo-ws`.
- The capture service attempts browser evidence through Python Playwright when available.
- Captured evidence includes final URL, title, viewport, capped visible text, structural inventory, console warnings/errors, and first-viewport screenshot path.
- If Playwright is unavailable, the base URL is missing, or navigation fails, generation continues with failure evidence and falls back to source context.
- SSE now emits `candidate_capture`, `candidate_capture_done`, and `candidate_capture_failed` events before generation.
- The frontend scan dialog exposes an opt-in `Use running app evidence` control and runtime base URL input.
- The frontend progress dialog displays capture progress and capture-failed fallback status.

Still not complete:

- Browser capture depends on Python Playwright being installed and does not yet include an HTTP-only fallback for environments without it.
- The app does not yet infer runtime base URL from project run logs or persist `access_url` on `Project`.
- Browser E2E for successful static route, dynamic placeholder route, and failed capture fallback is still pending.
- There is not yet a code-only vs runtime-assisted visual comparison report from a real captured route.

## Real E2E Evidence - 2026-07-05

A representative live validation pass has now been recorded in:

- `reports/runtime-assisted-e2e-2026-07-05.md`
- `reports/runtime-e2e-assets/runtime-evidence.json`
- `reports/runtime-e2e-assets/runtime-assisted-generation.sse`
- `reports/runtime-e2e-assets/runtime-assisted-generation-compact-summary.json`
- `reports/runtime-e2e-assets/runtime-preview-verification.json`

Observed result:

- Browser captured runtime evidence for `/help` and `/issues/demo-id`.
- Real LLM SSE generation ran for `next-app-router--help`,
  `next-app-router--issues-id`, and `next-app-router--settings`.
- `next-app-router--issues-id` regenerated successfully to `v2` with complete
  HTML.
- `next-app-router--settings` regenerated successfully to `v2` with complete
  HTML.
- `next-app-router--help` failed because the LLM returned incomplete HTML; the
  backend correctly rejected the version and did not save it.
- Browser preview iframe loaded complete `srcdoc` for the two successful v2
  results.

Automatic capture reload probe:

- After restarting local dev services with `./dev-local.sh`, the live backend
  emitted `candidate_capture` and `candidate_capture_failed` for
  `next-app-router--settings`.
- The failure reason was `python playwright is not installed in the backend
  environment`.
- Generation fell back to source/runtime failure evidence and produced a
  complete `v4` HTML artifact.
- Browser preview loaded the `v4` iframe with complete `srcdoc`.

Remaining caveat:

- Full all-route runtime-assisted generation and preview verification is still
  pending. Current live proof covers representative browser-supplied evidence,
  automatic capture fallback, and one successful backend-owned Playwright
  capture.

Successful automatic Playwright capture proof:

- Python Playwright and Chromium were installed in the local backend
  environment.
- `next-app-router--settings` emitted `candidate_capture_done`.
- Backend wrote a `1440 x 900` PNG screenshot under
  `.agent-collab/prototypes/runtime-captures/`.
- The same run regenerated `/settings` to `v5`.
- Browser preview loaded the `v5` iframe with complete HTML.
