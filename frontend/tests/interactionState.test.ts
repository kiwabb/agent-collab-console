import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  deriveAttentionItems,
  deriveIssueNextAction,
  deriveRunRecoveryActions,
} from "../src/features/workbench/interaction/interactionState";

describe("interactionState", () => {
  it("prioritizes approvals, failures, and running work in attention items", () => {
    const items = deriveAttentionItems({
      issues: [
        {
          id: "i1",
          title: "Needs review",
          status: "awaiting_approval",
          current_phase: "architecture",
          updated_at: "2026-05-22T08:00:00Z",
        } as any,
        {
          id: "i2",
          title: "Broken run",
          status: "failed",
          current_phase: "development",
          updated_at: "2026-05-22T08:01:00Z",
        } as any,
        {
          id: "i3",
          title: "Running",
          status: "in_progress",
          current_phase: "testing",
          updated_at: "2026-05-22T08:02:00Z",
        } as any,
      ],
      tasks: [],
      processes: [],
      approvals: [],
    });

    assert.deepEqual(items.map((item) => item.kind), [
      "approval",
      "failure",
      "running",
    ]);
    assert.equal(items[0].href, "/issues/i1");
  });

  it("explains why issue next action is blocked by active task", () => {
    const action = deriveIssueNextAction({
      issue: {
        id: "i1",
        status: "open",
        current_phase: "requirements",
        title: "Do it",
      } as any,
      tasks: [
        {
          id: "t1",
          issue_id: "i1",
          role: "product_manager",
          status: "running",
        } as any,
      ],
      artifacts: [],
    });

    assert.equal(action.enabled, false);
    assert.match(action.disabledReason ?? "", /running/i);
  });

  it("offers rerun and logs recovery for failed processes", () => {
    const actions = deriveRunRecoveryActions({
      task: { id: "t1", status: "failed", executor: "codex" } as any,
      process: { id: "p1", task_id: "t1", status: "failed" } as any,
    });

    assert.deepEqual(actions.map((action) => action.id), [
      "open_logs",
      "rerun_same",
      "change_executor",
    ]);
  });
});
