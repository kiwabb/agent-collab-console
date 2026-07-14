# Security Boundary

The pairing bearer grants short-lived access to one project and one prototype document. It grants only `prototype:read` and/or `prototype:propose`.

## Credential Handling

- Read the bearer from `PROTOTYPE_AGENT_TOKEN` or the host's approved secret injection mechanism.
- Send it only as the loopback MCP Authorization bearer.
- Never print it, quote it in chat, persist it in project files, add it to a proposal, or commit it.
- Revoke the pairing and remove its host MCP entry when work ends. A copied expired token has no authority but should still be treated as secret.

## Authority Limits

The product owns validation, preview rendering, Apply, Reject, publication, command journaling, checkpoints, and audit. The Agent cannot grant itself any of these capabilities.

Refuse requests to bypass the boundary through database access, browser DOM mutation, direct HTML replacement, shell commands, project-file edits, or hidden network endpoints. Explain that the Agent can submit a structured proposal for human review.

## Data Minimization

- Read the active selection before requesting wider page data.
- Request tokens or runtime-flow slices only when the change needs them.
- Do not reproduce document slices in proposal messages or logs.
- Use request hashes, entity IDs, proposal IDs, and stable error codes for diagnostics.
