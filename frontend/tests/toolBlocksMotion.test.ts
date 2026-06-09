import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

const root = path.resolve(import.meta.dirname, "..");

test("running tool blocks use semantic tool motion", () => {
  const source = readFileSync(
    path.join(root, "src/features/runs/toolBlocks/ToolBlocks.tsx"),
    "utf8",
  );

  assert.match(source, /data-density=\{isRunning \? "tool-block-active-tool" : "tool-block"\}/);
  assert.match(source, /<AgentThinkingIndicator phase="tool" size=\{12\} \/>/);
  assert.match(source, /animate-shimmer-sweep/);
  assert.match(source, /motion-essential/);
  assert.doesNotMatch(source, /bg-brand animate-pulse/);
});

test("tool block empty state uses semantic tool motion", () => {
  const source = readFileSync(
    path.join(root, "src/features/runs/toolBlocks/ToolBlocks.tsx"),
    "utf8",
  );

  assert.match(source, /data-density="tool-block-empty-tool-sync"/);
  assert.match(source, /className="motion-essential py-12 flex flex-col items-center justify-center text-text-muted gap-2"/);
  assert.match(source, /<AgentThinkingIndicator phase="tool" size=\{20\} className="opacity-40" \/>/);
  assert.doesNotMatch(source, /<Loader2 size=\{20\} className="opacity-30 animate-spin" \/>/);
});
