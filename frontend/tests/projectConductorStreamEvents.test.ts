import test from "node:test";
import assert from "node:assert/strict";

import {
  parseProjectConductorRecord,
  parseProjectConductorToolEvent,
  readProjectConductorToolEvents,
} from "../src/features/projects/components/projectConductorStreamEvents";

function messageEvent(payload: unknown): Event {
  return new MessageEvent("message", { data: JSON.stringify(payload) });
}

test("parseProjectConductorRecord accepts object JSON events only", () => {
  assert.deepEqual(parseProjectConductorRecord(messageEvent({ role: "project_conductor" })), {
    role: "project_conductor",
  });
  assert.equal(
    parseProjectConductorRecord(new MessageEvent("message", { data: "not-json" })),
    null,
  );
  assert.equal(parseProjectConductorRecord(new MessageEvent("message", { data: "[]" })), null);
});

test("project conductor tool event guard validates required fields", () => {
  const tool = {
    id: "tool-1",
    name: "read_status",
    input: { project_id: "p1" },
    result: { ok: true },
    is_error: false,
  };
  assert.deepEqual(parseProjectConductorToolEvent(messageEvent(tool)), tool);
  assert.equal(parseProjectConductorToolEvent(messageEvent({ ...tool, input: [] })), null);
  assert.equal(parseProjectConductorToolEvent(messageEvent({ ...tool, is_error: "false" })), null);
});

test("readProjectConductorToolEvents drops malformed tool arrays", () => {
  const tool = {
    id: "tool-1",
    name: "read_status",
    input: {},
    result: null,
    is_error: false,
  };
  assert.deepEqual(readProjectConductorToolEvents([tool]), [tool]);
  assert.deepEqual(readProjectConductorToolEvents([{ ...tool, id: 1 }]), []);
  assert.deepEqual(readProjectConductorToolEvents({ tool }), []);
});
