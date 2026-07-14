// AUTO-SPLIT from lib/api.ts by domain (frontend lib split).

import { API_BASE, apiRawRequest } from "./fetch";
import { isRecord } from "../utils";
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
