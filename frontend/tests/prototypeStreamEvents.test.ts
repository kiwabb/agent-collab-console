import test from "node:test";
import assert from "node:assert/strict";

import {
  parseSseRecord,
  readFailedPrototypeItems,
  readPrototypeGenerationSnapshot,
  readPrototypePlanSnapshot,
  readPrototypeStreamHeartbeat,
  readSseErrorMessage,
  readSseNumber,
  readSseString,
  readSseStringArray,
} from "../src/features/prototype/prototypeStreamEvents";
import type { PrototypeGenerationItemStatus, PrototypeGenerationRunStatus } from "../src/lib/types";

function messageEvent(payload: unknown): Event {
  return new MessageEvent("message", { data: JSON.stringify(payload) });
}

function evidence(overrides: Record<string, unknown> = {}) {
  return {
    evidence_id: "evidence-1",
    kind: "page-source",
    path: "src/Home.tsx",
    start_line: 1,
    end_line: 3,
    detail: "bounded source evidence",
    content: "export function Home() {}",
    confidence: "high",
    diagnostic: null,
    ...overrides,
  };
}

function planItem(overrides: Record<string, unknown> = {}) {
  return {
    id: "item-1",
    plan_id: "plan-1",
    candidate_id: "candidate-1",
    package_root: "frontend",
    surface_kind: "web",
    route_patterns: ["/home"],
    primary_source_path: "src/Home.tsx",
    source_paths: ["src/Home.tsx"],
    layout_paths: ["src/Layout.tsx"],
    title: "Home",
    summary: "Home page",
    brief: "Restore the current home page using evidence-1",
    states: ["default"],
    evidence_ids: ["evidence-1"],
    evidence: [evidence()],
    confidence: "high",
    discovery_origin: "static",
    review_status: "provisional",
    action: "create",
    selected: true,
    source_hash: "sha256:item",
    prototype_id: null,
    created_at: "2026-07-12T08:00:00",
    updated_at: "2026-07-12T08:00:01",
    ...overrides,
  };
}

function planSnapshot(overrides: Record<string, unknown> = {}) {
  return {
    contract_version: 1,
    id: "plan-1",
    project_id: "project-1",
    status: "ready",
    repository_fingerprint: "sha256:repository",
    scope: {
      packages: ["frontend"],
      supported_packages: ["frontend"],
      candidate_count: 1,
    },
    project_context: {
      product_summary: "Video note workspace",
      audience: "Researchers",
      visual_language: "Quiet operational UI",
      shared_layout: "Left navigation",
    },
    global_instruction: "Restore the current UI",
    output_locale: "en-US",
    analysis_phase: "complete",
    analysis_completed: 1,
    analysis_total: 1,
    diagnostics: [],
    error_message: null,
    created_at: "2026-07-12T08:00:00",
    updated_at: "2026-07-12T08:00:01",
    items: [planItem()],
    ...overrides,
  };
}

function generationItem(
  index: number,
  status: PrototypeGenerationItemStatus,
  overrides: Record<string, unknown> = {},
) {
  const terminal =
    status === "done" || status === "failed" || status === "interrupted" || status === "skipped";
  const phase =
    status === "pending"
      ? "queued"
      : status === "generating"
        ? "streaming"
        : status === "done"
          ? "completed"
          : status;
  return {
    id: `run-item-${index}`,
    run_id: "run-1",
    plan_item_id: `plan-item-${index}`,
    prototype_id: status === "done" ? `prototype-${index}` : null,
    status,
    title: `Page ${index}`,
    attempt: 1,
    phase,
    output_chars: status === "done" ? 4_000 : 800,
    last_event_at: "2026-07-12T08:00:03",
    status_message: status === "generating" ? "Generating page file" : "",
    task_id: status === "generating" ? `task-${index}` : null,
    execution_process_id: status === "generating" ? `process-${index}` : null,
    error_message:
      status === "failed" || status === "interrupted" ? "model output was incomplete" : null,
    version_no: status === "done" ? 1 : null,
    started_at: status === "pending" ? null : "2026-07-12T08:00:01",
    completed_at: terminal ? "2026-07-12T08:00:03" : null,
    created_at: "2026-07-12T08:00:00",
    updated_at: "2026-07-12T08:00:03",
    ...overrides,
  };
}

function generationSnapshot(overrides: Record<string, unknown> = {}) {
  const items = [
    ...Array.from({ length: 8 }, (_, index) => generationItem(index + 1, "done")),
    ...Array.from({ length: 5 }, (_, index) => generationItem(index + 9, "failed")),
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
    completed_at: "2026-07-12T08:00:03",
    created_at: "2026-07-12T08:00:00",
    updated_at: "2026-07-12T08:00:03",
    items,
    ...overrides,
  };
}

function generationSnapshotForItem(
  itemStatus: PrototypeGenerationItemStatus,
  itemOverrides: Record<string, unknown> = {},
) {
  const processed = itemStatus === "pending" || itemStatus === "generating" ? 0 : 1;
  const succeeded = itemStatus === "done" ? 1 : 0;
  const failed = itemStatus === "failed" || itemStatus === "interrupted" ? 1 : 0;
  const running = itemStatus === "generating" ? 1 : 0;
  const pending = itemStatus === "pending" ? 1 : 0;
  const status: PrototypeGenerationRunStatus =
    itemStatus === "pending"
      ? "queued"
      : itemStatus === "generating" || itemStatus === "skipped"
        ? "running"
        : itemStatus === "done"
          ? "completed"
          : itemStatus;
  const runTerminal = status === "completed" || status === "failed" || status === "interrupted";
  return generationSnapshot({
    status,
    total: 1,
    processed,
    succeeded,
    completed: succeeded,
    failed,
    running,
    pending,
    started_at: status === "queued" ? null : "2026-07-12T08:00:01",
    completed_at: runTerminal ? "2026-07-12T08:00:03" : null,
    items: [generationItem(1, itemStatus, itemOverrides)],
  });
}

test("parseSseRecord accepts only object JSON message data", () => {
  assert.deepEqual(parseSseRecord(messageEvent({ type: "ok" })), { type: "ok" });
  assert.equal(parseSseRecord(new MessageEvent("message", { data: "not json" })), null);
  assert.equal(parseSseRecord(new MessageEvent("message", { data: "[]" })), null);
  assert.equal(parseSseRecord(new Event("message")), null);
});

test("SSE primitive readers narrow fields without assertions", () => {
  const record = parseSseRecord(
    messageEvent({ title: "Prototype", count: 3, ok: ["a", "b"], message: "failed" }),
  );
  assert.ok(record);

  assert.equal(readSseString(record, "title"), "Prototype");
  assert.equal(readSseString(record, "missing"), null);
  assert.equal(readSseNumber(record, "count"), 3);
  assert.equal(readSseNumber(record, "title"), null);
  assert.deepEqual(readSseStringArray(record, "ok"), ["a", "b"]);
  assert.equal(readSseErrorMessage(messageEvent({ message: "failed" })), "failed");
});

test("readFailedPrototypeItems validates regenerate-all failure payloads", () => {
  const record = parseSseRecord(messageEvent({ failed: [{ prototype_id: "p2", message: "bad" }] }));
  assert.ok(record);
  assert.deepEqual(readFailedPrototypeItems(record, "failed"), [
    { prototype_id: "p2", message: "bad" },
  ]);

  const invalid = parseSseRecord(messageEvent({ failed: [{ prototype_id: "p2" }] }));
  assert.ok(invalid);
  assert.equal(readFailedPrototypeItems(invalid, "failed"), null);
});

test("prototype plan snapshots validate every nested plan, item, and evidence field", () => {
  const parsed = readPrototypePlanSnapshot(messageEvent(planSnapshot()));
  assert.ok(parsed);
  assert.equal(parsed.project_context.audience, "Researchers");
  assert.equal(parsed.items[0]?.evidence[0]?.content, "export function Home() {}");
  assert.equal(parsed.items[0]?.evidence[0]?.confidence, "high");
  assert.equal(parsed.items[0]?.evidence[0]?.diagnostic, null);
  assert.ok(
    readPrototypePlanSnapshot(
      messageEvent(
        planSnapshot({
          items: [planItem({ evidence: [evidence({ kind: "vue-router-route" })] })],
        }),
      ),
    ),
  );

  assert.equal(
    readPrototypePlanSnapshot(
      messageEvent(
        planSnapshot({ items: [planItem({ evidence: [evidence({ end_line: "3" })] })] }),
      ),
    ),
    null,
  );
  for (const invalidEvidence of [
    evidence({ kind: "unknown-kind" }),
    evidence({ confidence: "certain" }),
    evidence({ diagnostic: 42 }),
  ]) {
    assert.equal(
      readPrototypePlanSnapshot(
        messageEvent(planSnapshot({ items: [planItem({ evidence: [invalidEvidence] })] })),
      ),
      null,
    );
  }
  assert.equal(
    readPrototypePlanSnapshot(
      messageEvent(planSnapshot({ items: [planItem({ evidence_ids: ["unknown-evidence"] })] })),
    ),
    null,
  );
  assert.equal(
    readPrototypePlanSnapshot(
      messageEvent(
        planSnapshot({
          project_context: {
            product_summary: "Video note workspace",
            audience: "Researchers",
            visual_language: "Quiet operational UI",
            shared_layout: "Left navigation",
            extra: "not allowed",
          },
        }),
      ),
    ),
    null,
  );
  assert.equal(
    readPrototypePlanSnapshot(messageEvent(planSnapshot({ contract_version: 2 }))),
    null,
  );
  assert.ok(
    readPrototypePlanSnapshot(
      messageEvent(
        planSnapshot({
          items: [planItem({ action: "missing", source_hash: "", selected: false })],
        }),
      ),
    ),
  );
  assert.equal(
    readPrototypePlanSnapshot(
      messageEvent(planSnapshot({ items: [planItem({ action: "create", source_hash: "" })] })),
    ),
    null,
  );
  assert.equal(
    readPrototypePlanSnapshot(
      messageEvent(planSnapshot({ items: [planItem({ surface_kind: "television" })] })),
    ),
    null,
  );
});

test("prototype plan snapshots require evidence references for source-backed actions", () => {
  for (const action of ["create", "update", "unchanged"] as const) {
    assert.equal(
      readPrototypePlanSnapshot(
        messageEvent(
          planSnapshot({
            items: [planItem({ action, evidence_ids: [] })],
          }),
        ),
      ),
      null,
    );
  }

  for (const action of ["missing", "unsupported"] as const) {
    assert.ok(
      readPrototypePlanSnapshot(
        messageEvent(
          planSnapshot({
            items: [
              planItem({
                action,
                selected: false,
                evidence_ids: [],
                evidence: [],
                ...(action === "missing" ? { source_hash: "" } : {}),
              }),
            ],
          }),
        ),
      ),
    );
  }
});

test("generation snapshots enforce persisted processed counters and nested activity fields", () => {
  const parsed = readPrototypeGenerationSnapshot(messageEvent(generationSnapshot()));
  assert.ok(parsed);
  assert.equal(parsed.processed, 13);
  assert.equal(parsed.succeeded, 8);
  assert.equal(parsed.failed, 5);
  assert.equal(parsed.items.length, 13);

  assert.equal(
    readPrototypeGenerationSnapshot(messageEvent(generationSnapshot({ processed: 8 }))),
    null,
  );
  const invalidItems: Record<string, unknown>[] = [
    generationItem(1, "generating"),
    ...Array.from({ length: 12 }, (_, index) => generationItem(index + 2, "pending")),
  ];
  invalidItems[0] = { ...invalidItems[0], output_chars: "800" };
  assert.equal(
    readPrototypeGenerationSnapshot(
      messageEvent(
        generationSnapshot({
          status: "running",
          processed: 0,
          succeeded: 0,
          completed: 0,
          failed: 0,
          running: 1,
          pending: 12,
          completed_at: null,
          items: invalidItems,
        }),
      ),
    ),
    null,
  );
});

test("generation snapshots accept the persisted item lifecycle matrix", () => {
  const cases: Array<{
    name: string;
    status: PrototypeGenerationItemStatus;
    overrides?: Record<string, unknown>;
  }> = [
    { name: "pending is queued", status: "pending" },
    { name: "generating can be starting", status: "generating", overrides: { phase: "starting" } },
    { name: "generating can be streaming", status: "generating" },
    {
      name: "generating can be persisting",
      status: "generating",
      overrides: { phase: "persisting" },
    },
    { name: "done is completed with a version", status: "done" },
    { name: "failed after start", status: "failed" },
    { name: "failed before start", status: "failed", overrides: { started_at: null } },
    { name: "interrupted after start", status: "interrupted" },
    {
      name: "interrupted before start",
      status: "interrupted",
      overrides: { started_at: null },
    },
    { name: "skipped after start", status: "skipped" },
    { name: "skipped before start", status: "skipped", overrides: { started_at: null } },
  ];

  for (const { name, status, overrides } of cases) {
    assert.ok(
      readPrototypeGenerationSnapshot(messageEvent(generationSnapshotForItem(status, overrides))),
      name,
    );
  }
});

test("generation snapshots reject cross-field item lifecycle contradictions", () => {
  const cases: Array<{
    name: string;
    status: PrototypeGenerationItemStatus;
    overrides: Record<string, unknown>;
  }> = [
    { name: "pending phase mismatch", status: "pending", overrides: { phase: "starting" } },
    { name: "pending has error", status: "pending", overrides: { error_message: "bad" } },
    { name: "pending has version", status: "pending", overrides: { version_no: 1 } },
    {
      name: "pending has started timestamp",
      status: "pending",
      overrides: { started_at: "2026-07-12T08:00:01" },
    },
    {
      name: "pending has completed timestamp",
      status: "pending",
      overrides: { completed_at: "2026-07-12T08:00:03" },
    },
    { name: "generating phase mismatch", status: "generating", overrides: { phase: "queued" } },
    { name: "generating has no start", status: "generating", overrides: { started_at: null } },
    {
      name: "generating has completed timestamp",
      status: "generating",
      overrides: { completed_at: "2026-07-12T08:00:03" },
    },
    {
      name: "generating has error",
      status: "generating",
      overrides: { error_message: "bad" },
    },
    { name: "generating has version", status: "generating", overrides: { version_no: 1 } },
    { name: "done phase mismatch", status: "done", overrides: { phase: "persisting" } },
    { name: "done has no version", status: "done", overrides: { version_no: null } },
    { name: "done has seed version", status: "done", overrides: { version_no: 0 } },
    { name: "done has error", status: "done", overrides: { error_message: "bad" } },
    { name: "done has no start", status: "done", overrides: { started_at: null } },
    { name: "done has no completion", status: "done", overrides: { completed_at: null } },
    { name: "failed phase mismatch", status: "failed", overrides: { phase: "interrupted" } },
    { name: "failed has no error", status: "failed", overrides: { error_message: null } },
    { name: "failed has blank error", status: "failed", overrides: { error_message: "  " } },
    { name: "failed has version", status: "failed", overrides: { version_no: 1 } },
    { name: "failed has no completion", status: "failed", overrides: { completed_at: null } },
    {
      name: "interrupted phase mismatch",
      status: "interrupted",
      overrides: { phase: "failed" },
    },
    {
      name: "interrupted has no error",
      status: "interrupted",
      overrides: { error_message: null },
    },
    { name: "interrupted has version", status: "interrupted", overrides: { version_no: 1 } },
    {
      name: "interrupted has no completion",
      status: "interrupted",
      overrides: { completed_at: null },
    },
    { name: "skipped phase mismatch", status: "skipped", overrides: { phase: "completed" } },
    { name: "skipped has error", status: "skipped", overrides: { error_message: "bad" } },
    { name: "skipped has version", status: "skipped", overrides: { version_no: 1 } },
    { name: "skipped has no completion", status: "skipped", overrides: { completed_at: null } },
    { name: "item has no activity timestamp", status: "done", overrides: { last_event_at: null } },
  ];

  for (const { name, status, overrides } of cases) {
    assert.equal(
      readPrototypeGenerationSnapshot(messageEvent(generationSnapshotForItem(status, overrides))),
      null,
      name,
    );
  }
});

test("generation snapshots count skipped as processed without counting it as failed", () => {
  const items = [
    generationItem(1, "done"),
    generationItem(2, "failed"),
    generationItem(3, "interrupted"),
    generationItem(4, "skipped"),
  ];
  const parsed = readPrototypeGenerationSnapshot(
    messageEvent(
      generationSnapshot({
        status: "partial",
        total: 4,
        processed: 4,
        succeeded: 1,
        completed: 1,
        failed: 2,
        running: 0,
        pending: 0,
        items,
      }),
    ),
  );
  assert.ok(parsed);
  assert.equal(parsed.processed, 4);
  assert.equal(parsed.failed, 2);
  assert.equal(parsed.items.find((item) => item.status === "skipped")?.phase, "skipped");
});

test("generation snapshots reject terminal runs with pending work", () => {
  const items = [generationItem(1, "done"), generationItem(2, "pending")];
  for (const status of ["completed", "partial", "failed", "interrupted"] as const) {
    assert.equal(
      readPrototypeGenerationSnapshot(
        messageEvent(
          generationSnapshot({
            status,
            total: 2,
            processed: 1,
            succeeded: 1,
            completed: 1,
            failed: 0,
            running: 0,
            pending: 1,
            items,
          }),
        ),
      ),
      null,
    );
  }
});

test("generation snapshots reject unversioned legacy payloads", () => {
  const legacyItems = [generationItem(1, "done"), generationItem(2, "failed")].map(
    ({
      phase: _phase,
      output_chars: _outputChars,
      last_event_at: _lastEventAt,
      status_message: _statusMessage,
      task_id: _taskId,
      execution_process_id: _executionProcessId,
      ...item
    }) => item,
  );
  assert.equal(
    readPrototypeGenerationSnapshot(
      messageEvent({
        id: "run-1",
        plan_id: "plan-1",
        project_id: "project-1",
        status: "partial",
        repository_fingerprint: "sha256:repository",
        total: 2,
        completed: 1,
        failed: 1,
        error_message: null,
        created_at: "2026-07-12T08:00:00",
        updated_at: "2026-07-12T08:00:03",
        items: legacyItems,
      }),
    ),
    null,
  );
});

test("prototype stream heartbeat requires version, resource identity, and timestamp", () => {
  assert.deepEqual(
    readPrototypeStreamHeartbeat(
      messageEvent({ contract_version: 1, resource_id: "run-1", sent_at: "2026-07-12T08:00:00" }),
    ),
    { contract_version: 1, resource_id: "run-1", sent_at: "2026-07-12T08:00:00" },
  );
  assert.equal(
    readPrototypeStreamHeartbeat(messageEvent({ resource_id: "run-1", sent_at: "now" })),
    null,
  );
  assert.equal(
    readPrototypeStreamHeartbeat(
      messageEvent({ contract_version: 1, resource_id: "run-1", sent_at: "not-a-timestamp" }),
    ),
    null,
  );
});
