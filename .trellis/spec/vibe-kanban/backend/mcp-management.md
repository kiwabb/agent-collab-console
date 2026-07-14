# MCP Management Contract

> Executable contracts for registering framework-owned MCP servers, exposing
> their read-only management catalog, and auditing tool outcomes without
> retaining credentials or business payloads.

## Scenario: Framework-Owned MCP Registry and Management Catalog

### 1. Scope / Trigger

- Trigger: adding or changing a framework-owned MCP server, tool schema,
  session lifecycle, management catalog field, MCP audit record, or Settings
  MCP UI.
- The registry is code-owned. Browser editing, third-party installation, and
  long-lived credential storage are separate security-sensitive features.
- An MCP implementation can exist before its runtime wiring is complete. It
  must still appear as explicitly unavailable when its descriptor is
  registered without a runtime provider.

### 2. Signatures

- Registry types:
  - `McpToolDescriptor(id, description, risk_level, input_schema)`
  - `McpServerDescriptor(id, display_name, description, owner, scope, transport, version, tools)`
  - `McpRegistry.register(descriptor, runtime)`
  - `McpRuntimeProvider.active_session_count() -> int`
- Management projection:
  - `McpManagementService.catalog() -> JsonObject`
  - `GET /api/mcp/catalog`
- MCP protocol metadata:
  - `McpServerDescriptor.protocol_tools() -> list[JsonObject]`
  - shared protocol version: `MCP_PROTOCOL_VERSION`
- Audit recorder:
  - `record_mcp_call(server_id, tool_id, scope_id, task_id, started, is_error)`
- Frontend client:
  - `getMcpCatalog() -> Promise<McpCatalogResponse>`

### 3. Contracts

- Every framework-owned MCP server has one stable descriptor. The live
  `initialize` and `tools/list` responses use that descriptor; management UI
  metadata must not be maintained in a second list.
- `McpRegistry.register(...)` runs during bootstrap. A descriptor may be
  registered with `runtime=None`, which produces:
  - `availability="unavailable"`
  - `active_session_count=0`
- A wired service implements `active_session_count()` and produces
  `availability="available"`.
- Server IDs and tool IDs are stable machine identifiers. They are used in
  audit payloads, API responses, filtering, and frontend selection.
- Tool risk is one of `read|write|execute`. Risk is visible text as well as a
  semantic color; color alone is not the status signal.
- `GET /api/mcp/catalog` returns:
  - `servers[]`: descriptor fields, availability, active sessions, recent-call
    metrics, and `tools[]`.
  - `tools[]`: `id`, `description`, `risk_level`, `input_schema`,
    `recent_call_count`, `error_call_count`, and `last_called_at`.
  - `recent_calls[]`: IDs, task/scope correlation, status, duration, timestamp,
    and a safe generic error.
  - `audit_window_size`: maximum number of recent MCP audit rows considered.
- MCP audit rows use category `tool_result`, actor `mcp:<server_id>`, and a
  payload containing only:

  ```json
  {
    "transport": "mcp",
    "server_id": "project-startup",
    "tool_id": "save_startup_config",
    "scope_id": "task-1"
  }
  ```

- Audit rows never retain MCP arguments, results, headers, session tokens, or
  authorization material. This is critical because write-tool arguments can
  contain environment values and repository-derived data.
- The Settings MCP view is read-only. A refresh failure preserves the last
  valid catalog and shows an explicit error state.
- On narrow viewports, Settings navigation becomes a top tab row and the MCP
  server list/detail layout becomes one column. The page must not create
  horizontal document overflow.

### 4. Validation & Error Matrix

- Duplicate server ID during registration -> raise `ValueError`; application
  startup fails rather than silently replacing a registration.
- Duplicate tool ID inside one server descriptor -> raise `ValueError`.
- Registered descriptor without runtime provider -> catalog succeeds with
  `availability="unavailable"`; do not claim that the MCP is callable.
- Audit store unavailable -> `GET /api/mcp/catalog` returns the existing store
  unavailability `503`; do not fabricate empty usage data.
- Malformed or legacy non-MCP `tool_result` audit payload -> ignore it for the
  MCP projection; keep the registered inventory visible.
- MCP tool result with `isError=true` -> audit `status="error"` with the safe
  generic error text, not the raw tool result.
- Catalog refresh failure after a successful frontend load -> keep stale data
  and show an error banner.
- Empty registry -> render the localized empty state, not a blank panel.

### 5. Good/Base/Bad Cases

- Good: a new MCP service defines one descriptor, uses it for `tools/list`, and
  registers it during bootstrap. The Settings page shows it without a new
  feature-specific management endpoint.
- Good: `structured-prototype-ai` is defined but not wired; the catalog shows
  its tool and marks the server unavailable.
- Good: a failed write-tool call records server/tool/scope/duration only.
- Base: a server has no audit history; its recent counts are zero and its tools
  remain inspectable.
- Bad: copying a tool schema into the management API or frontend.
- Bad: treating a missing runtime as enabled because the descriptor exists.
- Bad: serializing `arguments`, tool output, MCP headers, or session token into
  `audit_log`.
- Bad: clearing the frontend catalog when refresh fails.

### 6. Tests Required

- Registry unit: duplicate server IDs and duplicate tool IDs are rejected.
- Descriptor unit: `protocol_tools()` returns a defensive copy and matches the
  MCP `tools/list` shape.
- Management service unit: registry metadata, runtime session count, and
  redacted audit rows produce the expected catalog metrics.
- Audit recorder unit: recorded payload has only transport/server/tool/scope;
  assertions reject `arguments`, `result`, `token`, and authorization fields.
- API integration: `/api/mcp/catalog` lists every registered descriptor and
  tool, returns unavailable descriptors explicitly, and contains no credential
  keys.
- Existing MCP tests: initialize, tools/list, tools/call, scoped token refusal,
  finalization, and session close behavior remain green.
- Frontend API test: `getMcpCatalog()` calls `/api/mcp/catalog` through the
  shared split API helper.
- Frontend state test: a valid selected server is preserved; a removed server
  falls back to the first current server.
- Frontend source/i18n tests: split API import, stale-data preservation, error
  state, Settings tab wiring, and zh-CN/en-US keys remain enforced.
- Browser QA: desktop and narrow layouts, light/dark themes, server selection,
  Schema expansion, and console errors are checked.

### 7. Wrong vs Correct

#### Wrong

```python
@router.get("/mcp/catalog")
async def catalog() -> object:
    return {
        "servers": [
            {"id": "project-startup", "tools": PROJECT_STARTUP_TOOLS_COPY},
        ]
    }
```

This creates a second metadata source that will drift from MCP `tools/list`.

#### Correct

```python
PROJECT_STARTUP_MCP_DESCRIPTOR = McpServerDescriptor(...)

class ProjectStartupMcpService:
    descriptor = PROJECT_STARTUP_MCP_DESCRIPTOR

    def active_session_count(self) -> int:
        return len(self._sessions)

# bootstrap.py
mcp_registry.register(PROJECT_STARTUP_MCP_DESCRIPTOR, project_startup_mcp_service)
```

#### Wrong

```python
sink.record("tool_result", payload={"arguments": arguments, "result": result})
```

#### Correct

```python
audit.record_mcp_call(
    server_id=self.descriptor.id,
    tool_id=name,
    scope_id=state.session.task_id,
    task_id=state.session.task_id,
    started=started,
    is_error=result["isError"] is True,
)
```
