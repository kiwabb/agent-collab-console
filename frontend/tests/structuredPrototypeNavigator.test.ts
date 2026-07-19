import assert from "node:assert/strict";
import test from "node:test";

import { structuredPrototypeCollisionDetection } from "../src/features/prototype/structured/structuredPrototypeDrag";
import {
  beginStructuredPrototypeInteraction,
  createStructuredPrototypeIdleInteraction,
  resolveStructuredPrototypeInteractionCapabilities,
} from "../src/features/prototype/structured/structuredPrototypeInteraction";
import {
  resolveStructuredPrototypeCreatedPageId,
  resolveStructuredPrototypeNearestSurvivingPageId,
} from "../src/features/prototype/structured/structuredPrototypePageActions";
import type { StructuredPrototypeCommandApplicationResult } from "../src/features/prototype/structured/useStructuredPrototypeStudio";
import type {
  StructuredPrototypeDocument,
  StructuredPrototypeDraft,
} from "../src/features/prototype/structured/types";
import { createProcurementPrototypeDocument } from "./fixtures/procurementDocumentFixture";
import { readCompactSource, readSource } from "./sourceTestUtils";

function applicationWithPages(
  pages: StructuredPrototypeDocument["pages"],
  allocatedEntityIds: StructuredPrototypeCommandApplicationResult["allocatedEntityIds"],
): StructuredPrototypeCommandApplicationResult {
  const document: StructuredPrototypeDocument = {
    ...createProcurementPrototypeDocument(),
    id: "11111111-1111-1111-1111-111111111111",
    pages,
  };
  const draft: StructuredPrototypeDraft = {
    contractVersion: 1,
    operationId: "22222222-2222-2222-2222-222222222222",
    correlationId: "33333333-3333-3333-3333-333333333333",
    documentId: document.id,
    draftId: "44444444-4444-4444-4444-444444444444",
    headSequenceNo: 2,
    documentHash: "sha256:navigator-test",
    canUndo: true,
    canRedo: false,
    document,
  };
  return { draft, allocatedEntityIds, runtimeReady: true };
}

function collisionRect(left: number, top: number, width: number, height: number) {
  return {
    left,
    top,
    width,
    height,
    right: left + width,
    bottom: top + height,
  };
}

function collisionArguments(
  activeData: Record<string, unknown>,
  targets: Array<{
    id: string;
    data: Record<string, unknown>;
    rect: ReturnType<typeof collisionRect>;
  }>,
): Parameters<typeof structuredPrototypeCollisionDetection>[0] {
  const activeRect = collisionRect(8, 8, 20, 20);
  return {
    active: {
      id: "active",
      data: { current: activeData },
      rect: { current: { initial: activeRect, translated: activeRect } },
    },
    collisionRect: activeRect,
    droppableRects: new Map(targets.map((target) => [target.id, target.rect])),
    droppableContainers: targets.map((target) => ({
      id: target.id,
      key: target.id,
      data: { current: target.data },
      disabled: false,
      node: { current: null },
      rect: { current: target.rect },
    })),
    pointerCoordinates: { x: 12, y: 12 },
  };
}

test("page creation resolves the direct allocation and recovered identity without title guessing", () => {
  const sourceDocument: StructuredPrototypeDocument = {
    ...createProcurementPrototypeDocument(),
    id: "11111111-1111-1111-1111-111111111111",
  };
  const previousPageIds = sourceDocument.pages.map((page) => page.id);
  const sourcePage = sourceDocument.pages[0];
  assert.ok(sourcePage);
  const createdPage = {
    ...structuredClone(sourcePage),
    id: "55555555-5555-5555-5555-555555555555",
    title: sourcePage.title,
  };
  const allocationKey = `page-add-${sourcePage.id.replaceAll("-", "")}`;
  const pages = [...sourceDocument.pages, createdPage];

  assert.equal(
    resolveStructuredPrototypeCreatedPageId(
      previousPageIds,
      allocationKey,
      applicationWithPages(pages, [
        { newNodeKey: `${allocationKey}:root`, entityId: createdPage.root.id },
        { newNodeKey: allocationKey, entityId: createdPage.id },
      ]),
    ),
    createdPage.id,
  );
  assert.equal(
    resolveStructuredPrototypeCreatedPageId(
      previousPageIds,
      allocationKey,
      applicationWithPages(pages, null),
    ),
    createdPage.id,
  );
  assert.equal(
    resolveStructuredPrototypeCreatedPageId(
      previousPageIds,
      allocationKey,
      applicationWithPages(pages, [{ newNodeKey: "wrong-key", entityId: createdPage.id }]),
    ),
    null,
  );
  assert.equal(
    resolveStructuredPrototypeCreatedPageId(
      previousPageIds,
      allocationKey,
      applicationWithPages(
        [...pages, { ...structuredClone(createdPage), id: "66666666-6666-6666-6666-666666666666" }],
        null,
      ),
    ),
    null,
  );
});

test("page deletion chooses the nearest survivor deterministically", () => {
  const pages = [{ id: "a" }, { id: "b" }, { id: "c" }, { id: "d" }];
  assert.equal(resolveStructuredPrototypeNearestSurvivingPageId(pages, "b"), "c");
  assert.equal(resolveStructuredPrototypeNearestSurvivingPageId(pages, "d"), "c");
  assert.equal(resolveStructuredPrototypeNearestSurvivingPageId(pages, "missing"), null);
  assert.equal(resolveStructuredPrototypeNearestSurvivingPageId([{ id: "only" }], "only"), null);
});

test("layer collision detection excludes page and canvas droppables", () => {
  const sharedRect = collisionRect(0, 0, 40, 40);
  const collisions = structuredPrototypeCollisionDetection(
    collisionArguments(
      {
        kind: "prototype-layer-drag",
        nodeId: "child",
        parentId: "root",
        index: 0,
        depth: 1,
        ancestorNodeIds: ["root"],
      },
      [
        {
          id: "page-target",
          data: { kind: "page", pageId: "page", index: 0 },
          rect: sharedRect,
        },
        {
          id: "canvas-target",
          data: {
            kind: "container",
            intent: "inside",
            ownerNodeId: "root",
            depth: 0,
            ancestorNodeIds: [],
            parentId: "root",
            index: 1,
          },
          rect: sharedRect,
        },
        {
          id: "layer-target",
          data: {
            kind: "prototype-layer-drop",
            nodeId: "sibling",
            intent: "before",
            parentId: "root",
            index: 1,
            depth: 1,
            ancestorNodeIds: ["root"],
          },
          rect: sharedRect,
        },
      ],
    ),
  );
  assert.deepEqual(
    collisions.map((collision) => collision.id),
    ["layer-target"],
  );
});

test("layer drag uses the shared move lock while keeping the active gesture operable", () => {
  const interaction = beginStructuredPrototypeInteraction(
    createStructuredPrototypeIdleInteraction(),
    {
      kind: "move",
      source: { kind: "layer", nodeId: "layer-node" },
      baseDocumentHash: "sha256:layer-drag",
    },
    7,
  );
  assert.deepEqual(resolveStructuredPrototypeInteractionCapabilities(interaction, false), {
    busy: true,
    documentControlsDisabled: true,
    moveDisabled: false,
    resizeDisabled: true,
  });
});

test("Studio navigator source keeps durable callbacks, structural sections, and recovery identity", () => {
  const studio = readCompactSource(
    "features/prototype/structured/StructuredPrototypeStudioPage.tsx",
  );
  const rail = readCompactSource("features/prototype/structured/StructuredPrototypePageRail.tsx");
  const drag = readCompactSource("features/prototype/structured/structuredPrototypeDrag.ts");
  const controller = readCompactSource(
    "features/prototype/structured/useStructuredPrototypeStudio.ts",
  );
  const layerTree = readCompactSource(
    "features/prototype/structured/StructuredPrototypeLayerTree.tsx",
  );

  assert.match(studio, /<StructuredPrototypeLayerTree/);
  assert.match(studio, /selectedNodeId={activeNodeSelection\.primaryNodeId}/);
  assert.match(studio, /prototype\.structured\.pages/);
  assert.match(studio, /prototype\.structured\.layers/);
  assert.match(studio, /prototype\.structured\.components/);
  assert.match(studio, /updateNodeNameBatch/);
  assert.match(studio, /update: \{kind: "visibility", visibility\}/);
  assert.match(studio, /moveNodeBatch\(move\.nodeId/);
  assert.match(studio, /source: \{kind: "layer", nodeId: layer\.nodeId\}/);
  assert.match(studio, /endInteraction\(activeInteraction\.sessionId\)/);
  assert.match(studio, /addPageBatch/);
  assert.match(studio, /duplicatePageBatch/);
  assert.match(studio, /renamePageBatch/);
  assert.match(studio, /deletePageBatch/);
  assert.match(studio, /structuredPrototypePageAllocationKey/);
  assert.match(studio, /resolveStructuredPrototypeCreatedPageId/);
  assert.match(studio, /resolveStructuredPrototypeNearestSurvivingPageId/);
  assert.doesNotMatch(studio, /pages\.find\([^)]*title/);

  assert.match(rail, /event\.key === "Enter"/);
  assert.match(rail, /event\.key === "Escape"/);
  assert.match(rail, /const renamed = await onRename/);
  assert.match(rail, /<Plus/);
  assert.match(rail, /<Copy/);
  assert.match(rail, /<Pencil/);
  assert.match(rail, /<Trash2/);
  assert.match(rail, /<ConfirmDialog/);
  assert.match(rail, /deleteDisabled={pages\.length === 1}/);

  assert.match(drag, /readStructuredPrototypeLayerDragData/);
  assert.match(drag, /readStructuredPrototypeLayerDropData/);
  assert.match(
    drag,
    /const layerDrag = readStructuredPrototypeLayerDragData.*droppableContainers = args\.droppableContainers\.filter/s,
  );
  assert.match(controller, /applyCommandsWithResult/);
  assert.match(controller, /allocatedEntityIds: applied\.allocatedEntityIds/);
  assert.match(controller, /allocatedEntityIds: null/);
  assert.match(controller, /\?\.runtimeReady === true/);
  assert.match(layerTree, /structuredPrototypeLayerTreeModel/);
  assert.match(layerTree, /role="treeitem"/);
  assert.match(layerTree, /tabIndex={focused \? 0 : -1}/);
  assert.match(layerTree, /resolveStructuredPrototypeLayerTreeKeyboardAction/);
  assert.match(layerTree, /data-prototype-layer-error/);
  assert.match(studio, /error={interactionError}/);
  assert.match(
    controller,
    /resolveStructuredPrototypeRecoveredOperationFailure\(error, recoveryError\)/,
  );
});

test("navigator copy has zh-CN and en-US parity", () => {
  const en = readSource("lib/i18n/en-US.ts");
  const zh = readSource("lib/i18n/zh-CN.ts");
  const keys = [
    "prototype.structured.navigator",
    "prototype.structured.pages.add",
    "prototype.structured.pages.duplicate",
    "prototype.structured.pages.renameFailed",
    "prototype.structured.pages.deleteDescription",
    "prototype.structured.layers.tree",
    "prototype.structured.layers.renameFailed",
    "prototype.structured.layers.visibilityFailed",
    "prototype.structured.layers.moveFailed",
  ];
  for (const key of keys) {
    assert.equal(en.includes(`"${key}"`), true, `missing en-US key ${key}`);
    assert.equal(zh.includes(`"${key}"`), true, `missing zh-CN key ${key}`);
  }
});
