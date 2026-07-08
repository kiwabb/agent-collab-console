import test from "node:test";
import assert from "node:assert/strict";
import { readCompactSource as readSource } from "./sourceTestUtils";

test("useExecutionProcesses uses global websocket resume instead of EventSource", () => {
  const source = readSource("hooks/useExecutionProcesses.ts");
  // Phase 4: api.ts split by domain — global events url builder + last_event_id
  // live in api/health.ts.
  const apiSource = readSource("lib/api/health.ts");

  assert.match(source, /getGlobalEventsStreamUrl/);
  assert.match(source, /LAST_EVENT_ID_KEY/);
  assert.match(source, /resume_gap/);
  assert.match(source, /ws\.send\("pong"\)/);
  assert.doesNotMatch(source, /EventSource/);
  assert.match(apiSource, /last_event_id/);
});

test("execution process context exposes resume gap state", () => {
  const source = readSource("contexts/ExecutionProcessesContext.tsx");
  const providerSource = readSource("providers/ExecutionProcessesProvider.tsx");
  const panelSource = readSource("features/workflow/ConductorLogPanel.tsx");

  assert.match(source, /type: "resume_gap"/);
  assert.match(source, /resumeGapCount: number/);
  assert.match(providerSource, /resumeGapCount/);
  assert.match(panelSource, /resumeGapCount/);
});

test("api exports a global events websocket url builder", () => {
  // Phase 4: api.ts split by domain — getGlobalEventsStreamUrl lives in api/health.ts.
  const source = readSource("lib/api/health.ts");

  assert.match(source, /export function getGlobalEventsStreamUrl/);
  assert.match(source, /\/api\/ws\/events/);
});
