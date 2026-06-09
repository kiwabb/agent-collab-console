import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const SRC_ROOT = join(process.cwd(), "src");

function readSource(relativePath: string): string {
  return readFileSync(join(SRC_ROOT, relativePath), "utf-8");
}

test("artifacts hub refresh cta uses tool motion while scanning artifacts", () => {
  const source = readSource("features/artifacts/ArtifactsHubPage.tsx");

  assert.match(source, /import \{ AgentThinkingIndicator \} from "@\/components\/ui\/AgentThinkingIndicator";/);
  assert.match(source, /data-density=\{refreshing \? "artifacts-hub-refresh-tool" : "artifacts-hub-refresh"\}/);
  assert.match(source, /refreshing && "motion-essential"/);
  assert.match(source, /refreshing \? \(\s*<AgentThinkingIndicator phase="tool" size=\{12\} \/>/);
  assert.match(source, /<RefreshCw size=\{12\} \/>/);
  assert.doesNotMatch(source, /<RefreshCw size=\{12\} className=\{cn\("mr-1\.5", refreshing && "animate-spin"\)\} \/>/);
});
