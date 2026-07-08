import test from "node:test";
import assert from "node:assert/strict";

import {
  parseGlobalEventsFrame,
  parseWorkspaceEventsFrame,
} from "../src/hooks/executionProcessesStreamFrames";

test("parseGlobalEventsFrame handles ping, resume gap, and event ids", () => {
  assert.deepEqual(parseGlobalEventsFrame(JSON.stringify({ type: "ping" })), { kind: "ping" });

  assert.deepEqual(
    parseGlobalEventsFrame(
      JSON.stringify({
        type: "resume_gap",
        event_id: "evt-1",
        payload: { reason: "too_old" },
      }),
    ),
    {
      kind: "event",
      eventId: "evt-1",
      event: { type: "resume_gap", reason: "too_old" },
    },
  );

  assert.deepEqual(parseGlobalEventsFrame("{bad"), { kind: "malformed" });
  assert.deepEqual(parseGlobalEventsFrame(JSON.stringify({ payload: {} })), {
    kind: "malformed",
  });
});

test("parseWorkspaceEventsFrame handles control and malformed frames", () => {
  assert.deepEqual(parseWorkspaceEventsFrame("pong"), { kind: "control" });
  assert.deepEqual(parseWorkspaceEventsFrame("ping"), { kind: "control" });
  assert.deepEqual(parseWorkspaceEventsFrame("not json"), { kind: "malformed" });
  assert.deepEqual(parseWorkspaceEventsFrame(JSON.stringify({ JsonPatch: [{ op: "bad" }] })), {
    kind: "malformed",
  });
});

test("parseWorkspaceEventsFrame narrows patches, events, ready, and finished", () => {
  const log = {
    id: "log-1",
    session_id: "session-1",
    stream: "stdout",
    content: "hi",
    task_id: null,
    execution_process_id: "exec-1",
    created_at: "2026-07-07T00:00:00Z",
  };
  assert.deepEqual(
    parseWorkspaceEventsFrame(
      JSON.stringify({
        JsonPatch: [{ op: "replace", path: "/execution_processes/exec-1/status", value: "done" }],
        Events: [log],
        Ready: true,
        finished: true,
      }),
    ),
    {
      kind: "message",
      patches: [{ op: "replace", path: "/execution_processes/exec-1/status", value: "done" }],
      events: [log],
      ready: true,
      finished: true,
    },
  );
});
