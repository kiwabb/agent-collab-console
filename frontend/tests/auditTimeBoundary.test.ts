import test from "node:test";
import assert from "node:assert/strict";

import { normalizeSince, normalizeUntil } from "../src/features/audit/timeBoundary";

test("normalizeSince returns null for empty / blank input", () => {
  assert.equal(normalizeSince(""), null);
  assert.equal(normalizeSince("   "), null);
});

test("normalizeUntil returns null for empty / blank input", () => {
  assert.equal(normalizeUntil(""), null);
  assert.equal(normalizeUntil("   "), null);
});

test("normalizeSince pads minute precision to the start of the value", () => {
  assert.equal(normalizeSince("2026-06-02T14:30"), "2026-06-02T14:30:00");
});

test("normalizeUntil pads minute precision to the inclusive end of the value", () => {
  assert.equal(normalizeUntil("2026-06-02T14:30"), "2026-06-02T14:30:59.999999");
});

test("values that already have seconds are left unchanged (idempotent)", () => {
  assert.equal(normalizeSince("2026-06-02T14:30:45"), "2026-06-02T14:30:45");
  assert.equal(normalizeUntil("2026-06-02T14:30:45"), "2026-06-02T14:30:45");
  // already padded by a prior pass — must not double-append
  assert.equal(normalizeSince("2026-06-02T14:30:00"), "2026-06-02T14:30:00");
  assert.equal(normalizeUntil("2026-06-02T14:30:59.999999"), "2026-06-02T14:30:59.999999");
});

test("values that already include fractional seconds are left unchanged", () => {
  assert.equal(normalizeSince("2026-06-02T14:30:45.123456"), "2026-06-02T14:30:45.123456");
  assert.equal(normalizeUntil("2026-06-02T14:30:45.123456"), "2026-06-02T14:30:45.123456");
});
