# Code-Driven Generate All Prototypes - Detailed Design

## Executive Summary

The current product already has a manual prototype workflow and a "regenerate all existing prototypes" stream. It does **not** yet have a code-driven workflow that scans a project's source tree and creates one HTML prototype for every discovered page. The proposed design adds a source-discovery layer, source-backed prototype metadata, and a new project-level generation stream while preserving the existing single-file HTML preview model.

The design intentionally borrows Axhub Make's resource model: source files become prototype resources with stable IDs, source paths, status, artifacts, and preview links. It does not copy Axhub's full client runtime, canvas, publishing, or React prototype directory architecture in the MVP.

## Current Business Code Findings

### Project Boundary

- `Project` already stores the local repository path in `repo_path` and optional `run_command` in `backend/app/domain/models.py`.
- `ProjectService.create_from_local` validates that the path exists, is a directory, and is a git repository before saving it.
- Project CRUD endpoints live in `backend/app/interfaces/api.py` under `/api/projects`.
- The prototype feature should scan `Project.repo_path`, not workspace worktrees, unless a future flow explicitly asks to generate prototypes for an issue worktree.

### Existing Prototype Backend

- `PrototypeService.create(project_id, title, brief)` creates a prototype row and stores the original brief as synthetic version `0`.
- `PrototypeService.stream_events(prototype_id, instruction=None)` generates from version `0` brief and writes a new version only after the LLM stream completes.
- `PrototypeService.stream_events(prototype_id, instruction=<text>)` iterates from the current version.
- `PrototypeService.regenerate_all_stream(project_id)` only loops existing prototypes and calls `stream_events(..., instruction=None)`.
- Generated HTML is mirrored to `<repo_path>/.agent-collab/prototypes/<prototype_id>/v<n>/index.html`.

### Important Store Gap

The current checked-out backend references `AsyncSQLiteStore.save_prototype`, `load_prototype`, `list_prototypes`, `save_prototype_version`, and related methods, but `AsyncSQLiteStore` currently does not expose those methods:

```text
has save_prototype False
prototype attrs []
```

That means implementation must first restore or add the prototype persistence layer before adding source-backed generation. Treating the existing prototype service as fully runnable would be unsafe.

### Existing Prototype Frontend

- `/projects/:id/prototypes` is already mounted by `ProjectPrototypesRoutePage` inside `ProjectShell`.
- `ProjectShell` has three project tabs: Workspaces, Conductor, Prototypes.
- `ProjectPrototypesPage` owns the prototype list, manual create form, existing batch regenerate button, batch progress dialog, and active prototype detail.
- `PrototypeCanvas` owns single-prototype SSE generation/iteration, preview/code tabs, version picker, and sandboxed iframe rendering.
- `PreviewFrame` uses `sandbox="allow-scripts"` and intentionally omits `allow-same-origin`, which should remain true for generated code-backed HTML.

### Frontend Style Alignment Findings

The static HTML prototypes must follow the real frontend's Console v2 dark operational style, not a standalone warm/light design language.

Code evidence:
- `frontend/src/app/globals.css` defines the default dark token system: `#0b0b0c` page background, `#0f1115` surface, `#161a21` raised cards, `#1b2230` inputs, `#e69552` brand primary, muted blue-gray text, and thin `#232a38` borders.
- `WorkbenchShell` wraps global application routes in a full-height dark app shell with `AppHeader`, `AppSidebar`, an `enterprise-panel` main container rounded to about 30px, and a bottom `AppStatusBar`. The `/projects/:id/prototypes` route itself is not rendered as a standalone global shell prototype; it is shown inside `ProjectShell`.
- `AppHeader` uses a compact 56px dark top bar, orange `C` brand mark, slash breadcrumbs, and a `bg-surface-input` search control.
- `AppSidebar` uses dark `enterprise-panel` navigation, rounded project switcher, orange active state, and muted section labels.
- `ProjectShell` adds the project-level header with orange/blue radial background and rounded pill tabs for Workspaces, Conductor, and Prototypes.
- `ProjectPrototypesPage` uses a two-column workbench: 280px prototype sidebar plus a raised main canvas, with `Button`, `Dialog`, `EmptyState`, `Loader`, and `ConfirmDialog` components.
- `PrototypeCanvas` uses compact preview/code tabs, dark iframe/code containers, version pills, and a bottom instruction panel.
- `DialogContent`, `DialogFooter`, `ProgressBar`, and `StatusBadge` define the expected progress dialog, footer, progress bar, dot/status, and running/error/done language.

Prototype style rules:
- Use the dark token set above as the default; do not use light beige/cream panels or standalone marketing-style colors.
- Prefer compact component density: 32px buttons, 8px button radius, 10-12px cards/panels, small uppercase section labels, and muted monospaced paths/hashes.
- Show progress and scanning inside dialogs or workbench panels, matching the current batch-regenerate UI, instead of using unrelated full-page wizard styling.
- Keep page prototypes self-contained HTML, but visually imitate the existing `ProjectShell`/`ProjectPrototypesPage`/`PrototypeCanvas` hierarchy for this route. Do not introduce a global sidebar/header/status bar around `/projects/:id/prototypes` states.
- Keep scan/progress states as compact dialogs over the project prototype page. Do not turn them into full-screen dashboards, analytics boards, or multi-column showcase layouts.
- Keep empty and unsupported states inside the same two-column prototype workbench using `EmptyState`-like centered content plus small diagnostics, not a hero/landing-page treatment.

### Current App Route Inventory

This repo is itself a good scanner target. It currently has these Next App Router page files:

| Route Pattern | Source File |
| --- | --- |
| `/` | `frontend/src/app/page.tsx` |
| `/agents` | `frontend/src/app/agents/page.tsx` |
| `/approvals` | `frontend/src/app/approvals/page.tsx` |
| `/artifacts` | `frontend/src/app/artifacts/page.tsx` |
| `/audit` | `frontend/src/app/audit/page.tsx` |
| `/benchmarks` | `frontend/src/app/benchmarks/page.tsx` |
| `/conductor` | `frontend/src/app/conductor/page.tsx` |
| `/help` | `frontend/src/app/help/page.tsx` |
| `/issues/:id` | `frontend/src/app/issues/[id]/page.tsx` |
| `/issues/:id/workflow` | `frontend/src/app/issues/[id]/workflow/page.tsx` |
| `/knowledge` | `frontend/src/app/knowledge/page.tsx` |
| `/projects` | `frontend/src/app/projects/page.tsx` |
| `/projects/:id` | `frontend/src/app/projects/[id]/page.tsx` |
| `/projects/:id/conductor` | `frontend/src/app/projects/[id]/conductor/page.tsx` |
| `/projects/:id/prototypes` | `frontend/src/app/projects/[id]/prototypes/page.tsx` |
| `/settings` | `frontend/src/app/settings/page.tsx` |
| `/skills` | `frontend/src/app/skills/page.tsx` |
| `/workspaces/:wsId` | `frontend/src/app/workspaces/[wsId]/page.tsx` |

The code-driven generation feature must be able to create one HTML prototype for each discovered page candidate like these, unless the candidate is explicitly ignored with a reason.

## Axhub Make Reference Findings

### Useful Axhub Patterns

- `client/scripts/sync-project-metadata.mjs` declares resource roots such as `src/prototypes`, scans prototype directories, reads display names, extracts nested page metadata, and writes project metadata.
- Axhub prototype resources include stable `id`, `title`, `clientUrl`, `previewMode`, `filePath`, optional `pages`, optional `artifacts`, and generation status.
- `managementApi.aiRuns.ts` normalizes AI output into typed artifacts and streams events such as run stages, text deltas, and artifact creation/update.
- `managementApi.prototypeUpload.ts` updates prototype metadata when importing or generating and uses `generationStatus` to expose progress.
- `client/rules/prototype-development-guide.md` enforces a clear prototype boundary and expects each prototype to pass preview validation.
- V0 and AI Studio converter rules show that generated projects should be preprocessed into local prototype entries instead of being treated as opaque output.

### What To Copy Conceptually

- Resource identity: every page/prototype needs a stable source-derived ID.
- Metadata first: UI should display what will be generated before generation starts.
- Status clarity: waiting/running/done/failed/skipped states must be explicit per item.
- Artifact traceability: generated output must link back to source paths, source hash, and version.
- Safe conversion: never run or mutate arbitrary source code during basic scan.

### What Not To Copy In MVP

- Axhub's React runtime and `src/prototypes/<slug>/index.tsx` output structure.
- Canvas, annotation, upload, import, export, cloud publishing, and ACP runtime.
- Browser/screenshot crawling as the primary path.

## Product Requirements

1. The project prototype page must offer a separate "Generate from code" action distinct from "Regenerate all".
2. The scan step must discover every supported page candidate and show the full candidate list before generation.
3. Each candidate should map to one source-backed prototype and one generated HTML version, unless skipped because the source hash is unchanged.
4. Changed code-backed prototypes should create a new version on rerun.
5. Manual prototypes must remain separate from code-backed prototypes.
6. Single-candidate failure must not stop the rest of the batch.
7. Empty or unsupported repositories must show a recovery-oriented state.
8. The UI must surface code coverage: discovered count, generated count, skipped count, changed count, failed count, unsupported count.

## Proposed Information Architecture

### Page 1: Prototype Hub With Code Coverage

Prototype path: [`prototypes/01-prototype-hub.html`](prototypes/01-prototype-hub.html)

Purpose:
- The normal `/projects/:id/prototypes` page after this feature lands.
- Shows manual and code-backed prototypes in the existing sidebar.
- Adds a "Generate from code" CTA and a coverage strip.
- Makes it obvious whether every page has a generated HTML prototype.

Key UI:
- Project header with repository path.
- Toolbar: "Generate from code", "Regenerate all", "New prototype".
- Source coverage summary.
- Prototype list with badges: Manual, Code, Changed, Missing HTML.
- Active detail preview.

### Page 2: Scan Review

Prototype path: [`prototypes/02-scan-review.html`](prototypes/02-scan-review.html)

Purpose:
- The confirmation/review step before LLM spend starts.
- Shows all discovered page candidates and action classification.
- Lets the user understand that every page is accounted for.

Key UI:
- Candidate table with route, title, primary source path, framework hint, source hash, and action.
- Filters for all/new/changed/skipped/unsupported.
- Scanner rules summary.
- Start button with exact generation counts.

### Page 3: Generation Progress

Prototype path: [`prototypes/03-generation-progress.html`](prototypes/03-generation-progress.html)

Purpose:
- One-shot SSE progress dialog for code-driven generation.
- Mirrors the existing batch-regenerate `DialogContent` flow but uses candidate terminology and skip states.

Key UI:
- Overall progress bar.
- Queue with candidate states.
- Live event timeline.
- Dimmed project-prototype workbench behind the dialog.
- Summary counters.

### Page 4: Generated Prototype Detail

Prototype path: [`prototypes/04-generated-detail.html`](prototypes/04-generated-detail.html)

Purpose:
- Active prototype detail after selecting a code-backed generated prototype.
- Shows source traceability beside normal preview/code/version controls.

Key UI:
- Preview/code tabs.
- Version selector.
- Source metadata panel: route, source paths, hash, scanner, generated version.
- Source drift indicator and "Regenerate changed source" action.

### Page 5: Empty Or Unsupported State

Prototype path: [`prototypes/05-empty-unsupported.html`](prototypes/05-empty-unsupported.html)

Purpose:
- Handles no candidates, unsupported framework, missing prototype persistence, or scanner limits.

Key UI:
- Clear reason cards.
- Recovery actions: configure include paths, create manual prototype, run diagnostics.
- List of ignored directories and supported patterns.

## Backend Design

### New Module

Create `backend/app/application/code_prototype_discovery.py`.

Types:

```python
class CodePrototypeCandidate(BaseModel):
    id: str
    title: str
    route: str
    kind: Literal["page", "route", "feature"]
    framework_hint: str
    source_paths: list[str]
    primary_source_path: str
    source_hash: str
    source_excerpt: str
    signals: list[str]
    unsupported_reason: str | None = None
```

Scanner responsibilities:
- Resolve project root from `Project.repo_path`.
- Refuse non-existing or non-directory roots.
- Ignore heavy or unsafe directories: `.git`, `node_modules`, `dist`, `build`, `.next`, `.turbo`, `.venv`, `__pycache__`, `.agent-collab`, `coverage`, `tmp`.
- Enforce max scanned files, max bytes per file, and max total prompt context bytes.
- Discover Next App Router pages:
  - `app/**/page.{tsx,jsx}`
  - `src/app/**/page.{tsx,jsx}`
  - `frontend/src/app/**/page.{tsx,jsx}`
- Discover Next Pages Router pages:
  - `pages/**/*.{tsx,jsx}`
  - `src/pages/**/*.{tsx,jsx}`
  - Exclude `pages/api/**`, `_app`, `_document`, `_error`.
- Discover Vite/React route-like pages:
  - `src/pages/**/*.{tsx,jsx}`
  - `src/routes/**/*.{tsx,jsx}`
  - `src/features/**/{*Page,*RoutePage}.{tsx,jsx}`
- Derive route paths from framework conventions.
- Derive titles from exported component names, `@name` comments, file paths, and i18n keys where cheap.
- Compute source hash from normalized primary file content plus selected referenced files.

### Prompt Builder

Add a code-backed prompt builder beside existing prompt helpers:

```python
def build_code_backed_html_prompt(candidate: CodePrototypeCandidate, project: Project) -> str:
    ...
```

Prompt requirements:
- Output complete single-file HTML only.
- Preserve the source page's information architecture and interaction intent.
- Use realistic static data where runtime APIs are unavailable.
- Include visible states implied by the code: empty, loading, error, success, selected row, disabled action.
- Do not execute source code.
- Mention source route/path in an internal comment at the top of generated HTML for traceability.

### Persistence Design

First restore existing prototype persistence:
- `prototypes` table.
- `prototype_versions` table.
- Store CRUD methods used by `PrototypeService`.
- Tests that prove existing manual flow works before new code-driven flow is added.

Then extend prototype metadata:

```sql
ALTER TABLE prototypes ADD COLUMN source_kind TEXT DEFAULT 'manual';
ALTER TABLE prototypes ADD COLUMN source_ref TEXT;
ALTER TABLE prototypes ADD COLUMN source_hash TEXT;
ALTER TABLE prototypes ADD COLUMN source_meta_json TEXT;
CREATE INDEX IF NOT EXISTS idx_prototypes_project_source
ON prototypes(project_id, source_kind, source_ref);
```

Domain model additions:

```python
source_kind: Literal["manual", "code"] = "manual"
source_ref: str | None = None
source_hash: str | None = None
source_meta: dict | None = None
```

Store helper additions:
- `load_prototype_by_source(project_id, source_ref)`.
- `update_prototype_source_metadata(prototype_id, source_hash, source_meta)`.
- `list_code_prototypes(project_id)`.

### Service Flow

Add `PrototypeService.generate_all_from_code_stream(project_id)`.

Algorithm:

1. Load project.
2. Scan candidates.
3. Yield `scan_meta`.
4. If no candidates, yield `all_done` with empty counts and return.
5. For each candidate:
   - Yield `candidate_start`.
   - Load existing code-backed prototype by `source_ref`.
   - If exists and `source_hash` unchanged, yield `candidate_skip`.
   - If missing, create a prototype with source-backed seed brief.
   - If changed, update seed v0 instruction with rebuilt source-backed brief and update source metadata.
   - Stream generation with `stream_events(prototype.id, instruction=None)`.
   - Forward deltas as `prototype_delta`.
   - On done, yield `prototype_done`.
   - On error/exception, yield `prototype_error` and continue.
6. Yield `all_done`.

SSE contract:

```text
event: scan_meta
data: {count, candidates, created_count, changed_count, unchanged_count, unsupported_count}

event: candidate_start
data: {candidate_id, route, title, action}

event: candidate_skip
data: {candidate_id, prototype_id, reason: "unchanged"}

event: prototype_created
data: {candidate_id, prototype_id, title}

event: prototype_delta
data: {candidate_id, prototype_id, chunk}

event: prototype_done
data: {candidate_id, prototype_id, version_no, disk_path}

event: prototype_error
data: {candidate_id, prototype_id?, message}

event: all_done
data: {created, regenerated, skipped, failed, unsupported}
```

### API Design

Add to prototype router:

- `GET /api/projects/{project_id}/prototypes/code-candidates`
  - Returns candidate preview and classification against existing prototypes.
- `GET /api/projects/{project_id}/prototypes/generate-from-code/stream`
  - SSE stream described above.

Response preview shape:

```json
{
  "project_id": "project-1",
  "count": 18,
  "candidates": [
    {
      "id": "next-app--projects-id-prototypes",
      "route": "/projects/:id/prototypes",
      "title": "Project Prototypes",
      "action": "create|regenerate|skip|unsupported",
      "source_paths": ["frontend/src/app/projects/[id]/prototypes/page.tsx"],
      "source_hash": "sha256:...",
      "prototype_id": null
    }
  ]
}
```

## Frontend Design

### Types

Add:

```ts
export interface PrototypeCodeCandidate {
  id: string;
  title: string;
  route: string;
  kind: "page" | "route" | "feature";
  framework_hint: string;
  source_paths: string[];
  primary_source_path: string;
  source_hash: string;
  action: "create" | "regenerate" | "skip" | "unsupported";
  prototype_id?: string | null;
  unsupported_reason?: string | null;
}
```

Extend `Prototype` with source metadata fields.

### API Helpers

Add:

```ts
listPrototypeCodeCandidates(projectId)
getGenerateFromCodeStreamUrl(projectId)
```

### ProjectPrototypesPage Changes

Add state:
- `codeScanOpen`.
- `codeCandidates`.
- `codeScanLoading`.
- `codeGenProgress`.
- `codeGenSourceRef`.

Add toolbar button:
- Label zh-CN: `从代码生成`
- Label en-US: `Generate from code`

Add scan review dialog:
- Fetch candidates on open.
- Display candidate table and counts.
- Start stream on confirm.

Add generation progress dialog:
- Reuse existing EventSource cleanup pattern.
- Track candidate statuses in a keyed object.
- Close only after `all_done` or explicit finished state.

Add list badges:
- Manual.
- Code.
- Changed.
- Missing HTML.

### I18n

Add keys under:

```text
prototype.generateFromCode.*
```

Required key groups:
- button/title/subtitle.
- scan loading/no candidates.
- action create/regenerate/skip/unsupported.
- progress status labels.
- summaries.
- error recovery copy.

## HTML Prototype Coverage

The five HTML prototypes in `prototypes/` cover every user-facing page/state introduced by this feature:

1. Prototype hub after code generation support.
2. Scan review before generation.
3. Generation progress during SSE.
4. Generated prototype detail with source traceability.
5. Empty/unsupported diagnostic state.

Each prototype is static, self-contained, and intended for design review before implementation.

All five prototypes follow the current frontend code's dark Console v2 system from `globals.css`, `ProjectShell`, `ProjectPrototypesPage`, `PrototypeCanvas`, and the shared UI components. The scan and progress flows are compact dialogs over the project prototype page; the detail and empty states remain inside the same two-column prototype workbench. They intentionally avoid the earlier light beige/warm standalone prototype palette and do not wrap this route in the global `WorkbenchShell`.

## Edge Cases

- Store methods missing: block stream with diagnostic until persistence exists.
- Project repo missing on disk: return 404-like business error with recovery.
- Unsupported framework: show unsupported candidates with reasons, do not silently skip.
- Very large files: truncate source excerpts and annotate scan limits.
- Dynamic routes: normalize `[id]` and `[...slug]` into stable route/source IDs.
- Duplicate route titles: use route-derived stable IDs.
- Changed source while stream is running: source hash captured at scan start; next run catches later changes.
- LLM error for one page: mark failed and continue.
- Client disconnect mid-generation: current `stream_events` behavior avoids partial version writes; batch may stop on disconnected SSE unless server keeps running in future background-task mode.

## Test Plan

Backend:
- Scanner detects Next app routes from temporary directories.
- Scanner ignores `node_modules`, `.next`, and `.agent-collab`.
- Scanner normalizes dynamic routes.
- Store prototype CRUD methods exist and pass manual flow tests.
- Code-backed create: missing candidate creates prototype and v1.
- Code-backed skip: unchanged candidate emits skip and no new version.
- Code-backed changed: changed hash updates seed and creates next version.
- Per-candidate failure continues.
- API preview returns correct actions.
- SSE endpoint returns terminal `all_done`.

Frontend:
- TypeScript typecheck.
- Candidate dialog renders loading, empty, populated, and unsupported states.
- EventSource lifecycle closes on `all_done` and error.
- Prototype list shows source badges.

Manual review:
- Open all static HTML prototypes.
- Verify every introduced page/state is represented.
- Verify no page uses hidden instructions in visible copy.

## Rollout Plan

1. Repair/confirm prototype persistence and tests.
2. Add scanner service and tests.
3. Add source metadata columns and source lookup helpers.
4. Add code-driven service stream.
5. Add preview and stream endpoints.
6. Add frontend candidate review and progress UI.
7. Update docs/CLAUDE.md core loop.
8. Run backend focused tests and frontend typecheck.
