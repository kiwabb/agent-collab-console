import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

import {
  matchesPrototypePlanFilter,
  prototypePlanRecoveryMessageKey,
} from "../src/features/prototype/PrototypePlanReviewPage";
import {
  boundedPrototypeEvidenceExcerpt,
  countSelectedGeneratablePrototypePlanItems,
  derivePrototypeGenerationProgress,
  formatPrototypeElapsed,
  isPrototypePlanActionGeneratable,
  matchesPrototypePlanStreamResource,
  prototypeDiagnosticMessage,
  prototypeEvidenceDetailMessage,
  prototypeEvidenceKindKey,
  prototypeGenerationErrorMessage,
  PROTOTYPE_POLL_EXHAUSTED_ERROR,
  prototypePlanDraftsEqual,
  prototypePlanErrorMessage,
  prototypePlanItemDraftsEqual,
  reconcilePrototypePlanDraft,
  reconcilePrototypeGenerationRun,
  reconcilePrototypePlanItemDraft,
  shouldAcceptPrototypeGenerationRun,
  shouldAcceptPrototypePlanSnapshot,
} from "../src/features/prototype/prototypePlanReviewState";
import {
  advancePrototypePollingRecovery,
  PROTOTYPE_POLL_DEADLINE_MS,
  PROTOTYPE_POLL_MAX_ATTEMPTS,
  resetPrototypePollingRecovery,
} from "../src/features/prototype/usePrototypeGenerationLiveRun";
import { shouldOpenPrototypeWorkbench } from "../src/features/prototype/prototypeWorkbenchState";
import {
  createPrototypeGenerationRun,
  createPrototypePlan,
  getLatestPrototypeGenerationRun,
  getPrototypeGenerationRunEventsUrl,
  patchPrototypePlanItem,
  patchPrototypePlanSelection,
  retryPrototypeGenerationRun,
} from "../src/lib/api/prototypes";
import type { PrototypeGenerationRun, PrototypePlan, PrototypePlanItem } from "../src/lib/types";
import { jsonRequestBody, withMockFetch } from "./fetchTestUtils";

function item(overrides: Partial<PrototypePlanItem> = {}): PrototypePlanItem {
  return {
    id: "item-1",
    plan_id: "plan-1",
    candidate_id: "candidate-1",
    package_root: "frontend",
    surface_kind: "web",
    route_patterns: ["/home"],
    primary_source_path: "src/Home.tsx",
    source_paths: ["src/Home.tsx"],
    layout_paths: [],
    title: "Home",
    summary: "Home page",
    brief: "Restore the home page",
    states: ["default"],
    evidence_ids: [],
    evidence: [],
    confidence: "high",
    action: "create",
    selected: true,
    source_hash: "sha256:item",
    discovery_origin: "static",
    review_status: "confirmed",
    prototype_id: null,
    created_at: null,
    updated_at: null,
    ...overrides,
  };
}

function plan(overrides: Partial<PrototypePlan> = {}): PrototypePlan {
  return {
    contract_version: 1,
    id: "plan-1",
    project_id: "project-1",
    status: "ready",
    repository_fingerprint: "sha256:repository",
    scope: { packages: ["frontend"], supported_packages: ["frontend"], candidate_count: 1 },
    project_context: {
      product_summary: "Video notes",
      audience: "Researchers",
      visual_language: "Quiet UI",
      shared_layout: "Left navigation",
    },
    global_instruction: "Restore the current UI",
    output_locale: "en-US",
    analysis_phase: "complete",
    analysis_completed: 1,
    analysis_total: 1,
    diagnostics: [],
    error_message: null,
    created_at: "2026-07-12T08:00:00Z",
    updated_at: "2026-07-12T08:00:01Z",
    items: [item()],
    ...overrides,
  };
}

function generationRun(overrides: Partial<PrototypeGenerationRun> = {}): PrototypeGenerationRun {
  const items: PrototypeGenerationRun["items"] = [
    ...Array.from({ length: 8 }, (_, index) => ({
      id: `item-done-${index}`,
      run_id: "run-1",
      plan_item_id: `plan-done-${index}`,
      prototype_id: `prototype-${index}`,
      status: "done" as const,
      title: `Done ${index}`,
      attempt: 1,
      phase: "completed" as const,
      output_chars: 1_000,
      last_event_at: "2026-07-12T08:00:03",
      status_message: "",
      task_id: null,
      execution_process_id: null,
      error_message: null,
      version_no: 1,
      started_at: "2026-07-12T08:00:01",
      completed_at: "2026-07-12T08:00:03",
      created_at: "2026-07-12T08:00:00",
      updated_at: "2026-07-12T08:00:03",
    })),
    ...Array.from({ length: 5 }, (_, index) => ({
      id: `item-failed-${index}`,
      run_id: "run-1",
      plan_item_id: `plan-failed-${index}`,
      prototype_id: null,
      status: "failed" as const,
      title: `Failed ${index}`,
      attempt: 1,
      phase: "failed" as const,
      output_chars: 200,
      last_event_at: "2026-07-12T08:00:04",
      status_message: "",
      task_id: null,
      execution_process_id: null,
      error_message: "model output incomplete",
      version_no: null,
      started_at: "2026-07-12T08:00:01",
      completed_at: "2026-07-12T08:00:04",
      created_at: "2026-07-12T08:00:00",
      updated_at: "2026-07-12T08:00:04",
    })),
  ];
  return {
    contract_version: 1,
    id: "run-1",
    plan_id: "plan-1",
    project_id: "project-1",
    status: "partial",
    repository_fingerprint: "sha256:repository",
    total: 13,
    processed: 13,
    succeeded: 8,
    running: 0,
    pending: 0,
    completed: 8,
    failed: 5,
    error_message: null,
    started_at: "2026-07-12T08:00:00",
    completed_at: "2026-07-12T08:00:04",
    created_at: "2026-07-12T08:00:00",
    updated_at: "2026-07-12T08:00:04",
    items,
    ...overrides,
  };
}

test("prototype plan filters match action and confidence", () => {
  assert.equal(matchesPrototypePlanFilter(item(), "all"), true);
  assert.equal(matchesPrototypePlanFilter(item(), "create"), true);
  assert.equal(matchesPrototypePlanFilter(item({ action: "update" }), "create"), false);
  assert.equal(matchesPrototypePlanFilter(item({ action: "missing" }), "missing"), true);
  assert.equal(matchesPrototypePlanFilter(item({ confidence: "low" }), "low"), true);
  assert.equal(matchesPrototypePlanFilter(item({ confidence: "medium" }), "low"), false);
  assert.equal(isPrototypePlanActionGeneratable("create"), true);
  assert.equal(isPrototypePlanActionGeneratable("update"), true);
  assert.equal(isPrototypePlanActionGeneratable("unchanged"), false);
  assert.equal(isPrototypePlanActionGeneratable("missing"), false);
  assert.equal(isPrototypePlanActionGeneratable("unsupported"), false);
  assert.equal(
    countSelectedGeneratablePrototypePlanItems([
      item({ id: "create", action: "create", selected: true }),
      item({ id: "update", action: "update", selected: true }),
      item({ id: "missing", action: "missing", selected: true }),
      item({ id: "unchanged", action: "unchanged", selected: true }),
    ]),
    2,
  );
});

test("server snapshots preserve dirty plan and item drafts", () => {
  const currentPlanDraft = {
    instruction: "Unsaved navigation edit",
    context: {
      product_summary: "Unsaved summary",
      audience: "Editors",
      visual_language: "Dense",
      shared_layout: "Top navigation",
    },
  };
  assert.equal(reconcilePrototypePlanDraft(currentPlanDraft, plan(), true), currentPlanDraft);
  assert.deepEqual(reconcilePrototypePlanDraft(currentPlanDraft, plan(), false), {
    instruction: "Restore the current UI",
    context: plan().project_context,
  });

  const currentItemDraft = item({ title: "Unsaved title" });
  const serverItem = item({ title: "Server title" });
  assert.equal(
    reconcilePrototypePlanItemDraft(currentItemDraft, serverItem, true),
    currentItemDraft,
  );
  assert.equal(reconcilePrototypePlanItemDraft(currentItemDraft, serverItem, false), serverItem);
  assert.equal(
    reconcilePrototypePlanItemDraft(currentItemDraft, item({ id: "item-2" }), true)?.id,
    "item-2",
  );
  assert.equal(prototypePlanDraftsEqual(currentPlanDraft, currentPlanDraft), true);
  assert.equal(
    prototypePlanDraftsEqual(currentPlanDraft, {
      ...currentPlanDraft,
      instruction: "Edited while saving",
    }),
    false,
  );
  assert.equal(prototypePlanItemDraftsEqual(currentItemDraft, currentItemDraft), true);
  assert.equal(
    prototypePlanItemDraftsEqual(currentItemDraft, {
      ...currentItemDraft,
      brief: "Edited while saving",
    }),
    false,
  );
});

test("plan and generation reconciliation reject delayed snapshots from older work", () => {
  const current = plan({ updated_at: "2026-07-12T08:00:03Z" });
  assert.equal(
    shouldAcceptPrototypePlanSnapshot(current, plan({ updated_at: "2026-07-12T08:00:02Z" })),
    false,
  );
  assert.equal(
    shouldAcceptPrototypePlanSnapshot(current, plan({ updated_at: "2026-07-12T08:00:04Z" })),
    true,
  );

  const currentRun = generationRun({
    id: "run-current",
    created_at: "2026-07-12T08:00:00Z",
    updated_at: "2026-07-12T08:00:04Z",
  });
  const newerRun = generationRun({
    id: "run-newer",
    created_at: "2026-07-12T08:00:05Z",
    updated_at: "2026-07-12T08:00:05Z",
  });
  const olderRun = generationRun({
    id: "run-older",
    created_at: "2026-07-12T07:59:59Z",
    updated_at: "2026-07-12T08:00:06Z",
  });
  const tiedRun = generationRun({
    id: "run-tied",
    created_at: currentRun.created_at,
    updated_at: currentRun.updated_at,
  });
  const currentWithoutRevision = generationRun({
    id: "run-current-without-revision",
    created_at: null,
    updated_at: null,
  });
  const incomingWithoutRevision = generationRun({
    id: "run-incoming-without-revision",
    created_at: null,
    updated_at: null,
  });
  assert.equal(shouldAcceptPrototypeGenerationRun(currentRun, currentRun), true);
  assert.equal(shouldAcceptPrototypeGenerationRun(currentRun, newerRun), false);
  assert.equal(
    shouldAcceptPrototypeGenerationRun(currentRun, newerRun, { allowNewerRun: true }),
    true,
  );
  assert.equal(
    shouldAcceptPrototypeGenerationRun(currentRun, olderRun, { allowNewerRun: true }),
    false,
  );
  assert.equal(
    shouldAcceptPrototypeGenerationRun(currentRun, tiedRun, { allowNewerRun: true }),
    false,
  );
  assert.equal(
    shouldAcceptPrototypeGenerationRun(currentWithoutRevision, incomingWithoutRevision, {
      allowNewerRun: true,
    }),
    false,
  );
  assert.equal(shouldAcceptPrototypeGenerationRun(null, newerRun), true);
  assert.equal(
    matchesPrototypePlanStreamResource(plan(), "plan-1", "project-1", "project-1"),
    true,
  );
  assert.equal(
    matchesPrototypePlanStreamResource(
      plan({ id: "plan-old" }),
      "plan-1",
      "project-1",
      "project-1",
    ),
    false,
  );
  assert.equal(
    matchesPrototypePlanStreamResource(
      plan({ project_id: "project-old" }),
      "plan-1",
      "project-1",
      "project-1",
    ),
    false,
  );
  assert.equal(
    matchesPrototypePlanStreamResource(plan(), "plan-1", "project-1", "project-old"),
    false,
  );
});

test("only the tracked successful generation run opens the prototype workbench", () => {
  const completed = generationRun({ id: "run-completed", status: "completed" });
  assert.equal(shouldOpenPrototypeWorkbench(completed, "run-completed"), true);
  assert.equal(shouldOpenPrototypeWorkbench(completed, null), false);
  assert.equal(shouldOpenPrototypeWorkbench(completed, "run-other"), false);
  assert.equal(
    shouldOpenPrototypeWorkbench(
      generationRun({ id: "run-completed", status: "partial" }),
      "run-completed",
    ),
    false,
  );
  assert.equal(shouldOpenPrototypeWorkbench(null, "run-completed"), false);
});

test("generation progress counts terminal failures as processed", () => {
  const progress = derivePrototypeGenerationProgress(generationRun());
  assert.equal(progress.processed, 13);
  assert.equal(progress.succeeded, 8);
  assert.equal(progress.failed, 5);
  assert.equal(progress.percent, 100);
  assert.equal(progress.failedItems.length, 5);
  assert.equal(progress.totalOutputChars, 9_000);
});

test("generation progress keeps skipped items out of failure and retry summaries", () => {
  const run = generationRun();
  const firstFailed = run.items.find((candidate) => candidate.status === "failed");
  assert.ok(firstFailed);
  const progress = derivePrototypeGenerationProgress({
    ...run,
    items: run.items.map((candidate) =>
      candidate.id === firstFailed.id
        ? {
            ...candidate,
            status: "skipped",
            phase: "skipped",
            error_message: null,
          }
        : candidate,
    ),
  });
  assert.equal(progress.failedItems.length, 4);
  assert.equal(
    progress.failedItems.some((candidate) => candidate.status === "skipped"),
    false,
  );
});

test("generation reconciliation rejects stale or regressive snapshots", () => {
  const terminal = generationRun();
  const staleActive = generationRun({
    status: "running",
    processed: 5,
    succeeded: 5,
    failed: 0,
    running: 2,
    pending: 6,
    completed: 5,
    completed_at: null,
    updated_at: "2026-07-12T08:00:02",
  });
  assert.equal(reconcilePrototypeGenerationRun(terminal, staleActive), terminal);

  const newer = generationRun({ updated_at: "2026-07-12T08:00:05" });
  assert.equal(reconcilePrototypeGenerationRun(terminal, newer), newer);

  const missingRevision = generationRun({ updated_at: null });
  assert.equal(reconcilePrototypeGenerationRun(terminal, missingRevision), terminal);

  const regressive = generationRun({
    processed: 12,
    pending: 1,
    updated_at: "2026-07-12T08:00:05",
  });
  assert.equal(reconcilePrototypeGenerationRun(terminal, regressive), terminal);

  const latestRun = generationRun({
    id: "run-2",
    created_at: "2026-07-12T08:00:05",
    updated_at: "2026-07-12T08:00:05",
  });
  assert.equal(reconcilePrototypeGenerationRun(terminal, latestRun), terminal);
  assert.equal(
    reconcilePrototypeGenerationRun(terminal, latestRun, { allowNewerRun: true }),
    latestRun,
  );
});

test("prototype review presentation localizes diagnostics and bounds excerpts", () => {
  assert.deepEqual(
    prototypeDiagnosticMessage("React Router path at line 42 is not statically evaluable"),
    { key: "prototype.plan.diagnostic.dynamicRoute", params: { line: "42" } },
  );
  assert.deepEqual(boundedPrototypeEvidenceExcerpt("abcdef", 4), {
    text: "abcd",
    truncated: true,
  });
  assert.equal(formatPrototypeElapsed("2026-07-12T08:00:00Z", "2026-07-12T08:01:05Z", 0), "01:05");
  assert.deepEqual(prototypeGenerationErrorMessage("prototype_plan_missing"), {
    key: "prototype.plan.generationError.planMissing",
  });
  assert.deepEqual(prototypeGenerationErrorMessage(PROTOTYPE_POLL_EXHAUSTED_ERROR), {
    key: "prototype.plan.generationPollingExhausted",
  });
  assert.equal(prototypeEvidenceKindKey("parser"), "prototype.plan.evidenceKind.parser");
  assert.deepEqual(prototypeEvidenceDetailMessage("HomePage -> /home"), {
    key: "prototype.plan.evidenceRouteRelationship",
    params: { component: "HomePage", route: "/home" },
  });
  assert.deepEqual(prototypeEvidenceDetailMessage("unrecognized discovery prose", "zh-CN"), {
    key: "prototype.plan.evidenceDetailUnknownLocalized",
  });
  assert.deepEqual(prototypeGenerationErrorMessage("prototype artifact is not valid UTF-8"), {
    key: "prototype.plan.generationError.artifactEncoding",
  });
  assert.deepEqual(
    prototypeGenerationErrorMessage(
      "prototype artifact uses a non-whitelisted external origin: https://example.com",
    ),
    {
      key: "prototype.plan.generationError.artifactExternalOrigin",
      params: { origin: "https://example.com" },
    },
  );
  assert.deepEqual(prototypeDiagnosticMessage("unknown English diagnostic", "zh-CN"), {
    key: "prototype.plan.diagnostic.unknownLocalized",
  });
  assert.deepEqual(prototypeDiagnosticMessage("自定义中文诊断", "zh-CN"), {
    key: "prototype.plan.diagnostic.raw",
    params: { message: "自定义中文诊断" },
  });
  assert.deepEqual(prototypeGenerationErrorMessage("unknown backend detail"), {
    key: "prototype.plan.generationError.raw",
    params: { message: "unknown backend detail" },
  });
  assert.deepEqual(
    prototypeDiagnosticMessage(
      "apps/extension: browser extension surface is detected but not supported in MVP",
    ),
    {
      key: "prototype.plan.diagnostic.packageBrowserExtensionUnsupported",
      params: { package: "apps/extension" },
    },
  );
  assert.deepEqual(prototypePlanErrorMessage("prototype planning runtime returned invalid JSON"), {
    key: "prototype.plan.error.invalidJson",
  });
  assert.deepEqual(
    prototypePlanErrorMessage(
      "prototype planning result did not match the required schema: items.4.states",
    ),
    {
      key: "prototype.plan.error.invalidSchemaDetail",
      params: { detail: "items.4.states" },
    },
  );
  assert.deepEqual(prototypePlanErrorMessage("unrecognized planner failure"), {
    key: "prototype.plan.error.raw",
    params: { message: "unrecognized planner failure" },
  });
  assert.deepEqual(
    prototypePlanErrorMessage("prototype planning reached the token limit for a single page"),
    { key: "prototype.plan.error.pageTokenLimit" },
  );
  assert.deepEqual(
    prototypePlanErrorMessage(
      "prototype planning result did not follow the en-US output locale: title was Chinese",
    ),
    {
      key: "prototype.plan.error.outputLocale",
      params: { locale: "en-US", detail: "title was Chinese" },
    },
  );
  assert.deepEqual(
    prototypeGenerationErrorMessage(
      "prototype UI engineer requires an available Claude CLI command",
    ),
    { key: "prototype.plan.generationError.claudeCliUnavailable" },
  );
});

test("plan recovery issues map to stable localized messages", () => {
  assert.equal(
    prototypePlanRecoveryMessageKey("invalid_resource", null),
    "prototype.plan.analysisResourceMismatch",
  );
  assert.equal(
    prototypePlanRecoveryMessageKey("silent", null),
    "prototype.plan.analysisStreamSilent",
  );
  assert.equal(
    prototypePlanRecoveryMessageKey("disconnected", "request_failed"),
    "prototype.plan.analysisPollingFailed",
  );
  assert.equal(
    prototypePlanRecoveryMessageKey("disconnected", "exhausted"),
    "prototype.plan.analysisPollingExhausted",
  );
  assert.equal(prototypePlanRecoveryMessageKey(null, null), null);
});

test("active generation polling stops at its attempt or deadline budget and can restart", () => {
  let budget = resetPrototypePollingRecovery();
  for (let attempt = 0; attempt < PROTOTYPE_POLL_MAX_ATTEMPTS; attempt += 1) {
    const decision = advancePrototypePollingRecovery(budget, 1_000 + attempt);
    assert.equal(decision.kind, "poll");
    budget = decision.budget;
  }
  assert.equal(advancePrototypePollingRecovery(budget, 2_000).kind, "exhausted");

  const restarted = advancePrototypePollingRecovery(resetPrototypePollingRecovery(), 3_000);
  assert.equal(restarted.kind, "poll");
  assert.equal(restarted.budget.attempts, 1);

  const deadlineBudget = { attempts: 1, startedAt: 5_000 };
  assert.equal(
    advancePrototypePollingRecovery(deadlineBudget, 5_000 + PROTOTYPE_POLL_DEADLINE_MS - 1).kind,
    "poll",
  );
  assert.equal(
    advancePrototypePollingRecovery(deadlineBudget, 5_000 + PROTOTYPE_POLL_DEADLINE_MS).kind,
    "exhausted",
  );
});

test("active generation streams wire bounded persisted polling and recovery resets", () => {
  const source = fs.readFileSync(
    new URL("../src/features/prototype/usePrototypeGenerationLiveRun.ts", import.meta.url),
    "utf8",
  );
  assert.match(source, /const POLL_INTERVAL_MS = 1_500/);
  assert.match(source, /PROTOTYPE_STREAM_SILENCE_MS = 15_000/);
  assert.match(source, /readPrototypeStreamHeartbeat/);
  assert.match(source, /getPrototypeGenerationRun\(runId\)/);
  assert.match(source, /setPollingError/);
  assert.match(source, /recoveryKey/);
  assert.match(source, /resetPrototypePollingRecovery\(\)/);
});

test("prototype review UI exposes retryable config errors and accessible selection state", () => {
  const prototypesPage = fs.readFileSync(
    new URL("../src/features/prototype/ProjectPrototypesPage.tsx", import.meta.url),
    "utf8",
  );
  assert.match(prototypesPage, /setPlanFeatureError/);
  assert.match(prototypesPage, /loadPlanFeatureConfig/);
  assert.doesNotMatch(prototypesPage, /setPlanFeatureEnabled\(false\)/);
  assert.match(prototypesPage, /prototype\.plan\.featureConfigLoadFailed/);

  const prototypePageRail = fs.readFileSync(
    new URL("../src/features/prototype/PrototypePageRail.tsx", import.meta.url),
    "utf8",
  );
  assert.match(prototypePageRail, /aria-current=/);

  const reviewPage = fs.readFileSync(
    new URL("../src/features/prototype/PrototypePlanReviewPage.tsx", import.meta.url),
    "utf8",
  );
  assert.match(reviewPage, /aria-pressed=/);
  assert.match(reviewPage, /aria-current=/);
  assert.match(reviewPage, /isPrototypePlanActionGeneratable\(item\.action\)/);
  assert.match(reviewPage, /patchPrototypePlanSelection/);
  assert.match(reviewPage, /submittedDraftIsCurrent \? "saved" : "idle"/);
  assert.match(reviewPage, /surfaceLabel\(surface, t\)/);
  assert.match(reviewPage, /usePrototypePlanLiveRecovery/);
  assert.match(reviewPage, /applyLatestGenerationRun\(latestRun\)/);

  const planRecovery = fs.readFileSync(
    new URL("../src/features/prototype/usePrototypePlanLiveRecovery.ts", import.meta.url),
    "utf8",
  );
  assert.match(planRecovery, /readPrototypeStreamHeartbeat/);
  assert.match(planRecovery, /heartbeat\.resource_id !== planId/);
  assert.match(planRecovery, /advancePrototypePollingRecovery/);
  assert.match(planRecovery, /getPrototypePlan\(planId\)/);
  assert.match(planRecovery, /setPollingIssue\("exhausted"\)/);
  assert.match(planRecovery, /const markStreamHealthy/);
  assert.match(planRecovery, /recoveryBudget = resetPrototypePollingRecovery\(\)/);
  assert.match(planRecovery, /recoveryKey/);

  const evidenceList = fs.readFileSync(
    new URL("../src/features/prototype/PrototypeEvidenceList.tsx", import.meta.url),
    "utf8",
  );
  assert.match(evidenceList, /evidence\.confidence/);
  assert.match(evidenceList, /evidence\.diagnostic/);
  assert.match(evidenceList, /prototypeDiagnosticMessage\(evidence\.diagnostic, locale\)/);
  assert.match(evidenceList, /evidence\.path/);
  assert.match(evidenceList, /evidence\.evidence_id/);

  const progressPanel = fs.readFileSync(
    new URL("../src/features/prototype/PrototypeGenerationProgressPanel.tsx", import.meta.url),
    "utf8",
  );
  assert.doesNotMatch(progressPanel, /<section[\s\S]{0,180}aria-live="polite"/);
  assert.match(progressPanel, /role="status"[\s\S]{0,100}aria-live="polite"/);
});

test("prototype mobile layout bounds lists and keeps operational text and controls readable", () => {
  const prototypesPage = fs.readFileSync(
    new URL("../src/features/prototype/ProjectPrototypesPage.tsx", import.meta.url),
    "utf8",
  );
  assert.match(prototypesPage, /overflow-x-hidden/);
  assert.match(prototypesPage, /lg:grid-cols-\[15rem_minmax\(0,1fr\)\]/);
  assert.match(prototypesPage, /<PrototypePageRail/);
  assert.match(prototypesPage, /id="prototype-workbench-main"/);
  assert.match(prototypesPage, /min-h-11 sm:min-h-0/);
  assert.match(prototypesPage, /role="progressbar"/);
  assert.match(prototypesPage, /role="status" aria-live="polite" aria-atomic="true"/);

  const pageRail = fs.readFileSync(
    new URL("../src/features/prototype/PrototypePageRail.tsx", import.meta.url),
    "utf8",
  );
  assert.match(pageRail, /overflow-x-auto overscroll-contain/);
  assert.match(pageRail, /lg:flex-col lg:overflow-y-auto/);
  assert.match(pageRail, /aria-current=/);
  assert.match(pageRail, /prototype\.source\./);

  const canvas = fs.readFileSync(
    new URL("../src/features/prototype/PrototypeCanvas.tsx", import.meta.url),
    "utf8",
  );
  assert.match(canvas, /xl:grid-cols-\[minmax\(0,1fr\)_18rem\]/);
  assert.match(canvas, /h-\[70dvh\]/);
  assert.match(canvas, /min-h-11 min-w-11/);
  assert.match(canvas, /<TabsList className="h-11 self-start sm:h-8">/);

  const progress = fs.readFileSync(
    new URL("../src/features/prototype/PrototypeGenerationProgressPanel.tsx", import.meta.url),
    "utf8",
  );
  assert.doesNotMatch(progress, /text-\[(?:10|11)px\]/);
  assert.match(progress, /\[overflow-wrap:anywhere\]/);
  assert.match(progress, /grid-cols-3/);
  assert.match(progress, /grid-cols-2 gap-2/);
  assert.match(progress, /order-1[^\n]*sm:order-2/);
  assert.match(progress, /order-2[^\n]*sm:order-1/);
  assert.match(progress, /flex flex-wrap gap-x-2 gap-y-0\.5 sm:hidden/);
  assert.match(progress, /hidden space-y-1\.5 sm:block/);
  assert.ok(
    progress.indexOf("progress.failedItems.length > 0") <
      progress.indexOf('t("prototype.plan.generationCurrentPages")'),
  );

  const evidence = fs.readFileSync(
    new URL("../src/features/prototype/PrototypeEvidenceList.tsx", import.meta.url),
    "utf8",
  );
  assert.doesNotMatch(evidence, /text-\[(?:10|11)px\]/);
});

test("prototype artifact page links to the latest planning review", () => {
  const prototypesPage = fs.readFileSync(
    new URL("../src/features/prototype/ProjectPrototypesPage.tsx", import.meta.url),
    "utf8",
  );
  assert.match(prototypesPage, /getLatestPrototypePlan\(projectId\)/);
  assert.match(
    prototypesPage,
    /window\.location\.assign\(`\/projects\/\$\{projectId\}\/prototypes\/plans\/\$\{latest\.id\}`\)/,
  );
  assert.match(prototypesPage, /t\("prototype\.plan\.viewLatest"\)/);
  assert.match(prototypesPage, /t\("prototype\.plan\.latestMissing"\)/);
});

test("prototype generation refreshes the plan revision and waits for pending saves", () => {
  const reviewPage = fs.readFileSync(
    new URL("../src/features/prototype/PrototypePlanReviewPage.tsx", import.meta.url),
    "utf8",
  );
  const generationStart = reviewPage.indexOf("const startGeneration");
  const generationEnd = reviewPage.indexOf("const retryGeneration", generationStart);
  const handler = reviewPage.slice(generationStart, generationEnd);

  assert.ok(generationStart >= 0 && generationEnd > generationStart);
  assert.ok(
    handler.indexOf("getPrototypePlan(plan.id)") <
      handler.indexOf("createPrototypeGenerationRun(latest.id, latest.updated_at)"),
  );
  assert.match(handler, /selectionSaving \|\| saveState === "saving"/);
  assert.match(reviewPage, /generationStarting \|\| selectionSaving \|\| saveState === "saving"/);
});

test("prototype generation completion returns to the workbench once", () => {
  const reviewPage = fs.readFileSync(
    new URL("../src/features/prototype/PrototypePlanReviewPage.tsx", import.meta.url),
    "utf8",
  );
  assert.match(reviewPage, /generationNavigationRunIdRef/);
  assert.match(reviewPage, /navigatedGenerationRunIdRef/);
  assert.match(reviewPage, /shouldOpenPrototypeWorkbench\(/);
  assert.match(reviewPage, /generationNavigationRunIdRef\.current = result\.run_id/);
  assert.match(reviewPage, /window\.location\.assign\(`\/projects\/\$\{projectId\}\/prototypes`\)/);
});

test("prototype analysis submission is synchronously guarded against repeated clicks", () => {
  const prototypesPage = fs.readFileSync(
    new URL("../src/features/prototype/ProjectPrototypesPage.tsx", import.meta.url),
    "utf8",
  );
  const handlerStart = prototypesPage.indexOf("const handleCreatePlan");
  const handlerEnd = prototypesPage.indexOf("const openPlanDialog", handlerStart);
  const handler = prototypesPage.slice(handlerStart, handlerEnd);

  assert.ok(handlerStart >= 0 && handlerEnd > handlerStart);
  assert.ok(
    handler.indexOf("if (planCreateInFlightRef.current) return") <
      handler.indexOf("createPrototypePlan(projectId, planInstruction, locale)"),
  );
  assert.match(handler, /planCreateInFlightRef\.current = true/);
  assert.match(handler, /catch \(err\) \{[\s\S]*planCreateInFlightRef\.current = false/);
  assert.doesNotMatch(handler, /finally/);
});

test("prototype plan API uses typed endpoint bodies", async () => {
  await withMockFetch(
    () => new Response(JSON.stringify({ plan_id: "plan-1", status: "queued" }), { status: 202 }),
    async (calls) => {
      await createPrototypePlan("project/1", "preserve navigation");
      const call = calls[0];
      assert.equal(call?.input, "/api/projects/project%2F1/prototype-plans");
      assert.equal(call?.init?.method, "POST");
      assert.deepEqual(jsonRequestBody(call), {
        global_instruction: "preserve navigation",
        output_locale: "zh-CN",
      });
    },
  );
});

test("prototype plan item patch preserves selection payload", async () => {
  await withMockFetch(
    () => new Response(JSON.stringify({ items: [] }), { status: 200 }),
    async (calls) => {
      await patchPrototypePlanItem("item-1", { selected: false });
      const call = calls[0];
      assert.equal(call?.init?.method, "PATCH");
      assert.deepEqual(jsonRequestBody(call), { selected: false });
    },
  );
});

test("prototype bulk selection uses one atomic plan request", async () => {
  await withMockFetch(
    () => new Response(JSON.stringify(plan()), { status: 200 }),
    async (calls) => {
      await patchPrototypePlanSelection("plan/1", {
        item_ids: ["item-1", "item-2"],
        selected: true,
      });
      assert.equal(calls.length, 1);
      assert.equal(calls[0]?.input, "/api/prototype-plans/plan%2F1/selection");
      assert.equal(calls[0]?.init?.method, "PATCH");
      assert.deepEqual(jsonRequestBody(calls[0]), {
        item_ids: ["item-1", "item-2"],
        selected: true,
      });
    },
  );
});

test("generation endpoints expose run and retry contracts", async () => {
  await withMockFetch(
    () => new Response(JSON.stringify({ run_id: "run-1", status: "queued" }), { status: 202 }),
    async (calls) => {
      await createPrototypeGenerationRun("plan-1", "2026-07-11T01:02:03");
      assert.equal(calls[0]?.input, "/api/prototype-plans/plan-1/generate");
      assert.deepEqual(jsonRequestBody(calls[0]), {
        expected_updated_at: "2026-07-11T01:02:03",
      });
      await retryPrototypeGenerationRun("plan-1", "run-1");
      assert.equal(calls[1]?.input, "/api/prototype-plans/plan-1/retry");
      assert.deepEqual(jsonRequestBody(calls[1]), { run_id: "run-1" });
      await getLatestPrototypeGenerationRun("plan-1");
      assert.equal(calls[2]?.input, "/api/prototype-plans/plan-1/generation-run");
    },
  );
  assert.equal(
    getPrototypeGenerationRunEventsUrl("run/1"),
    "/api/prototype-generation-runs/run%2F1/events",
  );
});
