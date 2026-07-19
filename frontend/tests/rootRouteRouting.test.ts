import assert from "node:assert/strict";
import test from "node:test";

import { readCompactSource as readSource } from "./sourceTestUtils";

test("root route owns the global inbox and no longer mounts the legacy workbench", () => {
  const source = readSource("app/page.tsx");

  assert.match(source, /from "next\/navigation"/);
  assert.match(source, /from "@\/features\/inbox\/InboxDashboard"/);
  assert.match(source, /from "@\/features\/workbench\/WorkbenchShell"/);
  assert.match(source, /<InboxDashboard \/>/);
  assert.match(source, /<WorkbenchShell breadcrumbs=\{\[\{\s*label: "Inbox"\s*\}\]\}>/);
  assert.doesNotMatch(source, /WorkbenchPage/);
});

test("root route redirects legacy project query links to the project workspace route", () => {
  const source = readSource("app/page.tsx");

  assert.match(source, /searchParams: Promise/);
  assert.match(source, /params\.project/);
  assert.match(source, /redirect\(`\/projects\/\$\{encodeURIComponent\(project\)\}`\)/);
});

test("canonical workspace ownership stays split by project and workspace identity", () => {
  const projectRoute = readSource("app/projects/[id]/page.tsx");
  const workspaceRoute = readSource("app/workspaces/[wsId]/page.tsx");

  assert.match(projectRoute, /ProjectWorkspacesPage projectId=\{id\}/);
  assert.match(projectRoute, /<WorkbenchShell projectId=\{id\}/);
  assert.match(workspaceRoute, /WorkspaceConsole workspaceId=\{wsId\}/);
  assert.doesNotMatch(projectRoute, /WorkspaceGrid/);
  assert.doesNotMatch(workspaceRoute, /ProjectWorkspacesPage/);
});

test("project-scoped routes pin the shared shell to their path project", () => {
  const shell = readSource("features/workbench/WorkbenchShell.tsx");
  const selection = readSource("features/workbench/state/SelectionProvider.tsx");
  const conductorRoute = readSource("app/projects/[id]/conductor/page.tsx");
  const environmentRoute = readSource("app/projects/[id]/env/page.tsx");
  const prototypeRoute = readSource(
    "features/prototype/structured/StructuredPrototypeRoutePage.tsx",
  );

  assert.match(shell, /projectId\?: string \| null \| undefined/);
  assert.match(shell, /projectId !== undefined \? \{projectId: projectId \?\? null\} : \{\}/);
  assert.match(selection, /writeLocal\(PROJECT_KEY, nextProjectId\)/);
  assert.match(conductorRoute, /<WorkbenchShell projectId=\{id\}/);
  assert.match(environmentRoute, /<WorkbenchShell projectId=\{id\}/);
  assert.match(prototypeRoute, /<WorkbenchShell projectId=\{projectId\}/);
});
