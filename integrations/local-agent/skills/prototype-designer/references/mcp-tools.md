# MCP Tools

The MCP server is `prototype-collaboration`. Every input uses camelCase and `protocolVersion: 1`. Tool schemas returned by `tools/list` are authoritative.

## Read Tools

`get_prototype_capabilities`

- Input: `{}`
- Use first to confirm the paired project, document, protocol, Skill version, and read/propose authority.

`get_active_design_context`

- Input: `scope` with nullable `pageId`, unique `selectedNodeIds`, nullable `flowId`, and `viewport` (`desktop`, `tablet`, or `mobile`).
- Use to obtain the authoritative draft base, `supportedCommandKinds`, and the exact `context.commandBatchSchema` required to construct a proposal.

`get_document_slice`

- Input: `sliceKind` (`pages`, `selection`, `tokens`, or `runtime_flow`), nullable `pageId`, and unique bounded `entityIds`.
- Request only entities needed for the current proposal.

`get_proposal_status`

- Input: `proposalId` from a successful submission receipt.
- Use to report Preview, Apply, Reject, stale, or failure state. It does not change state.

## Proposal Tools

`validate_command_batch`

- Input: the active `draftId`, `expectedHeadSequenceNo`, `expectedDocumentHash`, and one command batch.
- This is read-only. Preserve the returned affected entity IDs for submission.

`submit_command_proposal`

- Input: the same validation fields plus a canonical UUID `clientRequestId`, concise `message`, and exact `affectedEntityIds`.
- This creates a reviewable proposal, not a document revision.

## Error Handling

- `prototype_core_unavailable`: stop; the structured core adapter is not wired.
- `pairing_expired` or `pairing_revoked`: request a new pairing from the user.
- `tool_not_allowed`: stop; do not seek another mutation path.
- `request_invalid`: compare the arguments with the schema returned by `tools/list`.
- `affected_entities_mismatch`: revalidate; do not edit the returned affected IDs manually.
- `stale_base`: reread context and rebuild against the new base.
- `submission_conflict`: generate a new UUID only after deliberately rebuilding the changed request.
