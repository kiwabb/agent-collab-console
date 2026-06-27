# Phase 0 — 仓库卫生

## Goal

清理仓库中与生产/测试无关的"杂质"，让仓库"一眼可信任"。零行为变化。

属于父任务 `06-27-refactor-backend-frontend-to-standard` 的 Phase 0。

## What I already know

- 待删 12 个 tracked 一次性脚本（来自 `REFACTORING_PLAN.md §0`）：
  - `check_db.py`、`check_task.py`、`debug_task_status.py`、`doctor.py`
  - `test_handshake.py`、`test_message_flow.py`
  - `bubble-sort-demo.html`、根 `index.html`（Vite 时代残留）
  - `backend/fix_syntax.py`、`backend/migrate_tests.sh`、`backend/pytest_output.txt`、`backend/verify_happy_path.py`
- 待删工作树游离文件（未 tracked，但出现在 `git status` 杂质行）：
  - `backend/:memory:`(135KB)、`backend/codex.db`、`backend/benchmark.db`、根 `console.db*`
- 现有 `.gitignore` 已经忽略部分，但缺：`backend/:memory:`、本地 `.agent-collab/` 运行态（可能需要审）。
- `README.md` 启动段需复核（Vite@5173 残留描述），与 `dev-local.sh`（前 4000 / 后 9000）对齐。
- 父任务决议：本 Phase 与 `06-27-audit-*` 无文件交集（删的都不是 audit 路径）。

## Assumptions (temporary)

- A1：删除脚本前先扫一眼确认无 CI 引用（重点 `pytest_output.txt`、`migrate_tests.sh`、`fix_syntax.py`）。
- A2：若某脚本确有诊断价值，迁到 `backend/scripts/diagnostics/` 并补 docstring；否则 `git rm`。
- A3：`.gitignore` 强化后不影响任何已 tracked 文件（已 tracked 不受 ignore 影响）。

## Open Questions

- Q1：是否对每个删掉的脚本在 commit message 中说明"为何不需要"（推荐"删除 X 个一次性脚本，理由:..."）？→ 默认是。
- Q2：若发现某脚本被 CI/测试隐式依赖，怎么处理？→ 拆 follow-up，本 PR 不修。

## Requirements

- R1：删除/迁出 12 个 tracked 一次性脚本（`git rm` 或迁 `backend/scripts/diagnostics/`）。
- R2：删除工作树游离文件（`backend/:memory:`、`codex.db`、`benchmark.db`、根 `console.db*`）。
- R3：强化 `.gitignore`：补 `backend/:memory:`、本地 `.agent-collab/`、确认 `tsconfig.tsbuildinfo` 已忽略。
- R4：复核 `README.md` 启动段，与 `dev-local.sh` 端口（4000/9000）一致；移除 Vite@5173 残留描述。

## Acceptance Criteria

- [ ] AC1：`git ls-files | rg 'check_db|doctor\.py|fix_syntax|pytest_output|bubble-sort|test_handshake|test_message_flow'` 为空。
- [ ] AC2：`ls backend/:memory: 2>/dev/null; ls backend/codex.db backend/benchmark.db 2>/dev/null; ls console.db* 2>/dev/null` 均无输出。
- [ ] AC3：`git check-ignore backend/:memory:` 返回 0（被 ignore）。
- [ ] AC4：`README.md` 启动段不出现 "5173"、"Vite"。
- [ ] AC5：`git status` 仍处于本 PR 期望的状态（无其他工作树文件新增）。
- [ ] AC6：`pytest -v` 与 `npm run build && npm run lint` 仍可通过（卫生 PR 不应破坏任何测试）。

## Definition of Done

- 单 PR，提交 message 列出删除清单与理由。
- 不动业务代码、不动测试代码、不改 spec。
- 与父任务 DoD 对齐：零行为变化；任何发现的小问题走 follow-up。

## Out of Scope

- 业务行为变更（spec 明确 no drive-by）。
- 引入 ruff/mypy/Prettier（属 Phase 1）。
- 改 `timeouts.py` / API / 任何 store（属 Phase 2/3）。
- 处理 `06-27-audit-*` WIP 任务（按文件域隔离，不动）。

## Technical Notes

- 参考：
  - 父 PRD：`.trellis/tasks/06-27-refactor-backend-frontend-to-standard/prd.md`
  - 后端 spec：`.trellis/spec/vibe-kanban/backend/quality-guidelines.md`（确认"no drive-by"）
  - 顶层：`CLAUDE.md`（确认 dev-local.sh 端口）
- 操作顺序建议：
  1. 跑 `git ls-files | rg <pattern>` 列出 12 个待删文件，确认无遗漏。
  2. 对每个文件 grep `pytest|test_` 关键字确认无测试引用。
  3. `git rm` 一次性脚本（保留 `backend/` 子目录的做迁移候选）。
  4. 直接 `rm` 工作树游离文件（未 tracked，不入 commit，靠 `.gitignore` 防再生）。
  5. 改 `.gitignore`（增量，不重写）。
  6. 改 `README.md`（局部）。
  7. 跑 `git status` 复核；跑 `pytest -v` / `npm run build && npm run lint` 验证。
- 风险：极低；纯删除/配置。
