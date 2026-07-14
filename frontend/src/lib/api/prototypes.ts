// AUTO-SPLIT from lib/api.ts by domain (frontend lib split).

import { API_BASE, apiJsonRequest, apiRawRequest, apiRequest } from "./fetch";
import { isRecord } from "../utils";
import type {
  Prototype,
  PrototypeDetail,
  PrototypeGenerationRun,
  PrototypePlan,
  PrototypeProjectContext,
} from "../types";
import type {
  AppliedStructuredPrototypeCommands,
  AppliedStructuredPrototypeRuntimeEvents,
  AppliedPrototypeAiProposal,
  ApplyStructuredPrototypeCommandsRequest,
  ApplyStructuredPrototypeRuntimeEventsRequest,
  CheckpointStructuredPrototypeRuntimeSessionRequest,
  CreateStructuredPrototypeRequest,
  CreateStructuredPrototypeRuntimeSessionRequest,
  PublishedStructuredPrototype,
  PrototypeAiEditRun,
  PrototypeAiThread,
  PrototypeAiThreadSnapshot,
  PublishStructuredPrototypeRequest,
  StructuredPrototypeDraft,
  StructuredPrototypeGenerationAcceptResult,
  StructuredPrototypeGenerationJob,
  StructuredPrototypePublication,
  StructuredPrototypeRuntimeSession,
  SendPrototypeAiMessageRequest,
} from "../../features/prototype/structured/types";

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

export async function createPrototypePlan(
  projectId: string,
  globalInstruction = "",
  outputLocale: "zh-CN" | "en-US" = "zh-CN",
): Promise<{ plan_id: string; status: PrototypePlan["status"] }> {
  return apiJsonRequest(
    `${API_BASE}/projects/${encodeURIComponent(projectId)}/prototype-plans`,
    "POST",
    {
      global_instruction: globalInstruction,
      output_locale: outputLocale,
    },
  );
}

export async function getPrototypePlan(planId: string): Promise<PrototypePlan> {
  return apiRequest<PrototypePlan>(`${API_BASE}/prototype-plans/${encodeURIComponent(planId)}`);
}

export async function getLatestPrototypePlan(projectId: string): Promise<PrototypePlan | null> {
  return apiRequest<PrototypePlan | null>(
    `${API_BASE}/projects/${encodeURIComponent(projectId)}/prototype-plans/latest`,
  );
}

export async function getPrototypePlanFeatureConfig(): Promise<{ enabled: boolean }> {
  return apiRequest<{ enabled: boolean }>(`${API_BASE}/prototype-plans/config`);
}

export async function reanalyzePrototypePlan(
  planId: string,
): Promise<{ plan_id: string; status: PrototypePlan["status"] }> {
  return apiRequest(`${API_BASE}/prototype-plans/${encodeURIComponent(planId)}/reanalyze`, {
    method: "POST",
  });
}

export async function patchPrototypePlan(
  planId: string,
  body: { global_instruction?: string; project_context?: PrototypeProjectContext },
): Promise<PrototypePlan> {
  return apiJsonRequest<PrototypePlan>(
    `${API_BASE}/prototype-plans/${encodeURIComponent(planId)}`,
    "PATCH",
    body,
  );
}

export async function patchPrototypePlanItem(
  itemId: string,
  body: {
    title?: string;
    summary?: string;
    brief?: string;
    states?: string[];
    selected?: boolean;
  },
): Promise<PrototypePlan> {
  return apiJsonRequest<PrototypePlan>(
    `${API_BASE}/prototype-plan-items/${encodeURIComponent(itemId)}`,
    "PATCH",
    body,
  );
}

export async function patchPrototypePlanSelection(
  planId: string,
  body: { item_ids: string[]; selected: boolean },
): Promise<PrototypePlan> {
  return apiJsonRequest<PrototypePlan>(
    `${API_BASE}/prototype-plans/${encodeURIComponent(planId)}/selection`,
    "PATCH",
    body,
  );
}

export function getPrototypePlanEventsUrl(planId: string): string {
  return `${API_BASE}/prototype-plans/${encodeURIComponent(planId)}/events`;
}

export async function createPrototypeGenerationRun(
  planId: string,
  expectedUpdatedAt: string | null,
): Promise<{ run_id: string; status: PrototypeGenerationRun["status"] }> {
  return apiJsonRequest(
    `${API_BASE}/prototype-plans/${encodeURIComponent(planId)}/generate`,
    "POST",
    { expected_updated_at: expectedUpdatedAt },
  );
}

export async function getPrototypeGenerationRun(runId: string): Promise<PrototypeGenerationRun> {
  return apiRequest<PrototypeGenerationRun>(
    `${API_BASE}/prototype-generation-runs/${encodeURIComponent(runId)}`,
  );
}

export async function getLatestPrototypeGenerationRun(
  planId: string,
): Promise<PrototypeGenerationRun | null> {
  return apiRequest<PrototypeGenerationRun | null>(
    `${API_BASE}/prototype-plans/${encodeURIComponent(planId)}/generation-run`,
  );
}

export async function retryPrototypeGenerationRun(
  planId: string,
  runId: string,
): Promise<{ run_id: string; status: PrototypeGenerationRun["status"] }> {
  return apiJsonRequest(`${API_BASE}/prototype-plans/${encodeURIComponent(planId)}/retry`, "POST", {
    run_id: runId,
  });
}

export function getPrototypeGenerationRunEventsUrl(runId: string): string {
  return `${API_BASE}/prototype-generation-runs/${encodeURIComponent(runId)}/events`;
}

export class StructuredPrototypeApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly operationId: string | null;
  readonly correlationId: string;

  constructor(options: {
    status: number;
    code: string;
    message: string;
    operationId: string | null;
    correlationId: string;
  }) {
    const operation = options.operationId ? `; operation ${options.operationId}` : "";
    super(`${options.message} (${options.code}${operation}; correlation ${options.correlationId})`);
    this.name = "StructuredPrototypeApiError";
    this.status = options.status;
    this.code = options.code;
    this.operationId = options.operationId;
    this.correlationId = options.correlationId;
  }
}

async function structuredPrototypeRequest<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await apiRawRequest(url, init);
  if (response.ok) return (await response.json()) as T;
  let payload: unknown;
  try {
    payload = await response.json();
  } catch (error) {
    throw new Error(`Structured prototype request failed with HTTP ${response.status}`, {
      cause: error,
    });
  }
  if (!isRecord(payload)) {
    throw new Error(`Structured prototype request failed with HTTP ${response.status}`);
  }
  const detail = payload["error"];
  const operationId = payload["operationId"];
  const correlationId = payload["correlationId"];
  if (
    !isRecord(detail) ||
    typeof detail["code"] !== "string" ||
    typeof detail["message"] !== "string" ||
    (operationId !== null && typeof operationId !== "string") ||
    typeof correlationId !== "string"
  ) {
    throw new Error(`Structured prototype request failed with HTTP ${response.status}`);
  }
  throw new StructuredPrototypeApiError({
    status: response.status,
    code: detail["code"],
    message: detail["message"],
    operationId,
    correlationId,
  });
}

function structuredPrototypeJsonRequest<T>(url: string, method: "POST", body: unknown): Promise<T> {
  return structuredPrototypeRequest<T>(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function createStructuredPrototypeDocument(
  projectId: string,
  body: CreateStructuredPrototypeRequest,
): Promise<StructuredPrototypeDraft> {
  return structuredPrototypeJsonRequest<StructuredPrototypeDraft>(
    `${API_BASE}/projects/${encodeURIComponent(projectId)}/structured-prototype-documents`,
    "POST",
    body,
  );
}

export async function getCurrentStructuredPrototypeDraft(
  projectId: string,
  clientRequestId: string,
): Promise<StructuredPrototypeDraft | null> {
  const query = new URLSearchParams({ clientRequestId });
  return structuredPrototypeRequest<StructuredPrototypeDraft | null>(
    `${API_BASE}/projects/${encodeURIComponent(projectId)}/structured-prototype-documents/current?${query.toString()}`,
  );
}

export async function recoverStructuredPrototypeDraft(
  draftId: string,
  clientRequestId: string,
): Promise<StructuredPrototypeDraft> {
  const query = new URLSearchParams({ clientRequestId });
  return structuredPrototypeRequest<StructuredPrototypeDraft>(
    `${API_BASE}/structured-prototype-drafts/${encodeURIComponent(draftId)}?${query.toString()}`,
  );
}

export async function applyStructuredPrototypeCommands(
  draftId: string,
  body: ApplyStructuredPrototypeCommandsRequest,
): Promise<AppliedStructuredPrototypeCommands> {
  return structuredPrototypeJsonRequest<AppliedStructuredPrototypeCommands>(
    `${API_BASE}/structured-prototype-drafts/${encodeURIComponent(draftId)}/commands`,
    "POST",
    body,
  );
}

export async function createStructuredPrototypeRuntimeSession(
  draftId: string,
  body: CreateStructuredPrototypeRuntimeSessionRequest,
): Promise<StructuredPrototypeRuntimeSession> {
  return structuredPrototypeJsonRequest<StructuredPrototypeRuntimeSession>(
    `${API_BASE}/structured-prototype-drafts/${encodeURIComponent(draftId)}/runtime-sessions`,
    "POST",
    body,
  );
}

export async function recoverStructuredPrototypeRuntimeSession(
  sessionId: string,
  clientRequestId: string,
): Promise<StructuredPrototypeRuntimeSession> {
  const query = new URLSearchParams({ clientRequestId });
  return structuredPrototypeRequest<StructuredPrototypeRuntimeSession>(
    `${API_BASE}/structured-prototype-runtime-sessions/${encodeURIComponent(sessionId)}?${query.toString()}`,
  );
}

export async function applyStructuredPrototypeRuntimeEvents(
  sessionId: string,
  body: ApplyStructuredPrototypeRuntimeEventsRequest,
): Promise<AppliedStructuredPrototypeRuntimeEvents> {
  return structuredPrototypeJsonRequest<AppliedStructuredPrototypeRuntimeEvents>(
    `${API_BASE}/structured-prototype-runtime-sessions/${encodeURIComponent(sessionId)}/events`,
    "POST",
    body,
  );
}

export async function checkpointStructuredPrototypeRuntimeSession(
  sessionId: string,
  body: CheckpointStructuredPrototypeRuntimeSessionRequest,
): Promise<StructuredPrototypeRuntimeSession> {
  return structuredPrototypeJsonRequest<StructuredPrototypeRuntimeSession>(
    `${API_BASE}/structured-prototype-runtime-sessions/${encodeURIComponent(sessionId)}/checkpoint`,
    "POST",
    body,
  );
}

export async function publishStructuredPrototypeDraft(
  draftId: string,
  body: PublishStructuredPrototypeRequest,
): Promise<PublishedStructuredPrototype> {
  return structuredPrototypeJsonRequest<PublishedStructuredPrototype>(
    `${API_BASE}/structured-prototype-drafts/${encodeURIComponent(draftId)}/publish`,
    "POST",
    body,
  );
}

export async function getStructuredPrototypePublication(
  documentId: string,
): Promise<StructuredPrototypePublication | null> {
  return structuredPrototypeRequest<StructuredPrototypePublication | null>(
    `${API_BASE}/structured-prototype-documents/${encodeURIComponent(documentId)}/published`,
  );
}

export class StructuredPrototypeGenerationApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly jobId: string | null;
  readonly correlationId: string;

  constructor(options: {
    status: number;
    code: string;
    message: string;
    jobId: string | null;
    correlationId: string;
  }) {
    super(`${options.message} (${options.code}; correlation ${options.correlationId})`);
    this.name = "StructuredPrototypeGenerationApiError";
    this.status = options.status;
    this.code = options.code;
    this.jobId = options.jobId;
    this.correlationId = options.correlationId;
  }
}

async function structuredPrototypeGenerationRequest<T>(
  url: string,
  init?: RequestInit,
): Promise<T> {
  const response = await apiRawRequest(url, init);
  if (response.ok) return (await response.json()) as T;
  let payload: unknown;
  try {
    payload = await response.json();
  } catch (error) {
    throw new Error(`Structured prototype generation failed with HTTP ${response.status}`, {
      cause: error,
    });
  }
  const detail = isRecord(payload) ? payload["error"] : null;
  const correlationId = isRecord(payload) ? payload["correlationId"] : null;
  if (
    !isRecord(detail) ||
    typeof detail["code"] !== "string" ||
    typeof detail["message"] !== "string" ||
    (detail["jobId"] !== null && typeof detail["jobId"] !== "string") ||
    typeof correlationId !== "string"
  ) {
    throw new Error(`Structured prototype generation failed with HTTP ${response.status}`);
  }
  throw new StructuredPrototypeGenerationApiError({
    status: response.status,
    code: detail["code"],
    message: detail["message"],
    jobId: detail["jobId"],
    correlationId,
  });
}

function structuredPrototypeGenerationJsonRequest<T>(url: string, body: unknown): Promise<T> {
  return structuredPrototypeGenerationRequest<T>(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function createStructuredPrototypeGenerationJob(
  projectId: string,
  body: { contractVersion: 1; clientRequestId: string; mode: "requirements"; brief: string },
): Promise<StructuredPrototypeGenerationJob> {
  return structuredPrototypeGenerationJsonRequest<StructuredPrototypeGenerationJob>(
    `${API_BASE}/projects/${encodeURIComponent(projectId)}/prototype-document-generation-jobs`,
    body,
  );
}

export async function getCurrentStructuredPrototypeGenerationJob(
  projectId: string,
): Promise<StructuredPrototypeGenerationJob | null> {
  return structuredPrototypeGenerationRequest<StructuredPrototypeGenerationJob | null>(
    `${API_BASE}/projects/${encodeURIComponent(projectId)}/prototype-document-generation-jobs/current`,
  );
}

export async function getStructuredPrototypeGenerationJob(
  jobId: string,
): Promise<StructuredPrototypeGenerationJob> {
  return structuredPrototypeGenerationRequest<StructuredPrototypeGenerationJob>(
    `${API_BASE}/prototype-document-generation-jobs/${encodeURIComponent(jobId)}`,
  );
}

export async function confirmStructuredPrototypeGenerationBlueprint(
  jobId: string,
  body: { contractVersion: 1; clientRequestId: string; expectedBlueprintHash: string },
): Promise<StructuredPrototypeGenerationJob> {
  return structuredPrototypeGenerationJsonRequest<StructuredPrototypeGenerationJob>(
    `${API_BASE}/prototype-document-generation-jobs/${encodeURIComponent(jobId)}/confirm`,
    body,
  );
}

export async function acceptStructuredPrototypeGenerationCandidate(
  jobId: string,
  body: {
    contractVersion: 1;
    clientRequestId: string;
    expectedCandidateObjectHash: string;
    expectedPreviewOutputHash: string;
  },
): Promise<StructuredPrototypeGenerationAcceptResult> {
  return structuredPrototypeGenerationJsonRequest<StructuredPrototypeGenerationAcceptResult>(
    `${API_BASE}/prototype-document-generation-jobs/${encodeURIComponent(jobId)}/accept`,
    body,
  );
}

export class StructuredPrototypeAiApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly runId: string | null;
  readonly correlationId: string;

  constructor(options: {
    status: number;
    code: string;
    message: string;
    runId: string | null;
    correlationId: string;
  }) {
    super(`${options.message} (${options.code}; correlation ${options.correlationId})`);
    this.name = "StructuredPrototypeAiApiError";
    this.status = options.status;
    this.code = options.code;
    this.runId = options.runId;
    this.correlationId = options.correlationId;
  }
}

async function structuredPrototypeAiRequest<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await apiRawRequest(url, init);
  if (response.ok) return (await response.json()) as T;
  let payload: unknown;
  try {
    payload = await response.json();
  } catch (error) {
    throw new Error(`Structured prototype AI request failed with HTTP ${response.status}`, {
      cause: error,
    });
  }
  if (!isRecord(payload)) {
    throw new Error(`Structured prototype AI request failed with HTTP ${response.status}`);
  }
  const detail = payload["error"];
  const correlationId = payload["correlationId"];
  if (
    !isRecord(detail) ||
    typeof detail["code"] !== "string" ||
    typeof detail["message"] !== "string" ||
    (detail["runId"] !== null && typeof detail["runId"] !== "string") ||
    typeof correlationId !== "string"
  ) {
    throw new Error(`Structured prototype AI request failed with HTTP ${response.status}`);
  }
  throw new StructuredPrototypeAiApiError({
    status: response.status,
    code: detail["code"],
    message: detail["message"],
    runId: detail["runId"],
    correlationId,
  });
}

function structuredPrototypeAiJsonRequest<T>(url: string, body: unknown): Promise<T> {
  return structuredPrototypeAiRequest<T>(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function createPrototypeAiThread(
  documentId: string,
  body: { contractVersion: 1; clientRequestId: string; title: string },
): Promise<PrototypeAiThread> {
  return structuredPrototypeAiJsonRequest<PrototypeAiThread>(
    `${API_BASE}/prototype-documents/${encodeURIComponent(documentId)}/ai-threads`,
    body,
  );
}

export async function listPrototypeAiThreads(documentId: string): Promise<PrototypeAiThread[]> {
  return structuredPrototypeAiRequest<PrototypeAiThread[]>(
    `${API_BASE}/prototype-documents/${encodeURIComponent(documentId)}/ai-threads`,
  );
}

export async function getPrototypeAiThread(threadId: string): Promise<PrototypeAiThreadSnapshot> {
  return structuredPrototypeAiRequest<PrototypeAiThreadSnapshot>(
    `${API_BASE}/prototype-ai-threads/${encodeURIComponent(threadId)}`,
  );
}

export async function sendPrototypeAiMessage(
  threadId: string,
  body: SendPrototypeAiMessageRequest,
): Promise<PrototypeAiEditRun> {
  return structuredPrototypeAiJsonRequest<PrototypeAiEditRun>(
    `${API_BASE}/prototype-ai-threads/${encodeURIComponent(threadId)}/messages`,
    body,
  );
}

export async function getPrototypeAiEditRun(runId: string): Promise<PrototypeAiEditRun> {
  return structuredPrototypeAiRequest<PrototypeAiEditRun>(
    `${API_BASE}/prototype-ai-edit-runs/${encodeURIComponent(runId)}`,
  );
}

export async function applyPrototypeAiProposal(
  runId: string,
  body: {
    contractVersion: 1;
    clientRequestId: string;
    expectedHeadSequenceNo: number;
    expectedDocumentHash: string;
  },
): Promise<AppliedPrototypeAiProposal> {
  return structuredPrototypeAiJsonRequest<AppliedPrototypeAiProposal>(
    `${API_BASE}/prototype-ai-edit-runs/${encodeURIComponent(runId)}/apply`,
    body,
  );
}

export async function rejectPrototypeAiProposal(
  runId: string,
  body: { contractVersion: 1; clientRequestId: string },
): Promise<PrototypeAiEditRun> {
  return structuredPrototypeAiJsonRequest<PrototypeAiEditRun>(
    `${API_BASE}/prototype-ai-edit-runs/${encodeURIComponent(runId)}/reject`,
    body,
  );
}
