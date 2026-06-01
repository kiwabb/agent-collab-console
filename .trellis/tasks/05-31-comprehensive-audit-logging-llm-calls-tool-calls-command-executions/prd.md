# Comprehensive audit logging: LLM calls, tool calls, command executions

## Goal

用户要"每一次调用都有记录——agent 的每次返回、工具调用、命令执行都要记录"。核实后系统**已记录大部分**，本任务补齐确认的真缺口，目标是任意一次 LLM 调用 / 工具调用 / 命令执行都可事后溯源。

## What I already know (已亲验，详见研究)

**已覆盖**：
- Conductor LLM 请求/响应（完整 content + usage + stop_reason）→ `conductor_turns`（kind=llm_request/llm_response，`conductor_main_loop.py:272-274,1065`）
- Conductor tool_use/tool_result（名/入参/返回/is_error）→ `conductor_turns`（`:300-336`）
- role agent token/成本 → `execution_processes`；产物 → `CodexTask.result`/artifact
- CLI 子进程 stdout/stderr 逐行 → `log_events`（`event_bus._db_worker`）
- QA 命令执行（命令/exit/stdout/stderr/duration_s）→ task.result + 磁盘（`qa_workflow.py:204,343`）
- phase 跳变 → `conductor_state_log`；项目事件 → `project_audit`

**真缺口**：
- 🔴 git 命令零日志（`git_service._run` `:65-97` 无 logging/落库）
- 🔴 通用事件不持久化（EventBus 内存环形缓冲 maxlen=1000，仅 stdout/stderr 写 `log_events`，conductor_turn/batch_started 等只 WS 推送）
- 🟠 CLI 完整命令行不结构化（`claude_process_runtime._spawn_process_async:219-267` 拼命令但不落 execution_processes）
- 🟠 Auto-plan LLM 调用仅 stderr（`llm_runner.py`，不入 conductor_turns）
- 🟡 流式 token delta 不持久化（设计如此）；log 行不关联 tool_use/turn；project_audit 仅摘要无 operator/reason/changed_files
- 统一日志：纯文本 stderr → `/tmp/agent-collab-backend.log`（dev-local.sh 重定向），无结构化 JSON / 无轮转

## Decisions (ADR-lite)

- **[Q1] 统一落库 + UI 查看器**（不是只补缺口）。
- **[Q2] 新建统一 `audit_log` 表**：每次 LLM 调用/agent 返回/工具调用/命令执行/git/CLI 启动/通用事件各写一行。**用户明确选此**（UI 最简、schema 统一），接受与现有表的数据重复。
  - **对冲措施**：单一 `audit_logger` 模块做唯一写入口，各 choke point 调用，禁止散写（防双写漂移）。异步非阻塞写（复用 `event_bus._db_worker` 队列模式），不阻热路径。
  - **粒度边界（关键）**：audit_log = **调用级**（每次调用/命令/事件一行）。逐行 stdout/stderr **仍留 `log_events`**（高频已完整），audit_log 经 `execution_process_id` 关联，不重抄。大 payload 沿用 conductor_turns 8000 字符截断 + `__truncated__`。
- **[Q3] 全局审计页 + 过滤/搜索**：跨 issue/project，按 category/issue_id/task_id/时间过滤 + 关键词搜索 + 分页。

## Requirements

### audit_log 表 schema（建议）
`id, created_at, category, actor, issue_id?, task_id?, conductor_task_id?, execution_process_id?, correlation_id?, status?(ok/error), duration_ms?, payload_json(截断), error?`
- category 枚举：`llm_call`(请求) / `llm_return`(响应+usage) / `tool_use` / `tool_result` / `command_exec`(QA) / `git_command` / `cli_spawn`(完整命令行+cwd) / `event`(通用 EventBus) / `agent_finalize`。

### 写入点（经 audit_logger，集中）
- `conductor_main_loop`：llm_request/response、tool_use/result、finalize、error（与现有 conductor_turns 同处co-locate）。
- `llm_runner.py`：Auto-plan LLM 调用（现仅 stderr）。
- `git_service._run`：每条 git 命令（cmd/exit/stdout/stderr/duration）。
- `claude_process_runtime._spawn_process_async`：CLI 完整命令行 + cwd + model/provider。
- `qa_workflow`：命令执行（镜像入 audit_log，源仍在 task.result）。
- `event_bus.append`：通用事件持久化（含 conductor_turn/batch_started/budget_* 等）。

### 读取 API
- `GET /api/codex/audit-log`：filters(category[], issue_id, task_id, since/until, q 搜索) + 分页(cursor/limit) + 倒序。

### 前端
- 全局 "Audit Log" 页（路由 + 导航入口）：过滤栏(category/issue/task/时间) + 搜索框 + 虚拟化列表 + 行展开看 payload；i18n key。

## Acceptance Criteria

- [ ] AC1: `audit_log` 表 + 迁移；`audit_logger` 单一写入口，异步非阻塞
- [ ] AC2: 6 类写入点全部经 audit_logger 落库（LLM/tool/command/git/CLI/event + auto-plan）
- [ ] AC3: 逐行 stdout/stderr 不重抄进 audit_log，经 execution_process_id 关联 log_events
- [ ] AC4: 大 payload 截断不撑爆；写入失败不阻断/不拖慢热路径（best-effort）
- [ ] AC5: 读取 API 支持 category/issue/task/时间过滤 + 关键词搜索 + 分页
- [ ] AC6: 全局审计页可过滤/搜索/展开查看，i18n 齐全
- [ ] AC7: 不破坏现有 conductor_turns/log_events/QA；串行+并行 swarm 零回归；后端快档绿 + 前端 tsc/lint 绿

## Implementation Plan (PRs)
- **PR1**：`audit_log` 表 + schema + `audit_logger` 模块（异步写队列，复用 event_bus worker 模式）+ 单测。
- **PR2**：埋点——conductor/llm_runner/git_service/claude_process_runtime/qa/event_bus 6 类写入，经 audit_logger；测试断言各类落库。
- **PR3**：读取 API（过滤/搜索/分页）+ 测试。
- **PR4**：前端全局 Audit Log 页（过滤/搜索/虚拟列表/展开）+ i18n + tsc/lint。

## Out of Scope (explicit)
- 不重做 conductor_turns/log_events/QA（保留，audit_log 为附加统一视图）
- 不把逐行 stdout/stderr 重抄进 audit_log（留 log_events，关联即可）
- 不做日志轮转/外部采集（结构化文件 JSONL 那条路线未选）；audit_log 保留期/裁剪留后续
- 流式 token-level delta 持久化暂不做（仍走事件）

## Out of Scope (explicit)
- 不重做已完整的 conductor_turns / log_events / QA 命令记录

## Technical Notes
- 关键文件：`git_service.py` `event_bus.py` `conductor_main_loop.py` `claude_process_runtime.py` `llm_runner.py` `main.py`(logging 配置) `async_sqlite_store.py`/`sqlite_store.py`(表)
- 研究：`research/existing-logging-inventory.md`（待落）
