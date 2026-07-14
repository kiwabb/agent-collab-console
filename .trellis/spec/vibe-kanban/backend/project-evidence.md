# Project Evidence

## Scenario: Vue Router Prototype Page Discovery

### 1. Scope / Trigger

- Trigger: changing framework detection, repository source resolution, route parsing, or prototype evidence kinds used by project-driven prototype planning.
- Vue Router support means deterministic `createRouter({ routes: [...] })` discovery. Detecting the `vue` dependency alone is not sufficient.

### 2. Signatures

- `ProjectEvidenceService.scan_project(project) -> ProjectSurfaceManifest`.
- MCP `register_prototype_page` requires `title`, `summary`, `brief`, and `evidence_ids`; `states` is optional at the tool boundary.
- Vue package signals: `("vite", "vue", "vue-router")` when those dependencies exist.
- Vue route evidence kind: `"vue-router-route"` in both backend `EvidenceKind` and frontend `PrototypePlanEvidenceKind`.
- Source resolution supports `.vue` files for local static and dynamic imports.

### 3. Contracts

- A package with `vue-router` is a supported web surface.
- Parse literal route records from a static `routes` array passed directly to `createRouter`.
- Support literal `path`, nested static `children`, statically imported components, and lazy `import("*.vue")` components.
- Join nested relative child paths to their parent path.
- Redirects and catch-all paths (`*` or Vue `pathMatch`) are navigation behavior, not page candidates.
- Include route declaration, resolved page source, `src/App.vue`, and recognized shared styles as bounded evidence when present.
- Do not execute repository code or invent values for dynamic route expressions.
- When MCP omits `states`, copy the deterministic candidate's states before `_PlannerItem` validation. Explicit `states` still pass through strict identifier, uniqueness, and length validation.
- Before generation, the frontend refreshes the persisted plan and submits its latest `updated_at`. Pending plan/selection saves disable generation; repository fingerprint validation remains a separate backend gate.
- Prototype worktrees preserve the configured project root even when `Project.repo_path` is a subdirectory of a containing Git worktree. Git worktree creation uses the containing repository, while evidence scanning and source overlays use `<worktree>/<git show-prefix>`.
- Prototype prepare operations for the same project are serialized because `git stash create` and `git worktree add` share repository index/worktree metadata. Artifact generation after preparation remains parallel.
- A nested isolated project gets its own temporary Git repository and baseline commit. This prevents Claude Code from walking up to the containing worktree root and writing staging artifacts outside the configured project root.
- A successful task status whose result starts with `API Error:` is an upstream runtime failure, not an artifact manifest. Surface the original error before JSON validation.

### 4. Validation & Error Matrix

- Missing `src/router.ts` and `src/router.js` -> unsupported diagnostic candidate.
- Syntax-invalid router entry -> parser diagnostic candidate.
- `routes` is not a static array inside `createRouter` -> diagnostic candidate.
- Dynamic `path` -> low-confidence diagnostic; no guessed route candidate.
- Unresolved component -> low-confidence diagnostic; no page candidate.
- Dynamic/non-array `children` -> diagnostic; discovered sibling routes remain available.
- MCP omits `states` for a known static or dynamic candidate -> persist `candidate.states`.
- MCP supplies invalid `states` -> reject with the existing localized schema error; do not silently replace explicit input.
- Stale in-memory plan revision -> refresh before generation; do not label this as a project source change.
- Repository fingerprint mismatch after refresh -> reject generation and require a new analysis.
- Nested untracked project -> overlay project-relative untracked files under the isolated project prefix; do not scan the containing repository root.
- Concurrent page preparation -> serialize per project; do not let multiple `git stash create` calls contend on `index.lock`.
- Claude writes a valid manifest but the artifact is absent under the configured project root -> verify the nested project has a local temporary `.git` root instead of inheriting the parent worktree.
- Runtime returns `API Error: ...` with task status `done` -> classify as UI engineer failure and preserve the upstream status/message; do not report invalid manifest JSON.

### 5. Good/Base/Bad Cases

- Good: `component: () => import("./pages/UsersPage.vue")` resolves `/users` with the Vue page as primary source.
- Good: MCP registers a listed page without `states`; the server persists the candidate's `("default",)` state.
- Base: `children: [{ path: "profile", ... }]` under `/settings` resolves `/settings/profile`.
- Bad: marking every Vue package supported while returning zero candidates because only `.tsx/.jsx` fallback files are scanned.
- Bad: evaluating imported route factories or constants to guess runtime routes.

### 6. Tests Required

- `backend/tests/test_project_evidence_service.py` scans the real `examples/admin-demo` fixture and asserts `/dashboard`, `/users`, and `/orders`.
- The same test module covers nested children, redirect/catch-all exclusion, and dynamic-path diagnostics.
- `backend/tests/test_prototype_planning_service.py` asserts the MCP schema does not require `states` and omitted states are derived from the candidate.
- `frontend/tests/prototypeStreamEvents.test.ts` verifies the frontend accepts only typed evidence kinds at the stream boundary.
- `frontend/tests/prototypePlanReview.test.ts` verifies plan refresh precedes generation and pending saves block the action.
- `backend/tests/test_worktree_manager.py` verifies concurrent prototype preparation for a nested untracked project returns isolated project roots without parent-repository files.
- The nested-project worktree test also asserts `git rev-parse --show-toplevel` resolves to the configured isolated project root.
- `backend/tests/test_prototype_artifact_generator.py` verifies a done task containing `API Error:` bypasses manifest validation and surfaces the runtime failure.
- Run focused backend pytest, Ruff, mypy for touched files, frontend prototype stream tests, ESLint, Prettier, and frontend typecheck.

### 7. Wrong vs Correct

Wrong:

```python
if "vue" in dependencies:
    support = "supported"  # No Vue route parser or .vue source resolution.
```

Correct:

```python
if "vue-router" in dependencies:
    signals.add("vue-router")
    support = "supported"
# ProjectEvidenceService then parses static createRouter route records.
```
