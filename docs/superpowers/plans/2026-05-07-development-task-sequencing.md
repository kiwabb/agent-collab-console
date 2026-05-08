# 开发任务顺序化与串行解锁实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把当前 `architecture -> development` 只做“批量建并列 engineer tasks”的实现，升级成 MetaGPT 风格的顺序开发流。

**Architecture:** 保持现有四个 issue phase 不变，不新增可见阶段；由 Architect 在架构阶段同时产出 `implementation_plan.json` 和 `development_task_list.json`。`transition-to-development` 只负责校验这两份产物、创建带顺序元数据的 development tasks，并让开发任务严格串行解锁：前一个未完成，后一个不能运行。

**Tech Stack:** FastAPI, Pydantic, SQLite store, React, TypeScript, node:test, pytest

---

## File Structure

### Backend

- Modify: `backend/app/application/architect_workflow.py`
  - 扩展 Architect 输出 schema，新增 `development_task_list`
  - 持久化 `development_task_list.json`
- Modify: `backend/app/application/issue_artifact_documents.py`
  - 增加 `development_task_list.json` 的路径 helper
- Modify: `backend/app/domain/models.py`
  - 为 `CodexTask` 增加开发顺序字段
- Modify: `backend/app/interfaces/api.py`
  - 扩展 `transition-to-development` 的校验与任务创建
  - 在 `run_codex_task` 中增加 development 串行校验
- Modify or Create tests:
  - `backend/tests/test_architect_workflow.py`
  - `backend/tests/test_issue_transition_to_development.py`
  - `backend/tests/test_codex_tasks.py` 或更贴近运行入口的现有测试文件

### Frontend

- Modify: `frontend/src/lib/types.ts`
  - 扩展 `CodexTask` 顺序字段
- Modify: `frontend/src/features/tasks/TaskBoard.tsx`
  - development 列按顺序展示，并显示解锁状态
- Modify: `frontend/src/features/workbench/WorkbenchPage.tsx`
  - 计算开发任务是否已解锁，并把状态传给详情面板/运行入口
- Modify: `frontend/src/features/runs/RunDetail.tsx`
  - 未解锁任务禁用首次运行并展示原因
- Modify: `frontend/src/lib/i18n.ts`
  - 新增顺序与阻塞原因文案
- Modify tests:
  - `frontend/tests/workbenchActions.test.ts`
  - 与运行详情或任务排序相关的现有测试文件

## Behavior Contract

- Architect 必须同时产出：
  - `implementation_plan.json`
  - `development_task_list.json`
- `development_task_list.json` 是开发顺序权威来源，不再依赖 `implementation_plan.json` 的数组顺序。
- `development_task_list.json` 的内容是字符串数组，每项是一个 implementation task title，且必须：
  - 非空
  - 不重复
  - 完整覆盖 `implementation_plan.json` 中的全部 task title
  - 不允许出现 `implementation_plan.json` 中不存在的 title
- `transition-to-development` 只允许在：
  - issue `current_phase == "architecture"`
  - 无运行中任务
  - `system_design.json`、`implementation_plan.json`、`development_task_list.json` 都存在且有效
  时执行。
- development task 创建规则：
  - `phase = "development"`
  - `role = "engineer"`
  - `executor = "codex"`
  - `title = "开发 - {issue.title} - {item.title}"`
  - `prompt` 继续基于 item title / description / priority 生成
  - `sequence_index = 0..n-1`
  - `sequence_group = issue.id`
- 顺序运行规则：
  - `sequence_index == 0` 的 development task 可直接运行
  - `sequence_index > 0` 的 development task 只有在同 `sequence_group` 中前一个 task 状态为 `done` 时才可运行
  - 不实现 DAG，不支持跳步执行
  - 不自动运行下一任务，只做“解锁”
- 非 development task 不受该顺序约束。
- 重复流转仍然去重，不重复创建 task，且复用 task 时顺序元数据必须保持一致。

## Task 1: 锁定顺序化契约测试

**Files:**
- Modify: `backend/tests/test_issue_transition_to_development.py`
- Modify: `backend/tests/test_architect_workflow.py`
- Modify: `backend/tests/test_codex_tasks.py` 或现有运行入口测试文件

- [ ] **Step 1: 为 Architect 新产物写失败测试**

验证：
- Architect 成功持久化 `development_task_list.json`
- `development_task_list` 缺失、重复、缺项、未知标题时，持久化或校验失败

- [ ] **Step 2: 为开发流转顺序字段写失败测试**

验证：
- 缺失 `development_task_list.json` 返回 409
- 成功流转时返回的 tasks 顺序与 `development_task_list.json` 一致
- 每个返回 task 都有正确的 `sequence_index` 和 `sequence_group`

- [ ] **Step 3: 为运行串行约束写失败测试**

验证：
- 第一个 development task 可运行
- 第二个 development task 在第一个未 `done` 时运行返回 409
- 第一个 `done` 后第二个可运行
- requirements / architecture / testing task 不受该约束

- [ ] **Step 4: 运行相关后端测试，确认 RED**

Run:

```bash
cd backend && PYTHONPATH=. ./.venv/bin/pytest tests/test_issue_transition_to_development.py tests/test_architect_workflow.py tests/test_codex_tasks.py -q
```

Expected: 至少新增顺序化相关断言失败。

## Task 2: 扩展 Architect 输出与产物落盘

**Files:**
- Modify: `backend/app/application/architect_workflow.py`
- Modify: `backend/app/application/issue_artifact_documents.py`
- Modify: `backend/tests/test_architect_workflow.py`

- [ ] **Step 1: 为开发任务清单增加路径 helper**

新增 `development_task_list.json` 对应路径 helper，并纳入 issue artifact 管理。

- [ ] **Step 2: 扩展 Architect 输出 schema**

把 required schema 从：

```json
"implementation_tasks": [{"title": "string", "description": "string", "priority": "P0|P1|P2"}]
```

扩展为同时要求：

```json
"implementation_tasks": [{"title": "string", "description": "string", "priority": "P0|P1|P2"}],
"development_task_list": ["string"]
```

- [ ] **Step 3: 在 persist_result 中校验 development_task_list**

固定校验：
- 非空
- 不重复
- 与 `implementation_tasks.title` 完全一致，仅顺序可不同

失败时抛明确 `ArchitectWorkflowError`。

- [ ] **Step 4: 持久化 `development_task_list.json`**

文件内容直接为有序 title 数组 JSON。

- [ ] **Step 5: 运行 Architect 相关测试，确认 GREEN**

Run:

```bash
cd backend && PYTHONPATH=. ./.venv/bin/pytest tests/test_architect_workflow.py -q
```

Expected: PASS

## Task 3: 后端开发流转顺序化

**Files:**
- Modify: `backend/app/domain/models.py`
- Modify: `backend/app/interfaces/api.py`
- Modify: `backend/tests/test_issue_transition_to_development.py`

- [ ] **Step 1: 为 `CodexTask` 增加顺序字段**

新增：

```python
sequence_index: int | None = None
sequence_group: str | None = None
```

- [ ] **Step 2: 在 API 层增加 `development_task_list.json` 读取与校验 helper**

职责：
- 读取 title 数组
- 校验非空、无重复
- 校验与 implementation tasks 完全匹配
- 返回按清单顺序排好的 implementation items

- [ ] **Step 3: 更新 `transition-to-development` 创建逻辑**

创建/复用 task 时写入：
- `sequence_index`
- `sequence_group = issue.id`

并确保返回 tasks 顺序与清单一致。

- [ ] **Step 4: 保持原有 phase 契约与去重逻辑**

仍然只允许 `architecture -> development`，不新增 `development` 成功分支，不扩 scope。

- [ ] **Step 5: 运行开发流转测试，确认 GREEN**

Run:

```bash
cd backend && PYTHONPATH=. ./.venv/bin/pytest tests/test_issue_transition_to_development.py -q
```

Expected: PASS

## Task 4: 后端运行时串行解锁

**Files:**
- Modify: `backend/app/interfaces/api.py`
- Modify: 运行入口对应测试文件，例如 `backend/tests/test_codex_tasks.py`

- [ ] **Step 1: 在 `run_codex_task` 前增加顺序检查**

规则：
- 仅对 `phase == "development"` 且 `sequence_index is not None` 的 task 生效
- `sequence_index == 0` 直接放行
- 其余情况找到同 `sequence_group` 且 `sequence_index == current - 1` 的 task
- 若前序任务状态不是 `done`，返回 409

- [ ] **Step 2: 固定 409 错误文案**

文案应明确说明需要先完成上一个开发任务，避免用户只看到“不能运行”。

- [ ] **Step 3: 运行运行时约束测试，确认 GREEN**

Run:

```bash
cd backend && PYTHONPATH=. ./.venv/bin/pytest tests/test_codex_tasks.py -q
```

Expected: PASS

## Task 5: 前端顺序展示与阻塞交互

**Files:**
- Modify: `frontend/src/lib/types.ts`
- Modify: `frontend/src/features/tasks/TaskBoard.tsx`
- Modify: `frontend/src/features/workbench/WorkbenchPage.tsx`
- Modify: `frontend/src/features/runs/RunDetail.tsx`
- Modify: `frontend/src/lib/i18n.ts`
- Modify: frontend tests covering task sorting / run gating

- [ ] **Step 1: 扩展前端 `CodexTask` 类型**

新增：
- `sequence_index?: number | null`
- `sequence_group?: string | null`

- [ ] **Step 2: development 列按顺序展示**

仅 development phase task 使用 `sequence_index` 升序排序；其余 phase 保持现状。

- [ ] **Step 3: 计算开发任务是否已解锁**

规则与后端保持一致：
- 第一条解锁
- 其余依赖前序 task `done`

前端此计算只用于展示和禁用，不替代后端校验。

- [ ] **Step 4: 在任务卡与详情中展示顺序/阻塞状态**

至少包含：
- 顺序编号，如 `#1`
- 未解锁原因，如“需先完成上一个开发任务”

- [ ] **Step 5: 禁用未解锁任务的首次运行入口**

`RunDetail` 中 pending development task 若未解锁：
- 禁用运行按钮
- 展示明确原因

- [ ] **Step 6: 运行前端测试，确认 GREEN**

Run:

```bash
cd frontend && npm test
```

Expected: PASS

## Task 6: 端到端验证

**Files:**
- Verify existing backend/frontend changes only

- [ ] **Step 1: 运行后端相关测试**

Run:

```bash
cd backend && PYTHONPATH=. ./.venv/bin/pytest tests/test_issue_transition_to_development.py tests/test_architect_workflow.py tests/test_codex_tasks.py -q
```

Expected: PASS

- [ ] **Step 2: 运行前端测试**

Run:

```bash
cd frontend && npm test
```

Expected: PASS

- [ ] **Step 3: 手工链路验证**

1. 完成一次架构任务，确认生成：
   - `implementation_plan.json`
   - `development_task_list.json`
2. 点击 `流转到开发`
3. 验证 development tasks 数量与顺序清单一致
4. 验证只有第一个任务可运行
5. 尝试运行第二个任务，验证被阻止
6. 完成第一个任务后，验证第二个任务解锁
7. 重复流转，验证不重复建任务

- [ ] **Step 4: Scope 审核**

Task 6 只做验证，不允许：
- 修改 phase 契约
- 新增额外成功分支
- 修改非本计划要求的后端行为

## Assumptions

- 不新增 ProjectManager 可见阶段。
- 不实现通用依赖图，只实现 MetaGPT 风格的线性顺序列表。
- 顺序权威来源是 `development_task_list.json`，不是 `implementation_plan.json` 的数组位置。
- `development_task_list.json` 由 Architect 直接产出，不在流转时派生。
- 开发任务标题继续沿用 `开发 - {issue.title} - {item.title}`，便于复用现有去重逻辑。
