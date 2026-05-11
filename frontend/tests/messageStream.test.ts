// Lightweight unit test for the delta-accumulation logic.
// The full WebSocket lifecycle is exercised in manual E2E; here we just verify
// the math of "apply delta with monotonic seq" without React rendering.
import { test } from "node:test";
import assert from "node:assert/strict";

interface PendingAssistant {
  text: string;
  lastSeq: number;
}

// Mirror of the hook's reducer logic (kept in sync with useExecutionProcessMessageStream).
function applyDelta(prev: PendingAssistant | null, seq: number, deltaText: string): PendingAssistant {
  if (prev && seq <= prev.lastSeq) {
    return prev;  // ignore duplicate / out-of-order
  }
  return { text: (prev?.text ?? "") + deltaText, lastSeq: seq };
}

test("applyDelta accumulates text across monotonic seqs", () => {
  let state: PendingAssistant | null = null;
  state = applyDelta(state, 1, "Hello");
  state = applyDelta(state, 2, ", world");
  state = applyDelta(state, 3, "!");
  assert.equal(state.text, "Hello, world!");
  assert.equal(state.lastSeq, 3);
});

test("applyDelta ignores out-of-order or duplicate seqs", () => {
  let state: PendingAssistant | null = null;
  state = applyDelta(state, 5, "abc");
  // duplicate seq
  state = applyDelta(state, 5, "DUP");
  assert.equal(state.text, "abc");
  // older seq
  state = applyDelta(state, 4, "OLD");
  assert.equal(state.text, "abc");
  // newer
  state = applyDelta(state, 6, "def");
  assert.equal(state.text, "abcdef");
  assert.equal(state.lastSeq, 6);
});

test("applyDelta from empty state", () => {
  const state = applyDelta(null, 1, "first");
  assert.equal(state.text, "first");
  assert.equal(state.lastSeq, 1);
});
