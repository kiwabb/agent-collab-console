import assert from "node:assert/strict";
import test from "node:test";

import {
  createPaletteNode,
  insertPaletteNodeBatch,
  moveNodeBatch,
} from "../src/features/prototype/structured/structuredPrototypeCommands";

test("all six palette types produce bounded structured nodes", () => {
  const types = ["Stack", "Form", "Text", "Input", "Button", "Table"] as const;
  for (const type of types) {
    const node = createPaletteNode(type, `new-${type.toLowerCase()}`, "form-1");
    assert.equal(node.type, type);
    assert.equal(node.visibility, "visible");
    assert.equal(node.layoutItem.width.unit, "auto");
  }
  const form = createPaletteNode("Form", "new-form", "form-1");
  assert.equal(form.type, "Form");
  assert.equal(form.children.length, 1);
  assert.equal(form.children[0]?.newNodeKey, "new-form-field");
});

test("palette insert and component move preserve explicit target position", () => {
  const text = createPaletteNode("Text", "new-text", "form-1");
  assert.deepEqual(insertPaletteNodeBatch("root", 2, text).commands[0], {
    kind: "insertNode",
    parent: { kind: "existing", nodeId: "root" },
    slot: null,
    index: 2,
    node: text,
  });
  assert.deepEqual(moveNodeBatch("node", "root", 1).commands[0], {
    kind: "moveNode",
    node: { kind: "existing", nodeId: "node" },
    targetParent: { kind: "existing", nodeId: "root" },
    targetSlot: null,
    targetIndex: 1,
  });
});
