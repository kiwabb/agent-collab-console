import assert from "node:assert/strict";
import test from "node:test";

import {
  buildStructuredPrototypeInspectorBatch,
  buildStructuredPrototypeRuntimeTableCommands,
  createStructuredPrototypeTableRow,
} from "../src/features/prototype/structured/StructuredPrototypeInspector";
import { resolveStructuredPrototypeFreeformGrids } from "../src/features/prototype/structured/structuredPrototypeFreeformGrids";
import { createProcurementPrototypeDocument } from "./fixtures/procurementDocumentFixture";
import type { StructuredPrototypeInspectorDraft } from "../src/features/prototype/structured/StructuredPrototypeInspector";
import type {
  StructuredPrototypeFreeformGrid,
  StructuredPrototypeFreeformNode,
  StructuredPrototypeGridNode,
  StructuredPrototypeNode,
  StructuredPrototypeTableNode,
} from "../src/features/prototype/structured/types";

function inspectorDraftFor(
  node: StructuredPrototypeNode,
  overrides: Partial<StructuredPrototypeInspectorDraft>,
): StructuredPrototypeInspectorDraft {
  return {
    content: "",
    buttonVariant: "primary",
    visibility: node.visibility,
    width: node.layoutItem.width,
    minWidth: node.layoutItem.minWidth,
    maxWidth: node.layoutItem.maxWidth,
    height: node.layoutItem.height,
    minHeight: node.layoutItem.minHeight,
    maxHeight: node.layoutItem.maxHeight,
    grow: node.layoutItem.grow,
    shrink: node.layoutItem.shrink,
    alignSelf: node.layoutItem.alignSelf,
    containerLayout:
      node.type === "Stack"
        ? {
            kind: "stack",
            direction: node.direction,
            gap: node.gap,
            align: node.align,
            justify: node.justify,
            padding: node.padding,
          }
        : node.type === "Grid"
          ? {
              kind: "grid",
              columns: node.columns,
              gap: node.gap,
              padding: node.padding,
              columnOverrides: node.columnOverrides,
            }
          : node.type === "Form"
            ? { kind: "form", gap: node.gap, padding: node.padding }
            : null,
    freeformGrids:
      node.type === "Freeform" ? [...resolveStructuredPrototypeFreeformGrids(node)] : [],
    responsive: node.responsive,
    tableColumns: node.type === "Table" ? node.columns : [],
    tableRows: node.type === "Table" ? node.rows : [],
    ...overrides,
  };
}

function findTableOrNull(node: StructuredPrototypeNode): StructuredPrototypeTableNode | null {
  if (node.type === "Table") return node;
  if ("children" in node) {
    for (const child of node.children) {
      const table = findTableOrNull(child);
      if (table !== null) return table;
    }
  }
  return null;
}

test("Stack, Form, and Table nodes produce common visibility and layout edits", () => {
  const document = createProcurementPrototypeDocument();
  const nodes = [
    document.pages[0]?.root,
    document.pages[1]?.root.type === "Stack" ? document.pages[1].root.children[0] : null,
    document.pages[0]?.root.type === "Stack" ? document.pages[0].root.children[1] : null,
  ];

  for (const node of nodes) {
    assert.ok(node);
    const batch = buildStructuredPrototypeInspectorBatch(
      node,
      inspectorDraftFor(node, {
        visibility: "hidden",
        grow: 2,
        alignSelf: "center",
      }),
    );
    assert.ok(batch);
    assert.deepEqual(batch.commands.slice(-2), [
      {
        kind: "setNodeProperty",
        node: { kind: "existing", nodeId: node.id },
        update: { kind: "visibility", visibility: "hidden" },
      },
      {
        kind: "setNodeLayout",
        node: { kind: "existing", nodeId: node.id },
        update: { grow: 2, alignSelf: "center" },
      },
    ]);
  }
});

test("Text inspector combines content and common layout edits atomically", () => {
  const document = createProcurementPrototypeDocument();
  const root = document.pages[0]?.root;
  assert.equal(root?.type, "Stack");
  const text = root.children[0];
  assert.equal(text?.type, "Text");

  const batch = buildStructuredPrototypeInspectorBatch(
    text,
    inspectorDraftFor(text, {
      content: "采购申请总览",
      grow: 1,
    }),
  );
  assert.ok(batch);
  assert.deepEqual(
    batch.commands.map((command) => command.kind),
    ["setNodeProperty", "setNodeLayout"],
  );
});

test("unchanged inspector state creates no command batch", () => {
  const document = createProcurementPrototypeDocument();
  const root = document.pages[0]?.root;
  assert.ok(root);
  assert.equal(
    buildStructuredPrototypeInspectorBatch(root, {
      ...inspectorDraftFor(root, {}),
    }),
    null,
  );
});

test("Freeform grid save emits one property command and skips unchanged grids", () => {
  const document = createProcurementPrototypeDocument();
  const root = document.pages[0]?.root;
  assert.ok(root);
  const freeform: StructuredPrototypeFreeformNode = {
    id: "00000000-0000-4000-8000-000000000097",
    type: "Freeform",
    name: "Grid canvas",
    visibility: "visible",
    layoutItem: structuredClone(root.layoutItem),
    responsive: [],
    children: [],
  };
  const grid: StructuredPrototypeFreeformGrid = {
    id: "00000000-0000-4000-8000-000000000096",
    version: 1,
    type: "square",
    visible: true,
    snapEnabled: true,
    origin: { x: "12", y: "16" },
    params: {
      size: "8",
      colorTokenKey: "accent",
      opacity: "0.4",
    },
  };

  const batch = buildStructuredPrototypeInspectorBatch(
    freeform,
    inspectorDraftFor(freeform, { freeformGrids: [grid] }),
  );

  assert.ok(batch);
  assert.deepEqual(batch.commands, [
    {
      kind: "setNodeProperty",
      node: { kind: "existing", nodeId: freeform.id },
      update: { kind: "freeformGrids", grids: [grid] },
    },
  ]);

  const configuredGrids = [structuredClone(grid)];
  const configuredFreeform: StructuredPrototypeFreeformNode = {
    ...freeform,
    grids: configuredGrids,
  };
  assert.equal(
    buildStructuredPrototypeInspectorBatch(
      configuredFreeform,
      inspectorDraftFor(configuredFreeform, {
        freeformGrids: structuredClone(configuredGrids),
      }),
    ),
    null,
  );
});

test("inspector emits width and height layout edits", () => {
  const document = createProcurementPrototypeDocument();
  const root = document.pages[0]?.root;
  assert.ok(root);

  const batch = buildStructuredPrototypeInspectorBatch(
    root,
    inspectorDraftFor(root, {
      width: { unit: "px", value: "640" },
      height: { unit: "rem", value: "12" },
    }),
  );

  assert.ok(batch);
  assert.deepEqual(batch.commands.at(-1), {
    kind: "setNodeLayout",
    node: { kind: "existing", nodeId: root.id },
    update: {
      width: { unit: "px", value: "640" },
      height: { unit: "rem", value: "12" },
    },
  });
});

test("inspector combines constraints, flex sizing, and alignment in one layout command", () => {
  const document = createProcurementPrototypeDocument();
  const root = document.pages[0]?.root;
  assert.ok(root);

  const batch = buildStructuredPrototypeInspectorBatch(
    root,
    inspectorDraftFor(root, {
      minWidth: { unit: "px", value: "320" },
      maxWidth: { unit: "percent", value: "100" },
      minHeight: { unit: "rem", value: "8" },
      maxHeight: null,
      grow: 2,
      shrink: 0,
      alignSelf: "center",
    }),
  );

  assert.ok(batch);
  const layoutCommands = batch.commands.filter((command) => command.kind === "setNodeLayout");
  assert.equal(layoutCommands.length, 1);
  assert.deepEqual(layoutCommands[0], {
    kind: "setNodeLayout",
    node: { kind: "existing", nodeId: root.id },
    update: {
      minWidth: { unit: "px", value: "320" },
      maxWidth: { unit: "percent", value: "100" },
      minHeight: { unit: "rem", value: "8" },
      grow: 2,
      shrink: 0,
      alignSelf: "center",
    },
  });
});

test("container inspector emits typed Stack, Grid, and Form layout updates", () => {
  const document = createProcurementPrototypeDocument();
  const listPage = document.pages[0];
  const createPage = document.pages[1];
  assert.ok(listPage);
  assert.ok(createPage);
  const stack = listPage.root;
  assert.equal(stack.type, "Stack");
  if (stack.type !== "Stack") throw new Error("fixture list root is not a Stack");
  const form = createPage.root.type === "Stack" ? createPage.root.children[0] : null;
  assert.equal(form?.type, "Form");
  if (form?.type !== "Form") throw new Error("fixture create form is missing");
  const grid: StructuredPrototypeGridNode = {
    id: "00000000-0000-4000-8000-000000000099",
    type: "Grid",
    name: "Test grid",
    visibility: "visible",
    layoutItem: structuredClone(stack.layoutItem),
    responsive: [],
    columns: 2,
    gap: 12,
    padding: { top: 8, right: 8, bottom: 8, left: 8 },
    columnOverrides: [{ minWidth: 1024, columns: 4 }],
    children: [],
  };

  const stackBatch = buildStructuredPrototypeInspectorBatch(
    stack,
    inspectorDraftFor(stack, {
      containerLayout: {
        kind: "stack",
        direction: stack.direction === "row" ? "column" : "row",
        gap: 24,
        align: "center",
        justify: "between",
        padding: { top: 1, right: 2, bottom: 3, left: 4 },
      },
    }),
  );
  assert.deepEqual(stackBatch?.commands.at(-1), {
    kind: "setNodeProperty",
    node: { kind: "existing", nodeId: stack.id },
    update: {
      kind: "stackLayout",
      direction: stack.direction === "row" ? "column" : "row",
      gap: 24,
      align: "center",
      justify: "between",
      padding: { top: 1, right: 2, bottom: 3, left: 4 },
    },
  });

  const gridBatch = buildStructuredPrototypeInspectorBatch(
    grid,
    inspectorDraftFor(grid, {
      containerLayout: {
        kind: "grid",
        columns: 3,
        gap: 20,
        padding: grid.padding,
        columnOverrides: grid.columnOverrides,
      },
    }),
  );
  const gridCommand = gridBatch?.commands.at(-1);
  assert.equal(gridCommand?.kind, "setNodeProperty");
  if (gridCommand?.kind !== "setNodeProperty") throw new Error("grid layout command is missing");
  assert.deepEqual(gridCommand.update, {
    kind: "gridLayout",
    columns: 3,
    gap: 20,
    padding: grid.padding,
    columnOverrides: grid.columnOverrides,
  });

  const formBatch = buildStructuredPrototypeInspectorBatch(
    form,
    inspectorDraftFor(form, {
      containerLayout: { kind: "form", gap: 18, padding: form.padding },
    }),
  );
  const formCommand = formBatch?.commands.at(-1);
  assert.equal(formCommand?.kind, "setNodeProperty");
  if (formCommand?.kind !== "setNodeProperty") throw new Error("form layout command is missing");
  assert.equal(formCommand.update.kind, "formLayout");
});

test("inspector emits ordered responsive layout updates", () => {
  const document = createProcurementPrototypeDocument();
  const root = document.pages[0]?.root;
  assert.ok(root);

  const batch = buildStructuredPrototypeInspectorBatch(
    root,
    inspectorDraftFor(root, {
      responsive: [
        { breakpoint: "sm", layoutItem: { width: { unit: "percent", value: "100" } } },
        { breakpoint: "lg", layoutItem: { width: { unit: "px", value: "960" } } },
      ],
    }),
  );

  assert.deepEqual(batch?.commands.at(-1), {
    kind: "setNodeProperty",
    node: { kind: "existing", nodeId: root.id },
    update: {
      kind: "responsiveLayout",
      responsive: [
        { breakpoint: "sm", layoutItem: { width: { unit: "percent", value: "100" } } },
        { breakpoint: "lg", layoutItem: { width: { unit: "px", value: "960" } } },
      ],
    },
  });
});

test("Inspector saves responsive and Grid overrides in one atomic batch", () => {
  const document = createProcurementPrototypeDocument();
  const root = document.pages[0]?.root;
  assert.equal(root?.type, "Stack");
  if (root?.type !== "Stack") throw new Error("fixture list root is not a Stack");
  const grid: StructuredPrototypeGridNode = {
    id: "00000000-0000-4000-8000-000000000098",
    type: "Grid",
    name: "Responsive grid",
    visibility: "visible",
    layoutItem: structuredClone(root.layoutItem),
    responsive: [],
    columns: 2,
    gap: 12,
    padding: { top: 8, right: 8, bottom: 8, left: 8 },
    columnOverrides: [],
    children: [],
  };
  const responsive = [
    {
      breakpoint: "sm" as const,
      layoutItem: { width: { unit: "percent" as const, value: "100" } },
    },
  ];
  const columnOverrides = [{ minWidth: 1024, columns: 4 }];

  const batch = buildStructuredPrototypeInspectorBatch(
    grid,
    inspectorDraftFor(grid, {
      responsive,
      containerLayout: {
        kind: "grid",
        columns: grid.columns,
        gap: grid.gap,
        padding: grid.padding,
        columnOverrides,
      },
    }),
  );

  assert.ok(batch);
  assert.deepEqual(batch.commands, [
    {
      kind: "setNodeProperty",
      node: { kind: "existing", nodeId: grid.id },
      update: {
        kind: "gridLayout",
        columns: grid.columns,
        gap: grid.gap,
        padding: grid.padding,
        columnOverrides,
      },
    },
    {
      kind: "setNodeProperty",
      node: { kind: "existing", nodeId: grid.id },
      update: { kind: "responsiveLayout", responsive },
    },
  ]);
});

test("table inspector emits editable table data", () => {
  const document = createProcurementPrototypeDocument();
  const page = document.pages[0];
  assert.ok(page);
  const table = findTableOrNull(page.root);
  assert.ok(table);
  const nextRows = [
    {
      id: "00000000-0000-4000-8000-000000000001",
      cells: table.columns.map((column, index) => ({
        columnKey: column.key,
        value: index === 0 ? "edited cell" : "",
      })),
    },
  ];

  const batch = buildStructuredPrototypeInspectorBatch(
    table,
    inspectorDraftFor(table, { tableRows: nextRows }),
  );

  assert.ok(batch);
  assert.deepEqual(batch.commands.at(-1), {
    kind: "setNodeProperty",
    node: { kind: "existing", nodeId: table.id },
    update: {
      kind: "tableData",
      columns: table.columns,
      rows: nextRows,
    },
  });
});

test("new static table rows use backend-compatible UUIDs", () => {
  const row = createStructuredPrototypeTableRow([
    { key: "name", label: "Name", fieldId: null },
    { key: "status", label: "Status", fieldId: null },
  ]);

  assert.match(row.id, /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  assert.deepEqual(row.cells, [
    { columnKey: "name", value: "" },
    { columnKey: "status", value: "" },
  ]);
});

test("runtime table inspector emits fixture field edit commands", () => {
  const commands = buildStructuredPrototypeRuntimeTableCommands(
    {
      scenarioId: "scenario-1",
      schemaId: "schema-1",
      fields: [
        {
          id: "field-title",
          key: "title",
          valueType: "string",
          nullable: false,
        },
        {
          id: "field-status",
          key: "status",
          valueType: "enum",
          nullable: false,
        },
      ],
      rows: [
        {
          id: "entity-1",
          schemaId: "schema-1",
          fields: [
            { fieldId: "field-title", value: { type: "string", value: "old title" } },
            { fieldId: "field-status", value: { type: "enum", value: "pending" } },
          ],
        },
      ],
    },
    [
      {
        id: "entity-1",
        schemaId: "schema-1",
        fields: [
          { fieldId: "field-title", value: { type: "string", value: "new title" } },
          { fieldId: "field-status", value: { type: "enum", value: "pending" } },
        ],
      },
    ],
  );

  assert.deepEqual(commands, [
    {
      kind: "setRuntimeEntityField",
      scenarioId: "scenario-1",
      schemaId: "schema-1",
      entityId: "entity-1",
      fieldId: "field-title",
      value: { type: "string", value: "new title" },
    },
  ]);
});
