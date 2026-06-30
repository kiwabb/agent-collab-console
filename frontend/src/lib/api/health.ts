// AUTO-SPLIT from lib/api.ts by domain (frontend lib split).

import { API_BASE, WS_BASE } from "./fetch";
import type { HealthResponse } from "../types";

export async function checkBackendHealth(): Promise<HealthResponse> {
  const response = await fetch(`${API_BASE}/health`);
  if (!response.ok) {
    throw new Error(`Backend unreachable: HTTP ${response.status}`);
  }
  const data = await response.json();
  if (data.service !== "agent-collab-console") {
    throw new Error(`Wrong backend: ${data.service}`);
  }
  return data;
}
export async function getCodexStatus(): Promise<unknown> {
  const response = await fetch(`${API_BASE}/codex/status`);
  if (!response.ok) {
    throw new Error(`Failed to get Codex status: HTTP ${response.status}`);
  }
  return response.json();
}
export function getGlobalEventsStreamUrl(lastEventId?: string | null): string {
  const sp = new URLSearchParams();
  if (lastEventId) sp.set("last_event_id", lastEventId);
  const suffix = sp.size > 0 ? `?${sp.toString()}` : "";
  return `${WS_BASE}/api/ws/events${suffix}`;
}
