/**
 * Pure helper tests for project remote-update detection (badge + pull toast).
 */
import { strict as assert } from "node:assert";
import test from "node:test";

import {
  describePullResult,
  describeRemoteStatus,
} from "../src/features/projects/projectRemoteStatus";
import type { ProjectPullResult, ProjectRemoteStatus } from "../src/lib/types";

// The real i18n `t` does not interpolate; echo the key so we can assert which
// message was chosen and that {n}/{branch} substitution happens in the helper.
const TEMPLATES: Record<string, string> = {
  "projects.updateNoOrigin": "No remote",
  "projects.updateNoOriginTitle": "No 'origin' remote configured",
  "projects.updateOffline": "Remote unreachable",
  "projects.updateOfflineTitle": "git fetch failed",
  "projects.updateNoRemoteBranch": "No remote branch",
  "projects.updateNotOnDefaultTitle": "Not on default branch {branch}",
  "projects.updateDirty": "Local changes",
  "projects.updateDirtyTitle": "Uncommitted local changes",
  "projects.updateDiverged": "Diverged",
  "projects.updateDivergedTitle": "Local has unpushed commits",
  "projects.updateBehind": "{n} behind",
  "projects.updateBehindTitle": "{n} commit(s) behind remote",
  "projects.updateUpToDate": "Up to date",
  "projects.updateUpToDateTitle": "In sync with remote {branch}",
  "projects.syncSuccess": "Updated — fast-forwarded {n} commit(s)",
  "projects.syncNoop": "Already up to date",
  "projects.syncFailedDirty": "Uncommitted changes — sync cancelled",
  "projects.syncFailedDiverged": "Local history diverged",
  "projects.syncFailedNotOnDefault": "Not on the default branch",
  "projects.syncFailedNoOrigin": "No 'origin' remote configured",
  "projects.syncFailedOffline": "Remote unreachable",
  "projects.syncFailed": "Sync failed",
};
const t = (key: string) => TEMPLATES[key] ?? key;

function status(overrides: Partial<ProjectRemoteStatus> = {}): ProjectRemoteStatus {
  return {
    branch: "main",
    current_branch: "main",
    has_origin: true,
    dirty: false,
    behind: 0,
    ahead: 0,
    can_fast_forward: false,
    fetched: true,
    error: null,
    ...overrides,
  };
}

test("describeRemoteStatus returns null while status is loading", () => {
  assert.equal(describeRemoteStatus(null, t), null);
});

test("up to date → success tone, not syncable", () => {
  const d = describeRemoteStatus(status(), t)!;
  assert.equal(d.label, "Up to date");
  assert.equal(d.tone, "success");
  assert.equal(d.canSync, false);
  assert.match(d.title, /In sync with remote main/);
});

test("behind + clean + can_fast_forward → action tone, syncable, count filled", () => {
  const d = describeRemoteStatus(
    status({ behind: 3, can_fast_forward: true }),
    t,
  )!;
  assert.equal(d.label, "3 behind");
  assert.equal(d.tone, "action");
  assert.equal(d.canSync, true);
  assert.match(d.title, /3 commit\(s\) behind remote/);
});

test("dirty working tree blocks sync even when behind", () => {
  const d = describeRemoteStatus(
    status({ behind: 2, dirty: true, can_fast_forward: false }),
    t,
  )!;
  assert.equal(d.label, "Local changes");
  assert.equal(d.canSync, false);
});

test("diverged (ahead>0) blocks sync", () => {
  const d = describeRemoteStatus(
    status({ behind: 1, ahead: 1, can_fast_forward: false }),
    t,
  )!;
  assert.equal(d.label, "Diverged");
  assert.equal(d.canSync, false);
});

test("no origin → muted, not syncable", () => {
  const d = describeRemoteStatus(status({ has_origin: false, error: "no_origin" }), t)!;
  assert.equal(d.label, "No remote");
  assert.equal(d.tone, "muted");
  assert.equal(d.canSync, false);
});

test("fetch failed → warn tone offline label", () => {
  const d = describeRemoteStatus(status({ error: "fetch_failed" }), t)!;
  assert.equal(d.label, "Remote unreachable");
  assert.equal(d.tone, "warn");
});

test("checked out off the default branch is never syncable", () => {
  const d = describeRemoteStatus(
    status({ current_branch: "feature/x", behind: 2 }),
    t,
  )!;
  assert.equal(d.canSync, false);
  assert.equal(d.tone, "muted");
  assert.equal(d.label, "2 behind");
});

test("describePullResult success fills commit count", () => {
  const r: ProjectPullResult = { success: true, branch: "main", behind_before: 4, new_sha: "abc" };
  const toast = describePullResult(r, t);
  assert.equal(toast.type, "success");
  assert.match(toast.title, /fast-forwarded 4 commit/);
});

test("describePullResult maps refusal reasons to toast types", () => {
  const cases: Array<[ProjectPullResult["reason"], string]> = [
    ["already_up_to_date", "info"],
    ["dirty", "warning"],
    ["diverged", "warning"],
    ["not_on_default", "warning"],
    ["no_origin", "error"],
    ["fetch_failed", "error"],
  ];
  for (const [reason, expectedType] of cases) {
    const toast = describePullResult({ success: false, branch: "main", reason }, t);
    assert.equal(toast.type, expectedType, `reason=${reason}`);
  }
});
