import test from "node:test";
import assert from "node:assert/strict";

import {
  safeJsonNumberRecord,
  safeJsonParse,
  safeJsonRecord,
  safeJsonStringArray,
} from "../src/lib/utils";

test("safeJsonParse returns unknown values or null for malformed JSON", () => {
  assert.deepEqual(safeJsonParse('{"ok":true}'), { ok: true });
  assert.deepEqual(safeJsonParse("[1,2]"), [1, 2]);
  assert.equal(safeJsonParse("{bad"), null);
});

test("safeJsonRecord accepts only object records", () => {
  assert.deepEqual(safeJsonRecord('{"a":1}'), { a: 1 });
  assert.equal(safeJsonRecord("[1,2]"), null);
  assert.equal(safeJsonRecord("null"), null);
});

test("safeJsonStringArray accepts only string arrays", () => {
  assert.deepEqual(safeJsonStringArray('["a","b"]'), ["a", "b"]);
  assert.equal(safeJsonStringArray('["a",1]'), null);
  assert.equal(safeJsonStringArray('{"a":"b"}'), null);
});

test("safeJsonNumberRecord filters non-number values", () => {
  assert.deepEqual(safeJsonNumberRecord('{"a":1,"b":"x","c":null,"d":2}'), {
    a: 1,
    d: 2,
  });
  assert.equal(safeJsonNumberRecord("[1,2]"), null);
});
