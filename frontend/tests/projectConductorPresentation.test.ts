import test from "node:test";
import assert from "node:assert/strict";

import {
  nextProjectConductorVisibleCount,
  projectConductorHotEventBody,
  shouldCollapseProjectConductorText,
} from "../src/features/projects/projectConductorPresentation";

test("project conductor text collapses only after the configured threshold", () => {
  assert.equal(shouldCollapseProjectConductorText("12345", 5), false);
  assert.equal(shouldCollapseProjectConductorText("123456", 5), true);
});

test("project conductor memory reveal stays within the available item count", () => {
  assert.equal(nextProjectConductorVisibleCount(3, 10), 6);
  assert.equal(nextProjectConductorVisibleCount(9, 10), 10);
  assert.equal(nextProjectConductorVisibleCount(3, 4, 10), 4);
});

test("project conductor hot event body keeps role and content readable", () => {
  assert.equal(
    projectConductorHotEventBody({ role: "assistant", content: "Review completed." }),
    "assistant: Review completed.",
  );
  assert.equal(projectConductorHotEventBody({ role: "system" }), "system");
});
