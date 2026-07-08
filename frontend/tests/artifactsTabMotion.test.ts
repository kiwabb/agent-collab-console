import test from "node:test";
import assert from "node:assert/strict";
import { readCompactSource as readSource } from "./sourceTestUtils";

test("artifacts tab refresh cta uses tool motion while syncing artifacts", () => {
  const source = readSource("features/issues/tabs/ArtifactsTab.tsx");

  assert.match(
    source,
    /import \{ AgentThinkingIndicator \} from "@\/components\/ui\/AgentThinkingIndicator";/,
  );
  assert.match(
    source,
    /data-density=\{isRefreshing \? "artifacts-tab-refresh-tool" : "artifacts-tab-refresh"\}/,
  );
  assert.match(source, /isRefreshing && "motion-essential/);
  assert.match(
    source,
    /isRefreshing \? \(?\s*<AgentThinkingIndicator phase="tool" size=\{11\} \/>/,
  );
  assert.match(source, /<RefreshCw size=\{11\}/);
  assert.doesNotMatch(
    source,
    /<RefreshCw\s+size=\{11\}\s+className=\{cn\("mr-1\.5", isRefreshing && "animate-spin"\)\}\s+\/>/,
  );
});
