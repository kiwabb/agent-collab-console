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
  DeleteStructuredPrototypeResult,
  MutateStructuredPrototypeHistoryRequest,
  PublishedStructuredPrototype,
  PrototypeAiEditRun,
  PrototypeAiThread,
  PrototypeAiThreadSnapshot,
  PublishStructuredPrototypeRequest,
  ResetStructuredPrototypeRuntimeSessionRequest,
  RollbackStructuredPrototypeRequest,
  RolledBackStructuredPrototype,
  StructuredPrototypeDraft,
  StructuredPrototypeGenerationAcceptResult,
  StructuredPrototypeGenerationConfirmResult,
  StructuredPrototypeGenerationJob,
  StructuredPrototypePublication,
  StructuredPrototypeRevisionDiff,
  StructuredPrototypeRevisionHistory,
  StructuredPrototypeRuntimeSession,
  SendPrototypeAiMessageRequest,
} from "../../features/prototype/structured/types";

export class StructuredPrototypeApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly retryable: boolean;
  readonly operationId: string | null;
  readonly correlationId: string;
  readonly currentHeadSequenceNo: number | null;
  readonly currentStateHash: string | null;
  readonly currentViewModelHash: string | null;
  readonly currentRuntimeCoreBundleHash: string | null;
  readonly resourceUrl: string | null;

  constructor(options: {
    status: number;
    code: string;
    message: string;
    retryable: boolean;
    operationId: string | null;
    correlationId: string;
    currentHeadSequenceNo?: number | null;
    currentStateHash?: string | null;
    currentViewModelHash?: string | null;
    currentRuntimeCoreBundleHash?: string | null;
    resourceUrl?: string | null;
  }) {
    const operation = options.operationId ? `; operation ${options.operationId}` : "";
    super(`${options.message} (${options.code}${operation}; correlation ${options.correlationId})`);
    this.name = "StructuredPrototypeApiError";
    this.status = options.status;
    this.code = options.code;
    this.retryable = options.retryable;
    this.operationId = options.operationId;
    this.correlationId = options.correlationId;
    this.currentHeadSequenceNo = options.currentHeadSequenceNo ?? null;
    this.currentStateHash = options.currentStateHash ?? null;
    this.currentViewModelHash = options.currentViewModelHash ?? null;
    this.currentRuntimeCoreBundleHash = options.currentRuntimeCoreBundleHash ?? null;
    this.resourceUrl = options.resourceUrl ?? null;
  }
}

const STRUCTURED_PROTOTYPE_ERROR_HASH_PATTERN = /^sha256:[0-9a-f]{64}$/u;

function structuredPrototypeErrorNullableInteger(
  detail: Record<string, unknown>,
  field: string,
): number | null {
  const value = detail[field];
  if (value === undefined || value === null) return null;
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) {
    throw new Error(`Structured prototype error ${field} must be null or a non-negative integer`);
  }
  return value;
}

function structuredPrototypeErrorNullableHash(
  detail: Record<string, unknown>,
  field: string,
): string | null {
  const value = detail[field];
  if (value === undefined || value === null) return null;
  if (typeof value !== "string" || !STRUCTURED_PROTOTYPE_ERROR_HASH_PATTERN.test(value)) {
    throw new Error(`Structured prototype error ${field} must be null or a SHA-256 hash`);
  }
  return value;
}

function structuredPrototypeErrorNullableString(
  detail: Record<string, unknown>,
  field: string,
): string | null {
  const value = detail[field];
  if (value === undefined || value === null) return null;
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`Structured prototype error ${field} must be null or a non-empty string`);
  }
  return value;
}

export function isTerminalRetryableStructuredPrototypeError(
  error: unknown,
): error is StructuredPrototypeApiError {
  // In-progress retries must keep their ID so they can recover the original operation result.
  return (
    error instanceof StructuredPrototypeApiError &&
    error.retryable &&
    error.code !== "operation_in_progress"
  );
}

export function isTerminalStructuredPrototypeOperationError(
  error: unknown,
): error is StructuredPrototypeApiError {
  return error instanceof StructuredPrototypeApiError && error.code !== "operation_in_progress";
}

export const STRUCTURED_PROTOTYPE_REQUEST_DEADLINE_MS = 30_000;

export interface StructuredPrototypeRequestOptions {
  deadlineMs?: number;
  signal?: AbortSignal | null;
}

export class StructuredPrototypeRequestDeadlineError extends Error {
  readonly deadlineMs: number;

  constructor(deadlineMs: number, cause: unknown) {
    super(`Structured prototype request exceeded its ${deadlineMs}ms deadline`, { cause });
    this.name = "StructuredPrototypeRequestDeadlineError";
    this.deadlineMs = deadlineMs;
  }
}

export async function runStructuredPrototypeRequestWithDeadline<T>(
  request: (signal: AbortSignal) => Promise<T>,
  options: StructuredPrototypeRequestOptions = {},
): Promise<T> {
  const deadlineMs = options.deadlineMs ?? STRUCTURED_PROTOTYPE_REQUEST_DEADLINE_MS;
  if (!Number.isSafeInteger(deadlineMs) || deadlineMs <= 0) {
    throw new RangeError("Structured prototype request deadline must be a positive integer");
  }
  const controller = new AbortController();
  let deadlineReached = false;
  const upstreamSignal = options.signal;
  const abortFromUpstream = () => controller.abort(upstreamSignal?.reason);
  if (upstreamSignal?.aborted) abortFromUpstream();
  else upstreamSignal?.addEventListener("abort", abortFromUpstream, { once: true });
  const timer = setTimeout(() => {
    deadlineReached = true;
    controller.abort();
  }, deadlineMs);
  try {
    return await request(controller.signal);
  } catch (error) {
    if (deadlineReached) {
      throw new StructuredPrototypeRequestDeadlineError(deadlineMs, error);
    }
    throw error;
  } finally {
    clearTimeout(timer);
    upstreamSignal?.removeEventListener("abort", abortFromUpstream);
  }
}

async function structuredPrototypeRequest<T>(
  url: string,
  init?: RequestInit,
  options: StructuredPrototypeRequestOptions = {},
): Promise<T> {
  const upstreamSignal = options.signal ?? init?.signal;
  const deadlineOptions: StructuredPrototypeRequestOptions =
    upstreamSignal === undefined ? options : { ...options, signal: upstreamSignal };
  return runStructuredPrototypeRequestWithDeadline(async (signal) => {
    const response = await apiRawRequest(url, { ...init, signal });
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
      typeof detail["retryable"] !== "boolean" ||
      (operationId !== null && typeof operationId !== "string") ||
      typeof correlationId !== "string"
    ) {
      throw new Error(`Structured prototype request failed with HTTP ${response.status}`);
    }
    throw new StructuredPrototypeApiError({
      status: response.status,
      code: detail["code"],
      message: detail["message"],
      retryable: detail["retryable"],
      operationId,
      correlationId,
      currentHeadSequenceNo: structuredPrototypeErrorNullableInteger(
        detail,
        "currentHeadSequenceNo",
      ),
      currentStateHash: structuredPrototypeErrorNullableHash(detail, "currentStateHash"),
      currentViewModelHash: structuredPrototypeErrorNullableHash(detail, "currentViewModelHash"),
      currentRuntimeCoreBundleHash: structuredPrototypeErrorNullableHash(
        detail,
        "runtimeCoreBundleHash",
      ),
      resourceUrl: structuredPrototypeErrorNullableString(detail, "resourceUrl"),
    });
  }, deadlineOptions);
}

function structuredPrototypeJsonRequest<T>(url: string, method: "POST", body: unknown): Promise<T> {
  return structuredPrototypeRequest<T>(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export const STRUCTURED_PROTOTYPE_OPERATION_KINDS = [
  "create_document",
  "apply_command_batch",
  "undo",
  "redo",
  "create_checkpoint",
  "recover_draft",
  "delete_project_prototype",
  "generation_job",
  "generation_item",
  "ai_edit",
  "reject_ai_proposal",
  "semantic_repair",
  "render_preview",
  "publish",
  "create_runtime_session",
  "reset_runtime_session",
  "apply_runtime_event",
  "replay_runtime_session",
  "gc_run",
  "diagnostic_replay",
] as const;

export type StructuredPrototypeOperationKind =
  (typeof STRUCTURED_PROTOTYPE_OPERATION_KINDS)[number];

export const STRUCTURED_PROTOTYPE_OPERATION_STATUSES = [
  "queued",
  "running",
  "succeeded",
  "failed",
  "interrupted",
  "cancelled",
] as const;

export type StructuredPrototypeOperationStatus =
  (typeof STRUCTURED_PROTOTYPE_OPERATION_STATUSES)[number];

export interface StructuredPrototypeOperationOutcome {
  contractVersion: 1;
  known: true;
  terminal: boolean;
  operationId: string;
  operationKind: StructuredPrototypeOperationKind;
  projectId: string;
  resourceKind: string;
  resourceId: string | null;
  clientRequestId: string;
  correlationId: string;
  parentOperationId: string | null;
  status: StructuredPrototypeOperationStatus;
  phase: string;
  attempt: number;
  requestManifestHash: string;
  configManifestHash: string;
  resultManifestHash: string | null;
  failureEvidenceHash: string | null;
  errorCode: string | null;
  createdAt: string;
  startedAt: string | null;
  completedAt: string | null;
}

export const STRUCTURED_PROTOTYPE_OPERATION_STEP_STATUSES = [
  "pending",
  "running",
  "succeeded",
  "failed",
  "skipped",
  "interrupted",
] as const;

export type StructuredPrototypeOperationStepStatus =
  (typeof STRUCTURED_PROTOTYPE_OPERATION_STEP_STATUSES)[number];

export const STRUCTURED_PROTOTYPE_OPERATION_EVENT_STATUSES = [
  "queued",
  "pending",
  "running",
  "succeeded",
  "failed",
  "skipped",
  "interrupted",
  "cancelled",
] as const;

export type StructuredPrototypeOperationEventStatus =
  (typeof STRUCTURED_PROTOTYPE_OPERATION_EVENT_STATUSES)[number];

export interface StructuredPrototypeOperationStep {
  id: string;
  operationId: string;
  parentStepId: string | null;
  stepKind: string;
  stepOrdinal: number;
  attempt: number;
  status: StructuredPrototypeOperationStepStatus;
  phase: string;
  inputManifestHash: string;
  configManifestHash: string;
  outputManifestHash: string | null;
  completionEvidenceKind: string | null;
  completionEvidenceRef: string | null;
  errorCode: string | null;
  startedAt: string | null;
  completedAt: string | null;
}

export interface StructuredPrototypeOperationEvent {
  operationId: string;
  eventNo: number;
  stepId: string | null;
  eventKind: string;
  status: StructuredPrototypeOperationEventStatus;
  phase: string;
  inputHash: string | null;
  outputHash: string | null;
  evidenceHash: string | null;
  errorCode: string | null;
  occurredAt: string;
}

export interface StructuredPrototypeReplayManifestVersions {
  serviceVersion: string;
  documentSchemaVersion: number;
  commandContractVersion: number;
  runtimeStateSchemaVersion: number;
  runtimeEventContractVersion: number;
  runtimeCoreVersion: string | null;
  runtimeCoreBundleHash: string | null;
  stateMachineKernelVersion: string | null;
  rendererVersion: string | null;
  rendererEnvironmentVersion: string | null;
  replayManifestVersion: 1;
}

export interface StructuredPrototypeReplayManifest {
  manifestVersion: 1;
  operationId: string;
  operationKind: StructuredPrototypeOperationKind;
  parentOperationId: string | null;
  requestManifestHash: string;
  contextManifestHash: string | null;
  orderedInputObjectHashes: string[];
  versions: StructuredPrototypeReplayManifestVersions;
  agentTaskIdentity: Record<string, string> | null;
  submissionHash: string | null;
  orderedCommandBatchHashes: string[];
  baseCheckpointHash: string | null;
  baseSequenceNo: number | null;
  resultCheckpointHash: string | null;
  resultSequenceNo: number | null;
  rendererInputHash: string | null;
  rendererOutputHash: string | null;
  runtimeSessionId: string | null;
  runtimeCoreBundleHash: string | null;
  orderedRuntimeEventHashes: string[];
  runtimeFinalStateHash: string | null;
  runtimeFinalViewModelHash: string | null;
  validationReportHashes: string[];
  terminalStatus: "succeeded";
  errorCode: null;
}

export interface StructuredPrototypeOperationDetail {
  contractVersion: 1;
  operation: StructuredPrototypeOperationOutcome;
  steps: StructuredPrototypeOperationStep[];
  childOperationIds: string[];
  replayManifest: StructuredPrototypeReplayManifest | null;
}

export interface StructuredPrototypeOperationEvents {
  contractVersion: 1;
  operationId: string;
  events: StructuredPrototypeOperationEvent[];
}

const STRUCTURED_PROTOTYPE_OPERATION_OUTCOME_KEYS = [
  "contractVersion",
  "known",
  "terminal",
  "operationId",
  "operationKind",
  "projectId",
  "resourceKind",
  "resourceId",
  "clientRequestId",
  "correlationId",
  "parentOperationId",
  "status",
  "phase",
  "attempt",
  "requestManifestHash",
  "configManifestHash",
  "resultManifestHash",
  "failureEvidenceHash",
  "errorCode",
  "createdAt",
  "startedAt",
  "completedAt",
] as const;
const STRUCTURED_PROTOTYPE_UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/u;
const STRUCTURED_PROTOTYPE_HASH_PATTERN = /^sha256:[0-9a-f]{64}$/u;
const STRUCTURED_PROTOTYPE_ISO_TIMESTAMP_PATTERN =
  /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/u;

function operationOutcomeString(
  value: Record<string, unknown>,
  field: (typeof STRUCTURED_PROTOTYPE_OPERATION_OUTCOME_KEYS)[number],
): string {
  return operationObservabilityString(value, field, "Structured prototype operation outcome");
}

function operationOutcomeNullableString(
  value: Record<string, unknown>,
  field: (typeof STRUCTURED_PROTOTYPE_OPERATION_OUTCOME_KEYS)[number],
): string | null {
  return operationObservabilityNullableString(
    value,
    field,
    "Structured prototype operation outcome",
  );
}

function operationOutcomeUuid(
  value: Record<string, unknown>,
  field: (typeof STRUCTURED_PROTOTYPE_OPERATION_OUTCOME_KEYS)[number],
): string {
  return operationObservabilityUuid(value, field, "Structured prototype operation outcome");
}

function operationOutcomeNullableUuid(
  value: Record<string, unknown>,
  field: (typeof STRUCTURED_PROTOTYPE_OPERATION_OUTCOME_KEYS)[number],
): string | null {
  return operationObservabilityNullableUuid(value, field, "Structured prototype operation outcome");
}

function operationOutcomeHash(
  value: Record<string, unknown>,
  field: (typeof STRUCTURED_PROTOTYPE_OPERATION_OUTCOME_KEYS)[number],
): string {
  return operationObservabilityHash(value, field, "Structured prototype operation outcome");
}

function operationOutcomeNullableHash(
  value: Record<string, unknown>,
  field: (typeof STRUCTURED_PROTOTYPE_OPERATION_OUTCOME_KEYS)[number],
): string | null {
  return operationObservabilityNullableHash(value, field, "Structured prototype operation outcome");
}

function operationOutcomeTimestamp(
  value: Record<string, unknown>,
  field: (typeof STRUCTURED_PROTOTYPE_OPERATION_OUTCOME_KEYS)[number],
): string {
  return operationObservabilityTimestamp(value, field, "Structured prototype operation outcome");
}

function operationOutcomeNullableTimestamp(
  value: Record<string, unknown>,
  field: (typeof STRUCTURED_PROTOTYPE_OPERATION_OUTCOME_KEYS)[number],
): string | null {
  return operationObservabilityNullableTimestamp(
    value,
    field,
    "Structured prototype operation outcome",
  );
}

export function parseStructuredPrototypeOperationOutcome(
  value: unknown,
): StructuredPrototypeOperationOutcome {
  if (!isRecord(value)) throw new Error("Structured prototype operation outcome must be an object");
  const expectedKeys = new Set<string>(STRUCTURED_PROTOTYPE_OPERATION_OUTCOME_KEYS);
  for (const key of Object.keys(value)) {
    if (!expectedKeys.has(key)) {
      throw new Error(`Structured prototype operation outcome contains unknown field ${key}`);
    }
  }
  for (const key of STRUCTURED_PROTOTYPE_OPERATION_OUTCOME_KEYS) {
    if (!Object.hasOwn(value, key)) {
      throw new Error(`Structured prototype operation outcome is missing field ${key}`);
    }
  }
  if (value["contractVersion"] !== 1 || value["known"] !== true) {
    throw new Error("Structured prototype operation outcome contract is unsupported");
  }
  const operationKind = value["operationKind"];
  if (
    typeof operationKind !== "string" ||
    !STRUCTURED_PROTOTYPE_OPERATION_KINDS.includes(
      operationKind as StructuredPrototypeOperationKind,
    )
  ) {
    throw new Error("Structured prototype operation outcome kind is unsupported");
  }
  const status = value["status"];
  if (
    typeof status !== "string" ||
    !STRUCTURED_PROTOTYPE_OPERATION_STATUSES.includes(status as StructuredPrototypeOperationStatus)
  ) {
    throw new Error("Structured prototype operation outcome status is unsupported");
  }
  const terminal = value["terminal"];
  if (typeof terminal !== "boolean") {
    throw new Error("Structured prototype operation outcome terminal must be a boolean");
  }
  const terminalFromStatus = ["succeeded", "failed", "interrupted", "cancelled"].includes(status);
  if (terminal !== terminalFromStatus) {
    throw new Error("Structured prototype operation outcome terminal disagrees with status");
  }
  const attempt = value["attempt"];
  if (typeof attempt !== "number" || !Number.isSafeInteger(attempt) || attempt < 1) {
    throw new Error("Structured prototype operation outcome attempt must be a positive integer");
  }
  const resultManifestHash = operationOutcomeNullableHash(value, "resultManifestHash");
  const failureEvidenceHash = operationOutcomeNullableHash(value, "failureEvidenceHash");
  const errorCode = operationOutcomeNullableString(value, "errorCode");
  const startedAt = operationOutcomeNullableTimestamp(value, "startedAt");
  const completedAt = operationOutcomeNullableTimestamp(value, "completedAt");
  if (status === "queued" && (startedAt !== null || completedAt !== null)) {
    throw new Error("Queued structured prototype operation outcome cannot have lifecycle times");
  }
  if (status === "running" && (startedAt === null || completedAt !== null)) {
    throw new Error("Running structured prototype operation outcome has invalid lifecycle times");
  }
  if (terminal && completedAt === null) {
    throw new Error("Terminal structured prototype operation outcome requires completedAt");
  }
  if (
    (status === "queued" || status === "running") &&
    (resultManifestHash !== null || failureEvidenceHash !== null || errorCode !== null)
  ) {
    throw new Error("Active structured prototype operation outcome has terminal evidence");
  }
  if (
    status === "succeeded" &&
    (resultManifestHash === null || failureEvidenceHash !== null || errorCode !== null)
  ) {
    throw new Error("Succeeded structured prototype operation outcome has invalid result evidence");
  }
  if (
    status === "failed" &&
    (resultManifestHash !== null || failureEvidenceHash === null || errorCode === null)
  ) {
    throw new Error("Failed structured prototype operation outcome has invalid failure evidence");
  }
  if (
    (status === "interrupted" || status === "cancelled") &&
    (resultManifestHash !== null || errorCode === null)
  ) {
    throw new Error("Interrupted structured prototype operation outcome requires an error code");
  }
  return {
    contractVersion: 1,
    known: true,
    terminal,
    operationId: operationOutcomeUuid(value, "operationId"),
    operationKind: operationKind as StructuredPrototypeOperationKind,
    projectId: operationOutcomeUuid(value, "projectId"),
    resourceKind: operationOutcomeString(value, "resourceKind"),
    resourceId: operationOutcomeNullableUuid(value, "resourceId"),
    clientRequestId: operationOutcomeUuid(value, "clientRequestId"),
    correlationId: operationOutcomeUuid(value, "correlationId"),
    parentOperationId: operationOutcomeNullableUuid(value, "parentOperationId"),
    status: status as StructuredPrototypeOperationStatus,
    phase: operationOutcomeString(value, "phase"),
    attempt,
    requestManifestHash: operationOutcomeHash(value, "requestManifestHash"),
    configManifestHash: operationOutcomeHash(value, "configManifestHash"),
    resultManifestHash,
    failureEvidenceHash,
    errorCode,
    createdAt: operationOutcomeTimestamp(value, "createdAt"),
    startedAt,
    completedAt,
  };
}

export async function getStructuredPrototypeOperationOutcome(
  projectId: string,
  operationKind: StructuredPrototypeOperationKind,
  clientRequestId: string,
  options: StructuredPrototypeRequestOptions = {},
): Promise<StructuredPrototypeOperationOutcome> {
  const query = new URLSearchParams({ operationKind, clientRequestId });
  const value = await structuredPrototypeRequest<unknown>(
    `${API_BASE}/projects/${encodeURIComponent(projectId)}/structured-prototype-operations/outcome?${query.toString()}`,
    undefined,
    options,
  );
  const outcome = parseStructuredPrototypeOperationOutcome(value);
  if (
    outcome.projectId !== projectId ||
    outcome.operationKind !== operationKind ||
    outcome.clientRequestId !== clientRequestId
  ) {
    throw new Error("Structured prototype operation outcome does not match its query identity");
  }
  return outcome;
}

const STRUCTURED_PROTOTYPE_OPERATION_STEP_KEYS = [
  "id",
  "operationId",
  "parentStepId",
  "stepKind",
  "stepOrdinal",
  "attempt",
  "status",
  "phase",
  "inputManifestHash",
  "configManifestHash",
  "outputManifestHash",
  "completionEvidenceKind",
  "completionEvidenceRef",
  "errorCode",
  "startedAt",
  "completedAt",
] as const;

const STRUCTURED_PROTOTYPE_OPERATION_EVENT_KEYS = [
  "operationId",
  "eventNo",
  "stepId",
  "eventKind",
  "status",
  "phase",
  "inputHash",
  "outputHash",
  "evidenceHash",
  "errorCode",
  "occurredAt",
] as const;

function operationObservabilityRecord(
  value: unknown,
  expectedKeys: readonly string[],
  label: string,
): Record<string, unknown> {
  if (!isRecord(value)) throw new Error(`${label} must be an object`);
  const expected = new Set(expectedKeys);
  for (const key of Object.keys(value)) {
    if (!expected.has(key)) throw new Error(`${label} contains unknown field ${key}`);
  }
  for (const key of expectedKeys) {
    if (!Object.hasOwn(value, key)) throw new Error(`${label} is missing field ${key}`);
  }
  return value;
}

function operationObservabilityString(
  value: Record<string, unknown>,
  field: string,
  label: string,
): string {
  const parsed = value[field];
  if (typeof parsed !== "string" || parsed.length === 0) {
    throw new Error(`${label} ${field} must be a non-empty string`);
  }
  return parsed;
}

function operationObservabilityNullableString(
  value: Record<string, unknown>,
  field: string,
  label: string,
): string | null {
  const parsed = value[field];
  if (parsed === null) return null;
  if (typeof parsed !== "string" || parsed.length === 0) {
    throw new Error(`${label} ${field} must be null or a non-empty string`);
  }
  return parsed;
}

function operationObservabilityUuid(
  value: Record<string, unknown>,
  field: string,
  label: string,
): string {
  const parsed = operationObservabilityString(value, field, label);
  if (!STRUCTURED_PROTOTYPE_UUID_PATTERN.test(parsed)) {
    throw new Error(`${label} ${field} must be a canonical UUID`);
  }
  return parsed;
}

function operationObservabilityNullableUuid(
  value: Record<string, unknown>,
  field: string,
  label: string,
): string | null {
  const parsed = operationObservabilityNullableString(value, field, label);
  if (parsed !== null && !STRUCTURED_PROTOTYPE_UUID_PATTERN.test(parsed)) {
    throw new Error(`${label} ${field} must be null or a canonical UUID`);
  }
  return parsed;
}

function operationObservabilityHash(
  value: Record<string, unknown>,
  field: string,
  label: string,
): string {
  const parsed = operationObservabilityString(value, field, label);
  if (!STRUCTURED_PROTOTYPE_HASH_PATTERN.test(parsed)) {
    throw new Error(`${label} ${field} must be a SHA-256 hash`);
  }
  return parsed;
}

function operationObservabilityNullableHash(
  value: Record<string, unknown>,
  field: string,
  label: string,
): string | null {
  const parsed = operationObservabilityNullableString(value, field, label);
  if (parsed !== null && !STRUCTURED_PROTOTYPE_HASH_PATTERN.test(parsed)) {
    throw new Error(`${label} ${field} must be null or a SHA-256 hash`);
  }
  return parsed;
}

function operationObservabilityTimestamp(
  value: Record<string, unknown>,
  field: string,
  label: string,
): string {
  const parsed = operationObservabilityString(value, field, label);
  if (
    !STRUCTURED_PROTOTYPE_ISO_TIMESTAMP_PATTERN.test(parsed) ||
    !Number.isFinite(Date.parse(parsed))
  ) {
    throw new Error(`${label} ${field} must be an ISO timestamp`);
  }
  return parsed;
}

function operationObservabilityNullableTimestamp(
  value: Record<string, unknown>,
  field: string,
  label: string,
): string | null {
  const parsed = operationObservabilityNullableString(value, field, label);
  if (
    parsed !== null &&
    (!STRUCTURED_PROTOTYPE_ISO_TIMESTAMP_PATTERN.test(parsed) ||
      !Number.isFinite(Date.parse(parsed)))
  ) {
    throw new Error(`${label} ${field} must be null or an ISO timestamp`);
  }
  return parsed;
}

function operationObservabilityInteger(
  value: Record<string, unknown>,
  field: string,
  label: string,
  minimum: number,
): number {
  const parsed = value[field];
  if (typeof parsed !== "number" || !Number.isSafeInteger(parsed) || parsed < minimum) {
    throw new Error(`${label} ${field} must be an integer of at least ${minimum}`);
  }
  return parsed;
}

function parseStructuredPrototypeOperationStep(value: unknown): StructuredPrototypeOperationStep {
  const label = "Structured prototype operation step";
  const record = operationObservabilityRecord(
    value,
    STRUCTURED_PROTOTYPE_OPERATION_STEP_KEYS,
    label,
  );
  const statusValue = record["status"];
  if (
    typeof statusValue !== "string" ||
    !STRUCTURED_PROTOTYPE_OPERATION_STEP_STATUSES.includes(
      statusValue as StructuredPrototypeOperationStepStatus,
    )
  ) {
    throw new Error(`${label} status is unsupported`);
  }
  const status = statusValue as StructuredPrototypeOperationStepStatus;
  const outputManifestHash = operationObservabilityNullableHash(
    record,
    "outputManifestHash",
    label,
  );
  const completionEvidenceKind = operationObservabilityNullableString(
    record,
    "completionEvidenceKind",
    label,
  );
  const completionEvidenceRef = operationObservabilityNullableString(
    record,
    "completionEvidenceRef",
    label,
  );
  const errorCode = operationObservabilityNullableString(record, "errorCode", label);
  const startedAt = operationObservabilityNullableTimestamp(record, "startedAt", label);
  const completedAt = operationObservabilityNullableTimestamp(record, "completedAt", label);
  if ((completionEvidenceKind === null) !== (completionEvidenceRef === null)) {
    throw new Error(`${label} completion evidence is incomplete`);
  }
  if (
    status === "pending" &&
    [startedAt, completedAt, outputManifestHash, completionEvidenceKind, errorCode].some(
      (item) => item !== null,
    )
  ) {
    throw new Error(`${label} pending lifecycle is invalid`);
  }
  if (
    status === "running" &&
    (startedAt === null ||
      [completedAt, outputManifestHash, completionEvidenceKind, errorCode].some(
        (item) => item !== null,
      ))
  ) {
    throw new Error(`${label} running lifecycle is invalid`);
  }
  if (
    status === "succeeded" &&
    (startedAt === null ||
      completedAt === null ||
      outputManifestHash === null ||
      completionEvidenceKind === null ||
      errorCode !== null)
  ) {
    throw new Error(`${label} succeeded evidence is invalid`);
  }
  if (
    (status === "failed" || status === "interrupted") &&
    (startedAt === null ||
      completedAt === null ||
      completionEvidenceKind === null ||
      errorCode === null)
  ) {
    throw new Error(`${label} failure evidence is invalid`);
  }
  if (
    status === "skipped" &&
    (completedAt === null || completionEvidenceKind === null || errorCode !== null)
  ) {
    throw new Error(`${label} skipped evidence is invalid`);
  }
  if (
    startedAt !== null &&
    completedAt !== null &&
    Date.parse(completedAt) < Date.parse(startedAt)
  ) {
    throw new Error(`${label} completion precedes start`);
  }
  return {
    id: operationObservabilityUuid(record, "id", label),
    operationId: operationObservabilityUuid(record, "operationId", label),
    parentStepId: operationObservabilityNullableUuid(record, "parentStepId", label),
    stepKind: operationObservabilityString(record, "stepKind", label),
    stepOrdinal: operationObservabilityInteger(record, "stepOrdinal", label, 0),
    attempt: operationObservabilityInteger(record, "attempt", label, 1),
    status,
    phase: operationObservabilityString(record, "phase", label),
    inputManifestHash: operationObservabilityHash(record, "inputManifestHash", label),
    configManifestHash: operationObservabilityHash(record, "configManifestHash", label),
    outputManifestHash,
    completionEvidenceKind,
    completionEvidenceRef,
    errorCode,
    startedAt,
    completedAt,
  };
}

function parseStructuredPrototypeOperationEvent(value: unknown): StructuredPrototypeOperationEvent {
  const label = "Structured prototype operation event";
  const record = operationObservabilityRecord(
    value,
    STRUCTURED_PROTOTYPE_OPERATION_EVENT_KEYS,
    label,
  );
  const statusValue = record["status"];
  if (
    typeof statusValue !== "string" ||
    !STRUCTURED_PROTOTYPE_OPERATION_EVENT_STATUSES.includes(
      statusValue as StructuredPrototypeOperationEventStatus,
    )
  ) {
    throw new Error(`${label} status is unsupported`);
  }
  return {
    operationId: operationObservabilityUuid(record, "operationId", label),
    eventNo: operationObservabilityInteger(record, "eventNo", label, 0),
    stepId: operationObservabilityNullableUuid(record, "stepId", label),
    eventKind: operationObservabilityString(record, "eventKind", label),
    status: statusValue as StructuredPrototypeOperationEventStatus,
    phase: operationObservabilityString(record, "phase", label),
    inputHash: operationObservabilityNullableHash(record, "inputHash", label),
    outputHash: operationObservabilityNullableHash(record, "outputHash", label),
    evidenceHash: operationObservabilityNullableHash(record, "evidenceHash", label),
    errorCode: operationObservabilityNullableString(record, "errorCode", label),
    occurredAt: operationObservabilityTimestamp(record, "occurredAt", label),
  };
}

const STRUCTURED_PROTOTYPE_REPLAY_VERSION_KEYS = [
  "serviceVersion",
  "documentSchemaVersion",
  "commandContractVersion",
  "runtimeStateSchemaVersion",
  "runtimeEventContractVersion",
  "runtimeCoreVersion",
  "runtimeCoreBundleHash",
  "stateMachineKernelVersion",
  "rendererVersion",
  "rendererEnvironmentVersion",
  "replayManifestVersion",
] as const;

const STRUCTURED_PROTOTYPE_REPLAY_MANIFEST_KEYS = [
  "manifestVersion",
  "operationId",
  "operationKind",
  "parentOperationId",
  "requestManifestHash",
  "contextManifestHash",
  "orderedInputObjectHashes",
  "versions",
  "agentTaskIdentity",
  "submissionHash",
  "orderedCommandBatchHashes",
  "baseCheckpointHash",
  "baseSequenceNo",
  "resultCheckpointHash",
  "resultSequenceNo",
  "rendererInputHash",
  "rendererOutputHash",
  "runtimeSessionId",
  "runtimeCoreBundleHash",
  "orderedRuntimeEventHashes",
  "runtimeFinalStateHash",
  "runtimeFinalViewModelHash",
  "validationReportHashes",
  "terminalStatus",
  "errorCode",
] as const;

function operationObservabilityHashArray(value: unknown, label: string): string[] {
  if (!Array.isArray(value)) throw new Error(`${label} must be an array`);
  return value.map((item, index) => {
    if (typeof item !== "string" || !STRUCTURED_PROTOTYPE_HASH_PATTERN.test(item)) {
      throw new Error(`${label}[${index}] must be a SHA-256 hash`);
    }
    return item;
  });
}

function operationObservabilityNullableSequenceNo(
  value: Record<string, unknown>,
  field: string,
  label: string,
): number | null {
  if (value[field] === null) return null;
  return operationObservabilityInteger(value, field, label, 0);
}

function parseStructuredPrototypeReplayVersions(
  value: unknown,
): StructuredPrototypeReplayManifestVersions {
  const label = "Structured prototype replay manifest versions";
  const record = operationObservabilityRecord(
    value,
    STRUCTURED_PROTOTYPE_REPLAY_VERSION_KEYS,
    label,
  );
  if (record["replayManifestVersion"] !== 1) {
    throw new Error(`${label} contract is unsupported`);
  }
  return {
    serviceVersion: operationObservabilityString(record, "serviceVersion", label),
    documentSchemaVersion: operationObservabilityInteger(record, "documentSchemaVersion", label, 1),
    commandContractVersion: operationObservabilityInteger(
      record,
      "commandContractVersion",
      label,
      1,
    ),
    runtimeStateSchemaVersion: operationObservabilityInteger(
      record,
      "runtimeStateSchemaVersion",
      label,
      1,
    ),
    runtimeEventContractVersion: operationObservabilityInteger(
      record,
      "runtimeEventContractVersion",
      label,
      1,
    ),
    runtimeCoreVersion: operationObservabilityNullableString(record, "runtimeCoreVersion", label),
    runtimeCoreBundleHash: operationObservabilityNullableHash(
      record,
      "runtimeCoreBundleHash",
      label,
    ),
    stateMachineKernelVersion: operationObservabilityNullableString(
      record,
      "stateMachineKernelVersion",
      label,
    ),
    rendererVersion: operationObservabilityNullableString(record, "rendererVersion", label),
    rendererEnvironmentVersion: operationObservabilityNullableString(
      record,
      "rendererEnvironmentVersion",
      label,
    ),
    replayManifestVersion: 1,
  };
}

function parseStructuredPrototypeReplayManifest(value: unknown): StructuredPrototypeReplayManifest {
  const label = "Structured prototype replay manifest";
  const record = operationObservabilityRecord(
    value,
    STRUCTURED_PROTOTYPE_REPLAY_MANIFEST_KEYS,
    label,
  );
  if (record["manifestVersion"] !== 1) {
    throw new Error(`${label} contract is unsupported`);
  }
  const operationKindValue = record["operationKind"];
  if (
    typeof operationKindValue !== "string" ||
    !STRUCTURED_PROTOTYPE_OPERATION_KINDS.includes(
      operationKindValue as StructuredPrototypeOperationKind,
    )
  ) {
    throw new Error(`${label} operationKind is unsupported`);
  }
  if (record["terminalStatus"] !== "succeeded" || record["errorCode"] !== null) {
    throw new Error(`${label} terminal evidence is invalid`);
  }
  const versions = parseStructuredPrototypeReplayVersions(record["versions"]);
  const runtimeCoreBundleHash = operationObservabilityNullableHash(
    record,
    "runtimeCoreBundleHash",
    label,
  );
  if (runtimeCoreBundleHash !== versions.runtimeCoreBundleHash) {
    throw new Error(`${label} runtime core identity disagrees with versions`);
  }
  const baseCheckpointHash = operationObservabilityNullableHash(
    record,
    "baseCheckpointHash",
    label,
  );
  const baseSequenceNo = operationObservabilityNullableSequenceNo(record, "baseSequenceNo", label);
  const resultCheckpointHash = operationObservabilityNullableHash(
    record,
    "resultCheckpointHash",
    label,
  );
  const resultSequenceNo = operationObservabilityNullableSequenceNo(
    record,
    "resultSequenceNo",
    label,
  );
  if ((baseCheckpointHash === null) !== (baseSequenceNo === null)) {
    throw new Error(`${label} base checkpoint evidence is incomplete`);
  }
  if ((resultCheckpointHash === null) !== (resultSequenceNo === null)) {
    throw new Error(`${label} result checkpoint evidence is incomplete`);
  }
  const agentTaskIdentityValue = record["agentTaskIdentity"];
  let agentTaskIdentity: Record<string, string> | null = null;
  if (agentTaskIdentityValue !== null) {
    if (!isRecord(agentTaskIdentityValue) || Object.keys(agentTaskIdentityValue).length === 0) {
      throw new Error(`${label} agentTaskIdentity must be null or a non-empty object`);
    }
    agentTaskIdentity = {};
    for (const [key, item] of Object.entries(agentTaskIdentityValue)) {
      if (key.length === 0 || typeof item !== "string" || item.length === 0) {
        throw new Error(`${label} agentTaskIdentity entries must be non-empty strings`);
      }
      agentTaskIdentity[key] = item;
    }
  }
  return {
    manifestVersion: 1,
    operationId: operationObservabilityUuid(record, "operationId", label),
    operationKind: operationKindValue as StructuredPrototypeOperationKind,
    parentOperationId: operationObservabilityNullableUuid(record, "parentOperationId", label),
    requestManifestHash: operationObservabilityHash(record, "requestManifestHash", label),
    contextManifestHash: operationObservabilityNullableHash(record, "contextManifestHash", label),
    orderedInputObjectHashes: operationObservabilityHashArray(
      record["orderedInputObjectHashes"],
      `${label} orderedInputObjectHashes`,
    ),
    versions,
    agentTaskIdentity,
    submissionHash: operationObservabilityNullableHash(record, "submissionHash", label),
    orderedCommandBatchHashes: operationObservabilityHashArray(
      record["orderedCommandBatchHashes"],
      `${label} orderedCommandBatchHashes`,
    ),
    baseCheckpointHash,
    baseSequenceNo,
    resultCheckpointHash,
    resultSequenceNo,
    rendererInputHash: operationObservabilityNullableHash(record, "rendererInputHash", label),
    rendererOutputHash: operationObservabilityNullableHash(record, "rendererOutputHash", label),
    runtimeSessionId: operationObservabilityNullableUuid(record, "runtimeSessionId", label),
    runtimeCoreBundleHash,
    orderedRuntimeEventHashes: operationObservabilityHashArray(
      record["orderedRuntimeEventHashes"],
      `${label} orderedRuntimeEventHashes`,
    ),
    runtimeFinalStateHash: operationObservabilityNullableHash(
      record,
      "runtimeFinalStateHash",
      label,
    ),
    runtimeFinalViewModelHash: operationObservabilityNullableHash(
      record,
      "runtimeFinalViewModelHash",
      label,
    ),
    validationReportHashes: operationObservabilityHashArray(
      record["validationReportHashes"],
      `${label} validationReportHashes`,
    ),
    terminalStatus: "succeeded",
    errorCode: null,
  };
}

export function parseStructuredPrototypeOperationDetail(
  value: unknown,
): StructuredPrototypeOperationDetail {
  const label = "Structured prototype operation detail";
  const record = operationObservabilityRecord(
    value,
    ["contractVersion", "operation", "steps", "childOperationIds", "replayManifest"],
    label,
  );
  if (record["contractVersion"] !== 1) throw new Error(`${label} contract is unsupported`);
  const operation = parseStructuredPrototypeOperationOutcome(record["operation"]);
  const stepsValue = record["steps"];
  if (!Array.isArray(stepsValue)) throw new Error(`${label} steps must be an array`);
  const steps = stepsValue.map(parseStructuredPrototypeOperationStep);
  const stepIds = new Set<string>();
  const stepKeys = new Set<string>();
  let priorStepOrdinal = -1;
  let priorAttempt = -1;
  for (const step of steps) {
    if (step.operationId !== operation.operationId || stepIds.has(step.id)) {
      throw new Error(`${label} contains a duplicate or cross-operation step`);
    }
    if (
      step.stepOrdinal < priorStepOrdinal ||
      (step.stepOrdinal === priorStepOrdinal && step.attempt <= priorAttempt)
    ) {
      throw new Error(`${label} steps are not in stable order`);
    }
    const stepKey = `${step.stepOrdinal}:${step.attempt}`;
    if (stepKeys.has(stepKey)) throw new Error(`${label} contains a duplicate step attempt`);
    stepIds.add(step.id);
    stepKeys.add(stepKey);
    priorStepOrdinal = step.stepOrdinal;
    priorAttempt = step.attempt;
  }
  for (const step of steps) {
    if (step.parentStepId !== null && !stepIds.has(step.parentStepId)) {
      throw new Error(`${label} step parent is outside the operation`);
    }
  }
  const childOperationIdsValue = record["childOperationIds"];
  if (!Array.isArray(childOperationIdsValue)) {
    throw new Error(`${label} childOperationIds must be an array`);
  }
  const childOperationIds = childOperationIdsValue.map((item, index) => {
    if (typeof item !== "string" || !STRUCTURED_PROTOTYPE_UUID_PATTERN.test(item)) {
      throw new Error(`${label} childOperationIds[${index}] must be a canonical UUID`);
    }
    return item;
  });
  if (new Set(childOperationIds).size !== childOperationIds.length) {
    throw new Error(`${label} contains duplicate child operations`);
  }
  const replayManifest =
    record["replayManifest"] === null
      ? null
      : parseStructuredPrototypeReplayManifest(record["replayManifest"]);
  if (operation.status === "succeeded" && replayManifest === null) {
    throw new Error(`${label} succeeded operation requires a replay manifest`);
  }
  if (operation.status !== "succeeded" && replayManifest !== null) {
    throw new Error(`${label} non-succeeded operation cannot expose a replay manifest`);
  }
  if (
    replayManifest !== null &&
    (replayManifest.operationId !== operation.operationId ||
      replayManifest.operationKind !== operation.operationKind ||
      replayManifest.parentOperationId !== operation.parentOperationId ||
      replayManifest.requestManifestHash !== operation.requestManifestHash)
  ) {
    throw new Error(`${label} replay manifest identity does not match its operation`);
  }
  return {
    contractVersion: 1,
    operation,
    steps,
    childOperationIds,
    replayManifest,
  };
}

export function parseStructuredPrototypeOperationEvents(
  value: unknown,
): StructuredPrototypeOperationEvents {
  const label = "Structured prototype operation events";
  const record = operationObservabilityRecord(
    value,
    ["contractVersion", "operationId", "events"],
    label,
  );
  if (record["contractVersion"] !== 1) throw new Error(`${label} contract is unsupported`);
  const operationId = operationObservabilityUuid(record, "operationId", label);
  const eventsValue = record["events"];
  if (!Array.isArray(eventsValue) || eventsValue.length === 0) {
    throw new Error(`${label} must contain durable events`);
  }
  const events = eventsValue.map(parseStructuredPrototypeOperationEvent);
  let priorOccurredAt = Number.NEGATIVE_INFINITY;
  for (const [index, event] of events.entries()) {
    if (event.operationId !== operationId || event.eventNo !== index) {
      throw new Error(`${label} identity or gap-free sequence is invalid`);
    }
    const occurredAt = Date.parse(event.occurredAt);
    if (occurredAt < priorOccurredAt) {
      throw new Error(`${label} timestamps are not monotonic`);
    }
    priorOccurredAt = occurredAt;
  }
  return { contractVersion: 1, operationId, events };
}

export async function getStructuredPrototypeOperationDetail(
  operationId: string,
  options: StructuredPrototypeRequestOptions = {},
): Promise<StructuredPrototypeOperationDetail> {
  const value = await structuredPrototypeRequest<unknown>(
    `${API_BASE}/prototype-operations/${encodeURIComponent(operationId)}`,
    undefined,
    options,
  );
  const detail = parseStructuredPrototypeOperationDetail(value);
  if (detail.operation.operationId !== operationId) {
    throw new Error("Structured prototype operation detail does not match its query identity");
  }
  return detail;
}

export async function getStructuredPrototypeOperationEvents(
  operationId: string,
  options: StructuredPrototypeRequestOptions = {},
): Promise<StructuredPrototypeOperationEvents> {
  const value = await structuredPrototypeRequest<unknown>(
    `${API_BASE}/prototype-operations/${encodeURIComponent(operationId)}/events`,
    undefined,
    options,
  );
  const events = parseStructuredPrototypeOperationEvents(value);
  if (events.operationId !== operationId) {
    throw new Error("Structured prototype operation events do not match their query identity");
  }
  return events;
}

export function isStructuredPrototypeOperationOutcomeUnknownError(
  error: unknown,
): error is StructuredPrototypeApiError {
  return (
    error instanceof StructuredPrototypeApiError &&
    error.status === 404 &&
    error.code === "operation_outcome_unknown"
  );
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

export async function deleteProjectStructuredPrototype(
  projectId: string,
  clientRequestId: string,
): Promise<DeleteStructuredPrototypeResult> {
  const query = new URLSearchParams({ clientRequestId });
  return structuredPrototypeRequest<DeleteStructuredPrototypeResult>(
    `${API_BASE}/projects/${encodeURIComponent(projectId)}/structured-prototype-documents?${query.toString()}`,
    { method: "DELETE" },
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

export async function undoStructuredPrototypeDraft(
  draftId: string,
  body: MutateStructuredPrototypeHistoryRequest,
): Promise<AppliedStructuredPrototypeCommands> {
  return structuredPrototypeJsonRequest<AppliedStructuredPrototypeCommands>(
    `${API_BASE}/structured-prototype-drafts/${encodeURIComponent(draftId)}/undo`,
    "POST",
    body,
  );
}

export async function redoStructuredPrototypeDraft(
  draftId: string,
  body: MutateStructuredPrototypeHistoryRequest,
): Promise<AppliedStructuredPrototypeCommands> {
  return structuredPrototypeJsonRequest<AppliedStructuredPrototypeCommands>(
    `${API_BASE}/structured-prototype-drafts/${encodeURIComponent(draftId)}/redo`,
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

export async function resetStructuredPrototypeRuntimeSession(
  sessionId: string,
  body: ResetStructuredPrototypeRuntimeSessionRequest,
): Promise<StructuredPrototypeRuntimeSession> {
  return structuredPrototypeJsonRequest<StructuredPrototypeRuntimeSession>(
    `${API_BASE}/structured-prototype-runtime-sessions/${encodeURIComponent(sessionId)}/reset`,
    "POST",
    body,
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

export async function listStructuredPrototypeRevisions(
  documentId: string,
): Promise<StructuredPrototypeRevisionHistory> {
  return structuredPrototypeRequest<StructuredPrototypeRevisionHistory>(
    `${API_BASE}/structured-prototype-documents/${encodeURIComponent(documentId)}/revisions`,
  );
}

export async function diffStructuredPrototypeRevisions(
  documentId: string,
  revisionNo: number,
  against?: number,
): Promise<StructuredPrototypeRevisionDiff> {
  const query = against !== undefined ? `?against=${encodeURIComponent(against)}` : "";
  return structuredPrototypeRequest<StructuredPrototypeRevisionDiff>(
    `${API_BASE}/structured-prototype-documents/${encodeURIComponent(documentId)}` +
      `/revisions/${encodeURIComponent(revisionNo)}/diff${query}`,
  );
}

export async function rollbackStructuredPrototypePublication(
  documentId: string,
  body: RollbackStructuredPrototypeRequest,
): Promise<RolledBackStructuredPrototype> {
  return structuredPrototypeJsonRequest<RolledBackStructuredPrototype>(
    `${API_BASE}/structured-prototype-documents/${encodeURIComponent(documentId)}/rollback`,
    "POST",
    body,
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

export function isTerminalStructuredPrototypeGenerationOperationError(
  error: unknown,
): error is StructuredPrototypeGenerationApiError {
  return (
    error instanceof StructuredPrototypeGenerationApiError && !error.code.endsWith("_in_progress")
  );
}

async function structuredPrototypeGenerationRequest<T>(
  url: string,
  init?: RequestInit,
): Promise<T> {
  return runStructuredPrototypeRequestWithDeadline(
    async (signal) => {
      const response = await apiRawRequest(url, { ...init, signal });
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
    },
    init?.signal === undefined ? {} : { signal: init.signal },
  );
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
  body: {
    contractVersion: 1;
    clientRequestId: string;
    expectedBlueprintVersion: number;
    expectedBlueprintHash: string;
  },
): Promise<StructuredPrototypeGenerationConfirmResult> {
  return structuredPrototypeGenerationJsonRequest<StructuredPrototypeGenerationConfirmResult>(
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
    expectedSourceFingerprint: string;
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

export function isTerminalStructuredPrototypeAiOperationError(
  error: unknown,
): error is StructuredPrototypeAiApiError {
  return error instanceof StructuredPrototypeAiApiError && !error.code.endsWith("_in_progress");
}

async function structuredPrototypeAiRequest<T>(url: string, init?: RequestInit): Promise<T> {
  return runStructuredPrototypeRequestWithDeadline(
    async (signal) => {
      const response = await apiRawRequest(url, { ...init, signal });
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
    },
    init?.signal === undefined ? {} : { signal: init.signal },
  );
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
