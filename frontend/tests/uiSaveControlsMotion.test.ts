import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const SRC_ROOT = join(process.cwd(), "src");

function readSource(relativePath: string): string {
  return readFileSync(join(SRC_ROOT, relativePath), "utf-8");
}

test("markdown editor save button uses tool motion while saving", () => {
  const source = readSource("components/ui/markdown-editor.tsx");

  assert.match(source, /import \{ AgentThinkingIndicator \} from "@\/components\/ui\/AgentThinkingIndicator";/);
  assert.match(source, /data-density=\{isSaving \? "markdown-editor-save-tool" : "markdown-editor-save"\}/);
  assert.match(source, /isSaving && "motion-essential"/);
  assert.match(source, /\{isSaving \? <AgentThinkingIndicator phase="tool" size=\{12\} \/> : <Check size=\{12\} \/>\}/);
  assert.doesNotMatch(source, /\bLoader2\b/);
});

test("inline edit save button uses tool motion while saving", () => {
  const source = readSource("components/ui/inline-edit.tsx");

  assert.match(source, /import \{ AgentThinkingIndicator \} from "@\/components\/ui\/AgentThinkingIndicator";/);
  assert.match(source, /data-density=\{isSaving \? "inline-edit-save-tool" : "inline-edit-save"\}/);
  assert.match(source, /isSaving && "motion-essential"/);
  assert.match(source, /\{isSaving \? <AgentThinkingIndicator phase="tool" size=\{14\} \/> : <Check size=\{14\} \/>\}/);
  assert.doesNotMatch(source, /\bLoader2\b/);
});

test("auto-save indicator uses tool motion while saving", () => {
  const source = readSource("components/ui/auto-save-indicator.tsx");

  assert.match(source, /import \{ AgentThinkingIndicator \} from "@\/components\/ui\/AgentThinkingIndicator"/);
  assert.match(source, /data-density=\{status === "saving" \? "auto-save-indicator-tool" : "auto-save-indicator"\}/);
  assert.match(source, /status === "saving" && "motion-essential text-text-muted"/);
  assert.match(source, /<AgentThinkingIndicator phase="tool" size=\{12\} \/>/);
  assert.doesNotMatch(source, /\bLoader2\b/);
});
