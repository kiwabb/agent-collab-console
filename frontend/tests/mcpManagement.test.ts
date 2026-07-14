import test from "node:test";
import assert from "node:assert/strict";
import { readCompactSource } from "./sourceTestUtils";

import type { McpServerCatalogEntry } from "../src/lib/api/mcp";
import {
  formatMcpTimestamp,
  mcpRiskTone,
  resolveSelectedMcpServer,
} from "../src/features/settings/mcpManagement";
import { getDictionaryValue } from "../src/lib/i18n";

function server(id: string): McpServerCatalogEntry {
  return {
    id,
    display_name: id,
    description: "",
    owner: "tests",
    scope: "task",
    protocol_version: "2025-03-26",
    transport: "http",
    version: "1.0",
    availability: "available",
    active_session_count: 0,
    tool_count: 0,
    recent_call_count: 0,
    error_call_count: 0,
    last_called_at: null,
    tools: [],
  };
}

test("MCP server selection preserves a valid choice and falls back to the first server", () => {
  const servers = [server("alpha"), server("beta")];

  assert.equal(resolveSelectedMcpServer(servers, "beta")?.id, "beta");
  assert.equal(resolveSelectedMcpServer(servers, "missing")?.id, "alpha");
  assert.equal(resolveSelectedMcpServer([], null), null);
});

test("MCP risk tones distinguish read, write, and execute tools", () => {
  assert.match(mcpRiskTone("read"), /status-passed/);
  assert.match(mcpRiskTone("write"), /status-warning/);
  assert.match(mcpRiskTone("execute"), /error/);
});

test("MCP timestamps keep null and malformed boundary values explicit", () => {
  assert.equal(formatMcpTimestamp(null, "en-US"), null);
  assert.equal(formatMcpTimestamp("not-a-timestamp", "en-US"), "not-a-timestamp");
});

test("MCP settings use split API loading, stale-data error, and localized copy", () => {
  const panel = readCompactSource("features/settings/McpManagementPanel.tsx");
  const settings = readCompactSource("features/settings/SettingsPage.tsx");

  assert.match(panel, /from "@\/lib\/api\/mcp"/);
  assert.match(panel, /setCatalog\(next\)/);
  assert.doesNotMatch(panel, /setCatalog\(null\)/);
  assert.match(panel, /role="alert"/);
  assert.match(settings, /value="mcp"/);
  assert.match(settings, /<McpManagementPanel \/>/);
  assert.equal(getDictionaryValue("zh-CN", "settings.mcp.registry"), "MCP 注册中心");
  assert.equal(getDictionaryValue("en-US", "settings.mcp.registry"), "MCP Registry");
});
