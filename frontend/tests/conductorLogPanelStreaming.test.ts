import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { getDictionaryValue } from "../src/lib/i18n";

const SRC_ROOT = join(process.cwd(), "src");

function readSource(relativePath: string): string {
  return readFileSync(join(SRC_ROOT, relativePath), "utf-8");
}

test("ConductorLogPanel subscribes to streaming delta and phase/detail state", () => {
  const source = readSource("features/workflow/ConductorLogPanel.tsx");

  assert.match(source, /typeIn\("conductor_turn_delta"\)/);
  assert.match(source, /streamingBuffers/);
  assert.match(source, /turn\.kind === "llm_response"/);
  assert.match(source, /conductorState\?\.phase/);
  assert.match(source, /conductorState\?\.detail/);
  assert.match(source, /awaiting_subagent/);
});

test("Conductor streaming types expose phase/detail and llm_response", () => {
  const apiSource = readSource("lib/api.ts");
  const contextSource = readSource("contexts/ExecutionProcessesContext.tsx");

  assert.match(apiSource, /kind: "llm_request" \| "llm_response"/);
  assert.match(apiSource, /phase\?: string \| null;/);
  assert.match(apiSource, /detail\?: string \| null;/);
  assert.match(contextSource, /"conductor_turn_delta"/);
  assert.match(contextSource, /phase\?: string \| null;/);
  assert.match(contextSource, /detail\?: string \| null;/);
});

test("Conductor response labels are available in both locales", () => {
  assert.equal(getDictionaryValue("zh-CN", "conductor.turn.response"), "响应");
  assert.equal(getDictionaryValue("en-US", "conductor.turn.response"), "Response");
  assert.equal(getDictionaryValue("en-US", "conductor.turnSummary.llmResponse"), "The LLM response ended with {stopReason}.");
});
