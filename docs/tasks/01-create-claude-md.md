# Task: Create CLAUDE.md

在项目根目录 `/CLAUDE.md` 创建以下内容：

```markdown
# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# 启动（同时启动前后端）
./dev-local.sh

# 单独启动
cd backend && uvicorn app.main:app --reload --port 8000
cd frontend && npm run dev   # port 4000

# 测试
cd backend && python3 -m pytest -v
cd backend && python3 -m pytest tests/test_foo.py -v   # 单文件
cd frontend && npm test

# 前端构建/lint
cd frontend && npm run build
cd frontend && npm run lint
```

## Architecture

**Agent Collaboration Console** — 本地优先的 AI 任务工作台，用户创建 Issue、通过 AI CLI（Claude / Codex）执行任务、跟踪多阶段工作流进度。

### Stack
- **Backend**: Python FastAPI + aiosqlite，端口 8000，纯 asyncio（无线程）
- **Frontend**: Next.js 14 + TypeScript + Tailwind v4 + Base UI 组件，端口 4000
- **Storage**: SQLite (`backend/console.db`)；任务产物以 JSON 文件存储在磁盘

### 关键概念

**Executor 路由** (`backend/app/application/codex_process_manager.py`):  
`task.executor` 为 `"codex"` 或 `"claude"`，CodexProcessManager 据此分发到 `CodexAppServerRuntime` 或 `ClaudeProcessRuntime`。`task.provider` 和 `task.model` 在该 executor 内选择具体的 API 配置。

**工作流阶段**（顺序门控）:  
Issue 经历：需求 → 架构 → 开发 → 测试。每次阶段跳转都验证磁盘上是否存在必需的 JSON 产物文件（`implementation_plan.json`、`system_design.json`、`development_task_list.json` 等）。

**Runtime Catalog** (`backend/app/application/runtime_catalog_service.py`):  
集中管理 executor→provider→model 映射，存储在 `runtime_catalog_settings` 表。执行时按优先级解析配置：task 级别 > catalog 默认值。支持 `command_template` 和 `env_template` 为每个 provider 注入 CLI 参数/环境变量。

**实时通信**:
- WebSocket `/api/codex/sessions/{id}/logs` — 任务执行时流式传输日志
- SSE `/api/execution-processes` — 进程状态变更事件

### Frontend 注意事项

**Tailwind v4 颜色工具类**：`bg-popover`、`text-muted-foreground` 等需要 `globals.css` 的 `@theme` 块中有对应的 `--color-*` 变量。仅在 `:root` 定义的变量（如 `--popover`）不会自动生成工具类，需在 `@theme` 中添加别名 `--color-popover: var(--popover)`。

**Base UI Select**：`alignItemWithTrigger` 默认为 `false`（弹出框在 trigger 下方，不叠加）。`Select.Icon` 和 `Select.ItemIndicator` 使用 children 而非 `render` prop，避免 base-ui 将默认 `▼`/`✔️` 字符传入 Lucide SVG 导致文字叠加。

**i18n**：用户可见字符串通过 `useI18n().t("key")` 获取，key 定义在 `frontend/src/lib/i18n.ts`，支持 `zh-CN` 和 `en-US`。

### 环境变量
```
REAL_CLI=true                  # 使用真实 CLI 适配器（默认：mock）
CODEX_WORKSPACE_ROOT           # 产物文件工作目录
SQLITE_DB_PATH                 # DB 路径（默认：backend/console.db）
CLAUDE_CMD                     # Claude CLI 命令覆盖
CODEX_LAUNCH_ENABLED=false     # 测试中禁止真实 CLI 启动
```
```
