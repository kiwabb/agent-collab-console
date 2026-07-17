import assert from "node:assert/strict";
import test from "node:test";

import type { RuntimeFormDefinition } from "../src/features/prototype/runtime/types";
import type {
  StructuredPrototypeDocument,
  StructuredPrototypeFreeformNode,
} from "../src/features/prototype/structured/types";
import {
  createPaletteNode,
  insertPaletteNodeBatch,
  moveFreeformSelectionBatch,
  moveNodeBatch,
  removeNodeBatch,
  removeNodesBatch,
  reorderPageBatch,
  resolveStructuredPrototypeNavigationReorderCommands,
  resolvePaletteFormDefinition,
  setRuntimeFlowNodePositionBatch,
  setRuntimeEntityFieldBatch,
  setFreeformGroupLayoutBatch,
} from "../src/features/prototype/structured/structuredPrototypeCommands";
import { isStructuredPrototypeContainerNode } from "../src/features/prototype/structured/structuredPrototypeNodes";
import {
  createProcurementPrototypeDocument,
  STRUCTURED_PROCUREMENT_IDS,
} from "./fixtures/procurementDocumentFixture";

const formDefinition: RuntimeFormDefinition = {
  id: "form-1",
  key: "profile",
  fields: [
    {
      id: "field-name",
      key: "name",
      valueType: "string",
      initialValue: { type: "string", value: "" },
      required: true,
      minInteger: null,
    },
    {
      id: "field-age",
      key: "age",
      valueType: "integer",
      initialValue: { type: "integer", value: 18 },
      required: false,
      minInteger: 0,
    },
  ],
};

const labels = {
  Freeform: "Freeform",
  Stack: "Stack",
  Grid: "Grid",
  Form: "Form",
  Text: "Text",
  Input: "Input",
  Button: "Button",
  Table: "Table",
};

function commandDocument(): StructuredPrototypeDocument {
  return {
    ...createProcurementPrototypeDocument(),
    id: "00000000-0000-4000-8000-000000000100",
  };
}

test("all eight palette types produce bounded structured nodes", () => {
  const types = ["Freeform", "Stack", "Grid", "Form", "Text", "Input", "Button", "Table"] as const;
  for (const type of types) {
    const node = createPaletteNode(type, `new-${type.toLowerCase()}`, formDefinition, labels);
    assert.equal(node.type, type);
    assert.equal(node.visibility, "visible");
    assert.equal(node.layoutItem.width.unit, type === "Freeform" ? "px" : "auto");
  }
  const grid = createPaletteNode("Grid", "new-grid", null, labels);
  assert.equal(grid.type, "Grid");
  assert.equal(grid.columns, 1);
  assert.deepEqual(grid.columnOverrides, [{ minWidth: 768, columns: 2 }]);
  assert.deepEqual(grid.children, []);
  const freeform = createPaletteNode("Freeform", "new-freeform", null, labels);
  assert.equal(freeform.type, "Freeform");
  assert.deepEqual(freeform.layoutItem.width, { unit: "px", value: "960" });
  assert.deepEqual(freeform.layoutItem.height, { unit: "px", value: "640" });
  assert.deepEqual(freeform.children, []);
  const form = createPaletteNode("Form", "new-form", formDefinition, labels);
  assert.equal(form.type, "Form");
  assert.equal(form.children.length, 2);
  assert.deepEqual(
    form.children.map((child) =>
      child.type === "Input"
        ? [child.newNodeKey, child.formDefinitionId, child.formFieldId, child.inputType]
        : null,
    ),
    [
      ["new-form-name", "form-1", "field-name", "text"],
      ["new-form-age", "form-1", "field-age", "number"],
    ],
  );
  assert.throws(() => createPaletteNode("Form", "missing-form", null, labels));
  const text = createPaletteNode("Text", "localized-text", null, labels);
  const input = createPaletteNode("Input", "localized-input", null, labels);
  const button = createPaletteNode("Button", "localized-button", null, labels);
  const table = createPaletteNode("Table", "localized-table", null, labels);
  assert.equal(text.type === "Text" ? text.content : null, "Text");
  assert.equal(input.type === "Input" ? input.label : null, "Input");
  assert.equal(button.type === "Button" ? button.label : null, "Button");
  assert.equal(table.type === "Table" ? table.columns[0]?.label : null, "Table");
});

test("palette insert and component move preserve explicit target position", () => {
  const text = createPaletteNode("Text", "new-text", formDefinition, labels);
  const root = commandDocument().pages[0]?.root;
  assert.ok(root && isStructuredPrototypeContainerNode(root));
  assert.deepEqual(insertPaletteNodeBatch(root, 2, text).commands[0], {
    kind: "insertNode",
    parent: { kind: "existing", nodeId: root.id },
    slot: null,
    index: 2,
    node: text,
  });
  assert.deepEqual(moveNodeBatch("node", root, 1).commands[0], {
    kind: "moveNode",
    node: { kind: "existing", nodeId: "node" },
    targetParent: { kind: "existing", nodeId: root.id },
    targetSlot: null,
    targetIndex: 1,
  });
});

test("freeform selection moves use positioned same-parent commands in document order", () => {
  const document = commandDocument();
  const sourceRoot = document.pages[0]?.root;
  assert.ok(sourceRoot && isStructuredPrototypeContainerNode(sourceRoot));
  const root: StructuredPrototypeFreeformNode = {
    id: "00000000-0000-4000-8000-000000000200",
    type: "Freeform",
    name: "Freeform",
    visibility: "visible",
    layoutItem: sourceRoot.layoutItem,
    responsive: [],
    children: sourceRoot.children,
  };
  const first = root.children[0];
  const second = root.children[1];
  assert.ok(first && second);

  const batch = moveFreeformSelectionBatch(
    root,
    [
      { nodeId: second.id, x: 300.125, y: 72.5 },
      { nodeId: first.id, x: 12, y: 24 },
    ],
    "Move two freeform components",
  );

  assert.deepEqual(batch, {
    commandContractVersion: 1,
    summary: "Move two freeform components",
    commands: [
      {
        kind: "moveNode",
        node: { kind: "existing", nodeId: first.id },
        targetParent: { kind: "existing", nodeId: root.id },
        targetSlot: null,
        targetIndex: 0,
        targetPosition: { x: "12", y: "24" },
      },
      {
        kind: "moveNode",
        node: { kind: "existing", nodeId: second.id },
        targetParent: { kind: "existing", nodeId: root.id },
        targetSlot: null,
        targetIndex: 1,
        targetPosition: { x: "300.125", y: "72.5" },
      },
    ],
  });
  assert.throws(
    () =>
      moveFreeformSelectionBatch(
        root,
        [{ nodeId: "not-a-direct-child", x: 0, y: 0 }],
        "Invalid move",
      ),
    /direct child/u,
  );
});

test("component removal and page reordering use structured command contracts", () => {
  assert.deepEqual(removeNodeBatch("node-to-delete"), {
    commandContractVersion: 1,
    summary: "Remove component",
    commands: [{ kind: "removeNode", nodeId: "node-to-delete" }],
  });
  assert.deepEqual(removeNodesBatch(["first", "second"]), {
    commandContractVersion: 1,
    summary: "Remove 2 components",
    commands: [
      { kind: "removeNode", nodeId: "first" },
      { kind: "removeNode", nodeId: "second" },
    ],
  });
  const document = commandDocument();
  assert.deepEqual(reorderPageBatch(document, STRUCTURED_PROCUREMENT_IDS.pages.detail, 0), {
    commandContractVersion: 1,
    summary: "Reorder page",
    commands: [
      { kind: "reorderPage", pageId: STRUCTURED_PROCUREMENT_IDS.pages.detail, targetIndex: 0 },
      {
        kind: "reorderNavigationItem",
        itemId: STRUCTURED_PROCUREMENT_IDS.navigation.detail,
        targetIndex: 0,
      },
    ],
  });
});

test("group layout commands persist positions and resized frames in one atomic batch", () => {
  const items = [
    { nodeId: "first", x: 12.34567, y: 20, width: 80, height: 40 },
    { nodeId: "second", x: 120, y: 70, width: 60, height: 50 },
  ];
  assert.deepEqual(setFreeformGroupLayoutBatch(items, "position", "Arrange components"), {
    commandContractVersion: 1,
    summary: "Arrange components",
    commands: [
      {
        kind: "setNodeLayout",
        node: { kind: "existing", nodeId: "first" },
        update: { position: { x: "12.3457", y: "20" } },
      },
      {
        kind: "setNodeLayout",
        node: { kind: "existing", nodeId: "second" },
        update: { position: { x: "120", y: "70" } },
      },
    ],
  });
  assert.deepEqual(setFreeformGroupLayoutBatch(items, "frame", "Resize components").commands[0], {
    kind: "setNodeLayout",
    node: { kind: "existing", nodeId: "first" },
    update: {
      width: { unit: "px", value: "80" },
      height: { unit: "px", value: "40" },
      position: { x: "12.3457", y: "20" },
    },
  });
  assert.throws(() => setFreeformGroupLayoutBatch([], "position", "Empty"), /requires 1 to 100/);
});

test("navigation reorder commands deterministically transform the current order", () => {
  const current = [
    { id: "nav-a", key: "a", label: "A", targetPageId: "page-a" },
    { id: "nav-b", key: "b", label: "B", targetPageId: "page-b" },
    { id: "nav-c", key: "c", label: "C", targetPageId: "page-c" },
  ];
  const first = current[0];
  const second = current[1];
  const third = current[2];
  assert.ok(first);
  assert.ok(second);
  assert.ok(third);
  assert.deepEqual(
    resolveStructuredPrototypeNavigationReorderCommands(current, [third, first, second]),
    [{ kind: "reorderNavigationItem", itemId: "nav-c", targetIndex: 0 }],
  );
});

test("invalid page reorder targets are refused before submission", () => {
  const document = commandDocument();
  assert.equal(reorderPageBatch(document, "missing-page", 0), null);
  assert.equal(reorderPageBatch(document, STRUCTURED_PROCUREMENT_IDS.pages.list, 99), null);
});

test("runtime table field edits use document command contracts", () => {
  assert.deepEqual(
    setRuntimeEntityFieldBatch("scenario-1", "schema-1", "entity-1", "field-1", {
      type: "string",
      value: "edited",
    }),
    {
      commandContractVersion: 1,
      summary: "Edit runtime table cell",
      commands: [
        {
          kind: "setRuntimeEntityField",
          scenarioId: "scenario-1",
          schemaId: "schema-1",
          entityId: "entity-1",
          fieldId: "field-1",
          value: { type: "string", value: "edited" },
        },
      ],
    },
  );
});

test("flow node moves use one canonical structured command batch", () => {
  assert.deepEqual(setRuntimeFlowNodePositionBatch("flow-node-1", 10.6, -20.5), {
    commandContractVersion: 1,
    summary: "Move flow node",
    commands: [
      {
        kind: "setRuntimeFlowNodePosition",
        flowNodeId: "flow-node-1",
        x: 11,
        y: -20,
      },
    ],
  });
});

test("multi-form palette insertion requires an explicit form selection", () => {
  const secondForm = { ...formDefinition, id: "form-2", key: "settings" };

  assert.equal(resolvePaletteFormDefinition([formDefinition], null)?.id, "form-1");
  assert.equal(resolvePaletteFormDefinition([formDefinition, secondForm], null), null);
  assert.equal(
    resolvePaletteFormDefinition([formDefinition, secondForm], "form-2")?.key,
    "settings",
  );
  assert.equal(resolvePaletteFormDefinition([formDefinition], "missing")?.id, "form-1");
  assert.equal(resolvePaletteFormDefinition([formDefinition, secondForm], "missing"), null);
});
