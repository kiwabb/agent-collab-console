# Recovered global route-map audit

- **Purpose**: Recover the single broad route-map agent that failed with an upstream 502 in the original workflow.
- **Scope**: Repository-wide source/routing audit, reconciled with the existing live-browser audit for `/projects`, `/projects/[id]`, and `/projects/[id]/prototypes`.
- **Date**: 2026-07-14

## Evidence boundary

- Live-browser conclusions remain limited to the three project routes documented in [`current-layout-audit.md`](current-layout-audit.md).
- All other rankings below are code and route-mount findings, not claims of live visual verification.
- The root route `/` uses a separate `WorkbenchPage`; changing `WorkbenchShell` will not affect it.

## Ranked structural impact

### 1. Global `WorkbenchShell`

Files:

- `frontend/src/features/workbench/WorkbenchShell.tsx`
- `frontend/src/features/workbench/components/AppSidebar.tsx`
- `frontend/src/features/workbench/components/PageFrame.tsx`

The desktop sidebar and route content are separate rounded `enterprise-panel` surfaces over an ambient gradient. `PageFrame` can add another decorative header/action layer. This is the highest-leverage structural source because it affects most routed tools. Desktop navigation and content should become edge-to-edge sibling panes; mobile sheets, dialogs, menus, alerts, and other true overlays retain floating containment.

### 2. Root operational workbench `/`

Files:

- `frontend/src/features/workbench/WorkbenchPage.tsx`
- `frontend/src/features/workspaces/WorkspaceGrid.tsx`
- `frontend/src/features/issues/IssueGrid.tsx`
- `frontend/src/features/tasks/TaskBoard.tsx`

This route is outside `WorkbenchShell`. Most cards represent independently selectable workspaces, issues, or Kanban tasks, so they are legitimate object cards rather than structural cardification. The route needs visual-language consistency review, but must not be flattened mechanically. A future list/table mode would be a product feature, not a required part of de-cardification.

### 3. Projects configuration `/projects`

File: `frontend/src/features/projects/ProjectsPage.tsx`

Confirmed by live inspection as the most over-cardified target page: floating project rail plus up to five equal-weight cards, duplicated branch collection, hover-lift on configuration sections, 2308px mobile document, and clipped header actions. Map to a continuous master/detail pane with one branch collection and section dividers.

### 4. Project workspaces `/projects/[id]`

Files:

- `frontend/src/features/projects/ProjectWorkspacesPage.tsx`
- `frontend/src/features/projects/ProjectShell.tsx`

Keep the existing divided workspace rows. Convert KPI cards into a summary strip and fix confirmed 390px toolbar/table overflow through responsive columns or mobile row composition.

### 5. Issue detail insight rail

Files:

- `frontend/src/features/issues/IssueDetailPage.tsx`
- `frontend/src/features/issues/components/IssueSideStack.tsx`
- related decision/criteria/git/similar-issue components

The contextual rail is a stack of rounded panels with nested telemetry cells, all describing the same current issue. Convert it into one inspector pane with divider-separated or collapsible sections. Preserve independent failure alerts, drawers, diffs, dialogs, and openable similar-issue records.

### 6. Settings `/settings`

Files:

- `frontend/src/features/settings/SettingsPage.tsx`
- `frontend/src/features/settings/McpManagementPanel.tsx`
- `frontend/src/features/workflow/AgentCatalogPanel.tsx`
- `frontend/src/components/runtime/RuntimeCatalogEditor.tsx`

One of the strongest nested-card surfaces: preference tiles, nested option rows, runtime/agent/MCP parent cards, and tier containers. Treat Settings as a sectioned document with fieldsets/rows and bounded readable width. Preserve errors, schemas/code blocks, dialogs, and separately saved executor definitions where their lifecycle needs a boundary.

### 7. Knowledge `/knowledge`

File: `frontend/src/features/knowledge/KnowledgePage.tsx`

Replace the rounded tab, filter, and results wrappers with line tabs, one command bar, and one continuous result pane. Preserve the already-correct divided result rows.

### 8. Project Conductor and startup/environment configuration

Files:

- `frontend/src/features/projects/ProjectConductorPage.tsx`
- `frontend/src/features/projects/ProjectStartupConfigPage.tsx`
- `frontend/src/features/projects/ProjectEnvVarEditor.tsx`

These routes are directly reachable from `ProjectShell` but were omitted from the first child-task plan. Conductor has a rounded gradient parent, KPI cards, and nested rounded sections. Startup configuration has progress tiles and rounded sections; the environment-variable divided collection is already structurally appropriate. They must either join the project-layout child task or be explicitly excluded.

### 9. Benchmarks `/benchmarks`

File: `frontend/src/features/benchmarks/BenchmarksPage.tsx`

The densest analytics chrome: repeated rounded/blurred panels, nested stat tiles, tables, chart, diff, calibration, and matching loading/empty containers. Keep chart plot and selected-run boundaries; convert metrics to summary strips and related data to continuous tables/sections. The route currently does not use `WorkbenchShell` and was not found in sidebar navigation, so route-shell consistency must be decided explicitly.

### 10. Structured prototype

Files under `frontend/src/features/prototype/structured/`.

Preserve the uncommitted continuous editor baseline. Remaining inconsistency is mainly Flow mode's structural outer `enterprise-card`, page-card grid, and rule cards. Graph nodes may remain bounded objects; rules should become a relationship list. Browser/device preview, blueprint/progress records, errors, evidence states, and dialogs remain legitimate contained objects.

## Secondary surfaces

- `HelpPage.tsx`: sequential/document content is cardified but lower impact.
- `AuditLogPage.tsx`: filter and operation cards can become a flat filter strip plus event list.
- `ArtifactsHubPage.tsx`: issue groups are generally legitimate independent records.
- `ConductorMonitorPage.tsx`: independently openable conductor records are legitimate object cards.
- `WorkspaceConsole.tsx` and `IssueListPanel.tsx`: good local examples of one collection boundary plus compact divided rows.
- `InboxDashboard.tsx`: dense card matrix but no current route mount; do not rank as current user-facing impact.

## Scope corrections to the first child-task plan

1. Add Settings to an information/configuration layout workstream.
2. Add Project Conductor and startup configuration to the project workstream.
3. Treat `/` as a separate consistency review because it does not inherit `WorkbenchShell`; preserve legitimate object cards.
4. Reconcile Benchmarks with the global shell/navigation model before treating it as just another `WorkbenchShell` route.
5. Include lower-impact Help/Audit in the final global consistency audit, but do not flatten legitimate Artifacts/Conductor records.

## Working-tree preservation boundary

The tree contains concurrent uncommitted product, spec, test, task, and local environment changes. In particular:

- Preserve all existing `ProjectShell` and structured-prototype continuous-layout changes and their tests/specs.
- Preserve the interwoven structured-prototype deletion vertical slice across backend, frontend API/hooks/types/storage, i18n, and tests.
- Preserve the unrelated startup-service-identity task and its research.
- Do not inspect, overwrite, clean, stage, or otherwise touch `examples/admin-demo/.env`.
- Do not use reset/clean or broad rewrites; make incremental, file-scoped edits only.
