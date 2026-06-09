import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";

const SRC_ROOT = join(process.cwd(), "src");

function readSource(relativePath: string): string {
  return readFileSync(join(SRC_ROOT, relativePath), "utf-8");
}

test("execution config selector catalog loading uses tool motion", () => {
  const source = readSource("components/runtime/ExecutionConfigSelector.tsx");

  assert.match(source, /import \{ AgentThinkingIndicator \} from "@\/components\/ui\/AgentThinkingIndicator";/);
  assert.match(source, /data-density="execution-config-tool-loading"/);
  assert.match(source, /className=\{cn\("motion-essential relative flex min-h-\[40px\] items-center justify-center gap-2 overflow-hidden rounded-lg border border-status-tool\/25 bg-status-tool\/5 px-3 text-xs font-semibold text-text-muted", className\)\}/);
  assert.match(source, /<AgentThinkingIndicator phase="tool" size=\{14\} \/>/);
  assert.match(source, /t\("settings\.loadingCatalog"\)/);
  assert.match(source, /animate-shimmer-sweep/);
  assert.doesNotMatch(source, /animate-pulse/);
});
