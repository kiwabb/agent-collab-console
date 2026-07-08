import test from "node:test";
import assert from "node:assert/strict";

import {
  parseSseRecord,
  readCodeGenerationSummary,
  readFailedPrototypeItems,
  readPrototypeCodeCandidates,
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

test("readPrototypeCodeCandidates validates scanner metadata shape", () => {
  const validCandidate = {
    id: "next-app-router--help",
    title: "Help",
    route: "/help",
    kind: "page",
    framework_hint: "next-app-router",
    source_paths: ["src/app/help/page.tsx"],
    primary_source_path: "src/app/help/page.tsx",
    source_hash: "abc",
    source_excerpt: "export default",
    editable_brief: "Build help",
    signals: ["page"],
    action: "create",
    prototype_id: null,
    unsupported_reason: null,
  };
  const record = parseSseRecord(messageEvent({ candidates: [validCandidate] }));
  assert.ok(record);
  assert.equal(readPrototypeCodeCandidates(record, "candidates")?.[0]?.id, validCandidate.id);

  const invalid = parseSseRecord(
    messageEvent({ candidates: [{ ...validCandidate, action: "bad" }] }),
  );
  assert.ok(invalid);
  assert.equal(readPrototypeCodeCandidates(invalid, "candidates"), null);
});

test("summary readers validate complete aggregate payloads", () => {
  const summary = parseSseRecord(
    messageEvent({ created: 1, regenerated: 2, skipped: 3, failed: 4, unsupported: 5 }),
  );
  assert.ok(summary);
  assert.deepEqual(readCodeGenerationSummary(summary), {
    created: 1,
    regenerated: 2,
    skipped: 3,
    failed: 4,
    unsupported: 5,
  });

  const regen = parseSseRecord(
    messageEvent({ ok: ["p1"], failed: [{ prototype_id: "p2", message: "bad" }] }),
  );
  assert.ok(regen);
  assert.deepEqual(readFailedPrototypeItems(regen, "failed"), [
    { prototype_id: "p2", message: "bad" },
  ]);
});
