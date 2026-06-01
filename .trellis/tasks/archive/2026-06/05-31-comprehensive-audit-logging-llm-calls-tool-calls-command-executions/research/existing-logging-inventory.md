# Research: 现有日志/审计基建清单 (已亲验真代码)

> 用于本任务"统一 audit_log + UI"的埋点定位与不重复造轮子。本库成熟，区分已记录 vs 真缺口。

## 已完整记录（保留，不重做；audit_log 为附加统一视图）
- **Conductor LLM 请求/响应** → `conductor_turns`：kind=`llm_request`(content/message_count, `conductor_main_loop.py:1065`)、`llm_response`(content/stop_reason/usage, `:272-274`)。写入 `persist_turn`/`_record_turn`(`:457-474,569`)，store `save_conductor_turn`(`sqlite_store.py:1835-1856`)。payload 8000 字符截断(`:1048-1054`)。
- **Conductor 工具** → `conductor_turns`：`tool_use`{id,name,input}(`:305-310`)、`tool_result`{id,name,result,is_error}(`:329-335`)。
- **role agent 元数据** → `execution_processes`：executor/provider/model/input_tokens/output_tokens/cache_read_tokens/total_cost_usd/exit_code/status(`async_sqlite_store.py:190-208,1719-1733`)。**不含 request/response 全文**。
- **CLI 子进程 stdout/stderr** → `log_events`(stream/content/task_id/execution_process_id/created_at, `async_sqlite_store.py:180-189`)，经 `event_bus._db_worker` 异步落库(`event_bus.py:32-48`)。逐行粒度。
- **QA 命令** → task.result + 磁盘：`commands_run`(`qa_workflow.py:204-206`)、`execution_results`{command,exit_code,stdout,stderr,duration_s,refused}(`:343`)。
- **phase 跳变** → `conductor_state_log`(from/to_phase, duration_ms, is_legal, `:1082-1093`)。
- **项目审计** → `project_audit`(project_id,issue_id,event,sha,base_branch, `async_sqlite_store.py:1433-1448`；调用点 api.py:309,2605,3189,3255,3344,3543,3633)。仅摘要。
- **Python logging**：`main.py:9-13` basicConfig INFO→stderr；`/tmp/agent-collab-backend.log` 由 dev-local.sh 重定向。纯文本，无结构化/轮转。

## 真缺口（本任务 audit_log 要覆盖的埋点）
- 🔴 **git 命令**：`git_service._run`(`:65-97`) 零 logging/落库。
- 🔴 **通用事件持久化**：EventBus 内存环形缓冲 maxlen=1000(`event_bus.py:10-20`)，仅 stdout/stderr 写 log_events；conductor_turn/batch_started/budget_* 等只 WS 推送，刷新即丢历史。
- 🟠 **CLI 完整命令行**：`claude_process_runtime._spawn_process_async`(`:219-267`) 拼 `claude -p --model/--resume/...` + cwd，但不落 execution_processes（需多表推导）。
- 🟠 **Auto-plan LLM 调用**：`llm_runner.py`(WARNING 级 stderr，`:25,140,170,195,198`)，不入 conductor_turns。
- 🟡 流式 token delta 不持久化（设计）；log_events 行不关联 tool_use/turn；`conductor_decisions` 表存在但调用点稀少疑过时。

## 复用点（埋点 + 异步写）
- 异步非阻塞写模式：抄 `event_bus.py:_db_worker` 队列 → store。audit_logger 单一入口同款。
- store 层加表/读法：`async_sqlite_store.py` / `sqlite_store.py`（两份需同构，看现有 save_* 对照）。
- 大 payload 截断：抄 `conductor_main_loop.py:_prepare_payload`(8000 限 + __truncated__)。
