# ACP v1 runtime research

## Sources

- ACP stable v1 schema: https://github.com/agentclientprotocol/agent-client-protocol/blob/main/schema/v1/schema.json
- ACP protocol overview: https://agentclientprotocol.com/protocol/overview
- Agent Studio ACP client reference: https://github.com/sxhxliang/agent-studio/blob/main/crates/agentx-agent/src/client.rs

## Protocol facts used by this task

- Wire compatibility is negotiated through `initialize.protocolVersion`; the current stable version is `1`.
- The client can truthfully advertise no filesystem or terminal capabilities:
  `fs.readTextFile=false`, `fs.writeTextFile=false`, `terminal=false`.
- The minimal turn lifecycle is:
  `initialize` -> `session/new` -> `session/prompt`, with `session/update`
  notifications carrying message, thought, tool, plan and usage updates.
- `session/cancel` is a notification. A cancelled turn must also resolve every
  outstanding `session/request_permission` request with a cancelled outcome.
- Permission options have semantic kinds: `allow_once`, `allow_always`,
  `reject_once`, and `reject_always`.
- The response to `session/prompt` contains a `stopReason`; only `end_turn` is an
  unambiguous successful completion for this console's fail-closed task model.
- A session can expose model selection through `configOptions` and
  `session/set_config_option`. The client must not claim that a model override
  was applied when the agent does not expose a matching option.

## Repository mapping

- Reuse the newline-delimited transport in
  `backend/app/application/json_rpc_client.py::AsyncJsonRpcPeer`.
- Do not reuse `AppServerClient`; its methods and approvals are Codex-specific.
- Add an explicit third runtime route in `CodexProcessManager`. The current
  `codex else claude` branch would otherwise silently send ACP work to Claude.
- Keep the existing `Conductor + CodexTaskRunner + ExecutionProcess + worktree`
  path authoritative. ACP is an executor adapter, not a second orchestration
  stack.
- Store ACP launch shape in the existing runtime-catalog JSON. No database DDL
  is needed.

## Security decisions

- Spawn with `create_subprocess_exec(command, *args)`, never a shell command.
- Store only environment variable *names* in `env_allowlist`; values are read
  from the backend process environment at launch and never returned by the API.
- Use a small inherited base environment plus the explicit allowlist instead of
  copying the backend's complete environment.
- Manual permission requests time out and resolve as cancelled. Missing or
  malformed protocol responses fail the task rather than allowing execution.

