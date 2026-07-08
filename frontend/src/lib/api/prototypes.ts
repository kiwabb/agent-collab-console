// AUTO-SPLIT from lib/api.ts by domain (frontend lib split).

import { API_BASE, apiJsonRequest, apiRequest } from "./fetch";
import type { Prototype, PrototypeCodeCandidatesResponse, PrototypeDetail } from "../types";

// Keep this in sync with the backend SSE parser bound. The scan dialog also
// imports it for textarea `maxLength`, so users see the same limit the
// EventSource URL builder applies before request dispatch.
export const MAX_CANDIDATE_QUERY_TEXT_CHARS = 1200;

export interface RuntimePrototypeEvidenceInput {
  attempted_url?: string | null;
  final_url?: string | null;
  success?: boolean;
  title?: string | null;
  viewport?: Record<string, unknown> | null;
  visible_text_excerpt?: string | null;
  structure_summary?: string | null;
  console_errors?: string[];
  screenshot_path?: string | null;
  failure_reason?: string | null;
}

export async function listPrototypes(projectId: string): Promise<Prototype[]> {
  return apiRequest<Prototype[]>(`${API_BASE}/projects/${projectId}/prototypes`);
}
export async function createPrototype(
  projectId: string,
  body: { title: string; brief: string },
): Promise<Prototype> {
  return apiJsonRequest<Prototype>(`${API_BASE}/projects/${projectId}/prototypes`, "POST", body);
}
export async function getPrototype(prototypeId: string): Promise<PrototypeDetail> {
  return apiRequest<PrototypeDetail>(`${API_BASE}/prototypes/${prototypeId}`);
}
export async function getPrototypeVersion(
  prototypeId: string,
  versionNo: number,
): Promise<{ html: string; version_no: number }> {
  return apiRequest<{ html: string; version_no: number }>(
    `${API_BASE}/prototypes/${prototypeId}/versions/${versionNo}`,
  );
}
export async function deletePrototype(prototypeId: string): Promise<{ deleted: string }> {
  return apiRequest<{ deleted: string }>(`${API_BASE}/prototypes/${prototypeId}`, {
    method: "DELETE",
  });
}
export function getPrototypeStreamUrl(prototypeId: string, instruction?: string): string {
  const base = `${API_BASE}/prototypes/${encodeURIComponent(prototypeId)}/stream`;
  if (!instruction || !instruction.trim()) return base;
  return `${base}?instruction=${encodeURIComponent(instruction)}`;
}
/**
 * SSE URL for the project-level batch regen endpoint. The stream emits
 * `batch_meta` → (per-prototype `prototype_start` / `prototype_delta*` /
 * `prototype_done` | `prototype_error`)* → `all_done` summarizing
 * `{ok, failed}`. See `PrototypeService.regenerate_all_stream` for the
 * server contract.
 */
export function getRegenerateAllStreamUrl(projectId: string): string {
  return `${API_BASE}/projects/${encodeURIComponent(projectId)}/prototypes/regenerate-all/stream`;
}

export async function listPrototypeCodeCandidates(
  projectId: string,
): Promise<PrototypeCodeCandidatesResponse> {
  return apiRequest<PrototypeCodeCandidatesResponse>(
    `${API_BASE}/projects/${encodeURIComponent(projectId)}/prototypes/code-candidates`,
  );
}

export function getGenerateFromCodeStreamUrl(
  projectId: string,
  options?: {
    candidateIds?: string[];
    instruction?: string;
    candidateInstructions?: Record<string, string>;
    candidateBriefOverrides?: Record<string, string>;
    runtimeEvidence?: Record<string, RuntimePrototypeEvidenceInput>;
    useRuntimeEvidence?: boolean;
    runtimeBaseUrl?: string;
  },
): string {
  const base = `${API_BASE}/projects/${encodeURIComponent(projectId)}/prototypes/generate-from-code/stream`;
  const params = new URLSearchParams();
  for (const candidateId of options?.candidateIds ?? []) {
    params.append("candidate_id", candidateId);
  }
  const instruction = options?.instruction?.trim();
  if (instruction) params.set("instruction", instruction);
  if (options?.useRuntimeEvidence) params.set("use_runtime_evidence", "true");
  const runtimeBaseUrl = options?.runtimeBaseUrl?.trim();
  if (runtimeBaseUrl) params.set("runtime_base_url", runtimeBaseUrl);
  for (const [candidateId, candidateInstruction] of Object.entries(
    options?.candidateInstructions ?? {},
  )) {
    const clean = candidateInstruction.trim().slice(0, MAX_CANDIDATE_QUERY_TEXT_CHARS);
    if (clean) params.append("candidate_instruction", `${candidateId}\t${clean}`);
  }
  for (const [candidateId, candidateBrief] of Object.entries(
    options?.candidateBriefOverrides ?? {},
  )) {
    const clean = candidateBrief.trim().slice(0, MAX_CANDIDATE_QUERY_TEXT_CHARS);
    if (clean) params.append("candidate_brief_override", `${candidateId}\t${clean}`);
  }
  for (const [candidateId, evidence] of Object.entries(options?.runtimeEvidence ?? {})) {
    params.append("runtime_evidence", `${candidateId}\t${JSON.stringify(evidence)}`);
  }
  const query = params.toString();
  return query ? `${base}?${query}` : base;
}
