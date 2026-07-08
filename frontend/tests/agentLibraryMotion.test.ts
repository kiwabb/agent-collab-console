import test from "node:test";
import assert from "node:assert/strict";
import { readCompactSource as readSource } from "./sourceTestUtils";

test("agent library save cta uses tool motion while persisting an agent", () => {
  const source = readSource("features/agents/AgentLibraryPage.tsx");

  assert.match(
    source,
    /import \{ AgentThinkingIndicator \} from "@\/components\/ui\/AgentThinkingIndicator";/,
  );
  assert.match(
    source,
    /data-density=\{saving \? "agent-library-save-tool" : "agent-library-save"\}/,
  );
  assert.match(source, /saving && "motion-essential"/);
  assert.match(
    source,
    /<AgentThinkingIndicator phase="tool" size=\{12\} \/> \{t\("agents\.saving"\)\}/,
  );
  assert.doesNotMatch(
    source,
    /<Loader2 size=\{12\} className="animate-spin" \/> \{t\("agents\.saving"\)\}/,
  );
  assert.doesNotMatch(source, /\bLoader2\b/);
});
