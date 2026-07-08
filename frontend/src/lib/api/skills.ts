// AUTO-SPLIT from lib/api.ts by domain (frontend lib split).

import { API_BASE, apiJsonRequest, apiRequest } from "./fetch";
import type { CreateSkillRequest, Skill, SkillImportResult, UpdateSkillRequest } from "../types";

export async function listSkills(
  opts: { search?: string; category?: string } = {},
): Promise<Skill[]> {
  const params = new URLSearchParams();
  if (opts.search) params.set("search", opts.search);
  if (opts.category) params.set("category", opts.category);
  const qs = params.toString();
  return apiRequest<Skill[]>(`${API_BASE}/skills${qs ? `?${qs}` : ""}`);
}
export async function listSkillCategories(): Promise<string[]> {
  return apiRequest<string[]>(`${API_BASE}/skills/categories`);
}
export async function createSkillCategory(name: string): Promise<{ name: string }> {
  return apiJsonRequest<{ name: string }>(`${API_BASE}/skills/categories`, "POST", { name });
}
export async function deleteSkillCategory(name: string, force = false): Promise<void> {
  const url = new URL(
    `${API_BASE}/skills/categories/${encodeURIComponent(name)}`,
    window.location.origin,
  );
  if (force) url.searchParams.set("force", "true");
  const response = await fetch(url.toString(), { method: "DELETE" });
  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error(text || `HTTP ${response.status}`);
  }
}
export async function createSkill(body: CreateSkillRequest): Promise<Skill> {
  return apiJsonRequest<Skill>(`${API_BASE}/skills`, "POST", body);
}
export async function updateSkill(skillId: string, body: UpdateSkillRequest): Promise<Skill> {
  return apiJsonRequest<Skill>(`${API_BASE}/skills/${encodeURIComponent(skillId)}`, "PATCH", body);
}
export async function deleteSkill(skillId: string): Promise<{ deleted: string }> {
  return apiRequest<{ deleted: string }>(`${API_BASE}/skills/${encodeURIComponent(skillId)}`, {
    method: "DELETE",
  });
}
export async function importSkillsMarkdown(files: File[]): Promise<SkillImportResult> {
  const fd = new FormData();
  files.forEach((f) => fd.append("files", f));
  return apiRequest<SkillImportResult>(`${API_BASE}/skills/import/md`, {
    method: "POST",
    body: fd,
  });
}
export async function importSkillsExcel(file: File): Promise<SkillImportResult> {
  const fd = new FormData();
  fd.append("file", file);
  return apiRequest<SkillImportResult>(`${API_BASE}/skills/import/excel`, {
    method: "POST",
    body: fd,
  });
}
export async function fetchSkillContent(url: string): Promise<string> {
  const response = await fetch(`${API_BASE}/skills/proxy?url=${encodeURIComponent(url)}`);
  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error(text || `HTTP ${response.status}`);
  }
  return response.text();
}
export interface TranslateSkillResult {
  translated: string;
  target: "zh" | "en";
  truncated: boolean;
  model: string;
}
export async function translateSkillContent(
  text: string,
  target: "zh" | "en",
): Promise<TranslateSkillResult> {
  return apiJsonRequest<TranslateSkillResult>(`${API_BASE}/skills/translate`, "POST", {
    text,
    target,
  });
}
