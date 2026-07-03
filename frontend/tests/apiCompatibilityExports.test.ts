import test from "node:test";
import assert from "node:assert/strict";

import { getProjectResume, importProjectResumePdf, saveProjectResume } from "../src/lib/api";

test("monolithic api entrypoint preserves resume compatibility exports", () => {
  assert.equal(typeof getProjectResume, "function");
  assert.equal(typeof importProjectResumePdf, "function");
  assert.equal(typeof saveProjectResume, "function");
});
