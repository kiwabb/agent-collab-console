import test from "node:test";
import assert from "node:assert/strict";
import { readCompactSource as readSource } from "./sourceTestUtils";

test("global and project structural surfaces use continuous panes", () => {
  const shell = readSource("features/workbench/WorkbenchShell.tsx");
  const sidebar = readSource("features/workbench/components/AppSidebar.tsx");
  const projects = readSource("features/projects/ProjectsPage.tsx");
  const workspaces = readSource("features/projects/ProjectWorkspacesPage.tsx");
  const flow = readSource("features/prototype/structured/StructuredPrototypeFlow.tsx");

  assert.match(shell, /border-r border-border-subtle/);
  assert.doesNotMatch(shell, /enterprise-panel|rounded-\[22px\]|rounded-\[30px\]/);
  assert.doesNotMatch(sidebar, /enterprise-panel|rounded-\[30px\]/);
  assert.match(projects, /md:grid-cols-\[260px_minmax\(0,1fr\)\]/);
  assert.doesNotMatch(projects, /enterprise-card|enterprise-panel/);
  assert.match(workspaces, /divide-x divide-y divide-border-subtle/);
  assert.match(workspaces, /lg:grid-cols-\[1fr_120px_90px_1\.6fr_120px_70px\]/);
  assert.doesNotMatch(flow, /enterprise-card/);
});

test("structured prototype panes switch before the fixed tracks can overflow", () => {
  const studio = readSource("features/prototype/structured/StructuredPrototypeStudioPage.tsx");

  assert.match(studio, /xl:grid-cols-\[240px_minmax\(440px,1fr\)_300px\]/);
  assert.doesNotMatch(studio, /lg:grid-cols-\[240px_minmax\(440px,1fr\)_300px\]/);
  assert.match(studio, /role="tablist"/);
  assert.match(studio, /role="tabpanel"/);
});
