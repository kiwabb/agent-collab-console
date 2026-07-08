// Project-level resume maintenance APIs.

import { API_BASE, apiJsonRequest, apiRequest } from "./fetch";

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
  return apiRequest<ProjectResume>(`${API_BASE}/projects/${encodeURIComponent(projectId)}/resume`);
}

export async function saveProjectResume(
  projectId: string,
  markdown: string,
): Promise<ProjectResume> {
  return apiJsonRequest<ProjectResume>(
    `${API_BASE}/projects/${encodeURIComponent(projectId)}/resume`,
    "PUT",
    { markdown },
  );
}

export async function importProjectResumePdf(
  projectId: string,
  file: File,
): Promise<ProjectResumeImport> {
  const body = new FormData();
  body.set("file", file);
  return apiRequest<ProjectResumeImport>(
    `${API_BASE}/projects/${encodeURIComponent(projectId)}/resume/import-pdf`,
    {
      method: "POST",
      body,
    },
  );
}
