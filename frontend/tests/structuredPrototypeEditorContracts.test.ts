import assert from "node:assert/strict";
import test from "node:test";

import {
  renderPrototypeDocument,
  resolvePrototypeShellTheme,
} from "../src/features/prototype/structured/prototypeRendererCore";
import { parseRendererDocument } from "../src/features/prototype/structured/rendererDocumentCodec";
import {
  createProcurementPrototypeDocument,
  STRUCTURED_PROCUREMENT_IDS,
} from "./fixtures/procurementDocumentFixture";
import {
  findStructuredPrototypeNodeLocation,
  isStructuredPrototypePalettePreviewNodeId,
  materializeStructuredPrototypePalettePreviewNode,
  projectStructuredPrototypeNodeInsert,
  projectStructuredPrototypeNodeMove,
  projectStructuredPrototypeNodeMoveToDropTarget,
  projectStructuredPrototypePageReorder,
  projectStructuredPrototypePageReorderByTargetPageId,
  readStructuredPrototypeDropTarget,
  readStructuredPrototypeNodeDragData,
  readStructuredPrototypePageDragData,
  readStructuredPrototypePaletteDragData,
  resolveStructuredPrototypeActiveLayoutNodeId,
  resolveStructuredPrototypeMoveTargetIndex,
  resolveStructuredPrototypeSelectionChromeState,
  structuredPrototypeCollisionDetection,
  structuredPrototypeNodeDragMatchesSelection,
} from "../src/features/prototype/structured/structuredPrototypeDrag";
import { createPaletteNode } from "../src/features/prototype/structured/structuredPrototypeCommands";
import { resolveStructuredPrototypeMeasuredDropAreas } from "../src/features/prototype/structured/structuredPrototypeDropAreas";
import { resolveStructuredPrototypePageDropIndicator } from "../src/features/prototype/structured/StructuredPrototypePageRail";
import {
  resolveStructuredPrototypeResizeSize,
  structuredPrototypeResizePassedActivationThreshold,
} from "../src/features/prototype/structured/StructuredPrototypeCanvas";
import { resolveStructuredPrototypeSelectionControlsGeometry } from "../src/features/prototype/structured/structuredPrototypeSelectionControls";
import {
  advanceStructuredPrototypeInteraction,
  beginStructuredPrototypeInteraction,
  createStructuredPrototypeIdleInteraction,
  endStructuredPrototypeInteraction,
  resolveStructuredPrototypeInteractionCapabilities,
} from "../src/features/prototype/structured/structuredPrototypeInteraction";
import type { StructuredPrototypeDocument } from "../src/features/prototype/structured/types";
import { readCompactSource } from "./sourceTestUtils";

function rendererDocument(): StructuredPrototypeDocument {
  return structuredClone({
    ...createProcurementPrototypeDocument(),
    id: "11111111-1111-1111-1111-111111111111",
  });
}

function firstPage(document: StructuredPrototypeDocument) {
  const page = document.pages[0];
  if (page === undefined) throw new Error("fixture has no prototype page");
  return page;
}

function setShellColors(
  document: StructuredPrototypeDocument,
  values: { accent: string; navigation: string; content: string; surface: string },
): void {
  const shell = document.settings.shell;
  const byKey = new Map(document.tokens.colors.map((token) => [token.key, token]));
  const assignments = [
    [shell.accentColorTokenKey, values.accent],
    [shell.navigationBackgroundColorTokenKey, values.navigation],
    [shell.contentBackgroundColorTokenKey, values.content],
    [shell.surfaceColorTokenKey, values.surface],
  ] as const;
  for (const [key, value] of assignments) {
    const token = byKey.get(key);
    if (token === undefined) throw new Error(`fixture is missing color token ${key}`);
    token.value = value;
  }
}

function renderStyles(document: StructuredPrototypeDocument): string {
  return (
    renderPrototypeDocument(document, "{}", "sha256:test", "void 0;").files.find(
      (file) => file.relativePath === "styles.css",
    )?.content ?? ""
  );
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

function structuredCollisionArguments(
  activeData: Record<string, unknown>,
  pointerCoordinates: { x: number; y: number } | null,
  targets: Array<{
    id: string;
    data: Record<string, unknown>;
    rect: ReturnType<typeof collisionRect>;
  }>,
): Parameters<typeof structuredPrototypeCollisionDetection>[0] {
  const activeRect = collisionRect(90, 90, 20, 20);
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
    pointerCoordinates,
  };
}

test("page rail drop indicator follows the page move direction", () => {
  assert.equal(resolveStructuredPrototypePageDropIndicator(null, 1), null);
  assert.equal(resolveStructuredPrototypePageDropIndicator(1, 1), null);
  assert.equal(resolveStructuredPrototypePageDropIndicator(0, 2), "bottom");
  assert.equal(resolveStructuredPrototypePageDropIndicator(2, 0), "top");
});

test("resize projection uses canvas scale and the exact final pointer position", () => {
  assert.deepEqual(
    resolveStructuredPrototypeResizeSize({
      startWidth: 100,
      startHeight: 80,
      startClientX: 10,
      startClientY: 20,
      clientX: 20,
      clientY: 25,
      previewScale: 0.5,
      direction: "southeast",
      lockAspectRatio: false,
    }),
    { width: 120, height: 90 },
  );
  assert.deepEqual(
    resolveStructuredPrototypeResizeSize({
      startWidth: 100,
      startHeight: 80,
      startClientX: 10,
      startClientY: 20,
      clientX: 20,
      clientY: 25,
      previewScale: 2,
      direction: "southeast",
      lockAspectRatio: false,
    }),
    { width: 105, height: 83 },
  );
  assert.deepEqual(
    resolveStructuredPrototypeResizeSize({
      startWidth: 100,
      startHeight: 80,
      startClientX: 10,
      startClientY: 20,
      clientX: 20,
      clientY: 25,
      previewScale: 0.5,
      direction: "east",
      lockAspectRatio: false,
    }),
    { width: 120, height: 80 },
  );
  assert.deepEqual(
    resolveStructuredPrototypeResizeSize({
      startWidth: 100,
      startHeight: 80,
      startClientX: 10,
      startClientY: 20,
      clientX: 20,
      clientY: 25,
      previewScale: 0.5,
      direction: "south",
      lockAspectRatio: false,
    }),
    { width: 100, height: 90 },
  );
  assert.deepEqual(
    resolveStructuredPrototypeResizeSize({
      startWidth: 100,
      startHeight: 80,
      startClientX: 10,
      startClientY: 20,
      clientX: 20,
      clientY: 25,
      previewScale: 0.5,
      direction: "east",
      lockAspectRatio: true,
    }),
    { width: 120, height: 96 },
  );
  assert.deepEqual(
    resolveStructuredPrototypeResizeSize({
      startWidth: 100,
      startHeight: 80,
      startClientX: 10,
      startClientY: 20,
      clientX: 20,
      clientY: 25,
      previewScale: 0.5,
      direction: "south",
      lockAspectRatio: true,
    }),
    { width: 113, height: 90 },
  );
});

test("selection controls geometry uses canvas-local coordinates and inverse handle scale", () => {
  assert.deepEqual(
    resolveStructuredPrototypeSelectionControlsGeometry(
      collisionRect(100, 50, 900, 600),
      collisionRect(250, 125, 300, 150),
      1.5,
    ),
    {
      bounds: { top: 50, left: 100, width: 200, height: 100 },
      handleScale: 2 / 3,
    },
  );
});

test("resize waits for four client pixels before activating", () => {
  assert.equal(structuredPrototypeResizePassedActivationThreshold(10, 20, 13, 22), false);
  assert.equal(structuredPrototypeResizePassedActivationThreshold(10, 20, 14, 20), true);
});

test("prototype interactions grant one session and ignore stale completion", () => {
  const idle = createStructuredPrototypeIdleInteraction();
  const moving = beginStructuredPrototypeInteraction(
    idle,
    {
      kind: "move",
      source: { kind: "node", nodeId: "metric-a" },
      baseDocumentHash: "sha256:base",
    },
    7,
  );
  assert.equal(moving.kind, "move");
  assert.equal(
    beginStructuredPrototypeInteraction(moving, { kind: "pan", pointerId: 4 }, 8),
    moving,
  );
  assert.equal(endStructuredPrototypeInteraction(moving, 6), moving);

  const committing = advanceStructuredPrototypeInteraction(moving, 7, "committing");
  assert.deepEqual(committing, {
    kind: "move",
    sessionId: 7,
    source: { kind: "node", nodeId: "metric-a" },
    phase: "committing",
    baseDocumentHash: "sha256:base",
  });
  assert.equal(advanceStructuredPrototypeInteraction(committing, 7, "committing"), committing);
  assert.deepEqual(endStructuredPrototypeInteraction(committing, 7), { kind: "idle" });
});

test("prototype interaction capabilities keep only the active transform operable", () => {
  const idle = createStructuredPrototypeIdleInteraction();
  assert.deepEqual(resolveStructuredPrototypeInteractionCapabilities(idle, false), {
    busy: false,
    documentControlsDisabled: false,
    moveDisabled: false,
    resizeDisabled: false,
  });

  const resize = beginStructuredPrototypeInteraction(
    idle,
    {
      kind: "resize",
      nodeId: "metric-a",
      pointerId: 9,
      baseDocumentHash: "sha256:base",
      previewScale: 0.5,
    },
    10,
  );
  assert.deepEqual(resolveStructuredPrototypeInteractionCapabilities(resize, false), {
    busy: true,
    documentControlsDisabled: true,
    moveDisabled: true,
    resizeDisabled: false,
  });
  const freeformMove = beginStructuredPrototypeInteraction(
    idle,
    {
      kind: "freeformMove",
      nodeId: "metric-a",
      freeformId: "freeform-a",
      pointerId: 12,
      baseDocumentHash: "sha256:base",
      previewScale: 0.5,
      gridSnappingEnabled: true,
      gridIds: ["grid-a"],
    },
    12,
  );
  assert.deepEqual(resolveStructuredPrototypeInteractionCapabilities(freeformMove, false), {
    busy: true,
    documentControlsDisabled: true,
    moveDisabled: false,
    resizeDisabled: true,
  });
  const freeformPreview = advanceStructuredPrototypeInteraction(freeformMove, 12, "preview");
  const freeformCommitting = advanceStructuredPrototypeInteraction(
    freeformPreview,
    12,
    "committing",
  );
  assert.deepEqual(resolveStructuredPrototypeInteractionCapabilities(freeformCommitting, false), {
    busy: true,
    documentControlsDisabled: true,
    moveDisabled: true,
    resizeDisabled: true,
  });
  const committing = advanceStructuredPrototypeInteraction(resize, 10, "committing");
  assert.deepEqual(resolveStructuredPrototypeInteractionCapabilities(committing, false), {
    busy: true,
    documentControlsDisabled: true,
    moveDisabled: true,
    resizeDisabled: true,
  });
  assert.deepEqual(resolveStructuredPrototypeInteractionCapabilities(idle, true), {
    busy: false,
    documentControlsDisabled: true,
    moveDisabled: true,
    resizeDisabled: true,
  });
  const mutation = beginStructuredPrototypeInteraction(
    idle,
    { kind: "mutation", operation: "aiApply", baseDocumentHash: "sha256:base" },
    11,
  );
  assert.deepEqual(resolveStructuredPrototypeInteractionCapabilities(mutation, false), {
    busy: true,
    documentControlsDisabled: true,
    moveDisabled: true,
    resizeDisabled: true,
  });
});

test("measured prototype drop areas cover Stack gaps with canonical document indexes", () => {
  const areas = resolveStructuredPrototypeMeasuredDropAreas({
    parentRect: collisionRect(0, 0, 300, 300),
    children: [
      { nodeId: "visible-a", index: 0, rect: collisionRect(10, 20, 280, 40) },
      { nodeId: "visible-c", index: 2, rect: collisionRect(10, 100, 280, 60) },
    ],
    childCount: 3,
    activeIndex: null,
    layout: "vertical",
  });

  assert.deepEqual(
    areas.map((area) => ({
      targetIndex: area.targetIndex,
      top: area.rect.top,
      bottom: area.rect.bottom,
      line: area.indicator.position,
    })),
    [
      { targetIndex: 0, top: 0, bottom: 40, line: 20 },
      { targetIndex: 2, top: 40, bottom: 130, line: 100 },
      { targetIndex: 3, top: 130, bottom: 300, line: 160 },
    ],
  );
});

test("measured prototype Grid drop areas follow visual rows without dead gaps", () => {
  const areas = resolveStructuredPrototypeMeasuredDropAreas({
    parentRect: collisionRect(0, 0, 300, 240),
    children: [
      { nodeId: "a", index: 0, rect: collisionRect(0, 0, 100, 60) },
      { nodeId: "b", index: 1, rect: collisionRect(110, 0, 100, 60) },
      { nodeId: "c", index: 2, rect: collisionRect(0, 100, 100, 60) },
      { nodeId: "d", index: 3, rect: collisionRect(110, 100, 100, 60) },
    ],
    childCount: 4,
    activeIndex: null,
    layout: "grid",
  });

  assert.deepEqual(
    areas.map((area) => ({
      key: area.key,
      targetIndex: area.targetIndex,
      left: area.rect.left,
      right: area.rect.right,
      top: area.rect.top,
      bottom: area.rect.bottom,
    })),
    [
      { key: "grid-0-0", targetIndex: 0, left: 0, right: 50, top: 0, bottom: 80 },
      { key: "grid-0-1", targetIndex: 1, left: 50, right: 160, top: 0, bottom: 80 },
      { key: "grid-0-2", targetIndex: 2, left: 160, right: 300, top: 0, bottom: 80 },
      { key: "grid-1-0", targetIndex: 2, left: 0, right: 50, top: 80, bottom: 240 },
      { key: "grid-1-1", targetIndex: 3, left: 50, right: 160, top: 80, bottom: 240 },
      { key: "grid-1-2", targetIndex: 4, left: 160, right: 300, top: 80, bottom: 240 },
    ],
  );
});

test("active prototype slot preserves hidden siblings when the node does not move visually", () => {
  const areas = resolveStructuredPrototypeMeasuredDropAreas({
    parentRect: collisionRect(0, 0, 300, 200),
    children: [{ nodeId: "visible-c", index: 2, rect: collisionRect(0, 100, 300, 40) }],
    childCount: 3,
    activeIndex: 0,
    layout: "vertical",
  });
  assert.deepEqual(
    areas.map((area) => area.targetIndex),
    [1, 3],
  );

  const document = rendererDocument();
  const page = firstPage(document);
  const root = page.root;
  if (root.type !== "Stack") throw new Error("fixture list root is not a Stack");
  const active = root.children[0];
  const visibleC = root.children[1];
  if (active === undefined || visibleC === undefined) {
    throw new Error("fixture list root requires two children");
  }
  const hidden = structuredClone(active);
  hidden.id = "hidden-between-a-and-c";
  hidden.visibility = "hidden";
  root.children = [active, hidden, visibleC];

  const projection = projectStructuredPrototypeNodeMoveToDropTarget(document, page.id, active.id, {
    kind: "slot",
    intent: "before",
    ownerNodeId: root.id,
    depth: 1,
    ancestorNodeIds: [],
    parentId: root.id,
    index: 1,
  });
  assert.ok(projection);
  assert.equal(projection.document, document);
  assert.deepEqual(projection.location, { parentId: root.id, index: 0 });
  assert.deepEqual(
    root.children.map((node) => node.id),
    [active.id, hidden.id, visibleC.id],
  );
});

test("nested prototype drag data preserves the target parent and canonical index", () => {
  const dragged = readStructuredPrototypeNodeDragData({
    kind: "node",
    nodeId: "metric-a",
    parentId: "metrics-grid",
    index: 0,
  });
  const childTarget = readStructuredPrototypeDropTarget({
    kind: "node",
    nodeId: "metric-c",
    ownerNodeId: "metric-c",
    depth: 2,
    ancestorNodeIds: ["page-root", "metrics-grid"],
    parentId: "metrics-grid",
    index: 2,
  });
  const emptyGridTarget = readStructuredPrototypeDropTarget({
    kind: "container",
    ownerNodeId: "empty-grid",
    depth: 1,
    ancestorNodeIds: ["page-root"],
    parentId: "empty-grid",
    index: 0,
  });
  const containerNodeTarget = readStructuredPrototypeDropTarget({
    kind: "node",
    nodeId: "metric-card",
    ownerNodeId: "metric-card",
    depth: 2,
    ancestorNodeIds: ["page-root", "metrics-grid"],
    parentId: "metrics-grid",
    index: 1,
    containerId: "metric-card",
    containerIndex: 2,
  });
  assert.ok(dragged);
  assert.ok(childTarget);
  assert.ok(emptyGridTarget);
  assert.deepEqual(containerNodeTarget, {
    ownerNodeId: "metric-card",
    depth: 2,
    ancestorNodeIds: ["page-root", "metrics-grid"],
    kind: "container",
    intent: "inside",
    parentId: "metric-card",
    index: 2,
  });
  assert.equal(resolveStructuredPrototypeMoveTargetIndex(dragged, childTarget), 1);
  assert.equal(resolveStructuredPrototypeMoveTargetIndex(dragged, emptyGridTarget), 0);

  const sameContainerEnd = readStructuredPrototypeDropTarget({
    kind: "container",
    ownerNodeId: "metrics-grid",
    depth: 1,
    ancestorNodeIds: ["page-root"],
    parentId: "metrics-grid",
    index: 3,
  });
  assert.ok(sameContainerEnd);
  assert.equal(resolveStructuredPrototypeMoveTargetIndex(dragged, sameContainerEnd), 2);
  const sameContainerAfter = readStructuredPrototypeDropTarget({
    kind: "slot",
    intent: "after",
    ownerNodeId: "metric-b",
    depth: 2,
    ancestorNodeIds: ["page-root", "metrics-grid"],
    parentId: "metrics-grid",
    index: 2,
  });
  assert.ok(sameContainerAfter);
  assert.equal(resolveStructuredPrototypeMoveTargetIndex(dragged, sameContainerAfter), 1);
  const sameContainerNodeBefore = readStructuredPrototypeDropTarget({
    kind: "node",
    nodeId: "metric-b",
    ownerNodeId: "metric-b",
    depth: 2,
    ancestorNodeIds: ["page-root", "metrics-grid"],
    parentId: "metrics-grid",
    index: 1,
  });
  assert.ok(sameContainerNodeBefore);
  assert.equal(resolveStructuredPrototypeMoveTargetIndex(dragged, sameContainerNodeBefore), 0);
  assert.deepEqual(
    readStructuredPrototypeDropTarget({
      kind: "slot",
      intent: "before",
      ownerNodeId: "metric-b",
      depth: 2,
      ancestorNodeIds: ["page-root", "metrics-grid"],
      parentId: "metrics-grid",
      index: 1,
    }),
    {
      ownerNodeId: "metric-b",
      depth: 2,
      ancestorNodeIds: ["page-root", "metrics-grid"],
      kind: "slot",
      intent: "before",
      parentId: "metrics-grid",
      index: 1,
    },
  );
  assert.equal(
    readStructuredPrototypePaletteDragData({
      kind: "palette",
      nodeType: "Grid",
      formDefinitionId: null,
    })?.nodeType,
    "Grid",
  );
  assert.equal(
    readStructuredPrototypeNodeDragData({ kind: "node", nodeId: "metric-a", index: 0 }),
    null,
  );
  assert.deepEqual(
    readStructuredPrototypePageDragData({ kind: "page", pageId: "page-a", index: 1 }),
    {
      kind: "page",
      pageId: "page-a",
      index: 1,
    },
  );
  assert.equal(
    readStructuredPrototypeDropTarget({
      kind: "container",
      ownerNodeId: "grid",
      depth: 0,
      ancestorNodeIds: [],
      parentId: "grid",
      index: -1,
    }),
    null,
  );
  assert.equal(
    readStructuredPrototypeDropTarget({ kind: "container", parentId: "grid", index: 0 }),
    null,
  );
});

test("selection chrome hides only for selected canvas dragging or active Freeform movement", () => {
  const nodeDrag = { kind: "node", nodeId: "metric-a", parentId: "metrics-grid", index: 0 };
  assert.equal(structuredPrototypeNodeDragMatchesSelection(nodeDrag, ["metric-a"]), true);
  assert.equal(structuredPrototypeNodeDragMatchesSelection(nodeDrag, ["metric-b"]), false);
  assert.equal(
    structuredPrototypeNodeDragMatchesSelection(
      { kind: "palette", nodeType: "Text", formDefinitionId: null },
      ["metric-a"],
    ),
    false,
  );
  assert.equal(
    structuredPrototypeNodeDragMatchesSelection({ kind: "page", pageId: "page-a", index: 0 }, [
      "page-a",
    ]),
    false,
  );
  assert.equal(
    structuredPrototypeNodeDragMatchesSelection({ kind: "node", nodeId: "metric-a" }, ["metric-a"]),
    false,
  );
  assert.equal(
    resolveStructuredPrototypeSelectionChromeState(nodeDrag, ["metric-a"], "idle"),
    "hidden-during-node-drag",
  );
  assert.equal(
    resolveStructuredPrototypeSelectionChromeState(nodeDrag, ["metric-b"], "idle"),
    "visible",
  );
  assert.equal(
    resolveStructuredPrototypeSelectionChromeState(
      { kind: "palette", nodeType: "Text", formDefinitionId: null },
      ["metric-a"],
      "idle",
    ),
    "visible",
  );
  assert.equal(
    resolveStructuredPrototypeSelectionChromeState(null, ["metric-a"], "idle"),
    "visible",
  );
  assert.equal(
    resolveStructuredPrototypeSelectionChromeState(null, ["metric-a"], "armed"),
    "visible",
  );
  assert.equal(
    resolveStructuredPrototypeSelectionChromeState(null, ["metric-a"], "preview"),
    "hidden-during-freeform-move",
  );
  assert.equal(
    resolveStructuredPrototypeSelectionChromeState(null, ["metric-a"], "pending"),
    "hidden-during-freeform-move",
  );
});

test("prototype collision prefers the deepest valid target and excludes the dragged subtree", () => {
  const sharedRect = collisionRect(0, 0, 200, 200);
  const collisions = structuredPrototypeCollisionDetection(
    structuredCollisionArguments(
      {
        kind: "node",
        nodeId: "dragged-container",
        parentId: "page-root",
        index: 0,
      },
      { x: 100, y: 100 },
      [
        {
          id: "root-inside",
          data: {
            kind: "container",
            intent: "inside",
            ownerNodeId: "page-root",
            depth: 0,
            ancestorNodeIds: [],
            parentId: "page-root",
            index: 2,
          },
          rect: sharedRect,
        },
        {
          id: "card-inside",
          data: {
            kind: "container",
            intent: "inside",
            ownerNodeId: "target-card",
            depth: 1,
            ancestorNodeIds: ["page-root"],
            parentId: "target-card",
            index: 3,
          },
          rect: sharedRect,
        },
        {
          id: "card-after",
          data: {
            kind: "slot",
            intent: "after",
            ownerNodeId: "target-card",
            depth: 1,
            ancestorNodeIds: ["page-root"],
            parentId: "page-root",
            index: 2,
          },
          rect: sharedRect,
        },
        {
          id: "card-before",
          data: {
            kind: "slot",
            intent: "before",
            ownerNodeId: "target-card",
            depth: 1,
            ancestorNodeIds: ["page-root"],
            parentId: "page-root",
            index: 1,
          },
          rect: sharedRect,
        },
        {
          id: "dragged-child-inside",
          data: {
            kind: "container",
            intent: "inside",
            ownerNodeId: "dragged-child",
            depth: 2,
            ancestorNodeIds: ["page-root", "dragged-container"],
            parentId: "dragged-child",
            index: 0,
          },
          rect: sharedRect,
        },
      ],
    ),
  );

  assert.deepEqual(
    collisions.map((collision) => collision.id),
    ["card-before", "card-after", "card-inside", "root-inside"],
  );
});

test("prototype pointer collision cancels outside targets and keeps keyboard fallback", () => {
  const target = {
    id: "root-inside",
    data: {
      kind: "container",
      intent: "inside",
      ownerNodeId: "page-root",
      depth: 0,
      ancestorNodeIds: [],
      parentId: "page-root",
      index: 0,
    },
    rect: collisionRect(0, 0, 200, 200),
  };
  const activeData = {
    kind: "node",
    nodeId: "dragged-node",
    parentId: "page-root",
    index: 0,
  };

  assert.deepEqual(
    structuredPrototypeCollisionDetection(
      structuredCollisionArguments(activeData, { x: 500, y: 500 }, [target]),
    ),
    [],
  );
  assert.deepEqual(
    structuredPrototypeCollisionDetection(
      structuredCollisionArguments(activeData, null, [target]),
    ).map((collision) => collision.id),
    ["root-inside"],
  );
});

test("prototype move and page projections keep the dropped layout until server confirmation", () => {
  const document = rendererDocument();
  const ids = STRUCTURED_PROCUREMENT_IDS;
  const reorderedNodes = projectStructuredPrototypeNodeMove(
    document,
    ids.pages.list,
    ids.nodes.listTitle,
    ids.roots.list,
    1,
  );
  assert.ok(reorderedNodes);
  const reorderedRoot = firstPage(reorderedNodes).root;
  if (reorderedRoot.type !== "Stack") throw new Error("fixture list root is not a Stack");
  assert.deepEqual(
    reorderedRoot.children.map((node) => node.id),
    [ids.nodes.requestTable, ids.nodes.listTitle],
  );

  assert.equal(
    projectStructuredPrototypeNodeMove(
      document,
      ids.pages.create,
      ids.nodes.createForm,
      ids.nodes.titleInput,
      0,
    ),
    null,
  );

  const reorderedPages = projectStructuredPrototypePageReorder(document, ids.pages.detail, 0);
  assert.ok(reorderedPages);
  assert.deepEqual(
    reorderedPages.pages.map((page) => page.id),
    [ids.pages.detail, ids.pages.list, ids.pages.create],
  );
  assert.deepEqual(
    reorderedPages.navigation.items.map((item) => item.targetPageId),
    [ids.pages.detail, ids.pages.list, ids.pages.create],
  );
  assert.equal(projectStructuredPrototypePageReorder(document, ids.pages.list, 0), document);
});

test("live page hover projects pages and navigation from stable page identities", () => {
  const document = rendererDocument();
  const ids = STRUCTURED_PROCUREMENT_IDS;
  document.navigation.items.push(
    {
      id: "navigation-list-secondary",
      key: "navigation-list-secondary",
      label: "Secondary list",
      targetPageId: ids.pages.list,
    },
    {
      id: "navigation-unbound",
      key: "navigation-unbound",
      label: "Unbound",
      targetPageId: "missing-page",
    },
  );

  const projection = projectStructuredPrototypePageReorderByTargetPageId(
    document,
    ids.pages.detail,
    ids.pages.list,
  );
  assert.ok(projection);
  assert.equal(projection.targetIndex, 0);
  assert.deepEqual(
    projection.document.pages.map((page) => page.id),
    [ids.pages.detail, ids.pages.list, ids.pages.create],
  );
  assert.deepEqual(
    projection.document.navigation.items.map((item) => item.id),
    [
      STRUCTURED_PROCUREMENT_IDS.navigation.detail,
      STRUCTURED_PROCUREMENT_IDS.navigation.list,
      "navigation-list-secondary",
      STRUCTURED_PROCUREMENT_IDS.navigation.create,
      "navigation-unbound",
    ],
  );
  const noOp = projectStructuredPrototypePageReorderByTargetPageId(
    document,
    ids.pages.list,
    ids.pages.list,
  );
  assert.ok(noOp);
  assert.equal(noOp.document, document);
  assert.equal(noOp.targetIndex, 0);
});

test("palette hover moves one deterministic transient subtree without persisting its IDs", () => {
  const document = rendererDocument();
  const ids = STRUCTURED_PROCUREMENT_IDS;
  const formDefinition = document.runtime.forms[0];
  if (formDefinition === undefined) throw new Error("fixture requires a runtime form");
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
  } as const;
  const commandNode = createPaletteNode("Form", "new-form-live", formDefinition, labels);
  const transient = materializeStructuredPrototypePalettePreviewNode(commandNode, 42);
  assert.deepEqual(materializeStructuredPrototypePalettePreviewNode(commandNode, 42), transient);
  assert.match(transient.id, /^prototype-palette-preview:42:new-form-live$/);
  if (transient.type !== "Form") throw new Error("palette preview should be a Form");
  assert.ok(
    transient.children.every((child) =>
      child.id.startsWith("prototype-palette-preview:42:new-form-live-"),
    ),
  );

  const inserted = projectStructuredPrototypeNodeInsert(
    document,
    ids.pages.list,
    ids.roots.list,
    1,
    transient,
  );
  assert.ok(inserted);
  assert.deepEqual(findStructuredPrototypeNodeLocation(inserted, ids.pages.list, transient.id), {
    parentId: ids.roots.list,
    index: 1,
  });
  const moved = projectStructuredPrototypeNodeMoveToDropTarget(
    inserted,
    ids.pages.list,
    transient.id,
    {
      kind: "slot",
      intent: "after",
      ownerNodeId: ids.roots.list,
      depth: 1,
      ancestorNodeIds: [],
      parentId: ids.roots.list,
      index: 3,
    },
  );
  assert.ok(moved);
  assert.deepEqual(moved.location, { parentId: ids.roots.list, index: 2 });
  const repeated = projectStructuredPrototypeNodeMoveToDropTarget(
    moved.document,
    ids.pages.list,
    transient.id,
    {
      kind: "slot",
      intent: "after",
      ownerNodeId: ids.roots.list,
      depth: 1,
      ancestorNodeIds: [],
      parentId: ids.roots.list,
      index: 3,
    },
  );
  assert.ok(repeated);
  assert.equal(repeated.document, moved.document);
  const root = firstPage(moved.document).root;
  if (root.type !== "Stack") throw new Error("fixture list root is not a Stack");
  assert.equal(root.children.filter((node) => node.id === transient.id).length, 1);
  assert.equal(commandNode.newNodeKey, "new-form-live");

  const previewTarget = {
    id: "palette-preview-inside",
    data: {
      kind: "container",
      intent: "inside",
      ownerNodeId: transient.id,
      depth: 2,
      ancestorNodeIds: [ids.roots.list],
      parentId: transient.id,
      index: 0,
    },
    rect: collisionRect(0, 0, 100, 100),
  };
  assert.deepEqual(
    structuredPrototypeCollisionDetection(
      structuredCollisionArguments(
        { kind: "palette", nodeType: "Form", formDefinitionId: formDefinition.id },
        { x: 20, y: 20 },
        [previewTarget],
      ),
    ),
    [],
  );
});

test("palette preview is the active layout item and preserves the hovered insertion", () => {
  const commandNode = createPaletteNode("Text", "new-text-live", null, {
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
  });
  const transient = materializeStructuredPrototypePalettePreviewNode(commandNode, 43);
  const paletteDrag = { kind: "palette", nodeType: "Text", formDefinitionId: null };
  const projectedChildren = [
    { ...transient, id: "existing-a" },
    transient,
    { ...transient, id: "existing-b" },
  ];

  assert.equal(isStructuredPrototypePalettePreviewNodeId(transient.id), true);
  assert.equal(isStructuredPrototypePalettePreviewNodeId("existing-a"), false);
  assert.equal(
    resolveStructuredPrototypeActiveLayoutNodeId(paletteDrag, "real-parent", projectedChildren),
    transient.id,
  );
  assert.equal(
    resolveStructuredPrototypeActiveLayoutNodeId(undefined, "real-parent", projectedChildren),
    transient.id,
  );
  assert.equal(
    resolveStructuredPrototypeActiveLayoutNodeId(paletteDrag, transient.id, projectedChildren),
    null,
  );
  assert.equal(
    resolveStructuredPrototypeActiveLayoutNodeId(
      { kind: "node", nodeId: "existing-b", parentId: "real-parent", index: 2 },
      "real-parent",
      projectedChildren,
    ),
    "existing-b",
  );

  const parentRect = collisionRect(0, 0, 300, 220);
  const baselineAreas = resolveStructuredPrototypeMeasuredDropAreas({
    parentRect,
    children: [
      { nodeId: "existing-a", index: 0, rect: collisionRect(0, 20, 300, 40) },
      { nodeId: "existing-b", index: 1, rect: collisionRect(0, 120, 300, 40) },
    ],
    childCount: 2,
    activeIndex: null,
    layout: "vertical",
  });
  const projectedAreas = resolveStructuredPrototypeMeasuredDropAreas({
    parentRect,
    children: [
      { nodeId: "existing-a", index: 0, rect: collisionRect(0, 20, 300, 40) },
      { nodeId: "existing-b", index: 2, rect: collisionRect(0, 160, 300, 40) },
    ],
    childCount: 3,
    activeIndex: 1,
    layout: "vertical",
  });
  const baselineTarget = baselineAreas.find(
    (area) => area.rect.top <= 90 && area.rect.bottom >= 90,
  );
  const projectedTarget = projectedAreas.find(
    (area) => area.rect.top <= 90 && area.rect.bottom >= 90,
  );
  if (baselineTarget === undefined || projectedTarget === undefined) {
    throw new Error("expected the pointer to resolve to a measured drop area");
  }
  assert.equal(baselineTarget.targetIndex, 1);
  assert.equal(projectedTarget.targetIndex, 2);
  assert.equal(
    resolveStructuredPrototypeMoveTargetIndex(
      { kind: "node", nodeId: transient.id, parentId: "real-parent", index: 1 },
      {
        kind: "slot",
        intent: "before",
        ownerNodeId: "real-parent",
        depth: 1,
        ancestorNodeIds: [],
        parentId: "real-parent",
        index: projectedTarget.targetIndex,
      },
    ),
    baselineTarget.targetIndex,
  );
});

test("live node projection resolves each target from the current projected location", () => {
  const document = rendererDocument();
  const ids = STRUCTURED_PROCUREMENT_IDS;
  const movedToEnd = projectStructuredPrototypeNodeMoveToDropTarget(
    document,
    ids.pages.list,
    ids.nodes.listTitle,
    {
      kind: "slot",
      intent: "after",
      ownerNodeId: ids.roots.list,
      depth: 1,
      ancestorNodeIds: [],
      parentId: ids.roots.list,
      index: 2,
    },
  );
  assert.ok(movedToEnd);
  assert.deepEqual(movedToEnd.location, { parentId: ids.roots.list, index: 1 });
  assert.deepEqual(
    findStructuredPrototypeNodeLocation(movedToEnd.document, ids.pages.list, ids.nodes.listTitle),
    { parentId: ids.roots.list, index: 1 },
  );

  const movedBack = projectStructuredPrototypeNodeMoveToDropTarget(
    movedToEnd.document,
    ids.pages.list,
    ids.nodes.listTitle,
    {
      kind: "slot",
      intent: "before",
      ownerNodeId: ids.nodes.requestTable,
      depth: 1,
      ancestorNodeIds: [ids.roots.list],
      parentId: ids.roots.list,
      index: 0,
    },
  );
  assert.ok(movedBack);
  assert.deepEqual(movedBack.location, { parentId: ids.roots.list, index: 0 });
  const root = firstPage(movedBack.document).root;
  if (root.type !== "Stack") throw new Error("fixture list root is not a Stack");
  assert.deepEqual(
    root.children.map((node) => node.id),
    [ids.nodes.listTitle, ids.nodes.requestTable],
  );
});

test("Studio recursively registers sortable children and faithful drag mirrors", () => {
  const canvas = readCompactSource("features/prototype/structured/StructuredPrototypeCanvas.tsx");
  const studio = readCompactSource(
    "features/prototype/structured/StructuredPrototypeStudioPage.tsx",
  );
  const structuredDrag = readCompactSource(
    "features/prototype/structured/structuredPrototypeDrag.ts",
  );
  const dragMirror = readCompactSource(
    "features/prototype/structured/structuredPrototypeDragMirror.ts",
  );
  const dragMirrorView = readCompactSource(
    "features/prototype/structured/StructuredPrototypeDragMirrorView.tsx",
  );
  const preview = readCompactSource("features/prototype/structured/StructuredPrototypePreview.tsx");
  const interaction = readCompactSource(
    "features/prototype/structured/structuredPrototypeInteraction.ts",
  );
  const aiHook = readCompactSource("features/prototype/structured/useStructuredPrototypeAi.ts");
  const palette = readCompactSource("features/prototype/structured/StructuredPrototypePalette.tsx");
  const rail = readCompactSource("features/prototype/structured/StructuredPrototypePageRail.tsx");
  const inspector = readCompactSource(
    "features/prototype/structured/StructuredPrototypeInspector.tsx",
  );
  const sortableNodeStart = canvas.indexOf("function SortableCanvasNode");
  const controlsLayerStart = canvas.indexOf("function StructuredPrototypeSelectionControlsLayer");
  const canvasRootStart = canvas.indexOf("export function StructuredPrototypeCanvas");
  const canvasRootEnd = canvas.indexOf("function OverlayNodeContent");
  const dragStartStart = studio.indexOf("const handleDragStart");
  const dragOverStart = studio.indexOf("const handleDragOver");
  const cancelMoveStart = studio.indexOf("const cancelActiveMove");
  const commitMoveStart = studio.indexOf("const commitActiveMove");
  const dragEndStart = studio.indexOf("const handleDragEnd");
  const studioDragOverlayStart = studio.indexOf("<DragOverlay");
  assert.ok(sortableNodeStart >= 0 && controlsLayerStart > sortableNodeStart);
  assert.ok(canvasRootStart > controlsLayerStart && canvasRootEnd > canvasRootStart);
  assert.ok(dragStartStart >= 0 && dragOverStart > dragStartStart);
  assert.ok(cancelMoveStart > dragOverStart && commitMoveStart > cancelMoveStart);
  assert.ok(dragEndStart > commitMoveStart && studioDragOverlayStart > dragEndStart);
  const sortableNodeSource = canvas.slice(sortableNodeStart, controlsLayerStart);
  const controlsLayerSource = canvas.slice(controlsLayerStart, canvasRootStart);
  const canvasRootSource = canvas.slice(canvasRootStart, canvasRootEnd);
  const canvasDragOverlaySource = canvas.slice(canvasRootEnd);
  const dragStartSource = studio.slice(dragStartStart, dragOverStart);
  const cancelMoveSource = studio.slice(cancelMoveStart, commitMoveStart);
  const commitMoveSource = studio.slice(commitMoveStart, dragEndStart);
  const studioDragOverlaySource = studio.slice(studioDragOverlayStart);

  assert.match(canvas, /rectSortingStrategy/);
  assert.match(canvas, /ownerNodeId: node\.id/);
  assert.match(canvas, /depth=\{depth \+ 1\}/);
  assert.match(canvas, /ancestorNodeIds=\{childAncestorNodeIds\}/);
  assert.match(canvas, /parentId: node\.id/);
  assert.match(canvas, /index: node\.children\.length/);
  assert.match(canvas, /nodeId: node\.id/);
  assert.match(canvas, /containerId: node\.id, containerIndex: node\.children\.length/);
  assert.match(canvas, /data-prototype-drop-intent=\{intent\}/);
  assert.match(canvas, /intent="inside"/);
  assert.match(canvas, /resolveStructuredPrototypeMeasuredDropAreas/);
  assert.match(canvas, /new ResizeObserver\(measureDropAreas\)/);
  assert.match(canvas, /right: parentElement\.clientWidth/);
  assert.match(canvas, /left: element\.offsetLeft/);
  assert.match(canvas, /activeIndex/);
  assert.match(canvas, /child\.id !== activeNodeId && child\.layoutItem\.position === undefined/);
  assert.match(canvas, /data-prototype-active-layout-node-id/);
  assert.match(canvas, /data-prototype-measured-layout-child-count/);
  assert.match(canvas, /data-prototype-drop-area-count/);
  assert.doesNotMatch(canvas, /getClientRect/);
  assert.match(canvas, /data-prototype-drop-measured="true"/);
  assert.match(canvas, /index: area\.targetIndex/);
  assert.match(controlsLayerSource, /data-prototype-node-selected/);
  assert.match(controlsLayerSource, /data-prototype-selection-controls={primary/);
  assert.match(controlsLayerSource, /data-prototype-selection-count={targets\.length}/);
  assert.match(controlsLayerSource, /data-prototype-selection-primary/);
  assert.match(controlsLayerSource, /data-prototype-selection-outline="true"/);
  assert.match(controlsLayerSource, /resolveStructuredPrototypeSelectionChromeState/);
  assert.match(controlsLayerSource, /data-prototype-selection-chrome/);
  assert.match(controlsLayerSource, /outlineColor: selectionChromeHidden/);
  assert.match(controlsLayerSource, /visibility: selectionChromeHidden/);
  assert.match(controlsLayerSource, /data-prototype-marquee="true"/);
  assert.match(controlsLayerSource, /ref=\{sortableControls\.setActivatorNodeRef\}/);
  assert.match(controlsLayerSource, /data-prototype-selection-move-surface="sortable"/);
  assert.match(controlsLayerSource, /data-prototype-selection-move-surface="freeform"/);
  assert.match(canvas, /data-prototype-selection-move-edge="top"/);
  assert.match(canvas, /data-prototype-selection-move-edge="bottom"/);
  assert.match(canvas, /data-prototype-selection-move-edge="left"/);
  assert.match(canvas, /data-prototype-selection-move-edge="right"/);
  const selectionMoveEdgesStart = canvas.indexOf("function StructuredPrototypeSelectionMoveEdges");
  const selectionIntentStart = canvas.indexOf(
    "export type StructuredPrototypeNodeSelectionIntent",
    selectionMoveEdgesStart,
  );
  assert.ok(selectionMoveEdgesStart >= 0 && selectionIntentStart > selectionMoveEdgesStart);
  const selectionMoveEdgesSource = canvas.slice(selectionMoveEdgesStart, selectionIntentStart);
  assert.match(
    selectionMoveEdgesSource,
    /disabled \? "pointer-events-none" : "pointer-events-auto"/,
  );
  assert.equal(
    [...selectionMoveEdgesSource.matchAll(/data-prototype-selection-move-edge=/g)].length,
    4,
  );
  for (const surface of ["group-freeform", "freeform", "sortable"]) {
    const surfaceIndex = controlsLayerSource.indexOf(
      `data-prototype-selection-move-surface="${surface}"`,
    );
    const buttonStart = controlsLayerSource.lastIndexOf("<button", surfaceIndex);
    assert.ok(buttonStart >= 0 && surfaceIndex > buttonStart);
    assert.match(
      controlsLayerSource.slice(buttonStart, surfaceIndex),
      /className="pointer-events-none absolute inset-0/,
    );
  }
  const firstSelectionTools = controlsLayerSource.indexOf("data-prototype-selection-tools=");
  const lastSnapGuide = controlsLayerSource.lastIndexOf('data-prototype-snap-guide="true"');
  const lastSpacingGuide = controlsLayerSource.lastIndexOf('data-prototype-spacing-guide="true"');
  assert.ok(lastSnapGuide >= 0 && lastSnapGuide < firstSelectionTools);
  assert.ok(lastSpacingGuide >= 0 && lastSpacingGuide < firstSelectionTools);
  assert.ok(
    controlsLayerSource.indexOf('data-prototype-selection-move-surface="group-freeform"') <
      controlsLayerSource.indexOf('data-prototype-selection-tools="group"'),
  );
  assert.ok(
    controlsLayerSource.indexOf('data-prototype-selection-move-surface="freeform"') <
      controlsLayerSource.indexOf("data-prototype-selection-tools={primary"),
  );
  assert.ok(
    controlsLayerSource.indexOf('data-prototype-selection-move-surface="sortable"') <
      controlsLayerSource.indexOf("data-prototype-selection-tools={primary"),
  );
  assert.equal(
    [...controlsLayerSource.matchAll(/style=\{\{visibility: selectionChromeHidden/g)].length,
    2,
  );
  assert.match(canvas, /cursor-nwse-resize/);
  assert.match(canvas, /cursor-ew-resize/);
  assert.match(canvas, /cursor-ns-resize/);
  assert.match(controlsLayerSource, /data-prototype-resize-direction/);
  assert.match(
    controlsLayerSource,
    /onResizePointerDown\(target\.node\.id, handle\.direction, event\)/,
  );
  assert.match(canvas, /markerClassName/);
  assert.match(canvas, /size-2 border border-\[var\(--prototype-accent\)\]/);
  assert.doesNotMatch(canvas, /GripVertical/);
  assert.doesNotMatch(sortableNodeSource, /data-prototype-node-selected/);
  assert.doesNotMatch(sortableNodeSource, /cursor-nwse-resize/);
  assert.doesNotMatch(sortableNodeSource, /<GripVertical/);
  assert.match(canvas, /props\.onSelect\(node\.id, event\.shiftKey \? "toggle" : "replace"\)/);
  assert.doesNotMatch(canvas, /selected \? "opacity-100"/);
  assert.match(canvas, /if \(!props\.editing\) return; event\.stopPropagation\(\)/);
  assert.match(
    controlsLayerSource,
    /handleScale = resolveStructuredPrototypeInverseScale\(previewScale\)/,
  );
  assert.match(canvas, /left-full top-full/);
  assert.match(canvas, /origin-top-right/);
  assert.match(canvas, /resolveStructuredPrototypeLayoutItem/);
  assert.match(canvas, /canvasLayoutStyle\(resolvedLayoutItem\)/);
  assert.match(canvas, /\[&>:last-child\]:w-full/);
  assert.match(canvas, /\[&>:last-child\]:h-full/);
  assert.match(canvas, /cursor-nwse-resize/);
  assert.match(
    canvasRootSource,
    /resizeNodeRef\.current\(\s*nodeId,\s*finalSize\.width,\s*finalSize\.height,\s*finalSize\.position,\s*finalSize\.groupItems,\s*\)/,
  );
  assert.match(canvasRootSource, /catch \(error\).*resizeErrorRef\.current\(error\)/);
  assert.match(canvasRootSource, /finally.*endResizeCommit\("pointerup"\)/);
  assert.match(canvasRootSource, /acceptedSessionId !== gesture\.sessionId/);
  assert.match(canvas, /globalThis\.window\.addEventListener\("pointerup", handlePointerUp/);
  assert.match(
    canvas,
    /globalThis\.window\.addEventListener\("pointercancel", handlePointerCancel/,
  );
  assert.match(canvas, /data-prototype-resize-phase/);
  assert.match(canvas, /data-prototype-resize-last-end/);
  assert.match(canvasRootSource, /handle\.setPointerCapture\(pointerId\)/);
  assert.match(canvasRootSource, /handle\.addEventListener\("lostpointercapture"/);
  assert.match(canvasRootSource, /gesture\.handle\.hasPointerCapture\(gesture\.pointerId\)/);
  assert.match(canvasRootSource, /latestClientX/);
  assert.match(canvasRootSource, /latestLockAspectRatio/);
  assert.match(canvasRootSource, /pointerEvent\.shiftKey/);
  assert.match(canvasRootSource, /projectionFrame/);
  assert.match(canvasRootSource, /requestAnimationFrame/);
  assert.match(canvasRootSource, /cancelAnimationFrame/);
  assert.match(
    canvasRootSource,
    /scheduleResize\(\s*pointerEvent\.clientX,\s*pointerEvent\.clientY,\s*pointerEvent\.shiftKey,\s*pointerEvent\.altKey,\s*pointerEvent\.ctrlKey \|\| pointerEvent\.metaKey,?\s*\)/,
  );
  assert.match(
    canvasRootSource,
    /resolveResizeProjection\(\s*activeGesture,\s*pointerEvent\.clientX,\s*pointerEvent\.clientY,\s*pointerEvent\.shiftKey,\s*pointerEvent\.altKey,\s*pointerEvent\.ctrlKey \|\| pointerEvent\.metaKey,?\s*\)/,
  );
  assert.equal([...canvasRootSource.matchAll(/resizeNodeRef\.current\(/g)].length, 1);
  assert.match(canvasRootSource, /if \(finalSize === null\).*return;.*resizeNodeRef\.current/);
  assert.match(canvasRootSource, /nodeElementRegistrationsRef\.current\.set/);
  assert.match(canvasRootSource, /nodeElementRegistrationsRef\.current\.delete/);
  assert.match(canvasRootSource, /setNodeRegistryVersion/);
  assert.match(canvasRootSource, /registered\?\.registrationKey !== registrationKey/);
  assert.match(sortableNodeSource, /setActivatorNodeRef/);
  assert.match(sortableNodeSource, /registerSortableControls/);
  assert.match(canvasRootSource, /data-prototype-canvas-wrapper="true"/);
  assert.match(canvasRootSource, /data-prototype-node-layer="business"/);
  assert.match(canvasRootSource, /data-prototype-marquee-phase/);
  assert.match(canvasRootSource, /data-prototype-marquee-last-end/);
  assert.match(canvasRootSource, /handleMarqueePointerDown/);
  assert.match(canvasRootSource, /owner\.setPointerCapture\(pointerId\)/);
  assert.match(canvasRootSource, /scheduleMarquee/);
  assert.match(canvasRootSource, /projectMarquee\(gesture, pointerEvent\.clientX/);
  assert.match(canvasRootSource, /endMarqueeGesture\("pointerup", false\)/);
  assert.match(canvasRootSource, /endMarqueeGesture\(reason, true\)/);
  assert.match(canvasRootSource, /<StructuredPrototypeSelectionControlsLayer/);
  assert.match(
    canvasRootSource,
    /data-prototype-node-layer="business".*<StructuredPrototypeSelectionControlsLayer/,
  );
  assert.match(canvas, /<SortableCanvasNode/);
  assert.match(canvas, /StructuredPrototypeNodeDragOverlay/);
  assert.match(canvas, /<OverlayNodeContent/);
  assert.match(canvas, /runtimeNodeText\(viewModel, node\.id, node\.content\)/);
  assert.match(canvas, /runtimeNodeRows\(viewModel, node\.id\)/);
  assert.match(sortableNodeSource, /isDragging && "opacity-0"/);
  assert.doesNotMatch(sortableNodeSource, /opacity-20/);
  assert.match(
    sortableNodeSource,
    /const dragMirrorSourceRef = useRef<HTMLElement \| null>\(null\)/,
  );
  assert.match(
    sortableNodeSource,
    /captureStructuredPrototypeDragMirror\(dragMirrorSourceRef\.current\)/,
  );
  assert.match(sortableNodeSource, /captureDragMirror,/);
  assert.match(sortableNodeSource, /dragMirrorSourceRef\.current = element/);
  assert.match(structuredDrag, /export function readStructuredPrototypeNodeDragMirrorCapture\(/);
  assert.match(
    structuredDrag,
    /value\["kind"\] !== "node".*const capture = value\["captureDragMirror"\].*typeof capture === "function"/,
  );
  assert.match(
    dragStartSource,
    /const dragMirror =\s*readStructuredPrototypeNodeDragMirrorCapture\(event\.active\.data\.current\)\?\.\(\) \?\? null/,
  );
  assert.match(
    dragStartSource,
    /if \(dragMirror === null\).*setInteractionError\(t\("prototype\.structured\.canvas\.dragPreviewFailed"\)\).*return/,
  );
  assert.match(dragStartSource, /setActiveNodeDragMirror\(dragMirror\)/);
  assert.doesNotMatch(dragStartSource, /requestAnimationFrame/);
  const captureIndex = dragStartSource.indexOf(
    "readStructuredPrototypeNodeDragMirrorCapture(event.active.data.current)?.()",
  );
  const nodeProjectionIndex = dragStartSource.indexOf(
    'activeMoveProjectionRef.current = {kind: "node"',
  );
  const nodeInteractionIndex = dragStartSource.indexOf(
    'beginInteraction({kind: "move", source: {kind: "node"',
  );
  assert.ok(
    captureIndex >= 0 &&
      nodeInteractionIndex > captureIndex &&
      nodeProjectionIndex > nodeInteractionIndex,
  );

  assert.match(dragMirror, /const clonedNode = source\.cloneNode\(true\)/);
  assert.match(
    dragMirror,
    /querySelectorAll<HTMLElement>\("\[data-prototype-drop-intent\]"\).*dropTarget\.remove\(\)/,
  );
  assert.match(
    dragMirror,
    /for \(const attribute of MIRROR_IDENTITY_ATTRIBUTES\) descendant\.removeAttribute\(attribute\)/,
  );
  assert.match(dragMirror, /"id", "for", "name"/);
  assert.match(dragMirror, /"data-node-id", "data-container-id"/);
  assert.match(dragMirror, /descendant\.removeAttribute\("autofocus"\)/);
  assert.match(dragMirror, /descendant\.removeAttribute\("contenteditable"\)/);
  assert.match(dragMirror, /descendant\.setAttribute\("tabindex", "-1"\)/);
  assert.match(dragMirror, /element\.setAttribute\("aria-hidden", "true"\)/);
  assert.match(dragMirror, /element\.setAttribute\("inert", ""\)/);
  assert.match(dragMirror, /element\.style\.pointerEvents = "none"/);
  assert.match(dragMirror, /element\.style\.opacity = "1"/);
  assert.match(dragMirror, /Object\.assign\(element\.style, rootStyle\)/);
  assert.match(dragMirror, /position: "relative"/);
  assert.match(dragMirror, /top: "auto"/);
  assert.match(dragMirror, /right: "auto"/);
  assert.match(dragMirror, /bottom: "auto"/);
  assert.match(dragMirror, /left: "auto"/);
  assert.match(dragMirror, /width: `\$\{contentWidth\}px`/);
  assert.match(dragMirror, /height: `\$\{contentHeight\}px`/);
  assert.match(dragMirror, /maxWidth: "none"/);
  assert.match(dragMirror, /maxHeight: "none"/);
  assert.match(dragMirror, /flex: "0 0 auto"/);
  assert.match(dragMirror, /alignSelf: "auto"/);
  assert.match(dragMirror, /gridArea: "auto"/);
  assert.match(dragMirror, /transform: "none"/);
  assert.match(dragMirror, /transition: "none"/);

  assert.match(dragMirror, /cloneElement\.value = sourceElement\.value/);
  assert.match(dragMirror, /cloneElement\.checked = sourceElement\.checked/);
  assert.match(dragMirror, /cloneElement\.indeterminate = sourceElement\.indeterminate/);
  assert.match(dragMirror, /cloneOption\.selected = sourceOption\.selected/);
  assert.match(dragMirror, /scrollLeft: sourceElement\.scrollLeft/);
  assert.match(dragMirror, /scrollTop: sourceElement\.scrollTop/);
  assert.match(
    dragMirrorView,
    /restoreStructuredPrototypeDragMirrorScrollState\(snapshot\.scrollStates\)/,
  );

  assert.match(dragMirror, /name\.startsWith\("--prototype-"\)/);
  assert.match(dragMirror, /style\.getPropertyValue\(name\)\.trim\(\)/);
  assert.match(dragMirror, /customProperties: collectPrototypeCustomProperties\(computedStyle\)/);
  assert.match(dragMirrorView, /\.\.\.snapshot\.customProperties/);
  assert.match(dragMirror, /clientWidth: bounds\.width/);
  assert.match(dragMirror, /clientHeight: bounds\.height/);
  assert.match(dragMirror, /contentWidth: source\.offsetWidth/);
  assert.match(dragMirror, /contentHeight: source\.offsetHeight/);
  assert.match(dragMirror, /scaleX: clientWidth \/ contentWidth/);
  assert.match(dragMirror, /scaleY: clientHeight \/ contentHeight/);
  assert.match(dragMirrorView, /width: snapshot\.geometry\.clientWidth/);
  assert.match(dragMirrorView, /height: snapshot\.geometry\.clientHeight/);
  assert.match(
    dragMirrorView,
    /transform: `scale\(\$\{snapshot\.geometry\.scaleX\}, \$\{snapshot\.geometry\.scaleY\}\)`/,
  );
  assert.match(dragMirrorView, /host\.replaceChildren\(snapshot\.element\)/);
  assert.match(
    dragMirrorView,
    /if \(snapshot\.element\.parentElement === host\) host\.replaceChildren\(\)/,
  );
  assert.match(dragMirrorView, /data-prototype-drag-overlay="node"/);
  assert.match(dragMirrorView, /data-prototype-drag-mirror="true"/);
  assert.match(dragMirrorView, /aria-hidden inert/);

  assert.match(
    dragStartSource,
    /const transientNode = materializeStructuredPrototypePalettePreviewNode\(\s*commandNode, sessionId,?\s*\).*setActivePaletteDragNode\(transientNode\).*transientNode,/,
  );
  assert.match(canvasDragOverlaySource, /data-prototype-drag-overlay=\{kind\}/);
  assert.match(canvasDragOverlaySource, /aria-hidden inert/);
  assert.match(canvasDragOverlaySource, /\.\.\.resolveStructuredPrototypeTheme\(document\)/);
  assert.match(canvasDragOverlaySource, /renderedChildren\.map\(\(child\) =>/);
  assert.match(canvasDragOverlaySource, /<LeafNodeRenderer/);
  assert.match(studioDragOverlaySource, /kind="palette"/);
  assert.match(studioDragOverlaySource, /node=\{activePaletteDragNode\}/);
  assert.match(studioDragOverlaySource, /previewScale=\{effectivePreviewScale\}/);
  assert.match(
    studioDragOverlaySource,
    /<StructuredPrototypeDragMirrorView snapshot=\{activeNodeDragMirror\}/,
  );
  assert.match(studioDragOverlaySource, /adjustScale=\{false\}/);
  assert.doesNotMatch(studioDragOverlaySource, /kind="node"/);

  for (const lifecycleSource of [cancelMoveSource, commitMoveSource]) {
    assert.match(lifecycleSource, /setActiveNodeDragMirror\(null\)/);
    assert.match(lifecycleSource, /setActivePaletteDragNode\(null\)/);
  }
  assert.match(studio, /onDragCancel=\{\(\) => \{.*cancelActiveMove\(session\)/);
  assert.match(studio, /const handleDragEnd = .*cancelActiveMove\(session\).*commitActiveMove\(/);
  assert.doesNotMatch(canvasDragOverlaySource, /node\.type\}.*node\.name/);
  assert.doesNotMatch(studioDragOverlaySource, /paletteLabels\[activeDrag\.nodeType\]/);
  assert.doesNotMatch(canvasDragOverlaySource, /\.slice\(0, 6\)/);
  assert.doesNotMatch(canvasDragOverlaySource, /\.slice\(0, 3\)/);
  assert.match(studio, /<DragOverlay/);
  assert.match(studio, /collisionDetection=\{structuredPrototypeCollisionDetection\}/);
  assert.match(studio, /MeasuringStrategy\.Always/);
  assert.match(studio, /onDragStart=\{handleDragStart\}/);
  assert.match(studio, /onDragOver=\{handleDragOver\}/);
  assert.match(studio, /projectStructuredPrototypeNodeMoveToDropTarget/);
  assert.match(studio, /requestAnimationFrame/);
  assert.match(studio, /clearActiveMoveProjection\(\)/);
  assert.match(studio, /zIndex=\{1000\}/);
  assert.match(studio, /data-prototype-drag-overlay="page"/);
  assert.match(studio, /readStructuredPrototypePageDragData\(event\.active\.data\.current\)/);
  assert.match(
    studio,
    /reorderPageBatch\(.*session\.authoritativeDocument.*session\.pageId.*result\.targetIndex/,
  );
  assert.doesNotMatch(studio, /setManualPageId\(draggedPage\.pageId\)/);
  assert.match(studio, /removeNodesBatch\(deletingNodeIds\)/);
  assert.match(studio, /\{key: "Delete", action: \(\) => void deleteSelectedNodes\(\)\}/);
  assert.match(studio, /\{key: "Backspace", action: \(\) => void deleteSelectedNodes\(\)\}/);
  assert.match(studio, /if \(removed === true\).*createStructuredPrototypeEmptySelection/);
  assert.match(studio, /runtimeTableRowsBinding\(document, selectedNode\.id\)/);
  assert.match(studio, /readStructuredPrototypeDropTarget\(event\.over\.data\.current\)/);
  assert.match(
    studio,
    /moveNodeBatch\(\s*session\.nodeId,\s*targetParent,\s*result\.location\.index,\s*result\.location\.position/,
  );
  const hashGateIndex = studio.indexOf("currentDraft.documentHash !== session.baseDocumentHash");
  const noOpGateIndex = studio.indexOf("sameNodeLocation(result.location, originalLocation)");
  const moveCommandIndex = studio.indexOf("moveNodeBatch(", noOpGateIndex);
  assert.ok(hashGateIndex >= 0 && hashGateIndex < moveCommandIndex);
  assert.ok(noOpGateIndex >= 0 && noOpGateIndex < moveCommandIndex);
  assert.match(studio, /projectStructuredPrototypeNodeMove/);
  assert.match(studio, /projectStructuredPrototypePageReorderByTargetPageId/);
  assert.match(studio, /materializeStructuredPrototypePalettePreviewNode/);
  assert.match(studio, /projectStructuredPrototypeNodeInsert/);
  assert.match(studio, /ownerSessionId/);
  assert.match(studio, /status: "hover" \| "pending"/);
  assert.match(studio, /if \(!advanceInteraction\(session\.interactionSessionId, "committing"\)\)/);
  assert.match(studio, /setProjectedDocument/);
  assert.match(studio, /canDelete=\{activeSelectedNodeIds\.length > 0\}/);
  assert.match(studio, /isRuntimeBoundTable=\{selectedNodeIsRuntimeBoundTable\}/);
  assert.match(studio, /runtimeTable=\{selectedRuntimeTable\}/);
  assert.match(
    studio,
    /key=\{`\$\{selectedNode\?\.id \?\? "none"\}:\$\{controller\.draft\.documentHash\}`\}/,
  );
  assert.match(studio, /onDelete=\{\(\) => void deleteSelectedNodes\(\)\}/);
  assert.match(studio, /selection=\{activeNodeSelection\}/);
  assert.match(studio, /onMarqueeGestureChange=\{handleMarqueeGestureChange\}/);
  assert.match(studio, /selectedNodeIds=\{activeSelectedNodeIds\}/);
  assert.match(studio, /summary: "Resize component"/);
  assert.match(studio, /onResizeNode=\{resizeNode\}/);
  assert.match(studio, /onResizeGestureChange=\{handleResizeGestureChange\}/);
  assert.match(studio, /interactionRef\.current = next/);
  assert.match(studio, /data-prototype-interaction=\{interaction\.kind\}/);
  assert.match(studio, /data-prototype-interaction-phase/);
  assert.match(studio, /data-prototype-interaction-session/);
  assert.match(studio, /data-prototype-document-sequence=\{controller\.draft\.headSequenceNo\}/);
  assert.match(studio, /data-prototype-saving=\{controller\.saving \? "true" : "false"\}/);
  assert.match(studio, /data-prototype-projection-status/);
  assert.match(studio, /data-prototype-projection-owner/);
  assert.match(studio, /beginStructuredPrototypeInteraction/);
  assert.match(studio, /if \(interactionRef\.current\.kind !== "idle"\) return/);
  assert.match(studio, /documentControlsDisabled/);
  assert.match(studio, /onClick=\{\(\) => handleViewportSelect\(value\)\}/);
  assert.match(interaction, /kind: "idle"/);
  assert.match(interaction, /kind: "pan"/);
  assert.match(interaction, /kind: "marquee"/);
  assert.match(interaction, /kind: "move"/);
  assert.match(interaction, /kind: "resize"/);
  assert.match(interaction, /kind: "mutation"/);
  assert.match(interaction, /phase: "active" \| "committing"/);
  assert.match(aiHook, /const sessionId = onApplyStart\(\)/);
  assert.match(aiHook, /adopted = await onDraftApplied\(appliedDraft, sessionId\)/);
  assert.match(aiHook, /finally.*onApplyEnd\(sessionId\)/);
  assert.match(aiHook, /getCurrentStructuredPrototypeDraft/);
  assert.match(aiHook, /finishStructuredPrototypePendingOperation/);
  assert.match(studio, /const editorMutationLocked = controller\.saving \|\| aiMutating/);
  assert.match(studio, /onMutatingChange=\{setAiMutating\}/);
  assert.match(studio, /if \(!sessionMatches\).*return Promise\.resolve\(false\)/);
  assert.match(studio, /onResizeError=\{handleResizeError\}/);
  assert.match(studio, /editing=\{canvasInteraction === "edit"\}/);
  assert.match(rail, /SortableContext/);
  assert.match(rail, /useSortable/);
  assert.match(rail, /data: \{kind: "page", pageId: page\.id, index\}/);
  assert.match(rail, /<div ref=\{setNodeRef\}/);
  assert.doesNotMatch(rail, /<button ref=\{setNodeRef\}/);
  assert.match(rail, /<button ref=\{setActivatorNodeRef\}/);
  assert.match(rail, /\{\.\.\.attributes\} \{\.\.\.listeners\} aria-label=/);
  assert.match(rail, /disabled: dragDisabled/);
  assert.match(rail, /disabled=\{selectionDisabled\}/);
  assert.match(studio, /selectionDisabled=\{interactionCapabilities\.documentControlsDisabled\}/);
  assert.match(studio, /pages=\{pageRailPages \?\? document\.pages\}/);
  assert.match(rail, /data-prototype-page-drop-indicator=\{dropIndicator \?\? "none"\}/);
  assert.match(rail, /data-prototype-page-drop-indicator-line=\{dropIndicator\}/);
  assert.match(rail, /resolveStructuredPrototypePageDropIndicator/);
  assert.match(inspector, /kind: "tableData"/);
  assert.match(inspector, /kind: "setRuntimeEntityField"/);
  assert.match(inspector, /buildStructuredPrototypeRuntimeTableCommands/);
  assert.match(inspector, /prototype\.structured\.inspector\.tableData/);
  assert.match(inspector, /prototype\.structured\.inspector\.runtimeTableNote/);
  assert.match(inspector, /disabled=\{disabled \|\| isRuntimeBoundTable\}/);
  assert.match(inspector, /prototype\.structured\.inspector\.delete/);
  assert.doesNotMatch(palette, /translate3d/);
  assert.match(studio, /PREVIEW_ZOOM_OPTIONS/);
  assert.match(studio, /prototype\.structured\.zoom\.fit/);
  assert.match(studio, /zoom=\{previewZoom\}/);
  assert.match(studio, /viewResetKey=\{previewViewResetKey\}/);
  assert.match(
    studio,
    /dragGestureActive=\{\s*interaction\.kind === "move" \|\| interaction\.kind === "freeformMove"\s*\}/,
  );
  assert.match(studio, /activeInteractionKind=\{interaction\.kind\}/);
  assert.match(studio, /setPreviewViewResetKey\(\(current\) => current \+ 1\)/);
  assert.match(studio, /onZoomChange=\{setPreviewZoom\}/);
  assert.match(preview, /width: `\$\{viewportWidth\}px`/);
  assert.match(preview, /minWidth: `\$\{viewportWidth\}px`/);
  assert.match(preview, /data-prototype-preview-zoom/);
  assert.match(preview, /data-prototype-preview-scale/);
  assert.match(preview, /data-prototype-preview-scale-frozen/);
  assert.match(preview, /resolveStructuredPrototypeEffectivePreviewScale/);
  assert.match(preview, /frozenFrameHeight \?\? computedFrameHeight/);
  assert.match(preview, /transformGestureActive = dragGestureActive \|\| resizeGestureActive/);
  assert.match(preview, /onPanGestureStart\(event\.pointerId\)/);
  assert.match(preview, /onLostPointerCapture/);
  assert.match(preview, /previewScale=\{previewScale\}/);
  assert.match(preview, /onResizeNode=\{onResizeNode\}/);
  assert.match(preview, /onResizeGestureChange=\{handleResizeGestureChange\}/);
  assert.match(preview, /editing=\{editing\}/);
  assert.match(preview, /aria-current=\{item\.targetPageId === page\.id \? "page" : undefined\}/);
  assert.match(preview, /data-prototype-preview-pan/);
  assert.match(
    preview,
    /if \(zoom !== "fit"\) return; cancelWheelZoom\(\); finishPan\(null\); setPan/,
  );
  assert.match(preview, /\[cancelWheelZoom, finishPan, viewResetKey, zoom\]/);
  assert.match(preview, /previewHostSize\.height/);
  assert.match(preview, /previewFrameHeight/);
  assert.match(preview, /useLayoutEffect\(\(\) => \{const host = previewHostRef\.current/);
  assert.match(preview, /useLayoutEffect\(\(\) => \{const frame = previewFrameRef\.current/);
  assert.match(preview, /resolveStructuredPrototypeFitScale/);
  assert.match(preview, /resolveStructuredPrototypeZoomAtPoint/);
  assert.match(preview, /normalizeStructuredPrototypeWheelDelta/);
  assert.match(preview, /resolveStructuredPrototypeWheelScale/);
  assert.match(preview, /wheelAccumulatorRef/);
  assert.match(preview, /requestAnimationFrame/);
  assert.match(preview, /cancelAnimationFrame/);
  assert.match(preview, /data-prototype-wheel-input="normalized-raf"/);
  assert.match(preview, /viewportHeight: page\.viewport\.height/);
  assert.match(preview, /place-items-center/);
  assert.match(preview, /onWheel=\{handleWheel\}/);
  assert.match(preview, /onPointerDown=\{handlePointerDown\}/);
  assert.match(preview, /setPointerCapture\(event\.pointerId\)/);
  assert.match(preview, /releasePointerCapture\(currentPan\.pointerId\)/);
  assert.match(preview, /isKeyboardShortcutEditableTarget\(event\.target\)/);
  assert.match(preview, /width: `\$\{scaledFrameWidth\}px`/);
  assert.match(preview, /height: `\$\{scaledFrameHeight\}px`/);
  assert.match(preview, /transform: `translate\(\$\{pan\.x\}px, \$\{pan\.y\}px\)`/);
  assert.match(preview, /transform: `scale\(\$\{previewScale\}\)`/);
  assert.match(preview, /transformOrigin: "top left"/);
  assert.doesNotMatch(preview, /maxWidth: "100%"/);
});

test("renderer accepts injection-safe CSS color literals and rejects CSS escapes", () => {
  const accepted = [
    "#abc",
    "#abcd",
    "#aabbcc",
    "#aabbccdd",
    "black",
    "rgb(12 34 56 / 80%)",
    "rgba(12, 34, 56, 0.8)",
    "hsl(210deg 50% 40%)",
    "hsla(210, 50%, 40%, 0.8)",
    "oklab(55% 0.1 -0.1)",
    "oklch(55% 0.15 210 / 80%)",
    "lab(55% 20 -15)",
    "lch(55% 30 210)",
    "color(display-p3 0.2 0.4 0.6 / 0.8)",
  ];
  for (const color of accepted) {
    const document = rendererDocument();
    setShellColors(document, {
      accent: color,
      navigation: "#fff",
      content: "#fff",
      surface: "#fff",
    });
    assert.ok(renderStyles(document).includes(`--prototype-accent:${color}`));
  }

  const functional = rendererDocument();
  setShellColors(functional, {
    accent: "rgb(0 0 0)",
    navigation: "#fff",
    content: "#fff",
    surface: "#fff",
  });
  assert.equal(resolvePrototypeShellTheme(functional).accentText, "#17201d");

  for (const color of [
    "#12345",
    "#1234567",
    "red;--escape:black",
    "red{color:black}",
    "@supports(display:grid)",
    "rgb(var(--red) 0 0)",
    "url(data:text/css,red)",
    "'red'",
    "red\\9",
  ]) {
    const document = rendererDocument();
    setShellColors(document, {
      accent: color,
      navigation: "#fff",
      content: "#fff",
      surface: "#fff",
    });
    assert.throws(() => renderStyles(document), /renderer does not support color token value/);
  }
});

test("mixed shell palettes derive independent readable text tokens", () => {
  const document = rendererDocument();
  setShellColors(document, {
    accent: "#000f",
    navigation: "#fff8",
    content: "#ffffff",
    surface: "#111111",
  });
  assert.deepEqual(resolvePrototypeShellTheme(document), {
    accent: "#000f",
    accentText: "#ffffff",
    navigationBackground: "#fff8",
    navigationText: "#17201d",
    contentBackground: "#ffffff",
    contentText: "#17201d",
    surface: "#111111",
    surfaceText: "#ffffff",
  });
  const styles = renderStyles(document);
  assert.match(styles, /--prototype-content-text:#17201d/);
  assert.match(styles, /--prototype-surface-text:#ffffff/);
  assert.match(styles, /--prototype-text:var\(--prototype-content-text\)/);
});

test("renderer document codec matches Grid and Shell layout bounds", () => {
  const accepted = rendererDocument();
  const acceptedPage = firstPage(accepted);
  const acceptedRoot = acceptedPage.root;
  acceptedPage.viewport = { width: 320, height: 480 };
  acceptedRoot.layoutItem.width = { unit: "px", value: "4096" };
  acceptedRoot.layoutItem.grow = 12;
  acceptedRoot.layoutItem.shrink = 12;
  acceptedRoot.responsive = [
    {
      breakpoint: "sm",
      layoutItem: {
        width: { unit: "percent", value: "100" },
        maxWidth: { unit: "rem", value: "256" },
        grow: 12,
        shrink: 12,
      },
    },
  ];
  assert.equal(parseRendererDocument(accepted).pages[0]?.viewport.width, 320);

  const invalidCases: Array<{
    mutate: (document: StructuredPrototypeDocument) => void;
    message: RegExp;
  }> = [
    {
      mutate: (document) => {
        firstPage(document).root.layoutItem.width = { unit: "percent", value: "101" };
      },
      message: /must not exceed 100 for percent length/,
    },
    {
      mutate: (document) => {
        firstPage(document).root.layoutItem.width = { unit: "px", value: "4097" };
      },
      message: /must not exceed 4096 for px length/,
    },
    {
      mutate: (document) => {
        firstPage(document).root.layoutItem.width = { unit: "rem", value: "257" };
      },
      message: /must not exceed 256 for rem length/,
    },
    {
      mutate: (document) => {
        firstPage(document).root.layoutItem.grow = 13;
      },
      message: /grow must be between 0 and 12/,
    },
    {
      mutate: (document) => {
        firstPage(document).root.responsive = [
          { breakpoint: "sm", layoutItem: { grow: 1 } },
          { breakpoint: "md", layoutItem: { grow: 1 } },
          { breakpoint: "lg", layoutItem: { grow: 1 } },
          { breakpoint: "sm", layoutItem: { grow: 1 } },
        ];
      },
      message: /responsive must contain between 0 and 3 items/,
    },
    {
      mutate: (document) => {
        firstPage(document).root.responsive = [
          { breakpoint: "sm", layoutItem: { grow: 1 } },
          { breakpoint: "sm", layoutItem: { shrink: 1 } },
        ];
      },
      message: /responsive contains duplicate breakpoint/,
    },
    {
      mutate: (document) => {
        firstPage(document).root.responsive = [{ breakpoint: "sm", layoutItem: { grow: 13 } }];
      },
      message: /grow must be between 0 and 12/,
    },
    {
      mutate: (document) => {
        firstPage(document).viewport.width = 319;
      },
      message: /viewport\.width must be between 320 and 2560/,
    },
    {
      mutate: (document) => {
        firstPage(document).viewport.height = 2161;
      },
      message: /viewport\.height must be between 480 and 2160/,
    },
  ];

  for (const invalidCase of invalidCases) {
    const document = rendererDocument();
    invalidCase.mutate(document);
    assert.throws(() => parseRendererDocument(document), invalidCase.message);
  }
});
