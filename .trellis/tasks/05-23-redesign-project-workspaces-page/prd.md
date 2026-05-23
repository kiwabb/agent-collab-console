# 重设 project 工作区页 — Conductor 外推

## Goal

把 `/projects/[id]`（实际渲染 `ProjectWorkspacesPage`）从"workspace 列表 + Conductor 对话 + KPI + Hero 全部垂直堆"重设为**workspace 管理为主，Conductor 外推**。让"新建 workspace"这种核心操作不需要滚屏才能找到。

## What I already know

- 当前页结构（`features/projects/ProjectWorkspacesPage.tsx:193-310`）：
  ```
  Hero (项目名 + 渐变 banner)         ~140px
  KPIs (4 张卡片)                     ~80px
  <ProjectConductorPage>              227 行的完整对话面板，挤在中间
  Toolbar (搜索框 + [+ 新建])          ← 用户要的按钮在这里
  Table (workspace 列表)
  Empty-state CTA ([+ 创建第一个])
  ```
- Hero 占第一屏顶部，加上 KPIs + Conductor 面板，新建按钮被推到折叠线以下，用户得滚一段才看见
- `ProjectConductorPage` 227 行：BrainCircuit 头部 + 状态显示 + 问答 Input + ThreadDock —— 是个完整对话台
- 仅被 `ProjectWorkspacesPage` 引用一处
- `/projects/[id]` 路由只有一个 page.tsx，**当前没有 tab 子路由**
- 跟前一任务（workspace console 重设）思路一致：调度/管理类页面应该剥离"详情 / 对话"那种重型嵌入

## User pain points (确认)

- 想新建 workspace 要滚到页面下方才能点到按钮（顶部按钮被中间巨型 Conductor 面板挤走）

## Main purpose (确认)

`/projects/[id]` = **workspace 管理中心**：看 workspace 列表 / 状态 / KPI，新建 / 编辑 / 删除 workspace。Conductor 对话是 project 级别的独立功能，跟 workspace 管理是同级两件事，不该塞在同一垂直流。

## Final Layout

```
/projects/[id]                           /projects/[id]/conductor
┌─────────────────────────────────┐      ┌─────────────────────────────────┐
│ Hero (project name + repo)      │      │ Hero (project name + repo)      │
│ [Workspaces] | Conductor        │      │  Workspaces | [Conductor]       │
├─────────────────────────────────┤      ├─────────────────────────────────┤
│ KPIs (4 卡片)                    │      │ <ProjectConductorPage>          │
│ Toolbar (搜索框 + [+ 新建])      │      │   占满主区                       │
│ Table (workspace 列表)           │      │                                 │
│ Empty-state CTA                 │      │                                 │
└─────────────────────────────────┘      └─────────────────────────────────┘
```

- `/projects/[id]` → 渲染 Hero + SecondaryNav + WorkspacesView（KPIs + Toolbar + Table）
- `/projects/[id]/conductor` → 渲染同样的 Hero + SecondaryNav + 完整 ProjectConductorPage
- 共享布局：抽出 `ProjectShell.tsx` 包 Hero + SecondaryNav，两个 page 复用
- SecondaryNav 用 next/link + usePathname 判断 active
- KPIs 只在 Workspaces 子页（它们是 workspace 指标，conductor 页不显示）

## Requirements (MVP — 已收敛)

- [x] 新建路由 `frontend/src/app/projects/[id]/conductor/page.tsx`
- [x] 新建 `frontend/src/features/projects/ProjectShell.tsx`：Hero + SecondaryNav 复用容器
- [x] `ProjectWorkspacesPage` 删除 `<ProjectConductorPage>` 嵌入；Hero 抽走到 ProjectShell；主区只剩 KPIs + Toolbar + Table
- [x] `/projects/[id]/conductor` 直接 mount 现有 `ProjectConductorPage`（**不重写它**）
- [x] SecondaryNav 用 next/link + usePathname 高亮 active
- [x] `+ 新建 workspace` 按钮在 viewport 第一屏内可见（不滚屏可点）
- [x] i18n key 新增 `project.nav.workspaces` / `project.nav.conductor`

## Out of Scope

- WorkspaceRow / 表格列本身布局不动
- **不重写 ProjectConductorPage 内部**，只换它的挂载位置
- KPI 卡片本身不动
- Hero 内部样式不动（除了把它抽到 ProjectShell）
- 不加 Memory / Settings / Activity 等其他 secondary nav 项（为将来扩展铺路即可）

## Acceptance Criteria (evolving — 待 brainstorm 后补全)

- [x] 打开 `/projects/[id]` 首屏可见 `+ 新建 workspace` 按钮（1280px / 默认浏览器高度下）
- [x] Conductor 功能可访问，无功能回退
- [x] frontend `npm run build && npm run lint && npm test` 全绿
- [x] 加 1 个 component test 覆盖"按钮在首屏内"或"Conductor 在新位置可触达"

## Definition of Done

- 旧的 `<ProjectConductorPage projectId={projectId} />` 在 ProjectWorkspacesPage 内的直接嵌入彻底删干净，不留 `// removed` 注释
- 测试 + lint + build 全绿
- i18n key 必要时新增，不重命名旧的

## Technical Notes

- 文件：`frontend/src/features/projects/ProjectWorkspacesPage.tsx`（删 Conductor 嵌入 + 改 Hero/Toolbar 位置）
- 文件：`frontend/src/features/projects/ProjectConductorPage.tsx`（搬运不重写）
- 路由：`frontend/src/app/projects/[id]/page.tsx`（如果走子路由方案，需要新建 `/projects/[id]/conductor/page.tsx`）
- i18n：`frontend/src/lib/i18n.ts`
- 参考前一任务的 commit `9e93136`（同样"管理页瘦身 + 详情/对话外推"模式）

## Decision (ADR-lite)

**Context**: `/projects/[id]` 把 workspace 管理 + Conductor 对话 + KPI 全部垂直堆在一页，227 行的 Conductor 面板把 `+ 新建 workspace` 按钮挤到折叠线以下。两个职责（workspace 管理 / project 级对话）混居同一垂直流。

**Decision**: Conductor 外推到独立子路由 `/projects/[id]/conductor`。两页共享 Hero + 二级 nav（Workspaces | Conductor），子页之间通过 next/link 切换。复用 `ProjectShell` 容器组件避免 hero 重复。

**Consequences**:
- ✅ workspace 管理 vs project 对话职责清晰分离
- ✅ URL 可分享、back/forward 行为正确
- ✅ 为将来加 Memory / Settings / Activity 二级 nav 项铺路
- ✅ 各自的 loading state 互不影响
- ⚠️ 多一个 route 文件，但只有 ~10 行（mount 现有 ProjectConductorPage）
- ⚠️ 用户失去"workspace 列表和 conductor 同屏"的能力 → 接受，这正是改造目的

## Implementation Plan

- **PR1（本任务一次性完成）**:
  - 新建 `ProjectShell.tsx`（Hero + SecondaryNav 复用）
  - 新建 `app/projects/[id]/conductor/page.tsx`（mount ProjectConductorPage）
  - `ProjectWorkspacesPage` 删 Conductor 嵌入 + Hero 抽走 + 改为接受 ProjectShell 包裹
  - i18n 新增 `project.nav.workspaces` / `project.nav.conductor`
  - 加 1 个 component test：SecondaryNav 在不同 pathname 下高亮 active
  - frontend build + lint + test 全绿
