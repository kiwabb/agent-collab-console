import test from "node:test";
import assert from "node:assert/strict";

import type { CodexTask, Project, ProjectEnvVarDisplay, ProjectRunStatus } from "../src/lib/types";
import {
  deriveProjectRunPresentation,
  deriveProjectServiceState,
  deriveProjectStartupState,
  readProjectStartupAnalysis,
  selectProjectRunRefreshError,
  selectProjectRunFailureLine,
  selectLatestProjectStartupTask,
  shouldPollProjectServiceStatus,
  updateProjectRunRefreshError,
} from "../src/features/projects/projectStartupConfig";
import type { ProjectRunRefreshErrors } from "../src/features/projects/projectStartupConfig";

function project(overrides: Partial<Project> = {}): Project {
  return {
    id: "project-1",
    name: "Demo",
    repo_path: "/tmp/demo",
    default_branch: "main",
    origin_url: null,
    setup_script: null,
    run_command: null,
    ...overrides,
  };
}

function task(overrides: Partial<CodexTask> = {}): CodexTask {
  return {
    id: "task-1",
    session_id: "project-1",
    project_id: "project-1",
    issue_id: null,
    phase: "operations",
    title: "Generate Startup Scripts",
    prompt: "Analyze",
    role: "operations_engineer",
    executor: "codex",
    status: "done",
    result: null,
    parent_task_id: null,
    task_kind: "project_script_suggestion",
    blocked_by_help_id: null,
    workspace_path: "/tmp/demo",
    git_branch: "main",
    git_base_branch: "main",
    git_worktree_path: null,
    git_merge_status: "open",
    git_last_commit_sha: null,
    resume_session_id: null,
    resume_message_id: null,
    last_execution_process_id: null,
    created_at: "2026-07-10T08:00:00Z",
    updated_at: "2026-07-10T08:01:00Z",
    ...overrides,
  };
}

const stopped: ProjectRunStatus = {
  running: false,
  command: null,
  pid: null,
  started_at: null,
  exit_code: null,
  service: {
    state: "not_configured",
    url: null,
    http_status: null,
    checked_at: null,
    error: null,
  },
};

test("selectLatestProjectStartupTask ignores unrelated tasks and selects newest analysis", () => {
  const older = task();
  const newer = task({ id: "task-2", updated_at: "2026-07-10T09:00:00Z" });
  const unrelated = task({
    id: "task-3",
    task_kind: "implementation",
    updated_at: "2026-07-10T10:00:00Z",
  });

  assert.equal(selectLatestProjectStartupTask([older, unrelated, newer])?.id, "task-2");
});

test("readProjectStartupAnalysis narrows task result JSON", () => {
  const analysis = readProjectStartupAnalysis(
    task({
      result: JSON.stringify({
        access_url: "http://localhost:3015",
        notes: ["Use Docker Compose", 42],
      }),
    }),
  );

  assert.deepEqual(analysis, {
    taskId: "task-1",
    status: "done",
    accessUrl: "http://localhost:3015",
    notes: ["Use Docker Compose"],
    updatedAt: "2026-07-10T08:01:00Z",
  });
});

test("readProjectStartupAnalysis tolerates malformed result JSON", () => {
  const analysis = readProjectStartupAnalysis(task({ result: "{" }));
  assert.equal(analysis?.accessUrl, null);
  assert.deepEqual(analysis?.notes, []);
});

test("deriveProjectStartupState reports never analyzed", () => {
  assert.deepEqual(
    deriveProjectStartupState({
      project: project(),
      envVars: [],
      latestTask: null,
      runStatus: stopped,
    }),
    {
      analysis: "pending",
      configure: "pending",
      run: "pending",
      envCount: 0,
      missingCount: 0,
      unsavedCount: 0,
      canStart: false,
      runOutcome: "idle",
      serviceState: "not_configured",
    },
  );
});

test("deriveProjectStartupState reports missing environment values", () => {
  const envVars: ProjectEnvVarDisplay[] = [
    { name: "API_KEY", secret: true, source: "agent", is_set: false },
  ];
  const state = deriveProjectStartupState({
    project: project({ run_command: "npm run dev" }),
    envVars,
    latestTask: task(),
    runStatus: stopped,
  });

  assert.equal(state.analysis, "complete");
  assert.equal(state.configure, "error");
  assert.equal(state.missingCount, 1);
  assert.equal(state.canStart, false);
});

test("deriveProjectStartupState reports ready and running states", () => {
  const ready = deriveProjectStartupState({
    project: project({ run_command: "npm run dev" }),
    envVars: [{ name: "PORT", secret: false, source: "agent", is_set: true, value: "3000" }],
    latestTask: task(),
    runStatus: stopped,
  });
  const running = deriveProjectStartupState({
    project: project({ run_command: "npm run dev" }),
    envVars: [],
    latestTask: task(),
    runStatus: {
      ...stopped,
      running: true,
      command: "npm run dev",
      pid: 123,
      started_at: "2026-07-10T10:00:00Z",
    },
  });

  assert.equal(ready.run, "ready");
  assert.equal(ready.canStart, true);
  assert.equal(ready.runOutcome, "idle");
  assert.equal(running.run, "complete");
  assert.equal(running.canStart, false);
  assert.equal(running.runOutcome, "running");
});

test("deriveProjectStartupState exposes a failed terminal run and allows retry", () => {
  const failed = deriveProjectStartupState({
    project: project({ run_command: "docker compose up" }),
    envVars: [],
    latestTask: task(),
    runStatus: {
      running: false,
      command: "docker compose up",
      pid: 123,
      started_at: "2026-07-10T10:13:45Z",
      exit_code: 1,
      service: stopped.service,
    },
  });

  assert.equal(failed.run, "error");
  assert.equal(failed.runOutcome, "failed");
  assert.equal(failed.canStart, true);
});

test("selectProjectRunFailureLine prefers an actionable error over trailing log noise", () => {
  const line = selectProjectRunFailureLine([
    { seq: 1, stream: "stderr", line: "pulling image", ts: "2026-07-10T10:13:45Z" },
    {
      seq: 2,
      stream: "stderr",
      line: "failed to resolve source metadata: TLS handshake timeout",
      ts: "2026-07-10T10:14:30Z",
    },
    { seq: 3, stream: "stderr", line: "View build details", ts: "2026-07-10T10:14:31Z" },
  ]);

  assert.equal(line, "failed to resolve source metadata: TLS handshake timeout");
});

test("deriveProjectStartupState blocks start while environment edits are unsaved", () => {
  const state = deriveProjectStartupState({
    project: project({ run_command: "npm run dev" }),
    envVars: [{ name: "PORT", secret: false, source: "agent", is_set: true, value: "3000" }],
    latestTask: task(),
    runStatus: stopped,
    unsavedCount: 1,
  });

  assert.equal(state.configure, "pending");
  assert.equal(state.unsavedCount, 1);
  assert.equal(state.canStart, false);
});

test("deriveProjectServiceState keeps process ownership separate from reachability", () => {
  const external: ProjectRunStatus = {
    ...stopped,
    service: {
      state: "reachable",
      url: "http://127.0.0.1:3000/",
      http_status: 503,
      checked_at: "2026-07-12T08:00:00Z",
      error: null,
    },
  };
  const managedStarting: ProjectRunStatus = {
    ...external,
    running: true,
    command: "npm run dev",
    pid: 123,
    started_at: "2026-07-12T08:00:00Z",
    service: {
      ...external.service,
      state: "unreachable",
      http_status: null,
      error: "connection_failed",
    },
  };

  assert.equal(deriveProjectServiceState(external), "reachable");
  assert.equal(deriveProjectServiceState(managedStarting), "unreachable");
  assert.equal(deriveProjectServiceState(null), "unknown");
});

test("service status polling recovers initial loads and tracks configured endpoints", () => {
  const reachable: ProjectRunStatus = {
    ...stopped,
    service: {
      state: "reachable",
      url: "http://127.0.0.1:3000/",
      http_status: 200,
      checked_at: "2026-07-12T08:00:00Z",
      error: null,
    },
  };
  const unreachable: ProjectRunStatus = {
    ...reachable,
    service: {
      ...reachable.service,
      state: "unreachable",
      http_status: null,
      error: "connection_failed",
    },
  };
  const invalid: ProjectRunStatus = {
    ...reachable,
    service: {
      ...reachable.service,
      state: "invalid_url",
      url: null,
      http_status: null,
      error: "host_not_loopback",
    },
  };

  assert.equal(shouldPollProjectServiceStatus(null), true);
  assert.equal(shouldPollProjectServiceStatus(reachable), true);
  assert.equal(shouldPollProjectServiceStatus(unreachable), true);
  assert.equal(shouldPollProjectServiceStatus(stopped), false);
  assert.equal(shouldPollProjectServiceStatus(invalid), false);
});

test("run refresh errors recover independently by request source", () => {
  let errors: ProjectRunRefreshErrors = {
    status: "status unavailable",
    logs: "logs unavailable",
  };

  errors = updateProjectRunRefreshError(errors, "logs", null);
  assert.deepEqual(errors, { status: "status unavailable", logs: null });
  assert.equal(selectProjectRunRefreshError(errors), "status unavailable");

  errors = updateProjectRunRefreshError(errors, "status", null);
  assert.deepEqual(errors, { status: null, logs: null });
  assert.equal(selectProjectRunRefreshError(errors), null);

  errors = updateProjectRunRefreshError(errors, "logs", "logs unavailable");
  errors = updateProjectRunRefreshError(errors, "status", null);
  assert.equal(selectProjectRunRefreshError(errors), "logs unavailable");
});

test("deriveProjectStartupState blocks duplicate start for an externally reachable service", () => {
  const runStatus: ProjectRunStatus = {
    ...stopped,
    service: {
      state: "reachable",
      url: "http://127.0.0.1:3000/",
      http_status: 404,
      checked_at: "2026-07-12T08:00:00Z",
      error: null,
    },
  };
  const state = deriveProjectStartupState({
    project: project({ run_command: "npm run dev" }),
    envVars: [],
    latestTask: task(),
    runStatus,
  });

  assert.equal(state.run, "complete");
  assert.equal(state.runOutcome, "idle");
  assert.equal(state.serviceState, "reachable");
  assert.equal(state.canStart, false);
  assert.equal(deriveProjectRunPresentation(runStatus, state), "external_reachable");
});

test("deriveProjectRunPresentation reports a managed process waiting for service readiness", () => {
  const runStatus: ProjectRunStatus = {
    ...stopped,
    running: true,
    command: "npm run dev",
    pid: 123,
    started_at: "2026-07-12T08:00:00Z",
    service: {
      state: "unreachable",
      url: "http://127.0.0.1:3000/",
      http_status: null,
      checked_at: "2026-07-12T08:00:01Z",
      error: "connection_failed",
    },
  };
  const state = deriveProjectStartupState({
    project: project({ run_command: "npm run dev" }),
    envVars: [],
    latestTask: task(),
    runStatus,
  });

  assert.equal(deriveProjectRunPresentation(runStatus, state), "managed_starting");
  assert.equal(state.canStart, false);
});
