import test from "node:test";
import assert from "node:assert/strict";

import {
  cleanIssueResultText,
  deriveAgentResultSummary,
  extractAgentResultSections,
  looksLikeControlPayload,
  parseIssueResultRecord,
} from "../src/features/issues/issueResultParsing";
import { at } from "./testAssertions";

test("parseIssueResultRecord accepts only object JSON text", () => {
  assert.deepEqual(parseIssueResultRecord('{"summary":"done"}'), { summary: "done" });
  assert.equal(parseIssueResultRecord('["not","a","record"]'), null);
  assert.equal(parseIssueResultRecord("{bad"), null);
  assert.equal(parseIssueResultRecord("plain result"), null);
});

test("extractAgentResultSections falls back to text for non-json results", () => {
  const sections = extractAgentResultSections("engineer", "plain result");

  assert.deepEqual(sections, [{ label: "Result", kind: "text", value: "plain result" }]);
});

test("extractAgentResultSections surfaces clarification and role fields", () => {
  const sections = extractAgentResultSections(
    "qa",
    JSON.stringify({
      clarification_question: "Which environment?",
      final_recommendation: "Ship it.",
      commands_run: ["npm test", { command: "npm run lint" }],
    }),
  );

  assert.equal(at(sections, 0, "section").label, "Clarification question");
  assert.deepEqual(sections, [
    { label: "Clarification question", kind: "text", value: "Which environment?" },
    { label: "Final recommendation", kind: "text", value: "Ship it." },
    {
      label: "Commands run",
      kind: "list",
      value: ["npm test", '{"command":"npm run lint"}'],
    },
  ]);
});

test("deriveAgentResultSummary summarizes structured role results", () => {
  assert.equal(
    deriveAgentResultSummary(
      "product_manager",
      JSON.stringify({
        acceptance_criteria: ["a", "b"],
        product_goals: ["g"],
        requirement_pool: ["r"],
      }),
      "done",
    ),
    "2 acceptance criteria · 1 goal · 1 req",
  );
  assert.equal(deriveAgentResultSummary("engineer", "", "running"), "Working…");
  assert.equal(deriveAgentResultSummary("qa", "a".repeat(90), "done"), `${"a".repeat(77)}…`);
});

test("cleanIssueResultText hides hook control envelopes and extracts JSON summaries", () => {
  assert.equal(looksLikeControlPayload('{"type":"system","message":"hook"}'), true);
  assert.equal(cleanIssueResultText('{"hook_name":"SessionStart","message":"ignore"}'), "");
  assert.equal(cleanIssueResultText('{"summary":"Useful summary"}'), "Useful summary");
  assert.equal(cleanIssueResultText(" plain text "), "plain text");
});
