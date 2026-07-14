import assert from "node:assert/strict";
import test from "node:test";

import { buildStructuredPrototypeInspectorBatch } from "../src/features/prototype/structured/StructuredPrototypeInspector";
import { createProcurementPrototypeDocument } from "../src/features/prototype/structured/procurementDocumentFixture";

test("Stack, Form, and Table nodes produce common visibility and layout edits", () => {
  const document = createProcurementPrototypeDocument();
  const nodes = [
    document.pages[0]?.root,
    document.pages[1]?.root.type === "Stack" ? document.pages[1].root.children[0] : null,
    document.pages[0]?.root.type === "Stack" ? document.pages[0].root.children[1] : null,
  ];

  for (const node of nodes) {
    assert.ok(node);
    const batch = buildStructuredPrototypeInspectorBatch(node, {
      content: "",
      buttonVariant: "primary",
      visibility: "hidden",
      grow: 2,
      alignSelf: "center",
    });
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

  const batch = buildStructuredPrototypeInspectorBatch(text, {
    content: "采购申请总览",
    buttonVariant: "primary",
    visibility: text.visibility,
    grow: 1,
    alignSelf: text.layoutItem.alignSelf,
  });
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
      content: "",
      buttonVariant: "primary",
      visibility: root.visibility,
      grow: root.layoutItem.grow,
      alignSelf: root.layoutItem.alignSelf,
    }),
    null,
  );
});
