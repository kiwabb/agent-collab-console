// AUTO-SPLIT from lib/api.ts by domain (frontend lib split).

import { API_BASE, handleResponse } from "./fetch";
import type { CreateSkillRequest, Skill, SkillImportResult, UpdateSkillRequest } from "../types";

export async function listSkills(
  opts: { search?: string; category?: string } = {},
): Promise<Skill[]> {
  const params = new URLSearchParams();
  if (opts.search) params.set("search", opts.search);
  if (opts.category) params.set("category", opts.category);
  const qs = params.toString();
  const response = await fetch(`${API_BASE}/skills${qs ? `?${qs}` : ""}`);
  return handleResponse(response);
}
export async function listSkillCategories(): Promise<string[]> {
  const response = await fetch(`${API_BASE}/skills/categories`);
  return handleResponse(response);
}
export async function createSkillCategory(name: string): Promise<{ name: string }> {
  const response = await fetch(`${API_BASE}/skills/categories`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  return handleResponse(response);
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
export async function createSkill(
  body: CreateSkillRequest,
): Promise<Skill> {
  const response = await fetch(`${API_BASE}/skills`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return handleResponse(response);
}
export async function updateSkill(
  skillId: string,
  body: UpdateSkillRequest,
): Promise<Skill> {
  const response = await fetch(`${API_BASE}/skills/${encodeURIComponent(skillId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return handleResponse(response);
}
export async function deleteSkill(skillId: string): Promise<{ deleted: string }> {
  const response = await fetch(`${API_BASE}/skills/${encodeURIComponent(skillId)}`, {
    method: "DELETE",
  });
  return handleResponse(response);
}
export async function importSkillsMarkdown(
  files: File[],
): Promise<SkillImportResult> {
  const fd = new FormData();
  files.forEach((f) => fd.append("files", f));
  const response = await fetch(`${API_BASE}/skills/import/md`, { method: "POST", body: fd });
  return handleResponse(response);
}
export async function importSkillsExcel(file: File): Promise<SkillImportResult> {
  const fd = new FormData();
  fd.append("file", file);
  const response = await fetch(`${API_BASE}/skills/import/excel`, { method: "POST", body: fd });
  return handleResponse(response);
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
  const response = await fetch(`${API_BASE}/skills/translate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, target }),
  });
  return handleResponse(response);
}
