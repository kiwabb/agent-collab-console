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
  const prototypeRoute = readSource("app/projects/[id]/prototypes/page.tsx");
  const prototypeStudioRedirect = readSource("app/projects/[id]/prototypes/studio/page.tsx");
  const prototypeMount = readSource(
    "features/prototype/structured/StructuredPrototypeRoutePage.tsx",
  );

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
  assert.match(prototypeRoute, /StructuredPrototypeRoutePage/);
  assert.match(prototypeMount, /<WorkbenchShell/);
  assert.match(prototypeMount, /<ProjectShell/);
  assert.match(prototypeMount, /<StructuredPrototypeStudioPage/);
  assert.match(
    prototypeStudioRedirect,
    /redirect\(`\/projects\/\$\{encodeURIComponent\(id\)\}\/prototypes`\)/,
  );
  assert.doesNotMatch(prototypeRoute, /redirect/);
});

test("structured prototype chrome uses the console theme instead of a standalone palette", () => {
  const studio = readSource("features/prototype/structured/StructuredPrototypeStudioPage.tsx");
  const generation = readSource(
    "features/prototype/structured/StructuredPrototypeGenerationPanel.tsx",
  );

  assert.match(studio, /bg-surface/);
  assert.match(studio, /border-border-subtle/);
  assert.match(generation, /enterprise-panel/);
  assert.match(generation, /bg-brand/);
  assert.doesNotMatch(studio, /#[0-9a-fA-F]{3,8}/);
  assert.doesNotMatch(generation, /#[0-9a-fA-F]{3,8}/);
});
