# Unified MCP Management Center

## Goal

Provide one system-level place to discover and inspect framework-owned MCP servers and tools. Replace scattered, code-local metadata with a shared registry, and expose enough runtime and audit information to answer what MCP capabilities exist, where they are used, and whether they are healthy.

## What I Already Know

- The backend currently defines three internal HTTP MCP servers: `prototype-planning`, `project-startup`, and `structured-prototype-ai`; the first two are wired into the current runtime and the third is still unavailable at bootstrap.
- `prototype-planning` exposes `list_discovered_pages`, `register_prototype_page`, and `finalize_prototype_inventory`.
- `project-startup` exposes `save_startup_config`.
- `structured-prototype-ai` exposes `submit_prototype_assistant_outcome`.
- Both services create task- or plan-scoped in-memory sessions with bearer-like header tokens.
- The two services duplicate server metadata, protocol initialization, tool listing, JSON-RPC response helpers, and session bookkeeping patterns.
- The frontend recognizes MCP tool calls and displays their arguments/output in run timelines, but has no MCP inventory or operational view.
- The existing Settings page already manages runtime architecture and the agent catalog, so MCP management belongs in the same system configuration area.
- The startup configuration task explicitly reuses the prototype-planning MCP lifecycle, showing that more internal MCP services are likely to follow this pattern.

## Assumptions

- Phase 1 manages only framework-owned MCP servers registered by backend code.
- The registry is authoritative for descriptive metadata; runtime services remain authoritative for active session state.
- Session tokens and secret headers are never returned by management APIs or displayed in the UI.
- Management and observability failures must not silently enable an MCP service or erase previously loaded UI data.

## Requirements

- Introduce one typed MCP registry for server and tool metadata.
- Register all existing internal MCP servers and tools in that registry.
- Metadata includes stable server/tool identifiers, display names, descriptions, ownership, scope, protocol version, transport, risk level, and input schema.
- Expose a management API that returns the registry inventory and runtime summaries without secrets.
- Expose active session counts and aggregate invocation information that can be obtained reliably from current runtime state and audit records.
- Add an MCP section to system Settings with a dense server list and server detail view.
- The list shows server state, scope, tool count, active session count, recent usage, and error state.
- The detail view shows tool descriptions, risk classification, JSON input schema, runtime status, and recent calls.
- Phase 1 is read-only: server availability is reported from runtime state and cannot be changed from the browser.
- Reuse the existing audit infrastructure for durable invocation history rather than introducing a parallel log store.
- Preserve existing MCP endpoint behavior and Claude configuration payloads.
- Loading failures remain visible while previously loaded inventory stays on screen.
- All user-facing text is available in Chinese and English.

## Acceptance Criteria

- [x] The management API lists all three defined MCP servers and all five tools, including an explicit unavailable state for a descriptor without a runtime provider.
- [x] Adding a future internal MCP server requires registering typed metadata rather than creating another management-specific endpoint.
- [x] No session token, authorization header, or secret argument appears in inventory or audit API responses.
- [x] Each MCP server reports its protocol, transport, scope, risk profile, current availability, active sessions, and tool count.
- [x] Each tool exposes its description, risk level, and input schema in the detail view.
- [x] Existing prototype planning and project startup MCP tests continue to pass without behavior changes.
- [x] The Settings MCP view has explicit loading, empty, stale-data error, and success states.
- [x] Recent calls are scoped to one selected server without losing the surrounding server inventory.
- [x] Focused backend and frontend tests cover registry projection, secret exclusion, failure handling, and UI state.

## Definition of Done

- Focused backend tests pass for registry inventory and existing MCP services.
- Focused frontend tests or type-safe state tests pass for the management view.
- Relevant lint/type checks pass where justified by the touched layers.
- API, runtime registry, audit data, and frontend types remain consistent.
- Durable MCP registration and security conventions are captured in Trellis specs if warranted.

## Technical Approach

- Define immutable MCP server/tool descriptors in the application layer and assemble them through a single registry owned by application startup.
- Keep per-workflow session state inside the existing MCP service objects; expose only aggregate counters and availability through explicit runtime status providers.
- Have each MCP service use its registered descriptors when answering `initialize` and `tools/list`, eliminating metadata drift between the management API and live MCP protocol responses.
- Add a read API under the existing settings/runtime API surface rather than exposing the internal MCP transport endpoints.
- Extend existing audit categorization so MCP calls carry stable `server_id` and `tool_id` fields suitable for aggregate and recent-call projections.
- Build the UI as a Settings section with list/detail composition, not nested dashboard cards.

## Decision (ADR-lite)

**Context**: Internal MCP capabilities are increasing, but metadata, session state, and tool definitions are currently owned independently by each service. The UI can display individual calls but cannot inventory or govern the capability surface.

**Decision**: Introduce a code-owned registry plus a read-only management API and Settings UI. Keep executable service implementations and scoped session tokens in their current ownership boundaries. Defer enable/disable controls until a durable fail-closed policy model exists.

**Consequences**: Inventory and protocol metadata become consistent and extensible. Runtime summaries require explicit status providers. Arbitrary external MCP installation remains a separate security-sensitive feature.

## Expansion Sweep

- Future evolution: external MCP registration, credentials, health checks, per-project policy, and version compatibility can build on stable registry identifiers.
- Related scenarios: agent and skill catalogs should link to the MCP tools they depend on without duplicating MCP metadata.
- Failure and edge cases: registry collisions fail application startup; unknown tools fail closed; unavailable status providers show an explicit unavailable state; stale UI data remains visible after refresh failure.

## Out of Scope

- Installing, importing, or editing arbitrary third-party MCP servers.
- Storing third-party credentials or raw authorization headers.
- Manual execution of write or execute-risk tools from the management UI.
- Editing tool schemas or implementation metadata from the browser.
- Enabling or disabling MCP servers from the browser.
- Replacing project/task-scoped MCP session tokens with long-lived credentials.
- Building a marketplace, package updater, or remote MCP proxy.

## Technical Notes

- Existing services: `backend/app/application/prototype_planning_mcp.py`, `backend/app/application/project_startup_mcp.py`
- Existing transport routes: `backend/app/interfaces/sse.py`
- Existing call renderer: `frontend/src/features/runs/toolBlocks/ToolBlocks.tsx`
- Existing Settings surface: `frontend/src/features/settings/SettingsPage.tsx`
- Existing task proving lifecycle reuse: `.trellis/tasks/07-12-startup-config-claude-mcp/prd.md`
