import assert from "node:assert/strict";
import test from "node:test";

import { renderPrototypeDocument } from "../src/features/prototype/structured/prototypeRendererCore";
import { parseRendererDocument } from "../src/features/prototype/structured/rendererDocumentCodec";
import {
  createPaletteNode,
  insertPaletteNodeBatch,
  moveNodeBatch,
} from "../src/features/prototype/structured/structuredPrototypeCommands";
import {
  materializeStructuredPrototypePalettePreviewNode,
  projectStructuredPrototypeNodeInsert,
  projectStructuredPrototypeNodeMove,
  projectStructuredPrototypeNodeMoveToDropTarget,
} from "../src/features/prototype/structured/structuredPrototypeDrag";
import { findStructuredPrototypeNode } from "../src/features/prototype/structured/structuredPrototypeDerived";
import { resolveStructuredPrototypeFreeformGrids } from "../src/features/prototype/structured/structuredPrototypeFreeformGrids";
import { isStructuredPrototypeContainerNode } from "../src/features/prototype/structured/structuredPrototypeNodes";
import type {
  StructuredPrototypeDocument,
  StructuredPrototypeFreeformGrid,
  StructuredPrototypeFreeformNode,
} from "../src/features/prototype/structured/types";
import { createProcurementPrototypeDocument } from "./fixtures/procurementDocumentFixture";

const labels = {
  Freeform: "Freeform",
  Stack: "Stack",
  Grid: "Grid",
  Form: "Form",
  Text: "Text",
  Input: "Input",
  Button: "Button",
  Table: "Table",
  Divider: "Divider",
  Badge: "Badge",
};

function legacyDocument(): StructuredPrototypeDocument {
  return structuredClone({
    ...createProcurementPrototypeDocument(),
    id: "00000000-0000-4000-8000-000000000100",
  });
}

function freeformDocument(): StructuredPrototypeDocument {
  const document = legacyDocument();
  const page = document.pages[0];
  assert.ok(page);
  const originalRoot = page.root;
  const freeform: StructuredPrototypeFreeformNode = {
    id: "00000000-0000-4000-8000-000000000101",
    name: "Freeform canvas",
    visibility: "visible",
    layoutItem: {
      width: { unit: "px", value: "960" },
      minWidth: null,
      maxWidth: null,
      height: { unit: "px", value: "640" },
      minHeight: null,
      maxHeight: null,
      grow: 0,
      shrink: 0,
      alignSelf: "start",
    },
    responsive: [],
    type: "Freeform",
    children: [
      {
        ...originalRoot,
        layoutItem: {
          ...originalRoot.layoutItem,
          position: { x: "24.5", y: "0.5" },
        },
      },
    ],
  };
  return {
    ...document,
    pages: document.pages.map((candidate, index) =>
      index === 0 ? { ...candidate, root: freeform } : candidate,
    ),
  };
}

test("legacy document layout shape remains position-free", () => {
  const parsed = parseRendererDocument(legacyDocument());
  const root = parsed.pages[0]?.root;
  assert.ok(root);
  assert.equal(Object.hasOwn(root.layoutItem, "position"), false);
});

test("Freeform validates, traverses, and renders absolute direct children", () => {
  const parsed = parseRendererDocument(freeformDocument());
  const root = parsed.pages[0]?.root;
  assert.equal(root?.type, "Freeform");
  assert.ok(root && isStructuredPrototypeContainerNode(root));
  assert.equal(Object.hasOwn(root, "grids"), false);
  assert.deepEqual(resolveStructuredPrototypeFreeformGrids(root), []);
  const child = root.children[0];
  assert.ok(child);
  assert.equal(findStructuredPrototypeNode(root, child.id)?.id, child.id);

  const rendered = renderPrototypeDocument(parsed, "{}", "document-hash", "void 0;");
  const html = rendered.files.find((file) => file.relativePath === "index.html")?.content ?? "";
  const css = rendered.files.find((file) => file.relativePath === "styles.css")?.content ?? "";
  assert.match(html, /data-prototype-node-type="Freeform"/);
  assert.match(html, /class="prototype-freeform"/);
  assert.match(
    css,
    new RegExp(
      `data-prototype-node-id="${child.id}"[^}]*position:absolute[^}]*left:24\\.5px[^}]*top:0\\.5px`,
    ),
  );
  assert.match(
    css,
    /data-prototype-node-id="00000000-0000-4000-8000-000000000101"[^}]*position:relative[^}]*overflow:hidden/,
  );
});

test("Freeform grid variants validate without changing the legacy empty-grid shape", () => {
  const document = freeformDocument();
  const root = document.pages[0]?.root;
  assert.equal(root?.type, "Freeform");
  if (root?.type !== "Freeform") throw new Error("expected Freeform root");
  const colorTokenKey = document.settings.shell.accentColorTokenKey;
  const grids: StructuredPrototypeFreeformGrid[] = [
    {
      id: "00000000-0000-4000-8000-000000000110",
      version: 1,
      type: "square",
      visible: true,
      snapEnabled: true,
      origin: { x: "0", y: "0" },
      params: { size: "16", colorTokenKey, opacity: "0.4" },
    },
    {
      id: "00000000-0000-4000-8000-000000000111",
      version: 1,
      type: "columns",
      visible: true,
      snapEnabled: true,
      origin: { x: "0", y: "0" },
      params: {
        count: 12,
        itemSize: null,
        gutter: "8",
        margin: "0",
        alignment: "stretch",
        colorTokenKey,
        opacity: "0.1",
      },
    },
    {
      id: "00000000-0000-4000-8000-000000000112",
      version: 1,
      type: "rows",
      visible: false,
      snapEnabled: true,
      origin: { x: "4", y: "8" },
      params: {
        count: 4,
        itemSize: "64",
        gutter: "12",
        margin: "16",
        alignment: "center",
        colorTokenKey,
        opacity: "0.2",
      },
    },
  ];
  root.grids = grids;

  const parsed = parseRendererDocument(document);
  const parsedRoot = parsed.pages[0]?.root;
  assert.equal(parsedRoot?.type, "Freeform");
  if (parsedRoot?.type !== "Freeform") throw new Error("expected parsed Freeform root");
  assert.deepEqual(resolveStructuredPrototypeFreeformGrids(parsedRoot), grids);
  const rendered = renderPrototypeDocument(parsed, "{}", "document-hash", "void 0;");
  for (const file of rendered.files) {
    assert.doesNotMatch(file.content, /data-prototype-layout-grid/u);
  }

  delete root.grids;
  const legacy = parseRendererDocument(document);
  const legacyRoot = legacy.pages[0]?.root;
  assert.equal(legacyRoot?.type, "Freeform");
  assert.ok(legacyRoot?.type === "Freeform");
  assert.equal(Object.hasOwn(legacyRoot, "grids"), false);
});

test("Freeform grid contract rejects unknown, duplicate, and impossible values", () => {
  const base = freeformDocument();
  const baseRoot = base.pages[0]?.root;
  assert.equal(baseRoot?.type, "Freeform");
  if (baseRoot?.type !== "Freeform") throw new Error("expected Freeform root");
  const colorTokenKey = base.settings.shell.accentColorTokenKey;
  baseRoot.grids = [
    {
      id: "00000000-0000-4000-8000-000000000120",
      version: 1,
      type: "square",
      visible: true,
      snapEnabled: true,
      origin: { x: "0", y: "0" },
      params: { size: "16", colorTokenKey, opacity: "0.4" },
    },
  ];

  const unknownField = structuredClone(base) as unknown as {
    pages: Array<{ root: { grids: Array<Record<string, unknown>> } }>;
  };
  unknownField.pages[0]?.root.grids[0] &&
    (unknownField.pages[0].root.grids[0]["unexpected"] = true);
  assert.throws(() => parseRendererDocument(unknownField), /contains unknown field unexpected/);

  const duplicateId = structuredClone(base);
  const duplicateRoot = duplicateId.pages[0]?.root;
  assert.equal(duplicateRoot?.type, "Freeform");
  if (duplicateRoot?.type !== "Freeform") throw new Error("expected Freeform root");
  const firstGrid = duplicateRoot.grids?.[0];
  assert.ok(firstGrid);
  duplicateRoot.grids = [firstGrid, structuredClone(firstGrid)];
  assert.throws(() => parseRendererDocument(duplicateId), /grids\[1\]\.id is duplicated/);

  const pageIdCollision = structuredClone(base);
  const pageCollisionRoot = pageIdCollision.pages[0]?.root;
  const pageCollisionGrid =
    pageCollisionRoot?.type === "Freeform" ? pageCollisionRoot.grids?.[0] : undefined;
  const pageId = pageIdCollision.pages[0]?.id;
  assert.ok(pageCollisionGrid && pageId);
  pageCollisionGrid.id = pageId;
  assert.throws(
    () => parseRendererDocument(pageIdCollision),
    /pages\[0\]\.root\.grids\[0\]\.id is duplicated/,
  );

  const runtimeIdCollision = structuredClone(base);
  const runtimeCollisionRoot = runtimeIdCollision.pages[0]?.root;
  const runtimeCollisionGrid =
    runtimeCollisionRoot?.type === "Freeform" ? runtimeCollisionRoot.grids?.[0] : undefined;
  const roleId = runtimeIdCollision.runtime.roles[0]?.id;
  assert.ok(runtimeCollisionGrid && roleId);
  runtimeCollisionGrid.id = roleId;
  assert.throws(
    () => parseRendererDocument(runtimeIdCollision),
    /runtime\.roles\[0\]\.id is duplicated/,
  );

  const unknownToken = structuredClone(base);
  const unknownTokenRoot = unknownToken.pages[0]?.root;
  assert.equal(unknownTokenRoot?.type, "Freeform");
  if (unknownTokenRoot?.type !== "Freeform") throw new Error("expected Freeform root");
  const unknownTokenGrid = unknownTokenRoot.grids?.[0];
  assert.ok(unknownTokenGrid);
  unknownTokenGrid.params.colorTokenKey = "missing-color";
  assert.throws(() => parseRendererDocument(unknownToken), /unknown color token/);

  const impossible = structuredClone(base);
  const impossibleRoot = impossible.pages[0]?.root;
  assert.equal(impossibleRoot?.type, "Freeform");
  if (impossibleRoot?.type !== "Freeform") throw new Error("expected Freeform root");
  impossibleRoot.grids = [
    {
      id: "00000000-0000-4000-8000-000000000121",
      version: 1,
      type: "columns",
      visible: true,
      snapEnabled: true,
      origin: { x: "0", y: "0" },
      params: {
        count: 24,
        itemSize: "64",
        gutter: "64",
        margin: "64",
        alignment: "start",
        colorTokenKey,
        opacity: "0.1",
      },
    },
  ];
  assert.throws(() => parseRendererDocument(impossible), /does not fit inside its Freeform/);
});

test("Freeform position invariants fail closed at the document boundary", () => {
  const missingPosition = structuredClone(freeformDocument());
  const freeform = missingPosition.pages[0]?.root;
  assert.equal(freeform?.type, "Freeform");
  assert.ok(freeform && isStructuredPrototypeContainerNode(freeform));
  const child = freeform.children[0];
  assert.ok(child);
  delete child.layoutItem.position;
  assert.throws(
    () => parseRendererDocument(missingPosition),
    /position is required inside a Freeform container/,
  );

  const positionOutsideFreeform = legacyDocument();
  const legacyRoot = positionOutsideFreeform.pages[0]?.root;
  assert.ok(legacyRoot);
  legacyRoot.layoutItem.position = { x: "1", y: "2" };
  assert.throws(
    () => parseRendererDocument(positionOutsideFreeform),
    /position is forbidden on a document or component root/,
  );

  const autoSized = freeformDocument();
  const autoSizedRoot = autoSized.pages[0]?.root;
  assert.equal(autoSizedRoot?.type, "Freeform");
  if (autoSizedRoot?.type !== "Freeform") throw new Error("expected Freeform root");
  autoSizedRoot.layoutItem.width = { unit: "auto", value: null };
  assert.throws(
    () => parseRendererDocument(autoSized),
    /Freeform width and height must be non-zero px lengths/,
  );

  const responsivePosition = freeformDocument() as unknown as {
    pages: Array<{ root: StructuredPrototypeFreeformNode }>;
  };
  const responsiveChild = responsivePosition.pages[0]?.root.children[0];
  assert.ok(responsiveChild);
  responsiveChild.responsive = [
    {
      breakpoint: "sm",
      layoutItem: { position: { x: "10", y: "10" } },
    } as never,
  ];
  assert.throws(
    () => parseRendererDocument(responsivePosition),
    /responsive\[0\]\.layoutItem contains unknown field position/,
  );
});

test("layout containers accept flow and explicit-position direct children while roots reject position", () => {
  const stackDocument = legacyDocument();
  const stack = stackDocument.pages[0]?.root;
  assert.equal(stack?.type, "Stack");
  if (stack?.type !== "Stack") throw new Error("expected Stack root");
  const positionedStackChild = stack.children[0];
  const flowStackChild = stack.children[1];
  assert.ok(positionedStackChild && flowStackChild);
  positionedStackChild.layoutItem = {
    ...positionedStackChild.layoutItem,
    position: { x: "12.5", y: "24" },
  };
  assert.equal(parseRendererDocument(stackDocument).id, stackDocument.id);

  const gridDocument = legacyDocument();
  const gridPage = gridDocument.pages[0];
  assert.ok(gridPage);
  const originalGridRoot = gridPage.root;
  assert.equal(originalGridRoot?.type, "Stack");
  if (originalGridRoot?.type !== "Stack") throw new Error("expected Stack root");
  const gridChildren = originalGridRoot.children;
  const positionedGridChild = gridChildren[0];
  const flowGridChild = gridChildren[1];
  assert.ok(positionedGridChild && flowGridChild);
  positionedGridChild.layoutItem = {
    ...positionedGridChild.layoutItem,
    position: { x: "36", y: "48.25" },
  };
  gridDocument.pages[0] = {
    ...gridPage,
    root: {
      id: originalGridRoot.id,
      name: originalGridRoot.name,
      visibility: originalGridRoot.visibility,
      layoutItem: originalGridRoot.layoutItem,
      responsive: originalGridRoot.responsive,
      type: "Grid",
      columns: 2,
      gap: 16,
      padding: { top: 24, right: 24, bottom: 24, left: 24 },
      columnOverrides: [],
      children: gridChildren,
    },
  };
  assert.equal(parseRendererDocument(gridDocument).id, gridDocument.id);

  const formDocument = legacyDocument();
  const formRoot = formDocument.pages[1]?.root;
  assert.equal(formRoot?.type, "Stack");
  const form = formRoot?.type === "Stack" ? formRoot.children[0] : undefined;
  assert.equal(form?.type, "Form");
  if (form?.type !== "Form") throw new Error("expected nested Form");
  const positionedFormChild = form.children[0];
  const flowFormChild = form.children[1];
  assert.ok(positionedFormChild && flowFormChild);
  positionedFormChild.layoutItem = {
    ...positionedFormChild.layoutItem,
    position: { x: "20", y: "32" },
  };
  assert.equal(parseRendererDocument(formDocument).id, formDocument.id);

  for (const [document, flowChild] of [
    [stackDocument, flowStackChild],
    [gridDocument, flowGridChild],
    [formDocument, flowFormChild],
  ] as const) {
    assert.equal(Object.hasOwn(flowChild.layoutItem, "position"), false);
    const parsedRoot = parseRendererDocument(document).pages[0]?.root;
    assert.ok(parsedRoot);
  }

  const positionedPageRoot = legacyDocument();
  const pageRoot = positionedPageRoot.pages[0]?.root;
  assert.ok(pageRoot);
  pageRoot.layoutItem.position = { x: "1", y: "2" };
  assert.throws(
    () => parseRendererDocument(positionedPageRoot),
    /position is forbidden on a document or component root/,
  );

  const positionedComponentRoot = legacyDocument();
  const componentRoot = structuredClone(positionedComponentRoot.pages[0]?.root);
  assert.ok(componentRoot);
  componentRoot.layoutItem.position = { x: "3", y: "4" };
  positionedComponentRoot.componentDefinitions = [
    {
      id: "00000000-0000-4000-8000-000000000190",
      key: "positioned-root",
      root: componentRoot,
    },
  ];
  assert.throws(
    () => parseRendererDocument(positionedComponentRoot),
    /position is forbidden on a document or component root/,
  );
});

test("published layout containers establish positioning contexts without changing stacking order", () => {
  const document = legacyDocument();
  const stack = document.pages[0]?.root;
  assert.equal(stack?.type, "Stack");
  if (stack?.type !== "Stack") throw new Error("expected Stack root");
  const firstStackChild = stack.children[0];
  const secondStackChild = stack.children[1];
  assert.ok(firstStackChild && secondStackChild);
  firstStackChild.layoutItem = {
    ...firstStackChild.layoutItem,
    position: { x: "12.5", y: "24" },
  };
  secondStackChild.layoutItem = {
    ...secondStackChild.layoutItem,
    position: { x: "48", y: "64.25" },
  };

  const formRoot = document.pages[1]?.root;
  const form = formRoot?.type === "Stack" ? formRoot.children[0] : undefined;
  assert.equal(form?.type, "Form");
  if (form?.type !== "Form") throw new Error("expected nested Form");
  const formChild = form.children[0];
  assert.ok(formChild);
  formChild.layoutItem = { ...formChild.layoutItem, position: { x: "8", y: "16" } };

  const gridPage = document.pages[2];
  assert.ok(gridPage);
  const originalGridRoot = gridPage.root;
  assert.equal(originalGridRoot?.type, "Stack");
  if (originalGridRoot?.type !== "Stack") throw new Error("expected Stack root");
  const gridChild = originalGridRoot.children[0];
  assert.ok(gridChild);
  gridChild.layoutItem = { ...gridChild.layoutItem, position: { x: "6", y: "18" } };
  document.pages[2] = {
    ...gridPage,
    root: {
      id: originalGridRoot.id,
      name: originalGridRoot.name,
      visibility: originalGridRoot.visibility,
      layoutItem: originalGridRoot.layoutItem,
      responsive: originalGridRoot.responsive,
      type: "Grid",
      columns: 2,
      gap: 12,
      padding: { top: 24, right: 24, bottom: 24, left: 24 },
      columnOverrides: [],
      children: originalGridRoot.children,
    },
  };

  const parsed = parseRendererDocument(document);
  const rendered = renderPrototypeDocument(parsed, "{}", "document-hash", "void 0;");
  const html = rendered.files.find((file) => file.relativePath === "index.html")?.content ?? "";
  const css = rendered.files.find((file) => file.relativePath === "styles.css")?.content ?? "";

  for (const containerId of [stack.id, form.id, originalGridRoot.id]) {
    assert.match(css, new RegExp(`data-prototype-node-id="${containerId}"[^}]*position:relative`));
  }
  for (const [childId, x, y] of [
    [firstStackChild.id, "12\\.5", "24"],
    [secondStackChild.id, "48", "64\\.25"],
    [formChild.id, "8", "16"],
    [gridChild.id, "6", "18"],
  ]) {
    assert.match(
      css,
      new RegExp(
        `data-prototype-node-id="${childId}"[^}]*position:absolute[^}]*left:${x}px[^}]*top:${y}px`,
      ),
    );
    assert.doesNotMatch(css, new RegExp(`data-prototype-node-id="${childId}"[^}]*z-index:`));
  }
  assert.ok(
    html.indexOf(`data-prototype-node-id="${firstStackChild.id}"`) <
      html.indexOf(`data-prototype-node-id="${secondStackChild.id}"`),
  );
});

test("palette and move batches encode supported target placement", () => {
  const document = freeformDocument();
  const freeform = document.pages[0]?.root;
  assert.equal(freeform?.type, "Freeform");
  if (freeform?.type !== "Freeform") throw new Error("expected Freeform root");
  const normalParent = freeform.children[0];
  assert.ok(normalParent && isStructuredPrototypeContainerNode(normalParent));
  const text = createPaletteNode("Text", "new-text", null, labels);

  const insert = insertPaletteNodeBatch(freeform, 0, text, { x: "12", y: "34" });
  const insertCommand = insert.commands[0];
  assert.equal(insertCommand?.kind, "insertNode");
  if (insertCommand?.kind !== "insertNode") throw new Error("expected insert command");
  assert.deepEqual(insertCommand.node.layoutItem.position, { x: "12", y: "34" });
  assert.throws(() => insertPaletteNodeBatch(freeform, 0, text), /position is required/);
  const positionedInsert = insertPaletteNodeBatch(normalParent, 0, text, { x: "1", y: "2" });
  const positionedInsertCommand = positionedInsert.commands[0];
  assert.equal(positionedInsertCommand?.kind, "insertNode");
  assert.deepEqual(
    positionedInsertCommand?.kind === "insertNode"
      ? positionedInsertCommand.node.layoutItem.position
      : undefined,
    { x: "1", y: "2" },
  );

  const freeformMove = moveNodeBatch("node", freeform, 1, { x: "56", y: "78" });
  assert.deepEqual(freeformMove.commands[0], {
    kind: "moveNode",
    node: { kind: "existing", nodeId: "node" },
    targetParent: { kind: "existing", nodeId: freeform.id },
    targetSlot: null,
    targetIndex: 1,
    targetPosition: { x: "56", y: "78" },
  });
  assert.equal(
    Object.hasOwn(moveNodeBatch("node", normalParent, 0).commands[0] ?? {}, "targetPosition"),
    false,
  );
  assert.deepEqual(moveNodeBatch("node", normalParent, 0, null).commands[0], {
    kind: "moveNode",
    node: { kind: "existing", nodeId: "node" },
    targetParent: { kind: "existing", nodeId: normalParent.id },
    targetSlot: null,
    targetIndex: 0,
    targetPosition: null,
  });
  assert.deepEqual(moveNodeBatch("node", normalParent, 0, { x: "1", y: "2" }).commands[0], {
    kind: "moveNode",
    node: { kind: "existing", nodeId: "node" },
    targetParent: { kind: "existing", nodeId: normalParent.id },
    targetSlot: null,
    targetIndex: 0,
    targetPosition: { x: "1", y: "2" },
  });
  assert.throws(() => moveNodeBatch("node", freeform, 0), /target position is required/);
  assert.throws(() => moveNodeBatch("node", freeform, 0, null), /target position is required/);
});

test("drag projections require Freeform coordinates and explicitly clear them for flow layout", () => {
  const document = freeformDocument();
  const freeform = document.pages[0]?.root;
  assert.equal(freeform?.type, "Freeform");
  if (freeform?.type !== "Freeform") throw new Error("expected Freeform root");
  const normalParent = freeform.children[0];
  assert.ok(normalParent && isStructuredPrototypeContainerNode(normalParent));
  const transient = materializeStructuredPrototypePalettePreviewNode(
    createPaletteNode("Text", "transient-text", null, labels),
    77,
  );
  const pageId = document.pages[0]?.id;
  assert.ok(pageId);

  const inserted = projectStructuredPrototypeNodeInsert(
    document,
    pageId,
    freeform.id,
    1,
    transient,
    { x: "100", y: "120" },
  );
  assert.ok(inserted);
  assert.deepEqual(
    findStructuredPrototypeNode(inserted.pages[0]?.root ?? freeform, transient.id)?.layoutItem
      .position,
    { x: "100", y: "120" },
  );
  const unchangedFreeformTarget = {
    kind: "slot",
    intent: "before",
    ownerNodeId: transient.id,
    depth: 1,
    ancestorNodeIds: [freeform.id],
    parentId: freeform.id,
    index: 1,
  } as const;
  assert.equal(
    projectStructuredPrototypeNodeMoveToDropTarget(
      inserted,
      pageId,
      transient.id,
      unchangedFreeformTarget,
    ),
    null,
  );
  assert.equal(
    projectStructuredPrototypeNodeMoveToDropTarget(
      inserted,
      pageId,
      transient.id,
      unchangedFreeformTarget,
      null,
    ),
    null,
  );
  const unchangedFreeform = projectStructuredPrototypeNodeMoveToDropTarget(
    inserted,
    pageId,
    transient.id,
    unchangedFreeformTarget,
    { x: "100", y: "120" },
  );
  assert.ok(unchangedFreeform);
  assert.equal(unchangedFreeform.document, inserted);
  assert.equal(
    projectStructuredPrototypeNodeInsert(document, pageId, freeform.id, 1, transient),
    null,
  );
  assert.equal(
    projectStructuredPrototypeNodeInsert(document, pageId, freeform.id, 1, transient, null),
    null,
  );

  const movedToStack = projectStructuredPrototypeNodeMoveToDropTarget(
    inserted,
    pageId,
    transient.id,
    {
      kind: "container",
      intent: "inside",
      ownerNodeId: normalParent.id,
      depth: 1,
      ancestorNodeIds: [freeform.id],
      parentId: normalParent.id,
      index: 0,
    },
    null,
  );
  assert.ok(movedToStack);
  assert.deepEqual(movedToStack.location, {
    parentId: normalParent.id,
    index: 0,
    position: null,
  });
  assert.equal(
    Object.hasOwn(
      findStructuredPrototypeNode(movedToStack.document.pages[0]?.root ?? freeform, transient.id)
        ?.layoutItem ?? {},
      "position",
    ),
    false,
  );
  assert.equal(
    projectStructuredPrototypeNodeMove(movedToStack.document, pageId, transient.id, freeform.id, 1),
    null,
  );
  assert.equal(
    projectStructuredPrototypeNodeMove(
      movedToStack.document,
      pageId,
      transient.id,
      freeform.id,
      1,
      null,
    ),
    null,
  );

  const movedBack = projectStructuredPrototypeNodeMove(
    movedToStack.document,
    pageId,
    transient.id,
    freeform.id,
    1,
    { x: "140", y: "160" },
  );
  assert.ok(movedBack);
  assert.deepEqual(
    findStructuredPrototypeNode(movedBack.pages[0]?.root ?? freeform, transient.id)?.layoutItem
      .position,
    { x: "140", y: "160" },
  );
});

test("Stack Grid and Form drag projections accept explicit child positions", () => {
  let document = legacyDocument();
  const stackPage = document.pages[0];
  const formPage = document.pages[1];
  assert.ok(stackPage && formPage);
  const stack = stackPage.root;
  const form = formPage.root.type === "Stack" ? formPage.root.children[0] : undefined;
  assert.equal(stack.type, "Stack");
  assert.equal(form?.type, "Form");
  if (stack.type !== "Stack" || form?.type !== "Form") {
    throw new Error("expected Stack and Form projection targets");
  }

  const grid = materializeStructuredPrototypePalettePreviewNode(
    createPaletteNode("Grid", "position-target-grid", null, labels),
    78,
  );
  const withGrid = projectStructuredPrototypeNodeInsert(
    document,
    stackPage.id,
    stack.id,
    stack.children.length,
    grid,
  );
  assert.ok(withGrid);
  document = withGrid;

  const targets = [
    { pageId: stackPage.id, parentId: stack.id, parentType: "Stack" },
    { pageId: stackPage.id, parentId: grid.id, parentType: "Grid" },
    { pageId: formPage.id, parentId: form.id, parentType: "Form" },
  ] as const;
  for (const [index, target] of targets.entries()) {
    const node = materializeStructuredPrototypePalettePreviewNode(
      createPaletteNode("Text", `positioned-${target.parentType.toLowerCase()}`, null, labels),
      79 + index,
    );
    const position = { x: String(12 + index), y: String(24 + index) };
    const projected = projectStructuredPrototypeNodeInsert(
      document,
      target.pageId,
      target.parentId,
      0,
      node,
      position,
    );
    assert.ok(projected);
    assert.deepEqual(
      findStructuredPrototypeNode(
        projected.pages.find((page) => page.id === target.pageId)?.root ?? stack,
        node.id,
      )?.layoutItem.position,
      position,
    );
    document = projected;
  }
});

test("ordinary-container reprojection preserves flow and positioned placement", () => {
  const document = legacyDocument();
  const page = document.pages[0];
  assert.ok(page);
  const stack = page.root;
  assert.equal(stack.type, "Stack");
  if (stack.type !== "Stack") throw new Error("expected Stack root");
  const flowChild = stack.children[0];
  assert.ok(flowChild);
  const grid = materializeStructuredPrototypePalettePreviewNode(
    createPaletteNode("Grid", "reprojection-grid", null, labels),
    90,
  );
  const withGrid = projectStructuredPrototypeNodeInsert(
    document,
    page.id,
    stack.id,
    stack.children.length,
    grid,
  );
  assert.ok(withGrid);

  const flowMovedToGrid = projectStructuredPrototypeNodeMove(
    withGrid,
    page.id,
    flowChild.id,
    grid.id,
    0,
  );
  assert.ok(flowMovedToGrid);
  assert.equal(
    Object.hasOwn(
      findStructuredPrototypeNode(flowMovedToGrid.pages[0]?.root ?? stack, flowChild.id)
        ?.layoutItem ?? {},
      "position",
    ),
    false,
  );

  const positionedChild = materializeStructuredPrototypePalettePreviewNode(
    createPaletteNode("Text", "reproject-positioned", null, labels),
    91,
  );
  const position = { x: "40", y: "56" };
  const withPositionedChild = projectStructuredPrototypeNodeInsert(
    flowMovedToGrid,
    page.id,
    grid.id,
    1,
    positionedChild,
    position,
  );
  assert.ok(withPositionedChild);
  const reordered = projectStructuredPrototypeNodeMoveToDropTarget(
    withPositionedChild,
    page.id,
    positionedChild.id,
    {
      kind: "slot",
      intent: "before",
      ownerNodeId: flowChild.id,
      depth: 2,
      ancestorNodeIds: [stack.id, grid.id],
      parentId: grid.id,
      index: 0,
    },
  );
  assert.ok(reordered);
  assert.deepEqual(reordered.location, { parentId: grid.id, index: 0, position });
  assert.deepEqual(
    findStructuredPrototypeNode(reordered.document.pages[0]?.root ?? stack, positionedChild.id)
      ?.layoutItem.position,
    position,
  );

  const repeated = projectStructuredPrototypeNodeMoveToDropTarget(
    reordered.document,
    page.id,
    positionedChild.id,
    {
      kind: "slot",
      intent: "before",
      ownerNodeId: flowChild.id,
      depth: 2,
      ancestorNodeIds: [stack.id, grid.id],
      parentId: grid.id,
      index: 0,
    },
  );
  assert.ok(repeated);
  assert.equal(repeated.document, reordered.document);
  assert.deepEqual(repeated.location, { parentId: grid.id, index: 0, position });
});
