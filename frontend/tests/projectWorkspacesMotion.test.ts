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

  assert.match(
    source,
    /import \{ AgentThinkingIndicator \} from "@\/components\/ui\/AgentThinkingIndicator";/,
  );
  assert.match(
    source,
    /data-density=\{pulse \? "project-workspaces-active-kpi" : "project-workspaces-kpi"\}/,
  );
  assert.match(source, /pulse && "motion-essential"/);
  assert.match(source, /<AgentThinkingIndicator phase="dispatching" size=\{14\}/);
  assert.match(source, /animate-shimmer-sweep/);
  assert.doesNotMatch(source, /animate-ping/);
});

test("project workspaces running rows use dispatch motion", () => {
  const source = readFileSync(
    path.join(root, "src/features/projects/ProjectWorkspacesPage.tsx"),
    "utf8",
  );

  assert.match(
    source,
    /const isWorkspaceActive = ws\.status === "running" \|\| ws\.status === "responding";/,
  );
  assert.match(
    source,
    /data-density=\{isWorkspaceActive \? "project-workspaces-active-row" : "project-workspaces-row"\}/,
  );
  assert.match(source, /isWorkspaceActive && "motion-essential"/);
  assert.match(source, /<AgentThinkingIndicator phase="dispatching" size=\{12\}/);
  assert.match(source, /animate-shimmer-sweep/);
});

test("project workspaces loading table uses dispatch motion", () => {
  const source = readFileSync(
    path.join(root, "src/features/projects/ProjectWorkspacesPage.tsx"),
    "utf8",
  );

  assert.match(source, /data-density="project-workspaces-dispatch-loading"/);
  assert.match(
    source,
    /className="motion-essential relative flex min-h-\[200px\] items-center justify-center gap-2 overflow-hidden px-4 py-10 text-sm font-semibold text-text-muted"/,
  );
  assert.match(source, /<AgentThinkingIndicator phase="dispatching" size=\{16\} \/>/);
  assert.doesNotMatch(source, /<Loader variant="card" label=\{t\("workspace\.loading"\)\}/);
});
