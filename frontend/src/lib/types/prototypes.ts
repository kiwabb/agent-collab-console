// AUTO-SPLIT from lib/types.ts by domain (frontend lib split).

/** A Claude-Design-style prototype under a Project (PRD 06-23). */
export interface Prototype {
  id: string;
  project_id: string;
  title: string;
  framework: string;
  current_version: number;
  source_kind: "manual" | "code";
  source_ref: string | null;
  source_hash: string | null;
  source_meta_json: string | null;
  created_at: string | null;
  updated_at: string | null;
}

/** Lightweight metadata for one prototype version (no html body). */
export interface PrototypeVersion {
  id: string;
  prototype_id: string;
  version_no: number;
  instruction: string | null;
  disk_path: string | null;
  created_at: string | null;
}

/** Detail payload for `GET /api/prototypes/:id`. */
export interface PrototypeDetail {
  prototype: Prototype;
  versions: PrototypeVersion[];
}

export type PrototypeCodeCandidateAction = "create" | "regenerate" | "skip" | "unsupported";

export interface PrototypeCodeCandidate {
  id: string;
  title: string;
  route: string;
  kind: "page" | "route" | "feature";
  framework_hint: string;
  source_paths: string[];
  primary_source_path: string;
  source_hash: string;
  source_excerpt: string;
  editable_brief: string;
  signals: string[];
  action: PrototypeCodeCandidateAction;
  prototype_id: string | null;
  unsupported_reason: string | null;
}

export interface PrototypeCodeCandidatesResponse {
  project_id: string;
  count: number;
  counts: Record<PrototypeCodeCandidateAction, number>;
  candidates: PrototypeCodeCandidate[];
}
