import { RuntimeCoreError } from "../src/features/prototype/runtime/runtimeCore";
import { RuntimeInputCodecError } from "../src/features/prototype/runtime/runtimeInputCodec";
import { RuntimeStateCodecError } from "../src/features/prototype/runtime/runtimeStateCodec";
import {
  executeRuntimeWorkerRequest,
  parseRuntimeWorkerRequestJson,
  readRuntimeWorkerRequestIdentityJson,
  RuntimeWorkerProtocolError,
  runtimeWorkerErrorResponse,
  runtimeWorkerResponseJson,
} from "../src/features/prototype/runtime/runtimeWorkerProtocol";

const MAX_REQUEST_BYTES = 4 * 1024 * 1024;

interface WorkerFailure {
  code: string;
  message: string;
  internal: boolean;
}

function classifyFailure(error: unknown): WorkerFailure {
  if (error instanceof RuntimeWorkerProtocolError || error instanceof RuntimeCoreError) {
    return { code: error.code, message: error.message, internal: false };
  }
  if (error instanceof RuntimeInputCodecError) {
    return { code: "runtime_input_invalid", message: error.message, internal: false };
  }
  if (error instanceof RuntimeStateCodecError) {
    return { code: "runtime_state_invalid", message: error.message, internal: false };
  }
  return {
    code: "runtime_worker_internal_error",
    message: "runtime worker failed unexpectedly",
    internal: true,
  };
}

async function main(): Promise<void> {
  let requestId = "unknown";
  let action: "describe" | "initialize" | "apply" | "replay" | "unknown" = "unknown";
  try {
    process.stdin.setEncoding("utf8");
    let input = "";
    for await (const chunk of process.stdin) {
      if (typeof chunk !== "string") {
        throw new TypeError("runtime worker stdin did not decode as UTF-8 text");
      }
      input += chunk;
      if (Buffer.byteLength(input, "utf8") > MAX_REQUEST_BYTES) {
        throw new RuntimeWorkerProtocolError(
          "runtime_worker_request_too_large",
          "runtime worker request exceeds 4 MiB",
        );
      }
    }
    const requestIdentity = readRuntimeWorkerRequestIdentityJson(input);
    requestId = requestIdentity.requestId;
    action = requestIdentity.action;
    const request = parseRuntimeWorkerRequestJson(input);
    const response = await executeRuntimeWorkerRequest(request);
    process.stdout.write(`${runtimeWorkerResponseJson(response)}\n`);
  } catch (error: unknown) {
    const failure = classifyFailure(error);
    const response = runtimeWorkerErrorResponse(requestId, action, failure.code, failure.message);
    process.stdout.write(`${runtimeWorkerResponseJson(response)}\n`);
    if (failure.internal) {
      const details = error instanceof Error ? (error.stack ?? error.message) : String(error);
      process.stderr.write(`${details}\n`);
      process.exitCode = 1;
    }
  }
}

await main();
