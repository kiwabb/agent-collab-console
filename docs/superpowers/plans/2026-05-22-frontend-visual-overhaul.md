# Frontend Visual Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Rebuild the frontend into a modern enterprise control-room UI with a consistent light/dark hybrid visual system and stronger multi-agent identity, without changing product behavior.

**Architecture:** Treat the workbench shell as the visual foundation, then restyle the dense issue/conductor surfaces and the remaining top-level pages to match the same hierarchy, spacing, and surface language. Prefer shared shell/page primitives over one-off styling so the redesign stays consistent across inbox, projects, issues, agents, approvals, artifacts, knowledge, settings, and help.

**Tech Stack:** Next.js, React, Tailwind CSS, shadcn/ui, lucide-react, Framer Motion, browser smoke checks, ESLint, TypeScript.

---

### Task 1: Rebuild the app shell language

**Files:**
- Modify: `frontend/src/app/globals.css`
- Modify: `frontend/src/features/workbench/WorkbenchShell.tsx`
- Modify: `frontend/src/features/workbench/components/AppHeader.tsx`
- Modify: `frontend/src/features/workbench/components/AppSidebar.tsx`
- Modify: `frontend/src/features/workbench/components/AppStatusBar.tsx`

- [x] **Step 1: Restyle the global visual tokens**

Update the shell palette so surfaces feel like a modern mixed-light/dark backend: softer blue-gray panels, clearer text contrast, and less harsh borders.

```css
/* globals.css */
:root {
  --background: var(--color-background);
  --foreground: var(--color-foreground);
  --card: color-mix(in srgb, var(--color-surface-raised) 92%, white 8%);
  --popover: color-mix(in srgb, var(--color-surface) 96%, white 4%);
  --muted: color-mix(in srgb, var(--color-surface-input) 88%, white 12%);
  --accent: color-mix(in srgb, var(--color-surface-hover) 90%, white 10%);
}
```

- [x] **Step 2: Redesign the shell chrome**

Make the header, sidebar, main canvas, and status bar read as one composed control room instead of separate widgets. Keep the current routing and data flow intact.

```tsx
// WorkbenchShell.tsx
<div className="relative isolate min-h-dvh overflow-hidden bg-background text-foreground">
  <div aria-hidden className="pointer-events-none absolute inset-0 opacity-60" />
  <div className="relative z-10 flex min-h-dvh flex-col">
    <AppHeader ... />
    <div className="flex flex-1 min-h-0 gap-3 px-3 pb-3">
      <AppSidebar />
      <main className="flex-1 min-h-0 overflow-hidden rounded-[28px] border border-border-subtle bg-surface/80 shadow-[0_20px_60px_-30px_rgba(0,0,0,0.75)] backdrop-blur-sm">
        <div className="h-full overflow-auto">{children}</div>
      </main>
    </div>
    <AppStatusBar />
  </div>
</div>
```

- [x] **Step 3: Tighten navigation and header hierarchy**

Refine breadcrumbs, search, and account/help actions so the top bar feels premium rather than crowded. Keep the command palette shortcut behavior unchanged.

```tsx
// AppHeader.tsx
<header className="h-14 shrink-0 border-b border-border-subtle/80 bg-surface/85 backdrop-blur-md flex items-center gap-3.5 px-4">
  ...
  <div className="ml-auto flex items-center gap-2.5">
    {right}
    <SearchInput onOpen={() => setPaletteOpen(true)} t={t} />
    <HelpButton />
    <AccountPopover />
  </div>
</header>
```

- [x] **Step 4: Reduce sidebar noise and improve scanning**

Give the workspace and session sections clearer grouping, stronger active states, and calmer hover treatments. Preserve current navigation behavior and counts.

```tsx
// AppSidebar.tsx
<aside className="w-64 shrink-0 h-full rounded-[28px] border border-border-subtle bg-surface/90 backdrop-blur-sm flex flex-col overflow-hidden shadow-[0_18px_50px_-35px_rgba(0,0,0,0.9)]">
  ...
</aside>
```

- [x] **Step 5: Make the status bar feel like part of the shell**

Keep the runtime/status indicators, but reduce visual clutter and align them with the new surface system.

```tsx
// AppStatusBar.tsx
<footer className="h-7 shrink-0 border-t border-border-subtle/80 bg-surface/90 backdrop-blur-sm flex items-center px-4 text-[11px] font-mono leading-none">
  ...
</footer>
```

- [x] **Step 6: Verify shell behavior in the browser**

Run the app locally and confirm the shell still fits on desktop and smaller widths, with no horizontal overflow and no broken navigation.

Run: `cd frontend && npm run dev`
Expected: Next.js starts on port 4000 without shell layout errors.

---

### Task 2: Rework the issue and conductor surfaces

**Files:**
- Modify: `frontend/src/features/issues/IssueDetailPage.tsx`
- Modify: `frontend/src/features/issues/IssueDetailPanel.tsx`
- Modify: `frontend/src/features/issues/components/IssueSideStack.tsx`
- Modify: `frontend/src/features/issues/components/IssuePipelineTrace.tsx`
- Modify: `frontend/src/features/issues/components/LiveThinkingDock.tsx`
- Modify: `frontend/src/features/issues/components/TasksOverviewBar.tsx`
- Modify: `frontend/src/features/workflow/ConductorLogPanel.tsx`

- [x] **Step 1: Rebuild the issue hero into a control header**

Make the issue title, status, action buttons, and conductor banner feel like one intentional command strip instead of separate cards.

```tsx
// IssueDetailPage.tsx
<section className="px-6 pt-5 pb-4 max-w-[1640px] w-full mx-auto">
  <div className="flex items-end justify-between gap-6 rounded-[28px] border border-border-subtle bg-surface/70 px-6 py-5 shadow-[0_12px_40px_-28px_rgba(0,0,0,0.8)] backdrop-blur-sm">
    ...
  </div>
</section>
```

- [x] **Step 2: Make the pipeline trace read like a live workflow**

Keep the 4-station structure, but emphasize current state, completion, and time information with less border noise and stronger spacing.

```tsx
// IssuePipelineTrace.tsx
<section className="relative overflow-hidden rounded-[24px] border border-border-subtle px-5 pt-5 pb-4 shadow-[0_12px_34px_-28px_rgba(0,0,0,0.75)] backdrop-blur-sm">
  ...
</section>
```

- [x] **Step 3: Rework the right-side stack into clearer panels**

Keep acceptance, telemetry, and similar issues, but convert them into calmer cards with a more obvious reading order and less visual density.

```tsx
// IssueSideStack.tsx
<aside className="flex flex-col gap-4 sticky top-4">
  <AcceptanceCard ... />
  <TelemetryCard ... />
  <SimilarIssuesCard ... />
</aside>
```

- [x] **Step 4: Integrate live thinking and conductor logs**

Make streaming output feel embedded in the page instead of floating like a separate tool, with clearer role tabs, status chips, and a calmer transcript area.

```tsx
// LiveThinkingDock.tsx
<div className="fixed bottom-3 left-3 right-3 z-50 rounded-[24px] border border-border-subtle bg-surface/95 backdrop-blur-md shadow-[0_18px_40px_-24px_rgba(0,0,0,0.8)]">
  ...
</div>
```

```tsx
// ConductorLogPanel.tsx
// Keep the three-tab structure, but restyle it to match the new shell and issue surfaces.
```

- [x] **Step 5: Check issue-page readability at real densities**

Open an issue with live activity and confirm the page still feels usable at wide desktop sizes and mid-sized laptop widths.

Run: `cd frontend && npm run dev`
Expected: the issue page loads and the live panels remain readable without overlapping the shell.

---

### Task 3: Unify the remaining top-level pages

**Files:**
- Modify: `frontend/src/features/inbox/InboxDashboard.tsx`
- Modify: `frontend/src/features/projects/ProjectsPage.tsx`
- Modify: `frontend/src/features/projects/ProjectConductorPage.tsx`
- Modify: `frontend/src/features/projects/components/ProjectConductorThreadDock.tsx`
- Modify: `frontend/src/features/agents/AgentLibraryPage.tsx`
- Modify: `frontend/src/features/approvals/ApprovalsPage.tsx`
- Modify: `frontend/src/features/artifacts/ArtifactsHubPage.tsx`
- Modify: `frontend/src/features/knowledge/KnowledgePage.tsx`
- Modify: `frontend/src/features/settings/SettingsPage.tsx`
- Modify: `frontend/src/features/help/HelpPage.tsx`

- [x] **Step 1: Convert the inbox into the visual home base**

Make the inbox feel like a monitoring dashboard with clear KPI blocks, a strong hero, and calmer recent-activity sections.

```tsx
// InboxDashboard.tsx
<div className="min-h-full">
  <div className="relative overflow-hidden border-b border-border-subtle">
    ...
  </div>
</div>
```

- [x] **Step 2: Restyle projects and conductor pages as operational panels**

Make project lists, branch views, conductor state, and thread docks feel like cohesive admin surfaces rather than plain cards and forms.

```tsx
// ProjectsPage.tsx
// Use a stronger page header, softer card stack, and clearer table/list row hierarchy.
```

```tsx
// ProjectConductorPage.tsx
// Keep the same controls and data, but align the hero, metrics, and memory blocks to the new control-room style.
```

- [x] **Step 3: Update the remaining admin pages**

Apply the same typography, spacing, surface, and accent rules to agents, approvals, artifacts, knowledge, settings, and help so they no longer feel like separate apps.

```tsx
// AgentLibraryPage.tsx, ApprovalsPage.tsx, ArtifactsHubPage.tsx, KnowledgePage.tsx, SettingsPage.tsx, HelpPage.tsx
// Use the same header language, rounded surfaces, and visual hierarchy as the shell.
```

- [x] **Step 4: Verify cross-page consistency**

Use the browser to spot-check the home page, one issue page, one project page, and one utility page. The goal is that all of them look like they belong to the same product family.

Run: `cd frontend && npm run dev`
Expected: navigating between pages preserves the new visual language without layout jumps.

---

### Task 4: Verify, fix regressions, and close the loop

**Files:**
- Modify: any files found during verification only if they are required to fix the redesign

- [x] **Step 1: Run lint**

Run: `cd frontend && npm run lint`
Expected: exits successfully. If new lint warnings appear, fix the affected files before proceeding.

- [x] **Step 2: Run typecheck**

Run: `cd frontend && npx tsc --noEmit --pretty false`
Expected: exits successfully. If the existing missing test import still blocks typecheck, either fix it or record the blocker before claiming completion.

- [x] **Step 3: Run the frontend test suite**

Run: `cd frontend && npm run test`
Expected: exits successfully.

- [x] **Step 4: Browser smoke test**

Open the app in a browser and verify:
1. The shell has no horizontal overflow.
2. The sidebar, header, and status bar feel unified.
3. The issue page reads as a single workflow surface.
4. The project and utility pages match the same design language.

- [x] **Step 5: Commit after verification**

```bash
git add <all changed files>
git commit -m "refactor: overhaul frontend control room visuals"
```

