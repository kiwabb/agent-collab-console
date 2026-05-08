# Executor Selector Visual Tightening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the oversized executor toggle in issue creation and task execution with a lighter segmented control that matches the existing dashboard visual language.

**Architecture:** Extract one shared executor selector component so both the issue creation form and task board use the same compact interaction pattern. Keep the component purely presentational with a controlled value and a small set of style variants, then wire it into the two existing screens without changing their behavior or layout.

**Tech Stack:** React, Next.js App Router, TypeScript, Tailwind CSS, lucide-react, existing `cn` helper

---

### Task 1: Add a shared executor selector

**Files:**
- Create: `frontend/src/components/ui/executor-toggle.tsx`

- [ ] **Step 1: Write the component**

```tsx
"use client";

import { cn } from "@/lib/utils";

type Executor = "codex" | "claude";

interface ExecutorToggleProps {
  value: Executor;
  onChange: (value: Executor) => void;
  codexLabel: string;
  claudeLabel: string;
  className?: string;
}

export function ExecutorToggle({
  value,
  onChange,
  codexLabel,
  claudeLabel,
  className,
}: ExecutorToggleProps) {
  return (
    <div
      className={cn(
        "grid grid-cols-2 gap-1 p-1 rounded-xl border border-border-subtle bg-surface-input/50",
        className,
      )}
    >
      <button
        type="button"
        onClick={() => onChange("codex")}
        className={cn(
          "h-8 rounded-lg text-[10px] font-bold uppercase tracking-[0.12em] transition-all",
          value === "codex"
            ? "bg-brand text-background shadow-sm"
            : "text-text-muted hover:text-foreground hover:bg-surface-hover",
        )}
      >
        {codexLabel}
      </button>
      <button
        type="button"
        onClick={() => onChange("claude")}
        className={cn(
          "h-8 rounded-lg text-[10px] font-bold uppercase tracking-[0.12em] transition-all",
          value === "claude"
            ? "bg-brand text-background shadow-sm"
            : "text-text-muted hover:text-foreground hover:bg-surface-hover",
        )}
      >
        {claudeLabel}
      </button>
    </div>
  );
}
```

- [ ] **Step 2: Keep the component visually low-noise**

Run the app in your head against the existing phase selector styling and keep the selected state obvious without increasing card height or introducing a stronger border/shadow than the surrounding form fields.

- [ ] **Step 3: Verify the component file is isolated**

Confirm the component has no app-specific data fetching or task logic, only controlled value and styling.

### Task 2: Replace the issue-creation selector

**Files:**
- Modify: `frontend/src/features/issues/IssueGrid.tsx`

- [ ] **Step 1: Swap in the shared component**

```tsx
import { ExecutorToggle } from "@/components/ui/executor-toggle";
```

```tsx
<div className="mb-5">
  <label className="block text-[10px] font-black uppercase tracking-[0.2em] text-text-muted mb-2">
    {t("task.executor")}
  </label>
  <ExecutorToggle
    value={newExecutor}
    onChange={setNewExecutor}
    codexLabel={t("executor.codex")}
    claudeLabel={t("executor.claude")}
  />
</div>
```

- [ ] **Step 2: Remove the previous ad hoc button group**

Delete the old two-button grid block so the form no longer has an oversized visual anchor.

- [ ] **Step 3: Keep form spacing unchanged**

Leave the title, description, and action buttons exactly where they are so the surrounding layout stays familiar.

### Task 3: Replace the task-board selector

**Files:**
- Modify: `frontend/src/features/tasks/TaskBoard.tsx`

- [ ] **Step 1: Swap in the shared component**

```tsx
import { ExecutorToggle } from "@/components/ui/executor-toggle";
```

```tsx
<div>
  <label className="block text-[10px] font-black uppercase tracking-[0.2em] text-text-muted mb-2">
    {t("task.executor")}
  </label>
  <ExecutorToggle
    value={executor}
    onChange={setExecutor}
    codexLabel={t("executor.codex")}
    claudeLabel={t("executor.claude")}
    className="w-56"
  />
</div>
```

- [ ] **Step 2: Remove the old grid selector**

Delete the previous full-width button group so the header reads as a small control instead of a competing panel.

- [ ] **Step 3: Preserve the run button behavior**

Keep `onRunPhase(phase.id, executor)` unchanged so the visual tweak does not alter task execution semantics.

### Task 4: Verify the UI still feels like one system

**Files:**
- Test: `frontend/src/features/issues/IssueGrid.tsx`
- Test: `frontend/src/features/tasks/TaskBoard.tsx`

- [ ] **Step 1: Run the frontend checks**

Run: `npm test`
Expected: pass

- [ ] **Step 2: Run TypeScript**

Run: `npx tsc --noEmit`
Expected: pass

- [ ] **Step 3: Open the page and inspect the selector**

Run the app locally and verify the selector now reads as a small control aligned with the existing phase selector styling, without clipping text or pushing the surrounding layout apart.

- [ ] **Step 4: Commit the visual cleanup**

```bash
git add frontend/src/components/ui/executor-toggle.tsx frontend/src/features/issues/IssueGrid.tsx frontend/src/features/tasks/TaskBoard.tsx docs/superpowers/plans/2026-04-24-executor-selector-visual-tightening.md
git commit -m "fix: tighten executor selector styling"
```

