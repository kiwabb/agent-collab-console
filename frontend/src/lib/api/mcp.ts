import { API_BASE, apiRequest } from "./fetch";

export type McpRiskLevel = "read" | "write" | "execute";
export type McpAvailability = "available" | "unavailable";

export interface McpToolCatalogEntry {
  id: string;
  description: string;
  risk_level: McpRiskLevel;
  input_schema: Record<string, unknown>;
  recent_call_count: number;
  error_call_count: number;
  last_called_at: string | null;
}

export interface McpServerCatalogEntry {
  id: string;
  display_name: string;
  description: string;
  owner: string;
  scope: "plan" | "task" | "project" | "system";
  protocol_version: string;
  transport: "http";
  version: string;
  availability: McpAvailability;
  active_session_count: number;
  tool_count: number;
  recent_call_count: number;
  error_call_count: number;
  last_called_at: string | null;
  tools: McpToolCatalogEntry[];
}

export interface McpRecentCall {
  id: string;
  server_id: string;
  tool_id: string;
  task_id: string | null;
  scope_id: string | null;
  status: string | null;
  duration_ms: number | null;
  created_at: string | null;
  error: string | null;
}

export interface McpCatalogResponse {
  servers: McpServerCatalogEntry[];
  recent_calls: McpRecentCall[];
  audit_window_size: number;
}

export async function getMcpCatalog(): Promise<McpCatalogResponse> {
  return apiRequest<McpCatalogResponse>(`${API_BASE}/mcp/catalog`);
}
