import test from "node:test";
import assert from "node:assert/strict";
import { readCompactSource as readSource } from "./sourceTestUtils";

test("issue card live badge marks running issue work with dispatch motion", () => {
  const source = readSource("features/issues/IssueCard.tsx");

  assert.match(source, /data-density="issue-card-live-dispatch"/);
  assert.match(source, /<AgentThinkingIndicator phase="dispatching" size=\{12\} \/>/);
  assert.match(source, /animate-shimmer-sweep/);
  assert.match(source, /motion-essential/);
  assert.doesNotMatch(source, /bg-brand animate-pulse/);
});
