import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const SRC_ROOT = join(process.cwd(), "src");

function readSource(relativePath: string): string {
  return readFileSync(join(SRC_ROOT, relativePath), "utf-8");
}

test("skills import processing uses tool motion while ingesting capabilities", () => {
  const source = readSource("features/skills/SkillsLibraryPage.tsx");

  assert.match(source, /import \{ AgentThinkingIndicator \} from "@\/components\/ui\/AgentThinkingIndicator";/);
  assert.match(source, /data-density="skills-import-processing-tool"/);
  assert.match(source, /className="motion-essential flex items-center justify-center gap-2 text-\[12px\] text-text-muted"/);
  assert.match(source, /<AgentThinkingIndicator phase="tool" size=\{12\} \/> \{t\("skills\.import\.processing"\)\}/);
  assert.doesNotMatch(source, /<Loader2 size=\{12\} className="animate-spin" \/> \{t\("skills\.import\.processing"\)\}/);
});
