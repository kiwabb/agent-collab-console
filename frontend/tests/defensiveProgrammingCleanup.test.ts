import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { readBudgetSteeringEvent } from "../src/features/issues/components/useIssueBudget";

const SRC_ROOT = join(process.cwd(), "src");

function readSource(relativePath: string): string {
  return readFileSync(join(SRC_ROOT, relativePath), "utf-8");
}

function snippetAround(source: string, token: string, radius = 500): string {
  const index = source.indexOf(token);
  assert.notEqual(index, -1, `Expected source to contain ${token}`);
  return source.slice(Math.max(0, index - radius), index + token.length + radius);
}

test("useIssueBudget narrows websocket budget events before updating state", () => {
  const source = readSource("features/issues/components/useIssueBudget.ts");

  assert.match(source, /function isBudgetSteeringEventPayload/);
  assert.match(source, /function readBudgetSteeringEvent/);
  assert.match(source, /const next = readBudgetSteeringEvent\(event\)/);
  assert.doesNotMatch(source, /event as IssueBudgetStatus/);
  assert.doesNotMatch(source, /soft_warn_ratio \?\? 0\.8/);
  assert.doesNotMatch(source, /has_ceiling \?\? true/);
  assert.doesNotMatch(source, /budget_source \?\? "issue"/);
});

test("useIssueBudget normalizes real backend budget steering events", () => {
  const warning = readBudgetSteeringEvent({
    type: "budget_warning",
    issue_id: "issue-1",
    spent_usd: 8,
    reserved_usd: 0.5,
    effective_spend_usd: 8.5,
    budget_usd: 10,
    remaining_usd: 1.5,
    used_ratio: 0.85,
    budget_source: "default",
    soft_warn_ratio: 0.8,
  });

  assert.deepEqual(warning, {
    issue_id: "issue-1",
    spent_usd: 8,
    budget_usd: 10,
    remaining_usd: 1.5,
    used_ratio: 0.85,
    soft_warn: true,
    over_budget: false,
    soft_warn_ratio: 0.8,
    has_ceiling: true,
    budget_source: "default",
  });

  const exceeded = readBudgetSteeringEvent({
    type: "budget_exceeded",
    issue_id: "issue-1",
    spent_usd: 10,
    reserved_usd: 0.5,
    effective_spend_usd: 10.5,
    budget_usd: 10,
    remaining_usd: -0.5,
    used_ratio: 1.05,
    budget_source: "issue",
  });

  assert.deepEqual(exceeded, {
    issue_id: "issue-1",
    spent_usd: 10,
    budget_usd: 10,
    remaining_usd: -0.5,
    used_ratio: 1.05,
    soft_warn: true,
    over_budget: true,
    soft_warn_ratio: 1,
    has_ceiling: true,
    budget_source: "issue",
  });

  assert.equal(
    readBudgetSteeringEvent({
      type: "budget_warning",
      issue_id: "issue-1",
      spent_usd: 8,
      budget_usd: 10,
      remaining_usd: 2,
      used_ratio: 0.8,
      budget_source: "default",
    }),
    null,
  );
  assert.equal(
    readBudgetSteeringEvent({
      type: "budget_exceeded",
      issue_id: "issue-1",
      spent_usd: "10",
      budget_usd: 10,
      remaining_usd: -0.5,
      used_ratio: 1.05,
      budget_source: "issue",
    }),
    null,
  );
});
test("WorkbenchPage keeps executionProcessesAll as an array and preserves process output on reload failure", () => {
  const source = readSource("features/workbench/WorkbenchPage.tsx");

  assert.doesNotMatch(source, /Object\.values\(executionProcessesAll\)/);
  assert.match(source, /const executionProcesses = executionProcessesAll;/);

  const reloadFailure = snippetAround(source, "workbench process output reload failed");
  assert.match(reloadFailure, /setError\(msg\)/);
  assert.doesNotMatch(reloadFailure, /setProcessLogs\(\[\]\)/);
  assert.doesNotMatch(reloadFailure, /setProcessMessages\(\[\]\)/);
  assert.match(source, /console\.error\("workbench selectedProjectId sync failed:"/);
});

test("CommandPalette keeps a visible load error state", () => {
  const source = readSource("features/workbench/components/CommandPalette.tsx");

  assert.match(source, /const \[loadError, setLoadError\] = useState<string \| null>\(null\)/);
  assert.match(source, /console\.error\("CommandPalette initial load failed:"/);
  assert.match(source, /setLoadError\(msg\)/);
  assert.match(source, /\{loadError && \(/);
});

test("BranchListView validates dates without dead try/catch", () => {
  const source = readSource("features/projects/BranchListView.tsx");

  assert.match(source, /Number\.isNaN\(date\.getTime\(\)\) \? iso : date\.toLocaleString\(\)/);
  assert.doesNotMatch(source, /try \{/);
});

test("Task conversation helpers rely on typed arrays without redundant fallbacks", () => {
  const source = readSource("lib/taskConversationDetailUtils.ts");

  assert.doesNotMatch(source, /\(executionProcesses \|\| \[\]\)/);
  assert.doesNotMatch(source, /\(executionProcesses \?\? \[\]\)/);
  assert.doesNotMatch(source, /taskMessages \|\| \[\]/);
  assert.doesNotMatch(source, /taskMessages \?\? \[\]/);
  assert.match(source, /const processMessages = executionProcesses\.flatMap/);
  assert.match(source, /messages: buildConversationMessages\(\[\.\.\.taskMessages,/);
});
