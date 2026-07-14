import { createHash } from "node:crypto";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

import { build, version as esbuildVersion } from "esbuild";

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repositoryRoot = resolve(frontendRoot, "..");
const runtimeDirectory = "src/features/prototype/runtime";
const sourceFiles = [
  `${runtimeDirectory}/canonical.ts`,
  `${runtimeDirectory}/runtimeCore.ts`,
  `${runtimeDirectory}/runtimeInputCodec.ts`,
  `${runtimeDirectory}/runtimeStateCodec.ts`,
  `${runtimeDirectory}/runtimeWorkerProtocol.ts`,
  `${runtimeDirectory}/types.ts`,
  "src/lib/utils.tsx",
  "scripts/prototype-runtime-worker.ts",
];
const identityPath = resolve(frontendRoot, runtimeDirectory, "runtimeBuildIdentity.ts");
const outputDirectory = resolve(repositoryRoot, "backend/app/runtime_assets");
const bundlePath = resolve(outputDirectory, "prototype_runtime_worker.mjs");
const manifestPath = resolve(outputDirectory, "prototype_runtime_worker.manifest.json");
const protocolVersion = "prototype-runtime-worker/v1";

function sha256(bytes) {
  return `sha256:${createHash("sha256").update(bytes).digest("hex")}`;
}

async function writeAtomically(path, bytes) {
  const tempPath = `${path}.tmp-${process.pid}`;
  await writeFile(tempPath, bytes);
  await rename(tempPath, path);
}

const sources = [];
for (const path of sourceFiles) {
  const bytes = await readFile(resolve(frontendRoot, path));
  sources.push({ path, hash: sha256(bytes), byteSize: bytes.byteLength });
}
const sourceManifestBytes = Buffer.from(JSON.stringify(sources), "utf8");
const sourceHash = sha256(sourceManifestBytes);
const identitySource = `export const RUNTIME_CORE_SOURCE_HASH =\n  ${JSON.stringify(sourceHash)};\n`;
await writeAtomically(identityPath, identitySource);

await mkdir(outputDirectory, { recursive: true });
const buildResult = await build({
  absWorkingDir: frontendRoot,
  bundle: true,
  charset: "utf8",
  entryPoints: ["scripts/prototype-runtime-worker.ts"],
  format: "esm",
  legalComments: "none",
  logLevel: "silent",
  minify: false,
  outfile: bundlePath,
  platform: "node",
  sourcemap: false,
  target: ["node20"],
  treeShaking: true,
  tsconfig: resolve(frontendRoot, "tsconfig.json"),
  write: false,
});
const output = buildResult.outputFiles?.[0];
if (output === undefined) {
  throw new Error("prototype runtime worker build produced no bundle");
}
const bundleBytes = Buffer.from(output.contents);
const bundleHash = sha256(bundleBytes);
await writeAtomically(bundlePath, bundleBytes);

const describeRequest = JSON.stringify({
  protocolVersion,
  requestId: "build-identity-check",
  action: "describe",
});
const described = spawnSync(process.execPath, [bundlePath], {
  encoding: "utf8",
  input: describeRequest,
  maxBuffer: 1024 * 1024,
});
if (described.status !== 0) {
  throw new Error(`prototype runtime worker describe failed: ${described.stderr.trim()}`);
}
const description = JSON.parse(described.stdout);
if (
  description.status !== "ok" ||
  description.protocolVersion !== protocolVersion ||
  description.runtimeCoreSourceHash !== sourceHash
) {
  throw new Error("prototype runtime worker identity does not match its build inputs");
}

const manifest = {
  manifestVersion: "prototype-runtime-worker-manifest/v1",
  protocolVersion,
  runtimeCoreVersion: description.runtimeCoreVersion,
  runtimeCoreSourceHash: sourceHash,
  stateMachineKernelVersion: description.stateMachineKernelVersion,
  bundleFile: "prototype_runtime_worker.mjs",
  bundleHash,
  bundleByteSize: bundleBytes.byteLength,
  buildTool: `esbuild@${esbuildVersion}`,
  target: "node20",
  sources,
};
await writeAtomically(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);
