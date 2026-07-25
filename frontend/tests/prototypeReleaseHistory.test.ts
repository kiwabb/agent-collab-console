import test from "node:test";
import assert from "node:assert/strict";
import { readCompactSource as readSource } from "./sourceTestUtils";

import { getDictionaryValue } from "../src/lib/i18n";

test("release history zh-CN copy is wired", () => {
  assert.equal(getDictionaryValue("zh-CN", "prototype.structured.history"), "发布历史");
  assert.equal(getDictionaryValue("zh-CN", "prototype.structured.history.current"), "当前版本");
  assert.equal(
    getDictionaryValue("zh-CN", "prototype.structured.history.restore"),
    "恢复为当前版本",
  );
  assert.equal(
    getDictionaryValue("zh-CN", "prototype.structured.share.backToCurrent"),
    "返回当前版本",
  );
});

test("release history en-US copy is wired", () => {
  assert.equal(getDictionaryValue("en-US", "prototype.structured.history"), "Release history");
  assert.equal(getDictionaryValue("en-US", "prototype.structured.history.current"), "Current");
  assert.equal(
    getDictionaryValue("en-US", "prototype.structured.history.restore"),
    "Restore as current",
  );
  assert.equal(
    getDictionaryValue("en-US", "prototype.structured.share.backToCurrent"),
    "Back to current",
  );
});

test("release history keys exist in both locales", () => {
  const keys = [
    "prototype.structured.history",
    "prototype.structured.history.title",
    "prototype.structured.history.description",
    "prototype.structured.history.count",
    "prototype.structured.history.loading",
    "prototype.structured.history.failed",
    "prototype.structured.history.retry",
    "prototype.structured.history.empty",
    "prototype.structured.history.revision",
    "prototype.structured.history.current",
    "prototype.structured.history.source.user",
    "prototype.structured.history.source.ai",
    "prototype.structured.history.source.initial_generation",
    "prototype.structured.history.open",
    "prototype.structured.history.preview",
    "prototype.structured.history.restore",
    "prototype.structured.history.restoring",
    "prototype.structured.history.restoreTitle",
    "prototype.structured.history.restoreDescription",
    "prototype.structured.history.restoreConfirm",
    "prototype.structured.history.restoreCancel",
    "prototype.structured.history.restoreFailed",
    "prototype.structured.history.restoreImpact",
    "prototype.structured.share.title",
    "prototype.structured.share.versionLabel",
    "prototype.structured.share.viewingArchived",
    "prototype.structured.share.backToCurrent",
    "prototype.structured.share.emptyTitle",
    "prototype.structured.share.emptyDescription",
    "prototype.structured.publishDialog.title",
    "prototype.structured.publishDialog.description",
    "prototype.structured.publishDialog.summaryLabel",
    "prototype.structured.publishDialog.summaryPlaceholder",
    "prototype.structured.publishDialog.confirm",
    "prototype.structured.publishDialog.cancel",
    "prototype.structured.history.diff",
    "prototype.structured.history.diff.base",
    "prototype.structured.history.diff.loading",
    "prototype.structured.history.diff.failed",
    "prototype.structured.history.diff.identical",
    "prototype.structured.history.diff.titleChanged",
    "prototype.structured.history.diff.pageAdded",
    "prototype.structured.history.diff.pageRemoved",
    "prototype.structured.history.diff.pageModified",
    "prototype.structured.history.diff.flows",
    "prototype.structured.history.diff.assets",
    "prototype.structured.history.diff.sections",
    "prototype.structured.history.diff.section.tokens",
    "prototype.structured.history.diff.section.settings",
    "prototype.structured.history.diff.section.navigation",
    "prototype.structured.history.diff.section.runtime",
    "prototype.structured.history.diff.section.components",
    "prototype.structured.history.timeline",
    "prototype.structured.history.timeline.publish",
    "prototype.structured.history.timeline.rollback",
  ] as const;
  for (const key of keys) {
    for (const locale of ["zh-CN", "en-US"] as const) {
      const value = getDictionaryValue(locale, key);
      assert.notEqual(value, key, `${locale} is missing ${key}`);
      assert.ok(value.length > 0, `${locale} has empty ${key}`);
    }
  }
});

test("release history components read i18n keys", () => {
  const dialog = readSource("features/prototype/structured/StructuredPrototypeReleaseHistory.tsx");
  const studio = readSource("features/prototype/structured/StructuredPrototypeStudioPage.tsx");
  const shareViewer = readSource(
    "features/prototype/structured/StructuredPrototypeShareViewer.tsx",
  );

  assert.match(dialog, /t\("prototype\.structured\.history\.title"\)/);
  assert.match(dialog, /t\("prototype\.structured\.history\.empty"\)/);
  assert.match(dialog, /"prototype\.structured\.history\.restore"/);
  assert.match(dialog, /t\("prototype\.structured\.history\.restoreTitle"\)/);
  assert.match(studio, /t\("prototype\.structured\.history"\)/);
  assert.match(shareViewer, /t\("prototype\.structured\.share\.versionLabel"\)/);
  assert.match(shareViewer, /t\("prototype\.structured\.share\.backToCurrent"\)/);
});

test("release history dialog restores via rollback API with optimistic concurrency", () => {
  const dialog = readSource("features/prototype/structured/StructuredPrototypeReleaseHistory.tsx");
  assert.match(dialog, /rollbackStructuredPrototypePublication\(documentId,/);
  assert.match(dialog, /expectedCurrentRevisionNo: currentRevisionNo/);
  assert.match(dialog, /targetRevisionNo: selected\.revisionNo/);
  assert.match(dialog, /onRestored\?\.\(\)/);
});

test("restore confirmation previews the current-to-target live impact diff", () => {
  const dialog = readSource("features/prototype/structured/StructuredPrototypeReleaseHistory.tsx");
  assert.match(
    dialog,
    /diffStructuredPrototypeRevisions\(documentId, targetRevisionNo, currentRevisionNo\)/,
  );
  assert.match(dialog, /t\("prototype\.structured\.history\.restoreImpact",/);
  assert.match(dialog, /<RevisionDiffSummary state=\{restoreImpact\} \/>/);
});

test("studio refreshes its cached publication after a restore", () => {
  const studio = readSource("features/prototype/structured/StructuredPrototypeStudioPage.tsx");
  const hook = readSource("features/prototype/structured/useStructuredPrototypeStudio.ts");
  assert.match(studio, /onRestored=\{\(\) => void controller\.refreshPublication\(\)\}/);
  assert.match(hook, /refreshPublication: \(\) => Promise<void>/);
});

test("share viewer shows a friendly empty state instead of the raw 404 iframe", () => {
  const shareViewer = readSource(
    "features/prototype/structured/StructuredPrototypeShareViewer.tsx",
  );
  assert.match(shareViewer, /t\("prototype\.structured\.share\.emptyTitle"\)/);
  assert.match(shareViewer, /historyEmpty \?/);
});

test("share page renders the version-aware viewer with a sandboxed iframe", () => {
  const page = readSource("app/prototype-share/[documentId]/page.tsx");
  const shareViewer = readSource(
    "features/prototype/structured/StructuredPrototypeShareViewer.tsx",
  );
  assert.match(page, /<StructuredPrototypeShareViewer documentId=\{documentId\} \/>/);
  assert.match(shareViewer, /sandbox="allow-scripts"/);
  assert.doesNotMatch(shareViewer, /allow-same-origin/);
  assert.match(
    shareViewer,
    /structured-prototype-public\/\$\{encodeURIComponent\(documentId\)\}\/current\/index\.html/,
  );
});

test("publish flow carries an optional release note into the revision summary", () => {
  const publishDialog = readSource(
    "features/prototype/structured/StructuredPrototypePublishDialog.tsx",
  );
  const studio = readSource("features/prototype/structured/StructuredPrototypeStudioPage.tsx");
  const hook = readSource("features/prototype/structured/useStructuredPrototypeStudio.ts");

  assert.match(publishDialog, /t\("prototype\.structured\.publishDialog\.summaryLabel"\)/);
  assert.match(publishDialog, /maxLength=\{200\}/);
  assert.match(studio, /<StructuredPrototypePublishDialog/);
  assert.match(studio, /controller\.publish\(summary\)/);
  assert.match(hook, /publish: \(summary\?: string \| null\) => Promise<boolean>/);
  assert.match(hook, /summary: releaseNote/);
});

test("history dialog renders the publication timeline with rollback entries", () => {
  const dialog = readSource("features/prototype/structured/StructuredPrototypeReleaseHistory.tsx");
  assert.match(dialog, /t\("prototype\.structured\.history\.timeline"\)/);
  assert.match(dialog, /"prototype\.structured\.history\.timeline\.publish"/);
  assert.match(dialog, /"prototype\.structured\.history\.timeline\.rollback"/);
  assert.match(dialog, /fetchState\.history\.events/);
});

test("history dialog lazily fetches the diff against the previous listed revision", () => {
  const dialog = readSource("features/prototype/structured/StructuredPrototypeReleaseHistory.tsx");
  assert.match(
    dialog,
    /diffStructuredPrototypeRevisions\(documentId, targetRevisionNo, previousRevisionNo\)/,
  );
  assert.match(dialog, /t\("prototype\.structured\.history\.diff"\)/);
  assert.match(dialog, /t\("prototype\.structured\.history\.diff\.identical"\)/);
});

test("prototypes api exposes revision history surface", () => {
  const api = readSource("lib/api/prototypes.ts");
  assert.match(api, /export async function listStructuredPrototypeRevisions\b/);
  assert.match(api, /export async function diffStructuredPrototypeRevisions\b/);
  assert.match(api, /export async function rollbackStructuredPrototypePublication\b/);
  assert.match(
    api,
    /structured-prototype-documents\/\$\{encodeURIComponent\(documentId\)\}\/revisions/,
  );
  assert.match(
    api,
    /structured-prototype-documents\/\$\{encodeURIComponent\(documentId\)\}\/rollback/,
  );
});
