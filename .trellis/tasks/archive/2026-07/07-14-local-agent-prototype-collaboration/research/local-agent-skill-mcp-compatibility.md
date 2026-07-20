# Local Agent Skill and MCP Compatibility

## Scope

Repository- and installation-backed comparison for the first external prototype Agent hosts: Claude Code and Codex.

## Evidence Inspected

- Local `claude mcp --help` and `claude mcp add --help` from the installed Claude Code CLI.
- Local `codex mcp --help` and `codex mcp add --help` from the installed Codex CLI.
- Claude's installed official example Skill under `~/.claude/plugins/marketplaces/claude-plugins-official/plugins/example-plugin/skills/example-skill/SKILL.md`.
- Codex's installed curated Figma Skill under `~/.codex/vendor_imports/skills/skills/.curated/figma-generate-design/`.
- The repository's `local_auth.py` and current Skill metadata service.

## Findings

### Common portable core

- Both hosts can consume a folder centered on `SKILL.md` with YAML `name` and `description` plus Markdown instructions.
- Both CLIs support streamable HTTP MCP servers.
- Both can authenticate MCP requests without embedding a bearer token in the Skill body.
- Therefore one canonical Skill body and one MCP protocol can serve both hosts.

### Claude Code differences

- `claude mcp add` supports `local`, `user`, and `project` scopes.
- HTTP headers can be configured directly.
- Project-scoped `.mcp.json` servers are approval-gated by Claude Code.
- Claude plugin Skills may carry extra frontmatter, but the portable package should keep only `name` and `description`.

### Codex differences

- `codex mcp add --url` configures a streamable HTTP server.
- `--bearer-token-env-var` keeps the bearer value outside `config.toml`.
- Codex Skills add optional `agents/openai.yaml` UI metadata and may declare the MCP dependency there.
- Codex does not expose Claude's identical project-scope flag in the inspected CLI command, so installation must be represented as a host-specific command/manifest rather than one universal shell snippet.

### Repository constraints

- Existing `SkillService` stores remote Skill metadata, not an executable, versioned local-Agent package. The collaboration Skill needs a separate versioned artifact location.
- Existing local auth protects the console control plane but uses the console-wide token. External Agent pairing must use a narrower project/document capability and must not forward the console token.
- Stable HEAD has only legacy HTML prototypes, so the external protocol must depend on a typed structured-core port and fail closed until it is wired.

## Decision

- Store one canonical `prototype-designer` Skill in the repository.
- Generate/validate thin Claude Code and Codex host manifests from the same package metadata.
- Use loopback streamable HTTP MCP for both hosts.
- Use a short-lived pairing bearer token. Claude receives it as an HTTP header; Codex receives it through a named environment variable.
- Do not write either host's global configuration from the backend MVP. Return an installation manifest/command that the local user or Agent can apply explicitly.

## Deferred Compatibility

- Cursor, Gemini CLI, OpenCode, and other Agent products.
- OAuth or device-code pairing.
- Cloud relay/local bridge.
- Automatic global Skill installation and uninstall.
