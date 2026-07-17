import assert from "node:assert/strict";
import test from "node:test";

import {
  resolveStructuredPrototypeFlowRuleMutationOutcome,
  type StructuredPrototypeFlowRuleMutation,
} from "../src/features/prototype/structured/structuredPrototypeFlowRuleMutation";

const mutation: StructuredPrototypeFlowRuleMutation = {
  baseDocumentHash: "sha256:base",
  target: { kind: "ruleKey", ruleKey: "flow-dashboard-to-users" },
  failureMessage: "Could not save rule",
  requestSettled: false,
};

test("a staged draft is treated as persisted even while runtime recovery is still pending", () => {
  assert.deepEqual(
    resolveStructuredPrototypeFlowRuleMutationOutcome(mutation, "sha256:next", true),
    { kind: "persisted", target: mutation.target },
  );
});

test("a settled unchanged draft reports failure without discarding the inspector selection", () => {
  assert.deepEqual(
    resolveStructuredPrototypeFlowRuleMutationOutcome(
      { ...mutation, requestSettled: true },
      "sha256:base",
      false,
    ),
    { kind: "failed", message: "Could not save rule" },
  );
});

test("an in-flight unchanged draft remains pending", () => {
  assert.deepEqual(
    resolveStructuredPrototypeFlowRuleMutationOutcome(mutation, "sha256:base", false),
    { kind: "pending" },
  );
});
