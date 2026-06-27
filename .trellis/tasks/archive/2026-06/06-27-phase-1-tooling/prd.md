# Phase 1 — 工具链立门 + baseline 冻结

## Goal

把"业界最标准"的工程规范落地为机器可执行的质量门：后端 ruff + mypy strict；前端 Prettier + 严格 tsconfig；CI 必须强制执行。

存量违规建立 baseline（freeze）但不要求本 PR 清零——清零属 Phase 5。本 PR 引入工具 + 跑通 + 立 baseline。

## What I already know

- 父任务决议：1 PR / Phase；与 WIP 按文件域隔离。
- 后端现状（来自 `REFACTORING_PLAN.md`）：
  - 无 `pyproject.toml`；用 `pytest.ini` + `requirements.txt`。
  - venv 在 `backend/.venv/`。
  - 94 个 Python 模块 / 39.7k 行。
- 前端现状：
  - `next.config.ts` 设了 `eslint.ignoreDuringBuilds: true`。
  - tsconfig 缺 `noUncheckedIndexedAccess` / `forceConsistentCasingInFileNames` / `verbatimModuleSyntax` / `noFallthroughCasesInSwitch` / `noImplicitOverride`，`target: "ES2017"`，`allowJs: true`。
  - `prettier` 未安装；无 `.prettierrc`。
- CI 现状：`.github/workflows/ci.yml` 跑 pytest + tsc + test + lint；**无 ruff/mypy/prettier**。
- 后端 spec 已有质量门清单（`quality-guidelines.md`）：`pytest -v` / `pytest tests/test_foo.py -v` / `ruff check .` / `python -c "from app.main import app"`。
- 用户"直接做完"目标：5 个剩余 Phase 一次推完。

## Assumptions (temporary)

- A1：mypy strict **仅对 `app/`**；`tests/` 渐进。
- A2：`pyproject.toml` 吸收 `pytest.ini`（`[tool.pytest.ini_options]`），删除 `pytest.ini`。
- A3：baseline 冻结策略：
  - ruff: 文件级 `# ruff: noqa` 或 `ruff check --add-noqa`。
  - mypy: 逐模块 `# type: ignore[error-code]`（带错误码）。
  - tsconfig: **不冻结**（tsconfig 收紧是基线重建，行为必为"全开 + 不冻结"，只接受现状存量通过 = Phase 1 就把全开做掉）。
- A4：Prettier 只覆盖 `frontend/src/**/*.{ts,tsx}`；不动 `node_modules` / `.next`。
- A5：CI 加新 step（ruff / mypy / prettier）但不删任何已有 step；旧 step 保留兜底。

## Open Questions

- Q1：tsconfig `allowJs: false` 前需确认无 `.js` 源文件（仓库内除 `bubble-sort-demo.html` 已删，可能还有 `index.html`）—— 自动答：搜仓库 `.js` 源。
- Q2：Prettier 配置与现有 eslint 冲突？—— auto，按既有主流推断；不行就 follow-up。
- Q3：mypy `app/` 启用 strict 后大量错误如何处理？—— 按 A3 冻结，本 Phase 不清零。

## Requirements

- R1：新增 `backend/pyproject.toml`（含 `[project]` / `[tool.ruff]` / `[tool.ruff.format]` / `[tool.mypy]` / `[tool.pytest.ini_options]`，吸收 `pytest.ini`）。
- R2：删 `backend/pytest.ini`（迁完即删）。
- R3：把 `ruff` / `mypy` 加入 venv 依赖（`requirements.txt` 或 `pyproject.toml` 的 dev 组）。
- R4：跑 `ruff check .` / `ruff format --check .` / `mypy app`，产出 baseline 文件清单；冻结存量违规。
- R5：前端引入 `prettier` + `prettier-plugin-tailwindcss`；新增 `.prettierrc` + `.prettierignore`。
- R6：`next.config.ts` 移除 `eslint.ignoreDuringBuilds: true`。
- R7：`frontend/tsconfig.json` 收紧到严格全集（`noUncheckedIndexedAccess` / `forceConsistentCasingInFileNames` / `verbatimModuleSyntax` / `noFallthroughCasesInSwitch` / `noImplicitOverride` / `target: "ES2022"` / `allowJs: false`）。
- R8：`.github/workflows/ci.yml` 增 backend ruff + mypy step，前端 prettier + tsc 严格 step。
- R9：所有质量门跑通：ruff / mypy / tsc / eslint / prettier 有 baseline 但不破绿。

## Acceptance Criteria

- [ ] AC1：`backend/pyproject.toml` 存在；`backend/pytest.ini` 已删。
- [ ] AC2：`.venv/bin/ruff check .` 跑通（exit 0 或基线 frozen）。
- [ ] AC3：`.venv/bin/mypy app` 跑通。
- [ ] AC4：`.prettierrc` + `.prettierignore` 存在；`npx prettier --check frontend/src` 跑通。
- [ ] AC5：`next.config.ts` 不再含 `eslint.ignoreDuringBuilds: true`。
- [ ] AC6：`tsconfig.json` 严格全集全开；`npx tsc --noEmit` 通过。
- [ ] AC7：CI workflow 含 ruff + mypy + prettier 步骤。
- [ ] AC8：`pytest -v` + `npm test` 仍绿（零行为变化）。
- [ ] AC9：与 WIP（`06-27-audit-*`）按文件域隔离，本 PR 改动不与 WIP 冲突。

## Definition of Done

- 单 PR；CI 上跑通新加的质量门。
- baseline 文件清单 commit 注释清楚。
- 不动业务代码（除 `next.config.ts` / `tsconfig.json` 必要收紧）。
- 与 Phase 0 同样禁止 drive-by 修 bug。

## Out of Scope

- 清零 baseline 违规（属 Phase 5）。
- 大文件结构重构（属 Phase 3/4）。
- 改 `timeouts.py` 或业务逻辑（属 Phase 2）。

## Technical Notes

- 参考：
  - `REFACTORING_PLAN.md §1`：标准规范速查（PEP 8/257/484, ruff 替代 flake8·isort·pyupgrade·bugbear, ruff format Black 兼容, mypy strict）。
  - 后端 spec `quality-guidelines.md`：质量门顺序 `pytest -v` → `pytest tests/test_foo.py -v` → `ruff check .` → `python -c "from app.main import app"`。
  - 父 PRD：`.trellis/tasks/06-27-refactor-backend-frontend-to-standard/prd.md`。
- 风险与缓解：
  - ruff baseline 大量违规 → `ruff check --add-noqa` 一次性冻结。
  - mypy strict 噪音大 → 逐模块 `# type: ignore[error-code]` 冻结。
  - tsconfig 全开爆红 → Phase 1 必须接受现状 = 立即清零 = 不接受 baseline，**直接逐个修到 0**。如果工程量超出 Phase 1 范围，回退到保留 baseline + 渐进。
  - Prettier 与 ESLint 格式冲突 → 优先级 Prettier（业界主流），eslint 兼容性配置。
