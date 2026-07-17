import {
  executeSnapWorkerRequest,
  parseSnapWorkerRequestJson,
  readSnapWorkerRequestIdentityJson,
  SnapWorkerProtocolError,
  SNAP_WORKER_MAX_REQUEST_BYTES,
  snapWorkerErrorResponse,
  snapWorkerResponseJson,
  type SnapWorkerAction,
  type SnapWorkerResponse,
} from "../src/features/prototype/structured/structuredPrototypeSnapWorkerProtocol";

const MAX_RESPONSE_BYTES = 64 * 1024;

interface WorkerFailure {
  code: string;
  message: string;
  internal: boolean;
}

function classifyFailure(error: unknown): WorkerFailure {
  if (error instanceof SnapWorkerProtocolError) {
    return { code: error.code, message: error.message, internal: false };
  }
  return {
    code: "snap_worker_internal_error",
    message: "snap worker failed unexpectedly",
    internal: true,
  };
}

function writeBoundedResponse(response: SnapWorkerResponse): boolean {
  let responseJson = snapWorkerResponseJson(response);
  const withinLimit = Buffer.byteLength(responseJson, "utf8") <= MAX_RESPONSE_BYTES;
  if (!withinLimit) {
    responseJson = snapWorkerResponseJson(
      snapWorkerErrorResponse(
        "unknown",
        "unknown",
        "snap_worker_response_too_large",
        "snap worker response exceeds 64 KiB",
      ),
    );
  }
  process.stdout.write(`${responseJson}\n`);
  return withinLimit;
}

async function main(): Promise<void> {
  let requestId = "unknown";
  let action: SnapWorkerAction | "unknown" = "unknown";
  let response: SnapWorkerResponse;
  let internalDetails: string | null = null;

  try {
    process.stdin.setEncoding("utf8");
    let input = "";
    let inputBytes = 0;
    for await (const chunk of process.stdin) {
      if (typeof chunk !== "string") {
        throw new TypeError("snap worker stdin did not decode as UTF-8 text");
      }
      inputBytes += Buffer.byteLength(chunk, "utf8");
      if (inputBytes > SNAP_WORKER_MAX_REQUEST_BYTES) {
        throw new SnapWorkerProtocolError(
          "snap_worker_request_too_large",
          `snap worker request exceeds ${SNAP_WORKER_MAX_REQUEST_BYTES / (1024 * 1024)} MiB`,
        );
      }
      input += chunk;
    }
    const requestIdentity = readSnapWorkerRequestIdentityJson(input);
    requestId = requestIdentity.requestId;
    action = requestIdentity.action;
    const request = parseSnapWorkerRequestJson(input);
    response = await executeSnapWorkerRequest(request);
  } catch (error: unknown) {
    const failure = classifyFailure(error);
    response = snapWorkerErrorResponse(requestId, action, failure.code, failure.message);
    if (failure.internal) {
      internalDetails = error instanceof Error ? (error.stack ?? error.message) : String(error);
    }
  }

  if (!writeBoundedResponse(response)) {
    process.exitCode = 1;
  }
  if (internalDetails !== null) {
    process.stderr.write(`${internalDetails}\n`);
    process.exitCode = 1;
  }
}

await main();
