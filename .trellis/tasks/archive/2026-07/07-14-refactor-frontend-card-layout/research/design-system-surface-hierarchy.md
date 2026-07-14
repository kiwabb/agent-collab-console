# Research: Frontend design-system surface hierarchy

- **Query**: Research the repository's frontend design-system conventions for task `.trellis/tasks/07-14-refactor-frontend-card-layout`. Inspect globals/theme tokens, shared components, component guidelines, and current structured prototype components. Determine a coherent surface/radius/border/spacing hierarchy that reduces cardification without inventing a disconnected visual language. Identify accessibility and responsive constraints.
- **Scope**: Internal
- **Date**: 2026-07-14

## Findings

### Files Found

| File Path | Description |
|---|---|
| `frontend/src/app/globals.css` | Canonical dark/light color tokens, semantic aliases, radii, shadows, reusable panel/card recipes, density preferences, and reduced-motion behavior. |
| `frontend/src/features/workbench/WorkbenchShell.tsx` | Outermost application frame: `h-dvh`, global sidebar, and the one large rounded `enterprise-panel` that contains route content. |
| `frontend/src/features/workbench/components/AppSidebar.tsx` | Existing elevated navigation boundary and fixed desktop width (`w-64`). |
| `frontend/src/features/workbench/components/AppHeader.tsx` | Dense 56px application header and existing compact control sizing. |
| `frontend/src/features/projects/ProjectShell.tsx` | Project-level default vs workspace layout; workspace mode converts project chrome into a continuous 56px navigation strip and removes inner max-width/padding. |
| `frontend/src/features/prototype/structured/StructuredPrototypeRoutePage.tsx` | Mounts the studio through `WorkbenchShell` and `ProjectShell layout="workspace"`. |
| `frontend/src/features/prototype/structured/StructuredPrototypeStudioPage.tsx` | Current continuous toolbar + rail + canvas + inspector composition and narrow-screen panel switcher. |
| `frontend/src/features/prototype/structured/StructuredPrototypePageRail.tsx` | Page navigation expressed as full-width rows with an active left rule rather than cards. |
| `frontend/src/features/prototype/structured/StructuredPrototypePalette.tsx` | Palette expressed as divided rows with drag/button semantics rather than a card grid. |
| `frontend/src/features/prototype/structured/StructuredPrototypePreview.tsx` | Real browser/device preview boundary; intentionally separate white document palette inside console chrome. |
| `frontend/src/features/prototype/structured/StructuredPrototypeGenerationPanel.tsx` | Generation state uses one continuous split surface, plus remaining domain-record and preview boundaries. |
| `frontend/src/features/prototype/structured/StructuredPrototypeFlow.tsx` | Flow view still uses an `enterprise-card` wrapper and nested page/rule cards. |
| `frontend/src/features/prototype/structured/StructuredPrototypeAiPanel.tsx` | Divider-based chat/history region; status pills and a genuine generated-preview boundary remain raised. |
| `frontend/src/features/prototype/structured/StructuredPrototypeInspector.tsx` | Inspector form spacing and target-specific control styles. |
| `frontend/src/features/prototype/structured/StructuredPrototypeEvidence.tsx` | Evidence records currently use repeated raised cards inside the inspector domain. |
| `frontend/src/features/prototype/structured/StructuredPrototypeCanvas.tsx` | Embedded prototype document and selection/drag semantics; its hard-coded light palette is content, not console chrome. |
| `frontend/src/components/ui/card.tsx` | Shared object-card primitive: raised `bg-card`, `rounded-xl`, ring, and hover lift/shadow. |
| `frontend/src/components/ui/button.tsx` | Canonical control radius, sizes, focus ring, disabled state, and pressed motion. |
| `frontend/src/components/ui/input.tsx` | Canonical input surface, radius, border, focus, invalid, and disabled states. |
| `frontend/src/components/ui/textarea.tsx` | Canonical textarea styling, matching Input. |
| `frontend/src/components/ui/select.tsx` | Canonical trigger and floating popup conventions; popup uses popover surface, ring, and shadow. |
| `frontend/src/components/ui/tabs.tsx` | Canonical Base UI tab semantics and default/line visual variants. |
| `frontend/src/components/ui/dialog.tsx` | Floating modal boundary: `bg-popover`, `rounded-xl`, ring, and overlay. |
| `frontend/src/components/ui/sheet.tsx` | Edge-attached overlay convention: popover surface, directional divider, shadow, and no rounded card shell. |
| `frontend/src/components/ui/separator.tsx` | Semantic 1px divider backed by the `border` token. |
| `frontend/src/providers/ThemeProvider.tsx` | Applies explicit/system light and dark themes through `data-theme` and `color-scheme`. |
| `frontend/src/providers/PreferencesProvider.tsx` | Applies font-size, compact-mode, and reduced-motion preferences to the root. |
| `frontend/tests/projectShellRouting.test.ts` | Source-contract regression assertions for workspace mounting and removal of rounded/card-like studio chrome. |
| `.trellis/spec/ccgui/frontend/component-guidelines.md` | Active frontend design contract, including the full-height editor rule. |
| `.trellis/spec/vibe-kanban/frontend/component-guidelines.md` | Mirrored frontend contract and relevant project-page scenarios. |
| `.trellis/spec/cc-switch/frontend/component-guidelines.md` | Explicitly inactive; redirects current frontend work to the ccgui spec. |

### Existing Token and Surface Vocabulary

The repository already has a complete neutral surface ladder; this task does not need a parallel palette:

| Existing token/recipe | Dark value / behavior | Light value / behavior | Existing meaning |
|---|---|---|---|
| `bg-background` | `#0b0b0c` | `#f6f7f9` | App/canvas ground. |
| `bg-surface` | `#0f1115` | `#ffffff` | “Panel walls”: sidebar, rail, inspector, toolbar regions. |
| `bg-surface-raised` | `#161a21` | `#fdfdfd` | Cards, selected segmented controls, contained records. |
| `bg-surface-input` | `#1b2230` | `#eef1f5` | Inputs, compact segmented-control beds, keyboard chips. |
| `bg-surface-hover` | `#181e29` | `#e8edf3` | Row hover, not a persistent layer. |
| `bg-card` | Mix of raised surface and white | Same semantic alias | Shared object Card surface. |
| `bg-popover` | Mix of panel surface and white | Same semantic alias | Menus, dialogs, floating overlays. |
| `border-border-subtle` | `#232a38` | `#dde3eb` | Structural dividers and quiet boundaries. |
| `border-border-muted` | `#2e3647` | `#ced7e2` | Inputs and visible object/preview perimeters. |
| `border-border-strong` | `#3d4961` | `#aeb9c7` | Emphasized hover/drop/empty-state boundaries. |
| `enterprise-panel` | Border + panel/raised gradient + very soft large shadow + blur | Token-derived | High-level app panel boundary. |
| `enterprise-card` | Border + raised surface + subtle highlight + soft shadow | Token-derived | Independent object/record card. |

Source: `frontend/src/app/globals.css:7-31`, `161-182`, `234-256`, `448-487`.

`globals.css` also defines the semantic brand/status families (`brand`, `done`, `failed`, `warning`, `tool`, and their translucent backgrounds/rings) rather than requiring local colors (`frontend/src/app/globals.css:17-61`). Tailwind v4 aliases such as `--color-popover`, `--color-card`, `--color-border`, and `--color-ring` live under `@theme`, because variables under `:root` alone cannot generate utilities (`frontend/src/app/globals.css:137-155`; component guideline lines 153-157).

The embedded prototype is a separate content plane. `StructuredPrototypePreview.tsx:58-145` and `StructuredPrototypeCanvas.tsx:43-149` use a hard-coded light product palette inside a white preview boundary. The console-chrome regression test deliberately prohibits hex colors in the Studio and Generation panel, but not inside Preview/Canvas (`frontend/tests/projectShellRouting.test.ts:42-60`). This establishes that preview-document colors should not be promoted into, or confused with, console surface tokens.

### Current Direction Already Present in the Working Tree

The current uncommitted changes already encode the intended non-cardified editor structure and must be treated as the baseline rather than reverted:

```tsx
// ProjectShell workspace mode
<div className="flex h-full min-h-0 flex-col">…</div>
<nav className="min-w-0 flex-1 self-stretch overflow-x-auto">…</nav>
```

`frontend/src/features/projects/ProjectShell.tsx:34-35`, `86-119`.

```tsx
// Studio structure
<main className="grid min-h-0 grid-cols-1 lg:grid-cols-[240px_minmax(440px,1fr)_300px]">
  <aside className="… border-r border-border-subtle bg-surface" />
  <section className="min-h-0 grid-rows-[44px_minmax(0,1fr)]" />
  <aside className="… border-l border-border-subtle bg-surface" />
</main>
```

`frontend/src/features/prototype/structured/StructuredPrototypeStudioPage.tsx:331-447`.

The same direction appears in the navigation collections:

- Page rail: full-width rows, `border-l-2`, transparent default surface, `bg-brand-bg` active state, and `aria-current="page"` (`StructuredPrototypePageRail.tsx:17-46`).
- Palette: one column, shared `divide-y`, transparent rows, and a brand left edge on hover (`StructuredPrototypePalette.tsx:45-80`).
- Project workspace navigation: underline/edge navigation, no pill/card per item (`ProjectShell.tsx:103-123`).
- Generation: one full-height surface split by a responsive `border-b`/`lg:border-r`, not an outer rounded panel (`StructuredPrototypeGenerationPanel.tsx:43-80`).

The source-contract test now asserts all of those structural decisions: the route uses `layout="workspace"`; the Studio cannot regain an outer `overflow-hidden rounded-xl border`; Generation cannot regain `enterprise-panel`/`rounded-xl`; Preview cannot regain `shadow-xl`; Palette cannot regain raised rounded cards (`frontend/tests/projectShellRouting.test.ts:30-60`).

### Coherent Surface Hierarchy

The hierarchy below is composed entirely from established repository tokens and component behavior.

| Level | Semantic role | Surface | Boundary/elevation | Radius | Spacing rhythm | Current repository examples |
|---|---|---|---|---|---|---|
| **0. App ground** | Ambient area behind the workbench | `bg-background` plus existing shell gradient | None inside content | None | Outer shell owns viewport gutters | `WorkbenchShell.tsx:61-95` |
| **1. Application shell** | One top-level work area | `enterprise-panel` | One subtle perimeter and shell shadow | Exceptional `22px`/`30px` outer radius only | Shell padding/gaps of `2`/`3` | `WorkbenchShell.tsx:89-95`; `AppSidebar.tsx:190` |
| **2. Structural regions** | Project strip, editor toolbar, page rail, canvas well, inspector | `bg-surface` or low-opacity `bg-background/35` for the canvas well | One-sided `border-border-subtle` dividers between siblings; no shadow | **0** | Compact chrome `px-3`/`px-4`; 44–56px headers; region content `p-3`/`p-4` | `ProjectShell.tsx:35-52`; `StructuredPrototypeStudioPage.tsx:248-490` |
| **3. Rows and grouped controls** | Page/palette rows, tabs, segmented mode/viewport controls | Transparent/`bg-surface-hover` rows; `bg-surface-input` control bed; active `bg-surface-raised` or `bg-brand-bg` | Shared divider, active left/bottom rule, or control border; no free-standing shadow except selected control `shadow-sm` | Row **0**; trigger/segment `rounded-md`; group bed `rounded-lg` | `gap-1`/`gap-2`; `px-2`/`px-3`; row minimum 44–52px | Page rail, palette, project nav, Studio mode/viewport controls |
| **4. Independent content object** | A repeated domain record, alert, evidence object, or genuinely selectable item | `bg-surface-raised`, `bg-card`, or semantic tinted background | `border-subtle` for quiet records, `border-muted` for a stronger perimeter, semantic ring for status | `rounded-lg`; shared `Card` uses `rounded-xl` when true card elevation/hover is intended | `p-3`/`p-4`; internal `gap-2`/`gap-3`; section separation `gap-4` | Generation blueprint/progress, Evidence records, Alerts |
| **5. Real preview boundary** | Browser/device/artifact that must read as a distinct coordinate system | `bg-white` content inside `bg-background/35` canvas | One `border-border-muted`; no decorative lift | Current `rounded-sm` | Canvas gutter `p-3 sm:p-4` | `StructuredPrototypePreview.tsx:56-60`; AI and Generation iframes |
| **6. Floating overlay** | Menu, popover, dialog, sheet | `bg-popover` | Ring/perimeter + `shadow-md`/`shadow-lg`; overlay/backdrop | Popup `rounded-lg`, dialog `rounded-xl`; edge-attached sheet has no card radius | Usually `p-4`, list internals `p-1` | `select.tsx:57-95`, `dialog.tsx:27-73`, `sheet.tsx:27-76` |
| **7. Status/chip** | Compact state label, not a layout container | Status tint such as `bg-done-bg`/`bg-tool-bg` | Matching semantic ring; icon/text accompany color | `rounded-full` is reserved for compact status identity | `px-2`/`px-3`, 24–32px minimum height | Generation and AI run status (`GenerationPanel.tsx:57-75`; `AiPanel.tsx:105-127`) |

This hierarchy preserves the repository’s existing “outer shell may float; editor regions join by dividers; objects may be cards; overlays float” language. It does not require new colors, shadows, or surface names.

### Radius Hierarchy

The repository has `--radius: 0.5rem` in semantic variables, theme extensions `--radius-xl: 0.75rem` and `--radius-2xl: 1rem`, and an older `.cc-card` recipe at 10px (`globals.css:70-76`, `161-183`, `289-300`). Shared primitives settle into the following practical scale:

1. **No radius** — full-height structural siblings, headers, rails, inspector, lists, sheets attached to an edge.
2. **`rounded-sm`** — restrained browser/device preview perimeter; currently used by `StructuredPrototypePreview` (`:58`).
3. **`rounded-md`** — compact buttons, tab triggers, selected segments, and icon controls (`StructuredPrototypeStudioPage.tsx:256-323`, `386-403`, `449-465`).
4. **`rounded-lg`** — inputs, textareas, alerts, compact status containers, and independent small records (`button.tsx:8-35`; `input.tsx:6-16`; `alert.tsx:6-19`).
5. **`rounded-xl`** — true shared Card and modal dialog, where the whole object is elevated and self-contained (`card.tsx:5-19`; `dialog.tsx:40-73`).
6. **`rounded-[22px]`/`rounded-[30px]`** — exceptional application shell only (`WorkbenchShell.tsx:93`; `AppSidebar.tsx:190`).
7. **`rounded-full`** — status badges, presence, and pill identity; not structural navigation in workspace mode.

Nesting therefore tightens inward rather than repeating one radius at every level: large shell → square divided region → medium object/control → small inner trigger. The shared `Card` also applies hover lift and `shadow-lg` (`card.tsx:15`), which makes it appropriate for an interactive independent object but visually incompatible with a structural rail, toolbar, or inspector.

### Border and Elevation Hierarchy

- **`border-subtle` / 1px:** default structural separator and low-priority record divider. Use one edge (`border-r`, `border-l`, `border-b`, `divide-y`) when siblings already share a parent rather than drawing a rectangle around each sibling. This is the dominant Studio pattern (`StructuredPrototypeStudioPage.tsx:249`, `334`, `350`, `369`, `445`, `449`, `490`).
- **`border-muted` / 1px:** control boundaries, browser/device preview perimeter, and objects that need a complete outline (`StructuredPrototypeStudioPage.tsx:256`, `281`, `297`, `386`; `StructuredPrototypePreview.tsx:58`).
- **`border-strong`:** emphasized empty/drop boundary or hover affordance, not a default card perimeter (`StructuredPrototypeGenerationPanel.tsx:147`; `globals.css:28-31`).
- **Brand border/ring:** selected navigation edge, keyboard focus, or active drag/selection. The page rail combines a 2px brand edge, brand tint, and `aria-current`, so selection is not expressed only by a fill (`StructuredPrototypePageRail.tsx:23-29`).
- **Status border/ring:** error, done, warning, and tool states use the existing semantic `*-bg` + `*-ring` + status text/icon combinations (`globals.css:47-61`).
- **Shadow:** reserved for application shell, floating overlays, and a true lifted Card. Structural regions and real preview boundaries use no drop shadow. The test expressly rejects `shadow-xl` on Preview (`projectShellRouting.test.ts:55`).

### Spacing Hierarchy

Current editor code is based on Tailwind’s 4px spacing increments and already has a usable dense-tool rhythm:

| Relationship | Existing scale | Evidence |
|---|---|---|
| Icon ↔ label / adjacent compact controls | `gap-1` to `gap-2` (4–8px) | Studio controls and Palette rows (`StudioPage.tsx:256-328`; `Palette.tsx:48-61`) |
| Row internal padding | `px-2`/`px-3`, `py-2` (8–12px) | Page rail and Palette (`PageRail.tsx:17-44`; `Palette.tsx:45-62`) |
| Toolbar/structural strip | `px-3`/`px-4`; height 44, 52, or 56px | Project strip, Studio top toolbar and sub-toolbar (`ProjectShell.tsx:50`; `StudioPage.tsx:248-250`, `331-369`) |
| Inspector/form group | `gap-5 p-4`; labels use `gap-2` | `StructuredPrototypeInspector.tsx:112-201` |
| Independent object | `p-3`/`p-4`, with `gap-2`/`gap-3` | Generation records and Evidence (`GenerationPanel.tsx:166-235`; `Evidence.tsx:27-91`) |
| Major generated-state split | `p-5 sm:p-6` | `StructuredPrototypeGenerationPanel.tsx:45-46`, `78-141` |
| Preview canvas gutter | `p-3 sm:p-4` | `StructuredPrototypePreview.tsx:56` |

The coherent rule is to let spacing group structural content before adding a boundary: compact 4–8px gaps inside one control/row, 12–16px inside an object/region, and 20–24px only for a major setup/generation pane. Divider-based lists should use row padding plus `divide-y`, not `gap` plus one border/radius per item.

### Accessibility Constraints

#### Repository contract

The active guideline requires semantic HTML, keyboard operability, focus restoration for overlays, icon-button labels, live status semantics, reduced-motion support, and a non-color signal for every status (`.trellis/spec/ccgui/frontend/component-guidelines.md:166-182`). Shared Base UI primitives implement this contract more completely than local ad-hoc controls:

- Button/Input/Textarea/Select/Tab use `focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50` and explicit disabled/invalid states (`button.tsx:8-35`; `input.tsx:6-16`; `textarea.tsx:5-15`; `select.tsx:31-54`; `tabs.tsx:50-63`).
- Dialog and Sheet use Base UI semantics plus an explicit focus trap; close buttons have screen-reader text (`dialog.tsx:40-73`; `sheet.tsx:40-76`).
- The global reduced-motion reset collapses decorative animation/transition duration, while marked loading/progress motion remains active (`globals.css:362-445`). Preview width transitions explicitly use `motion-reduce:transition-none` (`StructuredPrototypePreview.tsx:58`).

#### Target-specific interaction semantics that the visual hierarchy must preserve

- Project navigation and page rail expose current location via `aria-current="page"` (`ProjectShell.tsx:100-118`; `StructuredPrototypePageRail.tsx:19-44`).
- Design/flow, viewport, and mobile panel selectors expose state with `aria-pressed` (`StructuredPrototypeStudioPage.tsx:256-271`, `386-402`, `508-523`).
- Icon-only checkpoint, published-preview, open-preview, retry, and send controls have labels/titles (`StructuredPrototypeStudioPage.tsx:295-326`; `StructuredPrototypeGenerationPanel.tsx:238-259`, `287-303`; `StructuredPrototypeAiPanel.tsx:160-181`, `209-225`, `241-254`).
- Errors use `role="alert"`; preview notifications use `role="status"` (`StructuredPrototypeRoutePage.tsx:52-65`; `GenerationPanel.tsx:287-303`; `AiPanel.tsx:209-225`; `StructuredPrototypePreview.tsx:116-127`).
- Page/Palette actions are native buttons. DnD installs both Pointer and Keyboard sensors (`StructuredPrototypeStudioPage.tsx:91-94`), and palette/sortable handles receive dnd-kit attributes/listeners (`StructuredPrototypePalette.tsx:38-62`; `StructuredPrototypeCanvas.tsx:307-340`).
- Current common row/primary target heights are 44px (`min-h-11`) or larger; dense toolbar icon controls are 36px (`size-9`), while the narrow-screen bottom panel navigation is 56px high (`StructuredPrototypeStudioPage.tsx:295-315`, `490-523`). Removing cards must not reduce these hit areas.
- Selection cannot rely on a surface color alone. Existing patterns pair color with left/bottom border, icon/text, `aria-current`, `aria-pressed`, or `aria-selected`; those redundant signals are part of the hierarchy.

#### Semantics/focus caveats visible in the current target

- Inspector buttons use `role="tab"` and `aria-selected`, but their parent is not a `role="tablist"`, there are no associated tabpanels/`aria-controls`, and local state does not provide the Base UI Tabs keyboard model (`StructuredPrototypeStudioPage.tsx:449-486`). The repository already has a semantic Base UI `Tabs` primitive (`components/ui/tabs.tsx`).
- Most local Studio buttons rely on browser focus indication and do not apply the shared `focus-visible:ring-3` recipe. The custom textareas remove native outlines and add a brand ring with `focus:` rather than the shared `focus-visible:` form (`GenerationPanel.tsx:88`; `AiPanel.tsx:234`; `Inspector.tsx:122`; `Canvas.tsx:256`). Any surface simplification must leave an equally visible keyboard indicator against both `surface` and `surface-input`.
- Theme, font-size, compact-mode, and reduced-motion preferences are applied at the root (`ThemeProvider.tsx:39-43`; `PreferencesProvider.tsx:62-68`). Console chrome should remain token-based in both dark and light modes. The structured workspace uses several fixed `text-[9px]`/`text-[10px]` labels and fixed-height strips, so large-font and zoom checks are relevant even though the global font-size preference changes only Tailwind size variables (`globals.css:328-360`).
- The component guideline requires all user-visible strings to use `useI18n().t()` (`component-guidelines.md:197-201`). Visual restructuring should not replace semantic labels with icon-only, untranslated controls.

### Responsive Constraints

#### Full-height containment

The outer workbench is `h-dvh overflow-hidden`; route content scrolls inside the one rounded main panel (`WorkbenchShell.tsx:61-95`). Workspace `ProjectShell` then uses `flex h-full min-h-0 flex-col`, gives the project strip fixed content height, and gives children `min-h-0 flex-1` (`ProjectShell.tsx:34-35`, `129-137`). The Studio continues the chain with `h-full min-h-[640px] overflow-hidden` and local scrolling in rail/canvas/inspector (`StructuredPrototypeStudioPage.tsx:248`, `331-487`). Preserving every `min-h-0`/`min-w-0` handoff is required to prevent nested flex/grid content from forcing the shell wider or taller than the viewport.

#### Desktop three-column minimum

At `lg`, Studio uses `240px + minmax(440px, 1fr) + 300px`, so its hard minimum internal width is **980px** (`StructuredPrototypeStudioPage.tsx:331`). At the same breakpoint, Workbench also shows a fixed `w-64` (256px) sidebar, a 12px gap, and 12px left/right padding (`WorkbenchShell.tsx:89-93`; `AppSidebar.tsx:190`). The practical viewport width needed for the full three-column editor is therefore roughly **1,272px** before borders, even though Tailwind’s `lg` layout activates at a lower width. Between the breakpoint and that practical width, the fixed rails plus 440px center can overflow a clipped shell. This is the principal responsive sizing constraint for any retained three-pane hierarchy.

#### Existing narrow-screen mode

Below `lg`, only one of left/canvas/right is rendered at a time, selected by a persistent 56px bottom navigation; Studio reserves `pb-14` so content remains reachable (`StructuredPrototypeStudioPage.tsx:248`, `331-367`, `443-525`). The top toolbar wraps, moves its action group to a full-width third row, hides save-state text until `xl`, and hides the publish label below `sm` (`StructuredPrototypeStudioPage.tsx:249-328`). Project navigation scrolls horizontally rather than wrapping in workspace mode (`ProjectShell.tsx:86-119`). These behaviors are part of the current narrow-screen contract.

#### Content overflow boundaries

- Center and side panes use `min-w-0`/`min-h-0` plus local `overflow-auto` (`StructuredPrototypeStudioPage.tsx:354`, `365`, `468`).
- Preview chooses desktop `100%`, tablet `760px`, and mobile `390px`, but caps every choice at `maxWidth: 100%`; its outer canvas scrolls (`StructuredPrototypePreview.tsx:31`, `56-60`).
- The embedded preview’s desktop side navigation appears at `md`; other preview widths collapse it (`StructuredPrototypePreview.tsx:72-104`).
- Runtime tables use horizontal overflow, with live rows enforcing `min-w-[520px]` (`StructuredPrototypeCanvas.tsx:74-75`, `126-149`).
- Generation moves from vertical regions to a `360px + minmax(0,1fr)` split only at `lg`, changes bottom border to right border, and changes blueprint cards to three columns at `sm` (`StructuredPrototypeGenerationPanel.tsx:78-80`, `141-185`).

### Shared Components and Reuse Boundary

- `Card` is not the default container. Its `rounded-xl bg-card ring-1` plus hover translation/shadow communicates an independent, interactive object (`components/ui/card.tsx:5-19`). Structural Studio regions should therefore remain plain semantic elements with one-sided dividers.
- `Separator` provides a token-backed semantic divider when a dedicated separator element is preferable to a border utility (`components/ui/separator.tsx:7-17`).
- `Tabs` has a `line` variant that already expresses active state without a filled segmented-control card and carries Base UI keyboard semantics (`components/ui/tabs.tsx:20-63`).
- `Sheet` demonstrates the established responsive/edge-overlay language: attached side surface, one directional border, and shadow rather than a rounded nested card (`components/ui/sheet.tsx:40-76`).
- Button, Input, Textarea, Select, Alert, Dialog, and Sheet centralize focus/invalid/disabled/overlay behavior. The structured prototype currently duplicates several of those recipes locally; the visual hierarchy should match these primitives even where direct replacement is outside this research task.

### Related Specs

- `.trellis/spec/ccgui/frontend/component-guidelines.md:81-130` — active Tailwind/token conventions and the explicit full-height editor contract: one page surface, divider-based toolbar/rail/canvas/inspector, no rounded outer editor panel, no card-grid navigation, cards retained for domain records/dialogs/real preview boundaries.
- `.trellis/spec/ccgui/frontend/component-guidelines.md:166-182` — semantic HTML, keyboard, ARIA, motion, and non-color signaling requirements.
- `.trellis/spec/vibe-kanban/frontend/component-guidelines.md:81-130` — mirrored styling and full-height editor contract.
- `.trellis/spec/vibe-kanban/frontend/component-guidelines.md:192-210` — project shell and secondary-navigation scenario.
- `.trellis/spec/cc-switch/frontend/component-guidelines.md:7-27` — package is inactive; current frontend conventions belong to ccgui.
- `.trellis/tasks/07-14-refactor-frontend-card-layout/prd.md` — task goal, acceptance criteria, current-worktree constraint, and editor-first technical direction.

### External References

None required. The query is repository-convention research, and the repository already contains explicit design-system, accessibility, and full-height editor contracts.

## Caveats / Not Found

- The target files and both active component-guideline copies already contain uncommitted non-cardification changes. Findings describe the current working tree, not only `HEAD`; implementation must preserve and extend those changes rather than reset them.
- No dedicated spacing-token namespace or formal named radius scale beyond Tailwind/theme values was found. The spacing/radius hierarchy above is an extraction of repeated existing code patterns, not a claim that named `surface-*` or `radius-*` component APIs already exist.
- No global focus utility specific to the structured editor was found. Shared UI primitives have a consistent focus recipe, while target-local controls vary.
- No container-query or intermediate two-pane adaptation was found for the Studio. Its layout changes directly from one-panel mobile mode to a 980px-minimum three-column grid at `lg`.
- `StructuredPrototypeFlow.tsx` and `StructuredPrototypeEvidence.tsx` retain more repeated raised-card treatment than PageRail/Palette/Studio chrome. They are current examples of true domain grouping mixed with remaining nested card treatment; this research does not change them.
- The shared `Card` primitive globally lifts every card on hover. That behavior is part of the existing primitive and reinforces why it should not be used as a neutral structural section.
