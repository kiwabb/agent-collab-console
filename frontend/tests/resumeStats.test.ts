import test from "node:test";
import assert from "node:assert/strict";

import { deriveResumeStats, formatByteCount } from "../src/features/resume/resumeStats";

test("deriveResumeStats counts empty content", () => {
  assert.deepEqual(deriveResumeStats(""), {
    characters: 0,
    words: 0,
    lines: 0,
    sizeBytes: 0,
  });
});

test("deriveResumeStats counts characters words and lines", () => {
  assert.deepEqual(deriveResumeStats("Jane Doe\nBackend engineer"), {
    characters: 25,
    words: 4,
    lines: 2,
    sizeBytes: 25,
  });
});

test("formatByteCount keeps compact readable units", () => {
  assert.equal(formatByteCount(0), "0 B");
  assert.equal(formatByteCount(512), "512 B");
  assert.equal(formatByteCount(1536), "1.5 KB");
  assert.equal(formatByteCount(15360), "15 KB");
});
