import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";

const SRC_ROOT = join(process.cwd(), "src");

function readSource(relativePath: string): string {
  return readFileSync(join(SRC_ROOT, relativePath), "utf-8");
}

test("virtualized task list active execution status uses dispatch motion", () => {
  const source = readSource("components/ui/VirtualizedList.tsx");

  assert.match(source, /import \{ AgentThinkingIndicator \} from "@\/components\/ui\/AgentThinkingIndicator";/);
  assert.match(source, /const isTaskActive = status === "running" \|\| status === "responding";/);
  assert.match(source, /data-density="virtualized-task-active-status"/);
  assert.match(source, /className="motion-essential flex size-3 items-center justify-center rounded-full"/);
  assert.match(source, /<AgentThinkingIndicator phase="dispatching" size=\{10\} \/>/);
  assert.doesNotMatch(source, /status === "running" \|\| status === "responding" \? "bg-brand animate-pulse"/);
});
