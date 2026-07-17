import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { build, version as esbuildVersion } from "esbuild";

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repositoryRoot = resolve(frontendRoot, "..");
const outputDirectory = resolve(repositoryRoot, "backend/app/runtime_assets");
const publicRuntimePath = resolve(outputDirectory, "prototype_public_runtime.js");
const workerPath = resolve(outputDirectory, "prototype_renderer_worker.mjs");
const manifestPath = resolve(outputDirectory, "prototype_renderer_worker.manifest.json");
const protocolVersion = "prototype-renderer-worker/v1";

const sourceFiles = [
  "src/features/prototype/runtime/canonical.ts",
  "src/features/prototype/runtime/runtimeBuildIdentity.ts",
  "src/features/prototype/runtime/runtimeCore.ts",
  "src/features/prototype/runtime/runtimeInputCodec.ts",
  "src/features/prototype/runtime/types.ts",
  "src/features/prototype/structured/prototypeRendererCore.ts",
  "src/features/prototype/structured/rendererDocumentCodec.ts",
  "src/features/prototype/structured/structuredPrototypeDerived.ts",
  "src/features/prototype/structured/structuredPrototypeNodes.ts",
  "src/features/prototype/structured/types.ts",
  "src/lib/utils.tsx",
  "scripts/prototype-public-runtime.ts",
  "scripts/prototype-renderer-worker.ts",
];

function sha256(value) {
  return `sha256:${createHash("sha256").update(value).digest("hex")}`;
}

async function writeAtomically(path, value) {
  const temporary = `${path}.tmp-${process.pid}`;
  await writeFile(temporary, value);
  await rename(temporary, path);
}

await mkdir(outputDirectory, { recursive: true });

const publicBuild = await build({
  absWorkingDir: frontendRoot,
  bundle: true,
  charset: "utf8",
  entryPoints: ["scripts/prototype-public-runtime.ts"],
  format: "iife",
  legalComments: "none",
  logLevel: "silent",
  minify: true,
  platform: "browser",
  sourcemap: false,
  target: ["es2022"],
  treeShaking: true,
  tsconfig: resolve(frontendRoot, "tsconfig.json"),
  write: false,
});
const publicOutput = publicBuild.outputFiles?.[0];
if (publicOutput === undefined)
  throw new Error("prototype public runtime build produced no bundle");
const publicRuntimeBytes = Buffer.from(publicOutput.contents);
const publicRuntimeHash = sha256(publicRuntimeBytes);
await writeAtomically(publicRuntimePath, publicRuntimeBytes);

const renderRuntimeImageHash = sha256(
  Buffer.from(JSON.stringify({ node: "20", platform: "node", renderer: "static-bundle-v1" })),
);
const fontPackHash = sha256(Buffer.from(JSON.stringify(["Inter", "system-ui", "sans-serif"])));
const viewportProfileHash = sha256(
  Buffer.from(
    JSON.stringify([
      { key: "desktop", width: 1440, height: 900 },
      { key: "mobile", width: 390, height: 844 },
    ]),
  ),
);

const workerBuild = await build({
  absWorkingDir: frontendRoot,
  bundle: true,
  charset: "utf8",
  define: {
    __PUBLIC_RUNTIME_SOURCE__: JSON.stringify(publicRuntimeBytes.toString("utf8")),
    __PUBLIC_RUNTIME_BUNDLE_HASH__: JSON.stringify(publicRuntimeHash),
    __RENDER_RUNTIME_IMAGE_HASH__: JSON.stringify(renderRuntimeImageHash),
    __FONT_PACK_HASH__: JSON.stringify(fontPackHash),
    __VIEWPORT_PROFILE_HASH__: JSON.stringify(viewportProfileHash),
  },
  entryPoints: ["scripts/prototype-renderer-worker.ts"],
  format: "esm",
  legalComments: "none",
  logLevel: "silent",
  minify: false,
  platform: "node",
  sourcemap: false,
  target: ["node20"],
  treeShaking: true,
  tsconfig: resolve(frontendRoot, "tsconfig.json"),
  write: false,
});
const workerOutput = workerBuild.outputFiles?.[0];
if (workerOutput === undefined)
  throw new Error("prototype renderer worker build produced no bundle");
const workerBytes = Buffer.from(workerOutput.contents);
const workerHash = sha256(workerBytes);
await writeAtomically(workerPath, workerBytes);

const describe = spawnSync(process.execPath, [workerPath], {
  encoding: "utf8",
  input: JSON.stringify({ protocolVersion, requestId: "build-identity-check", action: "describe" }),
  maxBuffer: 2 * 1024 * 1024,
});
if (describe.status !== 0) {
  throw new Error(`prototype renderer worker describe failed: ${describe.stderr.trim()}`);
}
const identity = JSON.parse(describe.stdout);
if (
  identity.status !== "ok" ||
  identity.protocolVersion !== protocolVersion ||
  identity.runtimeCoreBundleHash !== publicRuntimeHash ||
  identity.renderRuntimeImageHash !== renderRuntimeImageHash ||
  identity.fontPackHash !== fontPackHash ||
  identity.viewportProfileHash !== viewportProfileHash
) {
  throw new Error("prototype renderer worker identity does not match its build inputs");
}

const sources = [];
for (const path of sourceFiles) {
  const bytes = await readFile(resolve(frontendRoot, path));
  sources.push({ path, hash: sha256(bytes), byteSize: bytes.byteLength });
}
const rendererSourceHash = sha256(Buffer.from(JSON.stringify(sources), "utf8"));
const manifest = {
  manifestVersion: "prototype-renderer-worker-manifest/v1",
  protocolVersion,
  rendererVersion: identity.rendererVersion,
  rendererEnvironmentVersion: identity.rendererEnvironmentVersion,
  rendererSourceHash,
  runtimeCoreVersion: identity.runtimeCoreVersion,
  runtimeCoreSourceHash: identity.runtimeCoreSourceHash,
  runtimeCoreBundleHash: publicRuntimeHash,
  stateMachineKernelVersion: identity.stateMachineKernelVersion,
  renderRuntimeImageHash,
  browserVersion: identity.browserVersion,
  fontPackHash,
  viewportProfileHash,
  sandboxPolicyVersion: identity.sandboxPolicyVersion,
  publicRuntimeFile: "prototype_public_runtime.js",
  publicRuntimeHash,
  publicRuntimeByteSize: publicRuntimeBytes.byteLength,
  bundleFile: "prototype_renderer_worker.mjs",
  bundleHash: workerHash,
  bundleByteSize: workerBytes.byteLength,
  buildTool: `esbuild@${esbuildVersion}`,
  target: "node20",
  sources,
};
await writeAtomically(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);
