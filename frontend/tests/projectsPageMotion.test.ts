import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";

const SRC_ROOT = join(process.cwd(), "src");

function readSource(relativePath: string): string {
  return readFileSync(join(SRC_ROOT, relativePath), "utf-8");
}

test("projects page branch sync loading uses tool motion", () => {
  const source = readSource("features/projects/ProjectsPage.tsx");

  assert.match(source, /import \{ AgentThinkingIndicator \} from "@\/components\/ui\/AgentThinkingIndicator";/);
  assert.match(source, /data-density="projects-branches-tool-loading"/);
  assert.match(source, /className="motion-essential relative flex min-h-\[128px\] items-center justify-center gap-2 overflow-hidden rounded-lg border border-status-tool\/25 bg-status-tool\/5 text-sm font-semibold text-text-muted"/);
  assert.match(source, /<AgentThinkingIndicator phase="tool" size=\{16\} \/>/);
  assert.match(source, /t\("projects\.branches"\)/);
  assert.match(source, /animate-shimmer-sweep/);
  assert.doesNotMatch(source, /<Skeleton className="h-32 w-full" \/>/);
});
