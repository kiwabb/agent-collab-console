import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";

const SRC_ROOT = join(process.cwd(), "src");

function readSource(relativePath: string): string {
  return readFileSync(join(SRC_ROOT, relativePath), "utf-8");
}

test("knowledge reindex cta uses tool motion while rebuilding memory", () => {
  const source = readSource("features/knowledge/KnowledgePage.tsx");

  assert.match(source, /import \{ AgentThinkingIndicator \} from "@\/components\/ui\/AgentThinkingIndicator";/);
  assert.match(source, /data-density=\{reindexing \? "knowledge-reindex-tool" : "knowledge-reindex"\}/);
  assert.match(source, /className=\{cn\(\s*"inline-flex items-center gap-1 rounded-md border border-border bg-surface px-2 py-1 text-xs hover:bg-surface-hover disabled:opacity-50",\s*reindexing && "motion-essential",\s*\)\}/);
  assert.match(source, /reindexing \? <AgentThinkingIndicator phase="tool" size=\{12\} \/> : <RefreshCw size=\{12\} \/>/);
  assert.doesNotMatch(source, /<RefreshCw size=\{12\} className=\{reindexing \? "animate-spin" : ""\} \/>/);
});
