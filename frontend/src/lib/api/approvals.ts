// AUTO-SPLIT from lib/api.ts by domain (frontend lib split).

import { API_BASE, apiJsonRequest, apiRequestOr } from "./fetch";
import type { PendingApprovalsResponse, ResolveApprovalRequest } from "../types";

export async function resolveApproval(
  itemId: string,
  decision: string,
  feedback: string | null = null,
): Promise<unknown> {
  const body: ResolveApprovalRequest = { item_id: itemId, decision, feedback };
  return apiJsonRequest<unknown>(`${API_BASE}/codex/approvals/resolve`, "POST", body);
}
export async function getPendingApprovals(): Promise<PendingApprovalsResponse> {
  return apiRequestOr<PendingApprovalsResponse>(
    `${API_BASE}/codex/approvals/pending`,
    { pending: [] },
    { errorMessage: (status) => `getPendingApprovals failed: HTTP ${status}` },
  );
}
