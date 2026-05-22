import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

test("CommandPalette exposes action-oriented rows", () => {
  const source = fs.readFileSync(
    new URL(
      "../src/features/workbench/components/CommandPalette.tsx",
      import.meta.url,
    ),
    "utf8",
  );

  assert.match(source, /actionLabel/);
  assert.match(source, /review/i);
  assert.match(source, /rerun/i);
  assert.match(source, /Search in Knowledge|searchInKnowledge/);
});
