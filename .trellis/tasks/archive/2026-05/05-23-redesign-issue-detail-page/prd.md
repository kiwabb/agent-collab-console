# redesign issue detail page

## Goal

把 Issue 详情页（`/issues/[id]`）从 6-tab 杂货铺重做成 "Conductor 现场指挥所"：
任何时候看一眼就知道 (1) Conductor 现在在干什么 / 卡在哪 (2) 上一轮决策为什么这么决 (3) 最近一次失败的根本原因是什么。

## Requirements

### A. 主结构（替换现有 6-tab IssueDetailPage）

页面纵向 4 段（移动端 / 窄屏先不考虑，桌面优先）：

```
┌─────────────────────────────────────────────────────┐
│ 1. Status Strip  (issue meta + Conductor phase + 卡死指示 + 动作)│
│ 2. Latest Failure Alert  (条件性，最近一次未被后续覆盖的失败) │
│ 3. Decision Timeline  (主区域，per-dispatch 行 + 行内 reasoning 折叠) │
│ 4. Secondary Panels  (3 个 accordion: Artifacts / Diff / Mesh) │
├─────────────────────────────────────────────────────┤
│ 5. Conductor Chat Bar  (sticky bottom, [CLARIFY] 等待时上方加横幅) │
└─────────────────────────────────────────────────────┘
```

### B. Status Strip（顶部 hero）

- 左：issue title + status badge（running / paused / done / failed / abandoned）+ created/updated 时间
- 中：当前 phase（来自 `conductor_state_log` 末条）+ 当前 phase 持续时间 + 偏长警告
  - phase 阈值（写死，可后期 settings 化）：`awaiting_llm`>30s 黄、>60s 红；`awaiting_subagent`>180s 黄、>360s 红；`streaming_llm`>120s 黄
  - 紧跟下一行：当前 active task 标识（如 `engineer#2 running`）
- 右：动作组 `[Ⅱ 暂停 / ▶ 恢复] [↻ 重启 Conductor] [📄 backend log] [⋯ 更多]`
  - "更多" 菜单包含 `Steer issue` / `Mark abandoned` 等低频操作

Done / Abandoned 状态变体：
- Done：phase 区变 `✓ 完成 用时 12m32s`；动作组变 `[Re-open] [Re-run QA] [删除产物]`
- Paused：顶部黄色加粗带 `⏸ PAUSED  Resume Phase: awaiting_subagent`
- Abandoned：整页灰调 + 顶部展示放弃原因摘要

### C. Latest Failure Alert（条件性）

只要满足下面任一条件就显示一条红/黄横幅：
- 最近一次 dispatch（任意 role）`status=failed` 且该 role 还**未在更晚的 dispatch 中成功**
- conductor_task 本身 `status=failed`（Conductor 自身崩了）

横幅内容：
- 红圆点 + `LATEST FAILURE  <role> @ <时间>`
- 1 行错误摘要（QA = 失败命令 + exit code；Engineer/PM/Architect = LLM 返回的 error message 或 result_json.error；Conductor self-crash = traceback 首行）
- 动作 `[跳到 timeline 该行]` `[看完整输出]`
- 后续同角色 dispatch 成功则横幅自动消失（不需手动 dismiss）

### D. Decision Timeline（主区域）

数据源：`conductor_turns` + `workflow_nodes` + `codex_tasks`。每行 = 一次 `dispatch_subagent` 或 `spawn_custom_subagent` 或 `request_user_clarification` 或 `retrieve_cold_memory` 或 `finalize_task` 工具调用。

行结构（示例）：
```
14:03 ⬛ qa            FAILED 18s
      ▼ Why: pytest collection error
         tests/test_health.py:12 ImportError ...
         [查看完整输出 ▸]
      ▸ Thinking (2 turns)                  
```

- 第一行：时间 + status 方块 + role + 状态 + 用时
- 失败行：`Why` 区**默认展开**，含错误摘要 + 可点开看完整 stderr / traceback / SubAgentResult
- 成功 / running 行：`Why` 区不显示
- 所有行最后追加 `Thinking ▸ (N turns)` 折叠，里面是 dispatch 之前那批 LLM reasoning text turns（来自 `conductor_turns` 表，按 `tool_use_id` 关联）
- Running 行：状态 spinner + 实时累加时长 + 偏长警告（同 Status Strip 阈值）
- 用户中途插话（来自 chat bar）：在 timeline 中以一行蓝色 `💬 14:05 You: <消息>` 单独插入
- Conductor 提问（`request_user_clarification`）：黄色高亮行 `⚠ 14:04 ASKED: <问题>` + 同行 `[在底部回答 ↓]` 锚点跳到 chat bar
- 用户回答 [CLARIFY]：同 You 插话样式，但前缀 `💬 14:05 You (answer):`

行点击 → 右侧 drawer 滑出（见 F）。

长列表折叠：当 dispatch 行数 > 20 时，默认只展示最近 10 行 + 顶部一条 `... 上方有 N 行历史 [全部展开]`。

### E. Secondary Panels（Timeline 下方 3 个 accordion，默认全折叠）

每个 accordion 标题行包含 `[图标] [名称] [计数/状态摘要]`，点开展示内容：

1. **📁 Artifacts** — 列出本 issue 所有 artifact 文件（PRD / architecture / engineer 报告 / QA 报告等），按 role 分组。点击文件名内联展示（markdown 渲染或 JSON pretty-print）
2. **🔀 Diff** — 列出 worktree 内未合并的代码变更（reuses 现有 `DiffMergeTab` 内部组件，但变成 accordion）
3. **🔗 Mesh** — Specialist 邀请 / parent-child 任务关系 + 最近 mesh 消息（reuses 现有 `AgentMeshGraph` + Collab feed）

不再有独立的 DAG / Tasks-Runs / Artifacts / Diff-Merge / Collab tab。**全部 6 个旧 tab 消失。**

### F. Dispatch Detail Drawer（右侧滑出）

Timeline 行点击触发。Drawer 宽度 480px，关闭按 Esc 或点击外部。

内容（按顺序）：
- Role + status + task id + 时间区间
- SubAgentResult 完整字段（title / summary / artifact_json）— 复用现有 `SubAgentResultCard`
- 原始 LLM 调用上下文：prompt 顶部 + 中间消息 + 最终响应（折叠）
- 该 task 的 chat/refine/rerun 三组动作（复用 `/api/codex/tasks/{id}/chat|refine|rerun`，UI 复用 `TasksRunsTab` 的 `AgentLiveTimeline` 部分组件，但拆出来）
- 直链跳转：`📄 raw log`、`📁 jump to artifact`

### G. Conductor Chat Bar（sticky bottom）

- 永远固定在视口底部，宽度跟主内容
- 默认 placeholder `💬 中途插话 / 给 Conductor 一个新指令...`
- 当 Conductor 调 `request_user_clarification` 等待时，bar 上方出现黄色提示横幅 `⚠ Conductor 等待回答: "<问题>"`；placeholder 切换为 `回答 Conductor 的问题...`
- 提交后通过 `POST /api/codex/issues/{id}/conductor/message` 注入（已有端点）
- 当 Conductor 暂停时，bar 禁用，placeholder 变 `Conductor 已暂停 — 点 Resume 后再说话`

### H. WebSocket 断流横幅

- 监听全局 EventBus WS 连接状态
- 断开 > 3s 时顶部蓝色横幅 `⚠ 实时连接丢失 重连中...`
- 重连成功 + 补齐 N 个事件 → 横幅变绿 `✓ 已补齐 N 个事件`，2s 后自动消失

## Acceptance Criteria

- [x] `IssueDetailPage.tsx` 从 1015 行拆分为多个子组件，主文件 < 200 行
- [x] 新增组件：`StatusStrip` / `LatestFailureAlert` / `DecisionTimeline` / `TimelineRow` / `SecondaryAccordion` / `DispatchDrawer` / `ConductorChatBar` / `WsConnectionBanner`
- [x] 6 个旧 tab 路由删除（如有），URL 不再支持 `?tab=` 切换
- [x] Status Strip 至少展示 phase + duration + 偏长警告 + 3 个核心动作
- [x] Latest Failure Alert 在 QA failed 且未被 engineer#2 成功覆盖时显示；engineer#2 成功后自动消失
- [x] Timeline 一行对应一次 dispatch，行内 reasoning 默认折叠；失败行 Why 区默认展开
- [x] Timeline > 20 行时早期折叠
- [x] Done / Paused / Abandoned 状态分别有视觉变体
- [x] WS 断流横幅在断 > 3s 时出现，重连补齐事件后绿色 toast
- [x] sticky chat bar 在 [CLARIFY] 等待时切换横幅
- [x] 行点击 → 右侧 drawer 滑出，含 SubAgentResult、chat/refine/rerun 动作和原始 Conductor turns
- [x] 旧 `DagTab` / `TasksRunsTab` / `ArtifactsTab` / `DiffMergeTab` / `CollabFeedTab` / `AgentTabContent` 不再作为 IssueDetailPage 主导航；Artifacts / Diff / Mesh 已内化进 secondary accordion
- [x] 旧 graph 数据的 issue（历史 issue）打开不能崩 — 时间线如果没数据降级显示 "暂无 Conductor 决策历史"
- [x] 前端 `npm run build && npm run lint && npm test` 全绿
- [x] 手动验证三个场景：running issue（看到 phase + active task）、QA failed running issue（看到 latest failure alert）、done issue（看到完成时长 + 动作变体）

## Definition of Done

- 前端 build / lint / test 全绿
- 不破坏现有 WebSocket 订阅契约（event types 不变）
- 拆出的子组件保持可单测，关键组件至少有一个 unit test
- 至少手动验证一遍 AC 末项三个场景
- 旧组件文件物理删除（不留 `// removed` 注释）
- 单 PR 完成，无半成品提交

## Out of Scope

- 移动端 / 窄屏适配（桌面优先，窄屏先不管布局崩坏）
- 多 issue 跨页对比 / 同项目 issue 群 view
- 角色级 KPI（PM 平均产出耗时等）— 这是另一个独立功能
- Conductor 估时（已有的 conductor_state_log 衍生功能，但首版不集成进 Status Strip）
- 自定义 phase 阈值用户设置 — 写死即可，后期再 settings 化
- 国际化字符串补全（先英文 + 中文 mix，i18n key 走现有 `useI18n`，缺哪个 key 补哪个）
- 历史 conductor_turns 的 backfill / 数据迁移（旧 issue 显示 "暂无" 即可）

## Technical Approach

### 组件拆分

```
frontend/src/features/issues/
  IssueDetailPage.tsx                    # ≈150 行，纯 layout
  components/
    StatusStrip.tsx
    LatestFailureAlert.tsx
    DecisionTimeline.tsx
    TimelineRow.tsx                      # per-dispatch 行
    TimelineThinkingTurns.tsx            # 折叠 reasoning
    SecondaryAccordion.tsx               # 共用 accordion 容器
    ArtifactsPanel.tsx                   # 替代 ArtifactsTab
    DiffPanel.tsx                        # 替代 DiffMergeTab
    MeshPanel.tsx                        # 替代 AgentMeshGraph + Collab
    DispatchDrawer.tsx                   # 右侧 drawer
    ConductorChatBar.tsx                 # 替代 ConductorChatBar (重写)
    WsConnectionBanner.tsx
  hooks/
    useConductorPhase.ts                 # 订阅 conductor_state events
    useDecisionTimeline.ts               # 汇总 turns + nodes + tasks
    useLatestFailure.ts                  # 计算 unaddressed failure
    useWsConnectionStatus.ts
```

### 数据流

- 现有 WS 事件保持不变；新增订阅 `conductor_status` + `conductor_state_violation`
- `useConductorPhase` hook：拉 `/api/codex/issues/{id}/conductor-state` 初始 + 订阅事件增量
- `useDecisionTimeline` hook：拉 `/api/codex/issues/{id}/conductor/turns`（**需要研究 / 可能要新增此端点**）+ 订阅 `conductor_turn_*` 事件
- `useLatestFailure` hook：派生自 timeline 数据 + tasks

### 待研究项（implement 之前要确认）

1. `/api/codex/issues/{id}/conductor/turns` 端点是否存在 / 是否返回完整 turn 列表（CLAUDE.md 提到 `conductor_turns` 表但未列端点）
2. `/api/codex/issues/{id}/conductor/state-log` 端点是否存在
3. `conductor_state` WS 事件 envelope 字段（`phase` / `detail` / `resume_phase`）的精确名字
4. 旧 issue 没有 `conductor_turns` 数据时怎么降级（确认前端 hook 容错路径）

如端点不存在，task 实施 PR 内一并补；如果工作量大，task 拆子任务。

### 删除清单

```
frontend/src/features/issues/tabs/DagTab.tsx
frontend/src/features/issues/tabs/TasksRunsTab.tsx
frontend/src/features/issues/tabs/ArtifactsTab.tsx
frontend/src/features/issues/tabs/DiffMergeTab.tsx
frontend/src/features/issues/tabs/CollabFeedTab.tsx
frontend/src/features/issues/components/AgentTabContent.tsx  (并入 Decision Timeline + Drawer)
frontend/src/features/issues/components/ConductorLogPanel.tsx (功能并入 Timeline)
frontend/src/features/issues/components/IssuePipelineTrace.tsx (功能并入 Status Strip)
```

复用组件（拆出去 / 改 prop）：
- `SubAgentResultCard.tsx` — 在 Drawer 内复用
- `WorkflowGraphView.tsx` — 删除（timeline 取代）
- `AgentMeshGraph.tsx` — 内化进 MeshPanel
- `AgentLiveTimeline.tsx` — 拆出 raw-log 部分到 Drawer 复用

## Decision (ADR-lite)

**Context**：原 IssueDetailPage 1015 行 / 6 tab，信息分散、卡死无指示、失败原因藏在子 tab 日志尾巴里。用户痛点全集中在 "running issue 的可见性"。

**Decision**：以 "Conductor 现场指挥所" 为主线重做，单页纵向 4 段 + sticky chat bar 替换 6 tab；timeline 作为主区域，所有 dispatch / 决策 / 用户互动按时间合流；状态、失败、卡死三类信息浮到顶部和行内；其他视图（Artifacts / Diff / Mesh）退化到次级折叠面板。

**Consequences**：
- + 信息密度集中在首屏 / 单滚动；不再有 tab 跳转开销
- + Conductor 实时状态（phase + duration + 偏长）首次在前端可见
- + 失败原因强制曝光 → 用户能立刻判断 "code 真有 bug 还是 LLM 抽风"
- − 一次性删除 6 个 tab 是 breaking UI change；旧用户习惯需要重新建立
- − 历史 issue 数据兼容靠降级提示而非完整回填
- − 单 PR 实施代码量大（估 ~3000 LOC 增删），review 压力高，但符合用户 "全做完一个 PR" 偏好

## Implementation Plan

单 PR / 单分支，内部按以下顺序提交（每段一个 commit，方便回滚分段）：

1. **scaffolding + hooks**：新建 `components/`、`hooks/` 骨架文件 + `useConductorPhase` / `useDecisionTimeline` / `useLatestFailure` / `useWsConnectionStatus` hook + 必要 API client 函数（若端点缺失补后端）
2. **StatusStrip + LatestFailureAlert**：顶部两段先做，能独立挂在原 IssueDetailPage 之上
3. **DecisionTimeline + TimelineRow + ThinkingTurns**：主区域，行内展开/折叠交互
4. **DispatchDrawer**：行点击触发，含 SubAgentResult + chat/refine/rerun
5. **SecondaryAccordion + ArtifactsPanel + DiffPanel + MeshPanel**：内化原 tab 内容
6. **ConductorChatBar + [CLARIFY] 横幅 + WsConnectionBanner**
7. **删除旧 tab 文件 + 重写 IssueDetailPage.tsx 主框架（< 200 行）**
8. **AC 末项三场景手动验证 + 修边 case**

## Technical Notes

- Survey 详见 `What I already know` 段（上一版 PRD 内容已收）
- 用户 feedback：`feedback_prefer_architecture_over_speed.md`（不在乎改多久，要规范）+ `feedback_complete_everything.md`（要做完）
- 后端 `conductor_state_log` 已经记录所有 phase 变化（CLAUDE.md）
- 后端 `conductor_turns` 已经记录每轮 LLM response + tool_use / tool_result
- 旧 fixed pipeline 已彻底清理（commit `a83c813`）— UI 重做不再有 backend coupling 风险
