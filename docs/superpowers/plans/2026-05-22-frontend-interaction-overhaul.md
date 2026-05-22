# Frontend Interaction Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Build a major interaction layer that makes the multi-agent console easier to operate, recover, navigate, and understand without changing backend contracts.

**Architecture:** Add pure interaction-state derivation helpers first, then shared UI primitives, then apply them to shell, command palette, issue detail, task execution, conductor/live activity, and utility pages. Keep all behavior on existing routes and APIs.

**Tech Stack:** Next.js, React, TypeScript, Tailwind CSS, lucide-react, existing API/store/hooks, node test runner, ESLint.

---

### Task 1: Add Tested Interaction-State Utilities

**Files:**
- Create: `frontend/src/features/workbench/interaction/interactionState.ts`
- Test: `frontend/tests/interactionState.test.ts`

- [x] **Step 1: Create tests for attention and next-action derivation**

Write tests that cover:

```ts
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  deriveAttentionItems,
  deriveIssueNextAction,
  deriveRunRecoveryActions,
} from "../src/features/workbench/interaction/interactionState";

describe("interactionState", () => {
  it("prioritizes approvals, failures, and running work in attention items", () => {
    const items = deriveAttentionItems({
      issues: [
        { id: "i1", title: "Needs review", status: "awaiting_approval", current_phase: "architecture", updated_at: "2026-05-22T08:00:00Z" } as any,
        { id: "i2", title: "Broken run", status: "failed", current_phase: "development", updated_at: "2026-05-22T08:01:00Z" } as any,
        { id: "i3", title: "Running", status: "in_progress", current_phase: "testing", updated_at: "2026-05-22T08:02:00Z" } as any,
      ],
      tasks: [],
      processes: [],
      approvals: [],
    });
    assert.deepEqual(items.map((item) => item.kind), ["approval", "failure", "running"]);
    assert.equal(items[0].href, "/issues/i1");
  });

  it("explains why issue next action is blocked by active task", () => {
    const action = deriveIssueNextAction({
      issue: { id: "i1", status: "open", current_phase: "requirements", title: "Do it" } as any,
      tasks: [{ id: "t1", issue_id: "i1", role: "product_manager", status: "running" } as any],
      artifacts: [],
    });
    assert.equal(action.enabled, false);
    assert.match(action.disabledReason ?? "", /running/i);
  });

  it("offers rerun and logs recovery for failed processes", () => {
    const actions = deriveRunRecoveryActions({
      task: { id: "t1", status: "failed", executor: "codex" } as any,
      process: { id: "p1", task_id: "t1", status: "failed" } as any,
    });
    assert.deepEqual(actions.map((action) => action.id), ["open_logs", "rerun_same", "change_executor"]);
  });
});
```

- [x] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm run test -- tests/interactionState.test.ts`

Expected: fails because `interactionState.ts` does not exist.

- [x] **Step 3: Implement pure derivation helpers**

Create `frontend/src/features/workbench/interaction/interactionState.ts`:

```ts
import type { Approval, Artifact, CodexIssue, CodexTask, ExecutionProcess } from "@/lib/types";

export type AttentionKind = "approval" | "failure" | "running" | "question";

export interface AttentionItem {
  id: string;
  kind: AttentionKind;
  title: string;
  detail: string;
  href: string;
  priority: number;
}

export interface IssueNextAction {
  id: "approve_plan" | "review_qa" | "run_phase" | "inspect_failure" | "wait_for_agent" | "open_tasks";
  label: string;
  detail: string;
  enabled: boolean;
  disabledReason?: string;
  href?: string;
}

export interface RecoveryAction {
  id: "open_logs" | "rerun_same" | "change_executor" | "submit_review" | "stop_run";
  label: string;
  detail: string;
  tone: "neutral" | "primary" | "warning" | "danger";
}

export function deriveAttentionItems(input: {
  issues: CodexIssue[];
  tasks: CodexTask[];
  processes: ExecutionProcess[];
  approvals: Approval[];
}): AttentionItem[] {
  const items: AttentionItem[] = [];
  for (const issue of input.issues) {
    const title = issue.title || issue.id.slice(0, 8);
    if (issue.status === "awaiting_approval" || issue.status === "awaiting_review") {
      items.push({ id: issue.id, kind: "approval", title, detail: "Human review required", href: `/issues/${issue.id}`, priority: 10 });
    } else if (issue.status === "failed") {
      items.push({ id: issue.id, kind: "failure", title, detail: "Workflow needs recovery", href: `/issues/${issue.id}?tab=tasks`, priority: 8 });
    } else if (issue.status === "in_progress") {
      items.push({ id: issue.id, kind: "running", title, detail: `Phase ${issue.current_phase ?? "unknown"}`, href: `/issues/${issue.id}`, priority: 6 });
    }
  }
  for (const task of input.tasks) {
    if ((task.review_comment || "").startsWith("[CLARIFY] ")) {
      items.push({ id: task.id, kind: "question", title: task.title || task.id.slice(0, 8), detail: "Agent question waiting for answer", href: task.issue_id ? `/issues/${task.issue_id}?tab=tasks&taskId=${task.id}` : "/approvals", priority: 9 });
    }
  }
  return items.sort((a, b) => b.priority - a.priority).slice(0, 8);
}

export function deriveIssueNextAction(input: {
  issue: CodexIssue | null;
  tasks: CodexTask[];
  artifacts: Artifact[];
}): IssueNextAction {
  const issue = input.issue;
  if (!issue) return { id: "open_tasks", label: "Select an issue", detail: "No issue is loaded.", enabled: false };
  const issueTasks = input.tasks.filter((task) => task.issue_id === issue.id);
  const hasActiveTask = issueTasks.some((task) => ["running", "responding"].includes(String(task.status || "").toLowerCase()));
  const hasFailure = issue.status === "failed" || issueTasks.some((task) => String(task.status || "").toLowerCase() === "failed");
  if (hasFailure) return { id: "inspect_failure", label: "Inspect failure", detail: "Open task logs and recovery actions.", enabled: true, href: `/issues/${issue.id}?tab=tasks` };
  if (issue.status === "awaiting_approval") return { id: "approve_plan", label: "Review plan", detail: "Plan approval is required before agents continue.", enabled: true };
  if (issue.status === "awaiting_review") return { id: "review_qa", label: "Review QA", detail: "QA passed and awaits human review.", enabled: true };
  if (hasActiveTask) return { id: "wait_for_agent", label: "Agent running", detail: "Live work is in progress.", enabled: false, disabledReason: "A task is currently running. Wait for completion or open the live run." };
  return { id: "run_phase", label: "Run current phase", detail: `Dispatch the next agent for ${issue.current_phase ?? "this phase"}.`, enabled: true };
}

export function deriveRunRecoveryActions(input: {
  task: CodexTask | null;
  process: ExecutionProcess | null;
}): RecoveryAction[] {
  const status = String(input.process?.status || input.task?.status || "").toLowerCase();
  if (status === "failed") {
    return [
      { id: "open_logs", label: "Open logs", detail: "Inspect the failure before retrying.", tone: "neutral" },
      { id: "rerun_same", label: "Rerun same executor", detail: "Retry with the current runtime.", tone: "primary" },
      { id: "change_executor", label: "Change executor", detail: "Switch runtime before rerun.", tone: "warning" },
    ];
  }
  if (status === "running" || status === "responding") {
    return [{ id: "stop_run", label: "Stop run", detail: "Terminate the active execution process.", tone: "danger" }];
  }
  if (status === "completed" || status === "done") {
    return [{ id: "submit_review", label: "Submit for review", detail: "Move completed work into review.", tone: "primary" }];
  }
  return [];
}
```

- [x] **Step 4: Run tests and typecheck**

Run: `cd frontend && npm run test -- tests/interactionState.test.ts`

Expected: interaction tests pass.

Run: `cd frontend && npx tsc --noEmit --pretty false`

Expected: typecheck passes.

---

### Task 2: Build Shared Interaction UI Primitives

**Files:**
- Create: `frontend/src/components/ui/interaction-empty-state.tsx`
- Create: `frontend/src/features/workbench/components/AttentionRail.tsx`
- Create: `frontend/src/features/issues/components/IssueActionStrip.tsx`
- Create: `frontend/src/features/runs/components/RunRecoveryPanel.tsx`

- [x] **Step 1: Create `InteractionEmptyState`**

Create a reusable empty/loading/error state with title, description, action, and tone.

```tsx
"use client";

import type { ReactNode } from "react";
import { AlertCircle, Inbox, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface Props {
  tone?: "empty" | "loading" | "error";
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
}

export function InteractionEmptyState({ tone = "empty", title, description, action }: Props) {
  const Icon = tone === "loading" ? Loader2 : tone === "error" ? AlertCircle : Inbox;
  return (
    <div className={cn("enterprise-card flex min-h-[220px] flex-col items-center justify-center rounded-3xl px-6 py-10 text-center", tone === "error" && "border-error/30")}>
      <div className={cn("mb-4 flex size-12 items-center justify-center rounded-2xl border", tone === "error" ? "border-error/30 bg-error/10 text-error" : "border-border-subtle bg-surface-input text-text-muted")}>
        <Icon className={cn("size-5", tone === "loading" && "animate-spin")} />
      </div>
      <h2 className="text-base font-semibold text-foreground">{title}</h2>
      {description && <p className="mt-2 max-w-md text-sm leading-relaxed text-text-muted">{description}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function EmptyStateAction(props: React.ComponentProps<typeof Button>) {
  return <Button size="sm" className="bg-brand text-black hover:bg-brand-strong" {...props} />;
}
```

- [x] **Step 2: Create `AttentionRail`**

Render attention items from `deriveAttentionItems` as compact links in the shell.

```tsx
"use client";

import Link from "next/link";
import { AlertTriangle, CheckCircle2, HelpCircle, Radio } from "lucide-react";
import type { AttentionItem } from "@/features/workbench/interaction/interactionState";
import { cn } from "@/lib/utils";

const ICONS = {
  approval: CheckCircle2,
  failure: AlertTriangle,
  running: Radio,
  question: HelpCircle,
};

export function AttentionRail({ items }: { items: AttentionItem[] }) {
  if (items.length === 0) return null;
  return (
    <div className="mx-3 mb-3 rounded-2xl border border-border-subtle bg-surface/80 px-3 py-2 backdrop-blur-sm">
      <div className="mb-2 flex items-center justify-between text-[10px] font-mono uppercase tracking-[0.18em] text-text-muted">
        <span>attention</span>
        <span>{items.length}</span>
      </div>
      <div className="flex gap-2 overflow-x-auto">
        {items.map((item) => {
          const Icon = ICONS[item.kind];
          return (
            <Link key={`${item.kind}:${item.id}`} href={item.href} className={cn("flex min-w-[210px] items-center gap-2 rounded-xl border border-border-subtle bg-surface-raised/70 px-3 py-2 text-left hover:border-brand/40 hover:bg-surface-hover")}>
              <Icon className="size-4 shrink-0 text-brand" />
              <span className="min-w-0">
                <span className="block truncate text-[12px] font-semibold text-foreground">{item.title}</span>
                <span className="block truncate text-[10px] text-text-muted">{item.detail}</span>
              </span>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
```

- [x] **Step 3: Create `IssueActionStrip`**

Render the next action and disabled reason.

```tsx
"use client";

import Link from "next/link";
import { Info, Play, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { IssueNextAction } from "@/features/workbench/interaction/interactionState";

export function IssueActionStrip({ action, onPrimary }: { action: IssueNextAction; onPrimary?: () => void }) {
  return (
    <section className="enterprise-panel rounded-3xl px-4 py-3">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div className="flex items-start gap-3">
          <span className="flex size-9 items-center justify-center rounded-2xl bg-brand/10 text-brand">
            {action.id === "review_qa" ? <ShieldCheck size={17} /> : <Play size={17} />}
          </span>
          <div>
            <div className="text-sm font-semibold text-foreground">{action.label}</div>
            <div className="mt-0.5 text-xs text-text-muted">{action.disabledReason || action.detail}</div>
          </div>
        </div>
        {action.href ? (
          <Button asChild size="sm" className="bg-brand text-black hover:bg-brand-strong">
            <Link href={action.href}>Open</Link>
          </Button>
        ) : (
          <Button size="sm" disabled={!action.enabled} onClick={onPrimary} className="bg-brand text-black hover:bg-brand-strong disabled:opacity-40">
            {action.enabled ? "Continue" : "Blocked"}
          </Button>
        )}
      </div>
      {action.disabledReason && (
        <div className="mt-3 flex items-start gap-2 rounded-2xl border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning">
          <Info className="mt-0.5 size-3.5 shrink-0" />
          <span>{action.disabledReason}</span>
        </div>
      )}
    </section>
  );
}
```

- [x] **Step 4: Create `RunRecoveryPanel`**

Render recovery actions from `deriveRunRecoveryActions`.

```tsx
"use client";

import { Button } from "@/components/ui/button";
import type { RecoveryAction } from "@/features/workbench/interaction/interactionState";

interface Props {
  actions: RecoveryAction[];
  onAction: (id: RecoveryAction["id"]) => void;
}

export function RunRecoveryPanel({ actions, onAction }: Props) {
  if (actions.length === 0) return null;
  return (
    <section className="enterprise-card rounded-2xl p-4">
      <div className="mb-3">
        <h3 className="text-sm font-semibold text-foreground">Recovery actions</h3>
        <p className="text-xs text-text-muted">Choose a safe next step for this run.</p>
      </div>
      <div className="grid gap-2">
        {actions.map((action) => (
          <button key={action.id} type="button" onClick={() => onAction(action.id)} className="rounded-xl border border-border-subtle bg-surface/70 px-3 py-2 text-left hover:border-brand/40 hover:bg-surface-hover">
            <span className="block text-[12px] font-semibold text-foreground">{action.label}</span>
            <span className="block text-[11px] text-text-muted">{action.detail}</span>
          </button>
        ))}
      </div>
    </section>
  );
}
```

- [x] **Step 5: Run typecheck**

Run: `cd frontend && npx tsc --noEmit --pretty false`

Expected: no type errors.

---

### Task 3: Upgrade Command Palette Into an Action Palette

**Files:**
- Modify: `frontend/src/features/workbench/components/CommandPalette.tsx`
- Modify: `frontend/src/features/workbench/components/AppHeader.tsx`
- Test: `frontend/tests/commandPaletteSource.test.ts`

- [x] **Step 1: Add source test for action rows**

Create a source-level test that asserts the palette includes action-aware fields and keyboard hints.

```ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

test("CommandPalette exposes action-oriented rows", () => {
  const source = fs.readFileSync(new URL("../src/features/workbench/components/CommandPalette.tsx", import.meta.url), "utf8");
  assert.match(source, /actionLabel/);
  assert.match(source, /review/i);
  assert.match(source, /rerun/i);
  assert.match(source, /Search in Knowledge|searchInKnowledge/);
});
```

- [x] **Step 2: Extend `Hit` with action metadata**

Update `Hit`:

```ts
interface Hit {
  id: string;
  kind: "issue" | "workspace" | "project" | "nav" | "artifact" | "knowledge-link" | "action";
  label: string;
  hint?: string;
  href: string;
  snippet?: string;
  actionLabel?: string;
  actionTone?: "primary" | "warning" | "danger" | "neutral";
}
```

- [x] **Step 3: Add issue action hits**

In `hits`, append action rows for issues:

```ts
const issueActionHits: Hit[] = issues.flatMap((i) => {
  const rows: Hit[] = [];
  if (i.status === "awaiting_approval" || i.status === "awaiting_review") {
    rows.push({
      id: `action-review-${i.id}`,
      kind: "action",
      label: i.title || i.id.slice(0, 8),
      hint: "Human review required",
      href: `/issues/${i.id}?tab=diff`,
      actionLabel: "Review",
      actionTone: "primary",
    });
  }
  if (i.status === "failed") {
    rows.push({
      id: `action-rerun-${i.id}`,
      kind: "action",
      label: i.title || i.id.slice(0, 8),
      hint: "Open recovery actions",
      href: `/issues/${i.id}?tab=tasks`,
      actionLabel: "Rerun / recover",
      actionTone: "warning",
    });
  }
  return rows;
}).slice(0, 8);
```

- [x] **Step 4: Render action badges and footer hints**

Inside each hit row, show `actionLabel` when present:

```tsx
{hit.actionLabel && (
  <span className="ml-auto rounded-full border border-brand/30 bg-brand/10 px-2 py-0.5 text-[10px] font-semibold text-brand">
    {hit.actionLabel}
  </span>
)}
```

Add footer text:

```tsx
<div className="border-t border-border-subtle px-3 py-2 text-[10px] text-text-muted">
  Enter to open · Esc to close · type "review", "failed", or an issue title
</div>
```

- [x] **Step 5: Run tests**

Run: `cd frontend && npm run test -- tests/commandPaletteSource.test.ts`

Expected: pass.

---

### Task 4: Add Shell Attention Rail

**Files:**
- Modify: `frontend/src/features/workbench/WorkbenchShell.tsx`
- Modify: `frontend/src/features/workbench/components/AppStatusBar.tsx`
- Test: `frontend/tests/interactionState.test.ts`

- [x] **Step 1: Wire attention derivation in shell**

In `WorkbenchShell`, read existing issue/task/process context where available or fetch lightweight data for global attention. Use `deriveAttentionItems`.

Implementation shape:

```tsx
const [attentionItems, setAttentionItems] = useState<AttentionItem[]>([]);

useEffect(() => {
  let cancelled = false;
  async function loadAttention() {
    const [issues, tasks, approvals] = await Promise.all([
      getCodexIssues(null, null).catch(() => []),
      getCodexTasks(null, null).catch(() => []),
      getPendingApprovals().then((r) => r.pending).catch(() => []),
    ]);
    if (!cancelled) {
      setAttentionItems(deriveAttentionItems({ issues, tasks, processes: [], approvals }));
    }
  }
  void loadAttention();
  const id = window.setInterval(loadAttention, 30_000);
  return () => {
    cancelled = true;
    window.clearInterval(id);
  };
}, []);
```

- [x] **Step 2: Render `AttentionRail` below main canvas only when needed**

Place it in the shell after the main content row and before `AppStatusBar`:

```tsx
<AttentionRail items={attentionItems} />
<AppStatusBar />
```

- [x] **Step 3: Add event refresh hooks**

Refresh attention on bus events:

```tsx
useBusEventEffect({
  match: busEventMatchers.typeIn("task_status", "approval_required", "approval_resolved", "issue_updated", "issue_created"),
  onEvent: () => { void loadAttention(); },
  throttleMs: 800,
});
```

- [x] **Step 4: Run typecheck and smoke**

Run: `cd frontend && npx tsc --noEmit --pretty false`

Expected: pass.

---

### Task 5: Add Issue Cockpit Next-Action Strip

**Files:**
- Modify: `frontend/src/features/issues/IssueDetailPage.tsx`
- Create/modify: `frontend/src/features/issues/components/IssueActionStrip.tsx`
- Test: `frontend/tests/interactionState.test.ts`

- [x] **Step 1: Load tasks/artifacts needed by next-action derivation**

Use already available issue data where possible. If tasks/artifacts are not available in `IssueDetailPage`, fetch minimal data:

```tsx
const [issueTasks, setIssueTasks] = useState<CodexTask[]>([]);
const [issueArtifacts, setIssueArtifacts] = useState<Artifact[]>([]);
```

Refresh on issue load and task/artifact bus events.

- [x] **Step 2: Derive and render action strip**

```tsx
const nextAction = useMemo(
  () => deriveIssueNextAction({ issue, tasks: issueTasks, artifacts: issueArtifacts }),
  [issue, issueTasks, issueArtifacts],
);
```

Render below hero and above pipeline:

```tsx
<div className="mt-4">
  <IssueActionStrip action={nextAction} onPrimary={() => {
    if (nextAction.id === "approve_plan") setSteerOpen(false);
    if (nextAction.id === "run_phase") onTabChange("tasks");
  }} />
</div>
```

- [x] **Step 3: Explain disabled states**

Ensure the strip shows `disabledReason` when present and links to tasks/live run where useful.

- [x] **Step 4: Run tests**

Run: `cd frontend && npm run test -- tests/interactionState.test.ts`

Expected: pass.

---

### Task 6: Upgrade Task Execution Recovery

**Files:**
- Modify: `frontend/src/features/workbench/components/TaskExecutionSheet.tsx`
- Create/modify: `frontend/src/features/runs/components/RunRecoveryPanel.tsx`

- [x] **Step 1: Derive recovery actions**

Inside `TaskExecutionSheet`:

```tsx
const recoveryActions = useMemo(
  () => deriveRunRecoveryActions({ task: currentTask, process: selectedProcess ?? null }),
  [currentTask, selectedProcess],
);
```

- [x] **Step 2: Render recovery panel above run detail**

Place `RunRecoveryPanel` at the top of the execution sidebar content.

- [x] **Step 3: Wire actions to existing handlers**

Use existing functions:

```tsx
function handleRecoveryAction(id: RecoveryAction["id"]) {
  if (id === "open_logs") return;
  if (id === "rerun_same") {
    void rerunCodexTask(currentTask.id, {
      executor: currentTask.executor ?? undefined,
      provider: currentTask.provider ?? undefined,
      model: currentTask.model ?? undefined,
    });
  }
  if (id === "change_executor") {
    // switch to run-detail tab and focus existing executor selector
  }
  if (id === "stop_run" && selectedProcess) {
    void terminateCodexTask(selectedProcess.task_id);
  }
}
```

- [x] **Step 4: Replace console-only failures with toasts**

Current handlers often `console.error`. Convert user-triggered failures into `addToast({ type: "error", ... })`.

- [x] **Step 5: Run lint and typecheck**

Run: `cd frontend && npm run lint`

Expected: no new errors.

Run: `cd frontend && npx tsc --noEmit --pretty false`

Expected: pass.

---

### Task 7: Improve Conductor and Live-Agent Interaction

**Files:**
- Modify: `frontend/src/features/issues/components/LiveThinkingDock.tsx`
- Modify: `frontend/src/features/workflow/ConductorLogPanel.tsx`
- Modify: `frontend/src/features/issues/components/ConductorChatBar.tsx`

- [x] **Step 1: Add dock action buttons**

Add visible actions to `LiveThinkingDock` header:

```tsx
<button type="button" onClick={() => setExpanded(true)}>Expand</button>
<button type="button" onClick={() => window.dispatchEvent(new CustomEvent("open-conductor-log", { detail: { issueId } }))}>Open log</button>
```

- [x] **Step 2: Make completed streams dismissible but recoverable**

Persist dismissed state per issue in session storage:

```ts
const key = `live-thinking-dismissed:${issueId}`;
window.sessionStorage.setItem(key, "1");
```

Only auto-show again when a new running role appears.

- [x] **Step 3: Add visible send failure in `ConductorChatBar`**

Replace silent catch with local error:

```tsx
const [error, setError] = useState<string | null>(null);
...
catch (err) {
  setError(err instanceof Error ? err.message : "Failed to send message");
}
```

Render the error below the input.

- [x] **Step 4: Run typecheck**

Run: `cd frontend && npx tsc --noEmit --pretty false`

Expected: pass.

---

### Task 8: Standardize Empty, Loading, and Error States

**Files:**
- Modify: `frontend/src/features/approvals/ApprovalsPage.tsx`
- Modify: `frontend/src/features/artifacts/ArtifactsHubPage.tsx`
- Modify: `frontend/src/features/knowledge/KnowledgePage.tsx`
- Modify: `frontend/src/features/projects/ProjectsPage.tsx`
- Modify: `frontend/src/features/help/HelpPage.tsx`

- [x] **Step 1: Replace generic empty/loading blocks with `InteractionEmptyState`**

For each page:

```tsx
<InteractionEmptyState
  tone="empty"
  title="No artifacts produced yet"
  description="Run an issue through the workflow to produce PRD, design, and QA reports."
  action={<EmptyStateAction onClick={() => router.push("/")}>Open Inbox</EmptyStateAction>}
/>
```

- [x] **Step 2: Add page-specific recovery actions**

Use these actions:

* Approvals empty: Open Inbox.
* Artifacts empty: Open Projects or latest issue.
* Knowledge empty query: Clear filters or reindex.
* Projects empty: Create project.
* Help: Start from Projects.

- [x] **Step 3: Verify no duplicated empty-state styling remains**

Run:

```bash
cd frontend
rg "py-20 text-center|Loading…|No artifacts|Nothing is waiting" src/features
```

Expected: only intentional text remains, wrapped in `InteractionEmptyState`.

---

### Task 9: Accessibility and Keyboard Pass

**Files:**
- Modify: `frontend/src/features/workbench/components/CommandPalette.tsx`
- Modify: `frontend/src/features/issues/components/LiveThinkingDock.tsx`
- Modify: `frontend/src/features/workflow/ConductorLogPanel.tsx`
- Modify: `frontend/src/components/ui/interaction-empty-state.tsx`

- [x] **Step 1: Add ARIA roles and labels**

Command palette root:

```tsx
<div role="dialog" aria-modal="true" aria-label="Command palette">
```

Results list:

```tsx
<div role="listbox" aria-label="Command results">
```

Rows:

```tsx
aria-selected={i === selectedIdx}
role="option"
```

- [x] **Step 2: Restore focus after close**

Track the active element before opening and restore on close.

- [x] **Step 3: Ensure Escape closes all overlays**

Verify command palette closes on Escape, conductor sheet closes on Escape through the sheet component, and live dock collapses from expanded to compact on Escape.

- [x] **Step 4: Respect reduced motion**

Avoid adding motion that ignores existing reduced-motion preferences. Use CSS utilities and existing preference provider.

---

### Task 10: Final Verification

**Files:**
- Modify: only files needed to fix issues found during verification

- [x] **Step 1: Run lint**

Run: `cd frontend && npm run lint`

Expected: exits successfully. Existing warnings may remain, but no new blocking errors.

- [x] **Step 2: Run typecheck**

Run: `cd frontend && npx tsc --noEmit --pretty false`

Expected: exits successfully.

- [x] **Step 3: Run frontend tests**

Run: `cd frontend && npm run test`

Expected: all tests pass.

- [x] **Step 4: Route smoke test**

With dev server running on port 4000, verify:

```bash
/usr/bin/curl -s -o /tmp/codex-smoke.html -w '%{http_code}\n' http://localhost:4000/
/usr/bin/curl -s -o /tmp/codex-smoke.html -w '%{http_code}\n' http://localhost:4000/projects
/usr/bin/curl -s -o /tmp/codex-smoke.html -w '%{http_code}\n' http://localhost:4000/approvals
/usr/bin/curl -s -o /tmp/codex-smoke.html -w '%{http_code}\n' http://localhost:4000/artifacts
/usr/bin/curl -s -o /tmp/codex-smoke.html -w '%{http_code}\n' http://localhost:4000/knowledge
/usr/bin/curl -s -o /tmp/codex-smoke.html -w '%{http_code}\n' http://localhost:4000/settings
/usr/bin/curl -s -o /tmp/codex-smoke.html -w '%{http_code}\n' http://localhost:4000/help
```

Expected: all return `200`.

- [x] **Step 5: Update Trellis docs**

If the shared interaction primitives become conventions, update `.trellis/spec/ccgui/frontend/component-guidelines.md` with the rule: "derive interaction state in pure helpers; render it through shared primitives."
