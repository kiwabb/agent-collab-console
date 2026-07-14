# External Prototype Agent Contract

## Scenario: Local Agent Structured-Prototype Collaboration

### 1. Scope / Trigger

- Trigger: changing local Claude Code or Codex prototype collaboration, pairing capabilities, the `prototype-collaboration` MCP server, Skill packaging, external command validation, or Studio proposal persistence.
- The product remains authoritative for document state, rendering, Apply, Reject, Publish, and audit evidence. The external Agent has read and propose authority only.

### 2. Signatures

- Pairing API: `POST /api/external-prototype-agent/pairings` and `DELETE /api/external-prototype-agent/pairings/{pairing_id}`.
- Audit API: `GET /api/external-prototype-agent/audit-events?projectId=...&documentId=...`.
- MCP endpoint: `POST /api/internal/external-prototype-agent-mcp`, loopback only, with `Authorization: Bearer <pairing capability>`.
- MCP tools: `get_prototype_capabilities`, `get_active_design_context`, `get_document_slice`, `validate_command_batch`, `submit_command_proposal`, and `get_proposal_status`.
- Tables: `external_prototype_agent_pairings`, `external_prototype_agent_submissions`, and `external_prototype_agent_audit_events`.
- Core adapter: `StructuredPrototypeExternalCollaboration` implements `StructuredPrototypeCollaborationPort` and writes proposals through `StructuredPrototypeAiService.submit_external_proposal(...)`.

### 3. Contracts

- Pairing binds one `projectId`, `documentId`, Agent kind, permission set, protocol version, Skill version, expiry, and bearer-token digest. The raw bearer value is returned once and never stored.
- Claude Code and Codex share `integrations/local-agent/skills/prototype-designer/SKILL.md`; host manifests only adapt installation and bearer injection.
- Active context returns one immutable base: `draftId`, `headSequenceNo`, `documentHash`, and `commandContractVersion`.
- Active context also returns `supportedCommandKinds` and `context.commandBatchSchema`. Agents must construct camelCase `DomainCommandBatchV1` payloads from that exact schema.
- Validation parses the real domain command batch and executes it against the replay-verified draft without changing the draft.
- Submission is idempotent by pairing plus `clientRequestId`. It creates a normal Studio `PrototypeAiEditRunRecord`, candidate object, rendered preview, and replay manifest. Existing Studio Apply and Reject paths remain authoritative.
- External Agent replay identity records the Agent kind, pairing ID, task identity, and submission identity without storing credentials or command bodies in the external audit tables.

### 4. Validation & Error Matrix

- Non-loopback MCP peer -> `loopback_required`.
- Missing, malformed, expired, revoked, or unknown bearer -> stable pairing error and no tool execution.
- Project/document mismatch or no active draft -> `pairing_scope_invalid`.
- Draft sequence/hash mismatch -> `stale_base`.
- Command JSON outside `DomainCommandBatchV1` -> `command_batch_invalid`.
- Declared affected IDs differ from command execution -> `affected_entities_mismatch`.
- Same idempotency key with changed canonical arguments -> `submission_conflict`.
- Missing renderer/structured core at bootstrap -> `prototype_core_unavailable`; do not fall back to legacy HTML or a generic LLM path.
- Proposal lookup from another pairing -> `proposal_missing`.

### 5. Good/Base/Bad Cases

- Good: Codex reads a bounded page slice, validates `setNodeProperty`, submits once, receives `preview_ready`, and the user applies it through the existing Studio API.
- Base: a read-only pairing lists only read tools and cannot submit a proposal.
- Bad: persisting the bearer token, full document, prompt, or command body in external audit/submission tables.
- Bad: giving the MCP server Apply, Publish, shell, arbitrary file, SQL, HTML replacement, or full-document replacement tools.
- Bad: inventing a second proposal state machine instead of producing the normal Studio AI edit run.

### 6. Tests Required

- Pairing persistence asserts only the SHA-256 token digest reaches SQLite and lifecycle expiry/revocation fails closed.
- MCP tests assert loopback enforcement, permission-filtered `tools/list`, strict JSON-RPC parsing, bounded payloads, and redacted audit rows.
- Validation tests assert the current draft identity, exact command schema, affected IDs, stale bases, and invalid commands.
- Integration test creates a structured document, reads context/slices, submits an external proposal, verifies rendered preview and external replay identity, applies through `StructuredPrototypeAiService.apply`, and observes external status `applied`.
- Package validator asserts the canonical Skill, host manifests, references, and scripts are complete and contain no bearer values.

### 7. Wrong vs Correct

#### Wrong

```python
await external_store.save_proposal(command_json=request.batch, bearer_token=token)
await structured_service.apply_command_batch(...)
```

This leaks capability and command bodies into the external boundary and bypasses human preview.

#### Correct

```python
validation = await collaboration.validate_command_batch(pairing, request)
receipt = await collaboration.submit_command_proposal(
    pairing,
    request,
    request_hash,
    origin="external_agent",
)
```

The collaboration adapter validates the real command contract and persists a normal Studio preview; Apply and Publish remain separate human-controlled operations.
