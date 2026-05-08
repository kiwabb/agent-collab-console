# 重新运行支持选择执行器计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让右侧任务详情里的运行入口支持临时切换执行器。

**Architecture:** 采用“原任务切执行器”模型：用户在 `重新运行` 或首次运行时选择 `Codex` / `Claude Code`，前端先把该 task 的 `executor` 更新到后端，再调用现有 `run` 接口启动同一个 task。这样不新增任务，不拆散历史，运行记录仍挂在原 task 下。

**Tech Stack:** FastAPI, Pydantic, SQLite store, React, TypeScript, node:test, pytest

---

## File Structure

### Backend

- Modify: `backend/app/interfaces/api.py`
  - 新增轻量 task 更新接口，只允许更新 `executor`
- Modify: backend task API tests
  - 为 task 更新接口和运行联动补测试

### Frontend

- Modify: `frontend/src/lib/types.ts`
  - 增加 task 更新请求类型
- Modify: `frontend/src/lib/api.ts`
  - 增加更新 task executor 的 API 方法
- Modify: `frontend/src/features/runs/RunDetail.tsx`
  - 运行区加入执行器选择控件
- Modify: `frontend/src/features/workbench/WorkbenchPage.tsx`
  - 在首次运行/重新运行前先更新 executor，再启动任务
- Modify: frontend tests
  - 锁住执行器切换和运行联动行为

## Behavior Contract

- 只改右侧详情运行入口：
  - `重新运行`
  - pending / failed task 的首次运行
- 不改 phase 列头 `+` 的行为；它继续沿用当前已有执行器选择逻辑。
- 切换执行器不新建 task，只更新原 task 的 `executor` 字段。
- 推荐新增接口：
  - `PATCH /api/codex/tasks/{task_id}`
  - request body: `{ "executor": "codex" | "claude" }`
- 更新接口规则：
  - task 不存在 → 404
  - 非法 executor → 422/400
  - 只允许改 `executor`，不允许顺带改 phase / title / prompt / sequence
  - 返回更新后的 `CodexTask`
- 运行规则：
  - 如果用户当前选择的 executor 与 task.executor 不同，前端先更新 executor
  - 更新成功后再调用现有 `POST /api/codex/tasks/{task_id}/run`
  - 如果 executor 没变，直接运行
  - 更新失败则不启动运行
- development 顺序约束保持不变；切换执行器不能绕过“前序任务未完成”的限制。

## Task 1: 锁定后端接口与运行联动测试

**Files:**
- Modify: backend task API / runtime tests

- [ ] **Step 1: 为 task executor 更新接口写失败测试**

验证：
- 成功把 task.executor 从 `codex` 改为 `claude`
- 非法 executor 返回 422/400
- task 不存在返回 404
- 其他字段不会被改动

- [ ] **Step 2: 为运行联动写失败测试**

验证：
- 更新 executor 后调用 `run`，启动时使用新 executor
- development 顺序阻塞时，即使切了 executor，仍返回 409

- [ ] **Step 3: 运行相关后端测试，确认 RED**

Run:

```bash
cd backend && PYTHONPATH=. ./.venv/bin/pytest tests/test_codex_tasks.py -q
```

Expected: 新增断言失败。

## Task 2: 新增后端 task executor 更新接口

**Files:**
- Modify: `backend/app/interfaces/api.py`
- Modify: 对应 backend tests

- [ ] **Step 1: 增加更新请求模型**

新增窄接口请求体，只允许：

```python
class UpdateCodexTaskRequest(BaseModel):
    executor: Literal["codex", "claude"] | None = None
```

- [ ] **Step 2: 新增 `PATCH /api/codex/tasks/{task_id}`**

行为固定：
- 加载 task，不存在返回 404
- 若 request 未提供任何可更新字段，返回 400
- 若提供 `executor`，更新 task.executor 和 `updated_at`
- 保存并返回更新后的 task

- [ ] **Step 3: 保持运行接口不变**

`run_codex_task` 不接收 executor 参数，继续读取 task 当前 `executor` 并分发到对应 runtime。

- [ ] **Step 4: 跑后端测试，确认 GREEN**

Run:

```bash
cd backend && PYTHONPATH=. ./.venv/bin/pytest tests/test_codex_tasks.py -q
```

Expected: PASS

## Task 3: 前端接入 task executor 更新 API

**Files:**
- Modify: `frontend/src/lib/types.ts`
- Modify: `frontend/src/lib/api.ts`
- Modify: API tests

- [ ] **Step 1: 增加前端请求类型**

新增：

```ts
export interface UpdateCodexTaskRequest {
  executor?: "codex" | "claude";
}
```

- [ ] **Step 2: 增加 API 方法**

新增：

```ts
updateCodexTaskExecutor(taskId, executor)
```

固定请求：
- `PATCH /api/codex/tasks/{taskId}`
- body 只传 `executor`

- [ ] **Step 3: 增加 API 测试**

验证方法是否正确请求 `PATCH` 和请求体。

## Task 4: 详情运行区支持选择执行器

**Files:**
- Modify: `frontend/src/features/runs/RunDetail.tsx`
- Modify: `frontend/src/features/workbench/WorkbenchPage.tsx`

- [ ] **Step 1: 在 `RunDetail` 加入执行器选择控件**

复用现有 `ExecutorToggle`，放在运行按钮区域附近。

- [ ] **Step 2: 扩展 `RunDetail` props**

新增：
- `selectedExecutor: "codex" | "claude"`
- `onExecutorChange: (executor: "codex" | "claude") => void`
- `onRunInitial(executor: "codex" | "claude")`
- `onRunAgain(executor: "codex" | "claude")`

- [ ] **Step 3: 在 `WorkbenchPage` 持有当前详情执行器状态**

规则：
- 切换当前 task 时，默认值取 `currentTask.executor`
- 用户改选后，保存在 `selectedDetailExecutor` state（新增）

需要同步修改的 `WorkbenchPage.tsx` handlers：
- **line 745 `onRunInitial` inline handler**：当前无参数，改 `async (executor) => { ... runCodexTask(...) }`，先调 `updateCodexTaskExecutor` 再 `runCodexTask`
- **line 758 `onRunAgain` inline handler**：同上，签名从 `async () => { ... }` 改为 `async (executor) => { ... }`

- [ ] **Step 4: 首次运行 / 重新运行前先更新 executor**

规则：
- 若所选 executor 与 `currentTask.executor` 不同：
  - 调用 `updateCodexTaskExecutor`
  - 用返回 task 更新本地 `tasks` state
  - 再调用 `runCodexTask`
- 若相同则直接运行

- [ ] **Step 5: 更新失败时阻止运行**

需要展示明确错误，不允许“更新失败但仍启动旧 executor”。

## Task 5: 前端回归测试与交互验证

**Files:**
- Modify: frontend tests covering workbench / run detail / API

- [ ] **Step 1: 为运行区交互补测试**

验证：
- 首次运行可选 executor
- 重新运行可选 executor
- executor 未变化时不发更新请求
- executor 变化时先发更新请求，再发 run 请求
- 更新失败时不触发 run

- [ ] **Step 2: 为状态同步补测试**

验证：
- 更新成功后任务详情中的 executor 文案同步变化
- 本地 tasks state 中对应 task 的 executor 已更新

- [ ] **Step 3: 跑前端测试，确认 GREEN**

Run:

```bash
cd frontend && npm test
```

Expected: PASS

## Task 6: 端到端验证

**Files:**
- Verify existing backend/frontend changes only

- [ ] **Step 1: 跑后端测试**

```bash
cd backend && PYTHONPATH=. ./.venv/bin/pytest tests/test_codex_tasks.py -q
```

- [ ] **Step 2: 跑前端测试**

```bash
cd frontend && npm test
```

- [ ] **Step 3: 手工验证**

1. 打开一个已有 task 的详情
2. 在首次运行或 `重新运行` 前切换执行器
3. 验证任务详情头部 executor 立即同步
4. 验证新一轮运行按新 executor 启动
5. 对 development 被锁任务验证：即使切了 executor，仍不能绕过顺序限制

- [ ] **Step 4: Scope 审核**

Task 6 只做验证，不允许：
- 新建 task 副本
- 改 phase 列头 `+` 的交互
- 改现有 development 顺序契约

## Assumptions

- 只支持在右侧详情运行入口切换执行器，不改 phase 列头 `+`。
- 切换执行器不会新建 task，只更新原 task 的 `executor` 字段。
- 历史 execution process 继续保留原执行器语义；新一轮运行使用更新后的 executor 即可。
- 现有 `run_codex_task` 路由已经能依据 task.executor 分发到 `codex` 或 `claude` runtime，因此无需新增独立运行接口。
