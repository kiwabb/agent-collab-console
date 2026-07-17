import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  deriveFormInputBindings,
  renderPrototypeDocument,
  resolvePrototypeShellTheme,
} from "../src/features/prototype/structured/prototypeRendererCore";
import { parseRendererDocument } from "../src/features/prototype/structured/rendererDocumentCodec";
import {
  defaultRuntimeScenarioId,
  findStructuredPrototypeFormForNode,
  findStructuredPrototypeNode,
  runtimeNodeActivationEvents,
  runtimeEntityFieldText,
  runtimeNodeTriggerEvents,
  runtimeNodeRows,
  runtimeNodeText,
  runtimeNodeVisible,
  runtimeTableRowsBinding,
  structuredPrototypeInputNodes,
} from "../src/features/prototype/structured/structuredPrototypeDerived";
import {
  createProcurementPrototypeDocument,
  STRUCTURED_PROCUREMENT_IDS,
} from "./fixtures/procurementDocumentFixture";
import {
  resolveStructuredPrototypeGridColumns,
  resolveStructuredPrototypeLayoutItem,
} from "../src/features/prototype/structured/structuredPrototypeNodes";
import { compactSource, readCompactSource } from "./sourceTestUtils";

function topbarShell(
  document: ReturnType<typeof createProcurementPrototypeDocument>,
  title: string,
) {
  const shell = document.settings.shell;
  return {
    kind: "topbar" as const,
    title,
    accentColorTokenKey: shell.accentColorTokenKey,
    navigationBackgroundColorTokenKey: shell.navigationBackgroundColorTokenKey,
    contentBackgroundColorTokenKey: shell.contentBackgroundColorTokenKey,
    surfaceColorTokenKey: shell.surfaceColorTokenKey,
  };
}

function documentWithResponsiveGrid() {
  const source = createProcurementPrototypeDocument();
  const document = structuredClone({
    ...source,
    id: "11111111-1111-1111-1111-111111111111",
  });
  const page = document.pages[0];
  assert.ok(page);
  const root = page.root;
  assert.equal(root.type, "Stack");
  if (root.type !== "Stack") throw new Error("list fixture root must be a Stack");
  root.children = [
    {
      id: "22222222-2222-2222-2222-222222222222",
      type: "Grid",
      name: "Responsive content grid",
      visibility: "visible",
      layoutItem: root.layoutItem,
      responsive: [],
      columns: 1,
      gap: 16,
      padding: { top: 8, right: 8, bottom: 8, left: 8 },
      columnOverrides: [
        { minWidth: 320, columns: 2 },
        { minWidth: 1024, columns: 4 },
      ],
      children: root.children,
    },
  ];
  return document;
}

test("structured prototype node lookup traverses nested form children", () => {
  const document = createProcurementPrototypeDocument();
  const page = document.pages[1];
  assert.ok(page);
  const input = findStructuredPrototypeNode(page.root, "d1dced07-9e49-52f8-9d50-d0d16aef82f8");
  assert.equal(input?.type, "Input");
  assert.equal(input?.name, "申请事项输入框");
});

test("Grid traversal and selected viewport columns use the highest matching override", () => {
  const document = documentWithResponsiveGrid();
  const page = document.pages[0];
  assert.ok(page);
  const grid = page.root.type === "Stack" ? page.root.children[0] : null;
  assert.equal(grid?.type, "Grid");
  if (grid?.type !== "Grid") throw new Error("responsive Grid fixture is missing");

  assert.equal(
    findStructuredPrototypeNode(page.root, STRUCTURED_PROCUREMENT_IDS.nodes.requestTable)?.type,
    "Table",
  );
  assert.equal(resolveStructuredPrototypeGridColumns(grid, 319), 1);
  assert.equal(resolveStructuredPrototypeGridColumns(grid, 320), 2);
  assert.equal(resolveStructuredPrototypeGridColumns(grid, 1023), 2);
  assert.equal(resolveStructuredPrototypeGridColumns(grid, 1024), 4);
  assert.equal(parseRendererDocument(document).id, document.id);
});

test("Studio layout resolution applies responsive overrides at canonical boundaries", () => {
  const document = documentWithResponsiveGrid();
  const page = document.pages[0];
  assert.ok(page);
  const grid = page.root.type === "Stack" ? page.root.children[0] : null;
  assert.equal(grid?.type, "Grid");
  if (grid?.type !== "Grid") throw new Error("responsive Grid fixture is missing");
  grid.responsive = [
    { breakpoint: "sm", layoutItem: { width: { unit: "percent", value: "80" } } },
    { breakpoint: "md", layoutItem: { width: { unit: "px", value: "640" }, grow: 1 } },
    { breakpoint: "lg", layoutItem: { alignSelf: "center" } },
  ];

  assert.deepEqual(resolveStructuredPrototypeLayoutItem(grid, 639), grid.layoutItem);
  assert.deepEqual(resolveStructuredPrototypeLayoutItem(grid, 640).width, {
    unit: "percent",
    value: "80",
  });
  assert.deepEqual(resolveStructuredPrototypeLayoutItem(grid, 767).width, {
    unit: "percent",
    value: "80",
  });
  assert.deepEqual(resolveStructuredPrototypeLayoutItem(grid, 768).width, {
    unit: "px",
    value: "640",
  });
  assert.equal(resolveStructuredPrototypeLayoutItem(grid, 1023).alignSelf, "stretch");
  assert.equal(resolveStructuredPrototypeLayoutItem(grid, 1024).alignSelf, "center");
});

test("renderer codec rejects non-canonical Grid overrides and invalid shell token references", () => {
  const document = documentWithResponsiveGrid();
  const page = document.pages[0];
  assert.ok(page);
  const grid = page.root.type === "Stack" ? page.root.children[0] : null;
  assert.equal(grid?.type, "Grid");
  if (grid?.type !== "Grid") throw new Error("responsive Grid fixture is missing");

  const descendingOverrides = structuredClone(document);
  const descendingPage = descendingOverrides.pages[0];
  assert.ok(descendingPage);
  const descendingGrid =
    descendingPage.root.type === "Stack" ? descendingPage.root.children[0] : null;
  assert.equal(descendingGrid?.type, "Grid");
  if (descendingGrid?.type !== "Grid") throw new Error("responsive Grid fixture is missing");
  descendingGrid.columnOverrides.reverse();
  assert.throws(() => parseRendererDocument(descendingOverrides), /strictly increasing minWidth/);

  const descendingResponsive = structuredClone(document);
  const responsivePage = descendingResponsive.pages[0];
  assert.ok(responsivePage);
  responsivePage.root.responsive = [
    { breakpoint: "lg", layoutItem: { grow: 1 } },
    { breakpoint: "sm", layoutItem: { grow: 0 } },
  ];
  assert.throws(
    () => parseRendererDocument(descendingResponsive),
    /strictly increasing breakpoint order/,
  );

  const unknownToken = structuredClone(document);
  unknownToken.settings.shell.accentColorTokenKey = "missing-color";
  assert.throws(() => parseRendererDocument(unknownToken), /unknown color token keys/);

  const topbarWithSidebarWidth = {
    ...document,
    settings: {
      ...document.settings,
      shell: {
        ...topbarShell(document, "Invalid topbar"),
        navigationWidth: 220,
      },
    },
  };
  assert.throws(
    () => parseRendererDocument(topbarWithSidebarWidth),
    /contains unknown field navigationWidth/,
  );
});

test("runtime bindings come from IDs and typed document structure", () => {
  const document = createProcurementPrototypeDocument();
  const genericDocument = {
    ...document,
    id: "document-1",
    runtime: {
      ...document.runtime,
      scenarios: document.runtime.scenarios.map((scenario) => ({
        ...scenario,
        key: "generic-scenario",
      })),
      rules: document.runtime.rules.map((rule, index) => ({
        ...rule,
        key: `generic-rule-${index}`,
      })),
    },
  };
  const scenario = genericDocument.runtime.scenarios[0];
  const submitRule = genericDocument.runtime.rules.find((rule) => rule.trigger.event === "submit");
  const rowRule = genericDocument.runtime.rules.find(
    (rule) => rule.trigger.event === "rowActivated",
  );
  assert.ok(scenario);
  assert.ok(submitRule);
  assert.ok(rowRule);

  assert.equal(defaultRuntimeScenarioId(genericDocument), scenario.id);
  assert.deepEqual(runtimeNodeTriggerEvents(genericDocument, submitRule.trigger.nodeId), [
    "submit",
  ]);
  assert.deepEqual(runtimeNodeTriggerEvents(genericDocument, rowRule.trigger.nodeId), [
    "rowActivated",
  ]);
  assert.ok(runtimeTableRowsBinding(genericDocument, rowRule.trigger.nodeId));

  const form = findStructuredPrototypeFormForNode(genericDocument, submitRule.trigger.nodeId);
  assert.ok(form);
  const inputs = structuredPrototypeInputNodes(form);
  assert.equal(inputs.length, 2);
  assert.ok(inputs.every((input) => input.formDefinitionId === form.formDefinitionId));
});

test("runtime node events keep click and submit in canonical order for one Button", () => {
  const source = {
    ...createProcurementPrototypeDocument(),
    id: "11111111-1111-1111-1111-111111111111",
  };
  const clickRule = source.runtime.rules.find((rule) => rule.trigger.event === "click");
  const submitRule = source.runtime.rules.find((rule) => rule.trigger.event === "submit");
  const rowRule = source.runtime.rules.find((rule) => rule.trigger.event === "rowActivated");
  assert.ok(clickRule);
  assert.ok(submitRule);
  assert.ok(rowRule);

  const nodeId = submitRule.trigger.nodeId;
  const clickForSameButton = {
    ...clickRule,
    id: "33333333-3333-3333-3333-333333333333",
    key: "same-button-click",
    trigger: { ...clickRule.trigger, nodeId, event: "click" as const },
  };
  const withRules = (rules: typeof source.runtime.rules) => ({
    ...source,
    runtime: { ...source.runtime, rules },
  });

  const clickOnly = withRules([clickForSameButton]);
  assert.deepEqual(runtimeNodeTriggerEvents(clickOnly, nodeId), ["click"]);
  assert.deepEqual(runtimeNodeActivationEvents(clickOnly, nodeId), [
    { kind: "nodeActivated", nodeId, event: "click" },
  ]);

  const submitOnly = withRules([submitRule]);
  assert.deepEqual(runtimeNodeTriggerEvents(submitOnly, nodeId), ["submit"]);
  assert.deepEqual(runtimeNodeActivationEvents(submitOnly, nodeId), [
    { kind: "nodeActivated", nodeId, event: "submit" },
  ]);

  for (const rules of [
    [clickForSameButton, submitRule],
    [submitRule, clickForSameButton],
  ]) {
    const combined = withRules(rules);
    assert.deepEqual(runtimeNodeTriggerEvents(combined, nodeId), ["click", "submit"]);
    assert.deepEqual(runtimeNodeActivationEvents(combined, nodeId), [
      { kind: "nodeActivated", nodeId, event: "click" },
      { kind: "nodeActivated", nodeId, event: "submit" },
    ]);
  }

  const tableOnly = withRules([rowRule]);
  assert.deepEqual(runtimeNodeTriggerEvents(tableOnly, rowRule.trigger.nodeId), ["rowActivated"]);
  assert.deepEqual(runtimeNodeActivationEvents(tableOnly, rowRule.trigger.nodeId), []);
});

test("Studio and published runtime submit one ordered activation batch per Button click", () => {
  const canvas = readCompactSource("features/prototype/structured/StructuredPrototypeCanvas.tsx");
  const studio = readCompactSource(
    "features/prototype/structured/StructuredPrototypeStudioPage.tsx",
  );
  const publicRuntime = compactSource(
    readFileSync(new URL("../scripts/prototype-public-runtime.ts", import.meta.url), "utf8"),
  );

  const canvasButtonStart = canvas.indexOf('if (node.type === "Button")');
  const canvasButtonEnd = canvas.indexOf("return ( <div onClick={select}>", canvasButtonStart);
  assert.ok(canvasButtonStart >= 0 && canvasButtonEnd > canvasButtonStart);
  const canvasButton = canvas.slice(canvasButtonStart, canvasButtonEnd);
  assert.ok(
    canvasButton.indexOf('triggerEvents.includes("submit")') <
      canvasButton.indexOf('triggerEvents.includes("click")'),
  );
  assert.equal(
    (canvasButton.match(/onNodeActivate\(node\.id, activationEvent\)/g) ?? []).length,
    1,
  );
  assert.match(canvas, /rowEvents\.includes\("rowActivated"\)/);

  const studioActivationStart = studio.indexOf("const activateNode = async");
  const studioActivationEnd = studio.indexOf(
    "const clearProjectedDocumentForSession",
    studioActivationStart,
  );
  assert.ok(studioActivationStart >= 0 && studioActivationEnd > studioActivationStart);
  const studioActivation = studio.slice(studioActivationStart, studioActivationEnd);
  const studioFields = studioActivation.lastIndexOf('kind: "fieldValueCommitted"');
  const studioActivations = studioActivation.indexOf("events.push(...activationEvents)");
  const studioRequest = studioActivation.indexOf("await runEvents(events)");
  assert.ok(studioFields >= 0 && studioFields < studioActivations);
  assert.ok(studioActivations < studioRequest);
  assert.equal((studioActivation.match(/await runEvents\(events\)/g) ?? []).length, 1);

  const publicButtonStart = publicRuntime.indexOf(
    'document.querySelectorAll<HTMLButtonElement>("[data-runtime-node-id]")',
  );
  const publicButtonEnd = publicRuntime.indexOf(
    'document.addEventListener("click"',
    publicButtonStart,
  );
  assert.ok(publicButtonStart >= 0 && publicButtonEnd > publicButtonStart);
  const publicButton = publicRuntime.slice(publicButtonStart, publicButtonEnd);
  const publicFields = publicButton.indexOf("events.push(formValueEvent(binding, input))");
  const publicActivations = publicButton.indexOf("events.push(...activationEvents)");
  const publicRequest = publicButton.indexOf("await applyEvents(runtime, events)");
  assert.ok(publicFields >= 0 && publicFields < publicActivations);
  assert.ok(publicActivations < publicRequest);
  assert.equal((publicButton.match(/await applyEvents\(runtime, events\)/g) ?? []).length, 1);
  assert.match(
    publicRuntime,
    /runtimeNodeTriggerEvents\(runtime\.document, nodeId\)\.includes\("rowActivated"\)/,
  );
  assert.doesNotMatch(publicRuntime, /ambiguous runtime triggers/);
});

test("runtime scenario selection fails closed when the document has no scenario", () => {
  const document = createProcurementPrototypeDocument();
  assert.throws(() =>
    defaultRuntimeScenarioId({
      ...document,
      id: "document-1",
      runtime: { ...document.runtime, scenarios: [] },
    }),
  );
});

test("runtime table columns must bind fields from their rows schema", () => {
  const source = createProcurementPrototypeDocument();
  const valid = structuredClone({
    ...source,
    id: "11111111-1111-1111-1111-111111111111",
  });
  assert.equal(parseRendererDocument(valid).id, valid.id);

  const missingField = structuredClone(valid);
  const missingFieldPage = missingField.pages[0];
  assert.ok(missingFieldPage);
  const missingFieldTable = findStructuredPrototypeNode(
    missingFieldPage.root,
    STRUCTURED_PROCUREMENT_IDS.nodes.requestTable,
  );
  assert.equal(missingFieldTable?.type, "Table");
  if (missingFieldTable?.type !== "Table") throw new Error("table fixture is missing");
  const missingColumn = missingFieldTable.columns[0];
  assert.ok(missingColumn);
  missingColumn.fieldId = null;
  assert.throws(() => parseRendererDocument(missingField), /requires a schema field/);

  const staticTable = structuredClone(missingField);
  staticTable.runtime.viewBindings = staticTable.runtime.viewBindings.filter(
    (binding) => binding.target !== "tableRows",
  );
  assert.equal(parseRendererDocument(staticTable).id, staticTable.id);

  const wrongSchema = structuredClone(valid);
  const wrongSchemaPage = wrongSchema.pages[0];
  assert.ok(wrongSchemaPage);
  const wrongSchemaTable = findStructuredPrototypeNode(
    wrongSchemaPage.root,
    STRUCTURED_PROCUREMENT_IDS.nodes.requestTable,
  );
  assert.equal(wrongSchemaTable?.type, "Table");
  if (wrongSchemaTable?.type !== "Table") throw new Error("table fixture is missing");
  const wrongColumn = wrongSchemaTable.columns[0];
  assert.ok(wrongColumn);
  wrongColumn.fieldId = STRUCTURED_PROCUREMENT_IDS.form.title;
  assert.throws(() => parseRendererDocument(wrongSchema), /not in its binding schema/);

  const duplicateBinding = structuredClone(valid);
  const firstBinding = duplicateBinding.runtime.viewBindings.find(
    (binding) => binding.target === "tableRows",
  );
  assert.ok(firstBinding);
  duplicateBinding.runtime.viewBindings.push({
    ...firstBinding,
    id: "22222222-2222-2222-2222-222222222222",
    sortDirection: firstBinding.sortDirection === "asc" ? "desc" : "asc",
  });
  assert.throws(
    () => parseRendererDocument(duplicateBinding),
    /view bindings contain duplicate node target/,
  );
});

test("form inputs bind by explicit field ID rather than field order", () => {
  const document = createProcurementPrototypeDocument();
  const formDefinition = document.runtime.forms[0];
  assert.ok(formDefinition);
  const reordered = {
    ...document,
    id: "document-1",
    runtime: {
      ...document.runtime,
      forms: [{ ...formDefinition, fields: [...formDefinition.fields].reverse() }],
    },
  };
  const bindings = deriveFormInputBindings(reordered);
  const submitRule = reordered.runtime.rules.find((rule) => rule.trigger.event === "submit");
  assert.ok(submitRule);
  const form = findStructuredPrototypeFormForNode(reordered, submitRule.trigger.nodeId);
  assert.ok(form);
  const inputs = structuredPrototypeInputNodes(form).filter((input) => input.formFieldId !== null);
  assert.equal(bindings.length, inputs.length);
  for (const input of inputs) {
    assert.equal(
      bindings.find((binding) => binding.nodeId === input.id)?.fieldId,
      input.formFieldId,
    );
  }
});

test("published form bindings require every runtime field while drafts may contain unbound inputs", () => {
  const source = createProcurementPrototypeDocument();
  const document = structuredClone({ ...source, id: "document-1" });
  const submitRule = document.runtime.rules.find((rule) => rule.trigger.event === "submit");
  assert.ok(submitRule);
  const form = findStructuredPrototypeFormForNode(document, submitRule.trigger.nodeId);
  assert.ok(form);
  const input = structuredPrototypeInputNodes(form)[0];
  assert.ok(input);
  input.formDefinitionId = null;
  input.formFieldId = null;

  assert.throws(() => deriveFormInputBindings(document), /bind every runtime field/);
  assert.equal(deriveFormInputBindings(document, false).length, 1);
});

test("published renderer takes its brand, theme, and palette from the document", () => {
  const source = createProcurementPrototypeDocument();
  const document = {
    ...source,
    id: "document-1",
    title: "Inventory Console",
    settings: {
      ...source.settings,
      theme: "dark" as const,
      shell: {
        kind: "topbar" as const,
        title: "Inventory Console",
        accentColorTokenKey: "accent-any-name",
        navigationBackgroundColorTokenKey: "navigation-any-name",
        contentBackgroundColorTokenKey: "content-any-name",
        surfaceColorTokenKey: "surface-any-name",
      },
    },
    tokens: {
      colors: [
        { key: "accent-any-name", value: "#112233" },
        { key: "navigation-any-name", value: "#152536" },
        { key: "content-any-name", value: "#181c20" },
        { key: "surface-any-name", value: "#202428" },
      ],
      spacing: source.tokens.spacing,
    },
  };
  const rendered = renderPrototypeDocument(document, "{}", "document-hash", "void 0;");
  const html = rendered.files.find((file) => file.relativePath === "index.html")?.content;
  const styles = rendered.files.find((file) => file.relativePath === "styles.css")?.content;
  assert.match(html ?? "", /<div class="prototype-brand">Inventory Console<\/div>/);
  assert.match(styles ?? "", /--prototype-accent:#112233/);
  assert.match(styles ?? "", /--prototype-navigation-background:#152536/);
  assert.match(styles ?? "", /--prototype-content-background:#181c20/);
  assert.match(styles ?? "", /--prototype-surface:#202428/);
  assert.match(styles ?? "", /color-scheme:dark/);
  assert.deepEqual(resolvePrototypeShellTheme(document), {
    accent: "#112233",
    accentText: "#ffffff",
    navigationBackground: "#152536",
    navigationText: "#ffffff",
    contentBackground: "#181c20",
    contentText: "#ffffff",
    surface: "#202428",
    surfaceText: "#ffffff",
  });
});

test("published renderer uses a neutral top navigation and hides inactive role controls", () => {
  const source = createProcurementPrototypeDocument();
  const document = {
    ...source,
    id: "document-neutral-shell",
    settings: { ...source.settings, shell: topbarShell(source, source.title) },
    runtime: {
      ...source.runtime,
      scenarios: source.runtime.scenarios.map((scenario) => ({
        ...scenario,
        allowSimulatedRoleSwitch: false,
      })),
    },
  };

  const rendered = renderPrototypeDocument(document, "{}", "document-hash", "void 0;");
  const html = rendered.files.find((file) => file.relativePath === "index.html")?.content ?? "";
  const styles = rendered.files.find((file) => file.relativePath === "styles.css")?.content ?? "";

  assert.match(html, /<header class="prototype-header prototype-navigation">/);
  assert.match(html, /<label class="prototype-role" hidden>/);
  assert.doesNotMatch(html, /prototype-sidebar/);
  assert.doesNotMatch(styles, /grid-template-columns:220px/);
});

test("published renderer emits the configured sidebar shell and exact Grid media rules", () => {
  const document = documentWithResponsiveGrid();
  const baseline = createProcurementPrototypeDocument();
  const baselineRender = renderPrototypeDocument(
    { ...baseline, id: "33333333-3333-3333-3333-333333333333" },
    "{}",
    "document-hash",
    "void 0;",
  );
  const rendered = renderPrototypeDocument(document, "{}", "document-hash", "void 0;");
  const html = rendered.files.find((file) => file.relativePath === "index.html")?.content ?? "";
  const styles = rendered.files.find((file) => file.relativePath === "styles.css")?.content ?? "";

  assert.match(html, /<aside class="prototype-sidebar prototype-navigation">/);
  assert.match(html, /<div class="prototype-brand">Orion 采购协同<\/div>/);
  assert.match(styles, /--prototype-navigation-background:#173d38/);
  assert.match(styles, /@media\(min-width:768px\)\{\.prototype-shell-sidebar/);
  assert.match(styles, /grid-template-columns:220px minmax\(0,1fr\)/);
  assert.match(
    styles,
    /@media\(min-width:320px\)\{\[data-prototype-node-id="22222222-2222-2222-2222-222222222222"\]\{grid-template-columns:repeat\(2,minmax\(0,1fr\)\)\}\}/,
  );
  assert.match(
    styles,
    /@media\(min-width:1024px\)\{\[data-prototype-node-id="22222222-2222-2222-2222-222222222222"\]\{grid-template-columns:repeat\(4,minmax\(0,1fr\)\)\}\}/,
  );
  assert.equal(rendered.preflight.nodeCount, baselineRender.preflight.nodeCount + 1);
});

test("structured prototype runtime bindings derive text visibility and rows", () => {
  const entity = {
    id: "request-1",
    schemaId: "request-schema",
    fields: [{ fieldId: "status", value: { type: "enum" as const, value: "approved" } }],
  };
  const viewModel = {
    nodes: [
      {
        nodeId: "detail-status",
        properties: [
          { target: "textContent" as const, value: { type: "enum" as const, value: "approved" } },
        ],
      },
      {
        nodeId: "approve",
        properties: [
          { target: "visibility" as const, value: { type: "boolean" as const, value: false } },
        ],
      },
      {
        nodeId: "table",
        properties: [{ target: "tableRows" as const, rows: [entity] }],
      },
    ],
  };
  assert.equal(runtimeNodeText(viewModel, "detail-status", "pending"), "approved");
  assert.equal(runtimeNodeVisible(viewModel, "approve"), false);
  assert.deepEqual(runtimeNodeRows(viewModel, "table"), [entity]);
  assert.equal(runtimeEntityFieldText(entity, "status"), "approved");
  assert.throws(() => runtimeEntityFieldText(entity, null), /no schema field binding/);
  assert.throws(() => runtimeEntityFieldText(entity, "missing"), /has no value/);
});
