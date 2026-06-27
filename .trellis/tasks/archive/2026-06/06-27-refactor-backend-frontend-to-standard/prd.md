# 代码重构：按业界标准规范重构前后端

## Goal

将 `agent-collab-console` 前后端代码对齐"业界最标准"的工程规范，零行为变化地分阶段落地。
对齐对象（事实约定，权威）：
- 后端 `.trellis/spec/vibe-kanban/backend/`（5 篇）+ 前端 `.trellis/spec/vibe-kanban/frontend/`（6 篇）
- 顶层 `CLAUDE.md`（已落地的 gotchas / 环境变量规约）

参考计划（已存在的详细方案）：仓库根 `REFACTORING_PLAN.md`。本 PRD 收敛到 MVP 切片 + 验收。

## What I already know

- 仓库布局：FastAPI + aiosqlite 后端（9000），Next.js + Tailwind v4 + Base UI 前端（4000），`./dev-local.sh` 同启。
- 已有质量门：`pytest -v`（默认跳 `@pytest.mark.slow`）/ `npm test` / `npm run build && npm run lint`。
- 后端约束（来自 spec）：
  - 每个 Python 模块顶部必须有 `from __future__ import annotations`。
  - `os.getenv` 仅允许出现在 `application/timeouts.py` 的 `validate()`；其余用 accessor。
  - store 是唯一写 SQL 的地方；服务不 import `interfaces/`、不 `raise HTTPException`。
  - 后台协程在 loop boundary catch，落 `failed` + traceback。
- 前端约束：`strict` tsconfig、`no-any`、hooks 纯净、组件按域。
- 现状审计（`REFACTORING_PLAN.md §0` 摘要）：
  - 后端 39.7k 行 / 94 模块；前端 50.7k 行 ts/tsx。
  - 无 `pyproject.toml`；`pytest.ini` + `requirements.txt` 散落。
  - `os.getenv` 在 `timeouts.py` 之外有 67 处。
  - `next.config.ts` 设了 `eslint.ignoreDuringBuilds: true`；tsconfig 缺 `noUncheckedIndexedAccess` 等。
  - 超大文件：后端 `api.py` 7895 行 / 185 路由、`async_sqlite_store.py` 3517、`sqlite_store.py` 2540、`conductor_main_loop.py` 1451；前端 `i18n.ts` 3606、`api.ts` 2083、`SkillsLibraryPage.tsx` 1412、`types.ts` 1014。
  - 12 个 tracked 一次性脚本（`check_db.py`/`doctor.py`/`fix_syntax.py`/`test_handshake.py` 等）。
  - 工作树杂质：`backend/:memory:`(135KB)、`codex.db`、`benchmark.db` 等游离文件。
- 工作树已存在未提交的非重构范围改动（`06-27-audit-role-call-chain` 等），**不**纳入本任务。

## Assumptions (temporary)

- A1：本次重构 **不改任何对外语义**，仅做规范化与结构整理。
- A2：每个 Phase 独立可提交、可回滚；不与他人未提交改动交叉。
- A3：先立工具链（ruff/mypy/Prettier）+ 建立 baseline，再做结构拆分；存量违规用 `# noqa` / baseline 冻结，Phase 5 渐进清零。
- A4：`pyproject.toml` 引入后保留 `pytest.ini`（CI 兼容） 或迁入 `pyproject.toml [tool.pytest.ini_options]`（优先后者）。
- A5：超大文件拆分按"资源域"切片（如 `interfaces/routers/issues.py`），对外路径/方法零变化。
- A6：拆分后 `api.py` 仅留 router 聚合 + 异常处理器注册；每片迁移后跑该域测试。

## Open Questions

（仅 Blocking / Preference 留此处；其它走 spec/仓库自动回答）

- Q1 ✅ 决议：本次推到 **全 5 阶段**（仓库卫生 + 工具链 + 约定回归 + 结构重构 + 清零）。
- Q2 ✅ 决议：PR 粒度 = **1 PR / Phase**（共 5–6 PR），中间可暂停 / 回滚单个 Phase。
- Q3 ✅ 决议：与 `06-27-audit-*` WIP 的协作 = **按文件域隔离 PR**，两线并行不交叉。
- Q4：是否允许在重构同时顺手 fix 任何测试？答案：默认**不允许**（spec "no drive-by"），如必须则拆 follow-up。

## Requirements (evolving)

按 Phase 编排，**1 PR / Phase**，每 PR 自包含测试 + 验收 + 风险说明。

- **R0（Phase 0 PR）** — 仓库卫生
  - 删除/迁出 12 个 tracked 一次性脚本；删除工作树游离文件；强化 `.gitignore`。
  - 与 `06-27-audit-*` 无文件交集，安全先行。
- **R1（Phase 1 PR）** — 工具链立门 + baseline 冻结
  - 后端 `pyproject.toml` + ruff + ruff format + mypy strict（app/）；前端 Prettier + 严格 tsconfig + 关闭 `ignoreDuringBuilds`。
  - **CI 必须随工具链一起加 ruff/mypy/prettier 步骤**（避免"立门 = 摆设"）。
  - baseline 冻结方式：`ruff check --add-noqa` 或文件级 `# ruff: noqa`；mypy 逐模块 `# type: ignore[error]`（带错误码）。
- **R2（Phase 2 PR）** — 约定回归（零行为变化的纯整改）
  - 后端：`from __future__ import annotations` 全覆盖；`os.getenv` → `timeouts.py` accessor；服务层零 import `interfaces/`、零 `raise HTTPException`。
  - 前端：`console.log` 清零；`any` 清零。
- **R3（Phase 3 PR）** — 后端结构重构
  - `interfaces/api.py` 按资源域拆 router（issues/tasks/projects/prototypes/audit/runtime_catalog/diagnostics/skills/agents/approvals/conductors/knowledge/benchmarks/self_improvement/ws），每片 < ~700 行。
  - `adapters/*_store.py` 按聚合根拆；`AsyncSqliteStore` 单类型对外保持。
  - `conductor_main_loop.py` 抽 state machine 到独立模块。
- **R4（Phase 4 PR）** — 前端结构重构（可与 R3 并行，不同子树）
  - `i18n.ts` 按 locale 拆；`api.ts` / `types.ts` 按域拆；大组件抽 hook。
- **R5（Phase 5 PR）** — 清零
  - 移除所有 `# noqa` 与 `# type: ignore`，`ruff check .` / `mypy app` / `tsc --noEmit` / `eslint` 退出 0。
  - PR 模板 + CI 把质量门硬执行写进规则。

## Acceptance Criteria (evolving)

- [ ] AC1：`git ls-files | rg 'check_db|doctor\.py|fix_syntax|pytest_output|bubble-sort|test_handshake|test_message_flow'` 为空。
- [ ] AC2：`backend/pyproject.toml` 存在；`ruff check .`、`ruff format --check .`、`mypy app` 跑通（有 baseline 冻结文件可允许存量）。
- [ ] AC3：`.github/workflows/ci.yml` 含 ruff + mypy + 前端 prettier + tsc 步骤。
- [ ] AC4：`rg "os\.getenv" backend/app | rg -v timeouts.py` 为空。
- [ ] AC5：`rg "from app.interfaces" backend/app/application` 为空；`rg "raise HTTPException" backend/app/application` 为空。
- [ ] AC6：`rg "\bany\b" frontend/src`（按类型位）为 0；`rg "console\.(log|warn|error)" frontend/src` 为 0 或仅 error-boundary。
- [ ] AC7：`wc -l backend/app/interfaces/api.py` < ~800（仅聚合 + handler）。
- [ ] AC8：`wc -l frontend/src/lib/i18n.ts`（聚合后）< ~200。
- [ ] AC9：每个 Phase 完成后 `pytest -v` + `npm test` + `tsc --noEmit` + `npm run lint` 全绿。
- [ ] AC10：`tsc --noEmit` 在 `noUncheckedIndexedAccess` 等全开后无新增报错。
- [ ] AC11：路由总数 `rg -c "@router\.(get|post|put|patch|delete)" backend/app/interfaces/api.py`（拆分前 185）拆分后不变。

## Definition of Done (team quality bar)

- 每 Phase 独立提交 / 独立 PR / 独立可回滚。
- 不"重构与修 bug 混做"——任何发现的小问题走 follow-up。
- 测试覆盖：服务层单元 + 端点 integration + 状态机/迁移测试（如涉及）。
- 行为不变：所有现有测试在每个 Phase 末尾保持绿；`python -c "from app.main import app"` 导入烟雾过。
- 文档：`REFACTORING_PLAN.md` 状态随 PR 更新（每 Phase 末尾勾选对应 AC）。

## Out of Scope (explicit)

- 任何业务行为变更 / 新功能。
- 替换底层框架（FastAPI → 别的 / Next.js → 别的）。
- 引入新的运行时依赖（除非工具链必备，例如 ruff/mypy/Prettier）。
- 性能/数据库调优（与本规范无关）。
- 合并当前工作树的非重构范围改动（`06-27-audit-role-call-chain` 等），保留不动。

## Decision (ADR-lite)

**Context**: 重构范围与节奏直接决定 PR 数量、风险暴露面、与 WIP 任务的冲突概率。
**Decision**:
1. 范围 = **全 5 阶段一次性推完**（不切分任务、不断流）；PR 粒度 = **1 PR / Phase**（共 5–6 PR），每个 Phase 独立提交 / 独立可回滚。
2. 与 `06-27-audit-*` WIP 的协作 = **按文件域隔离 PR**（refactor 改的按文件不与 audit-* 交叉），两线并行不互相阻塞。
3. 重构期间**不允许**顺手修 bug（spec 明确 "no drive-by"），任何发现的小问题拆 follow-up。
**Consequences**:
- ✅ 单 PR review 边界清晰（一个 Phase 一个心智模型），可中途暂停。
- ✅ 工具链立门在前（Phase 1），后续 Phase 都有质量门兜底。
- ⚠️ Phase 3 / 4 工作量大，需要子任务编排避免单 PR 失控。
- ⚠️ 与 WIP 任务文件域若发生意外重叠，需要协调者裁决（不归本任务处理）。

## Technical Notes

- 参考文件：
  - 后端 spec：`.trellis/spec/vibe-kanban/backend/{index,directory-structure,database-guidelines,error-handling,quality-guidelines,logging-guidelines}.md`
  - 前端 spec：`.trellis/spec/vibe-kanban/frontend/{index,directory-structure,component-guidelines,hook-guidelines,state-management,quality-guidelines,type-safety}.md`
  - 顶层：`CLAUDE.md`（含 gotchas/env 规约/stack）
  - 详细计划：`REFACTORING_PLAN.md`（已有）
- 测量命令（迁移到 `REFACTORING_PLAN.md` 附录 A，本次任务开始前重跑一次确认基线数字）。
- 风险：
  - `api.py` 拆分误改路径/方法 → 每片后跑该域测试 + 路由计数核对。
  - store 拆分破坏 SQL 事务边界 → 保持 `AsyncSqliteStore` 单类型，组合优于继承。
  - tsconfig 收紧引发海量报错 → Phase 1 冻结 baseline，Phase 5 渐进清零。
  - 与他人未提交改动冲突 → 按文件域分小 PR，不回滚他人改动。
- 关键决策：使用 `mypy --strict` 仅对 `app/`，`tests/` 渐进（spec 默认态度）。
