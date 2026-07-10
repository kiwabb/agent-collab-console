// AUTO-SPLIT from lib/api.ts by domain (frontend lib split).

import { API_BASE, apiJsonRequest, apiRequest } from "./fetch";
import type { Prototype, PrototypeDetail } from "../types";

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
