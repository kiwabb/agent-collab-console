// AUTO-SPLIT from lib/api.ts by domain (frontend lib split).

import { API_BASE, handleResponse } from "./fetch";
import type { Prototype, PrototypeCodeCandidatesResponse, PrototypeDetail } from "../types";

export async function listPrototypes(projectId: string): Promise<Prototype[]> {
  const response = await fetch(`${API_BASE}/projects/${projectId}/prototypes`);
  return handleResponse<Prototype[]>(response);
}
export async function createPrototype(
  projectId: string,
  body: { title: string; brief: string },
): Promise<Prototype> {
  const response = await fetch(`${API_BASE}/projects/${projectId}/prototypes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return handleResponse<Prototype>(response);
}
export async function getPrototype(
  prototypeId: string,
): Promise<PrototypeDetail> {
  const response = await fetch(`${API_BASE}/prototypes/${prototypeId}`);
  return handleResponse<PrototypeDetail>(response);
}
export async function getPrototypeVersion(
  prototypeId: string,
  versionNo: number,
): Promise<{ html: string; version_no: number }> {
  const response = await fetch(`${API_BASE}/prototypes/${prototypeId}/versions/${versionNo}`);
  return handleResponse<{ html: string; version_no: number }>(response);
}
export async function deletePrototype(prototypeId: string): Promise<{ deleted: string }> {
  const response = await fetch(`${API_BASE}/prototypes/${prototypeId}`, {
    method: "DELETE",
  });
  return handleResponse<{ deleted: string }>(response);
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
  const response = await fetch(
    `${API_BASE}/projects/${encodeURIComponent(projectId)}/prototypes/code-candidates`,
  );
  return handleResponse<PrototypeCodeCandidatesResponse>(response);
}

export function getGenerateFromCodeStreamUrl(projectId: string): string {
  return `${API_BASE}/projects/${encodeURIComponent(projectId)}/prototypes/generate-from-code/stream`;
}
