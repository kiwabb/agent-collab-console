import test from "node:test";
import assert from "node:assert/strict";
import { readCompactSource as readSource } from "./sourceTestUtils";

test("project shell exposes workspace and conductor secondary routes", () => {
  const shell = readSource("features/projects/ProjectShell.tsx");
  const workspacesPage = readSource("features/projects/ProjectWorkspacesPage.tsx");
  const conductorRoute = readSource("app/projects/[id]/conductor/page.tsx");
  const conductorMount = readSource("features/projects/ProjectConductorRoutePage.tsx");
  const startupRoute = readSource("app/projects/[id]/env/page.tsx");
  const startupMount = readSource("features/projects/ProjectEnvConfigRoutePage.tsx");

  assert.match(shell, /usePathname/);
  assert.match(shell, /<Link/);
  assert.match(shell, /project\.nav\.workspaces/);
  assert.match(shell, /project\.nav\.conductor/);
  assert.match(shell, /project\.nav\.envConfig/);
  assert.match(shell, /aria-current=\{active \? "page" : undefined\}/);
  assert.doesNotMatch(workspacesPage, /<ProjectConductorPage/);
  assert.match(workspacesPage, /<ProjectShell/);
  assert.match(conductorRoute, /ProjectConductorRoutePage/);
  assert.match(conductorMount, /<ProjectConductorPage projectId=\{projectId\} \/>/);
  assert.match(startupRoute, /ProjectEnvConfigRoutePage/);
  assert.match(startupMount, /ProjectStartupConfigPage/);
});
