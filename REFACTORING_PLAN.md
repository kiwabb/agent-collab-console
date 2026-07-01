# 代码重构计划 / Code Refactoring Plan

> 目标：按照业界最标准的代码规范，重构本仓库（`agent-collab-console`）前后端代码。
> 基于对当前工作树的真实审计（文件、行数、配置、违规计数），所有发现均有证据支撑。
>
> 适用范围：`backend/`（FastAPI + aiosqlite，Python 3.13）与 `frontend/`（Next.js 15 + React 18 + Tailwind v4 + Base UI）。
> 已有 Trellis 规范（`.trellis/spec/vibe-kanban/`）是"事实约定"来源，本计划与之对齐，不另起炉灶。

---

## 0. 审计基线（Current State Audit）

下表为真实度量结果，作为重构前后对比的基线。

| 维度 | 现状（证据） | 标准 |
|---|---|---|
| 后端体量 | `backend/app` 39,750 行 / 94 模块；`backend/tests` 28,385 行 | — |
| 前端体量 | `frontend/src` 50,689 行（ts/tsx） | — |
| Python 工具链 | **无 `pyproject.toml`**；仅有 `pytest.ini` + `requirements.txt`（宽下界，无锁）；venv 未安装 ruff/mypy/black/isort | `pyproject.toml` 统一管理 + ruff + ruff-format + mypy(strict) |
| `__future__` 注解 | 仅 58/94 模块含 `from __future__ import annotations`（约 36 模块缺失） | 每个模块顶部必备（见 backend spec） |
| 环境变量直读 | **67 处 `os.getenv` 在 `timeouts.py` 之外**（违反 spec：仅 `timeouts.py` 可读 env） | 0 处违规；全部走 `timeouts.*()` accessor |
| 前端构建 lint | `next.config.ts` 设 `eslint.ignoreDuringBuilds: true`（构建期跳过 lint） | 构建期必须 lint |
| 前端格式化 | 无 Prettier 配置/依赖 | Prettier 统一格式 |
| tsconfig | `target: "ES2017"`、`allowJs: true`；缺 `noUncheckedIndexedAccess`/`forceConsistentCasingInFileNames`/`verbatimModuleSyntax` | `target: "ES2022"`、`allowJs: false`、严格全集 |
| 前端类型逃逸 | `any` 约 23 处；`console.log` 散落 8 个文件 | 0 `any`；无 `console.log` 进生产 |
| CI | `.github/workflows/ci.yml` 跑 pytest + tsc + test + lint；**无 ruff/mypy** | CI 含 ruff + mypy + 前端完整质量门 |
| 超大文件（后端） | `interfaces/api.py` **7895 行 / 185 路由**；`adapters/async_sqlite_store.py` 3517；`adapters/sqlite_store.py` 2540；`conductor_main_loop.py` 1451；`process_runtime_common.py` 1438 | 单文件宜 < ~800 行；按资源拆分 |
| 超大文件（前端） | `lib/i18n.ts` 3606；`lib/api.ts` 2083；`features/skills/SkillsLibraryPage.tsx` 1412；`lib/types.ts` 1014 | 同上；按域拆分 |
| 仓库杂质 | 12 个 tracked 一次性脚本（`check_db.py`/`check_task.py`/`debug_task_status.py`/`doctor.py`/`test_handshake.py`/`test_message_flow.py`/`bubble-sort-demo.html`/根 `index.html`/`backend/fix_syntax.py`/`backend/migrate_tests.sh`/`backend/pytest_output.txt`/`backend/verify_happy_path.py`）；工作树含 `backend/:memory:`(135KB)/`backend/codex.db`/`benchmark.db` 等游离文件 | 仓库仅保留生产/测试代码 |
| 文档漂移 | `README.md` 曾描述 Vite@5173（现 Next@4000），需复核 | 文档与实际端口/栈一致 |

> 测量命令见文末「附录 A」。

---

## 1. 标准规范基线（What "最标准的代码规范" Means Here）

不发明新风格，锚定业界事实标准，并与项目现有 Trellis spec 对齐。

**Python（后端）**
- PEP 8（风格）、PEP 257（docstring）、PEP 484/526（类型注解）、现代实践。
- 工具：`ruff check`（替代 flake8 + isort + pyupgrade + bugbear）+ `ruff format`（Black 兼容输出）+ `mypy --strict`（app 目录）。
- 配置归口：`backend/pyproject.toml`（`[tool.ruff]` / `[tool.mypy]` / `[tool.pytest.ini_options]`），废弃散落的 `pytest.ini`。
- 既有约定（来自 `.trellis/spec/vibe-kanban/backend/`，必须遵守）：
  - 每个模块顶部 `from __future__ import annotations`。
  - env 仅 `application/timeouts.py` 的 `validate()` 可读，余者走 accessor。
  - store 是唯一写 SQL 处；服务不手搓查询。
  - 服务不 import `interfaces/`、不 `raise HTTPException`（用类型化错误，transport 层映射状态码）。
  - 后台协程在 loop boundary catch，失败落 `failed` 行 + traceback。

**TypeScript/React（前端）**
- ESLint `typescript-eslint` strict/recommended + `eslint-config-next`；Prettier 统一格式。
- `tsconfig.json` 严格全集：`strict`、`noUncheckedIndexedAccess`、`forceConsistentCasingInFileNames`、`verbatimModuleSyntax`、`noFallthroughCasesInSwitch`、`noImplicitOverride`、`target: "ES2022"`、`allowJs: false`。
- 既有约定（来自 `.trellis/spec/vibe-kanban/frontend/`）：hooks 纯净、组件按域目录、状态走 zustand/store、类型端到端无 `any`。

---

## 2. 重构原则与约束

1. **行为保持**：重构不改对外语义。每一步后跑全量测试（后端 `pytest -v`、前端 `npm test` + `tsc --noEmit` + `npm run lint`）确认绿灯。不允许"重构与修 bug 混做"。
2. **小步、可回滚**：每个 Phase 独立可提交；单 PR 触及一个面。大文件拆分按资源切片，逐片迁移、逐片验证。
3. **先立工具，再动结构**：先引入 ruff/mypy/prettier 并跑出基线（必要时先用 `# noqa`/baseline 冻结存量违规，后续逐步消除），避免一边重构一边被海量历史告警淹没。
4. **不回滚他人改动**：当前工作树有未提交的 `06-27-audit-role-call-chain` 任务改动，这些不属于本重构范围，保留不动。
5. **以 spec 为准绳**：所有"对/错"判定引用 `.trellis/spec/`，不凭感觉。

---

## 3. 分阶段计划（Phased Plan）

### Phase 0 — 仓库卫生与文档对齐（Repo Hygiene）

**目标**：清掉与生产无关的杂质，让仓库"一眼可信任"。

**任务**
- 删除/迁出 12 个 tracked 一次性脚本：`check_db.py`、`check_task.py`、`debug_task_status.py`、`doctor.py`、`test_handshake.py`、`test_message_flow.py`、`bubble-sort-demo.html`、根 `index.html`（Vite 时代残留）、`backend/fix_syntax.py`、`backend/migrate_tests.sh`、`backend/pytest_output.txt`、`backend/verify_happy_path.py`。
  - 若确有诊断价值，迁移到 `backend/scripts/diagnostics/` 并补类型/docstring；否则直接 `git rm`。
- 删除工作树游离文件：`backend/:memory:`、`backend/codex.db`、`backend/benchmark.db`、根 `console.db*`。
- 强化 `.gitignore`：补 `backend/:memory:`、`**/*.tsbuildinfo`（确认 `tsconfig.tsbuildinfo` 已忽略）、本地 `.agent-collab/` 运行态。
- 复核 `README.md`：端口/栈/启动命令须与 `dev-local.sh`（前 4000 / 后 9000）一致；移除 Vite@5173 残留描述。

**验收**
- `git ls-files | rg 'check_db|doctor\.py|fix_syntax|pytest_output|bubble-sort|test_handshake|test_message_flow'` 为空。
- `README.md` 启动段与 `dev-local.sh` 端口一致。

---

### Phase 1 — 工具链标准化（Tooling Standardization）

**目标**：把"标准规范"做成机器可执行的门，而不是口头约定。

**后端**
- 新建 `backend/pyproject.toml`：
  - `[project]` 元数据 + 依赖（吸收 `requirements.txt`，改为带上下界；保留 `requirements.txt` 作为 CI 兼容入口或生成产物）。
  - `[tool.ruff]`：`line-length = 100`、`target-version = "py313"`、`select` 启用 `E/F/W/I/UP/B/SIM/RUF`，`[tool.ruff.format]` 用默认（Black 风格）。
  - `[tool.mypy]`：`strict = true`、`mypy_path`，对 `tests/` 放宽至 `disallow_untyped_defs = false`（测试可渐进）。
  - `[tool.pytest.ini_options]`：吸收 `pytest.ini`（`asyncio_mode = auto`、`addopts = -m "not slow"`、`markers`）。
- 在 venv 安装 `ruff`、`mypy`，加入 `requirements.txt` 的 dev 组（或 `requirements-dev.txt`）。
- 跑 `ruff check .` 与 `ruff format --check .` 建立基线；存量违规先用 `ruff check --add-noqa` 冻结或文件级 `# ruff: noqa`，列入 Phase 5 清零。
- 跑 `mypy --strict app` 建立基线；用逐模块 `# type: ignore[...]`（带错误码）冻结。

**前端**
- 引入 Prettier：`prettier` + `prettier-plugin-tailwindcss` 加入 devDeps；新增 `.prettierrc`（`printWidth: 100`、`semi: true`、`singleQuote` 视现有代码主流确认）与 `.prettierignore`（`node_modules`、`.next`）。
- `next.config.ts`：移除 `eslint.ignoreDuringBuilds = true`。
- 收紧 `tsconfig.json`：`target: "ES2022"`、`allowJs: false`、新增 `noUncheckedIndexedAccess`、`forceConsistentCasingInFileNames`、`verbatimModuleSyntax`、`noFallthroughCasesInSwitch`、`noImplicitOverride`。
- 跑 `npx prettier --check .` 与 `npx tsc --noEmit` 建立基线；新告警记入 Phase 5。

**CI 加固**
- `.github/workflows/ci.yml`：backend job 增 `ruff check .`、`ruff format --check .`、`mypy app`；frontend job 改 `npm run lint` 为非跳过、增 `prettier --check`。
- 本地统一：`make lint`/`make typecheck`/`make test`（可选 Makefile）。

**验收**
- `backend/.venv/bin/ruff check .` 有基线（已冻结）。
- `backend/.venv/bin/mypy app` 有基线文件。
- `npx tsc --noEmit` 在收紧 tsconfig 后仍绿（或已登记告警）。
- CI workflow 含 ruff/mypy/prettier 步骤。

---

### Phase 2 — 既有约定回归（Convention Regression Fixes）

**目标**：消除已记录 spec 的明确违规，零行为变化。

**后端**
- `from __future__ import annotations` 全覆盖：对剩余约 36 个模块补齐（逐文件 review 不破坏 docstring/`__all__`）。
- 消除 `os.getenv` 泄漏：67 处 → 0。策略：
  1. 审计每处调用，判断是否应进 `timeouts.py`（绝大多数是配置旋钮）。
  2. 在 `timeouts.py` 加 accessor（如 `timeouts.real_cli_enabled()`、`timeouts.codex_launch_enabled()`、`timeouts.cost_usd_per_m_input()` 等），`validate()` 做不变量校验。
  3. 替换调用点为 accessor；`timeouts.py` 之外 `os.getenv` 设为禁止（lint guard）。
  - 特例：诊断端点暴露"是否配置"的布尔（`api_key_configured`）本就允许 `bool(os.getenv(...))`，归一到一个 `timeouts`/`config` accessor 更干净。
- 服务层不 import `interfaces/`、不 `raise HTTPException`：扫描 `rg "from app.interfaces" backend/app/application` 与 `rg "raise HTTPException" backend/app/application`，逐处改为类型化错误 + transport 映射。

**前端**
- 清零 `console.log`（8 文件）：生产代码改 logger 或删除。
- 消除 `any`（~23 处）：改为窄联合/`unknown` + type guard/泛型。配 `@typescript-eslint/no-explicit-any` 规则为 `error`。

**验收**
- `rg "os\.getenv" backend/app | rg -v timeouts.py` 为空。
- `rg "from app.interfaces" backend/app/application` 为空。
- `rg "\bany\b" frontend/src`（按类型位）为 0。
- `rg "console\.(log|warn|error)" frontend/src` 为空或仅 error-boundary。

---

### Phase 3 — 后端结构重构（Backend Structural Refactor）

**目标**：拆解超大模块，恢复可读、可测、可审的粒度。行为不变。

**3.1 `interfaces/api.py`（7895 行 / 185 路由）按资源域拆分**
- 目标结构：`backend/app/interfaces/routers/<domain>.py`，每个 router 文件 < ~600 行。
- 建议域划分（按现有路由分组）：
  - `routers/issues.py`、`routers/tasks.py`、`routers/projects.py`、`routers/prototypes.py`、`routers/audit.py`、`routers/runtime_catalog.py`、`routers/diagnostics.py`、`routers/skills.py`、`routers/agents.py`、`routers/approvals.py`、`routers/conductors.py`、`routers/knowledge.py`、`routers/benchmarks.py`、`routers/self_improvement.py`、`routers/ws.py`（或保留 `codex_ws.py`）。
- 共享：`interfaces/errors.py`（`APIError`/`NotFoundError`/... 已在 api.py 顶部，抽出）、`interfaces/dependencies.py`（bootstrap 注入的依赖）、`interfaces/serialization.py`（行 → dict 的派生 helper）。
- `api.py` 收缩为 router 聚合 + 全局异常处理器注册（`main.py` 已有 handler 注册，保持）。
- 每片迁移：移动路由 → 跑该域测试 → 提交。整体完成后 `pytest -v` 全绿。
- 路由总数核对：`rg -c "@router\.(get|post|put|patch|delete)" backend/app/interfaces/api.py` 当前 185，拆分后须不变。

**3.2 `adapters/async_sqlite_store.py`（3517）/ `sqlite_store.py`（2540）按聚合根拆分**
- store 现为单巨型类。按聚合根拆为 mixin 或独立类，组合进顶层 `AsyncSqliteStore`：
  - `stores/issues.py`、`stores/tasks.py`、`stores/projects.py`、`stores/conductor.py`、`stores/audit.py`、`stores/workflow.py`、`stores/prototypes.py`、`stores/knowledge.py`、`stores/migrations.py`（schema/migrate 集中）。
- 保持对外 `AsyncSqliteStore` 单一类型不变（组合优于继承），调用方零改动。
- 同步 `sqlite_store.py`（测试用）镜像拆分或保留薄壳。

**3.3 `application/conductor_main_loop.py`（1451）/ `process_runtime_common.py`（1438）**
- `conductor_main_loop`：抽出 `LEGAL_TRANSITIONS`/状态机到 `conductor_state_machine.py`；prompt 组装到纯 helper（spec 要求"prompt assembly in a pure helper that tests can assert directly"）；loop 主体保留编排。
- `process_runtime_common`：按 runtime 类型（codex/claude）拆分共性到更小模块。

**3.4 通用**
- 函数过长（> ~80 行）/ 过深嵌套：抽 helper。spec 明确"no 9-prop god functions, no nested ternaries"。
- 重复 SQL/序列化 boilerplate：抽到 store/serialization helper。

**验收**
- `wc -l backend/app/interfaces/api.py` < ~800（仅聚合 + handler）。
- 每个新 router 文件 < ~700 行。
- `pytest -v` 全绿；`test_conductor_state_machine.py` 等既有测试不被动。
- `mypy app` 与 `ruff check` 无新增违规。

---

### Phase 4 — 前端结构重构（Frontend Structural Refactor）

**4.1 `lib/i18n.ts`（3606）拆分**
- 现为单巨型 `dictionaries` 对象。改为按 locale 拆文件：`lib/i18n/zh-CN.ts`、`lib/i18n/en-US.ts`，`lib/i18n/index.ts` 聚合并导出 `useI18n`/`t`。
- 或更进一步按域分 namespace（`nav`/`settings`/`issue`/...），按需加载（Next 动态 import）。
- 行为不变：key 集合与 `t()` 签名保持。

**4.2 `lib/api.ts`（2083）拆分**
- 按域拆 `lib/api/<domain>.ts`（issues/tasks/projects/...），`lib/api/index.ts` 聚合。类型来自 `lib/types.ts`。

**4.3 `lib/types.ts`（1014）拆分**
- 按域拆 `lib/types/<domain>.ts`，减少单文件认知负担。

**4.4 大组件拆分**
- `SkillsLibraryPage.tsx`（1412）、`ProjectWorkspacesPage.tsx`（1075）、`ConductorLogPanel.tsx`（992）、`InboxDashboard.tsx`（984）等：抽子组件与自定义 hook（`use*`），单组件 < ~400 行。遵循 frontend spec 的 component/hook guidelines。

**验收**
- `wc -l frontend/src/lib/i18n.ts`（聚合后）< ~200；各 locale 文件可独立编辑。
- `npx tsc --noEmit` + `npm test` + `npm run lint` 全绿。

---

### Phase 5 — 类型与质量门清零（Type & Lint Baseline Burn-down）

**目标**：把 Phase 1 冻结的存量违规逐项清零，最终"标准规范"全量硬执行。

- mypy strict：逐模块消除 `# type: ignore`，目标 `app/` 零 ignore（或仅带明确错误码的极少例外）。
- ruff：移除所有 `# noqa`，`ruff check .` 零告警。
- tsconfig：逐步收紧到 `noUncheckedIndexedAccess` 等全开且无新告警。
- `@typescript-eslint/no-explicit-any` 设 `error` 且零违反。
- 把质量门写入 PR 模板/CI，新增违规即红。

**验收**
- `ruff check .` 退出 0；`mypy app` 退出 0；`tsc --noEmit` 退出 0；`eslint` 退出 0。

---

## 4. 风险与回滚

| 风险 | 缓解 |
|---|---|
| 拆 `api.py` 误改路由路径/方法 | 拆分只移动不改语义；每片后跑该域测试 + `pytest -v`；用 `rg "@router\.(get|post)"` 核对路由总数 185 不变 |
| store 拆分破坏 SQL 事务边界 | 保持 `AsyncSqliteStore` 单类型；迁移测试覆盖 legacy 行（spec 要求）；`test_issue_budget.py::test_sync_store_migrates_legacy...` 为样板 |
| tsconfig 收紧引发海量报错 | Phase 1 先建基线冻结，Phase 5 渐进清零；`allowJs:false` 前确认无 `.js` 源文件 |
| mypy strict 在动态代码上噪音大 | 先 `--strict` on `app/`，`tests/` 渐进；逐模块启用 |
| 重构期间与他人改动冲突 | 不回滚 `06-27-audit-role-call-chain` 等在途改动；按文件域分小 PR |
| 行为回归未被发现 | 每个 Phase 结束跑全量测试 + 导入烟雾检查 `python -c "from app.main import app"` |

---

## 5. 执行顺序与里程碑

1. **Phase 0**（卫生）→ 低风险，先做，立即提升可信任度。
2. **Phase 1**（工具链）→ 立门；基线冻结。
3. **Phase 2**（约定回归）→ 零行为变化的纯整改，配合工具门最易推进。
4. **Phase 3**（后端结构）→ 按 3.1 → 3.2 → 3.3 顺序，每步独立验证。
5. **Phase 4**（前端结构）→ 可与 Phase 3 并行（不同子树）。
6. **Phase 5**（清零）→ 最后收口，标准全量硬执行。

每个 Phase 完成后：更新本文件对应验收勾选状态，并在 `.trellis/` 记录任务进度。

---

## 附录 A — 审计测量命令

```bash
# 后端体量/超大文件
rg --files backend/app --type py | xargs wc -l | sort -rn | head -16
rg --files backend/tests --type py | xargs wc -l | tail -1

# 前端体量/超大文件
rg --files frontend/src -g '*.ts' -g '*.tsx' | xargs wc -l | sort -rn | head -13

# __future__ 覆盖
rg -l "from __future__ import annotations" backend/app --type py | wc -l   # 58/94

# env 直读违规
rg -n "os\.getenv" backend/app --type py | rg -v timeouts.py | wc -l      # 67

# api.py 路由数
rg -c "@router\.(get|post|put|patch|delete)" backend/app/interfaces/api.py

# 前端 any / console
rg -n "\bany\b" frontend/src -g '*.ts' -g '*.tsx' | rg ":\s*any|as any|<any>"
rg -c "console\.(log|warn|error)" frontend/src -g '*.ts' -g '*.tsx'

# tracked 杂质
git ls-files -- check_db.py check_task.py debug_task_status.py doctor.py \
  test_handshake.py test_message_flow.py bubble-sort-demo.html index.html \
  backend/fix_syntax.py backend/verify_happy_path.py backend/migrate_tests.sh \
  backend/pytest_output.txt
```

---

## 附录 B — 标准规范速查

**Python**：PEP 8 / PEP 257 / PEP 484 + ruff(替代 flake8·isort·pyupgrade·bugbear) + ruff format(Black 兼容) + mypy strict；配置归 `pyproject.toml`。
**TypeScript/React**：typescript-eslint strict + eslint-config-next + Prettier + tsconfig 严格全集（strict/noUncheckedIndexedAccess/forceConsistentCasingInFileNames/verbatimModuleSyntax）。
**项目自有约定**：`.trellis/spec/vibe-kanban/backend|frontend/`（事实约定，权威）。
