# Research 02: useExecutionProcessMessageStream vs useExecutionProcessLogStream

- **Query**: 两个 hook 的接收/返回/WS 协议；DispatchDrawer 应该用哪个
- **Scope**: internal
- **Date**: 2026-05-23

## 关键结论先放前面

**DispatchDrawer 应该直接嵌 `AgentLiveTimeline`，不要自己调任何 hook。**

`AgentLiveTimeline` 内部已经用了 `useExecutionProcessLogStream`（`AgentLiveTimeline.tsx:8, 214-215`），它带 heartbeat / 流式 assistant_delta / disconnected / finished 全套状态。`useExecutionProcessMessageStream` 是更老/更简的"完整消息列表"流，**不带 token-level streaming、不带 heartbeat**，给老的 TasksRunsTab 双轨展示用，本任务用不上。

下面把两个 hook 的接口都写清楚，并对比差异。

---

## useExecutionProcessMessageStream

### File
- `/Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/frontend/src/hooks/useExecutionProcessMessageStream.ts:1-193`

### Signature
```ts
function useExecutionProcessMessageStream(processId: string | null): {
  messages: CodexTaskMessage[];
  pendingAssistant: { text: string; lastSeq: number } | null;
  error: string | null;
}
```
（`:20-24, :26`）

### 接收参数

- `processId`: `string | null` — **唯一参数**。`null` 时（`:133-154`）清空所有 state、关闭 WS、不重连，保持空闲。
- 切到新非 null id 时（`:156-168`）：重置 finishedRef / message ids / messages / pending / error，0ms setTimeout 后调 `connect()`。

### 返回字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `messages` | `CodexTaskMessage[]` | 完整消息列表（包含 user 和 assistant），按 `created_at` 排序（`:7-13`）。去重靠 `messageIdsRef`（`:35, 49`）。 |
| `pendingAssistant` | `{ text: string; lastSeq: number } \| null` | "正在输入"的临时 assistant text。收到 `message_delta` 累加（`:58-65`），收到完整 assistant message 时清空（`:53-56`）。 |
| `error` | `string \| null` | "Failed to process message stream update" / "Message stream connection failed"（`:98, 116`）。 |

### WS URL

- `getProcessMessagesUrl(processId)` → `${WS_BASE}/api/execution-processes/${processId}/messages/ws`
- 定义：`frontend/src/lib/api.ts:1186-1188`

### 消息协议

WS 发的 JSON envelope 三种 shape（`:82-96`）：
1. `{ finished: true }` → 标记 finished、`ws.close(1000)`，不重连。
2. `{ type: "message_delta", seq: number, delta_text: string }` → 累加 pendingAssistant.text，乱序按 lastSeq 过滤（`:58-65`）。
3. 否则当成 `CodexTaskMessage`（`id` / `role` / `content` / `created_at` / `execution_process_id` ...）addMessage 入 list。

### 重连 / cleanup

- 自带指数退避重连（`:38-46`），上限 6 次，超过设 error。
- finished / clean 关闭（code 1000）不重连。
- `useEffect` 的清理函数（`:170-189`）卸载组件时显式置空 onopen / onclose / onmessage 并 `ws.close()`。
- **调用方不需要管 cleanup**。

### Streaming 粒度

**Token-level**：通过 `message_delta` 累加 `pendingAssistant.text`。每个 delta_text 是一段新内容增量。

---

## useExecutionProcessLogStream（对比 / AgentLiveTimeline 实际在用的那个）

### File
- `/Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/frontend/src/hooks/useExecutionProcessLogStream.ts:1-277`

### Signature
```ts
function useExecutionProcessLogStream(processId: string | null): {
  logs: LogEvent[];
  error: string | null;
  streamingAssistant: { seq: number; text: string; receivedAt: number } | null;
  heartbeat: { phase: string; elapsedSinceLastMs: number; lastEventAt: number | null; receivedAt: number } | null;
  finished: boolean;
  disconnected: boolean;
}
```
（`:15-35, :37`）

### 接收参数
- `processId: string | null` — 同上，null 时清理停连（`:206-232`）。

### 返回字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `logs` | `LogEvent[]` | 原始 stdout/stderr 日志事件，按 created_at 排序、id 去重（`:7-13, 64-68`）。 |
| `streamingAssistant` | `{ seq, text, receivedAt } \| null` | Backend 已经 fold 过的 assistant text（`:126-144`）。**收到 LogEvent stdout 时主动清空**（`:160-166`）避免和最终 normalized log 重复。 |
| `heartbeat` | `{ phase, elapsedSinceLastMs, lastEventAt, receivedAt } \| null` | 后端定期推的心跳，含 phase（`tool` / `reasoning` / `text` / `idle`），驱动 `WorkingIndicator` 文案（`AgentLiveTimeline.tsx:140-151`）。 |
| `finished` | `boolean` | true → 任务结束，不重连。 |
| `disconnected` | `boolean` | 重连尝试 > 1 次后 true，UI 弹"已断线"红条。 |
| `error` | `string \| null` | 错误文案。 |

### WS URL
- `getProcessLogsUrl(processId)` → `${WS_BASE}/api/execution-processes/${processId}/logs/ws`（`api.ts:1182-1184`）

### 消息协议（envelope 五种）
1. `"pong"` 文本或非 `{` 起头 → ping/keepalive，忽略（`:91-95`）。
2. `{ finished: true }` → finishedRef + setFinished + 清 streaming + close(1000)（`:114-124`）。
3. `{ kind: "assistant_delta", seq, delta_text }` → token-level 拼字（`:126-144`）；如果新 seq <= 当前 seq 当成新 turn 重置 buffer。
4. `{ kind: "heartbeat", phase, elapsed_since_last_ms, last_event_at }` → setHeartbeat（`:146-154`）。
5. LogEvent shape（有 `id` + `stream`）→ addLog；stdout 到达时清空 streaming buffer（`:156-167`）。

### 重连 / cleanup
- 30s 客户端 ping 保活（`:83-86`）。
- 指数退避重连，> 1 次 setDisconnected, > 6 次 setError。
- finished / clean close 不重连。
- `useEffect` 卸载时显式置空 handlers + close（`:253-272`）。**调用方不管 cleanup**。

### Streaming 粒度
**Token-level**（`assistant_delta`）+ **行级**（`LogEvent`）+ **状态级**（`heartbeat`）。比 message stream 更丰富。

---

## 两个 hook 的差异对比

| 维度 | useExecutionProcessMessageStream | useExecutionProcessLogStream |
|---|---|---|
| 数据形态 | `CodexTaskMessage` 列表（user + assistant） | `LogEvent` 列表（raw stdout/stderr） |
| Token streaming | ✓（`message_delta`） | ✓（`assistant_delta`） |
| Heartbeat / phase | ✗ | ✓ |
| Finished 信号 | 仅内部状态 | 暴露 `finished` |
| Disconnected 信号 | ✗（只有 error） | ✓ |
| Ping 保活 | ✗ | ✓（30s） |
| AgentLiveTimeline 是否用 | ✗ | ✓ |
| TasksRunsTab 是否用 | ✓ | ✓ |
| RunDetail.tsx 是否用 | ✓（messages tab + pendingAssistant 气泡 `:512`） | ✓（logs tab 通过 AgentLiveTimeline） |

---

## DispatchDrawer 应该用哪个？

**用 `<AgentLiveTimeline executionProcessId={...} ...>` 直接嵌**，不要自己再调任何 stream hook。理由：

1. `AgentLiveTimeline` 已经走 logStream，token-level + heartbeat + 失败 banner 全在；
2. 自己再调 messageStream 反而会出现"两个 WS 连同一个 process_id"的尴尬，且少 heartbeat；
3. PRD 第 16 行明示"复用 `AgentLiveTimeline` 部分组件"。

也就是说本任务**不需要直接接触 `useExecutionProcessMessageStream`**，只需要拿到 `execution_process_id` 给 AgentLiveTimeline 就行（见 03 号文件）。
