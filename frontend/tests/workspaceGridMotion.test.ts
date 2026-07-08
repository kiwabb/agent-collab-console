import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

const root = path.resolve(import.meta.dirname, "..");

test("workspace grid loading uses dispatch motion", () => {
  const source = readFileSync(path.join(root, "src/features/workspaces/WorkspaceGrid.tsx"), "utf8");

  assert.match(
    source,
    /import \{ AgentThinkingIndicator \} from "@\/components\/ui\/AgentThinkingIndicator";/,
  );
  assert.match(source, /data-density="workspace-grid-dispatch-loading"/);
  assert.match(
    source,
    /className="motion-essential relative col-span-full flex min-h-\[220px\] items-center justify-center gap-2 overflow-hidden rounded-lg border border-status-running\/25 bg-status-running\/5 text-sm font-semibold text-text-muted"/,
  );
  assert.match(source, /<AgentThinkingIndicator phase="dispatching" size=\{16\} \/>/);
  assert.match(source, /animate-shimmer-sweep/);
  assert.match(source, /\{t\("workspace\.loading"\)\}/);
  assert.doesNotMatch(source, /<Skeleton variant=/);
});
