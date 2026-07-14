# Research: Current frontend card-layout audit

- **Query**: Audit the current frontend card-layout problem for `.trellis/tasks/07-14-refactor-frontend-card-layout`, including live project and structured prototype surfaces, responsive behavior, uncommitted changes, and exact files involved.
- **Scope**: Internal — repository source, current git diff, and the already-running local app at `http://127.0.0.1:4000`; no server was restarted and no product code was modified.
- **Date**: 2026-07-14

## Findings

### Audit result

Among the live surfaces inspected, **the project configuration page at `/projects` is currently the most over-cardified page**. The structured prototype studio was the clearest original concentration of nested cards, but the current uncommitted source and live app already contain a substantial conversion of that route to a continuous editor layout. The project configuration page still presents its information architecture as one left floating panel plus a vertical sequence of visually equivalent `Card` surfaces on the right.

This conclusion is scoped to the user-facing project and structured-prototype surfaces requested here. A repository-wide class-name count found other card-heavy files, but those pages were not live-audited in this task and therefore are not ranked here.

### Live inspection conditions

- Existing listeners were already present on `127.0.0.1:4000` and `127.0.0.1:9000`; they were used as-is.
- Chrome DevTools inspected the app at desktop width (`1440` CSS px), medium width (`900` CSS px), and mobile width (`390` CSS px).
- The live project used for inspection was `agent-collab-console` (`d26a7a4a-9c4b-4da2-a84f-c029416a3351`).
- The structured prototype was an existing three-page procurement application, so page rail, palette, preview, AI history, role switch, publish controls, and all three mobile panels were observable without creating or mutating data.
- No console errors were present on the final mobile inspections. At one desktop prototype capture, repeated `404`s were attributable to global `/api/codex/cost-stats` and `/api/codex/embedding/status` requests, not to the prototype layout itself.

## Files Found

| File Path | Description |
|---|---|
| `frontend/src/app/projects/page.tsx` | Route mount for the project configuration page (`/projects`). |
| `frontend/src/features/projects/ProjectsPage.tsx` | Main implementation of the currently most card-heavy audited page: project selector, project details, scripts, branches, and activity cards. |
| `frontend/src/features/workbench/components/PageFrame.tsx` | Page-level header/content wrapper used by `ProjectsPage`; supplies the top page surface and responsive content padding. |
| `frontend/src/components/ui/card.tsx` | Shared `Card` primitive; every card has rounded chrome, ring, transition, hover translation, and hover shadow by default. |
| `frontend/src/app/projects/[id]/page.tsx` | Route mount for a project workspace page. |
| `frontend/src/features/projects/ProjectWorkspacesPage.tsx` | Project workspace KPIs, toolbar, logs, and fixed-column workspace table. |
| `frontend/src/features/projects/ProjectShell.tsx` | Shared project title and secondary navigation; current uncommitted change adds `layout="workspace"`. |
| `frontend/src/features/workbench/WorkbenchShell.tsx` | Global desktop workbench shell; wraps project pages in one large rounded `enterprise-panel`. |
| `frontend/src/app/projects/[id]/prototypes/page.tsx` | Route mount for the structured prototype studio. |
| `frontend/src/features/prototype/structured/StructuredPrototypeRoutePage.tsx` | Composes `WorkbenchShell`, `ProjectShell`, and the structured studio; now opts into `layout="workspace"`. |
| `frontend/src/features/prototype/structured/StructuredPrototypeStudioPage.tsx` | Full-height editor composition: top toolbar, page/palette rail, canvas, inspector, and mobile panel navigation. |
| `frontend/src/features/prototype/structured/StructuredPrototypePageRail.tsx` | Page navigation; current rows use a continuous list with a left selection rule rather than cards. |
| `frontend/src/features/prototype/structured/StructuredPrototypePalette.tsx` | Component palette; current items are divided list rows rather than a two-column card grid. |
| `frontend/src/features/prototype/structured/StructuredPrototypePreview.tsx` | Device/browser preview boundary and responsive preview navigation. |
| `frontend/src/features/prototype/structured/StructuredPrototypeCanvas.tsx` | Editable preview contents, sortable node boundaries, form, table, and selection outlines. |
| `frontend/src/features/prototype/structured/StructuredPrototypeAiPanel.tsx` | Inspector-side AI message history, run evidence, preview, and composer. |
| `frontend/src/features/prototype/structured/StructuredPrototypeInspector.tsx` | Property editor shown in the right studio region. |
| `frontend/src/features/prototype/structured/StructuredPrototypeFlow.tsx` | Alternate flow mode; retains an `enterprise-card` parent and nested page/rule cards. |
| `frontend/src/features/prototype/structured/StructuredPrototypeGenerationPanel.tsx` | No-document generation state; outer card has been removed, while blueprint/progress result sections retain cards. |
| `frontend/src/app/globals.css` | Defines shared `enterprise-page`, `enterprise-panel`, and `enterprise-card` surface treatments and radius tokens. |
| `frontend/tests/projectShellRouting.test.ts` | Source-level regression assertions for workspace layout and removal of selected card/shadow recipes. |
| `.trellis/spec/ccgui/frontend/component-guidelines.md` | Current uncommitted package guideline for full-height editor chrome. |
| `.trellis/spec/vibe-kanban/frontend/component-guidelines.md` | Mirrored current uncommitted guideline for full-height editor chrome. |

## Page-by-page observations

### 1. Project configuration (`/projects`) — most over-cardified audited page

#### Surface inventory and hierarchy

`ProjectsPage` renders a two-column layout at medium widths: a `260px` left `enterprise-panel` and a right column of cards (`ProjectsPage.tsx:495-497`). For a selected project, the right column can contain:

1. project identity, remote actions, metadata, statistics, and an expanded branch list (`ProjectsPage.tsx:560-684`);
2. setup script (`ProjectsPage.tsx:54-127`);
3. run command (`ProjectsPage.tsx:130-195`);
4. a second branch section (`ProjectsPage.tsx:698-715`);
5. recent activity (`ProjectsPage.tsx:716-755`).

The branch list therefore appears both inside the primary project card (`ProjectsPage.tsx:659-681`) and as a later standalone branch card (`ProjectsPage.tsx:698-715`). In the inspected desktop state, the expanded branch list made the first right-hand card much taller than the left project selector, while additional cards continued below the viewport.

All five selected-project sections use the same `enterprise-card rounded-2xl overflow-hidden` treatment (`ProjectsPage.tsx:89`, `165`, `560`, `698`, `717`). Their visual vocabulary does not encode a different level for project identity, configuration fields, repeated records, and activity history. The left project selector is another rounded elevated panel (`ProjectsPage.tsx:497`).

The shared `Card` primitive adds `rounded-xl`, a ring, a 300ms transition, `hover:-translate-y-1`, and `hover:shadow-lg` to every consumer (`frontend/src/components/ui/card.tsx:11-17`). Consequently, the large project-detail and configuration sections carry the same lift-on-hover object behavior as a selectable standalone card.

#### Density

- Desktop: the left selector and right project-detail region are each detached rounded surfaces inside the page background. The right side then serializes heterogeneous project information as equally separated cards.
- The expanded top card combines title/actions, repository path, two metadata columns, issue statistics, and a long branch list. The following standalone branch card repeats the same branch collection.
- At `390px`, the project selector becomes a `358px × 437px` panel, followed by a `358px × 641px` project card and four more cards. The measured document height was `2308px`.
- One selected-project card had `scrollWidth: 696px` against `clientWidth: 356px` at `390px`, originating in its header/action arrangement. The screenshot showed the remote action area clipped to the right edge while the body itself remained at a `390px` document width.

### 2. Project workspaces (`/projects/[id]`) — card-heavy overview with a separate responsive defect

#### Surface inventory and hierarchy

The page uses the default `ProjectShell`, which produces a large project hero and pill-like secondary navigation (`ProjectShell.tsx:34-133`). Beneath it, four equally sized KPI tiles are rendered as rounded bordered surfaces (`ProjectWorkspacesPage.tsx:498-536`, `1082-1113`). A rounded workspace table follows (`ProjectWorkspacesPage.tsx:697-747`), and an optional rounded log panel appears above it (`ProjectWorkspacesPage.tsx:639-694`).

At desktop width, the four KPI cards occupy the full first content row. They are the strongest repeated card group on this page; the workspace records themselves are correctly expressed as divided rows inside one table surface rather than as per-record cards.

The workbench already contributes another large rounded boundary around the entire project page: `WorkbenchShell` uses `enterprise-panel ... rounded-[22px] lg:rounded-[30px]` (`WorkbenchShell.tsx:89-95`). Thus the live desktop hierarchy is global rounded workbench panel → project hero/navigation → KPI card row → rounded data table.

#### Responsive behavior

At `390px`:

- The project hero and four secondary navigation pills occupy approximately `214px` before page content begins.
- The KPI grid changes from four columns to two columns (`ProjectWorkspacesPage.tsx:498`), producing two rows of `164px × 107px` tiles.
- The toolbar remains one horizontal flex row (`ProjectWorkspacesPage.tsx:538-624`). Its measured content width was `427px` in a `340px` client region; the screenshot showed the final action clipped on the right.
- The workspace table retains the desktop template `grid-cols-[1fr_120px_90px_1.6fr_120px_70px]` in both its header and rows (`ProjectWorkspacesPage.tsx:698`, `822`). At `390px`, the table measured `scrollWidth: 497px` inside a `338px` client width. Several first-column cells collapsed to zero client width, the right-side columns were clipped, and a horizontal scrollbar appeared at the bottom of the workbench content.
- The containing default project content also measured `scrollWidth: 443px` against a `372px` client width.

This is the clearest responsive failure observed in the requested surfaces. It belongs to the project workspaces page, not the structured prototype studio.

### 3. Structured prototype (`/projects/[id]/prototypes`) — current live layout is predominantly continuous

#### Desktop hierarchy

The current live studio is an editor-style surface rather than a card collection:

- `StructuredPrototypeRoutePage` mounts `ProjectShell` with `layout="workspace"` (`StructuredPrototypeRoutePage.tsx:44-68`).
- Workspace mode compresses project identity and secondary navigation into a `56px` horizontal strip and removes the default hero spacing (`ProjectShell.tsx:34-50`, `54-89`, `104-133`).
- The studio uses a top toolbar followed by a three-column grid: `240px` page/palette rail, `minmax(440px, 1fr)` canvas, and `300px` inspector (`StructuredPrototypeStudioPage.tsx:246-331`).
- The three regions use sibling border dividers (`StructuredPrototypeStudioPage.tsx:332-487`) rather than independent outer cards.
- Page rows use a left selection border with transparent backgrounds (`StructuredPrototypePageRail.tsx:15-47`).
- Palette items are single-column divided rows (`StructuredPrototypePalette.tsx:45-80`).
- The browser/device preview keeps one thin border (`StructuredPrototypePreview.tsx:56-60`), which is distinct from structural editor chrome.

At `1440px`, the measured workbench content width was `1135px`: `240px` left rail, `595px` canvas region, and `300px` inspector. The fixed side regions therefore consume `540px`, leaving just over half of the editor width to the canvas. The preview itself includes a `185px` simulated application sidebar at desktop preview mode (`StructuredPrototypePreview.tsx:73-80`). This creates a dense center stack—editor rail, preview sidebar, preview content, inspector—but the boundaries are continuous dividers rather than repeated floating cards.

The global `WorkbenchShell` still encloses the studio in its `22/30px` rounded enterprise panel (`WorkbenchShell.tsx:93`), so one large rounded frame remains visible around the editor. Inside the canvas, sortable nodes use bordered white sections and selection outlines (`StructuredPrototypeCanvas.tsx:307-340`); these represent editable objects rather than page-level containers.

#### Medium and mobile behavior

The breakpoint is `lg` (`1024px`) in `StructuredPrototypeStudioPage.tsx:331-490`.

At `900px`:

- The left and right editor columns are hidden and the canvas receives the full `874px` studio width.
- A `56px` bottom navigation switches between Pages, Canvas, and AI.
- The desktop preview sidebar remains visible because the preview itself uses the smaller `md` breakpoint (`StructuredPrototypePreview.tsx:73-80`).
- No body-level horizontal overflow was measured.

At `390px`:

- The workbench content was `374px` wide; the studio region was `372px` wide and did not increase body width.
- The project navigation becomes a horizontally scrollable strip (`ProjectShell.tsx:86-90`). It measured `396px` of content in `151px` of visible width, so only part of the secondary navigation is visible at once; remaining links are reachable by horizontal scrolling.
- The studio toolbar wraps into three rows: project/document identity and mode, then role/checkpoint/publish/share actions, then the canvas context bar. Studio content begins around `y=217` in an `844px` viewport, leaving `534px` above the bottom panel navigation.
- The simulated application's desktop sidebar is hidden at mobile preview width and its menu icon appears (`StructuredPrototypePreview.tsx:74-80`, `106-109`). The preview form remains within the available width.
- Pages/Components, Canvas, and AI are mutually exclusive full-width panels controlled by the bottom navigation (`StructuredPrototypeStudioPage.tsx:331-488`, `489-525`). All three were opened successfully.
- The Pages panel retained the three page rows and a vertically scrollable six-item palette. The AI panel kept its message history scrollable and left the `80px` composer visible immediately above the bottom navigation.
- No body-level horizontal overflow or unreachable control was observed in these three mobile panels.

#### Remaining card-shaped areas in the structured feature

These states were identified in source but were not the initially mounted live design mode:

- Flow mode retains an outer `enterprise-card` and nested page/rule articles (`StructuredPrototypeFlow.tsx:18-81`).
- The generation state now has a continuous outer section (`StructuredPrototypeGenerationPanel.tsx:43-78`), but generated blueprint and progress results remain `enterprise-card` sections (`StructuredPrototypeGenerationPanel.tsx:166-235`), and blueprint pages are nested rounded articles (`StructuredPrototypeGenerationPanel.tsx:174-184`).
- The AI panel can render a rounded embedded preview and rounded error alert (`StructuredPrototypeAiPanel.tsx:160-181`, `209-225`). These are conditional evidence/error objects within the inspector rather than the page skeleton.

## Current uncommitted changes

The working tree already contains a coherent card-reduction pass for the structured studio. The relevant diff totals 10 files, with `164` insertions and `57` deletions overall; the product/spec/test files below must be treated as existing work rather than clean main-branch baseline.

| Modified file | Existing change observed |
|---|---|
| `frontend/src/features/projects/ProjectShell.tsx` | Adds `layout?: "default" | "workspace"`; workspace mode is full-height, uses compact identity, tab-like border navigation, and no padded max-width child wrapper. |
| `frontend/src/features/prototype/structured/StructuredPrototypeRoutePage.tsx` | Selects `layout="workspace"`. |
| `frontend/src/features/prototype/structured/StructuredPrototypeStudioPage.tsx` | Removes the studio's outer rounded border/card, changes viewport-height calculation to full height, shortens toolbar, removes duplicate back button, and converts the document sequence chip to plain monospaced text. |
| `frontend/src/features/prototype/structured/StructuredPrototypeGenerationPanel.tsx` | Removes `enterprise-panel rounded-xl` from the outer generation section. |
| `frontend/src/features/prototype/structured/StructuredPrototypePageRail.tsx` | Replaces rounded bordered page cards with continuous rows and a left selection rule. |
| `frontend/src/features/prototype/structured/StructuredPrototypePalette.tsx` | Replaces a two-column grid of large rounded palette cards with divided compact rows. |
| `frontend/src/features/prototype/structured/StructuredPrototypePreview.tsx` | Reduces preview padding, removes `shadow-xl`, and changes the preview radius from `rounded-lg` to `rounded-sm`. |
| `frontend/tests/projectShellRouting.test.ts` | Adds assertions for workspace layout and absence of the removed outer-card, palette-card, and preview-shadow patterns. |
| `.trellis/spec/ccgui/frontend/component-guidelines.md` | Adds a full-height editor rule: one page surface, sibling dividers, and cards only for records/dialogs/device preview boundaries. |
| `.trellis/spec/vibe-kanban/frontend/component-guidelines.md` | Mirrors the same full-height editor rule. |

The live app reflected these changes during inspection. Therefore, the structured studio shown live is not representative of the pre-diff main-branch layout; the git diff establishes that the studio previously had an additional rounded outer panel, card-like page navigation, a two-column palette-card grid, and a shadowed preview.

## Code Patterns

### Shared surface recipes

`frontend/src/app/globals.css:235-256` defines three layers:

- `.enterprise-page`: ambient page gradients;
- `.enterprise-panel`: border, raised gradient, shadow, and blur;
- `.enterprise-card`: border, raised background, and shadow.

Radius tokens are `0.75rem` and `1rem` (`globals.css:75-76`), while the global workbench bypasses them with `22px/30px` rounding (`WorkbenchShell.tsx:93`). This produces several concurrently visible radius scales on project pages: `30px` workbench frame, `16px` cards/panels, `12px` KPI/table surfaces, and smaller controls.

### Structural distinction in current code

- `ProjectsPage` uses `Card` for page sections and `enterprise-panel` for its selector.
- `ProjectWorkspacesPage` uses custom rounded bordered KPI/table sections rather than `Card`.
- The current structured studio uses CSS Grid, sibling borders, and one preview boundary for its primary structure.
- The uncommitted guideline records this distinction explicitly at `.trellis/spec/ccgui/frontend/component-guidelines.md:101-130` and `.trellis/spec/vibe-kanban/frontend/component-guidelines.md:101-130`.

## Related Specs

- `.trellis/tasks/07-14-refactor-frontend-card-layout/prd.md` — task goal, acceptance criteria, open scope question, and current editor-layout direction.
- `.trellis/spec/ccgui/frontend/component-guidelines.md:95-130` — panel recipe and newly added full-height editor chrome contract.
- `.trellis/spec/vibe-kanban/frontend/component-guidelines.md:95-130` — mirrored panel/editor contract plus project-page structural scenarios later in the file.

## External References

None. This audit is based on current repository code, the current uncommitted diff, and the running local application.

## Caveats / Not Found

- The ranking is limited to `/projects`, `/projects/[id]`, and `/projects/[id]/prototypes`, as requested. It is not a claim that `/projects` is the most card-heavy route in the entire application.
- Flow mode and the no-document generation state were inspected in source, not fully exercised live, because the existing prototype opened directly into design mode with persisted data.
- Desktop screenshot dimensions reported by Chrome were `1440 × 749` CSS pixels after window resizing, rather than the requested `1440 × 1000`; width-dependent conclusions remain valid, while vertical measurements are reported from the actual viewport.
- Existing global endpoint `404`s were observed during one prototype desktop pass. They did not prevent the audited controls or data from rendering and were not traced further because they are outside the layout query.
- No product code, spec, test, server process, or persisted application data was changed by this audit. This markdown file is the only file written.
