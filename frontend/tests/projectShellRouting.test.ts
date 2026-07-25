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
  assert.match(prototypeMount, /layout="workspace"/);
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
  const preview = readSource("features/prototype/structured/StructuredPrototypePreview.tsx");
  const palette = readSource("features/prototype/structured/StructuredPrototypePalette.tsx");

  assert.match(studio, /bg-surface/);
  assert.match(studio, /border-border-subtle/);
  assert.match(studio, /h-full min-h-\[640px\]/);
  assert.doesNotMatch(studio, /overflow-hidden rounded-xl border/);
  assert.doesNotMatch(generation, /enterprise-panel|rounded-xl/);
  assert.doesNotMatch(preview, /shadow-xl/);
  assert.doesNotMatch(palette, /rounded-lg border border-border-subtle bg-surface-raised/);
  assert.match(palette, /formSelectorPlaceholder/);
  assert.match(studio, /resolvePaletteFormDefinition/);
  assert.doesNotMatch(studio, /runtime\.forms\[0\]/);
  assert.equal((studio.match(/prototype\.structured\.form\.selectionRequired/g) ?? []).length, 2);
  assert.equal((studio.match(/prototype\.structured\.form\.invalid/g) ?? []).length, 2);
  assert.match(studio, /controller\.deletePrototype/);
  assert.match(studio, /<ConfirmDialog/);
  assert.match(generation, /generation\.deleteAll/);
  assert.match(generation, /<Trash2/);
  assert.match(generation, /bg-brand/);
  assert.doesNotMatch(studio, /#[0-9a-fA-F]{3,8}/);
  assert.doesNotMatch(generation, /#[0-9a-fA-F]{3,8}/);
});

test("structured prototype Studio fullscreen stays below modal chrome and remains escapable", () => {
  const studio = readSource("features/prototype/structured/StructuredPrototypeStudioPage.tsx");
  const dialog = readSource("components/ui/dialog.tsx");

  assert.match(studio, /isFullscreen/);
  assert.match(studio, /data-prototype-studio-fullscreen/);
  assert.match(studio, /fixed inset-0 z-40 h-dvh/);
  assert.match(dialog, /fixed inset-0 isolate z-50/);
  assert.match(dialog, /fixed top-1\/2 left-1\/2 z-50/);
  assert.match(studio, /ui\.enterFullscreen/);
  assert.match(studio, /ui\.exitFullscreen/);
  assert.match(studio, /key: "Escape"/);
  assert.match(studio, /setIsFullscreen\(false\)/);
});

test("generation preview keeps the runtime document fetch in the authenticated origin", () => {
  const generation = readSource(
    "features/prototype/structured/StructuredPrototypeGenerationPanel.tsx",
  );

  assert.match(generation, /sandbox="allow-scripts"/);
  assert.doesNotMatch(generation, /allow-same-origin/);
});

test("structured prototype deletion reuses one request identity until success", () => {
  const generation = readSource(
    "features/prototype/structured/useStructuredPrototypeGeneration.ts",
  );
  const studio = readSource("features/prototype/structured/useStructuredPrototypeStudio.ts");
  const storage = readSource("features/prototype/structured/structuredPrototypeStorage.ts");

  assert.match(storage, /STRUCTURED_PROTOTYPE_DELETE_REQUEST_KEY/);
  for (const source of [generation, studio]) {
    assert.match(source, /beginStructuredPrototypePendingOperation\(projectId/);
    assert.match(source, /operationKind: "delete_project_prototype"/);
    assert.match(source, /requestKey: STRUCTURED_PROTOTYPE_DELETE_REQUEST_KEY/);
    assert.match(
      source,
      /deleteProjectStructuredPrototype\(projectId, descriptor\.clientRequestId\)/,
    );
    assert.match(
      source,
      /finishStructuredPrototypePendingOperation\(projectId, descriptor\.clientRequestId\)/,
    );
  }
  assert.match(generation, /clearStructuredPrototypeProjectStorage\(projectId\)/);
  assert.match(studio, /clearStructuredPrototypeProjectStorage\(projectId\)/);
});
