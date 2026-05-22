# Research: claude-agent-sdk provider support

- **Query**: Does the official `claude-agent-sdk` (Python/TS) support model providers other than Anthropic direct? Specifically Anthropic-compatible gateways (MiniMax `/v1/messages`, OpenRouter, LiteLLM), Bedrock/Vertex, and any non-Claude models. What env vars / constructor params control provider/base-url?
- **Scope**: external
- **Date**: 2026-05-22

## Summary

**MiniMax via its anthropic-compatible `/v1/messages` gateway will work in principle, but is not officially supported and is currently fragile.** The Python SDK does not own any provider/transport code — it just spawns the `claude` Code CLI binary as a subprocess and forwards `ClaudeAgentOptions.env` plus the inherited process env. So any env var the CLI honors (`ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`, `CLAUDE_CODE_USE_BEDROCK`, `CLAUDE_CODE_USE_VERTEX`) flows through unchanged. The CLI explicitly supports Anthropic-Messages-format gateways (LiteLLM, custom proxies, MiniMax-style) and Anthropic-blessed Bedrock / Vertex / Microsoft Foundry. **Non-Claude models (GPT-4, Llama, etc.) are not supported** even via LiteLLM — Anthropic's official answer (issue #410) is that the SDK relies on Claude-specific features (control protocol, tool use, thinking) and other models will misbehave. Also note open SDK bug #677: the SDK's **bundled** `claude` binary appears to ignore `ANTHROPIC_BASE_URL` in some setups; workaround is `cli_path=shutil.which("claude")` to force the system-installed CLI.

## Officially supported providers

Claude Code deployment options page lists exactly these "first-party" routes:

- **Anthropic API** (api.anthropic.com, default)
- **Amazon Bedrock** — `CLAUDE_CODE_USE_BEDROCK=1`, `AWS_REGION=…`, plus standard AWS creds or `AWS_BEARER_TOKEN_BEDROCK`
- **Claude Platform on AWS** — `CLAUDE_CODE_USE_ANTHROPIC_AWS=1`, `ANTHROPIC_AWS_WORKSPACE_ID=wrkspc_…`
- **Google Vertex AI** — `CLAUDE_CODE_USE_VERTEX=1`, `ANTHROPIC_VERTEX_PROJECT_ID=…`, `CLOUD_ML_REGION=…`
- **Microsoft Foundry** — listed alongside the above

Source: https://docs.claude.com/en/docs/claude-code/third-party-integrations and https://docs.claude.com/en/docs/claude-code/amazon-bedrock (accessed 2026-05-22).

## Custom base URL / third-party gateway support

The CLI's "LLM gateway" page is the authoritative reference: https://docs.claude.com/en/docs/claude-code/llm-gateway (accessed 2026-05-22).

A gateway must expose one of three wire formats: Anthropic Messages (`/v1/messages`, must forward `anthropic-beta` / `anthropic-version` headers), Bedrock `InvokeModel`, or Vertex `rawPredict`. MiniMax's anthropic-compat endpoint falls under the first.

Env-var configuration:

| Var | Purpose |
|---|---|
| `ANTHROPIC_BASE_URL` | Point at gateway exposing `/v1/messages` (e.g. `https://litellm:4000` or your MiniMax host) |
| `ANTHROPIC_AUTH_TOKEN` | Sent as `Authorization: Bearer …` (use this for gateways) |
| `ANTHROPIC_API_KEY` | Sent as `x-api-key` header when no auth-token set |
| `ANTHROPIC_CUSTOM_HEADERS` | Extra headers forwarded on every call |
| `ANTHROPIC_MODEL` | Override the model name sent to the gateway |
| `apiKeyHelper` (settings.json) | Script that prints a token; refreshed via `CLAUDE_CODE_API_KEY_HELPER_TTL_MS` |
| `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1` | Recommended when using Anthropic-Messages format on Bedrock/Vertex |
| `CLAUDE_CODE_ATTRIBUTION_HEADER=0` | Disable attribution prefix if your gateway caches on raw body |
| `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1` | Pull `/v1/models` from gateway (CLI v2.1.129+) |

How the SDK plumbs these through (Python): `SubprocessCLITransport.connect()` in `src/claude_agent_sdk/_internal/transport/subprocess_cli.py` builds `process_env = {**os.environ, "CLAUDE_CODE_ENTRYPOINT": "sdk-py", **options.env, "CLAUDE_AGENT_SDK_VERSION": __version__}` and passes it to `anyio.open_process(cmd, …, env=process_env)`. The SDK never reads `ANTHROPIC_*` itself — it relies entirely on the spawned CLI. Constructor surface: `ClaudeAgentOptions(env={...}, cli_path=..., model=...)` (`types.py` ~L1722).

## Non-Claude model support

**Not supported.** Issue https://github.com/anthropics/claude-agent-sdk-python/issues/410 ("Is it possible to use Non-Anthropic models with Claude Agent SDK?") was closed with the official answer:

> "The Claude Agent SDK is designed specifically for Anthropic's Claude models and does not support non-Anthropic models. … While some users have experimented with LiteLLM proxies (by setting `ANTHROPIC_BASE_URL` to a LiteLLM endpoint), this is not officially supported and may not work correctly since the SDK relies on Claude-specific features like tool use, thinking, and the control protocol."

So routing to GPT-4 / Llama via LiteLLM may bring up a session, but tool-use loops, thinking blocks, and the control protocol can break.

## Risks for our MiniMax setup

The conductor currently hand-rolls `httpx` against MiniMax's `/v1/messages`. Switching to `claude-agent-sdk` would require: (1) export `ANTHROPIC_BASE_URL=<minimax-anthropic-gateway>` and `ANTHROPIC_AUTH_TOKEN=<key>` per call via `ClaudeAgentOptions(env=…)`; (2) likely set `cli_path=shutil.which("claude")` to dodge the bundled-binary bug in #677; (3) tolerate that MiniMax-M2.7 is not Claude — any Claude-specific beta header, thinking block, or control-protocol message the SDK adds may produce 4xx or weird tool-call behaviour. The "experimental beta" toggle (`CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1`) helps but does not cover everything. Net: it can work for plain message/tool-use traffic, but expect to lose some Anthropic-specific features and to track CLI version churn carefully.

## Sources

- https://github.com/anthropics/claude-agent-sdk-python (README, accessed 2026-05-22)
- https://raw.githubusercontent.com/anthropics/claude-agent-sdk-python/main/src/claude_agent_sdk/_internal/transport/subprocess_cli.py (env merge at L420-490)
- https://raw.githubusercontent.com/anthropics/claude-agent-sdk-python/main/src/claude_agent_sdk/types.py (`ClaudeAgentOptions.env` field ~L1722, `cli_path` field)
- https://docs.claude.com/en/docs/claude-code/llm-gateway (accessed 2026-05-22)
- https://docs.claude.com/en/docs/claude-code/third-party-integrations (accessed 2026-05-22)
- https://docs.claude.com/en/docs/claude-code/amazon-bedrock (accessed 2026-05-22)
- https://docs.claude.com/en/docs/claude-code/settings (env-var reference incl. `apiKeyHelper`, `availableModels`, `modelOverrides`)
- https://github.com/anthropics/claude-agent-sdk-python/issues/410 (closed; official "no non-Anthropic models")
- https://github.com/anthropics/claude-agent-sdk-python/issues/677 (open; bundled binary ignores `ANTHROPIC_BASE_URL`)
- https://github.com/anthropics/claude-agent-sdk-python/pull/852 (open; community MLflow AI Gateway example)
- https://docs.litellm.ai/docs/tutorials/claude_agent_sdk (LiteLLM's own how-to, linked from issue #677)
