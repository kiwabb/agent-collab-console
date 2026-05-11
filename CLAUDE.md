# CLAUDE.md
This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands
```bash
./dev-local.sh                                          # 同时启动前后端
cd backend && uvicorn app.main:app --reload --port 8000
cd frontend && npm run dev                              # port 4000
cd backend && python3 -m pytest -v
cd backend && python3 -m pytest tests/test_foo.py -v
cd frontend && npm test
cd frontend && npm run build && npm run lint
```

## Architecture
本地优先 AI 任务工作台：用户创建 Issue → AI CLI（Claude/Codex）执行 → 多阶段工作流追踪。

**Stack**: FastAPI+aiosqlite(8000) / Next.js14+Tailwind v4+Base UI(4000) / SQLite+磁盘 JSON 产物

**Executor 路由** (`codex_process_manager.py`): `task.executor`="codex"|"claude" 分发到对应 Runtime；`task.provider`/`task.model` 选具体 API 配置。

**工作流阶段**: 需求→架构→开发→测试，每次跳转验证磁盘 JSON 产物文件存在。

**Run kinds** (`ExecutionProcess.kind`): `initial` / `rerun` 用 role workflow prompt 并 persist 产物；`refine` 把现有产物 + 用户修改指令喂给 agent 再 persist；`chat` 用极简 prompt，CLI 自己续接历史，**不**改 `task.result`、**不** persist。端点：`POST /api/codex/tasks/{id}/chat|refine|rerun`，旧 `/messages` alias 到 chat。

**Runtime Catalog** (`runtime_catalog_service.py`): executor→provider→model 配置，存 `runtime_catalog_settings` 表，task 级 > catalog 默认。

**实时通信**: WebSocket `/api/codex/sessions/{id}/logs` 流式日志；SSE `/api/execution-processes` 状态事件。

**Tailwind v4**: `bg-popover` 等工具类需 `@theme` 中有 `--color-popover: var(--popover)` 别名，仅 `:root` 定义不够。

**Base UI Select**: `alignItemWithTrigger=false`；Icon/ItemIndicator 用 children 不用 render prop（避免默认 ▼/✔️ 传入 Lucide SVG）。

**i18n**: `useI18n().t("key")`，key 在 `frontend/src/lib/i18n.ts`。

**环境变量**: `REAL_CLI=true` / `CODEX_WORKSPACE_ROOT` / `SQLITE_DB_PATH` / `CLAUDE_CMD` / `CODEX_LAUNCH_ENABLED=false`
