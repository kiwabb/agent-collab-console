# Theme and Internationalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add in-app light/dark/system theme switching and Chinese/English UI switching for the current Next.js workbench, after removing unused legacy JSX components.

**Architecture:** Keep this as a frontend-only feature. Add small client providers for theme and locale, store preferences in `localStorage`, apply the resolved theme to the document root, and replace hardcoded current-workbench UI strings with dictionary lookups.

**Tech Stack:** Next.js 15 App Router, React 18, TypeScript, Tailwind CSS v4 CSS variables, lucide-react, Node test runner.

---

## File Structure

- Delete legacy components: `frontend/src/components/ApprovalDialog.jsx`, `frontend/src/components/ArtifactPanel.jsx`, `frontend/src/components/CodexSessionList.jsx`, `frontend/src/components/CodexTaskList.jsx`, `frontend/src/components/WorkspaceList.jsx`.
- Modify legacy tests: `frontend/tests/executionProcessPatch.test.js` to remove assertions that read deleted legacy component files.
- Create theme module: `frontend/src/providers/ThemeProvider.tsx`.
- Create i18n module: `frontend/src/providers/I18nProvider.tsx`.
- Create dictionaries: `frontend/src/lib/i18n.ts`.
- Modify app root: `frontend/src/app/layout.tsx`.
- Modify global tokens: `frontend/src/app/globals.css`.
- Modify current workbench path only: `frontend/src/features/workbench/WorkbenchPage.tsx`, `frontend/src/features/workspaces/WorkspaceGrid.tsx`, `frontend/src/features/issues/IssueBoard.tsx`, `frontend/src/features/issues/IssueCard.tsx`, `frontend/src/features/issues/IssueDetailPanel.tsx`, `frontend/src/features/agents/AgentCoordinationPanel.tsx`, `frontend/src/features/runs/RunDetail.tsx`, `frontend/src/features/artifacts/ArtifactPanel.tsx`, `frontend/src/features/approvals/ApprovalDialog.tsx`, `frontend/src/lib/task-selection.ts`.
- Add tests: `frontend/tests/theme-i18n.test.ts`.

## Task 1: Remove Unused Legacy JSX Components

**Files:**
- Delete: `frontend/src/components/ApprovalDialog.jsx`
- Delete: `frontend/src/components/ArtifactPanel.jsx`
- Delete: `frontend/src/components/CodexSessionList.jsx`
- Delete: `frontend/src/components/CodexTaskList.jsx`
- Delete: `frontend/src/components/WorkspaceList.jsx`
- Modify: `frontend/tests/executionProcessPatch.test.js`

- [ ] **Step 1: Confirm the current app does not import the legacy components**

Run:

```bash
cd frontend
rg -n "@/components/(ApprovalDialog|ArtifactPanel|CodexSessionList|CodexTaskList|WorkspaceList)|src/components/(ApprovalDialog|ArtifactPanel|CodexSessionList|CodexTaskList|WorkspaceList)|\\.\\./components/(ApprovalDialog|ArtifactPanel|CodexSessionList|CodexTaskList|WorkspaceList)" src tests
```

Expected: references only in `tests/executionProcessPatch.test.js` and within the legacy files themselves.

- [ ] **Step 2: Delete the unused JSX files**

Remove the five legacy component files listed above. Keep `frontend/src/components/ui/*` untouched.

- [ ] **Step 3: Update the patch tests**

In `frontend/tests/executionProcessPatch.test.js`, remove test blocks that open these paths:

```text
../src/components/CodexTaskList.jsx
../src/components/WorkspaceList.jsx
../src/components/CodexSessionList.jsx
../src/components/ApprovalDialog.jsx
```

Keep tests that validate current TypeScript code and generic patch behavior.

- [ ] **Step 4: Run frontend tests**

Run:

```bash
cd frontend
npm test
```

Expected: all remaining tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components frontend/tests/executionProcessPatch.test.js
git commit -m "chore: remove unused legacy jsx components"
```

## Task 2: Add Theme Provider and Light/Dark Tokens

**Files:**
- Create: `frontend/src/providers/ThemeProvider.tsx`
- Modify: `frontend/src/app/layout.tsx`
- Modify: `frontend/src/app/globals.css`
- Test: `frontend/tests/theme-i18n.test.ts`

- [ ] **Step 1: Add theme behavior tests**

Create `frontend/tests/theme-i18n.test.ts` with tests for theme preference resolution. Use pure exported helpers from `ThemeProvider.tsx` so the test can run in Node:

```ts
import test from "node:test";
import assert from "node:assert/strict";
import { resolveThemePreference } from "../src/providers/ThemeProvider";

test("resolveThemePreference returns explicit light and dark choices", () => {
  assert.equal(resolveThemePreference("light", true), "light");
  assert.equal(resolveThemePreference("dark", false), "dark");
});

test("resolveThemePreference follows system preference", () => {
  assert.equal(resolveThemePreference("system", true), "dark");
  assert.equal(resolveThemePreference("system", false), "light");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd frontend
npm test
```

Expected: failure because `frontend/src/providers/ThemeProvider.tsx` does not exist.

- [ ] **Step 3: Implement ThemeProvider**

Create `frontend/src/providers/ThemeProvider.tsx`:

```tsx
"use client";

import React, { createContext, useContext, useEffect, useMemo, useState } from "react";

export type ThemePreference = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

const STORAGE_KEY = "agent-collab.theme";
const DEFAULT_THEME: ThemePreference = "system";

interface ThemeContextValue {
  theme: ThemePreference;
  resolvedTheme: ResolvedTheme;
  setTheme: (theme: ThemePreference) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

export function resolveThemePreference(theme: ThemePreference, systemPrefersDark: boolean): ResolvedTheme {
  if (theme === "dark") return "dark";
  if (theme === "light") return "light";
  return systemPrefersDark ? "dark" : "light";
}

function getInitialTheme(): ThemePreference {
  if (typeof window === "undefined") return DEFAULT_THEME;
  const stored = window.localStorage.getItem(STORAGE_KEY);
  return stored === "light" || stored === "dark" || stored === "system" ? stored : DEFAULT_THEME;
}

function getSystemPrefersDark(): boolean {
  if (typeof window === "undefined") return true;
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function applyResolvedTheme(theme: ResolvedTheme) {
  document.documentElement.dataset.theme = theme;
  document.documentElement.classList.toggle("dark", theme === "dark");
  document.documentElement.style.colorScheme = theme;
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<ThemePreference>(getInitialTheme);
  const [systemPrefersDark, setSystemPrefersDark] = useState(getSystemPrefersDark);
  const resolvedTheme = resolveThemePreference(theme, systemPrefersDark);

  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const handleChange = () => setSystemPrefersDark(media.matches);
    handleChange();
    media.addEventListener("change", handleChange);
    return () => media.removeEventListener("change", handleChange);
  }, []);

  useEffect(() => {
    window.localStorage.setItem(STORAGE_KEY, theme);
  }, [theme]);

  useEffect(() => {
    applyResolvedTheme(resolvedTheme);
  }, [resolvedTheme]);

  const value = useMemo(
    () => ({
      theme,
      resolvedTheme,
      setTheme: setThemeState,
    }),
    [theme, resolvedTheme],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const value = useContext(ThemeContext);
  if (!value) throw new Error("useTheme must be used inside ThemeProvider");
  return value;
}
```

- [ ] **Step 4: Wrap the app with ThemeProvider**

Modify `frontend/src/app/layout.tsx` so `body` renders:

```tsx
<body>
  <ThemeProvider>{children}</ThemeProvider>
</body>
```

Add the import:

```tsx
import { ThemeProvider } from "@/providers/ThemeProvider";
```

Keep `html lang="en"` for now; Task 3 will update it for locale.

- [ ] **Step 5: Add root theme boot script**

In `frontend/src/app/layout.tsx`, add a small inline script before children to avoid a flash of the wrong theme:

```tsx
<script
  dangerouslySetInnerHTML={{
    __html: `(() => {
      try {
        const stored = localStorage.getItem("agent-collab.theme") || "system";
        const systemDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
        const theme = stored === "dark" || (stored === "system" && systemDark) ? "dark" : "light";
        document.documentElement.dataset.theme = theme;
        document.documentElement.classList.toggle("dark", theme === "dark");
        document.documentElement.style.colorScheme = theme;
      } catch {}
    })();`,
  }}
/>
```

- [ ] **Step 6: Add light tokens**

In `frontend/src/app/globals.css`, keep current dark values under `:root, [data-theme="dark"]`. Add `[data-theme="light"]` overrides:

```css
[data-theme="light"] {
  --color-background: #f6f7f9;
  --color-foreground: #171a1f;
  --color-surface: #ffffff;
  --color-surface-raised: #fdfdfd;
  --color-surface-input: #eef1f5;
  --color-surface-hover: #e8edf3;
  --color-brand: #315f91;
  --color-brand-muted: #d8e7f5;
  --color-text-primary: #171a1f;
  --color-text-secondary: #4e5968;
  --color-text-muted: #788392;
  --color-border-subtle: #dde3eb;
  --color-border-muted: #ced7e2;
  --color-border-strong: #aeb9c7;
  --color-success: #18794e;
  --color-warning: #a15c00;
  --color-error: #c43c3c;
}
```

Also replace hardcoded utility backgrounds such as `.cc-sidebar { background: #121212; }` with `var(--color-surface)`.

- [ ] **Step 7: Run tests**

Run:

```bash
cd frontend
npm test
```

Expected: all tests pass, including `theme-i18n.test.ts`.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/providers/ThemeProvider.tsx frontend/src/app/layout.tsx frontend/src/app/globals.css frontend/tests/theme-i18n.test.ts
git commit -m "feat: add theme provider and light theme tokens"
```

## Task 3: Add I18n Provider and Dictionaries

**Files:**
- Create: `frontend/src/lib/i18n.ts`
- Create: `frontend/src/providers/I18nProvider.tsx`
- Modify: `frontend/src/app/layout.tsx`
- Test: `frontend/tests/theme-i18n.test.ts`

- [ ] **Step 1: Add i18n tests**

Append to `frontend/tests/theme-i18n.test.ts`:

```ts
import { DEFAULT_LOCALE, getDictionaryValue, isLocale } from "../src/lib/i18n";

test("locale validation accepts supported locales only", () => {
  assert.equal(isLocale("zh-CN"), true);
  assert.equal(isLocale("en-US"), true);
  assert.equal(isLocale("fr-FR"), false);
});

test("dictionary defaults to Chinese copy", () => {
  assert.equal(DEFAULT_LOCALE, "zh-CN");
  assert.equal(getDictionaryValue("zh-CN", "nav.home"), "首页");
  assert.equal(getDictionaryValue("en-US", "nav.home"), "Home");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd frontend
npm test
```

Expected: failure because `frontend/src/lib/i18n.ts` does not exist.

- [ ] **Step 3: Create dictionary module**

Create `frontend/src/lib/i18n.ts` with:

```ts
export const LOCALES = ["zh-CN", "en-US"] as const;
export type Locale = (typeof LOCALES)[number];
export const DEFAULT_LOCALE: Locale = "zh-CN";

export const dictionaries = {
  "zh-CN": {
    "nav.home": "首页",
    "nav.workspace": "工作区",
    "nav.coreActive": "核心在线",
    "nav.coreOffline": "核心离线",
    "settings.title": "偏好设置",
    "settings.theme": "主题",
    "settings.theme.light": "浅色",
    "settings.theme.dark": "深色",
    "settings.theme.system": "跟随系统",
    "settings.language": "语言",
    "settings.language.zh": "中文",
    "settings.language.en": "英文",
    "workspace.title": "工作区",
    "workspace.subtitle": "选择一个项目空间继续会话",
    "workspace.new": "新建工作区",
    "workspace.namePlaceholder": "工作区名称",
    "workspace.create": "创建",
    "workspace.cancel": "取消",
    "workspace.recent": "最近",
    "workspace.empty": "暂无工作区",
    "issue.boardTitle": "需求看板",
    "issue.boardSubtitle": "泳道视图",
    "issue.create": "创建需求",
    "issue.titlePlaceholder": "需求标题",
    "issue.descriptionPlaceholder": "详细描述...",
    "issue.confirm": "确认",
    "issue.cancel": "取消",
    "issue.ready": "就绪",
    "issue.tasks": "任务",
    "issue.live": "运行中",
    "issue.selectEmpty": "选择一个需求查看详情",
    "issue.noTasks": "暂无任务",
    "issue.startPhase": "启动阶段",
    "issue.tab.tasks": "任务",
    "issue.tab.artifacts": "产物",
    "issue.artifacts.requirements": "需求",
    "issue.artifacts.strategy": "策略与计划",
    "issue.artifacts.execution": "执行报告",
    "issue.artifacts.empty": "暂无产物记录",
    "run.empty": "选择一次运行查看执行详情",
    "run.console": "运行控制台",
    "run.continue": "继续",
    "run.rerun": "重新运行",
    "run.delete": "删除会话",
    "run.communications": "通信",
    "run.logs": "运行日志",
    "run.loadingMessages": "同步节点中",
    "run.loadingLogs": "访问日志流",
    "run.noMessages": "暂无通信记录",
    "run.noLogs": "日志流为空",
    "run.messagePlaceholder": "向智能体注入指令...",
    "run.send": "发送",
    "agents.title": "智能体协作",
    "agents.active": "活跃会话",
    "agents.recent": "最近活动",
    "agents.noHistory": "暂无历史",
    "agents.overview": "生态概览",
    "agents.help": "紧急介入",
    "agents.helpNeeded": "需要协助",
    "artifacts.empty": "暂无生成产物",
    "artifacts.title": "产物浏览器",
    "artifacts.business": "业务逻辑",
    "artifacts.product": "产品规格",
    "artifacts.diagnostics": "诊断报告",
    "artifacts.strategy": "执行策略",
    "artifacts.runtime": "运行输出",
    "artifacts.general": "通用资源",
    "phase.requirements": "需求",
    "phase.architecture": "架构",
    "phase.development": "开发",
    "phase.testing": "测试",
    "phase.runProductManager": "运行产品经理",
    "phase.runArchitect": "运行架构师",
    "phase.runEngineer": "运行工程师",
    "phase.runQa": "运行 QA",
  },
  "en-US": {
    "nav.home": "Home",
    "nav.workspace": "Workspace",
    "nav.coreActive": "Core Active",
    "nav.coreOffline": "Core Offline",
    "settings.title": "Preferences",
    "settings.theme": "Theme",
    "settings.theme.light": "Light",
    "settings.theme.dark": "Dark",
    "settings.theme.system": "System",
    "settings.language": "Language",
    "settings.language.zh": "Chinese",
    "settings.language.en": "English",
    "workspace.title": "Workspaces",
    "workspace.subtitle": "Select a project space to continue your session",
    "workspace.new": "New Workspace",
    "workspace.namePlaceholder": "Workspace Name",
    "workspace.create": "Create",
    "workspace.cancel": "Cancel",
    "workspace.recent": "Recent",
    "workspace.empty": "No workspaces found",
    "issue.boardTitle": "Issue Board",
    "issue.boardSubtitle": "Swimlane View",
    "issue.create": "Create Issue",
    "issue.titlePlaceholder": "Issue title",
    "issue.descriptionPlaceholder": "Detailed description...",
    "issue.confirm": "Confirm",
    "issue.cancel": "Cancel",
    "issue.ready": "Ready",
    "issue.tasks": "Tasks",
    "issue.live": "Live",
    "issue.selectEmpty": "Select an issue to view detail",
    "issue.noTasks": "No tasks detected",
    "issue.startPhase": "Start Phase",
    "issue.tab.tasks": "Tasks",
    "issue.tab.artifacts": "Artifacts",
    "issue.artifacts.requirements": "Requirements",
    "issue.artifacts.strategy": "Strategy & Plan",
    "issue.artifacts.execution": "Execution Report",
    "issue.artifacts.empty": "No artifacts recorded",
    "run.empty": "Select a run to view execution details",
    "run.console": "Run Console",
    "run.continue": "Continue",
    "run.rerun": "Re-run",
    "run.delete": "Delete Session",
    "run.communications": "Communications",
    "run.logs": "Runtime Logs",
    "run.loadingMessages": "Synchronizing Node",
    "run.loadingLogs": "Accessing Stream",
    "run.noMessages": "No communications recorded",
    "run.noLogs": "Stream empty",
    "run.messagePlaceholder": "Inject instruction to agent...",
    "run.send": "Send",
    "agents.title": "Agent Coordination",
    "agents.active": "Active Sessions",
    "agents.recent": "Recent Activity",
    "agents.noHistory": "No history",
    "agents.overview": "Ecosystem Overview",
    "agents.help": "Urgent Interventions",
    "agents.helpNeeded": "Help Needed",
    "artifacts.empty": "No artifacts generated yet",
    "artifacts.title": "Artifact Explorer",
    "artifacts.business": "Business Logic",
    "artifacts.product": "Product Specifications",
    "artifacts.diagnostics": "Diagnostic Reports",
    "artifacts.strategy": "Operational Strategy",
    "artifacts.runtime": "Runtime Outputs",
    "artifacts.general": "General Resources",
    "phase.requirements": "Requirements",
    "phase.architecture": "Architecture",
    "phase.development": "Development",
    "phase.testing": "Testing",
    "phase.runProductManager": "Run Product Manager",
    "phase.runArchitect": "Run Architect",
    "phase.runEngineer": "Run Engineer",
    "phase.runQa": "Run QA",
  },
} as const;

export type TranslationKey = keyof typeof dictionaries["zh-CN"];

export function isLocale(value: string | null | undefined): value is Locale {
  return value === "zh-CN" || value === "en-US";
}

export function getDictionaryValue(locale: Locale, key: TranslationKey): string {
  return dictionaries[locale][key] ?? dictionaries[DEFAULT_LOCALE][key] ?? key;
}
```

- [ ] **Step 4: Create I18nProvider**

Create `frontend/src/providers/I18nProvider.tsx`:

```tsx
"use client";

import React, { createContext, useContext, useEffect, useMemo, useState } from "react";
import { DEFAULT_LOCALE, type Locale, type TranslationKey, getDictionaryValue, isLocale } from "@/lib/i18n";

const STORAGE_KEY = "agent-collab.locale";

interface I18nContextValue {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: TranslationKey) => string;
}

const I18nContext = createContext<I18nContextValue | null>(null);

function getInitialLocale(): Locale {
  if (typeof window === "undefined") return DEFAULT_LOCALE;
  const stored = window.localStorage.getItem(STORAGE_KEY);
  return isLocale(stored) ? stored : DEFAULT_LOCALE;
}

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(getInitialLocale);

  useEffect(() => {
    window.localStorage.setItem(STORAGE_KEY, locale);
    document.documentElement.lang = locale;
  }, [locale]);

  const value = useMemo(
    () => ({
      locale,
      setLocale: setLocaleState,
      t: (key: TranslationKey) => getDictionaryValue(locale, key),
    }),
    [locale],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  const value = useContext(I18nContext);
  if (!value) throw new Error("useI18n must be used inside I18nProvider");
  return value;
}
```

- [ ] **Step 5: Wrap the app with I18nProvider**

Modify `frontend/src/app/layout.tsx`:

```tsx
import { I18nProvider } from "@/providers/I18nProvider";
```

Set the initial server-rendered html language to Chinese:

```tsx
<html lang="zh-CN" className={cn("font-sans", geist.variable)}>
```

Wrap children:

```tsx
<body>
  <script ... />
  <ThemeProvider>
    <I18nProvider>{children}</I18nProvider>
  </ThemeProvider>
</body>
```

- [ ] **Step 6: Run tests**

Run:

```bash
cd frontend
npm test
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lib/i18n.ts frontend/src/providers/I18nProvider.tsx frontend/src/app/layout.tsx frontend/tests/theme-i18n.test.ts
git commit -m "feat: add in-app i18n provider"
```

## Task 4: Add Topbar Preference Menu

**Files:**
- Modify: `frontend/src/features/workbench/WorkbenchPage.tsx`

- [ ] **Step 1: Import providers and icons**

In `WorkbenchPage.tsx`, add:

```tsx
import { useTheme, type ThemePreference } from "@/providers/ThemeProvider";
import { useI18n } from "@/providers/I18nProvider";
import type { Locale } from "@/lib/i18n";
import { Check, Languages, Moon, Sun, Monitor } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
```

Merge the lucide imports with the existing import block.

- [ ] **Step 2: Read preferences inside `WorkbenchInner`**

Near other hooks in `WorkbenchInner`, add:

```tsx
const { theme, resolvedTheme, setTheme } = useTheme();
const { locale, setLocale, t } = useI18n();
```

- [ ] **Step 3: Add small option renderers**

Inside `WorkbenchInner`, before `return`, add:

```tsx
const themeOptions: { value: ThemePreference; label: string; icon: React.ReactNode }[] = [
  { value: "light", label: t("settings.theme.light"), icon: <Sun size={14} /> },
  { value: "dark", label: t("settings.theme.dark"), icon: <Moon size={14} /> },
  { value: "system", label: t("settings.theme.system"), icon: <Monitor size={14} /> },
];

const localeOptions: { value: Locale; label: string }[] = [
  { value: "zh-CN", label: t("settings.language.zh") },
  { value: "en-US", label: t("settings.language.en") },
];
```

- [ ] **Step 4: Add preference dropdown in the right topbar**

Replace the standalone `Settings` icon with a dropdown trigger:

```tsx
<DropdownMenu>
  <DropdownMenuTrigger asChild>
    <button
      className="p-1.5 rounded-md hover:bg-surface-hover text-text-muted hover:text-foreground transition-colors"
      aria-label={t("settings.title")}
      title={t("settings.title")}
    >
      <Settings size={18} />
    </button>
  </DropdownMenuTrigger>
  <DropdownMenuContent align="end" className="w-56">
    <DropdownMenuLabel>{t("settings.theme")}</DropdownMenuLabel>
    {themeOptions.map((option) => (
      <DropdownMenuItem key={option.value} onClick={() => setTheme(option.value)}>
        {option.icon}
        <span>{option.label}</span>
        {theme === option.value && <Check size={14} className="ml-auto" />}
      </DropdownMenuItem>
    ))}
    <DropdownMenuSeparator />
    <DropdownMenuLabel>{t("settings.language")}</DropdownMenuLabel>
    {localeOptions.map((option) => (
      <DropdownMenuItem key={option.value} onClick={() => setLocale(option.value)}>
        <Languages size={14} />
        <span>{option.label}</span>
        {locale === option.value && <Check size={14} className="ml-auto" />}
      </DropdownMenuItem>
    ))}
  </DropdownMenuContent>
</DropdownMenu>
```

Keep the Bell icon as-is. Use `resolvedTheme` only if a visible indicator is desired; no visible indicator is required for acceptance.

- [ ] **Step 5: Replace topbar strings**

In `WorkbenchPage.tsx`, replace:

```tsx
Home -> {t("nav.home")}
Workspace fallback -> {currentWorkspace?.title || t("nav.workspace")}
Core Active -> {t("nav.coreActive")}
Core Offline -> {t("nav.coreOffline")}
Coordination -> {t("agents.title")}
Run Detail -> {t("run.console")}
Artifacts -> {t("issue.tab.artifacts")}
```

- [ ] **Step 6: Run build**

Run:

```bash
cd frontend
npm run build
```

Expected: build succeeds.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/workbench/WorkbenchPage.tsx
git commit -m "feat: add preference menu"
```

## Task 5: Internationalize Current Workbench Components

**Files:**
- Modify: `frontend/src/features/workspaces/WorkspaceGrid.tsx`
- Modify: `frontend/src/features/issues/IssueBoard.tsx`
- Modify: `frontend/src/features/issues/IssueCard.tsx`
- Modify: `frontend/src/features/issues/IssueDetailPanel.tsx`
- Modify: `frontend/src/features/agents/AgentCoordinationPanel.tsx`
- Modify: `frontend/src/features/runs/RunDetail.tsx`
- Modify: `frontend/src/features/artifacts/ArtifactPanel.tsx`
- Modify: `frontend/src/features/approvals/ApprovalDialog.tsx`
- Modify: `frontend/src/lib/task-selection.ts`
- Modify: `frontend/src/lib/i18n.ts`

- [ ] **Step 1: Convert phase config to translation keys**

Modify `frontend/src/lib/task-selection.ts` so `PHASE_CONFIG` stores translation keys instead of fixed labels:

```ts
labelKey: "phase.requirements";
buttonLabelKey: "phase.runProductManager";
```

Apply the same pattern for architecture, development, and testing. Keep `role` unchanged. If `description` is not rendered in the current workbench, remove it from the public config type.

- [ ] **Step 2: Replace workspace strings**

In `WorkspaceGrid.tsx`, import `useI18n`, add `const { t } = useI18n();`, and replace title, subtitle, button labels, placeholder, recent label, and empty state with dictionary keys from `workspace.*`.

- [ ] **Step 3: Replace issue board strings**

In `IssueBoard.tsx`, import `useI18n`, add `const { t } = useI18n();`, and replace board title/subtitle, create labels, placeholders, confirm/cancel, phase column labels, and empty ready text.

- [ ] **Step 4: Replace issue card strings**

In `IssueCard.tsx`, import `useI18n`, add `const { t } = useI18n();`, and replace `Tasks` and `Live`. Keep dynamic titles such as failed/waiting counts in English for the first pass unless adding dictionary keys for browser-only `title` attributes in the same step.

- [ ] **Step 5: Replace issue detail strings**

In `IssueDetailPanel.tsx`, import `useI18n`, add `const { t } = useI18n();`, and replace empty state, task count labels, phase labels, tab labels, empty task state, start/executing labels, artifact section titles, and empty artifact state.

- [ ] **Step 6: Replace agent coordination strings**

In `AgentCoordinationPanel.tsx`, import `useI18n`, add `const { t } = useI18n();`, and replace section headings and empty/help fallback labels.

- [ ] **Step 7: Replace run detail strings**

In `RunDetail.tsx`, import `useI18n`, add `const { t } = useI18n();`, and replace empty state, console title, buttons, tab labels, loading/empty states, input placeholder, and button title.

- [ ] **Step 8: Replace artifact panel strings**

In `ArtifactPanel.tsx`, import `useI18n`, add `const { t } = useI18n();`, and replace empty state, explorer title, and section names.

- [ ] **Step 9: Replace approval dialog strings**

In `ApprovalDialog.tsx`, inspect current copy and add dictionary keys for its title, approve/reject actions, feedback label, and loading/error fallback text. Use `useI18n` inside the component.

- [ ] **Step 10: Run hardcoded string scan**

Run:

```bash
cd frontend
rg -n ">([A-Z][A-Za-z ]{2,}|No |Select |Create |Cancel |Run |Continue|Re-run|Artifacts|Tasks|Home)<|placeholder=\"[A-Za-z]" src/features src/app
```

Expected: only dynamic backend/user data, CSS class names, accessibility labels already backed by `t`, or strings intentionally left untranslated such as product brand `JACKMOUSE.AI`.

- [ ] **Step 11: Run tests and build**

Run:

```bash
cd frontend
npm test
npm run build
```

Expected: both commands pass.

- [ ] **Step 12: Commit**

```bash
git add frontend/src/features frontend/src/lib/task-selection.ts frontend/src/lib/i18n.ts
git commit -m "feat: internationalize workbench UI"
```

## Task 6: Final Verification

**Files:**
- Modify only if verification finds a concrete issue in files touched by earlier tasks.

- [ ] **Step 1: Check git diff**

Run:

```bash
git status --short
git diff --stat
```

Expected: only planned frontend files are changed or deleted.

- [ ] **Step 2: Run full frontend verification**

Run:

```bash
cd frontend
npm test
npm run build
```

Expected: all tests pass and Next build completes.

- [ ] **Step 3: Run the app manually**

Run:

```bash
cd frontend
npm run dev
```

Expected: Next serves on `http://localhost:3000`. Open the workbench and verify:

- Default UI language is Chinese.
- Language menu switches to English without changing the URL.
- Theme menu supports light, dark, and system.
- Refreshing the page preserves selected language and theme.
- Current workbench pages remain readable in both light and dark themes.

- [ ] **Step 4: Commit any verification fixes**

If Step 3 required fixes:

```bash
git add frontend
git commit -m "fix: polish theme and i18n behavior"
```

If no fixes were needed, do not create an empty commit.

## Assumptions

- This implementation does not introduce `next-intl` or `next-themes`; the app is currently a single workbench route and only needs in-app preferences.
- This implementation does not translate user-created workspace names, issue titles, task content, logs, artifact body content, or backend-provided free text.
- This implementation deletes only unused legacy JSX components and test references tied to those components. Existing `.js` hooks/api/utils migration remnants remain unless they become unreachable and untested in a later cleanup.
