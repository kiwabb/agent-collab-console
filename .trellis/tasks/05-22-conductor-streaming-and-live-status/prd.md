# conductor: 流式输出 + 实时状态真实化

## Goal

让用户发消息给 Conductor 后能**立刻**看到反应：(1) Conductor LLM 的 text 一段一段（100ms batch）出现在 UI；(2) 简状态字段 `phase + detail` 真实反映 Conductor 当前在做什么（等 LLM / dispatch / 等 sub-agent / 等用户回答），而不是死盯"运行中"。状态机 + 动画拆到下个子任务。

## Requirements

1. **Conductor LLM 调用切换为 SSE 流式**：`llm_runner.call_llm_with_tools` 改为流式版本，参考已有 `llm_runner.stream_llm`（line 237-303）；协议保持 Anthropic `/v1/messages` + `stream: true`；解析 `content_block_delta` 的 `text_delta`、`input_json_delta`（tool_use 输入也是流式 JSON 字符串），以及 `content_block_start` / `content_block_stop` / `message_stop`。
2. **后端 100ms batch 聚合**：text_delta 在内存里按 100ms 窗口聚合一次，emit 一条 SSE 事件 `conductor_turn_delta`（payload: `{issue_id, turn_index, sub_index, kind: "text" | "tool_input_json", text_or_chunk, content_block_index}`）。
3. **后端 turn 结束落盘完整文本**：LLM call 结束（流读完）后，把整段 assistant message（含完整 text + 完整 tool_use blocks）写一行 `conductor_turns(kind='llm_response', payload_json={content, stop_reason, usage})`。流式 buffer 不写 DB。
4. **后端 `conductor_status` 加两字段 `phase` + `detail`**：phase 枚举 `awaiting_llm | streaming_llm | dispatching_subagent | awaiting_subagent | awaiting_user_clarification | paused | done | failed`；detail 自由文本（如 "engineer#1 (32s)"）。现有 5 个 emit 点改报对应 phase。schema 向后兼容：旧 `status` 字段保留。
5. **前端 ConductorLogPanel 订阅 `conductor_turn_delta`**：当前 turn 内累积渲染 text；turn 完成（收到 `conductor_turn` 的 `llm_response`）后清掉临时缓冲并显示最终内容。
6. **前端 ConductorLogPanel 订阅 `conductor_status`**：固定区域展示 `phase` icon + `detail`；phase = `awaiting_subagent` 且 `detail` 含时长 > 30s 时高亮"卡住"。

## Acceptance Criteria

* [ ] 创建新 issue 触发 Conductor 启动 → ConductorLogPanel 在 2s 内出现 phase=`awaiting_llm`，且 `streaming_llm` 阶段能看到 ≥3 次中间文本更新。
* [ ] LLM 决定调 `dispatch_subagent` 时，phase 切到 `dispatching_subagent` → `awaiting_subagent`，detail 显示 `engineer#1`。
* [ ] sub-agent 完成后 phase 回到 `awaiting_llm`，下一轮流式继续。
* [ ] 同一 issue 刷新页面：历史轮的完整 text + tool_use blocks 能从 `conductor_turns(kind='llm_response')` 加载渲染；不重放打字动画。
* [ ] MiniMax-M2.7 网关在新流式实现下能正常完成一个简单 issue（PM → finalize）。
* [ ] pytest 覆盖：流式解析单测（mock SSE）、100ms batch 聚合单测、`conductor_status` payload schema 单测。

## Definition of Done

* 后端流式调用 + 状态事件改动有 pytest 覆盖。
* 前端订阅 + 渲染有快照 / RTL 测试（至少一条流式渲染 + 一条 phase 切换）。
* CLAUDE.md "诊断 Conductor 崩溃" 段加"流式 / phase 字段"小段。
* MiniMax 网关人工验证流式 + tool_use 不破坏。

## Technical Approach

### 后端

- 新增 `llm_runner.call_llm_with_tools_streaming(messages, tools, ctx, on_delta) -> dict` 替换 `call_llm_with_tools`（旧版可保留作 fallback 或删除）：
  - 用 `httpx.AsyncClient().stream("POST", ...)` 拿 SSE
  - 解析 Anthropic SSE 协议：`content_block_start` / `content_block_delta` (`text_delta` + `input_json_delta`) / `content_block_stop` / `message_stop`
  - 100ms batch：每 100ms 把 buffer 里累积的 text/json chunk 通过 `on_delta(content_block_index, kind, chunk)` 喂出去
  - 流读完后组装出 Anthropic shape `{role: "assistant", content: [text blocks, tool_use blocks]}`，返回给 `run_conductor_loop`
- `conductor_main_loop.py` `run_conductor_loop` 加新参数 `on_token_delta: Optional[Callable]`：
  - 把 `on_delta` 喂给上面新的 streaming caller
  - 不改 `_record_turn`/`turn_recorder` 现有调用模式
  - LLM call 结束后新增 `_record_turn(kind="llm_response", payload={content, stop_reason, usage})`
- `interfaces/api.py` issue conductor SSE 端点：把 `on_token_delta` 拼成 SSE event `conductor_turn_delta`
- `conductor_main_loop._emit_conductor_status` 改 payload，加 `phase` + `detail` 字段；5 个 emit 点（line 298, 358, 368, 490, 586）按场景填 phase

### 前端

- `frontend/src/lib/api.ts` 给 SSE 事件类型加 `conductor_turn_delta` + `conductor_status`（已有的）
- `frontend/src/features/workflow/ConductorLogPanel.tsx`：
  - 订阅 `conductor_turn_delta`：按 `turn_index + content_block_index` key 维护一个临时 buffer map，渲染"流式打字"区
  - 订阅 `conductor_status`：固定栏展示 phase icon + detail
  - 收到 `conductor_turn`(kind=`llm_response`) 时清掉对应 turn 的临时 buffer
- Decisions tab 历史轮渲染从 `conductor_turns(kind='llm_response')` 取完整内容

## Decision (ADR-lite)

**Context**: Conductor 用户体验问题——发消息后长达 30s 看不到任何反应，永远显示"运行中"。可选 (A) claude-agent-sdk / (B) Conductor 走 claude CLI / (C) 保持自撸只加流式+状态。

**Decision**: 选 C。配套：协议留 Anthropic-compat、流式 100ms batch、turn 结束落盘完整文本（不存逐 token）、状态字段加 phase + detail 简结构。完整状态机 + 前端动画拆到下个子任务。

**Consequences**:
- 优点：1-2 天可交付；MiniMax 继续用；现有 Conductor 工具/loop/tiered memory 一个不动；不挡未来上 SDK（只换 `call_llm_with_tools` 一个文件）
- 风险：MiniMax 的 anthropic-compat 流式行为可能跟官方有微差异（如 `input_json_delta` 是否真发），实施时要 fallback 到非流式
- 留尾巴：完整状态机/动画/进度估算/状态切换日志 = 后续独立任务

## Out of Scope

- 把 task-level CHAT/REFINE/RERUN 加流式（那是 codex/claude CLI 链路，本任务不动）
- 用户发消息立刻打断当前 LLM call（B 选项；后续看需要再做）
- 完整状态机 + 状态切换日志表 + 前端 Stepper/Timeline + 状态切换动画 + 进度条 + 预估剩余时间（**单独子任务**）
- 多协议 LLM 适配（OpenAI / DeepSeek 等独立任务）
- ConductorLogPanel UI 重写

## Technical Notes

- 关键文件：`backend/app/application/llm_runner.py`（`call_llm_with_tools` 改流式；`stream_llm` 是参考）、`backend/app/application/conductor_main_loop.py`（`run_conductor_loop` + 5 个 `_emit_conductor_status`）、`backend/app/interfaces/api.py`（SSE 端点）、`frontend/src/features/workflow/ConductorLogPanel.tsx`（订阅 + 渲染）、`frontend/src/lib/api.ts`（SSE 类型）。
- Anthropic SSE 协议参考：`stream_llm` line 237-303 已经处理了 `text_delta` 和 `message_stop`，需补 `input_json_delta` 和 `content_block_start/stop`。
- Runtime catalog 当前 executor：`minimax`（type=claude, endpoint=`https://api.minimaxi.com/anthropic`, model=MiniMax-M2.7）。Conductor 主循环只走 `executor_type=claude` 这条线。

## Research References

- [`research/claude-agent-sdk-provider-support.md`](research/claude-agent-sdk-provider-support.md) — claude-agent-sdk 对第三方 provider 的支持很有限，MiniMax 等非 Claude 模型不在官方背书范围；故本任务保持自撸 LLM 调用。
