import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { getDictionaryValue } from "../src/lib/i18n";

const SRC_ROOT = join(process.cwd(), "src");

function readSource(relativePath: string): string {
  return readFileSync(join(SRC_ROOT, relativePath), "utf-8");
}

test("project dashboard loading uses thinking motion", () => {
  const source = readSource("features/projects/ProjectDashboard.tsx");

  assert.match(source, /import \{ AgentThinkingIndicator \} from "@\/components\/ui\/AgentThinkingIndicator";/);
  assert.match(source, /data-density="project-dashboard-thinking-loading"/);
  assert.match(source, /className="motion-essential relative mx-auto flex min-h-\[360px\] max-w-6xl items-center justify-center gap-2 overflow-hidden px-8 py-6 text-sm font-semibold text-text-muted"/);
  assert.match(source, /<AgentThinkingIndicator phase="thinking" size=\{16\} \/>/);
  assert.match(source, /t\("project\.dashboard\.loading"\)/);
  assert.match(source, /animate-shimmer-sweep/);
  assert.doesNotMatch(source, /<Loader variant="full" label="Loading Project\.\.\." \/>/);
  assert.equal(getDictionaryValue("zh-CN", "project.dashboard.loading"), "加载项目上下文中...");
  assert.equal(getDictionaryValue("en-US", "project.dashboard.loading"), "Loading project context...");
});
