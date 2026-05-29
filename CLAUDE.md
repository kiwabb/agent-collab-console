# CLAUDE.md

## Commands
```bash
./dev-local.sh                                          # 同启前后端 (前 4000 / 后 9000)
cd backend && python3 -m pytest -v                      # 默认快档，跳 @pytest.mark.slow
cd backend && python3 -m pytest --runslow -v            # 全量
cd backend && python3 -m pytest tests/test_foo.py -v    # 点名文件不受 slow 跳过影响
cd frontend && npm test
cd frontend && npm run build && npm run lint
```
后端日志同步到 `/tmp/agent-collab-backend.log`。

## Stack
FastAPI+aiosqlite(9000) / Next.js14+Tailwind v4+Base UI(4000) / SQLite(`console.db`)+磁盘 JSON 产物。

## Architecture (Conductor-driven)
Issue 创建 → `auto_start_issue_graph` 起空 `WorkflowGraph` + 后台 `run_issue_conductor_loop(issue)` → Conductor 用 Anthropic tool-use 决定调谁。**没有固定 DAG**，流水线 = Conductor 决策序列。

**核心工具**（`conductor_tools.py`）：
- `dispatch_subagent(role, prompt?, prev_node_key?)` → `task_dispatcher.dispatch_role` 建 `CodexTask` + add `WorkflowNode/Edge` + 写一条 `AgentMessage(handoff)` 给 Mesh + 启 task runner；`TaskCompletionRegistry` (asyncio.Event 单例) await 完成 (900s timeout)
- `spawn_custom_subagent` — 注册项目专属 specialist
- `request_user_clarification` — 走 `awaiting_review` 状态对接 Approvals 页
- `retrieve_cold_memory` / `finalize_task`

**用户插话**：`POST /api/codex/issues/{id}/conductor/message` 以 `[USER INTERJECTION]` 注入下一轮；`/conductor/pause|resume` 控制 loop。

**Executor 路由** (`codex_process_manager.py`): `task.executor=codex|claude` 分发到 Runtime；`task.provider/model` 选 API 配置；`runtime_catalog_settings` 表存 catalog 默认 (task 级 > catalog)。

## Run kinds (`ExecutionProcess.kind`)
- `initial` / `rerun` → 用 role workflow prompt 并 persist 产物
- `refine` → 现有产物 + 修改指令重 persist
- `chat` → 极简 prompt，CLI 续接历史，**不**改 `task.result` / **不** persist
- 端点：`POST /api/codex/tasks/{id}/chat|refine|rerun`

## 实时通信
全局 WS `/api/ws/events`，envelope `{v, ts, event_id, type, payload}`，`EventBus` ring buffer + `last_event_id` resume。per-workspace WS 仅做 execution process JsonPatch / task chat / raw log 等 task 级流。

## 核心闭环
- **QA 真跑命令** (`qa_workflow.py`): 在 worktree cwd 执行 LLM 提议的 `recommended_commands`，安全过滤 (rm -rf/sudo/git push 拒) + 单条/总预算超时；任一非零退出强制 `failed` (不信 LLM 自报)；失败摘要落盘供下次 engineer prompt 用
- **项目记忆**: `<repo>/.agent-collab/team_notes.md` issue 完成后 `project_memory_service` 抽 deterministic 摘要 append (无 LLM 调用)；下个 issue 每个 role prompt 顶部注入 "TEAM CONTEXT"；超 16KB 丢最旧 block
- **Agent 提问**: role JSON schema 有 `clarification_question`；触发时 task → `awaiting_review` + `review_comment="[CLARIFY] ..."`；Approvals 页提交答案走 `POST /api/codex/tasks/{id}/answer` 重 dispatch
- **Tiered memory** (`project_conductor.py`): hot/warm/cold；启动注入 pinned+warm+hot；运行中 `retrieve_cold_memory`
- **Specialist mesh** (`specialist_orchestrator.py`): Engineer 自触发 specialist 走 parent/child pause/resume，不绕 Conductor

## Gotchas
- **Tailwind v4**: `bg-popover` 类需 `@theme` 中 `--color-popover: var(--popover)` 别名，仅 `:root` 定义不够
- **Base UI Select**: `alignItemWithTrigger=false`；Icon/ItemIndicator 用 children 不用 render prop
- **i18n**: `useI18n().t("key")`，key 在 `frontend/src/lib/i18n.ts`
- **WorkflowGraph 是 Conductor 决策时间线可视化**，不是预设 DAG；同 role 多次调度 node_key 加 `#N`

## Env vars
`REAL_CLI=true` (默认；false→mock) / `CODEX_LAUNCH_ENABLED=true` / `QA_EXECUTE_COMMANDS` (跟 REAL_CLI 同源) / `QA_COMMAND_TIMEOUT_S=120` / `QA_TOTAL_BUDGET_S=300` / `CODEX_WORKSPACE_ROOT` / `SQLITE_DB_PATH` / `CLAUDE_CMD` (默认 "claude") / `CODEX_CMD` (默认 "codex")
- 并发/超时旋钮集中在 `timeouts.py` (启动期 `validate()` 校验不变量)：`MAX_CONCURRENT_INSTANCES_PER_ROLE=3` (同 role 跨 issue 进程级并发上限，`dispatch_subagent` 占 slot 跑完释放，满则返回 `status=role_busy`) / `CONDUCTOR_ROLE_SLOT_WAIT_S` (等不到 slot 的超时，默认=`CONDUCTOR_SUBAGENT_MAX_S`) / `CONDUCTOR_LOOP_MAX_S=7200` (整个 conductor loop 墙钟上限，0 禁用；命中 → `status=max_wall` 按 failed 收尾)

## 诊断 Conductor
- 后台异常 → `conductor_tasks.status=failed` + traceback 写 `result_json`
- 完整 LLM 响应 / tool_use / tool_result / finalize → `conductor_turns`；流式增量只走事件不写库
- `conductor_status` 事件 + `/conductor-state` 带 `phase + detail` (`awaiting_llm/streaming_llm/awaiting_subagent/paused`)
- phase 跳变写 `conductor_state_log`；非法跳变只告警 + 发 `conductor_state_violation`；`LEGAL_TRANSITIONS` 在 `conductor_main_loop.py`
