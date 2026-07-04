import test from "node:test";
import assert from "node:assert/strict";

import { describeScriptTaskTerminalStatus } from "../src/features/projects/scriptTaskStatus";

test("describeScriptTaskTerminalStatus treats done/completed as successful terminal states", () => {
  assert.deepEqual(describeScriptTaskTerminalStatus("done"), {
    terminal: true,
    success: true,
  });
  assert.deepEqual(describeScriptTaskTerminalStatus("Completed"), {
    terminal: true,
    success: true,
  });
});

test("describeScriptTaskTerminalStatus treats failed/cancelled/killed as unsuccessful terminal states", () => {
  for (const status of ["failed", "Cancelled", "KILLED"]) {
    assert.deepEqual(describeScriptTaskTerminalStatus(status), {
      terminal: true,
      success: false,
    });
  }
});

test("describeScriptTaskTerminalStatus treats active or missing states as non-terminal", () => {
  for (const status of ["pending", "running", "responding", "", null, undefined]) {
    assert.deepEqual(describeScriptTaskTerminalStatus(status), {
      terminal: false,
      success: false,
    });
  }
});
