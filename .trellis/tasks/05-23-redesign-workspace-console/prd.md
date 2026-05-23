# brainstorm: 工作区页重设为调度中枢

## Goal

把 `/workspaces/[wsId]` 从"信息密度过载的三栏巨石页"重设为**Issue 调度中枢**：一眼看全部 issue 状态 + 进度、快速创建、快速跳转到 `/issues/[id]` 看详情。详情和产物的事**不在这里干**。

## What I already know

- 入口：`frontend/src/app/workspaces/[wsId]/page.tsx` → `<WorkbenchShell><WorkspaceConsole /></WorkbenchShell>`
- `WorkspaceConsole.tsx` 单文件 782 行，目前结构：
  - **左**：`WorkspaceSidebar`（WorkbenchShell 提供）
  - **中**：`IssueListColumn`（issue 表格 5 列 + Header[workspace/phase/title/Filter/Sort/New] + 底部命令输入框）
  - **右**：`RunDetailColumn`（440px 固定，tab 切换 logs / 等，监听 lastEvent 同步 issueTasks / executionProcess）
- `IssueListColumn` 接 16 个 props（structural code smell）
- 命令输入框双模：`mode="create"` 创新 issue / `mode="chat"` 给选中 issue 发消息
- 右侧详情和 `/issues/[id]` 详情高度重叠（同样的 ExecutionProcess、同样的 ConductorLogPanel 能力）

## User pain points (确认)

- 信息密度太高 / 一屏塞太多
- 视觉层级不清 / 主次不分
- 右侧 RunDetailColumn 太肥 / tab 太多 / 跟 `/issues/[id]` 重复
- Issue 列表行展示进度 / 状态 不够直观

## Main purpose (确认)

**Issue 调度中枢** —— 快速看状态、快速创建、快速跳转。详情进 `/issues/[id]`。

## Requirements (evolving)

### MVP
- [ ] 删除右侧 `RunDetailColumn`（440px 固定列）
- [ ] 强化 issue 列表行的状态/进度可视化：phase 进度条 / 当前 role avatar / awaiting-review badge
- [ ] Header 信息瘦身：workspace 名 + 简短计数（如 `3 running · 1 awaiting · 12 total`），不再塞"第一个 issue 的标题"
- [ ] 选中 issue 时不再展开右侧，而是 inline 在该行下显示极简快照（当前 phase / 当前 role / 一键跳 `/issues/[id]`）或直接跳转
- [ ] 命令输入框 → 简化为悬浮"+ 新建 issue"按钮 + 模态/抽屉创建表单（chat 模式从本页移除，chat 只在 `/issues/[id]` 里有）
- [ ] `IssueListColumn` 16 props → 拆出小组件 + 用 context / hook 收敛状态

### 非 MVP（Out of Scope，但要保留扩展点）
- 列表的 sort/filter UI 现在按钮是 placeholder，本轮可以接上 status / phase 筛选，但**不**做高级查询语法
- 看板/卡片视图（WorkspaceBoard / WorkspaceGrid 已存在但不在路由里），本轮**不**接

## Acceptance Criteria (evolving)

- [ ] `/workspaces/[wsId]` 打开默认只见左 sidebar + 主区 issue 列表，无右侧 440px 详情列
- [ ] 列表行能一眼区分：running / awaiting_review / completed / failed / queued
- [ ] 列表行直观显示当前 role（PM/Engineer/QA…）+ phase 进度（如 1/4、2/4）
- [ ] 点击 issue 跳 `/issues/[id]`（不再 inline 展开 RunDetailColumn）
- [ ] 新建 issue 走 `NewIssueDialog`（保留现有组件，不重写）
- [ ] `WorkspaceConsole.tsx` 拆分后单文件 < 300 行，主组件 props ≤ 5 个
- [ ] frontend `npm run build && npm run lint` 绿
- [ ] frontend `npm test` 绿

## Definition of Done

- 测试更新：至少加 1 个 component test 覆盖"列表行状态徽章 + 跳转"
- 文档：本 PRD + implement.jsonl 走完
- 旧代码彻底清理（RunDetailColumn、底部 chat 输入框、相关 props/state 全部删，不留 `// removed` 注释）

## Out of Scope (explicit)

- `/issues/[id]` 内部布局不动（那是另一回事）
- WorkbenchShell + WorkspaceSidebar 的左侧栏改动
- i18n key 重命名（必要时新增，不重命名旧的）
- WorkspaceBoard / WorkspaceGrid 看板视图接入

## Technical Notes

- 文件：`frontend/src/features/workspaces/WorkspaceConsole.tsx`（重写 → 拆成 `WorkspaceConsole.tsx` shell + `IssueListPanel.tsx` + `IssueRow.tsx`）
- 数据源：`getCodexIssues` / `getCodexTasks` / `useExecutionProcessesContext.lastEvent`（用现有 WebSocket envelope，不新增 hook）
- 进度推断：`issue.current_phase`（已有字段） + 后端 `conductor_state_log` API（已有 `/codex/issues/{id}/conductor-state-log`，可选项，本轮可以只用 current_phase）
- `NewIssueDialog` 现成可用，本轮 reuse
- 现有的 IssueRow 内部已有 selected / onOpen / onDelete，可基础上扩展

## Final Approach

```
┌─ WorkbenchShell ─────────────────────────────────────────────────┐
│ Sidebar (existing) │  WorkspaceConsole (new)                      │
│                    │ ┌──────────────────────────────────────────┐ │
│                    │ │ workspace · acme-api                     │ │
│                    │ │ 3 running · 1 awaiting · 12 total        │ │
│                    │ │                       [+ 新建 issue]      │ │
│                    │ ├──────────────────────────────────────────┤ │
│                    │ │ ● running #a4f2  feat: add /api/health   │ │
│                    │ │   ▓▓▓▓░░  PM→ARC→[ENG]→QA  engineer  →  │ │
│                    │ │ ⏸ awaiting #b8e1  fix: token leak        │ │
│                    │ │ ✓ done #c0d3  chore: bump deps           │ │
│                    │ │ ✗ failed #d2e5  feat: dark mode toggle   │ │
│                    │ │ ...                                       │ │
│                    │ └──────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

- 单栏主区，无右侧 RunDetailColumn
- Header：workspace 名 + 状态计数 + 右上 `[+ 新建 issue]` 按钮
- 每行：status icon + #id + title + age + phase 进度条 + 当前 role chip + 右箭头
- 点行 = `router.push("/issues/{id}")`，不留 selected state
- 命令输入框（chat / create dual-mode）整块删除；新建走 `NewIssueDialog`，chat 只在 `/issues/[id]` 里有
- 排序/过滤按钮本轮接最小可用（status + phase），不上高级查询

## File 拆分

- `WorkspaceConsole.tsx`（~120 行）— shell：拉数据、把 issues + 计数喂给下面两个子组件
- `WorkspaceConsoleHeader.tsx`（~80 行）— workspace 名 + 计数胶囊 + `+ 新建 issue` 按钮 + filter/sort
- `IssueListPanel.tsx`（~80 行）— 表头 + map IssueRow + empty/loading 状态
- `IssueRow.tsx`（~100 行）— 单行渲染（status icon、phase 进度条、role chip、点击跳转）
- 移除：`RunDetailColumn` / `IssueListColumn` 中的 chat composer / 双模 command state

## Decision (ADR-lite)

**Context**: WorkspaceConsole 当前是 782 行三栏巨石，右侧详情跟 `/issues/[id]` 重复，底部 chat composer 让本页同时承担"调度 + 对话"两种相互冲突的语义，造成视觉密度过高、主次不分。

**Decision**: 把本页定位收窄到**纯调度中枢**：只做"看 + 建 + 跳"。详情 / chat / 产物 / approvals 全部走 `/issues/[id]`。物理上拆 4 个 < 300 行的文件，按职责收敛 props。

**Consequences**:
- ✅ 主区简洁，状态可视化强（行级 phase 进度条 + role chip）
- ✅ 跟 `/issues/[id]` 职责清晰分离，消除重复
- ✅ 代码结构干净（小文件、少 props、易测试）
- ⚠️  用户失去"在 workspace 页 inline 看日志/产物"能力 → 接受，因为这是用户主动选择跳 `/issues/[id]` 的设计
- ⚠️  chat 模式只在 issue 页 → 跨 issue 群发的能力消失（本来也没正式做过）

## Implementation Plan (small PRs)

- **PR1 (本任务一次性完成)**:
  - 删 `RunDetailColumn` + 底部 chat composer + 相关 state/props/i18n
  - 新建 `WorkspaceConsoleHeader.tsx` / `IssueListPanel.tsx` / `IssueRow.tsx`（拆分现有逻辑）
  - 行级 phase 进度条 + role chip + 状态 icon
  - 行点击 = router.push 跳 `/issues/[id]`
  - 加 1 个 component test 覆盖"行渲染 + 跳转"
  - frontend build + lint + test 全绿

