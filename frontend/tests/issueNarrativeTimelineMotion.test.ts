import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const SRC_ROOT = join(process.cwd(), "src");

function readSource(relativePath: string): string {
  return readFileSync(join(SRC_ROOT, relativePath), "utf-8");
}

test("issue narrative timeline marks active role work with dispatch motion", () => {
  const source = readSource("features/issues/components/IssueNarrativeTimeline.tsx");

  assert.match(source, /data-density=\{isActiveRole \? "issue-narrative-active-role" : "issue-narrative-role"\}/);
  assert.match(source, /<AgentThinkingIndicator phase="dispatching" size=\{12\} \/>/);
  assert.match(source, /animate-shimmer-sweep/);
  assert.match(source, /motion-essential/);
  assert.doesNotMatch(source, /<Loader2 size=\{12\} className="text-brand animate-spin" \/>/);
});
