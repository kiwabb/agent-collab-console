import test from "node:test";
import assert from "node:assert/strict";

import { buildAuditRoleGroups } from "../src/features/audit/auditRoleChains";
import type { AuditLog } from "../src/lib/api";

function row(overrides: Partial<AuditLog>): AuditLog {
  return {
    id: "audit-1",
    created_at: "2026-06-27T12:00:00",
    category: "tool_use",
    actor: "dispatch_subagent",
    issue_id: "issue-1",
    task_id: null,
    conductor_task_id: "ct-1",
    execution_process_id: null,
    correlation_id: null,
    status: "ok",
    duration_ms: null,
    payload_json: "{}",
    error: null,
    role: null,
    role_label: null,
    turn_index: null,
    sub_index: null,
    call_name: null,
    call_input: null,
    call_output: null,
    call_summary: null,
    ...overrides,
  };
}

test("buildAuditRoleGroups groups audit entries by role and turn", () => {
  const groups = buildAuditRoleGroups([
    row({
      id: "result",
      category: "tool_result",
      role: "architect",
      role_label: "Architect",
      turn_index: 1,
      sub_index: 2,
      call_summary: "architecture ready",
    }),
    row({
      id: "use",
      role: "architect",
      role_label: "Architect",
      turn_index: 1,
      sub_index: 1,
      call_summary: "dispatch architect",
    }),
    row({
      id: "engineer",
      category: "cli_spawn",
      actor: "codex",
      task_id: "task-engineer",
      conductor_task_id: null,
      role: "engineer",
      role_label: "Engineer",
      call_summary: "cli_spawn",
    }),
  ]);

  assert.equal(groups.length, 2);
  assert.equal(groups[0]?.role, "architect");
  assert.equal(groups[0]?.turns[0]?.turnIndex, 1);
  assert.deepEqual(
    groups[0]?.turns[0]?.entries.map((entry) => entry.entry.id),
    ["use", "result"],
  );
  assert.equal(groups[1]?.roleLabel, "Engineer");
});

test("buildAuditRoleGroups falls back to conductor when no target role exists", () => {
  const groups = buildAuditRoleGroups([
    row({
      id: "llm",
      category: "llm_call",
      actor: "conductor",
      call_summary: "LLM request",
    }),
  ]);

  assert.equal(groups[0]?.role, "conductor");
  assert.equal(groups[0]?.roleLabel, "Conductor");
  assert.equal(groups[0]?.entries[0]?.summary, "LLM request");
});

test("buildAuditRoleGroups routes taskless rows to system instead of agent or unassigned", () => {
  const groups = buildAuditRoleGroups([
    row({
      id: "git",
      category: "git_command",
      actor: "git",
      task_id: null,
      conductor_task_id: null,
      call_summary: "git status --short",
      call_output: { exit_code: 0, stdout: "ok", stderr: "" },
    }),
    row({
      id: "event",
      category: "event",
      actor: "scheduler",
      task_id: null,
      conductor_task_id: null,
      call_summary: "background sweep",
    }),
  ]);

  const system = groups.find((group) => group.role === "system");
  const git = system?.entries.find((entry) => entry.entry.id === "git");
  assert.equal(system?.roleLabel, "System");
  assert.deepEqual(git?.entry.call_output, { exit_code: 0, stdout: "ok", stderr: "" });
  assert.deepEqual(
    system?.entries.map((entry) => entry.entry.id).sort(),
    ["event", "git"],
  );
  assert.equal(groups.some((group) => group.role === "agent"), false);
  assert.equal(groups.some((group) => group.role === "unassigned"), false);
});
