import test from "node:test";
import assert from "node:assert/strict";

import {
  getGenerateFromCodeStreamUrl,
  MAX_CANDIDATE_QUERY_TEXT_CHARS,
} from "../src/lib/api/prototypes";
import { safeJsonRecord } from "../src/lib/utils";

test("candidate query text limit documents the current EventSource transport bound", () => {
  assert.equal(MAX_CANDIDATE_QUERY_TEXT_CHARS, 1200);
});

test("generate-from-code URL includes selected candidates, guidance, and runtime evidence", () => {
  const url = getGenerateFromCodeStreamUrl("project 1", {
    candidateIds: ["next-app-router--help"],
    instruction: "mobile first",
    candidateInstructions: {
      "next-app-router--help": "keep dense controls",
    },
    candidateBriefOverrides: {
      "next-app-router--help": "Route: /help\nFocus on search and docs",
    },
    runtimeEvidence: {
      "next-app-router--help": {
        attempted_url: "http://127.0.0.1:3000/help",
        final_url: "http://127.0.0.1:3000/help",
        success: true,
        title: "Runtime Help",
        visible_text_excerpt: "Runtime Help\nLive docs",
        structure_summary: "headings: Runtime Help; buttons: Search",
        console_errors: ["hydration warning"],
      },
    },
    useRuntimeEvidence: true,
    runtimeBaseUrl: "http://localhost:4000",
  });

  const parsed = new URL(url, "http://frontend.local");
  assert.equal(parsed.pathname, "/api/projects/project%201/prototypes/generate-from-code/stream");
  assert.deepEqual(parsed.searchParams.getAll("candidate_id"), ["next-app-router--help"]);
  assert.equal(parsed.searchParams.get("instruction"), "mobile first");
  assert.equal(parsed.searchParams.get("use_runtime_evidence"), "true");
  assert.equal(parsed.searchParams.get("runtime_base_url"), "http://localhost:4000");
  assert.equal(
    parsed.searchParams.get("candidate_instruction"),
    "next-app-router--help\tkeep dense controls",
  );
  assert.equal(
    parsed.searchParams.get("candidate_brief_override"),
    "next-app-router--help\tRoute: /help\nFocus on search and docs",
  );
  const runtime = parsed.searchParams.get("runtime_evidence");
  assert.ok(runtime);
  assert.ok(runtime.startsWith("next-app-router--help\t"));
  const rawPayload = runtime.split("\t")[1];
  assert.ok(rawPayload);
  const payload = safeJsonRecord(rawPayload);
  assert.ok(payload);
  assert.equal(payload["title"], "Runtime Help");
});

test("generate-from-code URL trims candidate text query params", () => {
  const longText = "x".repeat(MAX_CANDIDATE_QUERY_TEXT_CHARS + 50);
  const url = getGenerateFromCodeStreamUrl("project 1", {
    candidateIds: ["next-app-router--help"],
    candidateInstructions: {
      "next-app-router--help": longText,
    },
    candidateBriefOverrides: {
      "next-app-router--help": longText,
    },
  });

  const parsed = new URL(url, "http://frontend.local");
  const instruction = parsed.searchParams.get("candidate_instruction");
  const brief = parsed.searchParams.get("candidate_brief_override");
  assert.ok(instruction);
  assert.ok(brief);
  assert.equal(instruction.split("\t")[1]?.length, MAX_CANDIDATE_QUERY_TEXT_CHARS);
  assert.equal(brief.split("\t")[1]?.length, MAX_CANDIDATE_QUERY_TEXT_CHARS);
});

test("generate-from-code URL omits blank candidate text query params", () => {
  const url = getGenerateFromCodeStreamUrl("project 1", {
    candidateIds: ["next-app-router--help"],
    candidateInstructions: {
      "next-app-router--help": "   ",
    },
    candidateBriefOverrides: {
      "next-app-router--help": "   ",
    },
  });

  const parsed = new URL(url, "http://frontend.local");
  assert.equal(parsed.searchParams.has("candidate_instruction"), false);
  assert.equal(parsed.searchParams.has("candidate_brief_override"), false);
});
