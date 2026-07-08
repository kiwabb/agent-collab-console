import assert from "node:assert/strict";

export function at<T>(items: readonly T[], index: number, label = "item"): T {
  const item = items[index];
  assert.ok(item, `Expected ${label} at index ${index}`);
  return item;
}
