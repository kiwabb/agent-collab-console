import test from "node:test";
import assert from "node:assert/strict";
import { readCompactSource as readSource } from "./sourceTestUtils";

test("issue detail status badge marks live work with dispatch motion", () => {
  const source = readSource("features/issues/IssueDetailPanel.tsx");

  assert.match(
    source,
    /data-density=\{isLive \? "issue-detail-status-live" : "issue-detail-status"\}/,
  );
  assert.match(source, /<AgentThinkingIndicator phase="dispatching" size=\{12\} \/>/);
  assert.match(source, /animate-shimmer-sweep/);
  assert.match(source, /motion-essential/);
  assert.doesNotMatch(source, /bg-brand animate-pulse/);
});
