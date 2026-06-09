import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const SRC_ROOT = join(process.cwd(), "src");

function readSource(relativePath: string): string {
  return readFileSync(join(SRC_ROOT, relativePath), "utf-8");
}

test("diff merge create PR cta uses dispatch motion while opening GitHub PR", () => {
  const source = readSource("features/issues/tabs/DiffMergeTab.tsx");

  assert.match(source, /import \{ AgentThinkingIndicator \} from "@\/components\/ui\/AgentThinkingIndicator";/);
  assert.match(source, /data-density=\{busy === "pr-create" \? "diff-merge-create-pr-dispatch" : "diff-merge-create-pr"\}/);
  assert.match(source, /busy === "pr-create" && "motion-essential/);
  assert.match(source, /<AgentThinkingIndicator phase="dispatching" size=\{12\}/);
  assert.match(source, /<GitPullRequest size=\{12\}/);
  assert.doesNotMatch(source, /busy === "pr-create" \? \(\s*<span className="flex items-center gap-1\.5">\s*<Loader2 size=\{12\} className="animate-spin"/);
});

test("diff merge merge-back cta uses dispatch motion while merging", () => {
  const source = readSource("features/issues/tabs/DiffMergeTab.tsx");

  assert.match(source, /data-density=\{busy === "merge" \? "diff-merge-back-dispatch" : "diff-merge-back"\}/);
  assert.match(source, /busy === "merge" && "motion-essential/);
  assert.match(source, /busy === "merge" \? \(\s*<span className="flex items-center gap-1\.5">\s*<AgentThinkingIndicator phase="dispatching" size=\{12\}/);
  assert.doesNotMatch(source, /busy === "merge" \? \(\s*<span className="flex items-center gap-1\.5">\s*<Loader2 size=\{12\} className="animate-spin"/);
});

test("diff merge abandon cta uses dispatch motion while abandoning", () => {
  const source = readSource("features/issues/tabs/DiffMergeTab.tsx");

  assert.match(source, /data-density=\{busy === "abandon" \? "diff-merge-abandon-dispatch" : "diff-merge-abandon"\}/);
  assert.match(source, /busy === "abandon" && "motion-essential/);
  assert.match(source, /busy === "abandon" \? \(\s*<span className="flex items-center gap-1\.5">\s*<AgentThinkingIndicator phase="dispatching" size=\{12\}/);
  assert.doesNotMatch(source, /busy === "abandon" \? \(\s*<span className="flex items-center gap-1\.5">\s*<Loader2 size=\{12\} className="animate-spin"/);
});
