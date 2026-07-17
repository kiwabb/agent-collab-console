import { canonicalRuntimeJson } from "@/features/prototype/runtime/canonical";
import { isRecord, safeJsonParse } from "@/lib/utils";

import {
  StructuredPrototypeFreeformMoveReplayError,
  attestStructuredPrototypeFreeformMoveEvidenceJson,
} from "./structuredPrototypeFreeformMoveReplay";
import {
  STRUCTURED_PROTOTYPE_SNAP_SOLVER_VERSION,
  STRUCTURED_PROTOTYPE_SNAP_SOURCE_HASH,
} from "./structuredPrototypeSnapBuildIdentity";

export const SNAP_WORKER_PROTOCOL_VERSION = "prototype-snap-worker/v1";
export const SNAP_WORKER_ATTEST_MANY_LIMIT = 200;
// Covers the largest schema-bounded evidence tail while keeping stdin finite.
export const SNAP_WORKER_MAX_REQUEST_BYTES = 32 * 1024 * 1024;

export type SnapWorkerAction = "describe" | "attest" | "attestMany";

interface SnapWorkerRequestBase {
  protocolVersion: typeof SNAP_WORKER_PROTOCOL_VERSION;
  requestId: string;
  action: SnapWorkerAction;
}

interface SnapWorkerDescribeRequest extends SnapWorkerRequestBase {
  action: "describe";
}

interface SnapWorkerAttestRequest extends SnapWorkerRequestBase {
  action: "attest";
  evidenceJson: string;
}

interface SnapWorkerAttestManyRequest extends SnapWorkerRequestBase {
  action: "attestMany";
  evidenceJsons: string[];
}

export type SnapWorkerRequest =
  SnapWorkerDescribeRequest | SnapWorkerAttestRequest | SnapWorkerAttestManyRequest;

export interface SnapWorkerIdentity {
  protocolVersion: typeof SNAP_WORKER_PROTOCOL_VERSION;
  snapSolverVersion: typeof STRUCTURED_PROTOTYPE_SNAP_SOLVER_VERSION;
  snapSolverSourceHash: typeof STRUCTURED_PROTOTYPE_SNAP_SOURCE_HASH;
}

interface SnapWorkerSuccessResponseBase extends SnapWorkerIdentity {
  requestId: string;
  status: "ok";
}

export interface SnapWorkerDescribeResponse extends SnapWorkerSuccessResponseBase {
  action: "describe";
  result: SnapWorkerIdentity;
}

export interface SnapWorkerAttestResponse extends SnapWorkerSuccessResponseBase {
  action: "attest";
  result: { evidenceHash: string };
}

export interface SnapWorkerAttestManyResponse extends SnapWorkerSuccessResponseBase {
  action: "attestMany";
  result: { evidenceHashes: string[] };
}

export type SnapWorkerSuccessResponse =
  SnapWorkerDescribeResponse | SnapWorkerAttestResponse | SnapWorkerAttestManyResponse;

export interface SnapWorkerErrorResponse extends SnapWorkerIdentity {
  requestId: string;
  action: SnapWorkerAction | "unknown";
  status: "error";
  error: {
    code: string;
    message: string;
  };
}

export type SnapWorkerResponse = SnapWorkerSuccessResponse | SnapWorkerErrorResponse;

export class SnapWorkerProtocolError extends Error {
  constructor(
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "SnapWorkerProtocolError";
  }
}

function identity(): SnapWorkerIdentity {
  return {
    protocolVersion: SNAP_WORKER_PROTOCOL_VERSION,
    snapSolverVersion: STRUCTURED_PROTOTYPE_SNAP_SOLVER_VERSION,
    snapSolverSourceHash: STRUCTURED_PROTOTYPE_SNAP_SOURCE_HASH,
  };
}

function requireExactKeys(
  record: Record<string, unknown>,
  expectedKeys: readonly string[],
  path: string,
): void {
  const expected = new Set(expectedKeys);
  for (const key of Object.keys(record)) {
    if (!expected.has(key)) {
      throw new SnapWorkerProtocolError(
        "snap_worker_request_invalid",
        `${path} contains an unknown field`,
      );
    }
  }
  for (const key of expectedKeys) {
    if (!Object.hasOwn(record, key)) {
      throw new SnapWorkerProtocolError(
        "snap_worker_request_invalid",
        `${path} is missing field ${key}`,
      );
    }
  }
}

function requireNonEmptyString(value: unknown, path: string): string {
  if (typeof value !== "string" || value.length === 0 || !value.isWellFormed()) {
    throw new SnapWorkerProtocolError(
      "snap_worker_request_invalid",
      `${path} must be a non-empty well-formed string`,
    );
  }
  return value;
}

function requireRequestId(value: unknown): string {
  const requestId = requireNonEmptyString(value, "request.requestId");
  if (requestId.length > 128) {
    throw new SnapWorkerProtocolError(
      "snap_worker_request_invalid",
      "request.requestId exceeds 128 characters",
    );
  }
  return requestId;
}

function requireAction(value: unknown): SnapWorkerAction {
  if (value === "describe" || value === "attest" || value === "attestMany") {
    return value;
  }
  throw new SnapWorkerProtocolError(
    "snap_worker_action_unsupported",
    "snap worker action is unsupported",
  );
}

function isSnapWorkerAction(value: unknown): value is SnapWorkerAction {
  return value === "describe" || value === "attest" || value === "attestMany";
}

function requireRequestRecord(value: unknown): Record<string, unknown> {
  if (!isRecord(value)) {
    throw new SnapWorkerProtocolError(
      "snap_worker_request_invalid",
      "snap worker request must be an object",
    );
  }
  return value;
}

function requireEvidenceJson(value: unknown, path: string): string {
  return requireNonEmptyString(value, path);
}

export function parseSnapWorkerRequest(value: unknown): SnapWorkerRequest {
  const record = requireRequestRecord(value);
  if (record["protocolVersion"] !== SNAP_WORKER_PROTOCOL_VERSION) {
    throw new SnapWorkerProtocolError(
      "snap_worker_protocol_mismatch",
      `snap worker protocol must equal ${SNAP_WORKER_PROTOCOL_VERSION}`,
    );
  }
  const requestId = requireRequestId(record["requestId"]);
  const action = requireAction(record["action"]);
  if (action === "describe") {
    requireExactKeys(record, ["protocolVersion", "requestId", "action"], "request");
    return { protocolVersion: SNAP_WORKER_PROTOCOL_VERSION, requestId, action };
  }
  if (action === "attest") {
    requireExactKeys(record, ["protocolVersion", "requestId", "action", "evidenceJson"], "request");
    return {
      protocolVersion: SNAP_WORKER_PROTOCOL_VERSION,
      requestId,
      action,
      evidenceJson: requireEvidenceJson(record["evidenceJson"], "request.evidenceJson"),
    };
  }
  requireExactKeys(record, ["protocolVersion", "requestId", "action", "evidenceJsons"], "request");
  const evidenceJsons = record["evidenceJsons"];
  if (!Array.isArray(evidenceJsons)) {
    throw new SnapWorkerProtocolError(
      "snap_worker_request_invalid",
      "request.evidenceJsons must be an array",
    );
  }
  if (evidenceJsons.length === 0 || evidenceJsons.length > SNAP_WORKER_ATTEST_MANY_LIMIT) {
    throw new SnapWorkerProtocolError(
      "snap_worker_request_invalid",
      `request.evidenceJsons must contain between 1 and ${SNAP_WORKER_ATTEST_MANY_LIMIT} items`,
    );
  }
  return {
    protocolVersion: SNAP_WORKER_PROTOCOL_VERSION,
    requestId,
    action,
    evidenceJsons: Array.from(evidenceJsons, (evidenceJson, index) =>
      requireEvidenceJson(evidenceJson, `request.evidenceJsons[${index}]`),
    ),
  };
}

export function parseSnapWorkerRequestJson(input: string): SnapWorkerRequest {
  const parsed = safeJsonParse(input);
  if (parsed === null) {
    throw new SnapWorkerProtocolError(
      "snap_worker_request_invalid_json",
      "snap worker request JSON is invalid",
    );
  }
  return parseSnapWorkerRequest(parsed);
}

export function readSnapWorkerRequestIdentityJson(input: string): {
  requestId: string;
  action: SnapWorkerAction | "unknown";
} {
  const parsed = safeJsonParse(input);
  if (!isRecord(parsed)) return { requestId: "unknown", action: "unknown" };
  const rawRequestId = parsed["requestId"];
  const requestId =
    typeof rawRequestId === "string" &&
    rawRequestId.length > 0 &&
    rawRequestId.length <= 128 &&
    rawRequestId.isWellFormed()
      ? rawRequestId
      : "unknown";
  return {
    requestId,
    action: isSnapWorkerAction(parsed["action"]) ? parsed["action"] : "unknown",
  };
}

function replayErrorCode(error: StructuredPrototypeFreeformMoveReplayError): string {
  if (
    error.code === "invalid_replay_input" ||
    error.code === "invalid_evidence_json" ||
    error.code === "invalid_evidence"
  ) {
    return "snap_evidence_invalid";
  }
  return "snap_attestation_mismatch";
}

async function attestEvidenceJson(evidenceJson: string): Promise<{ evidenceHash: string }> {
  try {
    return await attestStructuredPrototypeFreeformMoveEvidenceJson(evidenceJson);
  } catch (error: unknown) {
    if (error instanceof StructuredPrototypeFreeformMoveReplayError) {
      throw new SnapWorkerProtocolError(replayErrorCode(error), error.message);
    }
    throw error;
  }
}

export async function executeSnapWorkerRequest(
  request: SnapWorkerRequest,
): Promise<SnapWorkerSuccessResponse> {
  switch (request.action) {
    case "describe":
      return {
        ...identity(),
        requestId: request.requestId,
        action: request.action,
        status: "ok",
        result: identity(),
      };
    case "attest":
      return {
        ...identity(),
        requestId: request.requestId,
        action: request.action,
        status: "ok",
        result: await attestEvidenceJson(request.evidenceJson),
      };
    case "attestMany": {
      const evidenceHashes: string[] = [];
      for (const evidenceJson of request.evidenceJsons) {
        const attestation = await attestEvidenceJson(evidenceJson);
        evidenceHashes.push(attestation.evidenceHash);
      }
      return {
        ...identity(),
        requestId: request.requestId,
        action: request.action,
        status: "ok",
        result: { evidenceHashes },
      };
    }
  }
}

export function snapWorkerResponseJson(response: SnapWorkerResponse): string {
  return canonicalRuntimeJson(response);
}

export function snapWorkerErrorResponse(
  requestId: string,
  action: SnapWorkerAction | "unknown",
  code: string,
  message: string,
): SnapWorkerErrorResponse {
  const boundedMessage = Array.from(message.toWellFormed()).slice(0, 1_024).join("");
  return {
    ...identity(),
    requestId,
    action,
    status: "error",
    error: { code, message: boundedMessage },
  };
}
