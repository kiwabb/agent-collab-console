# Add ACP Runtime Adapter

## Goal

Add a production-shaped ACP v1 executor beside the existing Codex and Claude
runtimes so an explicitly configured local ACP agent can execute ordinary
console tasks without changing the Conductor, task, worktree, governance, or
completion-gate semantics.

## Requirements

- Add `acp` as a runtime executor type with a nested launch configuration:
  executable, argv list, host environment-variable allowlist, and bounded
  permission timeout.
- Keep ACP launch configuration in the existing runtime-catalog JSON; old
  catalogs must continue loading without migration.
- Expose ACP launch fields in Settings and allow ACP executors to be selected by
  the existing execution selector.
- Do not expose or persist environment-variable values. Only allowlisted names
  are stored; missing allowlisted variables reject launch.
- Route runtime types explicitly. Unknown executor types must raise instead of
  falling through to Claude.
- Implement stable ACP wire protocol version 1 over newline JSON-RPC/stdio:
  initialize, session/new, optional model config, session/prompt, session/update,
  session/cancel, and session/request_permission.
- Advertise only implemented client capabilities. Filesystem, terminal, MCP
  injection, session load, and remote transports are not advertised.
- Map ACP message/thought/tool updates into the existing task message, log,
  WebSocket event, trace, and ExecutionProcess lifecycle.
- Persist the ACP session ID on the task only. Do not reuse the Codex or Claude
  workspace session fields.
- Keep permission handling manual and fail closed. Existing approval decisions
  map to ACP semantic options; timeout/cancel returns ACP `cancelled`.
- Enforce task worktree cwd exactly like current runtimes and spawn without a
  shell.
- Add an ACP CLI connectivity probe to the runtime catalog's existing CLI-test
  endpoint.

## Acceptance Criteria

- [ ] A catalog containing an `acp` executor round-trips through GET/PUT and old
      catalog JSON still validates.
- [ ] Invalid/missing ACP command, argv, environment names, or timeout values are
      rejected with actionable validation errors.
- [ ] Settings can create/edit an ACP executor without ever receiving an
      environment value from the backend.
- [ ] A fake ACP v1 subprocess proves initialize -> session/new -> model option ->
      session/prompt and produces persisted assistant output plus structured
      thought/tool events.
- [ ] Protocol-version mismatch, malformed handshake, missing allowlisted env,
      process exit, and prompt timeout all fail the task and terminalize its
      ExecutionProcess.
- [ ] Permission approve/reject decisions select the matching ACP option;
      unresolved permissions time out as cancelled.
- [ ] Task cancellation sends session/cancel, resolves pending permissions as
      cancelled, and terminates the process tree.
- [ ] Codex and Claude routing/tests remain green; unknown runtime types do not
      silently route to either runtime.
- [ ] ACP executors cannot be selected as the HTTP Conductor LLM.

## Definition of Done

- Focused backend protocol/runtime/catalog/API tests pass.
- Focused frontend type/editor/compatibility tests pass.
- Ruff and the relevant TypeScript checks pass for changed files.
- No existing user changes are reverted or included accidentally.
- Behavior and configuration example are documented.

## Technical Approach

- Reuse `AsyncJsonRpcPeer` only as the transport and add a dedicated ACP client
  and translator.
- Implement `AcpProcessRuntime` as a `BaseProcessRuntime` sibling and register it
  explicitly in `CodexProcessManager`.
- Pass the resolved runtime-catalog executor ID through `CodexTaskRunner`; the
  runtime loads the corresponding ACP launch configuration at the process
  boundary.
- Keep a live ACP process/session for chat turns while the manager remains
  alive. Fresh processes always create fresh ACP sessions in this MVP.
- Use the existing approval inbox/API, extending the manager aggregation and
  decision mapping rather than creating a parallel approval system.

## Decision (ADR-lite)

**Context:** ACP can be introduced as a replacement orchestration stack, a new
third-party SDK dependency, or a small executor adapter over the repository's
existing JSON-RPC transport.

**Decision:** Add a stable-v1 executor adapter over `AsyncJsonRpcPeer`, preserving
the current execution kernel. Store argv structurally and inherit only a small
base environment plus explicitly named host variables.

**Consequences:** The first version is immediately governed and observable like
other tasks, avoids shell and secret-storage hazards, and adds no SDK dependency.
It intentionally supports only stdio and task-scoped live sessions.

## Out of Scope

- Replacing the Conductor, scheduler, worktree manager, or persistence model.
- ACP filesystem/terminal client methods, remote HTTP/WebSocket transport, MCP
  server injection, authentication flows, or cross-process session loading.
- Using an ACP executor as the Conductor's direct Anthropic/OpenAI HTTP LLM.
- Dockable IDE panels, context-selection chips, and the broader Run Composer.
- Storing new ACP secret values in the catalog; use host login state or explicit
  environment-name allowlisting for this milestone.

## Research References

- [`research/acp-v1-runtime.md`](research/acp-v1-runtime.md) — stable v1 wire
  lifecycle, repository mapping, and security boundary.

## Technical Notes

- The user approved the proposed first thin slice after the Agent Studio review.
- The worktree already contains unrelated uncommitted changes; implementation
  must preserve them and avoid broad rewrites.
- Primary integration points:
  `process_runtime_common.py`, `codex_process_manager.py`,
  `codex_task_runner.py`, `runtime_catalog_service.py`, runtime catalog API and
  Settings editor.

