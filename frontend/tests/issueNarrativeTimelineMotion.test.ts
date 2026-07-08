import test from "node:test";
import assert from "node:assert/strict";
import { readCompactSource as readSource } from "./sourceTestUtils";

test("issue narrative timeline marks active role work with dispatch motion", () => {
  const source = readSource("features/issues/components/IssueNarrativeTimeline.tsx");

  assert.match(
    source,
    /data-density=\{isActiveRole \? "issue-narrative-active-role" : "issue-narrative-role"\}/,
  );
  assert.match(source, /<AgentThinkingIndicator phase="dispatching" size=\{12\} \/>/);
  assert.match(source, /animate-shimmer-sweep/);
  assert.match(source, /motion-essential/);
  assert.doesNotMatch(source, /<Loader2 size=\{12\} className="text-brand animate-spin" \/>/);
});
