import test from "node:test";
import assert from "node:assert/strict";

import {
  parseSseRecord,
  readFailedPrototypeItems,
  readSseErrorMessage,
  readSseNumber,
  readSseString,
  readSseStringArray,
} from "../src/features/prototype/prototypeStreamEvents";

function messageEvent(payload: unknown): Event {
  return new MessageEvent("message", { data: JSON.stringify(payload) });
}

test("parseSseRecord accepts only object JSON message data", () => {
  assert.deepEqual(parseSseRecord(messageEvent({ type: "ok" })), { type: "ok" });
  assert.equal(parseSseRecord(new MessageEvent("message", { data: "not json" })), null);
  assert.equal(parseSseRecord(new MessageEvent("message", { data: "[]" })), null);
  assert.equal(parseSseRecord(new Event("message")), null);
});

test("SSE primitive readers narrow fields without assertions", () => {
  const record = parseSseRecord(
    messageEvent({ title: "Prototype", count: 3, ok: ["a", "b"], message: "failed" }),
  );
  assert.ok(record);

  assert.equal(readSseString(record, "title"), "Prototype");
  assert.equal(readSseString(record, "missing"), null);
  assert.equal(readSseNumber(record, "count"), 3);
  assert.equal(readSseNumber(record, "title"), null);
  assert.deepEqual(readSseStringArray(record, "ok"), ["a", "b"]);
  assert.equal(readSseErrorMessage(messageEvent({ message: "failed" })), "failed");
});

test("readFailedPrototypeItems validates regenerate-all failure payloads", () => {
  const record = parseSseRecord(messageEvent({ failed: [{ prototype_id: "p2", message: "bad" }] }));
  assert.ok(record);
  assert.deepEqual(readFailedPrototypeItems(record, "failed"), [
    { prototype_id: "p2", message: "bad" },
  ]);

  const invalid = parseSseRecord(messageEvent({ failed: [{ prototype_id: "p2" }] }));
  assert.ok(invalid);
  assert.equal(readFailedPrototypeItems(invalid, "failed"), null);
});
