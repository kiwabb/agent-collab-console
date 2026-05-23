# restore live streaming in issue detail

## Goal

新版 Issue 详情页（commit `774963c`）改完之后丢了 "agent 逐字 streaming" 的实时感 — `DispatchDrawer` 只渲染 `SubAgentResult` 终态卡片，`TasksRunsTab` 被孤立、`LiveThinkingDock` 写了但没人 mount。这次修复：**走 Path 1 — 把 `AgentLiveTimeline` 内嵌进 `DispatchDrawer`**，让用户点击 timeline 任意一行就能看到该 task 的 live token stream / thinking 折叠块 / ToolBlock 全套。

## What I already know

### 现状
- `frontend/src/features/issues/IssueDetailPage.tsx`（185 行）：没有任何 `AgentLiveTimeline` / `useExecutionProcessMessageStream` / `LiveThinkingDock` 引用
- `frontend/src/features/issues/components/AgentDecisionDrawer.tsx`（226 行）：仅展示 `SubAgentResultCard` 等静态内容
- `frontend/src/features/issues/components/DispatchDrawer.tsx`：drawer 入口（待具体读）
- `frontend/src/features/issues/components/LiveThinkingDock.tsx`（245 行）：**死代码**，定义了但没 import
- `frontend/src/features/runs/AgentLiveTimeline.tsx`：完整 streaming UI 仍在（thinking 折叠块 + 流式气泡带光标 + ToolBlock + framer-motion 进场动画）
- `frontend/src/features/runs/RunDetail.tsx:546`：示范用法（`AgentLiveTimeline` 配 `useExecutionProcessMessageStream(process?.id)`）
- `frontend/src/features/issues/tabs/TasksRunsTab.tsx:25, 345`：另一个示范用法，但页面已不再挂这个 tab
- `frontend/src/hooks/useExecutionProcessMessageStream.ts`：WS 流 hook（含重连）

### 用户路径（修完后期望）
1. 进 `/issues/[id]` → 看到 Decision Timeline
2. 点 timeline 任意一行（不论 running / done / failed）→ DispatchDrawer 滑出
3. Drawer 内除 SubAgentResult 终态外，**多一段 Live Stream 区**，正在 running 的 task 看到逐字打字 + thinking 块；已结束的 task 看到完整最后一帧 + 状态标
4. 关 drawer → WS 断开，不泄漏

## Requirements

### A. DispatchDrawer 内部结构重排

drawer 自上而下三段：

1. **Header**（保留现状）— role + status + task id + 时间区间 + 跳转链
2. **Live Stream**（新增 — 本任务核心；research 已确认实现细节）
   - 组件：`AgentLiveTimeline`（复用 `frontend/src/features/runs/AgentLiveTimeline.tsx`，**不复制**）
   - 数据：**AgentLiveTimeline 内部已经自带 `useExecutionProcessLogStream`（token-level `assistant_delta` + heartbeat + 自动重连）**。Drawer 只传 `executionProcessId={item.task?.last_execution_process_id ?? null}`，**不需要再调任何 stream hook**
   - 容器：高度约 drawer 视口 60%，**独立滚动容器**；外层 drawer 主滚动需拆成两层避免嵌套滚动冲突
   - 状态头条由 AgentLiveTimeline 本身的 WorkingIndicator 提供（running / done / failed / disconnected 几种 badge 已经有），不需要 drawer 包一层
   - 仅传 `onStop`（暂停 task）；**不传 `onRerun`** —— rerun 走下方 Summary&Actions 段的统一按钮，避免双按钮歧义
   - `emptyHint` prop：task pending（last_execution_process_id 为 null）→ "Waiting for task to start..."
3. **Summary & Actions**（沿用现有 SubAgentResultCard + chat/refine/rerun 区，**task running 时折叠为单条"完成后展示终态摘要"提示**）

### B. execution_process_id 解析 (research 已确认)

直接读 `item.task?.last_execution_process_id ?? null`，字段已存在于 `CodexTask` 类型 + 后端 SQL 返回 + `DecisionTimelineItem.task` 上。**零额外请求、零 helper、零新 API**。

- task pending（未跑过）→ 该字段为 null → AgentLiveTimeline 内部自然走空态分支

### C. Drawer 宽度调整 (research 已确认)

- 当前 `w-[480px]` 固定（DispatchDrawer.tsx 的 Tailwind class）
- 改为 `w-[560px]`（桌面优先；窄屏先不处理）
- 验证：长 thinking 块和 ToolBlock 不被压扁

### D. WS 生命周期 (research 已确认)

- AgentLiveTimeline 内部 `useExecutionProcessLogStream` 已通过 useEffect cleanup 断开 WS
- Drawer 关闭 → unmount AgentLiveTimeline → hook cleanup 触发 → WS 关
- 切换 timeline 另一行 → executionProcessId prop 变 → hook 内部 useEffect 重订阅
- 验证：浏览器 DevTools Network 面板 WS 行为符合预期
- 单 drawer 实例（同时只能开一个），不并发多 WS

### D.5 顺手补 Esc 关闭 (research 建议)

- 当前 DispatchDrawer **没有 Esc 关闭支持**
- 本次顺带加上 `useEffect` 监听 `keydown Escape` → 调 onClose
- 也加点击外部蒙层关闭（如尚未实现）

### E. 清理

- 删除 `frontend/src/features/issues/components/LiveThinkingDock.tsx`（死代码，零引用）
- **保留** `frontend/src/features/issues/tabs/TasksRunsTab.tsx` 以及它依赖的 `AgentLiveTimeline` —— 这条调用链虽然 IssueDetailPage 不再用，但 `RunDetail.tsx` 仍在用 `AgentLiveTimeline`；TasksRunsTab 本身是否别处还引用待 research 阶段确认（grep `TasksRunsTab` 整仓库）

## Acceptance Criteria

- [ ] `DispatchDrawer` 引入 `AgentLiveTimeline` + `useExecutionProcessMessageStream`
- [ ] Running issue → 点 timeline 上正在运行的行 → drawer 内 Live Stream 区出现，每秒能看到新内容追加
- [ ] Done issue → 点已完成行 → drawer 内 Live Stream 区显示该 task 完整最后一帧 + `✓ Done` 标头
- [ ] Failed issue → 点失败行 → drawer 内 Live Stream 区显示完整最后一帧 + `✗ Failed` 标头（红）
- [ ] Pending task（没起 execution_process）→ drawer 内显示空态 "Waiting for task to start..."
- [ ] 关 drawer → 浏览器 DevTools Network 看到 WS 关闭
- [ ] 切换 timeline 另一行 → 上一个 WS 关闭 + 新 WS 开启
- [ ] `LiveThinkingDock.tsx` 文件物理删除
- [ ] `frontend/src/features/issues/IssueDetailPage.tsx` 没有任何残留 LiveThinkingDock 引用
- [ ] `npm run build && npm run lint && npm test` 全绿
- [ ] 手动 3 场景（running / done / failed）+ pending 边界回归

## Definition of Done

- 前端 build / lint / test 全绿
- 不破坏现有 WS 协议（沿用 `useExecutionProcessMessageStream` 不改 hook 本身）
- 不复制 `AgentLiveTimeline` 代码，纯引用
- 删除 LiveThinkingDock 死代码
- 单 PR，无半成品
- 至少跑通 4 个场景手测

## Out of Scope

- Path 2：在 DecisionTimeline 行内直接展开 streaming（更大改动，下一轮再考虑）
- Path 3：完全 cc-gui 化的统一 message stream（重写级别）
- 恢复 TasksRunsTab 在导航里的入口（用户主线已确认走 drawer，不需要这个 tab）
- 重构 `useExecutionProcessMessageStream` hook 本身
- 添加 streamingThrottleMs 节流（cc-gui 有；先不引入新行为）
- 移动端 / 窄屏适配
- 历史 task（execution_process 已落地很久）的回放体验优化 — 当前显示最后一帧足矣

## Technical Approach

### 数据流

```
DispatchDrawer (drawerItem: DecisionTimelineItem | null)
  ↓ 从 drawerItem.task_id 找对应 task
  ↓ 从 task 找最近 execution_process_id（latestExecutionProcessIdForTask helper）
  ↓
  useExecutionProcessMessageStream(executionProcessId)
  ↓ 返回 { messages, pendingAssistant, phase, connected }
  ↓
  AgentLiveTimeline (复用 RunDetail.tsx:546 同一组 props)
```

### 待研究项（research 阶段必做）

1. `AgentLiveTimeline` 当前确切的 props 接口（`RunDetail.tsx:546` 上下文）
2. `useExecutionProcessMessageStream` 返回字段（看 `messages` / `pendingAssistant` / 其他）
3. `CodexTask` 类型有没有 `execution_processes` 字段（或类似），客户端能否直接取到 latest process id；若不能，是否要新增 API endpoint
4. `getCodexTasks` 已返回 task 详情时的字段完整度
5. grep 全仓 `TasksRunsTab` 残留引用（路由 / 其他组件 import）
6. `DispatchDrawer` 当前的宽度是怎么设置的（fixed / className），确认改 560px 是 1 行改动

### 文件修改清单（推断，research 后定稿）

**修改**：
- `frontend/src/features/issues/components/DispatchDrawer.tsx`（主战场）

**新增**：
- 无（research 确认不需要 helper，直接读 `task.last_execution_process_id`）

**删除**：
- `frontend/src/features/issues/components/LiveThinkingDock.tsx`

**不动**：
- `frontend/src/features/runs/AgentLiveTimeline.tsx`
- `frontend/src/hooks/useExecutionProcessMessageStream.ts`
- `frontend/src/features/runs/RunDetail.tsx`（作为参考用法）

## Decision (ADR-lite)

**Context**：新版 Issue 详情页（Decision Timeline + DispatchDrawer 主线）改完之后丢失了之前 `TasksRunsTab.AgentLiveTimeline` 提供的逐字打字实时流，用户感觉"看不动了"。`LiveThinkingDock` 像是一次半途而废的修复尝试，写了但没接上。

**Decision**：Path 1。把 `AgentLiveTimeline` 内嵌进 `DispatchDrawer` 的中段，配 `useExecutionProcessMessageStream`，按 task 状态分支（running / done / failed / pending）显示对应内容。删除 LiveThinkingDock 死代码。不触碰 timeline 行级渲染（避免一次性把面铺太大）。

**Consequences**：
- + 实时流回来了，用户点 timeline 行就能看活的
- + 复用现有组件，零代码重复
- + 改动局限在 `DispatchDrawer.tsx` + 一个小 helper + 删一个文件 — 单 PR 可控
- − 用户还是要点开 drawer 才能看 stream，不像 cc-gui 在主流主区永远可见。若后续不爽再走 Path 2/3
- − Drawer 宽度从默认 480px 扩到 560px，主区可视面积稍减

## Implementation Plan

单 PR，内部按顺序提交：

1. **research**：派 `trellis-research` 摸 `AgentLiveTimeline` props + `useExecutionProcessMessageStream` 返回 + task 拿 execution_process_id 路径 + `TasksRunsTab` 残留引用 + `DispatchDrawer` 宽度设置
2. **scaffolding**：`executionProcess.ts` helper（若 research 显示需要）
3. **DispatchDrawer 重构**：嵌 AgentLiveTimeline + 状态分支 + 宽度调整
4. **删 LiveThinkingDock.tsx**
5. **验证**：build / lint / test + 手动跑 4 场景

## Technical Notes

- 用户 feedback：`feedback_prefer_architecture_over_speed.md`（要规范）+ `feedback_complete_everything.md`（要做完）
- 参考实现：`references/cc-gui/src/features/messages/components/MessagesRows.tsx`（streaming 主流主区）和 `useStreamActivityPhase`（idle/waiting/ingress 状态机）— 本任务 Out of Scope，但下一轮可借
- Anti-pattern 警告：**不要**复制 `AgentLiveTimeline` 代码到 components 目录，要纯 import
- WS 生命周期由 `useExecutionProcessMessageStream` 自带的 useEffect cleanup 兜底，不要在 drawer 里手动管 WebSocket
