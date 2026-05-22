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
