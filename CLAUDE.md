# CLAUDE.md

## Commands
```bash
./dev-local.sh                                          # 同启前后端 (前 4000 / 后 9000)
cd backend && python3 -m pytest -v                      # 默认快档，跳 @pytest.mark.slow
cd backend && python3 -m pytest --runslow -v            # 全量
cd backend && python3 -m pytest tests/test_foo.py -v    # 点名文件不受 slow 跳过影响
cd frontend && npm test
cd frontend && npm run build && npm run lint
```
后端日志同步到 `/tmp/agent-collab-backend.log`。

## Stack
FastAPI+aiosqlite(9000) / Next.js14+Tailwind v4+Base UI(4000) / SQLite(`console.db`)+磁盘 JSON 产物。

## Architecture (Conductor-driven)
Issue 创建 → `auto_start_issue_graph` 起空 `WorkflowGraph` + 后台 `run_issue_conductor_loop(issue)` → Conductor 用 Anthropic tool-use 决定调谁。**没有固定 DAG**，流水线 = Conductor 决策序列。

**核心工具**（`conductor_tools.py`）：
- `dispatch_subagent(role, prompt?, prev_node_key?)` → `task_dispatcher.dispatch_role` 建 `CodexTask` + add `WorkflowNode/Edge` + 写一条 `AgentMessage(handoff)` 给 Mesh + 启 task runner；`TaskCompletionRegistry` (asyncio.Event 单例) await 完成 (900s timeout)。**串行路径**：跑在共享 issue worktree。
- `dispatch_batch(agents=[{role,prompt?}])` — **并行 swarm fan-out**：一轮并发起 N 个独立 subagent (`asyncio.gather`, `return_exceptions=True` 部分 join，`MAX_PARALLEL_DISPATCH_PER_BATCH` 限并发)，每个跑在**隔离 per-agent worktree** (`worktree_manager.prepare_agent_worktree`，fork 自 issue 分支，`swarm/<issue>-<key>`)。fan-out 前先 `commit_issue_worktree` flush 上游产物到 issue 分支(否则隔离 agent 看不到)。批次完成后 **in-flow join**：issue 锁内顺序 `merge_agent_worktrees` squash_merge 各 agent 分支回 issue 分支(分支 lineage 内存传递不持久化)；冲突→`squash_merge` reset+raise→`git_service.conflicted_files`+`worktree_diff` 收集→`merge_status=conflict`/`conflicts:[{agent,files,diff}]` 返回，Conductor 下一轮 LLM 决策(重派 resolver / `request_user_clarification`)。**遇冲突即停止后续 merge**，已成功的不回滚。纯 fan-out 无批内 DAG；串行路径零回归。同批 agent 共享一个 `WorkflowNode.batch_key`(`batch-<hex>`，`dispatch_role` 透传)，前端 `WorkflowGraphView` 据此在节点后画**并行泳道**分组框 (i18n `issue.dag.parallelBatch`)；串行节点 batch_key=None 不分组。
- `spawn_custom_subagent` — 注册项目专属 specialist
- `request_user_clarification` — 走 `awaiting_review` 状态对接 Approvals 页
- `retrieve_cold_memory` / `finalize_task`

**用户插话**：`POST /api/codex/issues/{id}/conductor/message` 以 `[USER INTERJECTION]` 注入下一轮；`/conductor/pause|resume` 控制 loop。

**Executor 路由** (`codex_process_manager.py`): `task.executor=codex|claude` 分发到 Runtime；`task.provider/model` 选 API 配置；`runtime_catalog_settings` 表存 catalog 默认 (task 级 > catalog)。

## Run kinds (`ExecutionProcess.kind`)
- `initial` / `rerun` → 用 role workflow prompt 并 persist 产物
- `refine` → 现有产物 + 修改指令重 persist
- `chat` → 极简 prompt，CLI 续接历史，**不**改 `task.result` / **不** persist
- 端点：`POST /api/codex/tasks/{id}/chat|refine|rerun`

## 实时通信
全局 WS `/api/ws/events`，envelope `{v, ts, event_id, type, payload}`，`EventBus` ring buffer + `last_event_id` resume。per-workspace WS 仅做 execution process JsonPatch / task chat / raw log 等 task 级流。

## 核心闭环
- **QA 真跑命令** (`qa_workflow.py`): 在 worktree cwd 执行 LLM 提议的 `recommended_commands`，安全过滤 (rm -rf/sudo/git push 拒) + 单条/总预算超时；任一非零退出强制 `failed` (不信 LLM 自报)；失败摘要落盘供下次 engineer prompt 用
- **项目记忆**: `<repo>/.agent-collab/team_notes.md` issue 完成后 `project_memory_service` 抽 deterministic 摘要 append (无 LLM 调用)；下个 issue 每个 role prompt 顶部注入 "TEAM CONTEXT"；超 16KB 丢最旧 block
- **Agent 提问**: role JSON schema 有 `clarification_question`；触发时 task → `awaiting_review` + `review_comment="[CLARIFY] ..."`；Approvals 页提交答案走 `POST /api/codex/tasks/{id}/answer` 重 dispatch
- **Tiered memory** (`project_conductor.py`): hot/warm/cold；启动注入 pinned+warm+hot；运行中 `retrieve_cold_memory`
- **Specialist mesh** (`specialist_orchestrator.py`): Engineer 自触发 specialist 走 parent/child pause/resume，不绕 Conductor
- **项目仓库更新检测** (`git_service.fetch/fast_forward/remote_status` + `project_service.remote_status/fast_forward_pull`): `GET /api/projects/{id}/remote-status?fetch=` 报告默认分支 vs `origin/<branch>` 的 behind/ahead/dirty/can_fast_forward (降级态走 `error` 字段不抛 500)；`POST /api/projects/{id}/pull` **仅 fast-forward** (干净+在默认分支+ahead==0+behind>0)，不可 ff 时 409+`reason` 且仓库零改动 (无 stash/force)。前端 ProjectsPage 卡片头部「检查更新/同步」按钮 + 分支行 `RemoteUpdateBadge`，选中项目进页即 fetch 一次后每 5min 轮询 (`projectRemoteStatus.ts` 纯函数派生 badge/toast 文案)
- **项目一键启动 dev server** (`project_run_manager.py` 单例，**纯 in-memory 不持久化**，app 关停 hook `shutdown_all()` 杀残留): Project 加持久 `run_command` 字段 (PATCH `/api/projects/{id}` 可改)；每项目单实例 `asyncio.create_subprocess_shell(start_new_session=True)` 独立进程组，stop 走 `killpg` SIGTERM→grace→SIGKILL；stdout/stderr reader task 打 tag 进 `deque(maxlen=2000)` ring buffer (单调 seq、单行裁 2000 字)；命令复用 `command_safety.refuse_reason` (与 QA 共享拒 rm -rf/sudo/git push)；env 继承但剔 `CODEX_*`/`SQLITE_DB_PATH`。端点：`POST /api/projects/{id}/run/start` (409 reason∈`no_run_command`|`already_running`|`refused`[带 `pattern`]) / `run/stop` (幂等) / `GET run/status` / `GET run/logs?after=<seq>` (增量)。**Out of scope**: WS 实时流(前端轮询)、跨重启恢复、多实例、自动重启
- **Agent 驱动 .env 自举** (`env_materializer.py` + `project_script_suggestions.py` env_vars): 运维工程师 Agent 产出 `env_vars` 数组 (name/value/secret/source)，确定性层 `merge_env_vars` 合并 Agent 默认值 + `project_env_vars` 表用户手填值 (用户优先)，`validate_merged_vars` 校验 secret 必填项 (缺失则阻断启动返回 `EnvValidationError[]`)，`materialize_env_file` 幂等写 `.env` 到项目根。`project_run_manager.start()` 前置从库取 stored vars 物化 `.env` + 校验；`POST /projects/{id}/env` (GET/PUT/DELETE) 管理面板；前端 ProjectShell nav 第四项「环境配置」。secret 红名检测 `is_secret_name` (轻量 heuristics 仅双重校验 Agent 分类)，绝不自动填 secret。密钥 `CONSOLE_ENCRYPTION_KEY` + Fernet (`env_crypto.py`) 加密入库。旧 `env_detection.py` 已废弃。
- **结构化原型编辑 Studio** (`structured_prototype_service.py` + `structured_prototype_api.py` + `structured_prototype_ai_service.py` + `structured_prototype_generation_service.py`): 真正的结构化编辑，**不是** regenerate-from-prompt。文档模型 = `prototype_documents` 挂 `prototype_drafts`（活跃草稿），编辑原语是 **event-sourced 命令批次**：`POST /api/structured-prototype-drafts/{draft_id}/commands` → `service.apply_command_batch`（`structured_prototype_service.py:2071`）执行 ~25 种 `DomainCommandV1`，含完整 operation 生命周期（queued→running→succeeded）、`validate_command_batch_evidence_context`、snap attestation、journal 前缀哈希推进、replay manifest。Freeform move 的几何权威是 checked TypeScript snap worker（`prototype_snap_worker.mjs` + manifest），Python 不算 snap 几何只校验哈希（见 `.trellis/spec/vibe-kanban/backend/structured-prototype-snap-attestation.md`）。表：`prototype_objects/operations/operation_steps/operation_events/documents/drafts/checkpoints/command_batches/ai_threads/ai_messages/ai_edit_runs`。前端 `frontend/src/features/prototype/structured/`: canvas 编辑器（dnd-kit 拖拽/resize）+ `StructuredPrototypeInspector` 属性编辑（`key={documentHash}` remount，仅 `onApply` 落库，切节点/页/AI apply 前有 dirty guard 确认）+ `StructuredPrototypeAiPanel`（AI run 预览/apply）+ `StructuredPrototypeGenerationPanel`（项目级生成）+ `StructuredPrototypePreview/ShareViewer/ReleaseHistory`。iframe 预览统一 `sandbox="allow-scripts"`（**不给 `allow-same-origin`**），renderer 产出 HTML 由后端设 strict CSP（`script-src 'self'`）。**AI 编辑路径** (`StructuredPrototypeAiService.apply`): AI run 是 fire-and-forget supervisor（`asyncio.create_task`，客户端断连不停），产出命令批次 candidate + `candidate_object_hash` 校验，apply 时整体替换 draft（新 documentHash），基于 `base_head_sequence_no` 乐观并发，冲突 409 `ai_run_conflict`；AI apply 复用 `service.validate_and_attest_command_batch_evidence`（与用户路径共享 evidence-context 校验 + snap attestation），但走自己的 `store.apply_ai_edit_run`（原子写 run/message/`ai_apply` checkpoint/candidate-object）+ AI 专属 replay manifest（含 agent identity/submission/contextManifestHash）+ reproducibility check（`execution.result_document_hash == run.candidate_object_hash`）；`BEGIN IMMEDIATE` + partial unique index 兜底单活跃 run。**运行时渲染**: `PrototypeRuntimeWorker`（Node checked worker，`describe/initialize/apply/replay`，deadline `PROTOTYPE_RUNTIME_WORKER_TIMEOUT_S` 默认 30s）+ `PrototypeRendererExecution` 产出 `index.html/runtime.js/styles.css/document.json` artifact。启动期 `recover_interrupted_publications` / `recover_interrupted_runs` / `recover_interrupted_jobs` 恢复中断态。3 个 router: `structured_prototype_router` / `structured_prototype_ai_router` / `structured_prototype_generation_router`。**Out of scope**: 多文件 React/Vite 沙箱（`framework` 字段预留）、设计系统选择、多屏联动、协作共享
- **结构化原型发布历史 + 回滚** (`structured_prototype_api.py`): `GET /api/structured-prototype-documents/{id}/revisions` 列出有 ready 归档产物的发布版本 (倒序 + `isCurrent` + `artifactPath`，中断发布留下的无产物 revision 被过滤) + `events[]` 发布时间线 (publish 事件来自 revisions、rollback 事件从 succeeded `rollback_publication` operation 的 step evidence_ref 反解目标版本号)；`POST .../rollback` (kind=`rollback_publication`，完整 operation 框架：幂等重放 + `expectedCurrentRevisionNo` 乐观并发，409 `publication_state_conflict`/`rollback_target_current`) 把 `published_revision_no` 指回目标版本——**复用归档产物不重渲染**，分享链接即时生效，草稿不受影响；`GET .../revisions/{no}/diff[?against=]` 确定性结构 diff (`structured_prototype_revision_diff.py` 纯函数吃归档 canonical JSON，不重验 pydantic：页面增删改 + 页内节点计数 [children 折叠成子 id 列表防深层编辑级联] + tokens/settings/navigation/runtime/组件定义变更标记，`against` 缺省取上一个已发布版本)。publish 请求可带可选 `summary` (1–200 字，**元数据不进 request hash**——崩溃重试换文案仍能幂等回放) 作为 revision 发布说明。前端：Studio 顶栏 History 按钮 → `StructuredPrototypeReleaseHistory` 对话框 (列表 + iframe 回看 + 恢复为当前版本)；分享页 `/prototype-share/{documentId}` 浮动版本切换器只读回看 (`StructuredPrototypeShareViewer`)。**新增 operation kind 要同步三处**：domain `PrototypeOperationKind` Literal、replay manifest `from_canonical_json` 的 kind 集合、store `_operation_from_row` 的 `_literal` 元组——漏掉 manifest 那处会在写入时被 strict read-back 拒掉

## Gotchas
- **Tailwind v4**: `bg-popover` 类需 `@theme` 中 `--color-popover: var(--popover)` 别名，仅 `:root` 定义不够
- **Base UI Select**: `alignItemWithTrigger=false`；Icon/ItemIndicator 用 children 不用 render prop
- **i18n**: `useI18n().t("key")`，key 在 `frontend/src/lib/i18n.ts`
- **WorkflowGraph 是 Conductor 决策时间线可视化**，不是预设 DAG；同 role 多次调度 node_key 加 `#N`

## Env vars
`REAL_CLI=true` (默认；false→mock) / `CODEX_LAUNCH_ENABLED=true` / `QA_EXECUTE_COMMANDS` (跟 REAL_CLI 同源) / `QA_COMMAND_TIMEOUT_S=120` / `QA_TOTAL_BUDGET_S=300` / `CODEX_WORKSPACE_ROOT` / `SQLITE_DB_PATH` / `CLAUDE_CMD` (默认 "claude") / `CODEX_CMD` (默认 "codex") / `CONSOLE_ENCRYPTION_KEY` (Fernet 密钥；`python -m app.application.env_crypto` 生成；未配时 secret 类 env var 无法加密存储)
- 并发/超时旋钮集中在 `timeouts.py` (启动期 `validate()` 校验不变量)：`MAX_CONCURRENT_INSTANCES_PER_ROLE=3` (同 role 跨 issue 进程级并发上限，`dispatch_subagent` 占 slot 跑完释放，满则返回 `status=role_busy`) / `CONDUCTOR_ROLE_SLOT_WAIT_S` (等不到 slot 的超时，默认=`CONDUCTOR_SUBAGENT_MAX_S`) / `CONDUCTOR_LOOP_MAX_S=7200` (整个 conductor loop 墙钟上限，0 禁用；命中 → `status=max_wall` 按 failed 收尾)
- 成本/预算旋钮也在 `timeouts.py`：`DEFAULT_ISSUE_BUDGET_USD=5.0` (per-issue 预算全局默认；issue 不填 `budget_usd` 则用它，0=无上限) / `BUDGET_SOFT_WARN_RATIO=0.8` (软警告阈值比例，∈(0,1]) / `EST_COST_PER_AGENT_USD=0.50` (粗略单 agent 成本估计，仅用于按预算压缩 `dispatch_batch` 并发，不影响真实计费)。`price_tokens` 分模型定价回落 `COST_USD_PER_M_INPUT=0.30`/`_OUTPUT=1.20`/`_CACHE_READ=0.075`

## Cost-aware scheduling
- **成本感知 (PR2)**：`CodexIssue.budget_usd` (per-issue USD 上限，None=全局默认)；`budget_service.py` 按 issue 聚合**已完成** `ExecutionProcess.total_cost_usd` (status ∈ Completed/Failed/Killed，跳过 Running 避免重复计)，`conductor_main_loop.py` 每个 loop run 把「已花/预算/剩余」`## COST / BUDGET` 块注入系统提示。
- **预算驱动行为 (PR3，软语义，不硬杀)**：
  - **选型引导**：`collect_candidate_model_prices(catalog)` 把 catalog enabled 模型的单价 (PR1 价格字段) 按 output→input 价**便宜→贵排序**注入 `## COST / BUDGET` 块 (无价模型用 `env` 标记排末)；prompt 引导预算充足选强模型、紧张选便宜。
  - **软警告 / 收尾**：消费 `IssueBudgetStatus.soft_warn`/`over_budget`。达 `BUDGET_SOFT_WARN_RATIO` → 块升级为 `BUDGET WARNING` (优先便宜/减派) + 发 `budget_warning` 事件；超上限 → `OVER BUDGET` 强引导尽快 `finalize_task`、不开新昂贵 dispatch + 发 `budget_exceeded` 事件。**loop 不被硬杀** (硬杀是 `CONDUCTOR_LOOP_MAX_S`/max_wall 的事)。`budget_usd=0`(unlimited) 全部不触发。
  - **并发按预算下调**：`dispatch_batch` 有效并发 = `timeouts.budget_supported_concurrency(remaining, configured_cap)` = `min(MAX_PARALLEL_DISPATCH_PER_BATCH, floor(remaining/EST_COST_PER_AGENT_USD))`，至少 1；over_budget 压到 1；unlimited 不压缩 (仅下调、永不上调)。`batch_started` 事件带 `configured_cap`+`concurrency_cap` 供观测。

## 诊断 Conductor
- 后台异常 → `conductor_tasks.status=failed` + traceback 写 `result_json`
- 完整 LLM 响应 / tool_use / tool_result / finalize → `conductor_turns`；流式增量只走事件不写库
- `conductor_status` 事件 + `/conductor-state` 带 `phase + detail` (`awaiting_llm/streaming_llm/awaiting_subagent/paused`)
- phase 跳变写 `conductor_state_log`；非法跳变只告警 + 发 `conductor_state_violation`；`LEGAL_TRANSITIONS` 在 `conductor_main_loop.py`
