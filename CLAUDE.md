# CLAUDE.md
This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands
```bash
./dev-local.sh                                          # 同时启动前后端
cd backend && uvicorn app.main:app --reload --port 9000
cd frontend && npm run dev                              # port 4000
cd backend && python3 -m pytest -v
cd backend && python3 -m pytest tests/test_foo.py -v
cd frontend && npm test
cd frontend && npm run build && npm run lint
```

## Architecture
本地优先 AI 任务工作台：用户创建 Issue → ProjectConductor 通过 tool-use loop 动态调度 sub-agent（PM/Architect/Engineer/QA/specialist），每个 agent 真跑 CLI（Claude/Codex）→ Conductor 收到 SubAgentResult 决定下一步 → 直到 `finalize_task`。

**Stack**: FastAPI+aiosqlite(9000) / Next.js14+Tailwind v4+Base UI(4000) / SQLite+磁盘 JSON 产物

**Executor 路由** (`codex_process_manager.py`): `task.executor`="codex"|"claude" 分发到对应 Runtime；`task.provider`/`task.model` 选具体 API 配置。

**Conductor-driven orchestration**: 创建 Issue → `auto_start_issue_graph` 起空 WorkflowGraph + 后台启 `run_issue_conductor_loop(issue)` → Conductor 用 Anthropic tool-use 决定调谁。核心工具：
  - `dispatch_subagent(role, prompt?, prev_node_key?)` — 真实化（不是 stub）。`task_dispatcher.dispatch_role` 建 CodexTask + 动态 add WorkflowNode/Edge + 启 task_runner；`TaskCompletionRegistry`（asyncio.Event 单例）让 Conductor await 到完成，900s 超时；`on_task_completed` 触发 registry.signal 唤醒 Conductor 拿 SubAgentResult。
  - `spawn_custom_subagent` — Conductor 自己注册项目专属 specialist agent。
  - `request_user_clarification` — Conductor 决定"PM 出完 PRD 要不要停"/"QA 通过要不要等用户审"等 gate，对接 Approvals 页 `awaiting_review` 状态。
  - `retrieve_cold_memory` / `finalize_task`。

**WorkflowGraph 现在是 Conductor 决策时间线的可视化**：每次 `dispatch_subagent` 加一个 node + 上一节点到当前节点的 sequence edge（`add_workflow_node` / `add_workflow_edge` 是 INSERT OR IGNORE，不破坏已存在的节点）。前端 DagTab 通过 `workflow_node_updated` / `task_status` / `task_created` SSE 事件实时增长画面。同一 role 多次调度的 node_key 加 `#N` 后缀（`engineer#1`、`engineer#2`），前端按前缀解析 role icon。

**Run kinds** (`ExecutionProcess.kind`): `initial` / `rerun` 用 role workflow prompt 并 persist 产物；`refine` 把现有产物 + 用户修改指令喂给 agent 再 persist；`chat` 用极简 prompt，CLI 自己续接历史，**不**改 `task.result`、**不** persist。端点：`POST /api/codex/tasks/{id}/chat|refine|rerun`，旧 `/messages` alias 到 chat。

**Runtime Catalog** (`runtime_catalog_service.py`): executor→provider→model 配置，存 `runtime_catalog_settings` 表，task 级 > catalog 默认。

**实时通信**: WebSocket `/api/codex/sessions/{id}/logs` 流式日志；SSE `/api/execution-processes` 状态事件；bus 事件 `task_created` / `workflow_node_updated` / `task_status` 驱动前端图增长。

**Tailwind v4**: `bg-popover` 等工具类需 `@theme` 中有 `--color-popover: var(--popover)` 别名，仅 `:root` 定义不够。

**Base UI Select**: `alignItemWithTrigger=false`；Icon/ItemIndicator 用 children 不用 render prop（避免默认 ▼/✔️ 传入 Lucide SVG）。

**i18n**: `useI18n().t("key")`，key 在 `frontend/src/lib/i18n.ts`。

**环境变量**: `REAL_CLI=true` (默认 true,Engineer 真改代码、QA 真跑测试;false 走 mock) / `CODEX_LAUNCH_ENABLED=true` (默认 true,真启 codex 进程) / `QA_EXECUTE_COMMANDS=true` (跟 REAL_CLI 同源,显式关掉测试执行) / `QA_COMMAND_TIMEOUT_S=120` / `QA_TOTAL_BUDGET_S=300` / `CODEX_WORKSPACE_ROOT` / `SQLITE_DB_PATH` / `CLAUDE_CMD` (默认 "claude") / `CODEX_CMD` (默认 "codex") / `MAX_CONCURRENT_INSTANCES_PER_ROLE=3` (默认 3,Phase 4 多实例同角色并发上限)

**保留的核心闭环**：
- **QA 真跑命令**: QA 阶段会真实执行 LLM 提议的 `recommended_commands`(在 worktree cwd 内),命令经安全过滤(rm -rf / sudo / git push 等拒跑)+ 单条超时 + 总预算。任一非零退出 → status 强制覆盖为 `failed`,不信 LLM 自报。QA failed 后 Conductor 看到失败结果，自己决定要不要再 dispatch engineer（`qa_failure_summary` 写盘给下次 engineer 的 prompt 用，触发 REWORK 分支）。
- **项目记忆**: `<project.repo_path>/.agent-collab/team_notes.md` 是项目级长期记忆,issue 完成后 `project_memory_service.record_project_memory` 自动从 PM/Architect/Engineer/QA 产物里抽 deterministic 摘要 append 进去(无额外 LLM 调用)。下个 issue 启动时,每个 role 的 prompt 顶部都被注入 "TEAM CONTEXT" 块。文件超过 16 KB 时丢最旧的 block 保持预算。
- **Agent 提问**: 每个 role 的 JSON schema 加了可选 `clarification_question` 字段;role prompt 里有 "AGENT QUESTION ESCAPE HATCH" 段告诉 agent 遇到关键模糊性必须用这个字段问问题而不是瞎猜。`RoleWorkflowService.persist_result` 检测到 question 时把 task 置为 `awaiting_review` + `review_comment="[CLARIFY] ..."`,Conductor 拿到 awaiting_review 结果可主动 dispatch `request_user_clarification` 把球交回给用户。Approvals 页"Agent questions"分类显示并提供文本框,提交答案走 `POST /api/codex/tasks/{id}/answer` → 把问题+答案塞 review_comment 重新 dispatch,agent 用 REWORK 分支接续。
- **Tiered memory** (`project_conductor.py`): hot thread / warm summary / cold embeddings，Conductor 启动时注入 pinned + warm + hot 拼 initial prompt，运行中可通过 `retrieve_cold_memory` 查项目历史。
- **Specialist mesh** (`specialist_orchestrator.py`): Engineer 自己触发 security_reviewer 等 specialist 走 parent/child pause/resume，不绕 Conductor；Conductor 看到的是聚合后的 SubAgentResult。

**已删除（旧固定流水线）**：`workflow_orchestrator.py`、`workflow_templates.py`、`conductor_actions.py`、`conductor_supervisor.py`，`WorkflowScheduler.settle / _compute_node_status / _maybe_trigger_qa_rework / _maybe_trigger_peer_critique / _maybe_open_replan / apply_replan / _apply_diff_to_graph / _apply_pending_conductor_dispatches`，API 端 `/plan` / `/plan/stream` / `POST /graph` / `/graph/replan-*` / `spawn-custom` / `workflow-templates` / `apply-template` 端点，前端 `planIssue` / `planIssueStream` / `saveIssueGraph` / `startIssueGraph` / `listReplanPending` / `confirmReplan` / `rejectReplan` / `listWorkflowTemplates` / `usePhaseTransitions` / `PhaseStateMachine` / `ProposedDAG` 类型 / `WorkflowGraphView` 的 ProposedDAG 分支。`CONDUCTOR_MODE` 环境变量也没了 —— Conductor 永远是 orchestrator。
