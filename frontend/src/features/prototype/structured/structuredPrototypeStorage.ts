import type { StructuredPrototypeOperationKind } from "@/lib/api/prototypes";
import { isRecord, safeJsonParse } from "@/lib/utils";

export const STRUCTURED_PROTOTYPE_DELETE_REQUEST_KEY = "delete-project-request";
export const STRUCTURED_PROTOTYPE_GENERATION_START_REQUEST_KEY = "generation-start-request";
export const STRUCTURED_PROTOTYPE_PENDING_OPERATION_KEY = "pending-operation-v1";

export type StructuredPrototypeHistoryOperation = "undo" | "redo";

export type StructuredPrototypeClientOperationKind = Extract<
  StructuredPrototypeOperationKind,
  | "apply_command_batch"
  | "undo"
  | "redo"
  | "create_checkpoint"
  | "delete_project_prototype"
  | "publish"
  | "create_runtime_session"
  | "reset_runtime_session"
  | "apply_runtime_event"
  | "ai_edit"
  | "reject_ai_proposal"
  | "generation_job"
  | "create_document"
>;

export type StructuredPrototypeStudioOperationKind = Extract<
  StructuredPrototypeClientOperationKind,
  | "apply_command_batch"
  | "undo"
  | "redo"
  | "create_checkpoint"
  | "delete_project_prototype"
  | "publish"
  | "create_runtime_session"
  | "reset_runtime_session"
  | "apply_runtime_event"
>;

export type StructuredPrototypePendingResourceKind =
  | "draft"
  | "runtime_session"
  | "project_prototype"
  | "ai_thread"
  | "ai_edit_run"
  | "project"
  | "generation_job";

export interface StructuredPrototypePendingOperation {
  contractVersion: 1;
  projectId: string;
  operationKind: StructuredPrototypeClientOperationKind;
  resourceKind: StructuredPrototypePendingResourceKind;
  resourceId: string;
  contextId: string | null;
  clientRequestId: string;
  requestKey: string;
  createdAt: string;
}

export class StructuredPrototypeStorageError extends Error {
  constructor(message: string, options?: ErrorOptions) {
    super(message, options);
    this.name = "StructuredPrototypeStorageError";
  }
}

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/u;
const PENDING_OPERATION_KEYS = [
  "contractVersion",
  "projectId",
  "operationKind",
  "resourceKind",
  "resourceId",
  "contextId",
  "clientRequestId",
  "requestKey",
  "createdAt",
] as const;

const CLIENT_OPERATION_KINDS = [
  "apply_command_batch",
  "undo",
  "redo",
  "create_checkpoint",
  "delete_project_prototype",
  "publish",
  "create_runtime_session",
  "reset_runtime_session",
  "apply_runtime_event",
  "ai_edit",
  "reject_ai_proposal",
  "generation_job",
  "create_document",
] as const satisfies readonly StructuredPrototypeClientOperationKind[];

const STUDIO_OPERATION_KINDS = [
  "apply_command_batch",
  "undo",
  "redo",
  "create_checkpoint",
  "delete_project_prototype",
  "publish",
  "create_runtime_session",
  "reset_runtime_session",
  "apply_runtime_event",
] as const satisfies readonly StructuredPrototypeStudioOperationKind[];
const STUDIO_OPERATION_KIND_SET: ReadonlySet<StructuredPrototypeClientOperationKind> = new Set(
  STUDIO_OPERATION_KINDS,
);
const CLIENT_OPERATION_KIND_SET: ReadonlySet<string> = new Set(CLIENT_OPERATION_KINDS);

function isStructuredPrototypeClientOperationKind(
  value: unknown,
): value is StructuredPrototypeClientOperationKind {
  return typeof value === "string" && CLIENT_OPERATION_KIND_SET.has(value);
}

export function isStructuredPrototypeStudioPendingOperation(
  operation: StructuredPrototypePendingOperation,
): boolean {
  return operation.contextId === null && STUDIO_OPERATION_KIND_SET.has(operation.operationKind);
}

export function isStructuredPrototypeAiPendingOperation(
  operation: StructuredPrototypePendingOperation,
): boolean {
  return (
    operation.operationKind === "ai_edit" ||
    operation.operationKind === "reject_ai_proposal" ||
    (operation.operationKind === "apply_command_batch" && operation.contextId !== null)
  );
}

export function isStructuredPrototypeGenerationPendingOperation(
  operation: StructuredPrototypePendingOperation,
): boolean {
  return (
    operation.operationKind === "generation_job" ||
    operation.operationKind === "create_document" ||
    (operation.operationKind === "delete_project_prototype" && operation.contextId === "generation")
  );
}

function allowedPendingResourceKinds(
  operationKind: StructuredPrototypeClientOperationKind,
): readonly StructuredPrototypePendingResourceKind[] {
  switch (operationKind) {
    case "apply_command_batch":
    case "undo":
    case "redo":
    case "publish":
    case "create_runtime_session":
      return ["draft"];
    case "create_checkpoint":
    case "reset_runtime_session":
    case "apply_runtime_event":
      return ["runtime_session"];
    case "delete_project_prototype":
      return ["project_prototype"];
    case "ai_edit":
      return ["ai_thread"];
    case "reject_ai_proposal":
      return ["ai_edit_run"];
    case "generation_job":
      return ["project", "generation_job"];
    case "create_document":
      return ["generation_job"];
  }
}

function isAllowedPendingResourceKind(
  operationKind: StructuredPrototypeClientOperationKind,
  value: unknown,
): value is StructuredPrototypePendingResourceKind {
  return (
    typeof value === "string" &&
    allowedPendingResourceKinds(operationKind).some((candidate) => candidate === value)
  );
}

function pendingContextMatchesOperation(
  operationKind: StructuredPrototypeClientOperationKind,
  contextId: string | null,
): boolean {
  if (operationKind === "apply_command_batch") {
    return contextId !== "generation";
  }
  if (operationKind === "delete_project_prototype") {
    return contextId === null || contextId === "generation";
  }
  return contextId === null;
}

function pendingRequestKeyMatchesOperation(
  operationKind: StructuredPrototypeClientOperationKind,
  resourceKind: StructuredPrototypePendingResourceKind,
  contextId: string | null,
  requestKey: string,
): boolean {
  const hasSuffix = (prefix: string) =>
    requestKey.startsWith(prefix) && requestKey.length > prefix.length;
  switch (operationKind) {
    case "apply_command_batch":
      return hasSuffix(contextId === null ? "command-request:" : "ai-apply-request:");
    case "undo":
      return hasSuffix("undo-request:");
    case "redo":
      return hasSuffix("redo-request:");
    case "create_checkpoint":
      return hasSuffix("runtime-checkpoint-request:");
    case "delete_project_prototype":
      return requestKey === STRUCTURED_PROTOTYPE_DELETE_REQUEST_KEY;
    case "publish":
      return hasSuffix("publish-request:");
    case "create_runtime_session":
      return hasSuffix("runtime-create-request:");
    case "reset_runtime_session":
      return hasSuffix("runtime-reset-request:");
    case "apply_runtime_event":
      return hasSuffix("runtime-event-request:");
    case "ai_edit":
      return hasSuffix("ai-message-request:");
    case "reject_ai_proposal":
      return hasSuffix("ai-reject-request:");
    case "generation_job":
      return resourceKind === "project"
        ? requestKey === STRUCTURED_PROTOTYPE_GENERATION_START_REQUEST_KEY
        : hasSuffix("generation-confirm-request:");
    case "create_document":
      return hasSuffix("generation-accept-request:");
  }
}

function pendingString(value: Record<string, unknown>, field: string): string {
  const fieldValue = value[field];
  if (typeof fieldValue !== "string" || fieldValue.length === 0) {
    throw new StructuredPrototypeStorageError(
      `Structured prototype pending operation ${field} must be a non-empty string`,
    );
  }
  return fieldValue;
}

export function parseStructuredPrototypePendingOperation(
  value: unknown,
  expectedProjectId?: string,
): StructuredPrototypePendingOperation {
  if (!isRecord(value)) {
    throw new StructuredPrototypeStorageError(
      "Structured prototype pending operation must be an object",
    );
  }
  const record = value;
  const expectedKeys = new Set<string>(PENDING_OPERATION_KEYS);
  for (const key of Object.keys(record)) {
    if (!expectedKeys.has(key)) {
      throw new StructuredPrototypeStorageError(
        `Structured prototype pending operation contains unknown field ${key}`,
      );
    }
  }
  for (const key of PENDING_OPERATION_KEYS) {
    if (!Object.hasOwn(record, key)) {
      throw new StructuredPrototypeStorageError(
        `Structured prototype pending operation is missing field ${key}`,
      );
    }
  }
  if (record["contractVersion"] !== 1) {
    throw new StructuredPrototypeStorageError(
      "Structured prototype pending operation contract is unsupported",
    );
  }
  const projectId = pendingString(record, "projectId");
  if (!UUID_PATTERN.test(projectId)) {
    throw new StructuredPrototypeStorageError(
      "Structured prototype pending operation projectId must be a canonical UUID",
    );
  }
  if (expectedProjectId !== undefined && projectId !== expectedProjectId) {
    throw new StructuredPrototypeStorageError(
      "Structured prototype pending operation belongs to another project",
    );
  }
  const operationKindValue = record["operationKind"];
  if (!isStructuredPrototypeClientOperationKind(operationKindValue)) {
    throw new StructuredPrototypeStorageError(
      "Structured prototype pending operation kind is unsupported",
    );
  }
  const operationKind = operationKindValue;
  const resourceKindValue = record["resourceKind"];
  if (!isAllowedPendingResourceKind(operationKind, resourceKindValue)) {
    throw new StructuredPrototypeStorageError(
      "Structured prototype pending operation resource does not match its operation kind",
    );
  }
  const clientRequestId = pendingString(record, "clientRequestId");
  if (!UUID_PATTERN.test(clientRequestId)) {
    throw new StructuredPrototypeStorageError(
      "Structured prototype pending operation clientRequestId must be a canonical UUID",
    );
  }
  const resourceId = pendingString(record, "resourceId");
  if (!UUID_PATTERN.test(resourceId)) {
    throw new StructuredPrototypeStorageError(
      "Structured prototype pending operation resourceId must be a canonical UUID",
    );
  }
  const createdAt = pendingString(record, "createdAt");
  const createdAtMilliseconds = Date.parse(createdAt);
  if (
    !Number.isFinite(createdAtMilliseconds) ||
    new Date(createdAtMilliseconds).toISOString() !== createdAt
  ) {
    throw new StructuredPrototypeStorageError(
      "Structured prototype pending operation createdAt must be a canonical UTC timestamp",
    );
  }
  const contextIdValue = record["contextId"];
  if (
    contextIdValue !== null &&
    contextIdValue !== "generation" &&
    (typeof contextIdValue !== "string" || !UUID_PATTERN.test(contextIdValue))
  ) {
    throw new StructuredPrototypeStorageError(
      "Structured prototype pending operation contextId must be null, generation, or a UUID",
    );
  }
  if (!pendingContextMatchesOperation(operationKind, contextIdValue)) {
    throw new StructuredPrototypeStorageError(
      "Structured prototype pending operation context does not match its operation kind",
    );
  }
  const requestKey = pendingString(record, "requestKey");
  if (
    !pendingRequestKeyMatchesOperation(operationKind, resourceKindValue, contextIdValue, requestKey)
  ) {
    throw new StructuredPrototypeStorageError(
      "Structured prototype pending operation request key does not match its operation",
    );
  }
  return {
    contractVersion: 1,
    projectId,
    operationKind,
    resourceKind: resourceKindValue,
    resourceId,
    contextId: contextIdValue,
    clientRequestId,
    requestKey,
    createdAt,
  };
}

export function structuredPrototypeRuntimeCreateRequestKey(
  draftId: string,
  headSequenceNo: number,
  documentHash: string,
): string {
  return `runtime-create-request:${draftId}:${headSequenceNo}:${documentHash}`;
}

export function structuredPrototypeRuntimeResetRequestKey(
  oldSessionId: string,
  oldHeadSequenceNo: number,
  oldStateHash: string,
  oldViewModelHash: string,
  oldRuntimeCoreBundleHash: string,
  targetDraftId: string,
  targetHeadSequenceNo: number,
  targetDocumentHash: string,
  scenarioId: string,
  causeOperationId: string | null,
): string {
  return [
    "runtime-reset-request",
    oldSessionId,
    oldHeadSequenceNo,
    oldStateHash,
    oldViewModelHash,
    oldRuntimeCoreBundleHash,
    targetDraftId,
    targetHeadSequenceNo,
    targetDocumentHash,
    scenarioId,
    causeOperationId ?? "none",
  ].join(":");
}

export function structuredPrototypeHistoryRequestKey(
  operation: StructuredPrototypeHistoryOperation,
  draftId: string,
  headSequenceNo: number,
  documentHash: string,
): string {
  return `${operation}-request:${draftId}:${headSequenceNo}:${documentHash}`;
}

export function structuredPrototypeCommandRequestKey(
  draftId: string,
  headSequenceNo: number,
  documentHash: string,
): string {
  return `command-request:${draftId}:${headSequenceNo}:${documentHash}`;
}

export function structuredPrototypeRuntimeEventRequestKey(
  sessionId: string,
  headSequenceNo: number,
  stateHash: string,
): string {
  return `runtime-event-request:${sessionId}:${headSequenceNo}:${stateHash}`;
}

export function structuredPrototypeRuntimeCheckpointRequestKey(
  sessionId: string,
  headSequenceNo: number,
  stateHash: string,
): string {
  return `runtime-checkpoint-request:${sessionId}:${headSequenceNo}:${stateHash}`;
}

export function structuredPrototypePublishRequestKey(
  draftId: string,
  headSequenceNo: number,
  documentHash: string,
): string {
  return `publish-request:${draftId}:${headSequenceNo}:${documentHash}`;
}

export function structuredPrototypeAiMessageRequestKey(
  threadId: string,
  draftId: string,
  headSequenceNo: number,
  documentHash: string,
): string {
  return `ai-message-request:${threadId}:${draftId}:${headSequenceNo}:${documentHash}`;
}

export function structuredPrototypeAiApplyRequestKey(
  runId: string,
  draftId: string,
  headSequenceNo: number,
  documentHash: string,
): string {
  return `ai-apply-request:${runId}:${draftId}:${headSequenceNo}:${documentHash}`;
}

export function structuredPrototypeAiRejectRequestKey(runId: string): string {
  return `ai-reject-request:${runId}`;
}

export function structuredPrototypeGenerationAcceptRequestKey(
  jobId: string,
  candidateObjectHash: string,
  previewOutputHash: string,
  sourceFingerprint: string,
): string {
  return `generation-accept-request:${jobId}:${candidateObjectHash}:${previewOutputHash}:${sourceFingerprint}`;
}

export function structuredPrototypeGenerationConfirmRequestKey(
  jobId: string,
  blueprintVersion: number,
  blueprintHash: string,
): string {
  return `generation-confirm-request:${jobId}:${blueprintVersion}:${blueprintHash}`;
}

export function structuredPrototypeStorageKey(projectId: string, suffix: string): string {
  return `structured-prototype:${projectId}:${suffix}`;
}

export function structuredPrototypeRequestIdentity(projectId: string, key: string): string {
  const name = structuredPrototypeStorageKey(projectId, key);
  const current = window.localStorage.getItem(name);
  if (current !== null) {
    if (!UUID_PATTERN.test(current)) {
      throw new StructuredPrototypeStorageError(
        "Structured prototype request identity must be a canonical UUID",
      );
    }
    return current;
  }
  const created = crypto.randomUUID();
  window.localStorage.setItem(name, created);
  return created;
}

export function finishStructuredPrototypeRequestIdentity(projectId: string, key: string): void {
  window.localStorage.removeItem(structuredPrototypeStorageKey(projectId, key));
}

export function loadStructuredPrototypePendingOperation(
  projectId: string,
): StructuredPrototypePendingOperation | null {
  const raw = window.localStorage.getItem(
    structuredPrototypeStorageKey(projectId, STRUCTURED_PROTOTYPE_PENDING_OPERATION_KEY),
  );
  if (raw === null) return null;
  const value = safeJsonParse(raw);
  if (value === null) {
    throw new StructuredPrototypeStorageError(
      "Structured prototype pending operation is not valid JSON",
    );
  }
  return parseStructuredPrototypePendingOperation(value, projectId);
}

export interface StructuredPrototypePendingLockState {
  locked: boolean;
  storageError: StructuredPrototypeStorageError | null;
}

export function readStructuredPrototypePendingLockState(
  projectId: string,
  ownsOperation: (operation: StructuredPrototypePendingOperation) => boolean,
): StructuredPrototypePendingLockState {
  try {
    const operation = loadStructuredPrototypePendingOperation(projectId);
    return { locked: operation !== null && ownsOperation(operation), storageError: null };
  } catch (error) {
    if (!(error instanceof StructuredPrototypeStorageError)) throw error;
    return { locked: true, storageError: error };
  }
}

export function beginStructuredPrototypePendingOperation(
  projectId: string,
  operation: {
    operationKind: StructuredPrototypeClientOperationKind;
    resourceKind: StructuredPrototypePendingResourceKind;
    resourceId: string;
    contextId?: string | null;
    requestKey: string;
  },
): StructuredPrototypePendingOperation {
  if (!allowedPendingResourceKinds(operation.operationKind).includes(operation.resourceKind)) {
    throw new StructuredPrototypeStorageError(
      "Structured prototype pending operation resource does not match its operation kind",
    );
  }
  const contextId = operation.contextId ?? null;
  if (!pendingContextMatchesOperation(operation.operationKind, contextId)) {
    throw new StructuredPrototypeStorageError(
      "Structured prototype pending operation context does not match its operation kind",
    );
  }
  if (
    !pendingRequestKeyMatchesOperation(
      operation.operationKind,
      operation.resourceKind,
      contextId,
      operation.requestKey,
    )
  ) {
    throw new StructuredPrototypeStorageError(
      "Structured prototype pending operation request key does not match its operation",
    );
  }
  const existing = loadStructuredPrototypePendingOperation(projectId);
  if (existing !== null) {
    if (
      existing.operationKind === operation.operationKind &&
      existing.resourceKind === operation.resourceKind &&
      existing.resourceId === operation.resourceId &&
      existing.contextId === contextId &&
      existing.requestKey === operation.requestKey
    ) {
      return existing;
    }
    throw new StructuredPrototypeStorageError(
      `Structured prototype operation ${existing.operationKind} is still pending`,
    );
  }
  const descriptor: StructuredPrototypePendingOperation = {
    contractVersion: 1,
    projectId,
    operationKind: operation.operationKind,
    resourceKind: operation.resourceKind,
    resourceId: operation.resourceId,
    contextId,
    clientRequestId: structuredPrototypeRequestIdentity(projectId, operation.requestKey),
    requestKey: operation.requestKey,
    createdAt: new Date().toISOString(),
  };
  window.localStorage.setItem(
    structuredPrototypeStorageKey(projectId, STRUCTURED_PROTOTYPE_PENDING_OPERATION_KEY),
    JSON.stringify(descriptor),
  );
  return descriptor;
}

export function finishStructuredPrototypePendingOperation(
  projectId: string,
  clientRequestId: string,
): void {
  const descriptor = loadStructuredPrototypePendingOperation(projectId);
  if (descriptor === null) {
    throw new StructuredPrototypeStorageError(
      "Structured prototype pending operation is missing during completion",
    );
  }
  if (descriptor.clientRequestId !== clientRequestId) {
    throw new StructuredPrototypeStorageError(
      "Structured prototype pending operation identity changed during completion",
    );
  }
  finishStructuredPrototypeRequestIdentity(projectId, descriptor.requestKey);
  window.localStorage.removeItem(
    structuredPrototypeStorageKey(projectId, STRUCTURED_PROTOTYPE_PENDING_OPERATION_KEY),
  );
}

export function clearStructuredPrototypeProjectStorage(projectId: string): void {
  const prefix = `structured-prototype:${projectId}:`;
  for (let index = window.localStorage.length - 1; index >= 0; index -= 1) {
    const key = window.localStorage.key(index);
    if (key?.startsWith(prefix)) window.localStorage.removeItem(key);
  }
}
