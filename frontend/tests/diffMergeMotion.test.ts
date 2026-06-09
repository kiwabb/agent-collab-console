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

test("diff merge toolbar ctas use dispatch motion while busy", () => {
  const source = readSource("features/issues/tabs/DiffMergeTab.tsx");

  assert.match(source, /data-density=\{busy === "pr-create" \? "diff-merge-toolbar-create-pr-dispatch" : "diff-merge-toolbar-create-pr"\}/);
  assert.match(source, /busy === "pr-create" && "motion-essential"/);
  assert.match(source, /busy === "pr-create" \? \(\s*<AgentThinkingIndicator phase="dispatching" size=\{11\}/);
  assert.doesNotMatch(source, /busy === "pr-create" \? \(\s*<Loader2 size=\{11\} className="animate-spin" \/>/);

  assert.match(source, /data-density=\{busy === "merge" \? "diff-merge-toolbar-back-dispatch" : "diff-merge-toolbar-back"\}/);
  assert.match(source, /busy === "merge" && "motion-essential"/);
  assert.match(source, /busy === "merge" \? \(\s*<span className="flex items-center gap-1\.5">\s*<AgentThinkingIndicator phase="dispatching" size=\{11\}/);
  assert.doesNotMatch(source, /busy === "merge" \? \(\s*<span className="flex items-center gap-1\.5">\s*<Loader2 size=\{11\} className="animate-spin" \/>/);
});

test("diff merge abandon cta uses dispatch motion while abandoning", () => {
  const source = readSource("features/issues/tabs/DiffMergeTab.tsx");

  assert.match(source, /data-density=\{busy === "abandon" \? "diff-merge-abandon-dispatch" : "diff-merge-abandon"\}/);
  assert.match(source, /busy === "abandon" && "motion-essential/);
  assert.match(source, /busy === "abandon" \? \(\s*<span className="flex items-center gap-1\.5">\s*<AgentThinkingIndicator phase="dispatching" size=\{12\}/);
  assert.doesNotMatch(source, /busy === "abandon" \? \(\s*<span className="flex items-center gap-1\.5">\s*<Loader2 size=\{12\} className="animate-spin"/);
});

test("diff merge PR refresh cta uses tool motion while syncing GitHub PR state", () => {
  const source = readSource("features/issues/tabs/DiffMergeTab.tsx");

  assert.match(source, /data-density=\{busy === "pr-refresh" \? "diff-merge-pr-refresh-tool" : "diff-merge-pr-refresh"\}/);
  assert.match(source, /busy === "pr-refresh" && "motion-essential/);
  assert.match(source, /busy === "pr-refresh" \? \(\s*<AgentThinkingIndicator phase="tool" size=\{12\}/);
  assert.doesNotMatch(source, /busy === "pr-refresh" \? \(\s*<Loader2 size=\{12\} className="animate-spin"/);
});

test("diff merge refresh cta uses tool motion while syncing diff state", () => {
  const source = readSource("features/issues/tabs/DiffMergeTab.tsx");

  assert.match(source, /data-density=\{isRefreshing \? "diff-merge-refresh-tool" : "diff-merge-refresh"\}/);
  assert.match(source, /isRefreshing && "motion-essential/);
  assert.match(source, /isRefreshing \? <AgentThinkingIndicator phase="tool" size=\{12\} \/> : <RefreshCw size=\{12\}/);
  assert.doesNotMatch(source, /<RefreshCw size=\{12\} className=\{cn\("mr-1\.5", isRefreshing && "animate-spin"\)\}/);
});

test("diff merge submit review cta uses thinking motion while submitting", () => {
  const source = readSource("features/issues/tabs/DiffMergeTab.tsx");

  assert.match(source, /data-density=\{busy === "submit" \? "diff-merge-submit-review-thinking" : "diff-merge-submit-review"\}/);
  assert.match(source, /busy === "submit" && "motion-essential/);
  assert.match(source, /busy === "submit" \? \(\s*<span className="flex items-center gap-1\.5">\s*<AgentThinkingIndicator phase="thinking" size=\{12\}/);
  assert.doesNotMatch(source, /busy === "submit" \? \(\s*<span className="flex items-center gap-1\.5">\s*<Loader2 size=\{12\} className="animate-spin"/);
});

test("diff merge review decision ctas use thinking motion while approving or rejecting", () => {
  const source = readSource("features/issues/tabs/DiffMergeTab.tsx");

  assert.match(source, /data-density=\{busy === "review-approve" \? "diff-merge-review-approve-thinking" : "diff-merge-review-approve"\}/);
  assert.match(source, /busy === "review-approve" && "motion-essential/);
  assert.match(source, /busy === "review-approve" \? \(\s*<span className="flex items-center gap-1\.5">\s*<AgentThinkingIndicator phase="thinking" size=\{12\}/);
  assert.doesNotMatch(source, /busy === "review-approve" \? \(\s*<span className="flex items-center gap-1\.5">\s*<Loader2 size=\{12\} className="animate-spin"/);
  assert.match(source, /data-density=\{isLoading \? "diff-merge-review-reject-thinking" : "diff-merge-review-reject"\}/);
  assert.match(source, /isLoading && "motion-essential/);
  assert.match(source, /isLoading \? \(\s*<span className="flex items-center gap-1\.5">\s*<AgentThinkingIndicator phase="thinking" size=\{12\}/);
  assert.doesNotMatch(source, /isLoading \? \(\s*<span className="flex items-center gap-1\.5">\s*<Loader2 size=\{12\} className="animate-spin"/);
});
