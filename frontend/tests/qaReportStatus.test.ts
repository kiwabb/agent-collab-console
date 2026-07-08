import test from "node:test";
import assert from "node:assert/strict";

import { isQaReportStatus, readQaReportStatus } from "../src/features/workbench/qaReportStatus";

test("isQaReportStatus narrows known QA report statuses", () => {
  assert.equal(isQaReportStatus("passed"), true);
  assert.equal(isQaReportStatus("failed"), true);
  assert.equal(isQaReportStatus("blocked"), true);
  assert.equal(isQaReportStatus("needs_follow_up"), true);
  assert.equal(isQaReportStatus("unknown"), false);
  assert.equal(isQaReportStatus(null), false);
});

test("readQaReportStatus parses qa_plan artifact through a literal guard", () => {
  assert.equal(
    readQaReportStatus([
      { name: "architect/system_design.json", content: "{}" },
      { name: "qa/qa_plan.json", content: '{"status":"blocked"}' },
    ]),
    "blocked",
  );
  assert.equal(
    readQaReportStatus([{ name: "qa/qa_plan.json", content: '{"status":"oops"}' }]),
    null,
  );
  assert.equal(readQaReportStatus([{ name: "qa/qa_plan.json", content: "{bad" }]), null);
  assert.equal(readQaReportStatus([{ name: "qa/qa_plan.json", content: null }]), null);
});
