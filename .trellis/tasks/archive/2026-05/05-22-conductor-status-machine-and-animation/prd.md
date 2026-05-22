# conductor: 完整状态机 + 前端动画/进度

## Goal

把上一任务（archive 中的 05-22-conductor-streaming-and-live-status，commit `fe12046`+`7dbf71c`）defer 出的"完整状态机 + 前端动画 + 进度"做实：从"single-cell 当前 phase + 时长 + stuck 提示"升级为有 transition 约束、有切换历史时间线、有动画、有预估剩余时间的完整可视化。

## Requirements

1. **后端定义状态机 transition 矩阵**：在 `conductor_main_loop.py` 定义 `LEGAL_TRANSITIONS: dict[str, set[str]]` 覆盖 8 个 phase（`awaiting_llm` → `streaming_llm` / `dispatching_subagent` / `awaiting_user_clarification` / `paused` / `done` / `failed` 等）。`set_phase()` 在做 transition 前校验 (from, to) 是否合法。
2. **违规处理 = 警告放行 + log + SSE 事件**：非法 transition 仍执行（避免阻塞 loop），但 `logger.warning(...)` + emit `conductor_state_violation` SSE 让前端 toast 提示。
3. **新表 `conductor_state_log`**：schema `(id TEXT PK, issue_id TEXT, from_phase TEXT NULL, to_phase TEXT, from_detail TEXT NULL, to_detail TEXT NULL, transition_at TEXT, duration_ms INTEGER NULL, is_legal INTEGER DEFAULT 1)`；index on (issue_id, transition_at)。两份 migration（sync `sqlite_store.py` + async `async_sqlite_store.py`）。每次 `set_phase()` 成功后 INSERT 一行（duration_ms = transition_at - 上一行 transition_at）。
4. **后端 API `GET /api/codex/issues/{id}/conductor-state-log?limit=200`**：返回 `[{from_phase, to_phase, transition_at, duration_ms, is_legal}]`，按 transition_at desc。
5. **后端 phase 历史时长建模**：新模块 `phase_duration_estimator.py` 读所有历史 issue 的 `conductor_state_log`，按 to_phase 计算 P50 + P95 + N（样本数）。封装 `estimate(phase) -> {p50_ms, p95_ms, n_samples}`，模块内缓存（issue 完成时 invalidate）。
6. **前端 ConductorLogPanel 加 Stepper/Timeline**：横向 Stepper 展示走过的 phase + 当前 phase + 每段时长；使用 `framer-motion` `AnimatePresence` 做新 phase 节点出现 + 当前节点高亮 pulse；参考 `frontend/src/features/agents/dock/StatusBubble.tsx` 现有 pattern。
7. **前端预估剩余时间**：调 `GET .../conductor-state-log` 拉历史 + 调新 `GET .../conductor-phase-estimates` 拉 P50/P95/N。当前 phase 显示 "已 32s / 预估 ~45s"；N<5 时数字前加 `~` + 灰色 + 问号 icon，hover tooltip 显示 "基于 N=2 历史样本，置信度低"；N>=5 去掉近似标记。
8. **前端进度条**：当前 phase 已用时长 / P50 → progress bar；超过 P95 时变 warning 色 + 文案 "比 95% 历史样本更慢"。
9. **前端 toast 监听 `conductor_state_violation`**：弹一个 warn-level toast，文案 "非法 phase 跳变：awaiting_subagent → streaming_llm"。复用 IssueDetailPage 现有 toast 系统（已存在的 `conductor_failed` toast）。
10. **Pause/Resume + LLM 报错的特殊外观**：Pause/Resume 在 Stepper 上合并成同一节点（不画成两个 phase），用横线遮罩 + 暂停 icon 表示；phase=`failed` 时该节点变 error 色 + ❌ icon。

## Acceptance Criteria

* [ ] 跑一个完整 issue（PM → engineer → QA → finalize）后，`GET /conductor-state-log` 返回完整序列；每行 duration_ms > 0；is_legal 全 1。
* [ ] 在 conductor_tools 临时插一个非法 transition（如 `done → awaiting_llm`）后，前端能看到 toast "非法 phase 跳变"，conductor_state_log 该行 is_legal=0，但 Conductor loop 继续运行。
* [ ] ConductorLogPanel 加载历史 issue 时，Stepper 展示所有走过的 phase + 每段时长，按时间从左到右；当前 phase 节点 pulse 动画。
* [ ] 第一个 issue 跑完前，预估时间显示 "—"；跑完后再跑第 2 个 issue，预估显示 "~XXs" + 灰色 + 问号；跑完第 5 个后，显示去掉近似标记。
* [ ] 当前 phase 超过 P95 时长时，进度条变 warning 色。
* [ ] Pause 一个 issue 后 Resume，Stepper 上 Pause/Resume 合并成同一节点（不是两个节点）。
* [ ] phase=failed 时该节点变 error 色 + ❌ icon。
* [ ] pytest 覆盖：transition 矩阵 + 违规放行 + state_log INSERT/duration 计算 + estimate 缓存。
* [ ] frontend 覆盖：Stepper 渲染快照 + 违规 toast RTL + 预估 fallback（N<5 / N>=5）的两个 case。

## Definition of Done

* 状态机改动 + 切换日志表 + API + estimator 有 pytest 覆盖。
* 前端 Stepper/Timeline + toast + 进度条有 RTL/快照测试。
* MiniMax 网关人工验证一个 issue 跑完，Stepper 正常增长 + 预估时间显示合理。
* CLAUDE.md 加一段"Conductor 状态机 + state_log"小节。

## Technical Approach

### 后端

- `conductor_main_loop.py`：
  - 顶层加 `LEGAL_TRANSITIONS: dict[str, set[str]]` 表
  - `set_phase()` 在 transition 前 lookup，违法时 `logger.warning(...)` + 写 `is_legal=0` 但仍执行
  - 改 `set_phase()` 也写 `conductor_state_log` INSERT
- `sqlite_store.py` + `async_sqlite_store.py`：加 `conductor_state_log` CREATE TABLE + CREATE INDEX；按 [[feedback-stop-after-task-definition]] 教训，ALTER TABLE 必须在 CREATE INDEX 之前（如有列追加）
- `phase_duration_estimator.py`：
  - `class PhaseDurationEstimator: estimate(phase) -> EstimateResult` 含 lru_cache + 在 issue done 时 invalidate
  - 从 `conductor_state_log` 按 to_phase group by 算 P50/P95/N
- `interfaces/api.py`：
  - `GET /api/codex/issues/{id}/conductor-state-log` → list
  - `GET /api/codex/issues/{id}/conductor-phase-estimates` → `{phase: {p50_ms, p95_ms, n_samples}}` map
  - emit `conductor_state_violation` SSE（参考现有 `conductor_failed`）

### 前端

- `frontend/src/lib/api.ts`：
  - `getConductorStateLog(issueId)` / `getConductorPhaseEstimates(issueId)`
  - SSE 事件类型加 `conductor_state_violation`
- `frontend/src/features/workflow/ConductorLogPanel.tsx`：
  - 新增 `<ConductorStepper>` 子组件：横向 Stepper，节点 = `(phase, started_at, ended_at, duration_ms)`；用 framer-motion `<AnimatePresence>` 包裹节点列表
  - 新增 `<PhaseEstimate>` 子组件：显示 "已 32s / ~45s" + 进度条
  - 订阅 `conductor_state_violation` → 调 IssueDetailPage 的 toast 系统
  - Pause/Resume 合并：把连续 paused 段合并成一个节点，detail 加横线 + ⏸ icon
- `frontend/src/features/issues/IssueDetailPage.tsx`：
  - 监听 `conductor_state_violation` 跟现有 `conductor_failed` 同样的 toast 模式

## Decision (ADR-lite)

**Context**: 上一任务交付了"single-cell phase 显示 + stuck 30s 提示"作为流式 MVP，但用户希望升级到完整状态机 + 时间线 + 动画 + 预估剩余时间。

**Decision**: Bundle C 全套（5-7 天）。切换日志独立新表；违规警告放行可观察；预估时间 N<5 显示 ~ 近似 + tooltip 解释置信度。

**Consequences**:
- 优点：单 Conductor 任务的可视化达到生产级；P50 数据持续积累后预估越来越准；状态机违规可观察便于后续调优合法矩阵
- 风险：合法矩阵第一版可能覆盖不全 → 选警告放行而非拒绝，保证 loop 不阻塞；冷启动期预估时间体验差 → tooltip 透明告知 N 样本数
- 留尾巴：(1) 多 issue 并发的 phase 总览面板；(2) specialist mesh phase 嵌套展示；(3) task-level CHAT 链路 stepper（不在本任务）

## Out of Scope

- 多 issue 并发的"工程台总览"面板（独立任务）
- specialist mesh（engineer → security_reviewer）的 phase 嵌套展示
- 给 task-level CHAT/REFINE/RERUN 加 stepper（codex/claude CLI 链路另一条线）
- 把状态机违规升级为"拒绝 transition"模式（数据积累后再决定）
- Approvals 页 `awaiting_review` 和 `awaiting_user_clarification` 联动（另一独立任务）

## Technical Notes

- 后端关键文件：`backend/app/application/conductor_main_loop.py` (`set_phase` + 8 phase emit 点)、`backend/app/application/conductor_tools.py` (`_notify_status` 3 处)、`backend/app/adapters/sqlite_store.py` + `async_sqlite_store.py` (新表 migration)、`backend/app/interfaces/api.py` (新 2 个 GET + SSE)、`backend/app/application/phase_duration_estimator.py` (新模块)
- 前端关键文件：`frontend/src/features/workflow/ConductorLogPanel.tsx`、`frontend/src/lib/api.ts`、`frontend/src/features/issues/IssueDetailPage.tsx`
- 动画库：framer-motion ^12.38.0 已装，参考 `frontend/src/features/agents/dock/StatusBubble.tsx`
- 上一任务已落地的基础设施：`phase + detail` 字段、`_emit_conductor_status` 5 个 emit 点、`conductor_status` SSE 事件、`conductor_turns(kind='llm_response')` 落盘、ConductorLogPanel 已订阅 `conductor_status` + `conductor_turn_delta`
- migration 顺序教训（[[feedback-stop-after-task-definition]] 相关）：在 sqlite_store / async_sqlite_store 加新表时确保 CREATE TABLE 在 CREATE INDEX 之前

## Predecessor

- Parent (archived): `.trellis/tasks/archive/2026-05/05-22-conductor-streaming-and-live-status/prd.md` — commit `fe12046` + `7dbf71c` 交付流式 + phase/detail 基础
