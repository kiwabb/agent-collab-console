import test from "node:test";
import assert from "node:assert/strict";

import {
  autoStartIssueGraph,
  checkBackendHealth,
  getCodexTaskMessages,
  getCodexCostStats,
  getEmbeddingStatus,
  getGlobalEventsStreamUrl,
  getIssueBudget,
  getIssueOrchestrationPolicy,
  getMcpCatalog,
  getProcessLogsUrl,
  getProcessMessagesUrl,
  getProjectResume,
  getRuntimeCatalog,
  getTeamNotes,
  importProjectResumePdf,
  pinTeamNotesBlock,
  restoreTeamNotesBlock,
  searchKnowledge,
  saveProjectResume,
  testRuntimeExecutor,
  triggerKnowledgeReindex,
  updateRuntimeCatalog,
  validateRuntimeCatalog,
} from "../src/lib/api";
import {
  checkBackendHealth as splitCheckBackendHealth,
  getGlobalEventsStreamUrl as splitGetGlobalEventsStreamUrl,
} from "../src/lib/api/health";
import {
  getCodexTaskMessages as splitGetCodexTaskMessages,
  getProcessLogsUrl as splitGetProcessLogsUrl,
  getProcessMessagesUrl as splitGetProcessMessagesUrl,
} from "../src/lib/api/tasks";
import {
  getRuntimeCatalog as splitGetRuntimeCatalog,
  testRuntimeExecutor as splitTestRuntimeExecutor,
  updateRuntimeCatalog as splitUpdateRuntimeCatalog,
  validateRuntimeCatalog as splitValidateRuntimeCatalog,
} from "../src/lib/api/runtime";
import { getMcpCatalog as splitGetMcpCatalog } from "../src/lib/api/mcp";
import {
  getEmbeddingStatus as splitGetEmbeddingStatus,
  getTeamNotes as splitGetTeamNotes,
  pinTeamNotesBlock as splitPinTeamNotesBlock,
  restoreTeamNotesBlock as splitRestoreTeamNotesBlock,
  searchKnowledge as splitSearchKnowledge,
  triggerKnowledgeReindex as splitTriggerKnowledgeReindex,
} from "../src/lib/api/knowledge";
import {
  transitionIssueToArchitecture,
  transitionIssueToDevelopment,
  transitionIssueToTesting,
} from "../src/lib/api/issues";
import { startProjectScriptTask, suggestProjectScript } from "../src/lib/api/projects";

test("monolithic api entrypoint preserves split knowledge/stats compatibility exports", () => {
  assert.equal(typeof getEmbeddingStatus, "function");
  assert.equal(typeof searchKnowledge, "function");
  assert.equal(typeof triggerKnowledgeReindex, "function");
  assert.equal(typeof getCodexCostStats, "function");
  assert.equal(typeof getIssueBudget, "function");
  assert.equal(typeof getIssueOrchestrationPolicy, "function");
  assert.equal(typeof getMcpCatalog, "function");
  assert.equal(typeof autoStartIssueGraph, "function");
  assert.equal(typeof getProjectResume, "function");
  assert.equal(typeof importProjectResumePdf, "function");
  assert.equal(typeof saveProjectResume, "function");
  assert.equal(typeof checkBackendHealth, "function");
  assert.equal(typeof getCodexTaskMessages, "function");
  assert.equal(typeof getProcessLogsUrl, "function");
  assert.equal(typeof getProcessMessagesUrl, "function");
  assert.equal(typeof getRuntimeCatalog, "function");
  assert.equal(typeof updateRuntimeCatalog, "function");
  assert.equal(typeof validateRuntimeCatalog, "function");
  assert.equal(typeof testRuntimeExecutor, "function");
  assert.equal(typeof getTeamNotes, "function");
  assert.equal(typeof pinTeamNotesBlock, "function");
  assert.equal(typeof restoreTeamNotesBlock, "function");
});

test("monolithic api entrypoint exposes global event stream URL builder", () => {
  const url = getGlobalEventsStreamUrl("evt-1");

  assert.match(url, /\/api\/ws\/events/);
  assert.match(url, /last_event_id=evt-1/);
});

test("split api modules expose runtime-critical functions directly", () => {
  assert.equal(typeof splitCheckBackendHealth, "function");
  assert.equal(typeof splitGetGlobalEventsStreamUrl, "function");
  assert.equal(typeof splitGetCodexTaskMessages, "function");
  assert.equal(typeof splitGetProcessLogsUrl, "function");
  assert.equal(typeof splitGetProcessMessagesUrl, "function");
  assert.equal(typeof splitGetRuntimeCatalog, "function");
  assert.equal(typeof splitUpdateRuntimeCatalog, "function");
  assert.equal(typeof splitValidateRuntimeCatalog, "function");
  assert.equal(typeof splitTestRuntimeExecutor, "function");
  assert.equal(typeof splitGetMcpCatalog, "function");
  assert.equal(typeof splitGetEmbeddingStatus, "function");
  assert.equal(typeof splitSearchKnowledge, "function");
  assert.equal(typeof splitTriggerKnowledgeReindex, "function");
  assert.equal(typeof splitGetTeamNotes, "function");
  assert.equal(typeof splitPinTeamNotesBlock, "function");
  assert.equal(typeof splitRestoreTeamNotesBlock, "function");
  assert.equal(typeof transitionIssueToArchitecture, "function");
  assert.equal(typeof transitionIssueToDevelopment, "function");
  assert.equal(typeof transitionIssueToTesting, "function");
  assert.equal(typeof startProjectScriptTask, "function");
  assert.equal(typeof suggestProjectScript, "function");
});
