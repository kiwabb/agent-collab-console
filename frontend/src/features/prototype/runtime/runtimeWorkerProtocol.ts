import { isRecord, safeJsonParse } from "@/lib/utils";

import { canonicalRuntimeJson, hashRuntimeValue } from "./canonical";
import { RUNTIME_CORE_SOURCE_HASH } from "./runtimeBuildIdentity";
import {
  applyRuntimeEventBatch,
  createInitialRuntimeState,
  deriveRuntimeViewModel,
  RUNTIME_CORE_VERSION,
  XSTATE_KERNEL_VERSION,
} from "./runtimeCore";
import { parseRuntimeDefinition, parseRuntimeEventBatch } from "./runtimeInputCodec";
import {
  parsePrototypeRuntimeStateJson,
  serializePrototypeRuntimeState,
} from "./runtimeStateCodec";
import type {
  PrototypeRuntimeState,
  RuntimeDefinition,
  RuntimeEventBatch,
  RuntimeTransitionReport,
  RuntimeViewModel,
} from "./types";

export const RUNTIME_WORKER_PROTOCOL_VERSION = "prototype-runtime-worker/v1";

type RuntimeWorkerAction = "describe" | "initialize" | "apply" | "replay";

interface RuntimeWorkerRequestBase {
  protocolVersion: typeof RUNTIME_WORKER_PROTOCOL_VERSION;
  requestId: string;
  action: RuntimeWorkerAction;
}

interface RuntimeWorkerDescribeRequest extends RuntimeWorkerRequestBase {
  action: "describe";
}

interface RuntimeWorkerInitializeRequest extends RuntimeWorkerRequestBase {
  action: "initialize";
  definition: RuntimeDefinition;
  scenarioId: string;
  sessionId: string;
}

interface RuntimeWorkerApplyRequest extends RuntimeWorkerRequestBase {
  action: "apply";
  definition: RuntimeDefinition;
  state: PrototypeRuntimeState;
  batch: RuntimeEventBatch;
}

interface RuntimeWorkerReplayRequest extends RuntimeWorkerRequestBase {
  action: "replay";
  definition: RuntimeDefinition;
  state: PrototypeRuntimeState;
  batches: RuntimeEventBatch[];
}

export type RuntimeWorkerRequest =
  | RuntimeWorkerDescribeRequest
  | RuntimeWorkerInitializeRequest
  | RuntimeWorkerApplyRequest
  | RuntimeWorkerReplayRequest;

interface RuntimeWorkerIdentity {
  protocolVersion: typeof RUNTIME_WORKER_PROTOCOL_VERSION;
  runtimeCoreVersion: string;
  runtimeCoreSourceHash: string;
  stateMachineKernelVersion: string;
}

export interface RuntimeWorkerStateResult {
  stateJson: string;
  stateHash: string;
  viewModelJson: string;
  viewModelHash: string;
}

export interface RuntimeWorkerTransitionResult extends RuntimeWorkerStateResult {
  eventsJson: string;
  eventBatchJson: string;
  eventBatchHash: string;
  matchedRuleIdsJson: string;
  guardReportJson: string;
  guardReportHash: string;
  effectReportJson: string;
  effectReportHash: string;
  report: RuntimeTransitionReport;
}

export interface RuntimeWorkerReplayResult {
  transitions: RuntimeWorkerTransitionResult[];
  final: RuntimeWorkerStateResult;
}

interface RuntimeWorkerSuccessResponseBase extends RuntimeWorkerIdentity {
  requestId: string;
  status: "ok";
}

export interface RuntimeWorkerDescribeResponse extends RuntimeWorkerSuccessResponseBase {
  action: "describe";
  result: RuntimeWorkerIdentity;
}

export interface RuntimeWorkerInitializeResponse extends RuntimeWorkerSuccessResponseBase {
  action: "initialize";
  result: RuntimeWorkerStateResult;
}

export interface RuntimeWorkerApplyResponse extends RuntimeWorkerSuccessResponseBase {
  action: "apply";
  result: RuntimeWorkerTransitionResult;
}

export interface RuntimeWorkerReplayResponse extends RuntimeWorkerSuccessResponseBase {
  action: "replay";
  result: RuntimeWorkerReplayResult;
}

export type RuntimeWorkerSuccessResponse =
  | RuntimeWorkerDescribeResponse
  | RuntimeWorkerInitializeResponse
  | RuntimeWorkerApplyResponse
  | RuntimeWorkerReplayResponse;

export interface RuntimeWorkerErrorResponse extends RuntimeWorkerIdentity {
  requestId: string;
  action: RuntimeWorkerAction | "unknown";
  status: "error";
  error: {
    code: string;
    message: string;
  };
}

export type RuntimeWorkerResponse = RuntimeWorkerSuccessResponse | RuntimeWorkerErrorResponse;

export class RuntimeWorkerProtocolError extends Error {
  constructor(
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "RuntimeWorkerProtocolError";
  }
}

function identity(): RuntimeWorkerIdentity {
  return {
    protocolVersion: RUNTIME_WORKER_PROTOCOL_VERSION,
    runtimeCoreVersion: RUNTIME_CORE_VERSION,
    runtimeCoreSourceHash: RUNTIME_CORE_SOURCE_HASH,
    stateMachineKernelVersion: XSTATE_KERNEL_VERSION,
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
      throw new RuntimeWorkerProtocolError(
        "runtime_worker_request_invalid",
        `${path} contains unknown field ${key}`,
      );
    }
  }
  for (const key of expectedKeys) {
    if (!Object.hasOwn(record, key)) {
      throw new RuntimeWorkerProtocolError(
        "runtime_worker_request_invalid",
        `${path} is missing field ${key}`,
      );
    }
  }
}

function requireNonEmptyString(value: unknown, path: string): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new RuntimeWorkerProtocolError(
      "runtime_worker_request_invalid",
      `${path} must be a non-empty string`,
    );
  }
  return value;
}

function requireAction(value: unknown): RuntimeWorkerAction {
  if (value === "describe" || value === "initialize" || value === "apply" || value === "replay") {
    return value;
  }
  throw new RuntimeWorkerProtocolError(
    "runtime_worker_action_unsupported",
    "runtime worker action is unsupported",
  );
}

function isRuntimeWorkerAction(value: unknown): value is RuntimeWorkerAction {
  return value === "describe" || value === "initialize" || value === "apply" || value === "replay";
}

function requireRequestRecord(value: unknown): Record<string, unknown> {
  if (!isRecord(value)) {
    throw new RuntimeWorkerProtocolError(
      "runtime_worker_request_invalid",
      "runtime worker request must be an object",
    );
  }
  return value;
}

export function parseRuntimeWorkerRequest(value: unknown): RuntimeWorkerRequest {
  const record = requireRequestRecord(value);
  if (record["protocolVersion"] !== RUNTIME_WORKER_PROTOCOL_VERSION) {
    throw new RuntimeWorkerProtocolError(
      "runtime_worker_protocol_mismatch",
      `runtime worker protocol must equal ${RUNTIME_WORKER_PROTOCOL_VERSION}`,
    );
  }
  const requestId = requireNonEmptyString(record["requestId"], "request.requestId");
  const action = requireAction(record["action"]);
  if (action === "describe") {
    requireExactKeys(record, ["protocolVersion", "requestId", "action"], "request");
    return { protocolVersion: RUNTIME_WORKER_PROTOCOL_VERSION, requestId, action };
  }
  if (action === "initialize") {
    requireExactKeys(
      record,
      ["protocolVersion", "requestId", "action", "definition", "scenarioId", "sessionId"],
      "request",
    );
    return {
      protocolVersion: RUNTIME_WORKER_PROTOCOL_VERSION,
      requestId,
      action,
      definition: parseRuntimeDefinition(record["definition"]),
      scenarioId: requireNonEmptyString(record["scenarioId"], "request.scenarioId"),
      sessionId: requireNonEmptyString(record["sessionId"], "request.sessionId"),
    };
  }
  if (action === "apply") {
    requireExactKeys(
      record,
      ["protocolVersion", "requestId", "action", "definition", "stateJson", "batch"],
      "request",
    );
    return {
      protocolVersion: RUNTIME_WORKER_PROTOCOL_VERSION,
      requestId,
      action,
      definition: parseRuntimeDefinition(record["definition"]),
      state: parsePrototypeRuntimeStateJson(
        requireNonEmptyString(record["stateJson"], "request.stateJson"),
      ),
      batch: parseRuntimeEventBatch(record["batch"]),
    };
  }
  requireExactKeys(
    record,
    ["protocolVersion", "requestId", "action", "definition", "stateJson", "batches"],
    "request",
  );
  if (!Array.isArray(record["batches"])) {
    throw new RuntimeWorkerProtocolError(
      "runtime_worker_request_invalid",
      "request.batches must be an array",
    );
  }
  if (record["batches"].length > 200) {
    throw new RuntimeWorkerProtocolError(
      "runtime_worker_replay_tail_limit_exceeded",
      "runtime worker replay tail exceeds 200 event batches",
    );
  }
  return {
    protocolVersion: RUNTIME_WORKER_PROTOCOL_VERSION,
    requestId,
    action,
    definition: parseRuntimeDefinition(record["definition"]),
    state: parsePrototypeRuntimeStateJson(
      requireNonEmptyString(record["stateJson"], "request.stateJson"),
    ),
    batches: record["batches"].map((batch, index) =>
      parseRuntimeEventBatch(batch, `request.batches[${index}]`),
    ),
  };
}

export function parseRuntimeWorkerRequestJson(input: string): RuntimeWorkerRequest {
  const parsed = safeJsonParse(input);
  if (parsed === null) {
    throw new RuntimeWorkerProtocolError(
      "runtime_worker_request_invalid_json",
      "runtime worker request JSON is invalid",
    );
  }
  return parseRuntimeWorkerRequest(parsed);
}

export function readRuntimeWorkerRequestIdentityJson(input: string): {
  requestId: string;
  action: RuntimeWorkerAction | "unknown";
} {
  const parsed = safeJsonParse(input);
  if (!isRecord(parsed)) {
    return { requestId: "unknown", action: "unknown" };
  }
  return {
    requestId:
      typeof parsed["requestId"] === "string" && parsed["requestId"].length > 0
        ? parsed["requestId"]
        : "unknown",
    action: isRuntimeWorkerAction(parsed["action"]) ? parsed["action"] : "unknown",
  };
}

async function stateResult(
  state: PrototypeRuntimeState,
  viewModel: RuntimeViewModel,
): Promise<RuntimeWorkerStateResult> {
  const [stateHash, viewModelHash] = await Promise.all([
    hashRuntimeValue(state),
    hashRuntimeValue(viewModel),
  ]);
  return {
    stateJson: serializePrototypeRuntimeState(state),
    stateHash,
    viewModelJson: canonicalRuntimeJson(viewModel),
    viewModelHash,
  };
}

async function apply(
  definition: RuntimeDefinition,
  state: PrototypeRuntimeState,
  batch: RuntimeEventBatch,
): Promise<RuntimeWorkerTransitionResult> {
  const transition = await applyRuntimeEventBatch(definition, state, batch);
  const guardReport = {
    outcome: transition.report.outcome,
    matchedRuleIds: transition.report.matchedRuleIds,
  };
  const effectReport = { effects: transition.report.effects };
  const [base, eventBatchHash, guardReportHash, effectReportHash] = await Promise.all([
    stateResult(transition.state, transition.viewModel),
    hashRuntimeValue(batch),
    hashRuntimeValue(guardReport),
    hashRuntimeValue(effectReport),
  ]);
  if (
    base.stateHash !== transition.report.resultStateHash ||
    base.viewModelHash !== transition.report.resultViewModelHash
  ) {
    throw new RuntimeWorkerProtocolError(
      "runtime_worker_transition_hash_mismatch",
      "runtime worker transition result does not match its report hashes",
    );
  }
  return {
    ...base,
    eventsJson: canonicalRuntimeJson(batch.events),
    eventBatchJson: canonicalRuntimeJson(batch),
    eventBatchHash,
    matchedRuleIdsJson: canonicalRuntimeJson(transition.report.matchedRuleIds),
    guardReportJson: canonicalRuntimeJson(guardReport),
    guardReportHash,
    effectReportJson: canonicalRuntimeJson(effectReport),
    effectReportHash,
    report: transition.report,
  };
}

export async function executeRuntimeWorkerRequest(
  request: RuntimeWorkerRequest,
): Promise<RuntimeWorkerSuccessResponse> {
  switch (request.action) {
    case "describe":
      return {
        ...identity(),
        requestId: request.requestId,
        action: request.action,
        status: "ok",
        result: identity(),
      };
    case "initialize": {
      const state = createInitialRuntimeState(
        request.definition,
        request.scenarioId,
        request.sessionId,
      );
      return {
        ...identity(),
        requestId: request.requestId,
        action: request.action,
        status: "ok",
        result: await stateResult(state, deriveRuntimeViewModel(request.definition, state)),
      };
    }
    case "apply":
      return {
        ...identity(),
        requestId: request.requestId,
        action: request.action,
        status: "ok",
        result: await apply(request.definition, request.state, request.batch),
      };
    case "replay": {
      const transitions: RuntimeWorkerTransitionResult[] = [];
      let state = request.state;
      for (const batch of request.batches) {
        const transition = await apply(request.definition, state, batch);
        transitions.push(transition);
        state = parsePrototypeRuntimeStateJson(transition.stateJson);
      }
      return {
        ...identity(),
        requestId: request.requestId,
        action: request.action,
        status: "ok",
        result: {
          transitions,
          final: await stateResult(state, deriveRuntimeViewModel(request.definition, state)),
        },
      };
    }
  }
}

export function runtimeWorkerResponseJson(response: RuntimeWorkerResponse): string {
  return canonicalRuntimeJson(response);
}

export function runtimeWorkerErrorResponse(
  requestId: string,
  action: RuntimeWorkerAction | "unknown",
  code: string,
  message: string,
): RuntimeWorkerErrorResponse {
  return {
    ...identity(),
    requestId,
    action,
    status: "error",
    error: { code, message },
  };
}
