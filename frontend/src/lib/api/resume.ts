// Project-level resume maintenance APIs.

import { API_BASE, handleResponse } from "./fetch";

export interface ProjectResume {
  project_id: string;
  markdown: string;
  exists: boolean;
  relative_path: string;
  updated_at: string | null;
  size_bytes: number;
}

export interface ProjectResumeImport {
  project_id: string;
  markdown: string;
  source_filename: string;
  page_count: number;
  extracted_pages: number;
  size_bytes: number;
  warnings: string[];
}

export async function getProjectResume(projectId: string): Promise<ProjectResume> {
  const response = await fetch(`${API_BASE}/projects/${encodeURIComponent(projectId)}/resume`);
  return handleResponse(response);
}

export async function saveProjectResume(
  projectId: string,
  markdown: string,
): Promise<ProjectResume> {
  const response = await fetch(`${API_BASE}/projects/${encodeURIComponent(projectId)}/resume`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ markdown }),
  });
  return handleResponse(response);
}

export async function importProjectResumePdf(
  projectId: string,
  file: File,
): Promise<ProjectResumeImport> {
  const body = new FormData();
  body.set("file", file);
  const response = await fetch(
    `${API_BASE}/projects/${encodeURIComponent(projectId)}/resume/import-pdf`,
    {
      method: "POST",
      body,
    },
  );
  return handleResponse(response);
}
