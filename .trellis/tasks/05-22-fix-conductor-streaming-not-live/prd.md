# refactor: 通信层统一到 WebSocket（含 Conductor 流式实时修复）

## Goal

把当前"per-workspace WS + 全局 /api/events SSE"的双通道架构统一为单一 WebSocket 通道：所有 backend → frontend 实时事件（task-scoped 的 task_status / log_event，issue-scoped 的 conductor_turn_delta / conductor_status / conductor_state_violation，project-scoped 的 project_conductor_loop，session-scoped 的 session_created 等）都通过一条 WS 连接推送，带 envelope 协议 + ring buffer + Last-Event-ID resume。**附带修复**：上一轮 streaming 任务在双通道边界处遗漏的"conductor 流式打字机不实时、要关开抽屉才刷新" bug 自然消失。

## Decisions

* **架构方案 = 统一 WS**（删 SSE）
  * **Why**：[[feedback-prefer-architecture-over-speed]] —— 这个项目要的是规范不是速度。
* **WS topic 粒度 = 一个全局 topic**
  * **Why**：Web 实时通信经典 pub/sub（Vite HMR、Next.js dev、Phoenix LiveView 早期）；无 topic registry；新事件零摩擦；现有 `busEventMatchers.typeIn(...)` 已在客户端 filter。
* **帧 schema = envelope `{v, ts, event_id, type, payload}`**
  * `v`: 协议版本号（int，从 1 起），用于未来 protocol upgrade
  * `ts`: 后端产生时间（ISO 8601）
  * `event_id`: 单调递增 UUID/ulid，用于 dedupe + resume
  * `type`: 事件 type（同现有 SSE）
  * `payload`: 事件具体数据（包原现有事件字典除 type 外的字段）
  * **Why**：production WS 协议标配；envelope 与 payload 解耦，未来加 client→server RPC 用同一信封扩展无破坏性变更。
* **断线 resume = ring buffer + Last-Event-ID（标准做法）**
  * 后端 `EventBus` 改为 ring buffer 限 last 1000 events（可配），每事件赋单调 event_id
  * 新 WS endpoint 支持 query param `?last_event_id=xxx`：reconnect 时 server 从 ring buffer 找该 id 之后所有事件，先回放再开始 live
  * 客户端 `useExecutionProcesses` 记 `lastSeenEventId` 在 sessionStorage（页面刷新前还能 resume）
  * ring buffer miss（客户端 last_event_id 已被挤出）→ server 发 `{type: "resume_gap", from_event_id: ..., reason: "buffer_overflow"}` 告知客户端"丢了，请 REST 重新拉 snapshot"
  * **Why**：EventSource Last-Event-ID 协议的等价物；防短暂断线丢事件；防重启 → 重连后看不到中间状态。

## Requirements

1. **R1 后端 `EventBus` 升级为 ring buffer**：
   - 配置项 `EVENT_BUS_BUFFER_SIZE`（默认 1000）
   - 每事件赋递增 `event_id`（uuid4 或 ulid）+ `ts` + `v=1`
   - 保留现有 `append(event_dict)` 签名，envelope 包装在 append 内部完成（旧 emit 侧零改动）
2. **R2 新增统一 WS endpoint `/api/ws/events`**：
   - 接受 `?last_event_id=xxx` query param
   - on connect：若有 last_event_id → 从 ring buffer 回放该 id 之后所有事件（或发 resume_gap）；然后 enter live broadcast
   - 心跳：30s ping，60s 未收 pong 服务端主动 close
3. **R3 后端 `event_bus._broadcast_to_ws` 扩展**：所有 envelope 广播到 `/api/ws/events` 的 subscriber list；原有 task/message/raw_log workspace-scoped stream_manager 仍保留（它们的客户端是 message log 等独立 UI，不动）
4. **R4 删除 `/api/events` SSE 端点**（`backend/app/interfaces/sse.py` 整个文件删）
5. **R5 前端 `useExecutionProcesses` 重写**：
   - 不再分 SSE/WS 双分支；统一连 `/api/ws/events`（无论 workspaceId 是否为 null）
   - workspaceId 非 null 时**额外**连 per-workspace WS（沿用现有代码）拿 task chat / log 流式
   - 维护 `lastSeenEventId` 状态 + 持久化 sessionStorage
   - 实现指数退避 reconnect（参考现有 per-workspace WS 的 retry 代码）+ jitter
   - 收到 `resume_gap` 时清除 lastSeenEventId 并触发上层 invalidate（通过 Context 暴露一个 `onResumeGap` callback）
6. **R6 删除前端 EventSource 分支**（`useExecutionProcesses.ts:55-95` 整段）
7. **R7 envelope unwrap**：`useExecutionProcesses` 接收 envelope 后 `setLastEvent({...envelope.payload, type: envelope.type})` 暴露给上层 —— 上层 `useBusEventEffect` / `busEventMatchers` 等代码零改动
8. **R8 不破坏现有 per-workspace WS task-level 流式**：codex/claude CLI 的 task_status / log_event 推送仍工作；这部分仍走 per-workspace WS（双通道继续存在，但不再需要"全局事件靠 SSE"）
9. **R9 后端 pytest 覆盖**：envelope 包装、event_id 单调递增、ring buffer eviction、resume from valid id、resume_gap on buffer miss、心跳超时
10. **R10 前端 RTL 覆盖**：reconnect 自动带 lastSeenEventId、resume_gap 触发 invalidate、envelope unwrap 不破坏现有订阅

## Acceptance Criteria

* [ ] 创建新 issue → ConductorLogPanel 抽屉打开**不关**就能看到 token-by-token 流式打字
* [ ] phase 切换 + violation toast 实时（不需要关开抽屉）
* [ ] task chat / CLI 流式日志推送仍工作不退化
* [ ] sidebar issue 创建 / status 变化实时刷新
* [ ] Approvals 页 awaiting_review 出现时实时弹
* [ ] 重启 backend → 前端 WS 断 → 自动重连（< 30s）→ 看到 buffer 内未送达事件回放
* [ ] backend ring buffer 满 → 客户端收 `resume_gap` → 自动触发 ConductorLogPanel 重新拉 turns snapshot
* [ ] `/api/events` SSE 端点从 backend 已删；前端 `grep "EventSource"` 零命中
* [ ] envelope `{v, ts, event_id, type, payload}` 在 backend & frontend 两端 schema 一致；新加事件类型只需在 payload 加字段不动 envelope
* [ ] pytest + frontend 单测覆盖 envelope / ring buffer / resume / reconnect / resume_gap

## Definition of Done

* 后端 EventBus 重构 + 新 WS endpoint + 删 SSE 端点有 pytest 覆盖
* 前端 useExecutionProcesses 重写 + envelope unwrap + reconnect + lastSeenEventId 持久化有 RTL 测试
* CLAUDE.md "实时通信" 段重写（删 SSE、加 envelope 协议、加 ring buffer + resume 说明）
* 手测全套：创建 issue / 跑 Conductor 看到 token 流式 / 任务 chat / Approvals / sidebar / backend 重启 resume / 故意溢出 buffer 触发 resume_gap

## Technical Approach

### 后端

- `backend/app/application/event_bus.py`：
  - `EventBus.__init__`：`self.events` 改成 `collections.deque(maxlen=EVENT_BUS_BUFFER_SIZE)`
  - `append(payload)` 内部包 envelope `{v: 1, ts: datetime.now().isoformat(), event_id: str(uuid4()), type: payload.pop("type"), payload}`
  - 单 envelope 对象推到所有 subscriber asyncio.Queue
  - 新方法 `replay_from(last_event_id) -> list[envelope] | "gap"`：从 deque 找 last_event_id 之后所有 envelope；找不到返回 "gap" 标记
- `backend/app/interfaces/ws_events.py` （新文件）：
  - `@router.websocket("/api/ws/events")`：accept、读 query last_event_id、若有则 replay 或发 resume_gap、然后 subscribe 到 EventBus broadcast queue
  - 心跳：每 30s 发 `{type: "ping"}`，60s 未收到 pong 则主动 close
- `backend/app/interfaces/sse.py`：**删整文件** + 在 main.py 取消 router include
- `backend/app/application/conductor_main_loop.py` 等所有 `event_bus.append({...})` 调用点：**不动**（envelope 在 EventBus 内部包，外部 emit 接口不变）

### 前端

- `frontend/src/hooks/useExecutionProcesses.ts`：
  - 删 EventSource 分支（line 55-95）
  - 新增 `globalWsRef`：永远连 `/api/ws/events?last_event_id=${lastSeenEventId ?? ""}`
  - onmessage：parse envelope → `setLastEvent({...envelope.payload, type: envelope.type})` + 更新 lastSeenEventId 到 sessionStorage
  - 收到 `{type: "resume_gap"}` → 清 sessionStorage lastSeenEventId + 触发 onResumeGap callback
  - reconnect 指数退避（参考现有 per-workspace WS reconnect 代码）
  - 心跳：on `{type: "ping"}` 回 `{type: "pong"}`
- `frontend/src/contexts/ExecutionProcessesContext.tsx`：暴露 `onResumeGap` callback prop（让上层 page / ConductorLogPanel 知道要 REST 重新拉 snapshot）
- `frontend/src/app/issues/[id]/page.tsx`：workspaceId 仍然传给 WorkbenchShell（per-workspace WS 还要），但**通信不再依赖**它走 SSE 还是 WS
- `frontend/src/features/workflow/ConductorLogPanel.tsx`：监听 onResumeGap 触发 `loadConductorTurns(issueId)` + `getConductorStateLog(issueId)` 重拉

## Out of Scope

- `/codex/projects/{project_id}/conductor/stream` 端点（project conductor hot_thread snapshot，单独用途，保留）
- per-workspace WS 协议升级 envelope（本次只升级全局 events 通道；per-workspace 通道沿用现有 stream_manager 协议）
- WebSocket 鉴权重写（用现有 auth）
- WS 客户端→服务端推送（双向 RPC，envelope 已为此预留，本次不实现）
- 协议 v2（本次只发 v=1）

## Technical Notes

* 关键文件：
  - `backend/app/application/event_bus.py`（ring buffer + envelope）
  - `backend/app/interfaces/ws_events.py`（新建）
  - `backend/app/interfaces/sse.py`（删）
  - `backend/app/main.py`（router include 调整）
  - `frontend/src/hooks/useExecutionProcesses.ts`（删 SSE 分支、加全局 WS）
  - `frontend/src/contexts/ExecutionProcessesContext.tsx`（onResumeGap）
  - `frontend/src/features/workflow/ConductorLogPanel.tsx`（onResumeGap → 重拉 snapshot）
* 现有 per-workspace WS 协议 reference：`backend/app/interfaces/codex_ws.py` + 前端 `frontend/src/hooks/useExecutionProcesses.ts:147+`
* event_id 实现：`uuid4()` 即可（ulid 需新依赖，不值）；ring buffer 内顺序就是接入顺序，event_id 只用于 dedupe + resume key，不需全局严格递增数值
