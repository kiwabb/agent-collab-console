import test from "node:test";
import assert from "node:assert/strict";

import {
  parseLogStreamFrame,
  parseMessageStreamFrame,
} from "../src/hooks/executionProcessStreamFrames";

test("parseMessageStreamFrame distinguishes malformed, finished, delta, and messages", () => {
  assert.deepEqual(parseMessageStreamFrame("not json"), { kind: "malformed" });
  assert.deepEqual(parseMessageStreamFrame(JSON.stringify({ finished: true })), {
    kind: "finished",
  });
  assert.deepEqual(
    parseMessageStreamFrame(JSON.stringify({ type: "message_delta", seq: 2, delta_text: "hi" })),
    { kind: "message_delta", seq: 2, deltaText: "hi" },
  );

  const message = {
    id: "m1",
    task_id: "task-1",
    execution_process_id: null,
    role: "assistant",
    content: "done",
    created_at: "2026-07-07T00:00:00Z",
  };
  assert.deepEqual(parseMessageStreamFrame(JSON.stringify(message)), {
    kind: "message",
    message,
  });
  assert.deepEqual(parseMessageStreamFrame(JSON.stringify({ type: "message_delta" })), {
    kind: "unknown",
  });
});

test("parseLogStreamFrame treats pongs and non-json as control frames", () => {
  assert.deepEqual(parseLogStreamFrame("pong"), { kind: "control" });
  assert.deepEqual(parseLogStreamFrame("not json"), { kind: "control" });
  assert.deepEqual(parseLogStreamFrame("[]"), { kind: "control" });
});

test("parseLogStreamFrame narrows assistant deltas and heartbeats", () => {
  assert.deepEqual(
    parseLogStreamFrame(JSON.stringify({ kind: "assistant_delta", seq: 5, delta_text: "abc" })),
    { kind: "assistant_delta", seq: 5, deltaText: "abc" },
  );
  assert.deepEqual(parseLogStreamFrame(JSON.stringify({ kind: "assistant_delta" })), {
    kind: "assistant_delta",
    seq: null,
    deltaText: "",
  });
  assert.deepEqual(
    parseLogStreamFrame(
      JSON.stringify({
        kind: "heartbeat",
        phase: "running",
        elapsed_since_last_ms: 120,
        last_event_at: 42,
      }),
    ),
    {
      kind: "heartbeat",
      phase: "running",
      elapsedSinceLastMs: 120,
      lastEventAt: 42,
    },
  );
});

test("parseLogStreamFrame validates LogEvent rows", () => {
  const log = {
    id: "log-1",
    session_id: "session-1",
    stream: "stdout",
    content: "hello",
    task_id: null,
    execution_process_id: "exec-1",
    created_at: "2026-07-07T00:00:00Z",
  };
  assert.deepEqual(parseLogStreamFrame(JSON.stringify(log)), { kind: "log", log });
  assert.deepEqual(parseLogStreamFrame(JSON.stringify({ ...log, stream: 1 })), {
    kind: "unknown",
  });
});
