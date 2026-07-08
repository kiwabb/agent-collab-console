import test from "node:test";
import assert from "node:assert/strict";
import { readCompactSource as readSource } from "./sourceTestUtils";

import { getDictionaryValue } from "../src/lib/i18n";

test("knowledge zh-CN copy is wired", () => {
  assert.equal(getDictionaryValue("zh-CN", "knowledge.title"), "知识层");
  assert.equal(getDictionaryValue("zh-CN", "sidebar.knowledge"), "知识层");
  assert.equal(getDictionaryValue("zh-CN", "knowledge.tab.teamNotes"), "团队备忘");
  assert.equal(getDictionaryValue("zh-CN", "knowledge.mode.hybrid"), "混合");
});

test("knowledge en-US copy is wired", () => {
  assert.equal(getDictionaryValue("en-US", "knowledge.title"), "Knowledge");
  assert.equal(getDictionaryValue("en-US", "sidebar.knowledge"), "Knowledge");
  assert.equal(getDictionaryValue("en-US", "knowledge.tab.teamNotes"), "Team Notes");
  assert.equal(getDictionaryValue("en-US", "knowledge.embedding.online"), "Semantic online");
});

test("knowledge components read i18n keys", () => {
  const knowledgePage = readSource("features/knowledge/KnowledgePage.tsx");
  const teamNotesEditor = readSource("features/knowledge/TeamNotesEditor.tsx");
  const similarCard = readSource("features/issues/components/SimilarIssuesCard.tsx");
  const sidebar = readSource("features/workbench/components/AppSidebar.tsx");

  assert.match(knowledgePage, /t\("knowledge\.title"\)/);
  assert.match(knowledgePage, /t\("knowledge\.searchPlaceholder"\)/);
  assert.match(knowledgePage, /t\("knowledge\.tab\.teamNotes"\)/);
  assert.match(teamNotesEditor, /t\("teamNotes\.softDelete"\)/);
  assert.match(teamNotesEditor, /t\("teamNotes\.refresh"\)/);
  assert.match(similarCard, /t\("issue\.similar"\)/);
  assert.match(sidebar, /t\("sidebar\.knowledge"\)/);
});

test("api.ts exposes knowledge surface", () => {
  // Phase 4: api.ts split by domain — knowledge wrappers live in api/knowledge.ts.
  const api = readSource("lib/api/knowledge.ts");
  assert.match(api, /export async function searchKnowledge\b/);
  assert.match(api, /export async function getSimilarIssues\b/);
  assert.match(api, /export async function getTeamNotes\b/);
  assert.match(api, /export async function deleteTeamNotesBlock\b/);
  assert.match(api, /export async function restoreTeamNotesBlock\b/);
  assert.match(api, /export async function pinTeamNotesBlock\b/);
  assert.match(api, /export async function getEmbeddingStatus\b/);
  assert.match(api, /export async function triggerKnowledgeReindex\b/);
});
