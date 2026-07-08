import test from "node:test";
import assert from "node:assert/strict";

import { getAgentTimeline } from "../src/lib/api/audit";
import { getDictionaryValue } from "../src/lib/i18n";
import { readCompactSource } from "./sourceTestUtils";
import { withMockJsonFetch } from "./fetchTestUtils";
import { at } from "./testAssertions";

const TIMELINE_I18N_KEYS = [
  "auditLog.view.flat",
  "auditLog.view.chain",
  "auditLog.roleChain.summary.failed",
  "auditLog.roleChain.summary.running",
  "auditLog.roleChain.summary.success",
  "auditLog.detail.task",
  "auditLog.detail.execution",
  "auditLog.detail.model",
  "auditLog.detail.cwd",
  "auditLog.detail.pid",
  "auditLog.detail.runCommand",
  "auditLog.detail.setupScript",
  "auditLog.trace.runtime",
  "auditLog.trace.messages",
  "auditLog.trace.logs",
  "auditLog.trace.semanticView",
  "auditLog.trace.rawView",
  "auditLog.trace.viewRuntime",
] as const;

test("getAgentTimeline hits the semantic agent-timeline endpoint", async () => {
  await withMockJsonFetch({ items: [], next_cursor: null }, async (calls) => {
    const result = await getAgentTimeline({
      category: ["cli_spawn", "event"],
      issueId: "issue/1",
      taskId: "task 1",
      since: "2026-07-08T10:00:00",
      until: "2026-07-08T11:00:00",
      q: "startup script",
      cursor: "cursor-1",
      limit: 25,
    });

    assert.deepEqual(result, { items: [], next_cursor: null });
    assert.equal(calls.length, 1);

    const call = at(calls, 0, "fetch call");
    const url = new URL(String(call.input), "http://localhost");

    assert.equal(url.pathname, "/api/codex/agent-timeline");
    assert.deepEqual(url.searchParams.getAll("category"), ["cli_spawn", "event"]);
    assert.equal(url.searchParams.get("issue_id"), "issue/1");
    assert.equal(url.searchParams.get("task_id"), "task 1");
    assert.equal(url.searchParams.get("since"), "2026-07-08T10:00:00");
    assert.equal(url.searchParams.get("until"), "2026-07-08T11:00:00");
    assert.equal(url.searchParams.get("q"), "startup script");
    assert.equal(url.searchParams.get("cursor"), "cursor-1");
    assert.equal(url.searchParams.get("limit"), "25");
    assert.equal(call.init, undefined);
  });
});

test("AuditLogPage uses Agent Timeline API for timeline mode", () => {
  const page = readCompactSource("features/audit/AuditLogPage.tsx");

  assert.match(page, /type ViewMode = "flat" \| "timeline"/);
  assert.match(page, /const \[timelineOperations, setTimelineOperations\]/);
  assert.equal(page.match(/\bgetAgentTimeline\(/g)?.length, 2);
  assert.match(page, /setTimelineOperations\(page\.items\)/);
  assert.match(page, /setTimelineOperations\(\(prev\) => \[\.\.\.prev, \.\.\.page\.items\]\)/);
  assert.doesNotMatch(page, /getAuditLogChains/);
  assert.doesNotMatch(page, /buildAuditRoleGroups/);
});

test("Agent Timeline hides machine event names for known semantic rows", () => {
  const view = readCompactSource("features/audit/AuditRoleChainView.tsx");

  assert.match(view, /function entryMachineName\(entry: AuditLog\): string \| null/);
  assert.match(
    view,
    /type === "task_status" \|\| type === "project_script_updated" \|\| entry\.category === "cli_spawn"/,
  );
  assert.match(view, /const machineName = entryMachineName\(entry\)/);
  assert.doesNotMatch(view, /\{entry\.call_name &&/);
});

test("Agent Timeline cards prefer execution titles over first step labels", () => {
  const view = readCompactSource("features/audit/AuditRoleChainView.tsx");

  assert.match(
    view,
    /operation\.timeline_kind === "agent_execution" && operation\.title/,
  );
  assert.match(view, /operation\.entry_count > 1 && operation\.task_title/);
});

test("Agent Timeline renders trace controls at the step level", () => {
  const view = readCompactSource("features/audit/AuditRoleChainView.tsx");

  assert.match(view, /function shouldShowStepTrace\(entry: AuditLog\): boolean/);
  assert.match(view, /entry\.category === "cli_spawn" \|\| type === "project_script_updated"/);
  assert.match(view, /\{shouldShowStepTrace\(entry\) && <TraceDetailPanel entry=\{entry\} \/>\}/);
  assert.doesNotMatch(view, /traceEntry && <TraceDetailPanel/);
  assert.match(view, /auditLog\.trace\.viewRuntime/);
  assert.match(view, /function TraceRuntimeBlock/);
});

test("Agent Timeline renders CLI runtime with task execution log blocks", () => {
  const view = readCompactSource("features/audit/AuditRoleChainView.tsx");

  assert.match(view, /normalizeLogs\(logEvents\)/);
  assert.match(view, /compactTraceRuntimeEntries\(runtimeEntries\)/);
  assert.match(view, /function traceLogEvents\(logs: Record<string, unknown>\[\]\): LogEvent\[\]/);
  assert.match(view, /function isApiFailureEntry\(entry: NormalizedEntry\): boolean/);
  assert.match(view, /useState<"semantic" \| "raw">\("semantic"\)/);
  assert.match(view, /<TraceRawRuntimeContent rows=\{rows\} \/>/);
  assert.match(view, /<ToolBlock entry=\{entry\} \/>/);
  assert.match(view, /<MessageMarkdown content=\{entry\.content\} \/>/);
});

test("Agent Timeline user-facing keys exist in both locales", () => {
  for (const key of TIMELINE_I18N_KEYS) {
    const zh = getDictionaryValue("zh-CN", key as never);
    const en = getDictionaryValue("en-US", key as never);

    assert.ok(zh && zh !== key, `zh-CN missing or fell back for ${key}`);
    assert.ok(en && en !== key, `en-US missing or fell back for ${key}`);
  }
});
