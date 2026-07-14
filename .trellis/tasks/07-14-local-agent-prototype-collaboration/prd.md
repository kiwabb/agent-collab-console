# Local Agent Prototype Collaboration via Skill and MCP

## Goal

Allow a product manager's own local Agent application to participate in structured prototype design. The Agent learns the design and command workflow from a versioned Skill package, reads bounded prototype context through a project-scoped MCP capability, and submits a validated command proposal for human Preview, Apply, or Reject. The product remains the authority for document state, rendering, publication, and audit evidence.

## What I Already Know

- The user explicitly wants local Agent software, not only the server-managed Claude Code UI Engineer, to participate in prototype design.
- The agreed architecture separates three concerns: the Agent reasons, the Skill explains how to design, and MCP grants typed capabilities.
- The Agent must not write the database, canonical document, rendered HTML, or published revision directly.
- Local Agent and built-in UI Engineer must eventually share one domain-command and proposal contract.
- The main checkout currently has extensive uncommitted structured-prototype and MCP work. This task therefore runs in the dedicated `codex/external-prototype-agent` worktree.
- Stable HEAD does not yet contain the structured prototype core. This branch must expose one typed collaboration port and must not duplicate the in-flight core.

## Requirements

- Provide a canonical `prototype-designer` Skill bundle that documents:
  - structured semantic design principles;
  - supported component and layout constraints;
  - context-reading and proposal workflow;
  - command proposal contract and stale-base behavior;
  - security rules and forbidden direct mutations.
- Provide platform manifests/adapters for Claude Code and Codex without pretending Skill installation paths are universally standardized.
- Provide a project/document-scoped pairing session with a short-lived bearer capability.
- Persist only a digest of the bearer token; never persist or log the bearer value.
- Restrict the first release to loopback clients and `read + propose` permissions.
- Expose an MCP server with typed tools for capabilities, active context, document slices, command validation, proposal submission, and proposal status.
- Require every context and proposal to carry contract versions plus the authoritative draft head sequence and document hash.
- Make proposal submission idempotent. Same capability plus same canonical arguments returns the same receipt; different arguments fail closed.
- Reject direct Apply, Publish, arbitrary shell, arbitrary file, database, full-document replacement, and HTML replacement tools.
- Delegate document reads, command validation, and proposal persistence to `StructuredPrototypeCollaborationPort`.
- Return a stable `prototype_core_unavailable` result when that port is not wired; never fabricate context or silently fall back to legacy HTML.
- Record safe observability metadata for pairing and MCP calls without prompt, source, document, command payload, credential, or model output bodies.
- Keep the integration compatible with a future local bridge for cloud deployments, while the MVP uses direct loopback access.

## Acceptance Criteria

- [x] A canonical Skill package and Claude Code/Codex installation manifests are versioned in the repository.
- [x] Pairing issues a one-time bearer value while persistence exposes only its SHA-256 digest and lifecycle timestamps.
- [x] Non-loopback, expired, revoked, wrong-project, wrong-document, wrong-tool, or unbound requests fail closed with stable codes.
- [x] MCP `initialize` and `tools/list` expose only the allowed read/propose tools.
- [x] Context reads are bounded and delegated to the collaboration port.
- [x] A proposal is bound to `draftId + headSequenceNo + documentHash` and uses a strict command-batch envelope.
- [x] Identical proposal retries return one durable receipt; changed retries return `submission_conflict`.
- [x] No MCP tool can Apply or Publish a proposal.
- [x] Missing structured core returns `prototype_core_unavailable` and leaves the pairing/proposal state unchanged.
- [x] Unit and API tests cover the success path, scope violations, expiry/revocation, stale bases, idempotency, and unavailable-core placeholder.
- [x] Logs and audit payloads contain identities, versions, durations, hashes, and stable codes only.

## Definition of Done

- Backend domain, application service, MCP protocol, loopback transport, and focused tests pass.
- Skill bundle and platform manifests pass a deterministic package validator.
- The structured-core integration point is documented and has a contract test with a fake port.
- Relevant Ruff, mypy, and pytest checks pass in the dedicated worktree.
- No main-checkout uncommitted file is modified.

## Technical Approach

Implement an additive external collaboration boundary in new modules. A local Agent first obtains a short-lived project/document pairing capability, loads the packaged Skill, and connects to a loopback MCP endpoint. MCP tools delegate all structured-document behavior to a narrow application `Protocol`. Stable HEAD receives a fail-closed unavailable implementation; the in-flight structured-prototype branch can later supply the real adapter without changing the external protocol.

The canonical proposal origin will be `external_agent`. It must converge with the built-in UI Engineer on the same future command batch, preview, stale detection, Apply, and audit pipeline.

## Decision (ADR-lite)

**Context**: The structured prototype core and internal Claude/MCP work are changing in the main checkout, while external local-Agent collaboration is a separate compatibility and security boundary.

**Decision**: Build the external boundary in a dedicated worktree using a typed collaboration port. MVP supports Claude Code and Codex packaging, loopback pairing, read/propose permissions, and human-controlled Apply/Publish.

**Consequences**: The protocol and security behavior can be implemented and tested now. End-to-end document mutation remains intentionally unavailable until the main structured core supplies the port adapter. The placeholder fails loudly rather than using legacy HTML or a generic LLM fallback.

## Out of Scope

- Arbitrary third-party MCP installation or an MCP marketplace.
- Remote workstation ingress, public MCP endpoints, or cloud relay implementation.
- Direct Apply, Reject, Publish, or autonomous production changes by a local Agent.
- Generic Skill installation into every Agent product.
- Legacy HTML mutation or full-document replacement.
- Reimplementation of the in-flight structured prototype document, renderer, journal, or AI coordinator.

## Technical Notes

- Stable HEAD currently owns local auth in `backend/app/application/local_auth.py`, legacy prototypes in `backend/app/application/prototype_service.py`, and Skill metadata in `backend/app/application/skill_service.py`.
- The main checkout's uncommitted structured-prototype design remains authoritative for the eventual adapter, but is intentionally not copied into this branch.
- Platform packaging must keep a canonical Skill body and generate or validate thin host-specific manifests to avoid content drift.
- The external boundary, persistence, MCP handler, loopback API, audit query, Skill, manifests, and focused tests are implemented on `codex/external-prototype-agent`.
- `bootstrap.py` intentionally wires `UnavailableStructuredPrototypeCollaborationPort`. When the in-flight structured prototype core is ready, replace only that binding with its adapter; do not change the external MCP contract or grant Apply/Publish authority.
- The branch remains isolated until the structured prototype work in the main checkout is ready to reconcile. Production pairing therefore fails closed with `prototype_core_unavailable` in this branch by design.

## Research References

- [`research/local-agent-skill-mcp-compatibility.md`](research/local-agent-skill-mcp-compatibility.md) - Both hosts support a common `SKILL.md` and HTTP MCP core, but configuration scope, bearer injection, and UI metadata require host-specific manifests.

## Open Questions

- None blocking for the agreed MVP. A cloud relay and additional Agent hosts remain later product decisions.
