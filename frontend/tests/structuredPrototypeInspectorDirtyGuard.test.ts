import assert from "node:assert/strict";
import test from "node:test";

import { readCompactSource as readSource } from "./sourceTestUtils";
import {
  buildStructuredPrototypeInspectorBatch,
  type StructuredPrototypeInspectorDraft,
} from "../src/features/prototype/structured/StructuredPrototypeInspector";
import { resolveStructuredPrototypeFreeformGrids } from "../src/features/prototype/structured/structuredPrototypeFreeformGrids";
import { createProcurementPrototypeDocument } from "./fixtures/procurementDocumentFixture";
import type { StructuredPrototypeNode } from "../src/features/prototype/structured/types";

function findTextNode(document: ReturnType<typeof createProcurementPrototypeDocument>): StructuredPrototypeNode {
  for (const page of document.pages) {
    const stack: StructuredPrototypeNode[] = [page.root];
    while (stack.length > 0) {
      const node = stack.pop()!;
      if (node.type === "Text") return node;
      if ("children" in node) {
        for (const child of node.children) stack.push(child as StructuredPrototypeNode);
      }
    }
  }
  throw new Error("no Text node found in procurement fixture");
}

function cleanDraftFor(node: StructuredPrototypeNode): StructuredPrototypeInspectorDraft {
  return {
    content: node.type === "Text" ? node.content : "",
    buttonVariant: node.type === "Button" ? node.variant : "primary",
    visibility: node.visibility,
    width: node.layoutItem.width,
    minWidth: node.layoutItem.minWidth,
    maxWidth: node.layoutItem.maxWidth,
    height: node.layoutItem.height,
    minHeight: node.layoutItem.minHeight,
    maxHeight: node.layoutItem.maxHeight,
    grow: node.layoutItem.grow,
    shrink: node.layoutItem.shrink,
    alignSelf: node.layoutItem.alignSelf,
    position: node.layoutItem.position ?? null,
    containerLayout:
      node.type === "Stack"
        ? {
            kind: "stack",
            direction: node.direction,
            gap: node.gap,
            align: node.align,
            justify: node.justify,
            padding: node.padding,
          }
        : node.type === "Grid"
          ? {
              kind: "grid",
              columns: node.columns,
              gap: node.gap,
              padding: node.padding,
              columnOverrides: node.columnOverrides,
            }
          : node.type === "Form"
            ? { kind: "form", gap: node.gap, padding: node.padding }
            : null,
    freeformGrids:
      node.type === "Freeform" ? [...resolveStructuredPrototypeFreeformGrids(node)] : [],
    responsive: node.responsive,
    tableColumns: node.type === "Table" ? node.columns : [],
    tableRows: node.type === "Table" ? node.rows : [],
  };
}

test("dirty guard i18n keys exist in en-US", () => {
  const en = readSource("lib/i18n/en-US.ts");
  assert.match(en, /"prototype\.structured\.dirtyGuard\.title":\s*"Unapplied edits"/);
  assert.match(
    en,
    /"prototype\.structured\.dirtyGuard\.description":\s*"Switching will discard your unapplied edits\. Continue\?"/,
  );
  assert.match(en, /"prototype\.structured\.dirtyGuard\.confirm":\s*"Discard and continue"/);
  assert.match(en, /"prototype\.structured\.dirtyGuard\.cancel":\s*"Cancel"/);
});

test("dirty guard i18n keys exist in zh-CN", () => {
  const zh = readSource("lib/i18n/zh-CN.ts");
  assert.match(zh, /"prototype\.structured\.dirtyGuard\.title":\s*"未应用的编辑"/);
  assert.match(
    zh,
    /"prototype\.structured\.dirtyGuard\.description":\s*"切换将丢失当前未应用的编辑，是否继续？"/,
  );
  assert.match(zh, /"prototype\.structured\.dirtyGuard\.confirm":\s*"丢弃并继续"/);
  assert.match(zh, /"prototype\.structured\.dirtyGuard\.cancel":\s*"取消"/);
});

test("dirty predicate is false when draft matches the node", () => {
  const document = createProcurementPrototypeDocument();
  const node = findTextNode(document);
  assert.equal(buildStructuredPrototypeInspectorBatch(node, cleanDraftFor(node)), null);
});

test("dirty predicate is true after a content edit", () => {
  const document = createProcurementPrototypeDocument();
  const node = findTextNode(document);
  const dirty = cleanDraftFor(node);
  dirty.content = `${dirty.content}-edited`;
  assert.notEqual(buildStructuredPrototypeInspectorBatch(node, dirty), null);
});

test("dirty predicate is true after a visibility edit", () => {
  const document = createProcurementPrototypeDocument();
  const node = findTextNode(document);
  const dirty = cleanDraftFor(node);
  dirty.visibility = dirty.visibility === "visible" ? "hidden" : "visible";
  assert.notEqual(buildStructuredPrototypeInspectorBatch(node, dirty), null);
});

test("dirty predicate is true after a layout edit and false after revert", () => {
  const document = createProcurementPrototypeDocument();
  const node = findTextNode(document);
  const dirty = cleanDraftFor(node);
  const original = dirty.width;
  dirty.width = { ...original, value: "999" };
  assert.notEqual(buildStructuredPrototypeInspectorBatch(node, dirty), null);
  dirty.width = original;
  assert.equal(buildStructuredPrototypeInspectorBatch(node, dirty), null);
});

test("inspector exposes onDirtyChange and reports dirty state via effect", () => {
  const inspector = readSource(
    "features/prototype/structured/StructuredPrototypeInspector.tsx",
  );
  assert.match(inspector, /onDirtyChange\?:\s*\(\(dirty:\s*boolean\)\s*=>\s*void\)\s*\|\s*undefined/);
  assert.match(inspector, /onDirtyChange,/);
  assert.match(inspector, /buildStructuredPrototypeInspectorBatch\(node,\s*inspectorDraft\)\s*!==\s*null/);
  assert.match(inspector, /onDirtyChange\?\.\(isDirty\)/);
});

test("studio page wires inspector dirty state and resets on node/document change", () => {
  const studio = readSource(
    "features/prototype/structured/StructuredPrototypeStudioPage.tsx",
  );
  assert.match(studio, /const \[inspectorDirty,\s*setInspectorDirty\]/);
  assert.match(studio, /onDirtyChange=\{setInspectorDirty\}/);
  assert.match(studio, /setInspectorDirty\(false\)/);
});

test("studio page guards layer switch, page switch, and ai apply when dirty", () => {
  const studio = readSource(
    "features/prototype/structured/StructuredPrototypeStudioPage.tsx",
  );
  assert.match(studio, /setPendingDirtyDiscard\(\{\s*kind:\s*"layer"/);
  assert.match(studio, /setPendingDirtyDiscard\(\{\s*kind:\s*"page"/);
  assert.match(studio, /setPendingDirtyDiscard\(\{\s*kind:\s*"ai"\s*\}\)/);
});

test("studio page renders the dirty guard ConfirmDialog with warning variant", () => {
  const studio = readSource(
    "features/prototype/structured/StructuredPrototypeStudioPage.tsx",
  );
  assert.match(studio, /open=\{pendingDirtyDiscard\s*!==\s*null\}/);
  assert.match(studio, /prototype\.structured\.dirtyGuard\.title/);
  assert.match(studio, /prototype\.structured\.dirtyGuard\.description/);
  assert.match(studio, /prototype\.structured\.dirtyGuard\.confirm/);
  assert.match(studio, /prototype\.structured\.dirtyGuard\.cancel/);
  assert.match(studio, /onConfirm=\{confirmDirtyDiscard\}/);
  assert.match(studio, /variant="warning"/);
});

test("ai panel routes the Apply button through the studio-owned gate", () => {
  const panel = readSource(
    "features/prototype/structured/StructuredPrototypeAiPanel.tsx",
  );
  assert.match(panel, /onRequireApply\?:\s*\(\(\)\s*=>\s*void\)\s*\|\s*undefined/);
  assert.match(
    panel,
    /registerApplyTrigger\?:\s*\(\(trigger:\s*\(\)\s*=>\s*void\)\s*=>\s*void\)\s*\|\s*undefined/,
  );
  assert.match(panel, /registerApplyTrigger\?\.\(applyAiProposal\)/);
  assert.match(panel, /if\s*\(onRequireApply\)\s*onRequireApply\(\)/);
});
