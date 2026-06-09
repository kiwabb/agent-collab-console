import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

const root = path.resolve(import.meta.dirname, "..");

test("run detail status badge marks live execution with dispatch motion", () => {
  const source = readFileSync(
    path.join(root, "src/features/runs/RunDetail.tsx"),
    "utf8",
  );

  assert.match(source, /const isLiveRunStatus = s === "running" \|\| s === "responding"/);
  assert.match(source, /data-density=\{isLiveRunStatus \? "run-detail-live-status" : "run-detail-status"\}/);
  assert.match(source, /<AgentThinkingIndicator phase="dispatching" size=\{12\} \/>/);
  assert.match(source, /animate-shimmer-sweep/);
  assert.match(source, /motion-essential/);
  assert.doesNotMatch(source, /bg-brand animate-pulse/);
});
