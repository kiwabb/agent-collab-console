import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const SRC_ROOT = join(process.cwd(), "src");

function readSource(relativePath: string): string {
  return readFileSync(join(SRC_ROOT, relativePath), "utf-8");
}

test("account popover version probe uses tool motion while loading", () => {
  const source = readSource("features/workbench/components/AccountPopover.tsx");

  assert.match(source, /import \{ AgentThinkingIndicator \} from "@\/components\/ui\/AgentThinkingIndicator";/);
  assert.match(source, /data-density="account-popover-version-tool"/);
  assert.match(source, /<AgentThinkingIndicator phase="tool" size=\{10\} \/> loading/);
  assert.doesNotMatch(source, /<Loader2 size=\{10\} className="animate-spin" \/>/);
  assert.doesNotMatch(source, /\bLoader2\b/);
});

test("command palette search spinner uses tool motion while querying", () => {
  const source = readSource("features/workbench/components/CommandPalette.tsx");

  assert.match(source, /import \{ AgentThinkingIndicator \} from "@\/components\/ui\/AgentThinkingIndicator";/);
  assert.match(source, /\{loading && <AgentThinkingIndicator phase="tool" size=\{12\} className="text-text-muted" \/>\}/);
  assert.doesNotMatch(source, /<Loader2 size=\{12\} className="animate-spin text-text-muted" \/>/);
  assert.doesNotMatch(source, /\bLoader2\b/);
});
