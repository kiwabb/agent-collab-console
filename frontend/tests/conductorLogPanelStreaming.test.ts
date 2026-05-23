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
  assert.match(source, /typeIn\("conductor_state_violation"\)/);
  assert.match(source, /streamingBuffers/);
  assert.match(source, /turn\.kind === "llm_response"/);
  assert.match(source, /conductorState\?\.phase/);
  assert.match(source, /conductorState\?\.detail/);
  assert.match(source, /awaiting_subagent/);
  assert.match(source, /getConductorStateLog/);
  assert.match(source, /getConductorPhaseEstimates/);
  assert.match(source, /AnimatePresence/);
  assert.match(source, /slowerThanP95/);
});

test("Conductor streaming types expose phase/detail and llm_response", () => {
  const apiSource = readSource("lib/api.ts");
  const contextSource = readSource("contexts/ExecutionProcessesContext.tsx");

  assert.match(apiSource, /kind: "llm_request" \| "llm_response"/);
  assert.match(apiSource, /export interface ConductorStateLogEntry/);
  assert.match(apiSource, /export interface ConductorPhaseEstimate/);
  assert.match(apiSource, /phase\?: string \| null;/);
  assert.match(apiSource, /detail\?: string \| null;/);
  assert.match(contextSource, /"conductor_turn_delta"/);
  assert.match(contextSource, /"conductor_state_violation"/);
  assert.match(contextSource, /phase\?: string \| null;/);
  assert.match(contextSource, /detail\?: string \| null;/);
});

test("Conductor response labels are available in both locales", () => {
  assert.equal(getDictionaryValue("zh-CN", "conductor.turn.response"), "响应");
  assert.equal(getDictionaryValue("en-US", "conductor.turn.response"), "Response");
  assert.equal(getDictionaryValue("en-US", "conductor.turnSummary.llmResponse"), "The LLM response ended with {stopReason}.");
  assert.equal(getDictionaryValue("zh-CN", "conductor.toastStateViolation"), "Conductor 非法状态跳变");
  assert.equal(getDictionaryValue("en-US", "conductor.panel.timeline"), "Phase Timeline");
});

test("issue command center phase hook listens for conductor state violation toast events", () => {
  const source = readSource("features/issues/hooks/useConductorPhase.ts");

  assert.match(source, /typeIn\("conductor_status", "conductor_state_violation", "conductor_failed"\)/);
  assert.match(source, /event\.type === "conductor_state_violation"/);
  assert.match(source, /conductor\.toastStateViolation/);
  assert.match(source, /conductor\.toastStateViolationMessage/);
});
