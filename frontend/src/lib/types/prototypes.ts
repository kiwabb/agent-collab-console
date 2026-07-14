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

export type PrototypePlanStatus =
  "queued" | "analyzing" | "ready" | "analysis_failed" | "stale" | "interrupted";
export type PrototypePlanConfidence = "high" | "medium" | "low";
export type PrototypePlanDiscoveryOrigin = "static" | "claude";
export type PrototypePlanReviewStatus = "provisional" | "confirmed" | "needs_confirmation";
export type PrototypePlanEvidenceKind =
  | "react-router-route"
  | "vue-router-route"
  | "file-route"
  | "page-directory"
  | "page-source"
  | "layout"
  | "style"
  | "parser";
export type PrototypePlanAction = "create" | "update" | "unchanged" | "missing" | "unsupported";
export type PrototypePlanOutputLocale = "zh-CN" | "en-US";
export type PrototypePlanSurfaceKind =
  "web" | "desktop" | "browser-extension" | "mobile" | "unknown";
export type PrototypePlanAnalysisPhase =
  "queued" | "scanning" | "planning" | "validating" | "complete" | "stale" | "failed";

export interface PrototypeProjectContext {
  product_summary: string;
  audience: string;
  visual_language: string;
  shared_layout: string;
}

export interface PrototypePlanScope {
  packages: string[];
  supported_packages: string[];
  candidate_count: number;
}

export interface PrototypePlanEvidence {
  evidence_id: string;
  kind: PrototypePlanEvidenceKind;
  path: string;
  start_line: number;
  end_line: number;
  detail: string;
  content: string;
  confidence: PrototypePlanConfidence;
  diagnostic: string | null;
}

export interface PrototypePlanItem {
  id: string;
  plan_id: string;
  candidate_id: string;
  package_root: string;
  surface_kind: PrototypePlanSurfaceKind;
  route_patterns: string[];
  primary_source_path: string | null;
  source_paths: string[];
  layout_paths: string[];
  title: string;
  summary: string;
  brief: string;
  states: string[];
  evidence_ids: string[];
  evidence: PrototypePlanEvidence[];
  confidence: PrototypePlanConfidence;
  action: PrototypePlanAction;
  selected: boolean;
  source_hash: string;
  discovery_origin: PrototypePlanDiscoveryOrigin;
  review_status: PrototypePlanReviewStatus;
  prototype_id: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface PrototypePlan {
  contract_version: 1;
  id: string;
  project_id: string;
  status: PrototypePlanStatus;
  repository_fingerprint: string;
  scope: PrototypePlanScope;
  project_context: PrototypeProjectContext;
  global_instruction: string;
  output_locale: PrototypePlanOutputLocale;
  analysis_phase: PrototypePlanAnalysisPhase;
  analysis_completed: number;
  analysis_total: number;
  diagnostics: string[];
  error_message: string | null;
  created_at: string | null;
  updated_at: string | null;
  items: PrototypePlanItem[];
}

export type PrototypeGenerationRunStatus =
  "queued" | "running" | "completed" | "partial" | "failed" | "interrupted";
export type PrototypeGenerationItemStatus =
  "pending" | "generating" | "done" | "failed" | "interrupted" | "skipped";
export type PrototypeGenerationItemPhase =
  | "queued"
  | "starting"
  | "streaming"
  | "persisting"
  | "completed"
  | "failed"
  | "interrupted"
  | "skipped";

export interface PrototypeGenerationRunItem {
  id: string;
  run_id: string;
  plan_item_id: string;
  prototype_id: string | null;
  status: PrototypeGenerationItemStatus;
  title: string;
  attempt: number;
  phase: PrototypeGenerationItemPhase;
  output_chars: number;
  last_event_at: string | null;
  status_message: string;
  task_id: string | null;
  execution_process_id: string | null;
  error_message: string | null;
  version_no: number | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface PrototypeGenerationRun {
  contract_version: 1;
  id: string;
  plan_id: string;
  project_id: string;
  status: PrototypeGenerationRunStatus;
  repository_fingerprint: string;
  total: number;
  processed: number;
  succeeded: number;
  running: number;
  pending: number;
  /** Compatibility alias from the original run contract; equals `succeeded`. */
  completed: number;
  failed: number;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string | null;
  updated_at: string | null;
  items: PrototypeGenerationRunItem[];
}

export interface PrototypeStreamHeartbeat {
  contract_version: 1;
  resource_id: string;
  sent_at: string;
}
