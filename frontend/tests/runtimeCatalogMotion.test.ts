import assert from "node:assert/strict";
import test from "node:test";
import { readCompactSource as readSource } from "./sourceTestUtils";

test("runtime catalog executor test cta uses tool motion while probing", () => {
  const source = readSource("components/runtime/RuntimeCatalogEditor.tsx");

  assert.match(
    source,
    /import \{ AgentThinkingIndicator \} from "@\/components\/ui\/AgentThinkingIndicator";/,
  );
  assert.match(
    source,
    /data-density=\{testing \? "runtime-catalog-test-tool" : "runtime-catalog-test"\}/,
  );
  assert.match(source, /testing && "motion-essential"/);
  assert.match(source, /testing \? \(\s*<AgentThinkingIndicator phase="tool" size=\{12\} \/>/);
  assert.doesNotMatch(source, /<Loader2 className="h-3 w-3 animate-spin" \/>/);
});
