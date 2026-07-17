import assert from "node:assert/strict";
import test from "node:test";

import {
  createStructuredPrototypeEmptySelection,
  normalizeStructuredPrototypeSelectionRect,
  resolveStructuredPrototypeMarqueeNodeIds,
  resolveStructuredPrototypeNodeSelection,
  structuredPrototypeMarqueePassedActivationThreshold,
  structuredPrototypeSelectionRectContains,
  structuredPrototypeSelectionRectsIntersect,
  toggleStructuredPrototypeNodeSelection,
  type StructuredPrototypeMarqueeCandidate,
} from "../src/features/prototype/structured/structuredPrototypeSelection";
import {
  createProcurementPrototypeDocument,
  STRUCTURED_PROCUREMENT_IDS,
} from "./fixtures/procurementDocumentFixture";

const candidates: StructuredPrototypeMarqueeCandidate[] = [
  {
    nodeId: "container",
    ancestorNodeIds: ["root"],
    kind: "container",
    rect: { top: 0, right: 100, bottom: 100, left: 0, width: 100, height: 100 },
  },
  {
    nodeId: "child",
    ancestorNodeIds: ["root", "container"],
    kind: "leaf",
    rect: { top: 10, right: 30, bottom: 30, left: 10, width: 20, height: 20 },
  },
  {
    nodeId: "sibling",
    ancestorNodeIds: ["root"],
    kind: "leaf",
    rect: { top: 120, right: 150, bottom: 150, left: 120, width: 30, height: 30 },
  },
];

test("marquee geometry normalizes reverse drags and distinguishes overlap from containment", () => {
  const rect = normalizeStructuredPrototypeSelectionRect({ x: 40, y: 30 }, { x: 10, y: 5 });
  assert.deepEqual(rect, {
    top: 5,
    right: 40,
    bottom: 30,
    left: 10,
    width: 30,
    height: 25,
  });
  assert.equal(
    structuredPrototypeSelectionRectsIntersect(rect, {
      top: 29,
      right: 80,
      bottom: 40,
      left: 39,
      width: 41,
      height: 11,
    }),
    true,
  );
  assert.equal(
    structuredPrototypeSelectionRectContains(rect, {
      top: 6,
      right: 39,
      bottom: 29,
      left: 11,
      width: 28,
      height: 23,
    }),
    true,
  );
  assert.equal(structuredPrototypeMarqueePassedActivationThreshold(0, 0, 3, 2), false);
  assert.equal(structuredPrototypeMarqueePassedActivationThreshold(0, 0, 4, 0), true);
});

test("marquee overlaps leaves, fully contains containers, and removes nested selection loops", () => {
  assert.deepEqual(
    resolveStructuredPrototypeMarqueeNodeIds(candidates, {
      top: 5,
      right: 35,
      bottom: 35,
      left: 5,
      width: 30,
      height: 30,
    }),
    ["child"],
  );
  assert.deepEqual(
    resolveStructuredPrototypeMarqueeNodeIds(candidates, {
      top: -1,
      right: 101,
      bottom: 101,
      left: -1,
      width: 102,
      height: 102,
    }),
    ["container"],
  );
});

test("document selection excludes the root, keeps outermost nodes, and shift toggles deterministically", () => {
  const document = createProcurementPrototypeDocument();
  const createPage = document.pages.find(
    (page) => page.id === STRUCTURED_PROCUREMENT_IDS.pages.create,
  );
  assert.ok(createPage);
  const normalized = resolveStructuredPrototypeNodeSelection(
    createPage.root,
    [
      createPage.root.id,
      STRUCTURED_PROCUREMENT_IDS.nodes.createForm,
      STRUCTURED_PROCUREMENT_IDS.nodes.titleInput,
    ],
    STRUCTURED_PROCUREMENT_IDS.nodes.titleInput,
  );
  assert.deepEqual(normalized, {
    nodeIds: [STRUCTURED_PROCUREMENT_IDS.nodes.createForm],
    primaryNodeId: STRUCTURED_PROCUREMENT_IDS.nodes.createForm,
  });

  const selected = toggleStructuredPrototypeNodeSelection(
    createPage.root,
    createStructuredPrototypeEmptySelection(),
    STRUCTURED_PROCUREMENT_IDS.nodes.titleInput,
  );
  assert.deepEqual(selected, {
    nodeIds: [STRUCTURED_PROCUREMENT_IDS.nodes.titleInput],
    primaryNodeId: STRUCTURED_PROCUREMENT_IDS.nodes.titleInput,
  });
  assert.deepEqual(
    toggleStructuredPrototypeNodeSelection(
      createPage.root,
      selected,
      STRUCTURED_PROCUREMENT_IDS.nodes.titleInput,
    ),
    createStructuredPrototypeEmptySelection(),
  );
});
