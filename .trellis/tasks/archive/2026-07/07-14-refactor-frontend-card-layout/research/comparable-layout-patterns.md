# Research: Comparable Dense Developer-Tool Layout Patterns

- **Query**: Research comparable dense desktop developer-tool layouts; inspect local `ccgui` and `vibe-kanban` references; identify structural panes, rails, inspectors, tables/lists, section dividers, and selective containment as alternatives to generic nested cards; map the findings to this repo's Next.js + Tailwind v4 + Base UI constraints.
- **Scope**: Mixed (local reference repositories, current frontend, package/spec constraints, and official external documentation)
- **Date**: 2026-07-14

## Executive Summary

Dense developer tools consistently make **application structure** carry hierarchy rather than repeating rounded containers. The recurring model is:

1. a narrow global activity/navigation rail,
2. an optional primary navigation/list pane,
3. one flexible work surface,
4. an optional contextual inspector,
5. an optional bottom output/log pane,
6. sibling regions separated by one-pixel dividers or operable resize separators.

`reference-cc-gui` and `references/vibe-kanban` both implement this model. The current repo's structured prototype studio already follows it closely. For this codebase, the directly compatible approach is CSS Grid/Flex with `minmax(0, 1fr)`, `min-w-0`, `min-h-0`, sibling borders, semantic `<aside>/<main>/<section>`, and Base UI Tabs/ScrollArea/Separator for behavior. Rounded containment should remain selective: dialogs, independently actionable domain records, alerts, and literal preview/device boundaries—not every toolbar, subsection, KPI, and structural region.

A stack-version caveat is material: the request says Next.js 14, but the current checkout declares `next: ^15.5.20`, and both frontend specs say Next.js 15. The layout recommendations are not version-sensitive, but implementation planning should use the actual Next.js 15 App Router baseline.

## Findings

### Files Found

| File Path | Description |
|---|---|
| `reference-cc-gui/src/features/layout/components/DesktopLayout.tsx` | Desktop workbench composition: primary sidebar, central content layers, contextual right panel, bottom docks, and semantic resize separators. |
| `reference-cc-gui/src/styles/base.css` | Top-level two-column shell driven by `--sidebar-width`, plus an 8px operable sidebar resize target. |
| `reference-cc-gui/src/styles/main.css` | Center/right-pane grid, full-height content layers, divider-based right inspector, collapsible regions, and resizer geometry. |
| `reference-cc-gui/src/app-shell.tsx` | Owns persisted/current pane dimensions and collapsed states through the layout controller. |
| `reference-cc-gui/src/app-shell-parts/renderAppShell.tsx` | Passes CSS pane-size variables and composes the workbench nodes into `AppLayout`. |
| `references/vibe-kanban/packages/web-core/src/shared/components/ui-new/containers/SharedAppLayout.tsx` | Global desktop activity rail + content grid; includes a transient hover-reveal workspace sidebar when the persistent pane is hidden. |
| `references/vibe-kanban/packages/web-core/src/pages/workspaces/WorkspacesLayout.tsx` | Fixed 300px outer sidebars around resizable main panes; switches to one active full-height pane on mobile. |
| `references/vibe-kanban/packages/web-core/src/pages/workspaces/RightSidebar.tsx` | Contextual inspector assembled from divider-separated collapsible sections, not cards. |
| `references/vibe-kanban/packages/ui/src/components/WorkspacesSidebar.tsx` | Fixed header/search, independently scrolling dense workspace list, optional grouped sections, and fixed footer. |
| `references/vibe-kanban/packages/ui/src/components/IssueListView.tsx` | Full-height issue list composed from status sections. |
| `references/vibe-kanban/packages/ui/src/components/IssueListSection.tsx` | Compact collapsible section header and contiguous droppable rows. |
| `references/vibe-kanban/packages/ui/src/components/IssueListRow.tsx` | Dense row model with priority, ID, status, title, tags, relationships, assignee, and age in one scan line. |
| `references/vibe-kanban/packages/ui/src/components/DataTable.tsx` | Generic semantic table with column definitions, loading/empty states, and keyboard-operable clickable rows. |
| `references/vibe-kanban/packages/ui/src/components/Table.tsx` | Thin semantic table primitives; row borders and hover state provide hierarchy without per-row containers. |
| `references/vibe-kanban/packages/ui/src/components/KanbanIssuePanel.tsx` | Inspector/detail panel with fixed header, scrolling body, and border-separated property/content sections. |
| `frontend/src/features/workbench/WorkbenchShell.tsx` | Current global shell; sidebar and entire route content are each large rounded `enterprise-panel` surfaces. |
| `frontend/src/features/workbench/components/AppSidebar.tsx` | Current 256px navigation/sidebar panel with compact rows and nested session list. |
| `frontend/src/features/projects/ProjectShell.tsx` | Already supports `layout="workspace"`, converting the project hero to compact full-width editor chrome. |
| `frontend/src/features/prototype/structured/StructuredPrototypeStudioPage.tsx` | Existing local exemplar of toolbar + 240px rail + flexible canvas + 300px inspector with divider boundaries and mobile pane switching. |
| `frontend/src/features/prototype/structured/StructuredPrototypePageRail.tsx` | Flat rail rows use a left active indicator and background change instead of individual cards. |
| `frontend/src/features/prototype/structured/StructuredPrototypePalette.tsx` | Compact component rows use `divide-y` and hover/active accents rather than tile cards. |
| `frontend/src/features/workspaces/IssueListPanel.tsx` | Existing compact table-like operation queue with one outer boundary and divider-separated rows. |
| `frontend/src/features/workspaces/IssueRow.tsx` | Dense four-column operational row that collapses to a single column at smaller widths. |
| `frontend/src/features/projects/ProjectWorkspacesPage.tsx` | Existing grid/list table for workspace records, but also four individually contained KPI tiles above it. |
| `frontend/src/features/projects/ProjectsPage.tsx` | Master/detail page with an already useful 260px list rail, while detail subsections are distributed across several rounded cards. |
| `frontend/src/features/knowledge/KnowledgePage.tsx` | Search page with separate rounded navigation, filter toolbar, and results-panel containers around an already flat divided result list. |
| `frontend/src/features/benchmarks/BenchmarksPage.tsx` | High-containment analytics surface: repeated 24px rounded panels and nested summary-stat tiles around semantic tables/charts. |
| `frontend/src/features/issues/IssueDetailPage.tsx` | Central timeline/detail with a secondary insight rail at 2XL. |
| `frontend/src/features/issues/components/IssueSideStack.tsx` | Context rail currently expressed as a vertical stack of independently rounded panels and nested telemetry cells. |
| `frontend/src/components/ui/tabs.tsx` | Base UI Tabs wrapper; supports line-style tabs, vertical orientation, keyboard behavior, and keep-mounted panels. |
| `frontend/src/components/ui/scroll-area.tsx` | Base UI ScrollArea wrapper suitable for independently scrolling panes. |
| `frontend/src/components/ui/separator.tsx` | Base UI semantic horizontal/vertical separator wrapper. |
| `frontend/src/app/globals.css` | Tailwind v4 theme tokens and current `enterprise-panel` / `enterprise-card` visual recipes. |
| `frontend/package.json` | Actual current stack and dependencies: Next.js 15.5, Tailwind v4, Base UI 1.4; no resizable-panel library is currently declared. |

### Code Patterns

#### 1. `ccgui`: a workbench is a pane graph, not a card stack

The outer application is one full-viewport grid whose first track is a CSS-variable sidebar and whose second track consumes the remaining space:

```css
/* reference-cc-gui/src/styles/base.css:128-139 */
.app {
  height: 100vh;
  width: 100vw;
  display: grid;
  grid-template-columns: var(--sidebar-width, 210px) 1fr;
  overflow: hidden;
}
```

The main area is another grid with a flexible center and a right contextual pane:

```css
/* reference-cc-gui/src/styles/main.css:1-14 */
.main {
  display: grid;
  grid-template-columns: minmax(280px, 1fr) var(--right-panel-width, 230px);
  grid-template-rows: auto 1fr auto auto auto auto;
  min-height: 0;
  min-width: 0;
  overflow: hidden;
}
```

`DesktopLayout` composes these as siblings and gives resize handles real separator semantics:

- sidebar separator: `reference-cc-gui/src/features/layout/components/DesktopLayout.tsx:235-246`
- center content layers: `reference-cc-gui/src/features/layout/components/DesktopLayout.tsx:273-326`
- right-panel separator and inspector: `reference-cc-gui/src/features/layout/components/DesktopLayout.tsx:328-358`
- bottom runtime/terminal/debug/history docks: `reference-cc-gui/src/features/layout/components/DesktopLayout.tsx:359-364`

Both vertical and horizontal handles expose `role="separator"` and `aria-orientation`, while CSS supplies a larger 8px hit target around a visually thin divider (`reference-cc-gui/src/styles/base.css:274-303`; `reference-cc-gui/src/styles/main.css:1692-1713,1747-1783`). The right panel itself is flat full-height chrome with one left border and internal toolbar/divider structure (`reference-cc-gui/src/styles/main.css:1624-1689`).

The center swaps chat, diff, editor, and memory as layers in the same spatial region rather than nesting another page shell. Hidden layers are made non-interactive and the React component also manages `inert`/focus (`reference-cc-gui/src/features/layout/components/DesktopLayout.tsx:99-132`; `reference-cc-gui/src/styles/main.css:1452-1502`). This preserves a stable workbench geometry while tools change.

**Pattern extracted**: use one viewport shell; treat primary navigation, work surface, contextual tools, and output as sibling regions. Use containment only inside a region when an object truly needs its own boundary.

#### 2. `vibe-kanban`: activity rail → list pane → work surface → inspector

At global scope, `SharedAppLayout` uses `grid-cols-[auto_1fr]`: the narrow `AppBar` is a persistent activity/project rail and the route outlet is the flexible content region (`references/vibe-kanban/packages/web-core/src/shared/components/ui-new/containers/SharedAppLayout.tsx:299-312,321-372`). When the workspace sidebar is hidden, a narrow reopen handle can reveal a temporary 300px overlay pane (`SharedAppLayout.tsx:371-399`), preserving work-surface width until navigation is needed.

Within a workspace, the desktop structure is:

- optional fixed 300px workspace list,
- a flexible main region,
- resizable left/right main panes using `react-resizable-panels`,
- optional fixed 300px contextual sidebar.

See `references/vibe-kanban/packages/web-core/src/pages/workspaces/WorkspacesLayout.tsx:333-414,419-438`. Important implementation details are `min-w-0`, `min-h-0`, and local `overflow-hidden` on every pane. The separator is visually transparent at rest but gets an accent hover state (`WorkspacesLayout.tsx:371-375`). The panel ratio is persisted and updates are throttled (`WorkspacesLayout.tsx:174-205`).

On mobile, the same content is not squeezed into narrow columns. One pane fills the available area and inactive panes receive `hidden` rather than being conditionally unmounted, explicitly preserving WebSocket connections and scroll positions (`WorkspacesLayout.tsx:207-310`). The current repo's Base UI `TabsContent` independently uses `keepMounted` for the same reason (`frontend/src/components/ui/tabs.tsx:66-95`).

**Pattern extracted**: use persistent rails and replaceable full-height panes on narrow screens; preserve live panel state when switching among tools.

#### 3. Contextual inspector: flat sections with one scroll owner

`vibe-kanban`'s `RightSidebar` is one full-height secondary surface with a left border and vertical scroll. Its Git, Terminal, Notes, Changes, Logs, and Preview sections are separated with `divide-y` and each has a compact collapsible header (`references/vibe-kanban/packages/web-core/src/pages/workspaces/RightSidebar.tsx:195-219`). The section body receives a top border and minimum useful height rather than another rounded container (`RightSidebar.tsx:201-215`).

The issue inspector has the same geometry: fixed border-bottom header, one scrolling content body, then border-separated property and content sections (`references/vibe-kanban/packages/ui/src/components/KanbanIssuePanel.tsx:255-319`).

The current structured prototype inspector already mirrors this pattern: the right pane has `border-l`, a 44px tab strip, and one `overflow-auto` content region (`frontend/src/features/prototype/structured/StructuredPrototypeStudioPage.tsx:443-487`).

**Pattern extracted**: an inspector is itself the containing pane. Its internal hierarchy should usually be section headers, disclosure, spacing, and dividers—not a stack of cards inside the pane.

#### 4. Dense collections: table/list rows, not record cards

`vibe-kanban`'s issue list organizes work into compact collapsible status sections and contiguous rows (`IssueListView.tsx:47-65`; `IssueListSection.tsx:70-135`). Each row carries priority, stable ID, status, title, tags, relationships, assignee, and age in a single scan path (`IssueListRow.tsx:94-190`). Hover and selected backgrounds provide state; there is no rounded border around each issue.

Its generic `DataTable` uses semantic table primitives, column definitions, loading/empty rows, and Enter/Space activation for clickable records (`references/vibe-kanban/packages/ui/src/components/DataTable.tsx:40-98`). The underlying row hierarchy is only `border-t` plus hover (`Table.tsx:32-47`).

The current repo already has two strong local versions:

- workspace operations queue: one outer boundary, a fixed column header, and `divide-y` rows (`frontend/src/features/workspaces/IssueListPanel.tsx:63-127`),
- project workspaces: one table/list boundary with six aligned columns and divider-separated rows (`frontend/src/features/projects/ProjectWorkspacesPage.tsx:696-747,802-883`).

**Pattern extracted**: for repeated comparable entities, one collection boundary plus aligned rows is denser and easier to scan than one independent card per entity.

#### 5. Flat navigation and palette rows

The current structured prototype page rail is an explicit non-card example. Each page is a full-width row with a 2px active left border, transparent inactive background, and compact title/route hierarchy (`frontend/src/features/prototype/structured/StructuredPrototypePageRail.tsx:15-47`). The palette similarly uses one-column `divide-y` rows with active/hover edge accents (`StructuredPrototypePalette.tsx:45-62,66-81`).

This matches the reference sidebars, where fixed headers and search controls sit above independently scrolling rows and a fixed footer (`references/vibe-kanban/packages/ui/src/components/WorkspacesSidebar.tsx:247-317,479-501`).

**Pattern extracted**: rails should favor selection indicators and continuous row rhythm. A card grid implies independent browseable objects, which is the wrong semantic signal for navigation or a tool palette.

#### 6. Selective containment, already visible in the current repo

The existing `enterprise-panel` and `enterprise-card` utilities are visually strong: each adds its own border, layered background, shadow, and—in the panel case—backdrop blur (`frontend/src/app/globals.css:234-256`). Repetition therefore creates a visible hierarchy at every DOM level.

Current concentration examples:

- global workbench content wraps every route in a rounded 22/30px `enterprise-panel` (`frontend/src/features/workbench/WorkbenchShell.tsx:89-95`), while the sidebar is another rounded 30px panel (`AppSidebar.tsx:189-195`);
- Projects uses a rounded list panel and multiple rounded detail cards (`frontend/src/features/projects/ProjectsPage.tsx:495-560,698-755`);
- Knowledge separately contains navigation, filters, and results (`frontend/src/features/knowledge/KnowledgePage.tsx:159-175,236-318`);
- Benchmarks repeatedly uses 24px rounded panels, then nests summary-stat tiles within them (`frontend/src/features/benchmarks/BenchmarksPage.tsx:726-857,861-877,918-1007`);
- the issue insight rail stacks multiple rounded panels and telemetry cells (`frontend/src/features/issues/components/IssueSideStack.tsx:118-167,261-329`).

By contrast, the structured studio uses one workspace and sibling borders (`frontend/src/features/prototype/structured/StructuredPrototypeStudioPage.tsx:246-488`). This is the closest in-repo reference for the target visual direction.

## External References

All sources below are official product documentation, searched and checked on 2026-07-14.

1. [Visual Studio Code — Custom Layout](https://code.visualstudio.com/docs/configure/custom-layout)
   - The Primary Side Bar holds views such as Explorer, Search, and Source Control, switched from the Activity Bar.
   - A Secondary Side Bar can show another view opposite the primary side bar so two contexts remain visible at once.
   - The Panel region hosts Problems, Terminal, and Output and can move around the editor.
   - Views/panels can move among regions, and VS Code remembers the layout across sessions.
   - **Relevant pattern**: outer activity rail + primary navigator + center editor + auxiliary inspector + output panel; user-configurable pane visibility is more valuable than multiplying static cards.

2. [GitHub Docs — Customizing the table layout](https://docs.github.com/en/issues/planning-and-tracking-with-projects/customizing-views-in-your-project/customizing-the-table-layout)
   - GitHub describes the table layout as a spreadsheet of issues, pull requests, draft issues, GitHub metadata, and custom fields.
   - Items can be grouped, sorted, filtered, and fields can be shown/hidden; rows and fields can be reordered.
   - Moving an item between field-value groups updates that field value.
   - **Relevant pattern**: operational collections should use aligned rows and configurable dimensions; grouping headers can carry workflow meaning without wrapping each record in a card.

3. [JetBrains IntelliJ IDEA — Arrange tool windows](https://www.jetbrains.com/help/idea/manipulating-the-tool-windows.html)
   - Tool windows attach to main-window edges by default, can move by icon/header, and can be detached.
   - Users resize them by dragging the tool-window border.
   - Locations and custom sizes can be saved as layouts; windows can also be maximized or arranged side-by-side.
   - The Exa result identifies the page as published/updated 2025-04-02.
   - **Relevant pattern**: tool panes belong to stable edges around a primary canvas; resizing and collapse/maximize state are first-class interactions.

4. [Linear Docs — Display options](https://linear.app/docs/display-options), [Custom Views](https://linear.app/docs/custom-views), and [Insights](https://linear.app/docs/insights)
   - Display options determine issue/project grouping, ordering, and visible information; issue views can switch between list and board layouts.
   - Custom-view right sidebars clarify view contents and expose common property filters.
   - Most issue views expose Insights in a right-hand sidebar, with an expanded full-screen mode when more analysis space is needed.
   - **Relevant pattern**: the central collection stays primary while filtering/analytics live in a contextual right rail that may expand when it becomes the primary task.

## Layout Alternatives to Generic Nested Cards

### Alternative A: Structural workbench panes

```text
┌────────┬────────────────┬────────────────────────────┬────────────────┐
│ global │ primary list   │ primary work surface       │ inspector      │
│ rail   │ / navigation   │                            │ / properties   │
│ 48–64  │ 220–300        │ minmax(0, 1fr)             │ 280–360        │
├────────┴────────────────┴────────────────────────────┴────────────────┤
│ optional logs / terminal / trace panel                                │
└───────────────────────────────────────────────────────────────────────┘
```

Use when the page is an editor, command center, master/detail workspace, or long-lived operational surface. Pane borders are the containment; child sections remain mostly flat.

### Alternative B: Table/list workspace

```text
header / title + primary action
filter and query toolbar
────────────────────────────────────────────────────────
column header or grouped section header
row
row
row
────────────────────────────────────────────────────────
selection/action footer or pagination
```

Use for workspaces, issues, runs, audit entries, approvals, agents, artifacts, and benchmark records. Use a semantic `<table>` where columns must remain aligned; use a CSS-grid `<ul>` when responsive row reflow or rich row interaction is more important.

### Alternative C: Main surface + contextual inspector

```text
┌──────────────────────────────────────┬──────────────────┐
│ timeline / chart / preview / editor  │ Properties       │
│                                      │ ──────────────── │
│                                      │ Runtime          │
│                                      │ ──────────────── │
│                                      │ Activity         │
└──────────────────────────────────────┴──────────────────┘
```

Use when the right-side information describes the current selection. Give the inspector one border, one tab/header strip, one scroll owner, and divider-separated or collapsible sections.

### Alternative D: Sectioned document surface

```text
page title and actions
summary strip (inline metrics)
────────────────────────────────────────────────────────
section heading                         secondary action
content, table, or form
────────────────────────────────────────────────────────
section heading
content
```

Use for settings, project configuration, knowledge search, and analytics where the page is conceptually one document rather than several unrelated objects. Reserve rounded sub-containment for a warning, code/log block, preview frame, or independently actionable record.

### Alternative E: Collapsible tool stack

One fixed inspector/sidebar can host multiple tool sections with compact disclosure headers. This is the `vibe-kanban` right sidebar model. It is appropriate when several auxiliary tools compete for a narrow rail but should not each appear as a floating card.

## Recommendation Map for This Repo

These are mappings from observed patterns to the current surfaces, not a product-scope proposal.

| Current Surface | Comparable Pattern | Structural Mapping | Containment That Still Fits |
|---|---|---|---|
| Global `WorkbenchShell` | VS Code / `ccgui` workbench | Treat sidebar and route content as flush siblings with one divider; keep header/status bar as spanning strips. | Dialogs, command palette, transient alerts, literal preview windows. |
| `ProjectsPage` | Master list + detail inspector | Keep a 240–280px project rail; make project detail one continuous pane with header/actions and divider-separated sections. | Delete confirmation, repair result/error, independently actionable setup/run-command editors if they must preserve form state. |
| `ProjectWorkspacesPage` | GitHub Projects table | Keep toolbar + one row collection. Convert the four KPI tiles into a compact summary/status strip if density is the goal. | Empty state, run log/code block, destructive confirmation. |
| `WorkspaceConsole` | Operational queue | Its existing one-boundary, divider-row pattern is already aligned with the references. | The queue's single outer boundary and exceptional failure/approval banners. |
| `IssueDetailPage` + `IssueSideStack` | Center timeline + Linear/JetBrains inspector | Keep timeline primary; make the insight rail one pane whose policy, criteria, telemetry, activity, and similar-issue content are divided/collapsible sections. | A selected execution drawer, critical failure alert, domain records that open independently. |
| `KnowledgePage` | Search/list workspace | Make navigation a line tab strip; merge search/scope/mode into one command bar; keep results as one divided list with optional selection preview. | Search input control, empty state, selected artifact preview. |
| `BenchmarksPage` | Analytics workbench | Use one tab/toolbar strip and one table/chart surface; use an optional comparison/calibration inspector instead of repeated large panels. Present summary statistics as an inline strip. | Chart plotting boundary, selected-run detail, regression alert, export/dialog surfaces. |
| Structured prototype studio | VS Code/Figma-like editor | Preserve the current page rail + canvas + inspector geometry as the local reference implementation. | Device/browser preview boundary and error/empty states. |
| Narrow/mobile layouts | `vibe-kanban` mobile pane switcher | Show one primary pane at a time through tabs/navigation or a Base UI Sheet; keep live panels mounted when connection/scroll state matters. | Modal/Sheet containment appropriate to transient navigation and inspector access. |

## Selective Containment Rules

A practical distinction from the references:

### Keep a card/panel boundary when the object is

- a repeated **domain record** that is independently selectable/actionable and not better compared by aligned columns;
- a dialog, popover, sheet, toast, or transient overlay;
- an alert/error/approval that must interrupt the surrounding rhythm;
- a literal device, browser, terminal, code, media, or prototype preview boundary;
- a self-contained editor/form whose save/error lifecycle must remain distinct;
- a compact dashboard visualization whose axes/plot need a bounded field.

### Prefer a flat region, row, divider, or section when the object is

- global or project navigation;
- a toolbar, tab strip, filter strip, breadcrumb, or title region;
- a page-level section inside one conceptual document;
- a KPI that can fit in a summary strip;
- an inspector subsection;
- a row in a comparable collection;
- a structural parent whose children already carry their own real boundaries.

### Avoid duplicated visual hierarchy

If a region already has a pane background and border, its immediate child should not automatically repeat `enterprise-panel`. If a table/list already has one outer boundary, each row should normally use only a divider/hover/selection state. If an inspector is one bounded rail, its sections should normally use section headers and borders.

## Mapping to Next.js + Tailwind v4 + Base UI

### Actual stack constraints

- `frontend/package.json:19-20,42,58-70` declares Base UI `^1.4.1`, Next.js `^15.5.20`, and Tailwind v4. The task wording's Next.js 14 is stale relative to the checkout.
- `frontend/src/app/globals.css:3-159` correctly exposes design tokens through Tailwind v4 `@theme`; new shared pane/divider tokens must be defined there if utility names should resolve.
- The package does **not** currently declare `react-resizable-panels`. `vibe-kanban` uses it, while `ccgui` implements pointer-driven resizing itself. Fixed CSS-grid panes therefore require no dependency; persistent user resizing requires an explicit implementation/dependency decision.

### Layout primitives already available

1. **CSS Grid / Flex**
   - The current studio proves arbitrary Tailwind grid tracks work: `lg:grid-cols-[240px_minmax(440px,1fr)_300px]` (`StructuredPrototypeStudioPage.tsx:331`).
   - Always place `min-w-0` on flexible grid/flex children and `min-h-0` on full-height vertical descendants. Both reference repos rely on this to prevent content from forcing pane expansion.
   - Give each pane one scroll owner (`overflow-auto` or `ScrollArea`) and keep ancestors `overflow-hidden`.

2. **Base UI Tabs**
   - The local wrapper supports horizontal/vertical orientation and a `variant="line"` style (`frontend/src/components/ui/tabs.tsx:9-63`). Line tabs are the direct alternative to a rounded segmented control when tabs are part of structural chrome.
   - `TabsContent` is keep-mounted (`tabs.tsx:66-95`), useful for streams, WebSockets, unsaved forms, and scroll-state preservation during pane switching.

3. **Base UI ScrollArea**
   - Use for independently scrolling navigation, results, or inspector panes when styled scrollbars are required (`frontend/src/components/ui/scroll-area.tsx:8-51`). Native `overflow-auto` remains sufficient where no custom behavior is needed.

4. **Base UI Separator**
   - The wrapper supports horizontal/vertical geometry (`frontend/src/components/ui/separator.tsx:7-18`). It is suitable for decorative section division.
   - A draggable divider is interactive and should instead expose `role="separator"`, `aria-orientation`, keyboard resizing if implemented, and a hit target wider than the visible line, following `ccgui`'s pattern.

5. **Base UI Sheet/Dialog/Menu/Select**
   - Use Sheet/Dialog to expose navigation or an inspector on smaller screens rather than compressing a three-pane desktop grid.
   - Keep the established Select constraints from the component spec: `alignItemWithTrigger={false}` and children for Icon/ItemIndicator slots.

### App Router/component boundaries

- Structural shells that only compose server content can remain server components.
- Route-aware or interactive shells (path active state, collapse, resize, tabs, drag/drop) must be client components; current `ProjectShell` and studio already establish this pattern.
- Preserve thin page shells and split header/list/row/inspector responsibilities into feature-local components, as required by `.trellis/spec/ccgui/frontend/component-guidelines.md:31-56`.

### Responsive behavior

- Desktop: use two or three sibling columns and optional bottom output.
- Intermediate widths: collapse the contextual inspector first or make it a Sheet; keep the primary list and work surface if both remain useful.
- Mobile: select one full-height pane at a time. Keep mounted when live state matters, matching `vibe-kanban` and the local Tabs wrapper.
- A structural CSS breakpoint should change the navigation model, not merely stack several desktop cards vertically.

### Accessibility requirements

- Use native `<nav>`, `<aside>`, `<main>`, `<section>`, `<table>`, `<thead>`, and `<tbody>` where semantics fit.
- Collection rows that navigate should preferably contain a real link/button; if the whole row is interactive, provide Enter/Space handling as the reference `DataTable` does.
- Draggable resize boundaries should be semantic separators with orientation and an adequate hit area.
- Selection must use more than color: `aria-current`, `aria-selected`, labels/icons, and visible focus states.
- Pane switching must move or restore focus predictably; hidden panes must not retain reachable controls (`ccgui` uses `inert` for this).

## Related Specs

- `.trellis/spec/ccgui/frontend/component-guidelines.md:81-130` — Tailwind v4 styling rules and the explicit full-height editor contract: one page surface, divider-based toolbar/rail/canvas/inspector regions, no outer nested rounded panel, no card-grid navigation.
- `.trellis/spec/vibe-kanban/frontend/component-guidelines.md:81-130` — mirror of the same full-height editor and selective-card guidance.
- `.trellis/spec/ccgui/frontend/component-guidelines.md:166-182` — semantic HTML, keyboard operation, ARIA, reduced motion, and non-color status requirements.
- `.trellis/spec/ccgui/frontend/quality-guidelines.md:306-328` — stable source-contract assertions and browser-walkthrough implications for status bar, diff, and right-rail surfaces.
- `.trellis/spec/vibe-kanban/frontend/component-guidelines.md:169-235` — page-specific architecture: workspace overview uses list rows, project workspaces uses a table, issue detail makes the timeline primary and lower-priority content secondary.
- `.trellis/spec/ccgui/frontend/directory-structure.md` — feature-local component ownership and thin route/page composition.

## Caveats / Not Found

- The active task metadata has an empty description and no concrete target file list; recommendations therefore map patterns to the highest-density current surfaces rather than asserting a final rollout scope.
- The external sources document product behavior and region models, not this repo's exact dimensions or visual tokens. Widths in the recommendation map are derived from local references and existing code, not mandated by VS Code, GitHub, JetBrains, or Linear.
- `vibe-kanban` uses `react-resizable-panels`, but that package is absent from the current frontend dependency list. No dependency addition is implied by this research.
- Base UI primitives cover tabs, scroll areas, separators, sheets, dialogs, menus, and controls in the current repo. An interactive splitter primitive was not found in this checkout.
- The requested “Next.js 14” constraint conflicts with the current package and specs, which are on Next.js 15.5.20 / Next.js 15.
