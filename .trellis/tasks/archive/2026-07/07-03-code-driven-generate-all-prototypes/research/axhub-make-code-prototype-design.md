# Axhub Make Reference Notes For Code-Driven Prototype Generation

## Sources Reviewed

- GitHub repository: https://github.com/xiaokeaijqx/Axhub-Make
- README: Axhub Make positions prototypes as project assets with review, annotation, publishing, and import/export workflows.
- `client/scripts/sync-project-metadata.mjs`: scans `src/prototypes/<name>/index.tsx` and builds `.axhub/make/project.json` metadata.
- `src/server/managementApi.aiRuns.ts`: normalizes AI run outputs into typed artifacts such as prototype, image, document, and file.
- `src/server/managementApi.prototypeUpload.ts`: creates or updates prototype metadata after imports and marks generation status while AI work is running.
- `client/rules/prototype-development-guide.md`: defines a stable prototype directory contract: `src/prototypes/<name>/index.tsx`, optional `style.css`, `components/`, `pages/`, and `assets/`.
- `client/rules/v0-project-converter.md` and `client/rules/ai-studio-project-converter.md`: convert external generated code projects into local prototype entries rather than storing opaque blobs only.

## Useful Patterns

- Prototype resources have stable IDs, display names, source file paths, preview URLs, and optional artifact metadata.
- Metadata is discoverable from filesystem structure, then cached/synced into project metadata for the UI.
- AI generation returns normalized artifacts and status, rather than only free-form assistant text.
- Imports/conversions are represented as source-backed prototype entries that can later be previewed, edited, exported, and published.
- Per-prototype isolation is explicit. Assets, style, canvas artifacts, and pages live under the prototype boundary.

## Mapping To This Repo

Current repo already has manual prototypes in SQLite:

- `Prototype` rows are project-scoped and versioned.
- `PrototypeVersion(version_no=0)` stores the original brief.
- `PrototypeService.stream_events(pid, instruction=None)` generates from the seed brief.
- `PrototypeService.regenerate_all_stream(project_id)` regenerates every existing prototype from its original brief.

The missing capability is different: discover UI surfaces from `Project.repo_path`, create/update prototypes from source code context, then generate all of them. The existing regenerate-all endpoint cannot do this because it only iterates over already-created prototypes.

## Recommended Direction

Use an Axhub-like resource discovery layer, but keep this repo's simpler single-file HTML generator:

1. Scan source code under `Project.repo_path` into deterministic `CodePrototypeCandidate` records.
2. Convert each candidate into a source-backed prototype seed brief with source snippets, route info, framework hints, and dependency/style context.
3. Reuse existing `PrototypeService.create` and `stream_events(..., instruction=None)` to stream generation serially.
4. Add source metadata to prototypes so repeat runs can skip unchanged candidates or regenerate changed ones.

This gets the core "generate all prototypes from code" behavior without importing Axhub Make's full client runtime, canvas system, or publish pipeline.
