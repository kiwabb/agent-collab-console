import test from "node:test";
import assert from "node:assert/strict";
import { readCompactSource as readSource } from "./sourceTestUtils";

import { getDictionaryValue } from "../src/lib/i18n";

test("resume copy is wired in both locales", () => {
  assert.equal(getDictionaryValue("zh-CN", "sidebar.resume"), "简历");
  assert.equal(getDictionaryValue("zh-CN", "resume.title"), "简历");
  assert.equal(getDictionaryValue("zh-CN", "ui.openNavigation"), "打开导航");
  assert.equal(getDictionaryValue("en-US", "sidebar.resume"), "Resume");
  assert.equal(getDictionaryValue("en-US", "resume.title"), "Resume");
  assert.equal(getDictionaryValue("en-US", "ui.openNavigation"), "Open navigation");
});

test("resume page and sidebar use i18n keys", () => {
  const resumeSource = [
    readSource("features/resume/ResumePage.tsx"),
    readSource("features/resume/ResumePageActions.tsx"),
    readSource("features/resume/ResumeEditorPanel.tsx"),
    readSource("features/resume/ResumeSidebar.tsx"),
  ].join("\n");
  const workbenchSidebar = readSource("features/workbench/components/AppSidebar.tsx");

  assert.match(resumeSource, /t\("resume\.title"\)/);
  assert.match(resumeSource, /t\("resume\.importPdf"\)/);
  assert.match(resumeSource, /t\("resume\.toast\.saved"\)/);
  assert.match(workbenchSidebar, /t\("sidebar\.resume"\)/);
});

test("resume api module exposes the project resume surface", () => {
  const api = readSource("lib/api/resume.ts");

  assert.match(api, /export async function getProjectResume\b/);
  assert.match(api, /export async function saveProjectResume\b/);
  assert.match(api, /export async function importProjectResumePdf\b/);
});

test("resume workbench layout keeps the editor usable on narrow screens", () => {
  const shell = readSource("features/workbench/WorkbenchShell.tsx");
  const header = readSource("features/workbench/components/AppHeader.tsx");
  const pageFrame = readSource("features/workbench/components/PageFrame.tsx");
  const actions = readSource("features/resume/ResumePageActions.tsx");

  assert.match(shell, /h-dvh/);
  assert.match(shell, /hidden h-full shrink-0 lg:block/);
  assert.match(shell, /enterprise-panel min-w-0 flex-1/);
  assert.match(shell, /fixed inset-0 z-40 lg:hidden/);
  assert.match(shell, /t\("ui\.closeNavigation"\)/);
  assert.match(header, /t\("ui\.openNavigation"\)/);
  assert.match(header, /lg:hidden/);
  assert.match(pageFrame, /flex flex-col items-start justify-between/);
  assert.match(pageFrame, /w-full items-center gap-2/);
  assert.match(actions, /w-full max-w-full flex-wrap/);
  assert.match(actions, /flex-\[1_1_220px\]/);
});

test("selection provider keeps local storage reads out of hydration state initializers", () => {
  const selectionProvider = readSource("features/workbench/state/SelectionProvider.tsx");

  assert.match(selectionProvider, /useState<string \| null>\(initial\?\.projectId \?\? null\)/);
  assert.match(selectionProvider, /else setProjectIdState\(readLocal\(PROJECT_KEY\)\)/);
  assert.doesNotMatch(selectionProvider, /useState<string \| null>\([^)]*readLocal\(PROJECT_KEY\)/);
});
