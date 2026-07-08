import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { parseUnifiedDiff } from "../src/lib/diffParser";
import { at } from "./testAssertions";

const MODIFIED_DIFF = `diff --git a/src/components/Foo.tsx b/src/components/Foo.tsx
index abc123..def456 100644
--- a/src/components/Foo.tsx
+++ b/src/components/Foo.tsx
@@ -1,5 +1,6 @@
 import React from "react";
+import { useState } from "react";

 export function Foo() {
-  return <div>Hello</div>;
+  return <div>World</div>;
 }
`;

const UNTRACKED_DIFF = `diff --git a/HelloWorld.tsx b/HelloWorld.tsx
new file mode 100644
--- /dev/null
+++ b/HelloWorld.tsx
@@ -0,0 +1,3 @@
+export function HelloWorld() {
+  return <div>Hello</div>;
+}
`;

const DELETED_DIFF = `diff --git a/old.ts b/old.ts
deleted file mode 100644
--- a/old.ts
+++ /dev/null
@@ -1,2 +0,0 @@
-export const x = 1;
-export const y = 2;
`;

const BINARY_DIFF = `diff --git a/logo.png b/logo.png
new file mode 100644
Binary files /dev/null and b/logo.png differ
`;

const MULTI_FILE = MODIFIED_DIFF + UNTRACKED_DIFF + DELETED_DIFF + BINARY_DIFF;

describe("parseUnifiedDiff", () => {
  it("returns empty array for empty string", () => {
    assert.deepEqual(parseUnifiedDiff(""), []);
    assert.deepEqual(parseUnifiedDiff("   "), []);
  });

  it("parses a modified file correctly", () => {
    const files = parseUnifiedDiff(MODIFIED_DIFF);
    assert.equal(files.length, 1);
    const f = at(files, 0, "diff file");
    assert.equal(f.oldPath, "src/components/Foo.tsx");
    assert.equal(f.newPath, "src/components/Foo.tsx");
    assert.equal(f.isNew, false);
    assert.equal(f.isDeleted, false);
    assert.equal(f.isBinary, false);
    assert.equal(f.additions, 2);
    assert.equal(f.deletions, 1);
    assert.ok(f.lines.some((l) => l.type === "hunk"));
    assert.ok(f.lines.some((l) => l.type === "add"));
    assert.ok(f.lines.some((l) => l.type === "del"));
  });

  it("parses untracked (synthesized new file) patch", () => {
    const files = parseUnifiedDiff(UNTRACKED_DIFF);
    assert.equal(files.length, 1);
    const f = at(files, 0, "diff file");
    assert.equal(f.isNew, true);
    assert.equal(f.isDeleted, false);
    assert.equal(f.additions, 3);
    assert.equal(f.deletions, 0);
  });

  it("parses deleted file", () => {
    const files = parseUnifiedDiff(DELETED_DIFF);
    assert.equal(files.length, 1);
    const f = at(files, 0, "diff file");
    assert.equal(f.isDeleted, true);
    assert.equal(f.isNew, false);
    assert.equal(f.deletions, 2);
    assert.equal(f.additions, 0);
  });

  it("parses binary file", () => {
    const files = parseUnifiedDiff(BINARY_DIFF);
    assert.equal(files.length, 1);
    const f = at(files, 0, "diff file");
    assert.equal(f.isBinary, true);
    assert.equal(f.lines.length, 0);
  });

  it("splits multi-file diff correctly", () => {
    const files = parseUnifiedDiff(MULTI_FILE);
    assert.equal(files.length, 4);
    assert.equal(at(files, 0, "diff file").newPath, "src/components/Foo.tsx");
    assert.equal(at(files, 1, "diff file").isNew, true);
    assert.equal(at(files, 2, "diff file").isDeleted, true);
    assert.equal(at(files, 3, "diff file").isBinary, true);
  });

  it("rawPatch starts with diff --git line", () => {
    const files = parseUnifiedDiff(MODIFIED_DIFF);
    assert.ok(at(files, 0, "diff file").rawPatch.startsWith("diff --git "));
  });

  it("tracks old/new line numbers on context lines", () => {
    const files = parseUnifiedDiff(MODIFIED_DIFF);
    const contextLines = at(files, 0, "diff file").lines.filter((l) => l.type === "context");
    assert.ok(contextLines.length > 0);
    for (const l of contextLines) {
      assert.notEqual(l.oldLine, null);
      assert.notEqual(l.newLine, null);
    }
  });
});
