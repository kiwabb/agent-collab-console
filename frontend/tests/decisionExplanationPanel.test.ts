import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { getIssueOrchestrationPolicy } from "../src/lib/api";
import { deriveDecisionExplanationView } from "../src/features/issues/components/deriveDecisionExplanationView";

const SRC_ROOT = join(process.cwd(), "src");

type FetchCall = {
  input: RequestInfo | URL;
  init?: RequestInit;
};

function readSource(relativePath: string): string {
  return readFileSync(join(SRC_ROOT, relativePath), "utf-8");
}

function withMockFetch(
  responseBody: unknown,
  run: (calls: FetchCall[]) => Promise<void>,
) {
  const originalFetch = globalThis.fetch;
  const calls: FetchCall[] = [];

  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ input, init });
    return new Response(JSON.stringify(responseBody), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }) as typeof fetch;

  return run(calls).finally(() => {
    globalThis.fetch = originalFetch;
  });
}

test("getIssueOrchestrationPolicy hits the policy endpoint and returns the typed shape", async () => {
  await withMockFetch(
    {
      issue_id: "issue-1",
      recommendation: "single_engineer",
      batch_allowed: false,
      signals: ["trivial"],
      guidance: ["Prefer one focused engineer."],
    },
    async (calls) => {
      const result = await getIssueOrchestrationPolicy("issue-1");

      assert.equal(result?.issue_id, "issue-1");
      assert.equal(result?.recommendation, "single_engineer");
      assert.equal(result?.batch_allowed, false);
      assert.deepEqual(result?.signals, ["trivial"]);
      assert.equal(
        String(calls[0].input),
        "/api/codex/issues/issue-1/orchestration-policy",
      );
      assert.equal(calls[0].init, undefined);
    },
  );
});

test("getIssueOrchestrationPolicy URL-encodes issue IDs", async () => {
  await withMockFetch(
    {
      issue_id: "issue/with/slashes",
      recommendation: "single_engineer",
      batch_allowed: false,
      signals: [],
      guidance: [],
    },
    async (calls) => {
      await getIssueOrchestrationPolicy("issue/with/slashes");

      assert.equal(
        String(calls[0].input),
        "/api/codex/issues/issue%2Fwith%2Fslashes/orchestration-policy",
      );
    },
  );
});

test("decision explanation derivation maps recommendations to compact view state", () => {
  const view = deriveDecisionExplanationView({
    issue_id: "issue-1",
    recommendation: "batch_allowed",
    batch_allowed: true,
    signals: ["explicit_parallel", "independent_slices"],
    guidance: ["Keep one agent per independent slice."],
  });

  assert.equal(view.recommendationKey, "issue.decision.recommendation.batch_allowed");
  assert.equal(view.batchKey, "issue.decision.batch.allowed");
  assert.equal(view.tone, "parallel");
  assert.deepEqual(view.signalKeys, [
    "issue.decision.signal.explicit_parallel",
    "issue.decision.signal.independent_slices",
  ]);
  assert.deepEqual(view.guidanceKeys, [
    "issue.decision.guidance.batch.1",
    "issue.decision.guidance.batch.2",
    "issue.decision.guidance.batch.3",
  ]);
});

test("decision explanation derivation caps noisy signals and keeps empty guidance stable", () => {
  const view = deriveDecisionExplanationView({
    issue_id: "issue-1",
    recommendation: "single_engineer",
    batch_allowed: false,
    signals: ["trivial", "default_serial", "risk_or_cross_layer", "unknown_signal"],
    guidance: [],
  });

  assert.equal(view.tone, "serial");
  assert.equal(view.signalKeys.length, 3);
  assert.deepEqual(view.guidanceKeys, [
    "issue.decision.guidance.singleEngineer.1",
    "issue.decision.guidance.singleEngineer.2",
    "issue.decision.guidance.singleEngineer.3",
  ]);
  assert.equal(view.moreSignals, 1);
});

test("issue side rail renders the decision explanation panel without adding a top-level tab", () => {
  const sideStackSource = readSource("features/issues/components/IssueSideStack.tsx");
  const pageSource = readSource("features/issues/IssueDetailPage.tsx");

  assert.match(sideStackSource, /<DecisionExplanationCard/);
  assert.match(sideStackSource, /getIssueOrchestrationPolicy/);
  assert.match(sideStackSource, /issue_updated/);
  assert.match(sideStackSource, /issue_steered/);
  assert.doesNotMatch(pageSource, /value="decision"/);
});
