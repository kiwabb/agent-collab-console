import test from "node:test";
import assert from "node:assert/strict";
import { readCompactSource as readSource } from "./sourceTestUtils";

test("workspace console is a scheduler surface that opens issue detail rows", () => {
  const consoleSource = readSource("features/workspaces/WorkspaceConsole.tsx");
  const rowSource = readSource("features/workspaces/IssueRow.tsx");

  assert.doesNotMatch(consoleSource, /RunDetailColumn/);
  assert.doesNotMatch(consoleSource, /chatCodexTask/);
  assert.doesNotMatch(consoleSource, /textarea/);
  assert.match(consoleSource, /router\.push\(`\/issues\/\$\{issueId\}`\)/);
  assert.match(rowSource, /getIssueStatusBucket/);
  assert.match(rowSource, /getPhaseProgress/);
  assert.match(rowSource, /onClick=\{onOpen\}/);
});

test("workspace console uses dense operations queue chrome", () => {
  const consoleSource = readSource("features/workspaces/WorkspaceConsole.tsx");
  const headerSource = readSource("features/workspaces/WorkspaceConsoleHeader.tsx");
  const panelSource = readSource("features/workspaces/IssueListPanel.tsx");
  const rowSource = readSource("features/workspaces/IssueRow.tsx");

  assert.match(panelSource, /data-density="operations-queue"/);
  assert.match(rowSource, /grid-cols-\[minmax\(0,1fr\)_128px_156px_84px\]/);
  assert.match(rowSource, /min-h-\[72px\]/);
  assert.doesNotMatch(consoleSource, /radial-gradient/);
  assert.doesNotMatch(headerSource, /rounded-\[1\.4rem\]|rounded-full|tracking-\[-/);
  assert.doesNotMatch(panelSource, /rounded-\[1\.4rem\]|rounded-2xl|shadow-\[0_24px_80px/);
  assert.doesNotMatch(rowSource, /hover:-translate-y|rounded-2xl|tracking-\[-/);
});

test("workspace operations queue loading uses dispatch motion", () => {
  const panelSource = readSource("features/workspaces/IssueListPanel.tsx");

  assert.match(
    panelSource,
    /import \{ AgentThinkingIndicator \} from "@\/components\/ui\/AgentThinkingIndicator";/,
  );
  assert.match(panelSource, /data-density="workspace-console-dispatch-loading"/);
  assert.match(
    panelSource,
    /className="motion-essential relative flex h-48 min-h-0 items-center justify-center gap-2 overflow-hidden text-sm font-semibold text-text-muted"/,
  );
  assert.match(panelSource, /<AgentThinkingIndicator phase="dispatching" size=\{16\} \/>/);
  assert.match(panelSource, /animate-shimmer-sweep/);
  assert.doesNotMatch(
    panelSource,
    /<Loader variant="card" label=\{t\("workspace\.console\.loading"\)\}/,
  );
});

test("workspace console marks running issue rows with scheduling motion", () => {
  const rowSource = readSource("features/workspaces/IssueRow.tsx");

  assert.match(rowSource, /isIssueScheduling/);
  assert.match(rowSource, /data-density="workspace-scheduling-row"/);
  assert.match(rowSource, /data-density="workspace-scheduling-role"/);
  assert.match(rowSource, /<AgentThinkingIndicator/);
  assert.match(rowSource, /animate-shimmer-sweep/);
  assert.match(rowSource, /phase="dispatching"/);
  assert.match(rowSource, /motion-essential/);
  assert.doesNotMatch(rowSource, /animate-pulse/);
});

test("workspace console header marks active queue totals with scheduling motion", () => {
  const headerSource = readSource("features/workspaces/WorkspaceConsoleHeader.tsx");

  assert.match(headerSource, /const isQueueScheduling = counts\.running > 0/);
  assert.match(
    headerSource,
    /data-density=\{isQueueScheduling \? "workspace-console-active-summary" : "workspace-console-summary"\}/,
  );
  assert.match(headerSource, /isQueueScheduling && "motion-essential"/);
  assert.match(headerSource, /<AgentThinkingIndicator phase="dispatching" size=\{12\}/);
  assert.match(headerSource, /animate-shimmer-sweep/);
  assert.doesNotMatch(headerSource, /animate-pulse/);
});

test("workspace console running filter uses dispatch motion for live work", () => {
  const headerSource = readSource("features/workspaces/WorkspaceConsoleHeader.tsx");

  assert.match(
    headerSource,
    /const isRunningFilterLive = filter === "running" && counts\.running > 0/,
  );
  assert.match(
    headerSource,
    /data-density=\{isRunningFilterLive \? "workspace-console-running-filter" : "workspace-console-filter"\}/,
  );
  assert.match(headerSource, /isRunningFilterLive && "motion-essential"/);
  assert.match(headerSource, /<AgentThinkingIndicator phase="dispatching" size=\{10\}/);
  assert.match(headerSource, /isRunningFilterLive && \(/);
  assert.match(headerSource, /animate-shimmer-sweep/);
  assert.doesNotMatch(headerSource, /animate-pulse/);
});
