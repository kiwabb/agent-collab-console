import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import test from "node:test";

// The prototype worker bundles under backend/app/runtime_assets are built from
// the frontend sources listed in each bundle's manifest. Backend replay,
// rendering, and snap attestation all execute the bundled copy, so editing a
// listed source without rebuilding silently forks editor behavior from replay
// behavior. Each manifest records {path, hash, byteSize} per source; re-hash
// them here so any drift fails fast with the exact rebuild command.

const frontendRoot = resolve(import.meta.dirname, "..");
const runtimeAssetsRoot = resolve(frontendRoot, "../backend/app/runtime_assets");

const WORKER_MANIFESTS = [
  { manifest: "prototype_runtime_worker.manifest.json", rebuild: "build:prototype-runtime-worker" },
  {
    manifest: "prototype_renderer_worker.manifest.json",
    rebuild: "build:prototype-renderer-worker",
  },
  { manifest: "prototype_snap_worker.manifest.json", rebuild: "build:prototype-snap-worker" },
] as const;

interface ManifestSourceEntry {
  path: string;
  hash: string;
  byteSize: number;
}

function manifestSources(manifestFileName: string): ManifestSourceEntry[] {
  const raw: unknown = JSON.parse(
    readFileSync(resolve(runtimeAssetsRoot, manifestFileName), "utf8"),
  );
  assert.ok(typeof raw === "object" && raw !== null, `${manifestFileName} must be an object`);
  const sources = (raw as { sources?: unknown }).sources;
  assert.ok(Array.isArray(sources), `${manifestFileName} must list its sources`);
  assert.ok(sources.length > 0, `${manifestFileName} sources must not be empty`);
  return sources.map((entry: unknown, index: number): ManifestSourceEntry => {
    assert.ok(
      typeof entry === "object" && entry !== null,
      `${manifestFileName} sources[${index}] must be an object`,
    );
    const { path, hash, byteSize } = entry as Record<string, unknown>;
    assert.equal(typeof path, "string", `${manifestFileName} sources[${index}].path`);
    assert.equal(typeof hash, "string", `${manifestFileName} sources[${index}].hash`);
    assert.equal(typeof byteSize, "number", `${manifestFileName} sources[${index}].byteSize`);
    return { path: path as string, hash: hash as string, byteSize: byteSize as number };
  });
}

for (const { manifest, rebuild } of WORKER_MANIFESTS) {
  test(`${manifest} matches the checked-in frontend sources`, () => {
    const staleSources: string[] = [];
    for (const entry of manifestSources(manifest)) {
      const bytes = readFileSync(resolve(frontendRoot, entry.path));
      const hash = `sha256:${createHash("sha256").update(bytes).digest("hex")}`;
      if (hash !== entry.hash || bytes.byteLength !== entry.byteSize) {
        staleSources.push(entry.path);
      }
    }
    assert.deepEqual(
      staleSources,
      [],
      `worker bundle is stale for: ${staleSources.join(", ")} — run \`npm run ${rebuild}\` and commit backend/app/runtime_assets`,
    );
  });
}
