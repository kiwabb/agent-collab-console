# Add Vue Router prototype page discovery

## Goal

Discover Vue 3 / Vue Router 4 pages as deterministic prototype planning candidates so repositories such as `examples/admin-demo` produce a complete page inventory.

## Requirements

- Detect `vue-router` packages as supported web surfaces.
- Parse static route records passed to `createRouter({ routes: [...] })` with the existing tree-sitter TypeScript parser.
- Support literal route paths, nested `children`, lazy `import("*.vue")` components, and statically imported Vue components.
- Ignore redirects and Vue Router catch-all records as non-page routes.
- Refuse to invent dynamic paths or unresolved component files; expose bounded diagnostics instead.
- Default omitted MCP `states` from the deterministic page candidate while validating explicit values strictly.
- Refresh the persisted plan revision immediately before generation and block generation while plan mutations are saving.
- Isolate nested project roots correctly during prototype generation and serialize shared Git snapshot preparation.
- Give nested generation directories an independent temporary Git root and preserve upstream runtime API errors.
- Include the route declaration, `.vue` page source, `App.vue` layout, and shared style files as evidence when present.
- Add `vue-router-route` to the typed backend/frontend evidence contract and localized evidence labels.
- Preserve existing React Router, Next.js, extension, and fallback behavior.

## Acceptance Criteria

- [x] Scanning `examples/admin-demo` reports the frontend package as supported.
- [x] The scan returns exactly `/dashboard`, `/users`, and `/orders` page candidates.
- [x] Each candidate points to the corresponding `.vue` page source and uses `framework_hint="vue-router"`.
- [x] Redirect and catch-all records do not become candidates.
- [x] Nested static Vue Router children resolve to joined route paths.
- [x] Dynamic route declarations produce diagnostics instead of guessed candidates.
- [x] Focused backend and frontend contract tests pass.
- [x] MCP registration succeeds when `states` is omitted and persists candidate-derived states.
- [x] Generation does not report source changes for an internal stale plan revision.
- [x] Parallel generation for an untracked nested project avoids Git index contention and preserves reviewed source hashes.
- [x] Claude writes artifacts relative to the configured nested project, and quota errors are not mislabeled as invalid manifests.

## Out of Scope

- Executing arbitrary JavaScript/TypeScript route factories.
- Nuxt file-based routing.
- Vue Router configurations assembled across multiple runtime variables or plugins.

## Technical Notes

- Scanner: `backend/app/application/project_evidence_service.py`.
- Repository path resolution: `backend/app/adapters/project_source_reader.py`.
- Evidence contract: backend domain types, frontend prototype types/stream validation/i18n mapping.
- Primary fixture: `examples/admin-demo/frontend/src/router.ts`.
