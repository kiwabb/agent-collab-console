import test from "node:test";
import assert from "node:assert/strict";
import { readCompactSource as readSource } from "./sourceTestUtils";

import { getDictionaryValue } from "../src/lib/i18n";

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

test("ConductorLogPanel marks active phase and pending dispatches with scheduling motion", () => {
  const source = readSource("features/workflow/ConductorLogPanel.tsx");

  assert.match(source, /isConductorLogScheduling/);
  assert.match(source, /conductorLogMotionPhase/);
  assert.match(
    source,
    /conductorLogMotionPhase = conductorPhase \?\? \(conductorStatus === "running" \? "dispatching" : "idle"\)/,
  );
  assert.match(
    source,
    /data-density=\{isConductorLogScheduling \? "conductor-log-active-phase" : "conductor-log-live-phase"\}/,
  );
  assert.match(source, /data-density="conductor-phase-timeline"/);
  assert.match(
    source,
    /data-density=\{node\.isCurrent \? "conductor-phase-current-node" : "conductor-phase-node"\}/,
  );
  assert.match(source, /data-density="conductor-pending-dispatches"/);
  assert.match(source, /animate-shimmer-sweep/);
  assert.match(source, /phase=\{conductorLogMotionPhase\}/);
  assert.match(source, /phase=\{node\.phase\}/);
  assert.match(source, /phase="dispatching"/);
  assert.match(source, /motion-essential/);
});

test("ConductorLogPanel send button uses thinking motion while sending", () => {
  const source = readSource("features/workflow/ConductorLogPanel.tsx");

  assert.match(
    source,
    /data-density=\{sending \? "conductor-message-send-thinking" : "conductor-message-send"\}/,
  );
  assert.match(source, /sending && "motion-essential"/);
  assert.match(source, /<AgentThinkingIndicator phase="thinking" size=\{14\}/);
  assert.doesNotMatch(
    source,
    /sending \?\s*\(\s*<Loader2 className="mr-1\.5 h-3\.5 w-3\.5 animate-spin"/,
  );
});

test("ConductorLogPanel pause resume control uses thinking motion while busy", () => {
  const source = readSource("features/workflow/ConductorLogPanel.tsx");

  assert.match(
    source,
    /data-density=\{statusBusy \? "conductor-pause-resume-thinking" : "conductor-pause-resume"\}/,
  );
  assert.match(source, /statusBusy && "motion-essential"/);
  assert.match(source, /statusBusy \?\s*\(\s*<AgentThinkingIndicator phase="thinking" size=\{14\}/);
  assert.doesNotMatch(
    source,
    /statusBusy \?\s*\(\s*<Loader2 className="mr-1\.5 h-3\.5 w-3\.5 animate-spin"/,
  );
});

test("ConductorLogPanel loading state uses thinking motion", () => {
  const source = readSource("features/workflow/ConductorLogPanel.tsx");

  assert.match(source, /data-density="conductor-panel-thinking-loading"/);
  assert.match(
    source,
    /className="motion-essential flex items-center justify-center gap-2 py-6 text-sm font-semibold text-text-muted"/,
  );
  assert.match(source, /<AgentThinkingIndicator phase="thinking" size=\{14\} \/>/);
});

test("Conductor streaming types expose phase/detail and llm_response", () => {
  // Phase 4: api.ts split by domain — conductor types live in api/conductors.ts.
  const apiSource = readSource("lib/api/conductors.ts");
  const contextSource = readSource("contexts/ExecutionProcessesContext.tsx");

  // The union may be single- or multi-line depending on Prettier wrapping;
  // assert the two members independently rather than their exact layout.
  assert.match(apiSource, /"llm_request"/);
  assert.match(apiSource, /"llm_response"/);
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
  assert.equal(
    getDictionaryValue("en-US", "conductor.turnSummary.llmResponse"),
    "The LLM response ended with {stopReason}.",
  );
  assert.equal(
    getDictionaryValue("zh-CN", "conductor.toastStateViolation"),
    "Conductor 非法状态跳变",
  );
  assert.equal(getDictionaryValue("en-US", "conductor.panel.timeline"), "Phase Timeline");
});

test("issue command center phase hook listens for conductor state violation toast events", () => {
  const source = readSource("features/issues/hooks/useConductorPhase.ts");

  assert.match(
    source,
    /typeIn\("conductor_status", "conductor_state_violation", "conductor_failed"\)/,
  );
  assert.match(source, /event\.type === "conductor_state_violation"/);
  assert.match(source, /conductor\.toastStateViolation/);
  assert.match(source, /conductor\.toastStateViolationMessage/);
});
