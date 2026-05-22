# Conductor 交互式对话 (Steer + Resume)

## Goal

让用户能在 Conductor loop 跑的过程中**主动**给 Conductor 发消息（"换个策略"/"跳过 architect 直接 engineer"/"加个 security_reviewer"），消息进入 Conductor **下一次 LLM call 的 messages**，Conductor 看到后调整决策继续跑。同时支持手动 pause/resume Conductor。

跟现有的 `/steer`（写给 role agent 看的 `_steer.md`）和 `request_user_clarification`（Conductor 主动问）都不同——这是**用户主动 + 收件人是 Conductor 本身**。

## What I already know

- 后端 `conductor_main_loop.run_conductor_loop` 是 `for turn_index in range(max_turns)` 的同步循环，每轮调一次 LLM 拿响应
- 当前没有任何机制让外部线程往循环里塞 message
- `request_user_clarification` 工具通过 `task.status=awaiting_review` 实现"等用户"，但只能 Conductor 自己触发
- `POST /codex/issues/{id}/steer` 现成但 payload 写到 worktree `_steer.md`，是给 role agent 用，不进 Conductor messages
- 上一轮刚加的 `conductor_turns` 表 + ConductorLogPanel "Decisions" tab —— 决策时间线已经能实时看
- IssueDetailPage 监听 `conductor_failed` SSE 弹 toast
- `conductor_tasks.status` 当前只有 `running` / `done` / `failed`，没有 `paused` / `awaiting_user`

## Assumptions (temporary)

- Conductor loop 长跑（每轮 LLM call 5-30s），用户在两轮之间插入消息是常态；不需要中断当前 LLM call
- 用户消息按 FIFO 队列处理，下一轮 LLM call 之前把所有 pending 全部 flush 进 messages
- "pause" 等价于"loop 在 LLM 调用之间停下、conductor_tasks.status=paused"；用户发消息触发 resume

## Open Questions

（全部解决）

## Resolved

- **Q1 注入时机 → Poll DB 表 `conductor_inbox`**：每轮 LLM call 之前 query `WHERE conductor_task_id=X AND consumed=0`，全部 mark consumed 后 append 成新 user turn 到 messages 数组。与 Claude Code "queued message" 机制一致——不打断当前 turn，下轮自然续接。崩溃恢复消息不丢。延迟 = 一轮 LLM call（5-30s）对人类聊天可接受。
- **Q2 Pause 模式 → Mid-call interrupt (Esc-like)**：Pause endpoint 通过 asyncio task.cancel() 取消正在飞的 httpx 请求；loop catch CancelledError → 标 `conductor_tasks.status='paused'` → await wakeup signal。Resume 或发消息自动 wake up。立刻响应（<1s）。代价：要把 LLM call 包成可取消 task、处理 partial response、保存 messages 状态以便 resume。
- **Q3 UI 入口 → ConductorLogPanel 加输入框 + 顶部 Pause/Resume**：复用现有 285→412 行的面板（Thread/Log/Decisions 三 tab + SSE 订阅），底部 sticky 输入框 + 头部状态 chip（running/paused/awaiting LLM 第 N 轮）。入口仍是 DAG 点 Conductor 圆形节点弹抽屉。
- **Q4 消息存储 → conductor_turns 加 kind='user_message'**：复用上一任务刚加的 conductor_turns 表，新增 kind 枚举值 + 表加 `consumed_at TEXT NULL` 列（仅 user_message 用，其他 kind 永远 NULL）。Loop poll: `WHERE conductor_task_id=X AND kind='user_message' AND consumed_at IS NULL ORDER BY created_at`。统一时间线、统一 SSE 通道（conductor_turn），前端 Decisions tab 加一个新样式渲染 user_message kind 即可。

## Requirements (evolving)

### 必做（无论 MVP 范围）

- 后端：一个端点 `POST /api/codex/issues/{id}/conductor/message`，body `{message: str}`，把消息排到队列
- 后端：`run_conductor_loop` 每轮 LLM call 前检查队列，pending 消息以 `{"role":"user","content":"[USER INTERJECTION] ..."}` 形式 append 到 messages
- 前端：ConductorLogPanel 加输入框，发消息后实时 SSE 反映"用户消息已注入"
- 后端 prompt 调整：Conductor 系统 prompt 加一段告诉它"用户可能在任意 turn 插入 [USER INTERJECTION] 消息，必须严肃对待"

### 可能做（取决于范围）

- Pause/Resume 按钮 + `conductor_tasks.status=paused` 状态
- 注入消息历史可视化（在 Decisions tab 用不同样式高亮 user_message kind）

## Acceptance Criteria (evolving)

- [ ] **必做**：Conductor 在跑（处于两轮 LLM call 之间）时用户发 "skip architect, go straight to engineer"，下一轮 LLM call 的 messages 末尾会有 `[USER INTERJECTION] skip architect...`，Conductor 看到后真的 dispatch engineer 而不是 architect
- [ ] **必做**：用户发的消息在 ConductorLogPanel 的 Decisions tab 实时显示（SSE event）
- [ ] **必做**：原有路径未退化 —— 不发消息时 Conductor 决策跟之前一致
- [ ] **如果做 pause/resume**：点 Pause，loop 在当前轮跑完后停在 await（不发 LLM call），conductor_tasks.status 变 `paused`；点 Resume 或发任意消息触发恢复

## Definition of Done

- 后端 pytest 全绿（不引入新 fail）
- 前端 `npm run build` 通过
- 至少 1 个新单测：注入消息后下一轮 messages 包含 USER INTERJECTION
- CLAUDE.md "Conductor-driven orchestration" 段补一句"用户可通过 /conductor/message 端点中途插话"

## Out of Scope (explicit)

- 不做撤销/编辑已发送的 user message
- 不做中断当前正在进行的 LLM call（实现复杂、收益小）
- 不做多用户并发（同一时刻只一个用户操作一个 issue 的 Conductor）
- 不改 role agent 的 `_steer.md` 流程（那是另一回事，给 PM/Engineer/QA 用）
- 不做 Conductor 跟用户的多轮"对话历史"独立于 turns 表（消息就是 turn kind 的一种）

## Technical Approach

### 数据流

```
[用户在 ConductorLogPanel 发消息 / 点 Pause]
       ↓
  POST /api/codex/issues/{id}/conductor/message   →  save_conductor_turn(kind="user_message", payload={text})
  POST /api/codex/issues/{id}/conductor/pause     →  task.cancel() 当前 LLM call task
  POST /api/codex/issues/{id}/conductor/resume    →  set wakeup signal
       ↓
  conductor loop (run_conductor_loop):
    for turn_index:
      1. flush_inbox(): WHERE kind='user_message' AND consumed_at IS NULL
         → 每条 append 成 {"role":"user","content":"[USER INTERJECTION] ..."}
         → UPDATE consumed_at = now
      2. check paused flag → 若 paused: status='paused' + await wakeup_event
      3. _record_turn(llm_request)
      4. await call_llm_with_tools(...)   ← 包成可取消的 asyncio.Task
         - 正常返回: 继续 tool_use 处理
         - CancelledError (用户点 Pause): 标 paused + await wakeup → 唤醒后从本轮开头重试
      5. ... 现有 tool_use 处理 + tool_result + finalize 不变
       ↓
  loop 内每次 save_conductor_turn 已经 emit conductor_turn SSE
  ConductorLogPanel 订阅 conductor_turn，Decisions tab 看到 user_message kind 用聊天气泡样式渲染
       ↓
  Pause/Resume 也 emit conductor_status 让前端 chip 实时更新
```

### 关键设计

- **conductor_turns 加列**: `ALTER TABLE conductor_turns ADD COLUMN consumed_at TEXT`（nullable）。仅 `kind='user_message'` 行使用，其他 kind 永远 NULL。新增索引 `(conductor_task_id, kind, consumed_at)` 加速 poll 查询。
- **conductor_tasks.status**: 现有枚举 `running/done/failed`，新增 `paused`。Pause 时写 paused，Resume 时写回 running。
- **wakeup 机制**: 进程内维护 `dict[conductor_task_id → asyncio.Event]`（类似 TaskCompletionRegistry pattern）。Pause endpoint set event；Resume endpoint clear event 后再 set 一次让 await 解锁。崩溃恢复时 status=paused 的 task 不自动 resume——用户必须显式 resume（避免遗留 paused task 复活时上下文已变）。
- **可取消 LLM call**: `call_llm_with_tools` 已经用 `httpx.AsyncClient` + `async with client.stream/post`。把这个 await 包成 `asyncio.create_task(...)` 加 reference 到注册表，Pause endpoint 直接 `task.cancel()`。loop 内 `try/except asyncio.CancelledError`。被取消时**保留 messages 状态**（不 append assistant turn），下次 wake 后从本轮 step 1 重新 flush_inbox + LLM call，相当于"用户插话 + 重跑本轮"。
- **POSL prompt 调整**: Conductor 系统 prompt 加一段："用户可能在任意 turn 用 `[USER INTERJECTION]` 注入消息，严肃对待并立即调整后续决策。"
- **前端**: ConductorLogPanel 头部加 status chip + Pause/Resume 按钮；底部加 sticky 输入框（Cmd+Enter 提交）；Decisions tab 渲染 user_message kind 用右对齐聊天气泡（区别 LLM 调用左对齐时间线）。

## Decision (ADR-lite)

**Context**: Conductor 长跑 loop 用户完全被动——只能事后看时间线，不能在跑的过程中影响决策。上一任务做了可见性，这次解决"可控性"。

**Decision**:
1. 消息通过 DB poll 注入（崩溃恢复不丢，跟 Claude Code "queued message" 一致）
2. 强力 pause：mid-call interrupt 通过 asyncio task.cancel() 立刻响应
3. UI 复用 ConductorLogPanel，加输入框 + 状态 chip + Pause/Resume 按钮
4. 消息统一进 conductor_turns 表用新 kind=`user_message` + `consumed_at` 列

**Consequences**:
- 跟上一任务的 conductor_turns 表 schema 演进（加列、加 kind 枚举），数据库 migration 必须向后兼容
- `call_llm_with_tools` 要支持取消，可能影响其他调用方（搜下用法确认）
- paused 状态崩溃恢复策略明确"用户必须显式 resume"——避免 ghost resume

## Implementation Plan

4 个 PR-style 切片，单 PR 合并：

**PR1 — 后端 schema 演进 + inbox**
- migration: ALTER conductor_turns ADD COLUMN consumed_at TEXT + 新索引
- `app/adapters/async_sqlite_store.py`: 加 `enqueue_user_message(conductor_task_id, issue_id, text)` / `drain_inbox(conductor_task_id)`
- `app/application/conductor_main_loop.py` 的 `run_conductor_loop`:
  - turn 入口加 `flush_inbox` 步骤
  - 加 `paused` 检查 + `await wakeup_event`
  - `call_llm_with_tools` 包成可取消 task，catch CancelledError → 标 paused → await
- `app/interfaces/api.py`: 新端点 `POST /conductor/message` / `/conductor/pause` / `/conductor/resume`
- 测试: `test_conductor_inbox.py` 覆盖 enqueue→flush→appear in messages；test_pause_cancels_inflight 覆盖 pause→cancel→paused→resume→retry

**PR2 — Conductor prompt + wakeup registry**
- 新增 `app/application/conductor_pause_registry.py`（类似 TaskCompletionRegistry 的 asyncio.Event 单例 by conductor_task_id）
- `run_issue_conductor_loop` 初始 prompt 加 USER INTERJECTION 段
- conductor_tasks.status 新增 `paused` 枚举（仅是 string，不需要 schema 改）

**PR3 — 前端**
- `frontend/src/lib/api.ts`: `sendConductorMessage` / `pauseConductor` / `resumeConductor`
- `ConductorLogPanel.tsx`:
  - 头部加 status chip + Pause/Resume 按钮
  - 底部加 sticky 输入框
  - Decisions tab 加 user_message 渲染样式（右对齐气泡）
- 订阅新 SSE event 类型 `conductor_status`

**PR4 — 收尾**
- CLAUDE.md "Conductor-driven orchestration" 段补一句：用户可通过 POST /conductor/message 中途插话，可 pause/resume
- 测试补完整 acceptance 路径

## Out of Scope (extended)

（沿用之前的 + 几条 reaffirm）
- 不做撤销/编辑已发送消息
- 不做多用户同时操作同一 Conductor 的并发协调
- 不做 paused 自动 resume（崩溃恢复后 paused task 必须人工 resume）
- 不影响 `request_user_clarification` / `_steer.md` 现有路径

## Technical Notes

- 关键文件：
  - `backend/app/application/conductor_main_loop.py:46` — `run_conductor_loop` 主循环，注入点在 for 循环开头
  - `backend/app/application/conductor_main_loop.py:178` — `run_issue_conductor_loop` 入口，构建初始 prompt
  - `backend/app/interfaces/api.py` — 新端点放这
  - `backend/app/domain/models.py` — 可能加 `ConductorInboxMessage` 模型
  - `frontend/src/features/workflow/ConductorLogPanel.tsx` — 加输入框 UI
  - `frontend/src/lib/api.ts` — 加 `sendConductorMessage` / `pauseConductor` / `resumeConductor`
- 相关已有机制：
  - `/codex/issues/{id}/steer` — 已存在但给 role agent 用，不复用
  - `request_user_clarification` tool — Conductor → 用户的另一个方向，跟本任务正交
  - `conductor_turns` 表 — 时间线，可加新 kind=user_message
- 设计约束：
  - 不破坏 `run_conductor_loop` 的现有签名（其他 caller 比如测试可能调）
  - poll 间隔不能太短（避免 LLM call 之间空转），FIFO 就好
