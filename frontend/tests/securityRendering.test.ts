import test from "node:test";
import assert from "node:assert/strict";
import { readCompactSource as readSource } from "./sourceTestUtils";

test("artifact preview escapes highlight fallback before HTML injection", () => {
  const source = readSource("components/ui/virtualized-artifact-list.tsx");

  assert.match(source, /function escapeHtml\b/);
  assert.doesNotMatch(source, /catch\s*\{[\s\S]*?return code;[\s\S]*?\}/);
  assert.match(source, /return escapeHtml\(code\);/);
});

test("skill markdown sanitizes raw HTML before rendering", () => {
  const source = readSource("features/skills/SkillMarkdown.tsx");

  assert.match(source, /rehypeSanitize/);
  assert.doesNotMatch(source, /rehypePlugins=\{\[rehypeRaw,\s*rehypeHighlight\]\}/);
  assert.match(source, /rehypePlugins=\{\[rehypeRaw,\s*.*rehypeSanitize/);
});
