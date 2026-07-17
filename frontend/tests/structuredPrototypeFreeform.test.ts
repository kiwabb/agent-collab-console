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
};

function legacyDocument(): StructuredPrototypeDocument {
  return {
    ...createProcurementPrototypeDocument(),
    id: "00000000-0000-4000-8000-000000000100",
  };
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
    /position is only valid inside a Freeform container/,
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

test("palette and move batches encode positions only for Freeform targets", () => {
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
  assert.throws(
    () => insertPaletteNodeBatch(normalParent, 0, text, { x: "1", y: "2" }),
    /only valid for a direct child/,
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
  assert.throws(() => moveNodeBatch("node", freeform, 0), /target position is required/);
  assert.throws(
    () => moveNodeBatch("node", normalParent, 0, { x: "1", y: "2" }),
    /only valid for a Freeform/,
  );
});

test("drag projections persist Freeform coordinates and clear them in normal layout", () => {
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
  assert.equal(
    projectStructuredPrototypeNodeInsert(document, pageId, freeform.id, 1, transient),
    null,
  );

  const movedToStack = projectStructuredPrototypeNodeMove(
    inserted,
    pageId,
    transient.id,
    normalParent.id,
    0,
  );
  assert.ok(movedToStack);
  assert.equal(
    Object.hasOwn(
      findStructuredPrototypeNode(movedToStack.pages[0]?.root ?? freeform, transient.id)
        ?.layoutItem ?? {},
      "position",
    ),
    false,
  );

  const movedBack = projectStructuredPrototypeNodeMove(
    movedToStack,
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
