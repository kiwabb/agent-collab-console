import type { McpRiskLevel, McpServerCatalogEntry } from "@/lib/api/mcp";

export function resolveSelectedMcpServer(
  servers: McpServerCatalogEntry[],
  selectedId: string | null,
): McpServerCatalogEntry | null {
  if (selectedId !== null) {
    const selected = servers.find((server) => server.id === selectedId);
    if (selected) return selected;
  }
  return servers[0] ?? null;
}

export function mcpRiskTone(risk: McpRiskLevel): string {
  if (risk === "execute") return "border-error/25 bg-error/10 text-error";
  if (risk === "write") {
    return "border-status-warning/25 bg-status-warning/10 text-status-warning";
  }
  return "border-status-passed/25 bg-status-passed/10 text-status-passed";
}

export function formatMcpTimestamp(value: string | null, locale: string): string | null {
  if (value === null) return null;
  const timestamp = new Date(value);
  if (Number.isNaN(timestamp.getTime())) return value;
  return new Intl.DateTimeFormat(locale, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(timestamp);
}
