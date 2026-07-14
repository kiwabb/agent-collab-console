import { createHash } from "node:crypto";

import { canonicalRuntimeJson } from "../src/features/prototype/runtime/canonical";
import {
  RUNTIME_CORE_VERSION,
  XSTATE_KERNEL_VERSION,
} from "../src/features/prototype/runtime/runtimeCore";
import { RUNTIME_CORE_SOURCE_HASH } from "../src/features/prototype/runtime/runtimeBuildIdentity";
import {
  PROTOTYPE_RENDERER_ENVIRONMENT_VERSION,
  PROTOTYPE_RENDERER_SANDBOX_POLICY_VERSION,
  PROTOTYPE_RENDERER_VERSION,
  PrototypeRendererError,
  renderPrototypeDocument,
} from "../src/features/prototype/structured/prototypeRendererCore";
import {
  parseRendererDocument,
  RendererDocumentCodecError,
} from "../src/features/prototype/structured/rendererDocumentCodec";

declare const __PUBLIC_RUNTIME_SOURCE__: string;
declare const __PUBLIC_RUNTIME_BUNDLE_HASH__: string;
declare const __RENDER_RUNTIME_IMAGE_HASH__: string;
declare const __FONT_PACK_HASH__: string;
declare const __VIEWPORT_PROFILE_HASH__: string;

const PROTOCOL_VERSION = "prototype-renderer-worker/v1";
const MAX_REQUEST_BYTES = 4 * 1024 * 1024;

interface RendererInputManifest {
  rendererVersion: string;
  rendererEnvironmentVersion: string;
  runtimeCoreVersion: string;
  runtimeCoreSourceHash: string;
  runtimeCoreBundleHash: string;
  stateMachineKernelVersion: string;
  renderRuntimeImageHash: string;
  browserVersion: string;
  fontPackHash: string;
  viewportProfileHash: string;
  documentObjectHash: string;
  documentSchemaVersion: number;
  assetObjectHashes: string[];
  sandboxPolicyVersion: string;
  outputLocale: "zh-CN" | "en-US";
}

interface RequestIdentity {
  requestId: string;
  action: "describe" | "render" | "unknown";
}

class RendererWorkerProtocolError extends Error {
  constructor(
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "RendererWorkerProtocolError";
  }
}

function sha256(value: string | Buffer): string {
  return `sha256:${createHash("sha256").update(value).digest("hex")}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function record(value: unknown, path: string): Record<string, unknown> {
  if (!isRecord(value))
    throw new RendererWorkerProtocolError("renderer_request_invalid", `${path} must be an object`);
  return value;
}

function exactKeys(value: Record<string, unknown>, keys: readonly string[], path: string): void {
  const expected = new Set(keys);
  for (const key of Object.keys(value)) {
    if (!expected.has(key))
      throw new RendererWorkerProtocolError(
        "renderer_request_invalid",
        `${path} contains unknown field ${key}`,
      );
  }
  for (const key of keys) {
    if (!Object.hasOwn(value, key))
      throw new RendererWorkerProtocolError(
        "renderer_request_invalid",
        `${path} is missing field ${key}`,
      );
  }
}

function string(value: unknown, path: string): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new RendererWorkerProtocolError(
      "renderer_request_invalid",
      `${path} must be a non-empty string`,
    );
  }
  return value;
}

function hash(value: unknown, path: string): string {
  const parsed = string(value, path);
  if (!/^sha256:[0-9a-f]{64}$/u.test(parsed)) {
    throw new RendererWorkerProtocolError(
      "renderer_request_invalid",
      `${path} must be a SHA-256 hash`,
    );
  }
  return parsed;
}

function inputManifest(value: unknown): RendererInputManifest {
  const item = record(value, "inputManifest");
  exactKeys(
    item,
    [
      "rendererVersion",
      "rendererEnvironmentVersion",
      "runtimeCoreVersion",
      "runtimeCoreSourceHash",
      "runtimeCoreBundleHash",
      "stateMachineKernelVersion",
      "renderRuntimeImageHash",
      "browserVersion",
      "fontPackHash",
      "viewportProfileHash",
      "documentObjectHash",
      "documentSchemaVersion",
      "assetObjectHashes",
      "sandboxPolicyVersion",
      "outputLocale",
    ],
    "inputManifest",
  );
  const assets = item["assetObjectHashes"];
  if (!Array.isArray(assets))
    throw new RendererWorkerProtocolError(
      "renderer_request_invalid",
      "inputManifest.assetObjectHashes must be an array",
    );
  const parsedAssets = assets.map((asset, index) =>
    hash(asset, `inputManifest.assetObjectHashes[${index}]`),
  );
  if (parsedAssets.some((asset, index) => index > 0 && (parsedAssets[index - 1] ?? "") >= asset)) {
    throw new RendererWorkerProtocolError(
      "renderer_request_invalid",
      "inputManifest.assetObjectHashes must be unique and sorted",
    );
  }
  if (item["documentSchemaVersion"] !== 1) {
    throw new RendererWorkerProtocolError(
      "renderer_schema_unsupported",
      "renderer only supports document schema version 1",
    );
  }
  const locale = item["outputLocale"];
  if (locale !== "zh-CN" && locale !== "en-US") {
    throw new RendererWorkerProtocolError(
      "renderer_request_invalid",
      "inputManifest.outputLocale is unsupported",
    );
  }
  return {
    rendererVersion: string(item["rendererVersion"], "inputManifest.rendererVersion"),
    rendererEnvironmentVersion: string(
      item["rendererEnvironmentVersion"],
      "inputManifest.rendererEnvironmentVersion",
    ),
    runtimeCoreVersion: string(item["runtimeCoreVersion"], "inputManifest.runtimeCoreVersion"),
    runtimeCoreSourceHash: hash(
      item["runtimeCoreSourceHash"],
      "inputManifest.runtimeCoreSourceHash",
    ),
    runtimeCoreBundleHash: hash(
      item["runtimeCoreBundleHash"],
      "inputManifest.runtimeCoreBundleHash",
    ),
    stateMachineKernelVersion: string(
      item["stateMachineKernelVersion"],
      "inputManifest.stateMachineKernelVersion",
    ),
    renderRuntimeImageHash: hash(
      item["renderRuntimeImageHash"],
      "inputManifest.renderRuntimeImageHash",
    ),
    browserVersion: string(item["browserVersion"], "inputManifest.browserVersion"),
    fontPackHash: hash(item["fontPackHash"], "inputManifest.fontPackHash"),
    viewportProfileHash: hash(item["viewportProfileHash"], "inputManifest.viewportProfileHash"),
    documentObjectHash: hash(item["documentObjectHash"], "inputManifest.documentObjectHash"),
    documentSchemaVersion: 1,
    assetObjectHashes: parsedAssets,
    sandboxPolicyVersion: string(
      item["sandboxPolicyVersion"],
      "inputManifest.sandboxPolicyVersion",
    ),
    outputLocale: locale,
  };
}

function assertCompatibility(manifest: RendererInputManifest): void {
  const expected = {
    rendererVersion: PROTOTYPE_RENDERER_VERSION,
    rendererEnvironmentVersion: PROTOTYPE_RENDERER_ENVIRONMENT_VERSION,
    runtimeCoreVersion: RUNTIME_CORE_VERSION,
    runtimeCoreSourceHash: RUNTIME_CORE_SOURCE_HASH,
    runtimeCoreBundleHash: __PUBLIC_RUNTIME_BUNDLE_HASH__,
    stateMachineKernelVersion: XSTATE_KERNEL_VERSION,
    renderRuntimeImageHash: __RENDER_RUNTIME_IMAGE_HASH__,
    browserVersion: "web-platform-es2022/1",
    fontPackHash: __FONT_PACK_HASH__,
    viewportProfileHash: __VIEWPORT_PROFILE_HASH__,
    sandboxPolicyVersion: PROTOTYPE_RENDERER_SANDBOX_POLICY_VERSION,
  } as const;
  for (const [key, expectedValue] of Object.entries(expected)) {
    if (manifest[key as keyof typeof expected] !== expectedValue) {
      throw new RendererWorkerProtocolError(
        "renderer_compatibility_mismatch",
        `inputManifest.${key} does not match the renderer compatibility row`,
      );
    }
  }
}

function identity() {
  return {
    protocolVersion: PROTOCOL_VERSION,
    rendererVersion: PROTOTYPE_RENDERER_VERSION,
    rendererEnvironmentVersion: PROTOTYPE_RENDERER_ENVIRONMENT_VERSION,
    runtimeCoreVersion: RUNTIME_CORE_VERSION,
    runtimeCoreSourceHash: RUNTIME_CORE_SOURCE_HASH,
    runtimeCoreBundleHash: __PUBLIC_RUNTIME_BUNDLE_HASH__,
    stateMachineKernelVersion: XSTATE_KERNEL_VERSION,
    renderRuntimeImageHash: __RENDER_RUNTIME_IMAGE_HASH__,
    browserVersion: "web-platform-es2022/1",
    fontPackHash: __FONT_PACK_HASH__,
    viewportProfileHash: __VIEWPORT_PROFILE_HASH__,
    sandboxPolicyVersion: PROTOTYPE_RENDERER_SANDBOX_POLICY_VERSION,
  };
}

function readIdentity(input: string): RequestIdentity {
  let decoded: unknown;
  try {
    decoded = JSON.parse(input);
  } catch (error) {
    throw new RendererWorkerProtocolError(
      "renderer_request_invalid",
      "renderer request is not valid JSON",
    );
  }
  if (!isRecord(decoded)) return { requestId: "unknown", action: "unknown" };
  const requestId = typeof decoded["requestId"] === "string" ? decoded["requestId"] : "unknown";
  const action = decoded["action"];
  return { requestId, action: action === "describe" || action === "render" ? action : "unknown" };
}

function render(request: Record<string, unknown>) {
  exactKeys(
    request,
    ["protocolVersion", "requestId", "action", "artifactId", "inputManifest", "document"],
    "request",
  );
  if (request["protocolVersion"] !== PROTOCOL_VERSION || request["action"] !== "render") {
    throw new RendererWorkerProtocolError(
      "renderer_request_invalid",
      "renderer request identity is invalid",
    );
  }
  const requestId = string(request["requestId"], "request.requestId");
  const artifactId = string(request["artifactId"], "request.artifactId");
  const manifest = inputManifest(request["inputManifest"]);
  assertCompatibility(manifest);
  const documentValue = parseRendererDocument(request["document"]);
  if (documentValue.locale !== manifest.outputLocale) {
    throw new RendererWorkerProtocolError(
      "renderer_locale_mismatch",
      "document locale does not match renderer output locale",
    );
  }
  if (documentValue.assetRefs.length !== manifest.assetObjectHashes.length) {
    throw new RendererWorkerProtocolError(
      "renderer_asset_manifest_mismatch",
      "document assets do not match renderer input manifest",
    );
  }
  const documentJson = canonicalRuntimeJson(documentValue);
  if (sha256(documentJson) !== manifest.documentObjectHash) {
    throw new RendererWorkerProtocolError(
      "renderer_document_hash_mismatch",
      "document does not match renderer input manifest",
    );
  }
  const inputManifestHash = sha256(canonicalRuntimeJson(manifest));
  const rendered = renderPrototypeDocument(
    documentValue,
    documentJson,
    manifest.documentObjectHash,
    __PUBLIC_RUNTIME_SOURCE__,
  );
  const files = rendered.files.map((file) => {
    const bytes = Buffer.from(file.content, "utf8");
    return {
      relativePath: file.relativePath,
      byteSize: bytes.byteLength,
      contentHash: sha256(bytes),
      contentBase64: bytes.toString("base64"),
    };
  });
  const descriptors = files.map(({ relativePath, byteSize, contentHash }) => ({
    relativePath,
    byteSize,
    contentHash,
  }));
  const bundleHash = sha256(canonicalRuntimeJson(descriptors));
  const visualPreflightReportHash = sha256(canonicalRuntimeJson(rendered.preflight));
  const outputManifest = {
    contractVersion: 1,
    rendererVersion: manifest.rendererVersion,
    rendererEnvironmentVersion: manifest.rendererEnvironmentVersion,
    runtimeCoreVersion: manifest.runtimeCoreVersion,
    runtimeCoreSourceHash: manifest.runtimeCoreSourceHash,
    runtimeCoreBundleHash: manifest.runtimeCoreBundleHash,
    stateMachineKernelVersion: manifest.stateMachineKernelVersion,
    inputManifestHash,
    documentObjectHash: manifest.documentObjectHash,
    artifactId,
    files: descriptors,
    bundleHash,
    visualPreflightReportHash,
  };
  return {
    ...identity(),
    requestId,
    action: "render",
    status: "ok",
    result: {
      inputManifestHash,
      outputManifest,
      outputManifestHash: sha256(canonicalRuntimeJson(outputManifest)),
      visualPreflightReport: rendered.preflight,
      visualPreflightReportHash,
      bundleHash,
      files,
    },
  };
}

function execute(input: string) {
  const decoded = record(JSON.parse(input), "request");
  if (decoded["action"] === "describe") {
    exactKeys(decoded, ["protocolVersion", "requestId", "action"], "request");
    if (decoded["protocolVersion"] !== PROTOCOL_VERSION) {
      throw new RendererWorkerProtocolError(
        "renderer_request_invalid",
        "renderer protocol version is unsupported",
      );
    }
    return {
      ...identity(),
      requestId: string(decoded["requestId"], "request.requestId"),
      action: "describe",
      status: "ok",
      result: identity(),
    };
  }
  return render(decoded);
}

function failure(error: unknown): { code: string; message: string; internal: boolean } {
  if (error instanceof RendererWorkerProtocolError || error instanceof PrototypeRendererError) {
    return { code: error.code, message: error.message, internal: false };
  }
  if (error instanceof RendererDocumentCodecError) {
    return { code: "renderer_document_invalid", message: error.message, internal: false };
  }
  return {
    code: "renderer_internal_error",
    message: "renderer failed unexpectedly",
    internal: true,
  };
}

async function main(): Promise<void> {
  let input = "";
  process.stdin.setEncoding("utf8");
  for await (const chunk of process.stdin) {
    if (typeof chunk !== "string") throw new TypeError("renderer stdin did not decode as UTF-8");
    input += chunk;
    if (Buffer.byteLength(input, "utf8") > MAX_REQUEST_BYTES) {
      throw new RendererWorkerProtocolError(
        "renderer_request_too_large",
        "renderer request exceeds 4 MiB",
      );
    }
  }
  const request = readIdentity(input);
  try {
    process.stdout.write(`${canonicalRuntimeJson(execute(input))}\n`);
  } catch (error: unknown) {
    const result = failure(error);
    process.stdout.write(
      `${canonicalRuntimeJson({ ...identity(), requestId: request.requestId, action: request.action, status: "error", error: { code: result.code, message: result.message } })}\n`,
    );
    if (result.internal) {
      process.stderr.write(
        `${error instanceof Error ? (error.stack ?? error.message) : String(error)}\n`,
      );
      process.exitCode = 1;
    }
  }
}

void main().catch((error: unknown) => {
  process.stderr.write(
    `${error instanceof Error ? (error.stack ?? error.message) : String(error)}\n`,
  );
  process.exitCode = 1;
});
