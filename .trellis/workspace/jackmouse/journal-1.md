# Journal - jackmouse (Part 1)

> AI development session journal
> Started: 2026-05-21

---



## Session 1: Conductor 决策日志可见性 + 静默崩溃修复

**Date**: 2026-05-22
**Task**: Conductor 决策日志可见性 + 静默崩溃修复
**Package**: ccgui
**Branch**: `main`

### Summary

新增 conductor_turns 表（5 kind: llm_request/tool_use/tool_result/finalize/error）+ 2 索引；run_conductor_loop 在 5 个点位写 turn；双层崩溃兜底（run_issue_conductor_loop try/except + auto_start_issue_graph 的 asyncio.create_task done_callback）→ conductor_tasks.status=failed + result_json 含 traceback；新端点 /codex/issues/{id}/conductor-turns；SSE conductor_turn + conductor_failed；前端 ConductorLogPanel 加 Decisions tab + IssueDetailPage 全局 toast；dev-local.sh tee 后端日志到 /tmp/agent-collab-backend.log；CLAUDE.md 加诊断段。验证 298 passed (+2)，frontend build 干净。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `75bcae0` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 2: Conductor 交互式对话 (Steer + Resume)

**Date**: 2026-05-22
**Task**: Conductor 交互式对话 (Steer + Resume)
**Package**: ccgui
**Branch**: `main`

### Summary

用户主动给 Conductor 发消息影响下一轮决策（poll DB 注入 [USER INTERJECTION] user turn）+ mid-call interrupt Pause/Resume（asyncio task.cancel + wake_event）。conductor_turns 加 consumed_at 列 + kind='user_message'；新 conductor_pause_registry.py 单例 _ConductorControl；3 新 API 端点。前端 ConductorLogPanel 加输入框 + Pause/Resume + 状态 chip + user_message 气泡渲染。23/23 conductor test 过，frontend build 干净。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `5e3cc65` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 3: pytest 提速 + Conductor consumed_at hotfix

**Date**: 2026-05-22
**Task**: pytest 提速 + Conductor consumed_at hotfix
**Package**: ccgui
**Branch**: `main`

### Summary

(1) Hotfix: 01454d4 把 conductor_turns consumed_at ALTER TABLE 移到 CREATE INDEX 之前，老 DB 启动不再炸。(2) e30653c 加 @pytest.mark.slow + addopts 默认跳过 + conftest.py 实现 --runslow flag，老 DB → 355/410，--runslow → 410，显式 path 仍跑全量。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `01454d4` | (see git log) |
| `e30653c` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 4: Conductor 流式输出 + phase/detail 实时状态可见

**Date**: 2026-05-22
**Task**: Conductor 流式输出 + phase/detail 实时状态可见
**Package**: ccgui
**Branch**: `main`

### Summary

Conductor LLM 调用从非流式 httpx.post 切到 Anthropic SSE 流式 (call_llm_with_tools_streaming)；100ms batch 聚合 text_delta + tool_use input_json_delta，emit 新 SSE 事件 conductor_turn_delta；turn 结束写一行 conductor_turns(kind='llm_response') 落盘完整文本。conductor_status 加 phase + detail 两字段，8 个枚举覆盖 awaiting_llm/streaming_llm/dispatching_subagent/awaiting_subagent/awaiting_user_clarification/paused/done/failed；前端 ConductorLogPanel 订阅两个新事件实时渲染打字流 + phase 时长，awaiting_subagent>30s 显示 stuck。Brainstorm 阶段验证 claude-agent-sdk 切换不可行 (MiniMax-M2.7 非 Claude，SDK 注入 Claude-only 控制协议会让 anthropic-compat 网关 4xx)，决定保持自撸 httpx。Codex 实施完成后 main agent 派 trellis-check 验证，sub-agent 违反 prompt 指令跑全量 pytest 卡死被 TaskStop；改 inline targeted 验证 11/11 + 静态 grep 6/6 Requirements 全绿。补 commit 7dbf71c 是 Phase 3.4 stage 时遗漏的两个流式专用测试 (test_llm_runner_streaming.py + conductorLogPanelStreaming.test.ts)。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `fe12046` | (see git log) |
| `7dbf71c` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 5: Conductor 完整状态机 + Stepper/Timeline + 预估剩余时间

**Date**: 2026-05-22
**Task**: Conductor 完整状态机 + Stepper/Timeline + 预估剩余时间
**Package**: ccgui
**Branch**: `main`

### Summary

上一任务 (05-22-conductor-streaming-and-live-status, fe12046+7dbf71c) 交付的 phase/detail 基础上升级到完整状态机。后端 conductor_main_loop 加 LEGAL_TRANSITIONS 矩阵 + set_phase 校验 + 违规警告放行（is_legal=0 + emit conductor_state_violation SSE）；新表 conductor_state_log 两份 migration (CREATE TABLE 在 CREATE INDEX 之前)，set_phase 成功后 INSERT 一行带 duration_ms；phase_duration_estimator.py 新模块按 to_phase 算 P50/P95/N + lru cache + done invalidate；api.py 加 GET /conductor-state-log + /conductor-phase-estimates。前端 ConductorLogPanel 加横向 Stepper（framer-motion AnimatePresence + motion.div）当前节点 pulse、failed XCircle error 色、连续 paused 合并成一个节点 + i18n '暂停合并' 提示；PhaseEstimate 显示 '已 32s / ~45s' N<5 加 ~ + 灰 + tooltip 解释置信度、超 P95 进度条变 warning；IssueDetailPage + ExecutionProcessesContext 监听 conductor_state_violation 弹 toast。Codex 完成实施，main agent inline 验证 10 条 R 全绿（15 backend tests + 4 frontend node:test + build 通过 + lint 无 error），避免上次 sub-agent 跑全量 pytest 卡死的教训。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `f7c912d` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 6: Fix conductor streaming not live

**Date**: 2026-05-22
**Task**: Fix conductor streaming not live
**Package**: ccgui
**Branch**: `main`

### Summary

Unified the global realtime event stream onto WebSocket with envelope/ring-buffer resume, removed the SSE endpoint, and fixed the conductor drawer refresh gap with resume_gap handling and regression tests.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `2b9dbc4` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete
