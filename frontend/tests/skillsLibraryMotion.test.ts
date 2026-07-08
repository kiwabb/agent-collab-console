import test from "node:test";
import assert from "node:assert/strict";
import { readCompactSource as readSource } from "./sourceTestUtils";

test("skills import processing uses tool motion while ingesting capabilities", () => {
  const source = readSource("features/skills/SkillsLibraryPage.tsx");

  assert.match(
    source,
    /import \{ AgentThinkingIndicator \} from "@\/components\/ui\/AgentThinkingIndicator";/,
  );
  assert.match(source, /data-density="skills-import-processing-tool"/);
  assert.match(
    source,
    /className="motion-essential flex items-center justify-center gap-2 text-\[12px\] text-text-muted"/,
  );
  assert.match(
    source,
    /<AgentThinkingIndicator phase="tool" size=\{12\} \/> \{t\("skills\.import\.processing"\)\}/,
  );
  assert.doesNotMatch(
    source,
    /<Loader2 size=\{12\} className="animate-spin" \/> \{t\("skills\.import\.processing"\)\}/,
  );
});

test("skills preview loading uses tool motion while fetching capability content", () => {
  const source = readSource("features/skills/SkillsLibraryPage.tsx");

  assert.match(source, /data-density="skills-preview-loading-tool"/);
  assert.match(
    source,
    /className="motion-essential flex items-center gap-2 text-\[12px\] text-text-muted"/,
  );
  assert.match(
    source,
    /<AgentThinkingIndicator phase="tool" size=\{12\} \/> \{t\("skills\.preview\.loading"\)\}/,
  );
  assert.doesNotMatch(
    source,
    /<Loader2 size=\{12\} className="animate-spin" \/> \{t\("skills\.preview\.loading"\)\}/,
  );
});

test("skills editor save cta uses tool motion while persisting capability metadata", () => {
  const source = readSource("features/skills/SkillsLibraryPage.tsx");

  assert.match(
    source,
    /data-density=\{submitting \? "skills-editor-save-tool" : "skills-editor-save"\}/,
  );
  assert.match(source, /className=\{cn\("gap-1", submitting && "motion-essential"\)\}/);
  assert.match(source, /submitting && <AgentThinkingIndicator phase="tool" size=\{12\} \/>/);
  assert.match(source, /\{t\("skills\.btn\.save"\)\}/);
  assert.doesNotMatch(
    source,
    /<Loader2 size=\{12\} className="animate-spin" \/>\s*\{t\("skills\.btn\.save"\)\}/,
  );
});

test("skills list loading uses tool motion while fetching the capability list", () => {
  const source = readSource("features/skills/SkillsLibraryPage.tsx");

  assert.match(source, /data-density="skills-list-loading-tool"/);
  assert.match(
    source,
    /<AgentThinkingIndicator phase="tool" size=\{12\} \/> \{t\("skills\.loading"\)\}/,
  );
  assert.doesNotMatch(
    source,
    /<Loader2 size=\{12\} className="animate-spin" \/> \{t\("skills\.loading"\)\}/,
  );
});

test("skills language translate buttons use tool motion while translating", () => {
  const source = readSource("features/skills/SkillsLibraryPage.tsx");

  assert.match(source, /<AgentThinkingIndicator phase="tool" size=\{11\} className="inline" \/>/);
  assert.doesNotMatch(source, /<Loader2 size=\{11\} className="animate-spin inline" \/>/);
});

test("skills paste save-all cta uses tool motion while persisting pasted rows", () => {
  const source = readSource("features/skills/SkillsLibraryPage.tsx");

  assert.match(
    source,
    /data-density=\{submitting \? "skills-paste-saveall-tool" : "skills-paste-saveall"\}/,
  );
  assert.match(source, /submitting && "motion-essential"/);
  assert.match(source, /\{submitting && <AgentThinkingIndicator phase="tool" size=\{12\} \/>\}/);
  assert.doesNotMatch(
    source,
    /\{submitting && <Loader2 size=\{12\} className="animate-spin" \/>\}/,
  );
});

test("skills library no longer imports the Loader2 spinner", () => {
  const source = readSource("features/skills/SkillsLibraryPage.tsx");
  assert.doesNotMatch(source, /\bLoader2\b/);
});
