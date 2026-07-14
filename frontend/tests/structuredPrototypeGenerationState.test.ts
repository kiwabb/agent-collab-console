import assert from "node:assert/strict";
import test from "node:test";

import {
  canStartStructuredPrototypeGeneration,
  isStructuredPrototypeGenerationActive,
  structuredPrototypeGenerationBrief,
  structuredPrototypeGenerationPercent,
} from "../src/features/prototype/structured/structuredPrototypeGenerationState";
import type { StructuredPrototypeGenerationJob } from "../src/features/prototype/structured/types";

function job(status: StructuredPrototypeGenerationJob["status"]): StructuredPrototypeGenerationJob {
  return {
    contractVersion: 1,
    id: "job-1",
    projectId: "project-1",
    status,
    operationId: "operation-1",
    blueprintVersion: 1,
    blueprintHash: null,
    blueprint: null,
    candidateObjectHash: null,
    previewArtifactId: null,
    previewOutputHash: null,
    replayManifestObjectHash: null,
    documentId: null,
    errorCode: null,
    errorMessage: null,
    total: 5,
    processed: 2,
    succeeded: 2,
    failed: 0,
    running: 1,
    pending: 2,
    items: [],
    createdAt: "2026-07-14T00:00:00Z",
    updatedAt: "2026-07-14T00:00:00Z",
    completedAt: null,
    canConfirm: false,
    canAccept: false,
    previewPath: null,
  };
}

test("structured generation polling statuses are explicit", () => {
  assert.equal(isStructuredPrototypeGenerationActive("planning"), true);
  assert.equal(isStructuredPrototypeGenerationActive("rendering_preview"), true);
  assert.equal(isStructuredPrototypeGenerationActive("awaiting_confirmation"), false);
  assert.equal(isStructuredPrototypeGenerationActive("ready"), false);
});

test("structured generation progress uses processed work", () => {
  assert.equal(structuredPrototypeGenerationPercent(job("generating")), 40);
  assert.equal(structuredPrototypeGenerationPercent({ ...job("queued"), total: 0 }), 0);
});

test("a new generation starts only after no job or a terminal failure", () => {
  assert.equal(canStartStructuredPrototypeGeneration(null), true);
  assert.equal(canStartStructuredPrototypeGeneration(job("failed")), true);
  assert.equal(canStartStructuredPrototypeGeneration(job("interrupted")), true);
  assert.equal(canStartStructuredPrototypeGeneration(job("planning")), false);
  assert.equal(canStartStructuredPrototypeGeneration(job("ready")), false);
});

test("project analysis has a reproducible default brief when user guidance is empty", () => {
  assert.match(structuredPrototypeGenerationBrief(""), /Analyze the registered project source/);
  assert.equal(
    structuredPrototypeGenerationBrief("  Focus on manager approval.  "),
    "Focus on manager approval.",
  );
});
