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
本地优先 AI 任务工作台：用户创建 Issue → AI CLI（Claude/Codex）执行 → 多阶段工作流追踪。

**Stack**: FastAPI+aiosqlite(9000) / Next.js14+Tailwind v4+Base UI(4000) / SQLite+磁盘 JSON 产物

**Executor 路由** (`codex_process_manager.py`): `task.executor`="codex"|"claude" 分发到对应 Runtime；`task.provider`/`task.model` 选具体 API 配置。

**工作流阶段**: 需求→架构→开发→测试，每次跳转验证磁盘 JSON 产物文件存在。

**Run kinds** (`ExecutionProcess.kind`): `initial` / `rerun` 用 role workflow prompt 并 persist 产物；`refine` 把现有产物 + 用户修改指令喂给 agent 再 persist；`chat` 用极简 prompt，CLI 自己续接历史，**不**改 `task.result`、**不** persist。端点：`POST /api/codex/tasks/{id}/chat|refine|rerun`，旧 `/messages` alias 到 chat。

**Runtime Catalog** (`runtime_catalog_service.py`): executor→provider→model 配置，存 `runtime_catalog_settings` 表，task 级 > catalog 默认。

**实时通信**: WebSocket `/api/codex/sessions/{id}/logs` 流式日志；SSE `/api/execution-processes` 状态事件。

**Tailwind v4**: `bg-popover` 等工具类需 `@theme` 中有 `--color-popover: var(--popover)` 别名，仅 `:root` 定义不够。

**Base UI Select**: `alignItemWithTrigger=false`；Icon/ItemIndicator 用 children 不用 render prop（避免默认 ▼/✔️ 传入 Lucide SVG）。

**i18n**: `useI18n().t("key")`，key 在 `frontend/src/lib/i18n.ts`。

**环境变量**: `REAL_CLI=true` (默认 true,Engineer 真改代码、QA 真跑测试;false 走 mock) / `CODEX_LAUNCH_ENABLED=true` (默认 true,真启 codex 进程) / `QA_EXECUTE_COMMANDS=true` (跟 REAL_CLI 同源,显式关掉测试执行) / `QA_COMMAND_TIMEOUT_S=120` / `QA_TOTAL_BUDGET_S=300` / `CODEX_WORKSPACE_ROOT` / `SQLITE_DB_PATH` / `CLAUDE_CMD` (默认 "claude") / `CODEX_CMD` (默认 "codex") / `MAX_CONCURRENT_INSTANCES_PER_ROLE=3` (默认 3,Phase 4 多实例同角色并发上限,如 3 个 Engineer 同时各持一个子任务)

**P0 闭环**: QA 阶段会真实执行 LLM 提议的 `recommended_commands`(在 worktree cwd 内),命令经安全过滤(rm -rf / sudo / git push 等拒跑)+ 单条超时 + 总预算。任一非零退出 → status 强制覆盖为 `failed`,不信 LLM 自报。QA failed 后 `WorkflowScheduler._maybe_trigger_qa_rework` 自动把 Engineer 节点重置 pending,把 qa_plan.json 失败摘要塞进 `task.review_comment` 触发"REWORK REQUIRED"分支,最多 `engineer.max_retries` 次自循环。

**P1 项目记忆**: `<project.repo_path>/.agent-collab/team_notes.md` 是项目级长期记忆,issue 完成后 `WorkflowScheduler._record_project_memory` 自动从 PM/Architect/Engineer/QA 产物里抽 deterministic 摘要 append 进去(无额外 LLM 调用)。下个 issue 启动时,每个 role 的 prompt 顶部都被注入 "TEAM CONTEXT" 块。文件超过 16 KB 时丢最旧的 block 保持预算。文件就是 markdown,人也可以手编。

**P2 Agent 提问**: 每个 role 的 JSON schema 加了可选 `clarification_question` 字段;role prompt 里有 "AGENT QUESTION ESCAPE HATCH" 段告诉 agent 遇到关键模糊性必须用这个字段问问题而不是瞎猜。`RoleWorkflowService.persist_result` 检测到 question 时把 task 置为 `awaiting_review` + `review_comment="[CLARIFY] ..."`,scheduler 不再向前推进。Approvals 页"Agent questions"分类显示并提供文本框,提交答案走 `POST /api/codex/tasks/{id}/answer` → 把问题+答案塞 review_comment 重新 dispatch,agent 用 REWORK 分支接续工作。

**节点 prompt 修复**: 工作流节点 `node.title="Draft PRD"` 这种泛 label 之前被 PM 当作 "issue_title" 使用,导致 PRD 完全跑偏。`WorkflowScheduler._dispatch_node` 现在对 managed_role 强制 `task.title=issue.title`、`task.prompt=issue.title+\\n+issue.description`,绕过 `[builtin:<role>]` 占位符。
