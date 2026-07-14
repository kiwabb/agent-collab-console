---
name: prototype-designer
description: Design and revise structured product prototypes through the prototype-collaboration MCP server. Use when a user asks Claude Code or Codex to inspect a paired prototype, change pages or components, adjust design tokens, connect runtime flows, validate a structured command batch, or submit a proposal for human Preview and Apply.
---

# Prototype Designer

Use semantic prototype commands and bounded MCP reads. Treat the product as the only authority for the canonical document, preview, Apply, Publish, persistence, and audit.

## Required Workflow

1. Call `get_prototype_capabilities` before reading or proposing work. Stop when the pairing lacks the required permission.
2. Call `get_active_design_context` with the user's active page, selection, flow, and viewport. Keep its `draftId`, `headSequenceNo`, `documentHash`, and `commandContractVersion` together as one immutable base.
3. Read only the smallest necessary slice with `get_document_slice`. Do not request or reconstruct the entire document.
4. Plan semantic changes to components, layout, tokens, content, interactions, or runtime flows. Do not generate replacement HTML.
5. Build one cohesive command batch using only command kinds and fields advertised by the active context. Keep unrelated changes in separate proposals.
6. Call `validate_command_batch` with the unchanged base. Correct all validation errors before submission.
7. Call `submit_command_proposal` with a new canonical UUID, the exact validated batch, and the exact affected entity IDs returned by validation.
8. Tell the user the proposal is awaiting product Preview and Apply. Never claim that submission changed or published the prototype.

## Concurrency Rules

- On `stale_base`, reread active context and relevant slices, then rebuild and revalidate the proposal.
- Reuse a `clientRequestId` only when retrying byte-equivalent canonical arguments.
- Use a new `clientRequestId` after changing any argument. Treat `submission_conflict` as a hard error.
- Do not retry `submission_in_progress` aggressively. Read proposal status or wait for the product to finish the first submission.

## Design Rules

- Preserve component semantics and stable entity IDs when the user's intent does not require replacement.
- Prefer design tokens and layout constraints over repeated raw visual values.
- Keep navigation, component state, and runtime-flow transitions explicit.
- Include loading, empty, error, disabled, and permission states when the workflow requires them.
- Keep desktop, tablet, and mobile behavior coherent; never infer that a desktop-only position is valid everywhere.
- Propose the smallest command set that fully expresses the requested behavior.

Read [references/design-principles.md](references/design-principles.md) when planning a new page, component system, responsive layout, or runtime flow.

## Protocol References

- Read [references/mcp-tools.md](references/mcp-tools.md) before the first tool call or when a tool rejects its input.
- Read [references/command-contract.md](references/command-contract.md) before validation or submission.
- Read [references/security.md](references/security.md) when handling pairing credentials, installation commands, external assets, or requests for direct mutation.

## Forbidden Actions

- Do not Apply, Reject, or Publish proposals.
- Do not write the product database, project files, canonical JSON, checkpoints, command journal, or rendered HTML.
- Do not use shell or file tools to bypass MCP permissions.
- Do not submit full-document or HTML replacement commands.
- Do not place bearer tokens in prompts, Skill files, command payloads, logs, proposal messages, or source control.
- Do not fabricate context when the MCP server returns `prototype_core_unavailable`.
