import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { formatApiErrorDetail } from "../src/lib/api";
import { getDictionaryValue } from "../src/lib/i18n";

const SRC_ROOT = join(process.cwd(), "src");

function readSource(relativePath: string): string {
  return readFileSync(join(SRC_ROOT, relativePath), "utf-8");
}

test("formatApiErrorDetail renders FastAPI 422 array details", () => {
  const message = formatApiErrorDetail(
    [
      {
        type: "string_too_short",
        loc: ["body", "title"],
        msg: "String should have at least 3 characters",
      },
      {
        type: "missing",
        loc: ["body", "cwd"],
        msg: "Field required",
      },
    ],
    "HTTP 422",
  );

  assert.equal(
    message,
    "body.title: String should have at least 3 characters; body.cwd: Field required",
  );
});

test("workspace dialog enforces the backend title min length contract", () => {
  const source = readSource("features/projects/ProjectWorkspacesPage.tsx");

  assert.match(source, /trimmedTitleLength >= 3 && !saving/);
  assert.match(source, /showTitleMinLengthHint/);
  assert.match(source, /t\("workspace\.field\.titleMinLengthHint"\)/);
  assert.equal(getDictionaryValue("en-US", "workspace.field.titleMinLengthHint"), "At least 3 characters");
});
