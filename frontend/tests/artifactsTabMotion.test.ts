import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const SRC_ROOT = join(process.cwd(), "src");

function readSource(relativePath: string): string {
  return readFileSync(join(SRC_ROOT, relativePath), "utf-8");
}

test("artifacts tab refresh cta uses tool motion while syncing artifacts", () => {
  const source = readSource("features/issues/tabs/ArtifactsTab.tsx");

  assert.match(source, /import \{ AgentThinkingIndicator \} from "@\/components\/ui\/AgentThinkingIndicator";/);
  assert.match(source, /data-density=\{isRefreshing \? "artifacts-tab-refresh-tool" : "artifacts-tab-refresh"\}/);
  assert.match(source, /isRefreshing && "motion-essential/);
  assert.match(source, /isRefreshing \? <AgentThinkingIndicator phase="tool" size=\{11\} \/> : <RefreshCw size=\{11\}/);
  assert.doesNotMatch(source, /<RefreshCw\s+size=\{11\}\s+className=\{cn\("mr-1\.5", isRefreshing && "animate-spin"\)\}\s+\/>/);
});
