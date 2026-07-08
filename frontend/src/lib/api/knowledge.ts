// AUTO-SPLIT from lib/api.ts by domain (frontend lib split).

import { API_BASE, apiJsonRequest, apiRequest } from "./fetch";

export type KnowledgeSearchScope = "all" | "issues" | "artifacts";
export type KnowledgeSearchMode = "fts" | "semantic" | "hybrid";
export interface KnowledgeIssueHit {
  kind: "issue";
  issue_id: string;
  project_id: string | null;
  title: string;
  snippet?: string;
  score?: number;
  source?: string;
  rrf?: number;
}
export interface KnowledgeArtifactHit {
  kind: "artifact";
  artifact_id: string;
  issue_id: string;
  project_id: string | null;
  role: string;
  name: string;
  snippet?: string;
  score?: number;
  source?: string;
  rrf?: number;
}
export interface KnowledgeSearchResponse {
  issues: KnowledgeIssueHit[];
  artifacts: KnowledgeArtifactHit[];
  mode: KnowledgeSearchMode;
  query: string;
}
export async function searchKnowledge(opts: {
  q: string;
  scope?: KnowledgeSearchScope;
  projectId?: string;
  mode?: KnowledgeSearchMode;
  limit?: number;
}): Promise<KnowledgeSearchResponse> {
  const params = new URLSearchParams({ q: opts.q });
  if (opts.scope) params.set("scope", opts.scope);
  if (opts.projectId) params.set("project_id", opts.projectId);
  if (opts.mode) params.set("mode", opts.mode);
  if (typeof opts.limit === "number") params.set("limit", String(opts.limit));
  return apiRequest<KnowledgeSearchResponse>(`${API_BASE}/codex/search?${params.toString()}`);
}
export interface SimilarIssue {
  issue_id: string;
  title: string;
  project_id: string | null;
  score?: number;
  source?: string;
}
export async function getSimilarIssues(issueId: string, k = 5): Promise<SimilarIssue[]> {
  const data = await apiRequest<{ items: SimilarIssue[] }>(
    `${API_BASE}/codex/issues/${encodeURIComponent(issueId)}/similar?k=${k}`,
  );
  return data.items ?? [];
}
export interface EmbeddingStatus {
  enabled: boolean;
  model: string | null;
  provider_type: string | null;
}
export async function getEmbeddingStatus(): Promise<EmbeddingStatus> {
  return apiRequest<EmbeddingStatus>(`${API_BASE}/codex/embedding/status`);
}
export async function triggerKnowledgeReindex(projectId?: string): Promise<{
  indexed_issues: number;
  indexed_artifacts: number;
  embedded_issues: number;
  embedded_artifacts: number;
}> {
  const url = projectId
    ? `${API_BASE}/codex/index/reindex?project_id=${encodeURIComponent(projectId)}`
    : `${API_BASE}/codex/index/reindex`;
  return apiRequest<{
    indexed_issues: number;
    indexed_artifacts: number;
    embedded_issues: number;
    embedded_artifacts: number;
  }>(url, { method: "POST" });
}
export interface TeamNoteBlock {
  block_id: string;
  issue_id: string | null;
  heading: string;
  body: string;
  timestamp: string | null;
  pinned: boolean;
  deleted_at: string | null;
  distilled: boolean;
}
export interface TeamNotesResponse {
  project_id: string;
  raw_markdown: string;
  blocks: TeamNoteBlock[];
}
export async function getTeamNotes(
  projectId: string,
  includeDeleted = false,
): Promise<TeamNotesResponse> {
  const params = new URLSearchParams();
  if (includeDeleted) params.set("include_deleted", "true");
  return apiRequest<TeamNotesResponse>(
    `${API_BASE}/projects/${encodeURIComponent(projectId)}/team-notes?${params.toString()}`,
  );
}
export async function deleteTeamNotesBlock(projectId: string, blockId: string): Promise<void> {
  await apiRequest<void>(
    `${API_BASE}/projects/${encodeURIComponent(projectId)}/team-notes/${encodeURIComponent(blockId)}`,
    { method: "DELETE" },
  );
}
export async function restoreTeamNotesBlock(projectId: string, blockId: string): Promise<void> {
  await apiRequest<void>(
    `${API_BASE}/projects/${encodeURIComponent(projectId)}/team-notes/${encodeURIComponent(blockId)}/restore`,
    { method: "POST" },
  );
}
export async function pinTeamNotesBlock(
  projectId: string,
  blockId: string,
  pinned: boolean,
): Promise<void> {
  await apiJsonRequest<void>(
    `${API_BASE}/projects/${encodeURIComponent(projectId)}/team-notes/${encodeURIComponent(blockId)}/pin`,
    "POST",
    { pinned },
  );
}
