// AUTO-SPLIT from lib/api.ts by domain (frontend lib split).

import { API_BASE, handleResponse } from "./fetch";
import type { PendingApprovalsResponse, ResolveApprovalRequest } from "../types";

export async function resolveApproval(
  itemId: string,
  decision: string,
  feedback: string | null = null,
): Promise<unknown> {
  const body: ResolveApprovalRequest = { item_id: itemId, decision, feedback };
  const response = await fetch(`${API_BASE}/codex/approvals/resolve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return handleResponse(response);
}
export async function getPendingApprovals(): Promise<PendingApprovalsResponse> {
  const response = await fetch(`${API_BASE}/codex/approvals/pending`);
  if (!response.ok) {
    console.error(`getPendingApprovals failed: HTTP ${response.status}`);
    return { pending: [] };
  }
  return response.json();
}
