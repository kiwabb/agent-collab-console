# Existing AI Generation Boundaries

## Purpose

This note records repository-backed constraints for the structured AI generation design.

## Current Runtime Boundaries

- `prototype_artifact_generator.py` runs the built-in `prototype_ui_engineer` through the configured Claude executor in an isolated project worktree.
- Repository-backed generation fails closed when the Claude runtime, Runtime Catalog configuration, worktree, or governance dependency is unavailable. It does not fall back to direct HTTP generation.
- The agent writes a staged artifact and returns a compact typed manifest. The backend validates path containment, size, UTF-8, completeness, SHA-256, allowed external origins, and unchanged source state.
- Planning can use an ephemeral, token-scoped loopback MCP endpoint. The agent registers durable discoveries incrementally and the token is revoked when the run ends.
- The existing task infrastructure already persists `CodexTask` and execution-process identity, so structured generation can correlate every submission with a fresh project UI Engineer task instead of relying on Claude process memory.

## Current Durable Workflow Boundaries

- Prototype plans freeze repository fingerprints and evidence IDs before generation.
- Generation runs and run items persist phase, attempt, progress, timestamps, task identity, execution-process identity, errors, and terminal status.
- Concurrent generation requests are deduplicated in SQLite, not only by service-local locks.
- Claude task execution and artifact writes occur outside SQLite transactions.
- Generated version publication and run-item completion are one transaction.
- Startup recovery turns active work into explicit `interrupted` states and preserves completed siblings for deterministic retry.

## Current AI Submission Boundaries

- Planning response models use strict Pydantic schemas with `extra="forbid"`, bounded strings/lists, stable technical identifiers, and evidence-reference validation.
- Generic direct streaming exists elsewhere in the codebase, but it relies on provider text and assistant prefill and is explicitly excluded from structured prototype generation/editing.
- The project Claude Code UI Engineer must submit through a scoped MCP boundary or a staged immutable artifact plus compact manifest, with explicit task/process completion evidence.
- Process failure, runtime-limit truncation, missing finalization, invalid manifest, and ambiguous output must remain failures. Syntax repair must not invent missing semantic content.

## Current Observability Boundaries

- Project UI Engineer tasks preserve complete runtime trajectory in task messages, logs, traces, and audit evidence.
- Validation audit events record only safe metadata: task/process identity, artifact path, checksum, size, result, and stable error code.
- INFO logs identify run/task boundaries but do not include full prompts, documents, CodeBlock payloads, source contents, credentials, or model output.

## Design Consequences

1. The user selected one project-bound runtime: requirements generation, repository restoration, and conversation edits all invoke Claude Code `prototype_ui_engineer`; the product backend does not call a generic LLM API or provide a fallback.
2. Requirements/repository are input-source modes, while blueprint/foundation/page/conversation/repair are task protocols. All protocols submit strict contracts to one application validator.
3. Each request creates a fresh `CodexTask`, execution process, isolated worktree, and scoped submission capability. Persisted thread/context/draft state provides continuity rather than hidden Claude session memory.
4. Initial generation must be split into bounded artifacts instead of requesting one complete multi-page document from a single Agent task.
5. Page generation can be retried independently, but no partial set of pages may become the active canonical draft.
6. Conversation history is durable context, while the structured draft remains the only authority for current product state.
7. All cost, timeout, concurrency, page-count, node-count, and repair limits belong in typed `timeouts.py` accessors.

## Files Inspected

- `backend/app/application/prototype_artifact_generator.py`
- `backend/app/application/prototype_planning_service.py`
- `backend/app/application/prototype_generation_service.py`
- `backend/app/application/llm_runner.py`
- `backend/app/application/project_evidence_service.py`
- `backend/app/application/timeouts.py`
- `backend/app/domain/project_evidence.py`
- `backend/tests/test_prototype_generation_service.py`
- `backend/tests/test_prototype_runtime_metadata_boundary.py`
