import assert from "node:assert/strict";
import test from "node:test";

import {
  deriveProcurementRuntimeBindings,
  findStructuredPrototypeNode,
  runtimeEntityFieldText,
  runtimeNodeRows,
  runtimeNodeText,
  runtimeNodeVisible,
} from "../src/features/prototype/structured/structuredPrototypeDerived";
import { createProcurementPrototypeDocument } from "../src/features/prototype/structured/procurementDocumentFixture";

test("structured prototype node lookup traverses nested form children", () => {
  const document = createProcurementPrototypeDocument();
  const page = document.pages[1];
  assert.ok(page);
  const input = findStructuredPrototypeNode(page.root, "d1dced07-9e49-52f8-9d50-d0d16aef82f8");
  assert.equal(input?.type, "Input");
  assert.equal(input?.name, "申请事项输入框");
});

test("procurement runtime bindings come from semantic keys and document structure", () => {
  const document = createProcurementPrototypeDocument();
  const bindings = deriveProcurementRuntimeBindings({
    ...document,
    id: "document-1",
  });

  assert.ok(bindings);
  assert.equal(bindings.scenarioId, document.runtime.scenarios[0]?.id);
  assert.equal(bindings.submitNodeId, document.runtime.rules[0]?.trigger.nodeId);
  assert.equal(bindings.requestTableNodeId, document.runtime.rules[1]?.trigger.nodeId);
  assert.equal(bindings.approveNodeId, document.runtime.rules[2]?.trigger.nodeId);
  assert.notEqual(bindings.titleInputNodeId, bindings.amountInputNodeId);
});

test("procurement runtime bindings fail closed when the semantic contract is missing", () => {
  const document = createProcurementPrototypeDocument();
  assert.equal(
    deriveProcurementRuntimeBindings({
      ...document,
      id: "document-1",
      runtime: {
        ...document.runtime,
        scenarios: document.runtime.scenarios.map((scenario) => ({
          ...scenario,
          key: "unsupported-scenario",
        })),
      },
    }),
    null,
  );
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
});
