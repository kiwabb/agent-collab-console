import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

const root = path.resolve(import.meta.dirname, "..");

test("tasks runs tab status dots use dispatch motion for active execution", () => {
  const source = readFileSync(
    path.join(root, "src/features/issues/tabs/TasksRunsTab.tsx"),
    "utf8",
  );

  assert.match(source, /import \{ AgentThinkingIndicator \} from "@\/components\/ui\/AgentThinkingIndicator";/);
  assert.match(source, /const isActive = status === "running" \|\| status === "in_progress";/);
  assert.match(source, /data-density=\{isActive \? "tasks-runs-active-status-dot" : "tasks-runs-status-dot"\}/);
  assert.match(source, /isActive && "motion-essential"/);
  assert.match(source, /<AgentThinkingIndicator phase="dispatching" size=\{10\}/);
  assert.doesNotMatch(source, /bg-warning animate-pulse/);
});
