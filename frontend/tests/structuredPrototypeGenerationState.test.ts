import assert from "node:assert/strict";
import test from "node:test";

import {
  canStartStructuredPrototypeGeneration,
  isStructuredPrototypeGenerationActive,
  nextStructuredPrototypeGenerationPollFailureCount,
  structuredPrototypeGenerationBrief,
  structuredPrototypeGenerationBlueprintScope,
  structuredPrototypeGenerationPercent,
  structuredPrototypeGenerationSourceExclusion,
} from "../src/features/prototype/structured/structuredPrototypeGenerationState";
import type {
  StructuredPrototypeGenerationBlueprint,
  StructuredPrototypeGenerationJob,
} from "../src/features/prototype/structured/types";
import { readCompactSource } from "./sourceTestUtils";

function job(status: StructuredPrototypeGenerationJob["status"]): StructuredPrototypeGenerationJob {
  return {
    contractVersion: 1,
    id: "job-1",
    projectId: "project-1",
    status,
    operationId: "operation-1",
    sourcePolicy: "committed_head_v1",
    sourceSnapshotObjectHash: "sha256:" + "a".repeat(64),
    sourceFingerprint: "sha256:" + "b".repeat(64),
    sourceSnapshotRef: "refs/agent-collab/prototype-generation/job-1",
    repositoryObjectFormat: "sha1",
    worktreeBaseCommit: "c".repeat(40),
    repositoryProjectPrefix: "",
    repositoryTreeObjectId: "d".repeat(40),
    workingTreeDirty: false,
    excludedTrackedChangeCount: 0,
    excludedUntrackedCount: 0,
    sourceFileExclusionPolicy: "dotenv_checkout_filter_v1",
    excludedSensitiveFileCount: 0,
    excludedStatusHash: "sha256:" + "e".repeat(64),
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

test("structured generation source exclusion distinguishes legacy, clean, and dirty evidence", () => {
  assert.deepEqual(structuredPrototypeGenerationSourceExclusion(null), { kind: "unknown" });
  assert.deepEqual(structuredPrototypeGenerationSourceExclusion(job("queued")), {
    kind: "clean",
    sensitive: 0,
  });
  assert.deepEqual(
    structuredPrototypeGenerationSourceExclusion({
      ...job("queued"),
      workingTreeDirty: true,
      excludedTrackedChangeCount: 2,
      excludedUntrackedCount: 1,
      excludedSensitiveFileCount: 1,
    }),
    { kind: "dirty", tracked: 2, untracked: 1, sensitive: 1 },
  );
});

test("a new generation starts only after no job or a terminal failure", () => {
  assert.equal(canStartStructuredPrototypeGeneration(null), true);
  assert.equal(canStartStructuredPrototypeGeneration(job("failed")), true);
  assert.equal(canStartStructuredPrototypeGeneration(job("interrupted")), true);
  assert.equal(canStartStructuredPrototypeGeneration(job("planning")), false);
  assert.equal(canStartStructuredPrototypeGeneration(job("ready")), false);
});

test("project analysis has a reproducible default brief when user guidance is empty", () => {
  assert.equal(
    structuredPrototypeGenerationBrief(""),
    "Analyze the registered project source and generate the smallest coherent editable prototype " +
      "from its routes and pages. Include data models, roles, forms, behaviors, flows, and scenarios " +
      "only when repository code proves they exist.",
  );
  assert.equal(
    structuredPrototypeGenerationBrief("  Emphasize the existing reporting workflow.  "),
    "Emphasize the existing reporting workflow.",
  );
});

test("generation recovery errors preserve the project-level delete control", () => {
  const source = readCompactSource(
    "features/prototype/structured/StructuredPrototypeGenerationPanel.tsx",
  );

  assert.match(source, /\{\(job \|\| generation\.error\) && \(/);
  assert.match(source, /setDeleteDialogOpen\(true\)/);
  assert.match(source, /aria-label=\{t\("prototype\.structured\.delete"\)\}/);
});

test("a valid generation snapshot resets the consecutive polling failure budget", () => {
  const afterTwoFailures = nextStructuredPrototypeGenerationPollFailureCount(
    nextStructuredPrototypeGenerationPollFailureCount(0, "failure"),
    "failure",
  );

  assert.equal(afterTwoFailures, 2);
  assert.equal(nextStructuredPrototypeGenerationPollFailureCount(afterTwoFailures, "success"), 0);
});

test("blueprint confirmation exposes executable variable, behavior, and scenario scope", () => {
  const blueprint: StructuredPrototypeGenerationBlueprint = {
    contractVersion: 3,
    documentTitle: "Events",
    productIntent: "Manage registrations",
    outputLocale: "en-US",
    foundationIntent: {
      visualLanguage: "operations",
      density: "compact",
      responsiveStrategy: "responsive",
    },
    pages: [
      {
        pageKey: "events",
        title: "Events",
        route: "/events",
        purpose: "List events",
        navigationGroupKey: "main",
      },
    ],
    navigation: [{ key: "events", label: "Events", targetPageKey: "events" }],
    flowIntents: [],
    roleIntents: [{ key: "operator", label: "Operator" }],
    entityIntents: [],
    variableIntents: [
      {
        key: "selectedEvent",
        valueType: "entityRef",
        nullable: true,
        entitySchemaKey: "event",
        defaultValue: { type: "null" },
      },
    ],
    formIntents: [],
    viewBindingIntents: [],
    behaviorIntents: [
      {
        key: "open-event",
        sourcePageKey: "events",
        guard: { kind: "roleIs", roleKey: "operator" },
        effects: [{ kind: "navigate", targetPageKey: "events" }],
        guardFalseEffects: [{ kind: "notify", level: "warning", message: "Not allowed" }],
      },
    ],
    scenarioIntents: [
      {
        key: "operator-opens-event",
        actorRoleKey: "operator",
        startPageKey: "events",
        initialVariables: [],
        entityFixtures: [],
        allowSimulatedRoleSwitch: false,
        scriptedSteps: [
          {
            kind: "activateBehavior",
            behaviorIntentKey: "open-event",
            expectedOutcome: "applied",
          },
        ],
        milestones: [
          {
            afterStep: 1,
            currentPageKey: "events",
            variableValues: [],
            entityFieldValues: [],
          },
        ],
      },
    ],
    startPageKeys: ["events"],
  };

  const scope = structuredPrototypeGenerationBlueprintScope(blueprint);
  assert.equal(blueprint.contractVersion, 3);
  assert.match(scope.find((group) => group.key === "variables")?.values[0] ?? "", /event/);
  assert.match(scope.find((group) => group.key === "behaviors")?.values[0] ?? "", /guard:/);
  assert.match(scope.find((group) => group.key === "behaviors")?.values[0] ?? "", /navigate/);
  assert.match(scope.find((group) => group.key === "scenarios")?.values[0] ?? "", /steps:/);
  assert.match(scope.find((group) => group.key === "scenarios")?.values[0] ?? "", /after 1/);
});
