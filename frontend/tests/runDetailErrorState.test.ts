import test from "node:test";
import assert from "node:assert/strict";

import { shouldShowTopErrorCard } from "../src/lib/runDetailErrorState";

test("shows top error card when task is not failed", () => {
  assert.equal(
    shouldShowTopErrorCard({ content: "Failed to persist artifacts: boom" }, "running", null),
    true,
  );
});

test("hides top error card when failed task result duplicates the error content", () => {
  const duplicated = "ProductManager 返回了无效的 PRD 格式\n\n错误类型: JSONDecodeError";

  assert.equal(shouldShowTopErrorCard({ content: duplicated }, "failed", duplicated), false);
});

test("hides top error card when one failed error message contains the other", () => {
  assert.equal(
    shouldShowTopErrorCard(
      { content: "Failed to persist artifacts: ProductManager 返回了无效的 PRD 格式" },
      "failed",
      "ProductManager 返回了无效的 PRD 格式",
    ),
    false,
  );
});

test("keeps top error card when failed task result differs from log error", () => {
  assert.equal(
    shouldShowTopErrorCard(
      { content: "workspace sync failed" },
      "failed",
      "ProductManager 返回了无效的 PRD 格式",
    ),
    true,
  );
});
