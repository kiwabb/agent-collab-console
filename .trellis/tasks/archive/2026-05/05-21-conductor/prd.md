# Conductor 决策日志可见性 + 静默崩溃修复

## Goal

让用户能"看到 Conductor 在干嘛"。当前 `run_issue_conductor_loop` 用 `asyncio.create_task` 启动，任何异常都被 asyncio 静默吞掉；`conductor_tasks.status` 永远停在 `running`；后端 stderr 只输出到用户终端窗口（dev-local.sh 不 tee 到文件）。结果：用户创建 issue 后完全无从判断 Conductor 是在 LLM 调用排队、是已经跑完、还是早就崩了。

## What I already know

- `auto_start_issue_graph` 在 `backend/app/interfaces/api.py:4564` 里用 `asyncio.create_task(run_issue_conductor_loop(...))` fire-and-forget 启动 Conductor
- `run_issue_conductor_loop` 在 `backend/app/application/conductor_main_loop.py:170` 起，loop 内部异常如果未 catch 会向上传播，但 asyncio.create_task 没 done_callback，整个 traceback 丢失
- `ConductorTask` 模型（`backend/app/domain/models.py`）有 `status` / `result_json` 字段，loop 结束才写回；中途崩溃没人改它
- `run_conductor_loop`（line 55）每一轮调 `llm(messages, tools)` 拿响应，提取 tool_use 块，执行 tool，把 tool_result 喂回；turn_index 从 0 到 max_turns(30)
- 现有可视化：`ProjectConductor.append_hot_event`（每个 turn 结尾才追一条），`agentBus.onConductorLog`（前端 toast 流，DagTab 的旧 streaming 模式才用），`ConductorLogPanel`（DagTab 点 Conductor 根节点弹出的右侧抽屉，只读 hot_thread）
- `dev-local.sh` 不重定向后端 stderr 到文件，只往启动它的终端窗口输出
- MiniMax-M2.7（Anthropic 兼容 API）是当前唯一配置 API key 的 executor，每次 LLM 调用走 `call_llm_with_tools`（`llm_runner.py:306`），单次默认超时 28s（`WORKFLOW_ORCHESTRATOR_TIMEOUT`）

## Assumptions (temporary)

- 静默崩溃的主因是 LLM 调用出错（HTTP 4xx、thinking 块往复传 MiniMax 不接受、tool_use 解析异常等），不是 Conductor 业务逻辑死循环
- 用户要的"可见"主要是诊断用途（看 Conductor 决策路径 + 看崩溃原因），不是给生产环境监控
- 决策实时刷新对前端来说足够价值，不需要 audit-log 级别的不可篡改记录

## Open Questions

（全部解决）

## Resolved

- **Q1 范围 → 大全**：崩溃可见 + 日志落盘 + UI 决策面板，前后端都改。
- **Q2 UI 入口 → 复用 ConductorLogPanel**：扩展现有 285 行的 `frontend/src/features/workflow/ConductorLogPanel.tsx`，在它已有的 thread/log 双 tab 基础上加一个 "Decisions" tab（或扩展 log tab）展示每轮 LLM 调用 + tool_use + tool_result 的时间线。入口已经接好（DAG tab 点 Conductor 根节点）。
- **Q3 崩溃通知 → DB + SSE**：`done_callback` 写 conductor_tasks.status=failed 后通过 event_bus emit `conductor_failed` 事件。前端监听弹 toast，引导用户打开 ConductorLogPanel 看 traceback。每轮决策事件也同步 emit（`conductor_turn`），让面板能实时长。
- **Q4 决策数据存哪 → 新表 conductor_turns**：schema `(id TEXT PK, conductor_task_id TEXT, issue_id TEXT, turn_index INT, kind TEXT, payload_json TEXT, created_at)`；`kind ∈ {llm_request, tool_use, tool_result, error, finalize}`。索引 `(conductor_task_id, turn_index)` + `(issue_id, created_at)`。一行一事件，分页/SSE/查询都顺。

## Requirements (evolving)

### 必做（不论范围）

- `asyncio.create_task(run_issue_conductor_loop(...))` 加 `add_done_callback`，异常时：
  - 把 `conductor_task.status` 标为 `failed`
  - `result_json` 写 `{"error": "<class>", "message": "<str>", "traceback": "<truncated>"}`
  - 通过 event_bus 发 `conductor_failed` SSE，让前端能弹 toast
- `run_issue_conductor_loop` 内部本身也 wrap try/except，确保即使 done_callback 没生效，conductor_task 至少能落到 failed 而不是 stuck running

### 可能做（取决于范围）

- 日志落盘：`dev-local.sh` 把后端 stderr `tee` 到 `/tmp/agent-collab-backend.log` 并打印路径，方便 `tail -f`
- 决策实时可见：每轮 LLM call/tool_use/tool_result 持久化到一张新表或扩展现有结构，提供 `GET /api/codex/issues/{id}/conductor/turns` 端点 + 前端面板

## Acceptance Criteria (evolving)

- [ ] **必做**：故意让 Conductor 崩（比如把 API key 改错），20s 内 `sqlite3 conductor_tasks WHERE issue_id=<x>` 状态变 `failed`，`result_json` 包含 traceback
- [ ] **必做**：上面同样场景，前端能看到崩溃状态（toast 或 DAG status 变红），不需要刷新页面
- [ ] **必做**：原有功能不退化——成功路径下 conductor_task.status 仍然走 done，graph.status 走 done
- [ ] **如果做日志落盘**：`./dev-local.sh` 启动时控制台打印 `Backend log: /tmp/agent-collab-backend.log`，启动后 `tail -f /tmp/agent-collab-backend.log` 能看到 uvicorn + conductor 全部输出
- [ ] **如果做 UI 决策面板**：创建 issue 后打开决策面板，能实时看到每轮 LLM 调用：`turn N: dispatch_subagent(role=pm) → SubAgentResult(status=done, ...)`，至少能区分 thinking/tool_use/tool_result/finalize 四种事件

## Definition of Done

- 后端 pytest 全绿（不引入新 failure）
- 前端 `npm run build` 通过（如果改前端）
- 至少 1 个新单测覆盖崩溃捕获路径
- CLAUDE.md 加一段"诊断 Conductor 崩溃"的小节

## Out of Scope (explicit)

- 不做生产级 audit log（不可篡改 / 审计追溯）
- 不做 Conductor 决策的"重放"或"回滚"能力
- 不做 Anthropic SDK 升级或 LLM provider 切换
- 不做 hot/warm/cold memory 改造
- 不重写 `run_conductor_loop` 主循环逻辑，只在它周围加观测点

## Technical Approach

### 数据流

```
[Conductor loop turn N]
       ↓
  run_conductor_loop 内打点：
    - llm_request → save_conductor_turn(kind="llm_request", payload={msgs_tail, tools})
    - llm response → save_conductor_turn(kind="tool_use", payload={name, input}) × N
    - tool 执行返回 → save_conductor_turn(kind="tool_result", payload={result, is_error}) × N
    - finalize_task → save_conductor_turn(kind="finalize", payload={status, answer})
       ↓
  每次 save 同步 event_bus.append({type:"conductor_turn", issue_id, conductor_task_id, turn_index, kind, summary})
       ↓
  loop 退出（正常/异常）→ run_issue_conductor_loop 写 conductor_tasks.status + 写 graph.status
  异常 → event_bus.append({type:"conductor_failed", issue_id, error_message})
       ↓
  前端：
    DagTab/AppShell 订阅 SSE conductor_failed → toast
    ConductorLogPanel 订阅 conductor_turn → append timeline
```

### 关键设计

- **conductor_turns 表 schema**: `id TEXT PK, conductor_task_id TEXT NOT NULL, issue_id TEXT NOT NULL, turn_index INTEGER NOT NULL, sub_index INTEGER NOT NULL DEFAULT 0, kind TEXT NOT NULL CHECK(kind IN ('llm_request','tool_use','tool_result','error','finalize')), payload_json TEXT NOT NULL, created_at TEXT NOT NULL`
  - 索引 `(conductor_task_id, turn_index, sub_index)` 主时间线
  - 索引 `(issue_id, created_at)` 按 issue 拉
  - payload_json 写入前 truncate 到 32 KB，超长加 `__truncated__: true`
- **崩溃捕获双层兜底**: `run_issue_conductor_loop` 顶层 try/except + `auto_start_issue_graph` 的 `asyncio.create_task` 加 done_callback。两层都更新 conductor_task.status = failed + 写 result_json{error,...}。done_callback 自己用 try/except 包，至少 logger.error。
- **dev-local.sh log tee**: 启动后端时 `2>&1 | tee /tmp/agent-collab-backend.log`，控制台同时打印 `Backend log: /tmp/agent-collab-backend.log`。
- **前端 SSE 监听**: 复用现有 `useBusEventEffect` + `busEventMatchers.typeIn`。toast 用现有 `useToast`。
- **ConductorLogPanel 改造**: 在现有 thread/log 双 tab 基础上加第三个 "Decisions" tab，渲染 conductor_turns 按 turn_index 分组的时间线。

## Decision (ADR-lite)

**Context**: Conductor 后台跑、任何异常被 asyncio.create_task 吞掉、用户完全看不到决策也看不到崩溃。

**Decision**:
1. 决策数据新建 `conductor_turns` 表，一行一事件，跟 hot/warm/cold memory 隔离
2. 崩溃双层兜底：loop 内 try/except + create_task done_callback
3. SSE 推 `conductor_turn` / `conductor_failed`，前端实时增长 + toast
4. UI 复用 `ConductorLogPanel`，加 "Decisions" tab
5. `dev-local.sh` tee 后端 stderr 到固定日志路径

**Consequences**:
- 多一张表 + 一个迁移；写盘开销每 turn 几 KB，可接受
- payload truncation 是必须的（防止 LLM 巨大响应吃满 DB）
- specialist mesh 当前不写 conductor_turns（已有 AgentMessage 表），未来如要统一可加 kind="specialist_event"

## Implementation Plan

4 个 PR-style 切片，单 PR 合并：

**PR1 — 后端骨架（崩溃可见 + turn 写入）**
- migration: `conductor_turns` 表
- `app/domain/models.py`: 新增 `ConductorTurn` 模型
- `app/adapters/async_sqlite_store.py`: 加 `save_conductor_turn` / `list_conductor_turns`
- `app/application/conductor_main_loop.py`:
  - 在 `run_conductor_loop` 入口/响应/工具返回/finalize/error 5 个点位调 `save_conductor_turn`
  - 在 `run_issue_conductor_loop` 顶层加 try/except，异常时 update conductor_task.status=failed + 写 result_json
- `app/interfaces/api.py` 的 `auto_start_issue_graph`: `asyncio.create_task` 加 done_callback 兜底
- 测试: `tests/test_conductor_turns.py` 覆盖正常路径写入 + 异常路径 status=failed

**PR2 — API + SSE**
- 新端点 `GET /api/codex/issues/{id}/conductor/turns?conductor_task_id=&limit=&since_id=`
- 写 turn 时同步 `event_bus.append({type:"conductor_turn", issue_id, conductor_task_id, turn_index, kind, summary})`
- 失败兜底 `event_bus.append({type:"conductor_failed", issue_id, conductor_task_id, error_message})`
- 测试: `tests/test_conductor_turns_api.py` 覆盖端点 + SSE event 类型

**PR3 — 前端面板**
- `frontend/src/lib/api.ts`: `getConductorTurns(issueId, opts)` + 类型
- `frontend/src/features/workflow/ConductorLogPanel.tsx`: 加 "Decisions" tab，渲染时间线 + 订阅 `conductor_turn` SSE append
- `frontend/src/app/layout.tsx` 或公共 layout: 订阅 `conductor_failed` 全局弹 toast（点击打开 ConductorLogPanel）

**PR4 — 日志落盘 + 收尾**
- `dev-local.sh`: 后端 `tee /tmp/agent-collab-backend.log` + 控制台打印路径
- `CLAUDE.md`: 加"诊断 Conductor"小节（链 turn 表 + toast + 日志路径）

## Technical Notes

- 关键文件:
  - `backend/app/interfaces/api.py:4564` — `auto_start_issue_graph` 的 fire-and-forget 在这
  - `backend/app/application/conductor_main_loop.py:170` — `run_issue_conductor_loop` 入口
  - `backend/app/application/conductor_main_loop.py:55` — `run_conductor_loop` 主循环
  - `backend/app/application/llm_runner.py:306` — `call_llm_with_tools` 单次 LLM 调用
  - `backend/app/domain/models.py` — `ConductorTask` 模型
  - `dev-local.sh` — 启动脚本，未重定向 log
  - `frontend/src/features/workflow/ConductorLogPanel.tsx` — 现有决策面板
  - `frontend/src/features/agents/dock/agentBus.ts` — 前端 Conductor event 总线
- 现有 SSE 通道：`event_bus.append({"type": "conductor_tool", ...})` 已经存在（conductor_tools.py 里 spawn_custom_subagent / inject_context 等会发），但 dispatch_subagent 调用 LLM 那一层没有事件
