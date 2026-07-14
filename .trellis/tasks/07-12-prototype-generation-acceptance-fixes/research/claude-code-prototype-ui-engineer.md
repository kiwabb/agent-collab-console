# Claude Code prototype UI engineer integration

## Confirmed current behavior

- Project-driven page generation calls the Anthropic-compatible HTTP SSE API
  directly through `PrototypeService`; it does not invoke Claude Code.
- The fallback uses the shared streaming token limit. A real 13-page run ended
  with 8 successes and 5 failures; four failures reported `max_tokens` and one
  produced incomplete HTML.
- `PrototypeGenerationService` discards HTML delta events and persists only
  item terminal transitions. The UI therefore has no output-activity signal.
- The run's `completed` counter means successful pages. Rendering it as the
  primary numerator makes a terminal 8-success/5-failure run appear as 8/13.
- The Runtime Catalog already contains a Claude executor configured for an
  Anthropic-compatible MiniMax endpoint/model. `ClaudeProcessRuntime` injects
  the catalog endpoint, credential, and model into Claude Code.

## Decision

Reuse the existing task/runtime stack rather than adding another Claude SDK or
subprocess implementation:

1. Seed a built-in `prototype_ui_engineer` agent with executor `claude`; provider
   and model remain catalog-owned.
2. Create one `task_kind=prototype_generation` task per run item in an isolated
   worktree.
3. Instruct Claude Code to read the real project source and write only
   `.agent-collab/prototype-staging/<run-item-id>/index.html`.
4. The final assistant response is a strict, small manifest containing status,
   relative artifact path, SHA-256, and warnings. It never contains HTML.
5. Validate containment, symlinks, UTF-8, byte size, complete HTML, external URL
   allowlist, checksum, and source-tree diff before atomically completing the
   prototype version/run item.
6. Persist task/process identity and coarse activity (`phase`, output size,
   last event time) on the run item. SSE emits revisioned snapshots plus
   heartbeat; REST polling reconciles active state after stream silence/error.
7. Keep direct HTTP streaming only for manual prototype creation with an
   independent `PROTOTYPE_GENERATION_MAX_TOKENS >= 16384` setting. Project-
   driven generation fails closed when the repository-capable Claude runtime
   is unavailable and never falls back to direct HTTP.
8. Claude chooses how to create the staging file. The backend validates the
   final file and manifest, never replays Write/Edit logs or whitelists Bash.
   Runtime and audit surfaces retain the complete Agent trajectory, including
   HTML and tool content, but never use that history as artifact evidence.

## Counter contract

- `processed = done + failed + interrupted + skipped`
- `succeeded = done`
- `failed = failed + interrupted`
- `running = generating`
- `pending = pending`

The first-viewport progress bar uses `processed / total`. Success and failure
remain separate secondary metrics.

## Locale and evidence contract

`output_locale` is persisted on the plan and governs all model-authored human
text. Stable source paths and raw excerpts retain their original language.
Evidence IDs referenced by the planner are persisted and rendered with a
localized evidence type, file/line location, diagnosis, and bounded excerpt.
