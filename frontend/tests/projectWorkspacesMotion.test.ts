import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

const root = path.resolve(import.meta.dirname, "..");

test("project workspaces active KPI uses dispatch motion", () => {
  const source = readFileSync(
    path.join(root, "src/features/projects/ProjectWorkspacesPage.tsx"),
    "utf8",
  );

  assert.match(source, /import \{ AgentThinkingIndicator \} from "@\/components\/ui\/AgentThinkingIndicator";/);
  assert.match(source, /data-density=\{pulse \? "project-workspaces-active-kpi" : "project-workspaces-kpi"\}/);
  assert.match(source, /pulse && "motion-essential"/);
  assert.match(source, /<AgentThinkingIndicator phase="dispatching" size=\{14\}/);
  assert.match(source, /animate-shimmer-sweep/);
  assert.doesNotMatch(source, /animate-ping/);
});
