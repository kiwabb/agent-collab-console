import assert from "node:assert/strict";
import test from "node:test";

import {
  STRUCTURED_PROTOTYPE_FLOW_COORDINATE_LIMIT,
  findStructuredPrototypeFlowSourcePageId,
  normalizeStructuredPrototypeFlowNodePosition,
  projectStructuredPrototypeFlow,
  resolveStructuredPrototypePendingFlowConnection,
  resolveStructuredPrototypeDefaultFlowPosition,
} from "../src/features/prototype/structured/structuredPrototypeFlowProjection";
import {
  STRUCTURED_PROCUREMENT_IDS,
  createProcurementPrototypeDocument,
} from "./fixtures/procurementDocumentFixture";
import type { StructuredPrototypeDocument } from "../src/features/prototype/structured/types";
import { readCompactSource } from "./sourceTestUtils";

function flowDocument(): StructuredPrototypeDocument {
  return {
    ...createProcurementPrototypeDocument(),
    id: "11111111-1111-4111-8111-111111111111",
  };
}

test("flow projection maps nested trigger nodes to their owning pages", () => {
  const document = flowDocument();

  assert.equal(
    findStructuredPrototypeFlowSourcePageId(
      document,
      STRUCTURED_PROCUREMENT_IDS.nodes.submitRequest,
    ),
    STRUCTURED_PROCUREMENT_IDS.pages.create,
  );
  assert.equal(
    findStructuredPrototypeFlowSourcePageId(
      document,
      STRUCTURED_PROCUREMENT_IDS.nodes.requestTable,
    ),
    STRUCTURED_PROCUREMENT_IDS.pages.list,
  );
  assert.equal(findStructuredPrototypeFlowSourcePageId(document, "missing-node"), null);

  const projection = projectStructuredPrototypeFlow(document);
  const submitEdge = projection.edges.find(
    (edge) => edge.id === STRUCTURED_PROCUREMENT_IDS.flows.submit,
  );
  assert.deepEqual(submitEdge && { source: submitEdge.source, target: submitEdge.target }, {
    source: STRUCTURED_PROCUREMENT_IDS.pages.create,
    target: STRUCTURED_PROCUREMENT_IDS.pages.detail,
  });
  assert.equal(submitEdge?.data?.ruleId, STRUCTURED_PROCUREMENT_IDS.rules.submit);
  assert.equal(submitEdge?.focusable, true);
});

test("page connection resolves only source and target without mutating a document", () => {
  const document = flowDocument();
  const before = structuredClone(document);

  assert.deepEqual(
    resolveStructuredPrototypePendingFlowConnection({
      source: STRUCTURED_PROCUREMENT_IDS.pages.create,
      target: STRUCTURED_PROCUREMENT_IDS.pages.detail,
    }),
    {
      kind: "pendingConnection",
      sourcePageId: STRUCTURED_PROCUREMENT_IDS.pages.create,
      targetPageId: STRUCTURED_PROCUREMENT_IDS.pages.detail,
    },
  );
  assert.equal(
    resolveStructuredPrototypePendingFlowConnection({ source: null, target: "target" }),
    null,
  );
  assert.deepEqual(document, before);
});

test("flow projection uses a stable page grid and derives connection counts", () => {
  const document = flowDocument();
  const first = projectStructuredPrototypeFlow(document);
  const second = projectStructuredPrototypeFlow(structuredClone(document));

  assert.deepEqual(first, second);
  assert.deepEqual(
    first.nodes.map((node) => node.position),
    document.pages.map((_page, index) => resolveStructuredPrototypeDefaultFlowPosition(index)),
  );
  const detail = first.nodes.find((node) => node.id === STRUCTURED_PROCUREMENT_IDS.pages.detail);
  assert.ok(detail);
  assert.equal(detail.data.incomingCount, 3);
  assert.equal(detail.data.outgoingCount, 1);
});

test("saved flow layout positions override only their matching page nodes", () => {
  const document = flowDocument();
  document.runtime.flowLayout = {
    nodes: [
      {
        nodeId: STRUCTURED_PROCUREMENT_IDS.pages.create,
        x: 901,
        y: -117,
      },
    ],
  };

  const projection = projectStructuredPrototypeFlow(document);
  assert.deepEqual(
    projection.nodes.find((node) => node.id === STRUCTURED_PROCUREMENT_IDS.pages.create)?.position,
    { x: 901, y: -117 },
  );
  assert.deepEqual(
    projection.nodes.find((node) => node.id === STRUCTURED_PROCUREMENT_IDS.pages.list)?.position,
    resolveStructuredPrototypeDefaultFlowPosition(0),
  );
});

test("flow positions round and clamp through one canonical helper", () => {
  assert.deepEqual(normalizeStructuredPrototypeFlowNodePosition({ x: 10.49, y: -20.5 }), {
    x: 10,
    y: -20,
  });
  assert.deepEqual(
    normalizeStructuredPrototypeFlowNodePosition({
      x: STRUCTURED_PROTOTYPE_FLOW_COORDINATE_LIMIT + 100,
      y: -STRUCTURED_PROTOTYPE_FLOW_COORDINATE_LIMIT - 100,
    }),
    {
      x: STRUCTURED_PROTOTYPE_FLOW_COORDINATE_LIMIT,
      y: -STRUCTURED_PROTOTYPE_FLOW_COORDINATE_LIMIT,
    },
  );
  assert.throws(
    () => normalizeStructuredPrototypeFlowNodePosition({ x: Number.NaN, y: 0 }),
    /finite numbers/,
  );
});

test("flow projection rejects a flow without a navigate target", () => {
  const document = flowDocument();
  const sourceFlow = document.flows[0];
  assert.ok(sourceFlow);
  document.flows = [
    {
      ...sourceFlow,
      id: "00000000-0000-4000-8000-000000000099",
      toPageId: null,
    },
  ];

  assert.throws(() => projectStructuredPrototypeFlow(document), /has no navigate target page/);
});

test("Flow UI routes connection and edge selection intents without direct rule mutation", () => {
  const flow = readCompactSource("features/prototype/structured/StructuredPrototypeFlow.tsx");
  const connectStart = flow.indexOf("const handleConnect");
  const connectEnd = flow.indexOf("const handleNodeClick", connectStart);
  const connectSource = flow.slice(connectStart, connectEnd);

  assert.match(flow, /onConnect=\{handleConnect\}/);
  assert.match(connectSource, /resolveStructuredPrototypePendingFlowConnection\(connection\)/);
  assert.match(connectSource, /onConnectPages\(pending\)/);
  assert.doesNotMatch(connectSource, /applyCommands|addBehaviorRule|addEdge|onNodePositionChange/);
  assert.match(flow, /onRuleSelect\(edge\.data\.ruleId\)/);
  assert.match(flow, /deleteKeyCode=\{null\}/);
  assert.match(flow, /nodesConnectable=\{!disabled\}/);
  assert.match(flow, /edgesUpdatable=\{false\}/);
  assert.match(flow, /edgesFocusable/);
});

test("Studio keeps Flow selection separate and wires rule batches through the shared inspector", () => {
  const studio = readCompactSource(
    "features/prototype/structured/StructuredPrototypeStudioPage.tsx",
  );

  assert.match(studio, /const \[nodeSelection, setNodeSelection\]/);
  assert.match(studio, /const \[flowRuleSelection, setFlowRuleSelection\]/);
  assert.match(studio, /mode === "flow" \? selectFlowPage : handlePageSelect/);
  assert.match(studio, /<StructuredPrototypeRuleInspector/);
  assert.match(studio, /selection=\{flowInspectorSelection\}/);
  assert.match(studio, /onCreate=\{createFlowRule\}/);
  assert.match(studio, /onReplace=\{replaceFlowRule\}/);
  assert.match(studio, /onRemove=\{removeFlowRule\}/);
  assert.match(studio, /addBehaviorRuleBatch\(newRuleKey, definition\)/);
  assert.match(studio, /replaceBehaviorRuleBatch\(ruleId, definition\)/);
  assert.match(studio, /removeBehaviorRuleBatch\(ruleId\)/);
  assert.match(studio, /applyInspectorCommands\(batch\)/);
  assert.match(studio, /setFlowRuleMutation\(mutation\)/);
  assert.match(studio, /current === mutation/);
  assert.match(studio, /requestSettled: true/);
  assert.match(studio, /resolveStructuredPrototypeFlowRuleMutationOutcome/);
  assert.match(studio, /error=\{visibleError\}/);
  assert.match(studio, /mode === "design" && canvasInteraction === "edit"/);
});
