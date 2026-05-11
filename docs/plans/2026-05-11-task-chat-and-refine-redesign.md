# Task Chat / Refine / Rerun — 运行意图分离重构

> **For agentic workers:** Implement task-by-task with TDD. Each task follows RED → GREEN → COMMIT, and stops at a QA handoff point in `COMMUNICATION.md` before the next task begins.

**Goal:** 让"对话 / 修订 / 重跑 / 首次生成"四种意图在 ExecutionProcess 层面被一等公民地区分；聊天回复不再覆盖 role artifact 或 `task.result`；CLI 自然的 session resume 接住对话历史；refine 走通用 merge/replace 走通 4 个 role。

**Non-goals:**
- 不引入 LLM token 估算 / 历史裁剪。历史靠 CLI `resume_session_id` 续接（codex / claude CLI 都支持）。
- 不重写 role workflow 的 prompt 构造，只增加 chat / refine 两个旁路。
- 不做 streaming 中途的"切模式"，每次 send 时模式确定不再改。

**Architecture:**

```
ExecutionProcess.kind ∈ {initial, rerun, refine, chat}
                          │
        ┌─────────────────┼──────────────────┐
        │                 │                  │
   initial / rerun     refine            chat
        │                 │                  │
   role build_prompt  refine_prompt    chat_prompt
        │                 │                  │
   parse + persist    parse + persist    only message
   (overwrite)        (merge if PM,      no task.result
                       replace others)    no artifact write
```

**Tech Stack:** Python (FastAPI, pytest, aiosqlite), TypeScript (Next.js, node:test).

---

## Execution Rule

每个 task 完成后写状态块到 `COMMUNICATION.md`，等 review 通过再启动下一个。

---

## File Structure (新建/修改)

### Backend

- Modify: `backend/app/domain/models.py` — `ExecutionProcess` 加 `kind` / `triggering_message_id`
- Modify: `backend/app/adapters/sqlite_store.py` — DDL + save/load 处理新列
- Modify: `backend/app/adapters/async_sqlite_store.py` — 同上 + migration（ALTER TABLE IF NOT EXISTS 风格）
- Modify: `backend/app/application/codex_task_runner.py` — `start_task_run` 接 `kind` 参数；`_build_prompt_text` 按 kind 分支；`_create_execution_process` 写新字段
- Modify: `backend/app/application/process_runtime_common.py` — `_mark_task_done` 按 EP.kind 分支
- Modify: `backend/app/interfaces/api.py` —
  - 新增 `POST /api/codex/tasks/{id}/chat`、`/refine`、`/rerun`
  - 旧 `POST /api/codex/tasks/{id}/messages` 内部路由到 chat（保留向后兼容）
  - 移除 `_chat_followup_execution_processes` 内存集合
  - `_refresh_task_result` 不再 hack，纯按 task.role/status/result 走
- Create: `backend/tests/test_execution_process_kind.py` — domain + store
- Create: `backend/tests/test_task_chat_endpoint.py` — chat 行为
- Create: `backend/tests/test_task_refine_endpoint.py` — refine 行为（4 role）
- Create: `backend/tests/test_task_rerun_endpoint.py` — rerun 覆盖语义

### Frontend

- Modify: `frontend/src/lib/types.ts` — `ExecutionProcess.kind`、`ChatRequest` / `RefineRequest` / `RerunRequest` 类型
- Modify: `frontend/src/lib/api.ts` — `chatCodexTask` / `refineCodexTask` / `rerunCodexTask` 三个 helper
- Modify: `frontend/src/features/runs/RunDetail.tsx` — chat 输入框上方加 mode chip `[对话] [修订] [重跑]`
- Modify: `frontend/src/features/workbench/WorkbenchPage.tsx` — `handleSendMessage(content, mode)` 按 mode 路由
- Modify: `frontend/tests/workbenchActions.test.ts` — 新 API helper 测试

### Cleanup

- 修改 `backend/app/application/product_manager_service.py` — 移除上次最小修复里的"prd 已存在则不覆盖"分支（refine merge 接管）
- 删除 `_chat_followup_execution_processes` / `is_chat_followup_execution` 函数

---

## Task 1: Domain + Storage Foundation (P1)

**Files:**
- `backend/app/domain/models.py`
- `backend/app/adapters/sqlite_store.py`
- `backend/app/adapters/async_sqlite_store.py`
- `backend/tests/test_execution_process_kind.py` (new)

**Steps:**

- [ ] **Step 1: RED tests** in `test_execution_process_kind.py`:
  - `test_execution_process_defaults_to_initial_kind` — new EP 默认 `kind="initial"`、`triggering_message_id=None`
  - `test_execution_process_persists_kind_and_triggering_message_id` — save→load 后字段保留
  - `test_existing_execution_process_rows_backfill_to_initial` — 模拟旧数据（不带 kind 列）通过 migration 后查到 `kind="initial"`
  - `test_execution_process_kind_invalid_value_rejected` — pydantic 拒绝非法 kind

- [ ] **Step 2: 域模型扩展** `ExecutionProcess`:

```python
class ExecutionProcess(BaseModel):
    ...
    kind: Literal["initial", "rerun", "refine", "chat"] = "initial"
    triggering_message_id: str | None = None
```

- [ ] **Step 3: SQLite schema + migration**:
  - `sqlite_store.py` / `async_sqlite_store.py` 的 CREATE TABLE 加新列；
  - 同步加 idempotent migration（`ALTER TABLE execution_processes ADD COLUMN kind TEXT NOT NULL DEFAULT 'initial'`，捕获已存在异常）；
  - 更新 INSERT / UPDATE / 反序列化逻辑。

- [ ] **Step 4: GREEN**：

```bash
cd backend && python3 -m pytest tests/test_execution_process_kind.py tests/test_models.py tests/test_codex_session.py -v
```

- [ ] **Step 5: Commit** — `feat: add kind + triggering_message_id to ExecutionProcess`

### Codex QA gate
- migration 在已有 DB（非空 execution_processes 表）上无破坏地运行（写一个"已有旧表"的测试场景）。
- pydantic Literal 拒绝拼写错误（防御未来手敲 SQL）。

---

## Task 2: Chat Run Kind Wiring (P2)

**Files:**
- `backend/app/application/codex_task_runner.py`
- `backend/app/application/process_runtime_common.py`
- `backend/app/interfaces/api.py`
- `backend/tests/test_task_chat_endpoint.py` (new)

**Steps:**

- [ ] **Step 1: RED tests**:
  - `test_chat_endpoint_creates_user_message_and_returns_ep` — POST `/chat` 创建 user message，新 EP 的 `kind="chat"`，`triggering_message_id=message.id`
  - `test_chat_does_not_overwrite_task_result` — task 跑完聊天后 `task.result` 保留原值
  - `test_chat_does_not_persist_pm_artifact` — 已有 `pm/prd.md` + `prd.json`，chat 完成后文件 mtime 不变
  - `test_chat_assistant_message_persisted` — assistant 回复进消息表
  - `test_chat_reuses_resume_session_id` — chat 用 `task.resume_session_id` 续接 CLI session（断言 mock CLI 收到的 resume 参数）
  - `test_legacy_messages_endpoint_routes_to_chat` — 老 `/messages` 端点 alias 到 chat（kind=chat）

- [ ] **Step 2: start_task_run 接 kind**:

```python
async def start_task_run(self, task, *, kind="initial", triggering_message_id=None, ...):
    ...
    exec_process = await self._create_execution_process(
        task, executor, provider, model,
        kind=kind, triggering_message_id=triggering_message_id,
    )
```

- [ ] **Step 3: _build_prompt_text 加 chat 分支**:

```python
async def _build_prompt_text(self, task, *, prompt_text, prompt_override, resume_session_id, resume_message_id, kind="initial"):
    if kind == "chat":
        return (
            "This is a follow-up conversation. Reply in natural language. "
            "Do NOT output JSON or modify the task artifact unless explicitly asked.\n\n"
            f"{prompt_text}"
        )
    # ... existing role-aware logic unchanged
```

- [ ] **Step 4: _mark_task_done 按 EP.kind 分支** (`process_runtime_common.py`):

```python
ep = await self.codex_store.load_execution_process(execution_process_id) if execution_process_id else None
is_chat = ep is not None and ep.kind == "chat"

if is_chat:
    # 保留 task.result 不动，不跑 refresh_task_result
    task.status = "done"
    task.updated_at = datetime.now()
else:
    task.status = "done"
    if entry.result_text:
        task.result = entry.result_text
    task.updated_at = datetime.now()
    if callable(self.refresh_task_result):
        ...
```

- [ ] **Step 5: 新 endpoint** in `api.py`:

```python
class ChatRequest(BaseModel):
    content: str

@router.post("/codex/tasks/{task_id}/chat", status_code=201)
async def chat_codex_task(task_id: str, request: ChatRequest):
    # 1. load task; reject if running
    # 2. 创建 CodexTaskMessage(role="user")
    # 3. start_task_run(task, kind="chat", triggering_message_id=msg.id,
    #                   prompt_override=request.content,
    #                   resume_session_id=task.resume_session_id, ...)
    # 4. 关联 message.execution_process_id = ep.id
    # 5. 返回 {message, execution_process, task}
```

旧 `/messages` 内部 alias：

```python
@router.post("/codex/tasks/{task_id}/messages", status_code=201, deprecated=True)
async def send_codex_task_message(task_id: str, request: SendTaskMessageRequest):
    return await chat_codex_task(task_id, ChatRequest(content=request.content))
```

- [ ] **Step 6: 删除 hack**：移除 `_chat_followup_execution_processes`、`is_chat_followup_execution()`、`_refresh_task_result` 里的相关 check。

- [ ] **Step 7: GREEN**：

```bash
cd backend && python3 -m pytest tests/test_task_chat_endpoint.py tests/test_codex_tasks.py tests/test_codex_task_runner.py -v
```

- [ ] **Step 8: Commit** — `feat: add chat run kind with artifact-safe semantics`

### Codex QA gate
- chat 完 task.result 真没动（独立测试，不依赖 PM 工作流）。
- assistant 消息能查到，UI 拉 task 级 messages 时按时间顺序排列。
- 4 个 role 都要覆盖（test 用参数化）：PM、Architect、Engineer、QA。

---

## Task 3: Refine Run Kind (P3)

**Files:**
- `backend/app/application/codex_task_runner.py`
- `backend/app/application/product_manager_service.py` (移除上次的 followup 防御)
- `backend/app/interfaces/api.py`
- `backend/tests/test_task_refine_endpoint.py` (new)

**Steps:**

- [ ] **Step 1: RED tests**（4 role 各一份成功路径 + 失败路径）：
  - `test_refine_pm_merges_existing_prd` — 已有 PRD，refine "把 product_goals 加一条 X"，最终 prd.json 包含原有 + 新增
  - `test_refine_architect_replaces_system_design` — refine system_design.json，新版本生效，development_task_list 一致性校验
  - `test_refine_engineer_rewrites_implementation_md` — refine engineer 报告，markdown 内容替换
  - `test_refine_qa_replaces_report` — refine qa_plan.json，新 status 写入
  - `test_refine_kind_persisted_on_ep` — EP.kind == "refine"
  - `test_refine_rejects_when_no_existing_artifact` — 没跑过 initial 时 refine → 409

- [ ] **Step 2: _build_prompt_text 加 refine 分支**:

```python
if kind == "refine":
    existing = await self._read_current_artifact(task)  # role-aware
    return (
        "You previously produced this artifact:\n"
        f"```\n{existing}\n```\n\n"
        f"The user requests these changes:\n{prompt_text}\n\n"
        "Re-emit the full artifact JSON conforming to the original schema, "
        "incorporating these changes. Do not omit unchanged fields."
    )
```

`_read_current_artifact(task)` 用 `IssueArtifactDocuments` 按 role 读取（PM→prd.json, Architect→system_design.json, Engineer→implementation*.md, QA→qa_plan.json）。

- [ ] **Step 3: refine 端点**:

```python
class RefineRequest(BaseModel):
    content: str

@router.post("/codex/tasks/{task_id}/refine", status_code=201)
async def refine_codex_task(task_id: str, request: RefineRequest):
    # reject if no canonical run finished (task.result empty or task.status != done)
    # reject if running
    # 创建 user message; start_task_run(kind="refine", prompt_override=request.content, ...)
    # 完成后走正常 persist_result（PM 已有 merge_with_existing_prd 逻辑，其他 role 直接 replace）
```

- [ ] **Step 4: 移除 PM defensive 分支**（上次最小修复加的 "if prd exists skip"），让 refine merge 接管。chat 路径已被 kind 区分，不会再误触 persist。

- [ ] **Step 5: GREEN**：

```bash
cd backend && python3 -m pytest tests/test_task_refine_endpoint.py tests/test_product_manager_service.py tests/test_architect_workflow.py tests/test_engineer_workflow.py tests/test_qa_workflow.py -v
```

- [ ] **Step 6: Commit** — `feat: add refine run kind with role-aware merge/replace persistence`

### Codex QA gate
- Engineer markdown refine 不破坏既有结构（snapshot 测试关键字符串）。
- Architect refine 后 `development_task_list.json` 仍校验通过（development sequencing 不被破坏）。

---

## Task 4: Rerun Run Kind (P3)

**Files:**
- `backend/app/interfaces/api.py`
- `backend/tests/test_task_rerun_endpoint.py` (new)

**Steps:**

- [ ] **Step 1: RED tests**:
  - `test_rerun_overwrites_artifact` — 跑两次 initial（第二次是 rerun），artifact 被新内容覆盖
  - `test_rerun_kind_persisted_on_ep` — kind=rerun
  - `test_rerun_uses_role_prompt_not_user_content` — 不接收 content，重用 task.prompt + role build_prompt（区别于 refine 接修改指令）
  - `test_rerun_rejects_running_task` — 409

- [ ] **Step 2: Rerun 端点**：

```python
@router.post("/codex/tasks/{task_id}/rerun", status_code=201)
async def rerun_codex_task(task_id: str):
    # 用原 prompt + role workflow（kind="rerun"）
    # start_task_run(task, kind="rerun")
    # 完成后正常 persist（覆盖既有 artifact）
```

- [ ] **Step 3: _mark_task_done**: rerun 走和 initial 完全相同的路径（task.result 更新 + persist）。kind 之间分支只有 chat 是特殊。

- [ ] **Step 4: GREEN + Commit** — `feat: add rerun endpoint reusing role workflow`

### Codex QA gate
- rerun 不被允许的 phase 状态过滤（development task 还要走 sequencing serial unlock）。

---

## Task 5: Frontend Mode Chip + API Helpers (P4)

**Files:**
- `frontend/src/lib/types.ts`
- `frontend/src/lib/api.ts`
- `frontend/src/features/runs/RunDetail.tsx`
- `frontend/src/features/workbench/WorkbenchPage.tsx`
- `frontend/tests/workbenchActions.test.ts`

**Steps:**

- [ ] **Step 1: 新类型 + API helper**：

```ts
export type RunMode = "chat" | "refine" | "rerun";

export async function chatCodexTask(taskId: string, content: string): Promise<SendMessageResult>;
export async function refineCodexTask(taskId: string, content: string): Promise<SendMessageResult>;
export async function rerunCodexTask(taskId: string): Promise<SendMessageResult>;
```

`ExecutionProcess` 加 `kind` 字段。

- [ ] **Step 2: 三个 API helper 的 RED + GREEN 测试**（mock fetch，断言 URL + method）。

- [ ] **Step 3: RunDetail mode chip**：在输入框上方加切换条 `[对话] [修订] [重跑]`：
  - 对话 / 修订: 输入框可见，发送按钮触发 `chat` / `refine`
  - 重跑: 输入框隐藏，按钮变 "重新生成"，触发 `rerun`，需要二次确认（因为会覆盖 artifact）
  - 默认 mode="chat"
  - 重跑按钮在 development 顺序锁定时禁用

- [ ] **Step 4: handleSendMessage 按 mode 路由** in `WorkbenchPage.tsx`：

```tsx
const handleSendMessage = useCallback(async (content: string, mode: RunMode) => {
  const fn = mode === "refine" ? refineCodexTask : mode === "rerun" ? rerunCodexTask : chatCodexTask;
  const result = await fn(selectedProcess.task_id, content);
  ...
}, [selectedProcess]);
```

- [ ] **Step 5: 错误展示分级**：chat 模式下 backend 不再 raise PRD 解析错误，但保留 toast 显示其他类错误。Refine / rerun 失败时把 ProductManagerArtifactError 之类的 detail 直接显示。

- [ ] **Step 6: 验证**：

```bash
cd frontend && npm test && npm run build && npm run lint
```

- [ ] **Step 7: 手动 E2E**: 在 PM 任务完成后，对话模式发 "你好" 应得到自然语言回复且 prd.md 不变；修订模式发 "把 product_goals 加上 X" 应更新 prd 且包含 X；重跑应重新生成完整 PRD。

- [ ] **Step 8: Commit** — `feat(frontend): chat/refine/rerun mode chip and routing`

### Codex QA gate
- 重跑二次确认不可绕过。
- mode 切换后输入框状态正确清理（避免上次的内容残留到错误 mode）。

---

## Task 6: Cleanup, Docs, E2E (P5)

**Files:**
- `backend/app/interfaces/api.py` (移除 dead code)
- `CLAUDE.md` (架构注记)
- `COMMUNICATION.md` (review log)

**Steps:**

- [ ] **Step 1: 删除残留 hack**：
  - `_chat_followup_execution_processes` set
  - `is_chat_followup_execution()` 函数
  - `_refresh_task_result` 里相关 check
  - `product_manager_service.persist_prd_from_result` 里上次加的 followup 防御分支

- [ ] **Step 2: 更新 `CLAUDE.md`**：增加一节"Run kinds: initial / rerun / refine / chat" 简短说明。

- [ ] **Step 3: 全量测试 + 手动 4 role × 3 mode 矩阵走查**：

```bash
cd backend && python3 -m pytest -v
cd frontend && npm test && npm run build
./dev-local.sh  # 手动验证
```

- [ ] **Step 4: 写 COMMUNICATION.md 总结块** — 状态、改动文件、回归覆盖。

- [ ] **Step 5: Commit** — `chore: cleanup chat-followup hack and document run kinds`

### Codex QA gate
- 最终全量回归 backend 全过 + frontend npm test 不引入新失败。
- E2E：用一个真实 issue 跑完 PM→Architect→Engineer→QA，在每个 role 任务都试 chat / refine，artifact 行为如预期。

---

## Risk / 边界

| 风险 | 缓解 |
|---|---|
| 历史 DB 没有 kind 列，旧 EP 不工作 | Task 1 加 idempotent ALTER + 默认值 'initial'；测试覆盖旧表场景 |
| Chat 模式下 CLI 没有 `resume_session_id`（第一次没跑过） | chat 端点逻辑：若 `task.resume_session_id` is None 仍发起新 session，让 CLI 用 prompt 里的任务上下文起手 |
| Refine 时 artifact 文件不存在（rerun 失败后） | 端点级 409，提示先跑 initial |
| Rerun 把开发任务的 sequencing 锁绕过 | rerun 端点复用 `/run` 的所有前置守卫（sequencing、依赖等） |
| Engineer artifact 是 markdown，refine 不好 merge | refine 直接 replace（agent 重写整篇）；UX 提示用户"修订会覆盖现有报告" |
| 旧 `/messages` 端点客户端仍在用 | alias 到 chat，保留至少 1 个版本，文档标 deprecated |

## 测试矩阵

| Role | initial | rerun | refine | chat |
|---|---|---|---|---|
| PM | ✓ (已有) | new | new (merge) | new (no persist) |
| Architect | ✓ (已有) | new | new (replace + dev_task_list 校验) | new |
| Engineer | ✓ (已有) | new | new (markdown replace) | new |
| QA | ✓ (已有) | new | new (replace) | new |

每格至少 1 个测试，标 `@pytest.mark.parametrize` 在 4 role 上展开。

## 估算工作量

| Task | 后端 LOC | 前端 LOC | 测试 LOC | 风险 |
|---|---|---|---|---|
| 1 Foundation | ~80 | 0 | ~120 | 中（migration） |
| 2 Chat | ~150 | 0 | ~250 | 中 |
| 3 Refine | ~180 | 0 | ~350 | 中 |
| 4 Rerun | ~60 | 0 | ~150 | 低 |
| 5 Frontend | 0 | ~200 | ~100 | 低 |
| 6 Cleanup | -60 | 0 | ~50 | 低 |
| **Total** | ~410 | ~200 | ~1020 | — |

约 1600 LOC（含测试），分 6 次 commit。
