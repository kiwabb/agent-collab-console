# Journal - jackmouse (Part 1)

> AI development session journal
> Started: 2026-05-21

---



## Session 1: Conductor 决策日志可见性 + 静默崩溃修复

**Date**: 2026-05-22
**Task**: Conductor 决策日志可见性 + 静默崩溃修复
**Package**: ccgui
**Branch**: `main`

### Summary

新增 conductor_turns 表（5 kind: llm_request/tool_use/tool_result/finalize/error）+ 2 索引；run_conductor_loop 在 5 个点位写 turn；双层崩溃兜底（run_issue_conductor_loop try/except + auto_start_issue_graph 的 asyncio.create_task done_callback）→ conductor_tasks.status=failed + result_json 含 traceback；新端点 /codex/issues/{id}/conductor-turns；SSE conductor_turn + conductor_failed；前端 ConductorLogPanel 加 Decisions tab + IssueDetailPage 全局 toast；dev-local.sh tee 后端日志到 /tmp/agent-collab-backend.log；CLAUDE.md 加诊断段。验证 298 passed (+2)，frontend build 干净。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `75bcae0` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 2: Conductor 交互式对话 (Steer + Resume)

**Date**: 2026-05-22
**Task**: Conductor 交互式对话 (Steer + Resume)
**Package**: ccgui
**Branch**: `main`

### Summary

用户主动给 Conductor 发消息影响下一轮决策（poll DB 注入 [USER INTERJECTION] user turn）+ mid-call interrupt Pause/Resume（asyncio task.cancel + wake_event）。conductor_turns 加 consumed_at 列 + kind='user_message'；新 conductor_pause_registry.py 单例 _ConductorControl；3 新 API 端点。前端 ConductorLogPanel 加输入框 + Pause/Resume + 状态 chip + user_message 气泡渲染。23/23 conductor test 过，frontend build 干净。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `5e3cc65` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 3: pytest 提速 + Conductor consumed_at hotfix

**Date**: 2026-05-22
**Task**: pytest 提速 + Conductor consumed_at hotfix
**Package**: ccgui
**Branch**: `main`

### Summary

(1) Hotfix: 01454d4 把 conductor_turns consumed_at ALTER TABLE 移到 CREATE INDEX 之前，老 DB 启动不再炸。(2) e30653c 加 @pytest.mark.slow + addopts 默认跳过 + conftest.py 实现 --runslow flag，老 DB → 355/410，--runslow → 410，显式 path 仍跑全量。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `01454d4` | (see git log) |
| `e30653c` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 4: Conductor 流式输出 + phase/detail 实时状态可见

**Date**: 2026-05-22
**Task**: Conductor 流式输出 + phase/detail 实时状态可见
**Package**: ccgui
**Branch**: `main`

### Summary

Conductor LLM 调用从非流式 httpx.post 切到 Anthropic SSE 流式 (call_llm_with_tools_streaming)；100ms batch 聚合 text_delta + tool_use input_json_delta，emit 新 SSE 事件 conductor_turn_delta；turn 结束写一行 conductor_turns(kind='llm_response') 落盘完整文本。conductor_status 加 phase + detail 两字段，8 个枚举覆盖 awaiting_llm/streaming_llm/dispatching_subagent/awaiting_subagent/awaiting_user_clarification/paused/done/failed；前端 ConductorLogPanel 订阅两个新事件实时渲染打字流 + phase 时长，awaiting_subagent>30s 显示 stuck。Brainstorm 阶段验证 claude-agent-sdk 切换不可行 (MiniMax-M2.7 非 Claude，SDK 注入 Claude-only 控制协议会让 anthropic-compat 网关 4xx)，决定保持自撸 httpx。Codex 实施完成后 main agent 派 trellis-check 验证，sub-agent 违反 prompt 指令跑全量 pytest 卡死被 TaskStop；改 inline targeted 验证 11/11 + 静态 grep 6/6 Requirements 全绿。补 commit 7dbf71c 是 Phase 3.4 stage 时遗漏的两个流式专用测试 (test_llm_runner_streaming.py + conductorLogPanelStreaming.test.ts)。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `fe12046` | (see git log) |
| `7dbf71c` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 5: Conductor 完整状态机 + Stepper/Timeline + 预估剩余时间

**Date**: 2026-05-22
**Task**: Conductor 完整状态机 + Stepper/Timeline + 预估剩余时间
**Package**: ccgui
**Branch**: `main`

### Summary

上一任务 (05-22-conductor-streaming-and-live-status, fe12046+7dbf71c) 交付的 phase/detail 基础上升级到完整状态机。后端 conductor_main_loop 加 LEGAL_TRANSITIONS 矩阵 + set_phase 校验 + 违规警告放行（is_legal=0 + emit conductor_state_violation SSE）；新表 conductor_state_log 两份 migration (CREATE TABLE 在 CREATE INDEX 之前)，set_phase 成功后 INSERT 一行带 duration_ms；phase_duration_estimator.py 新模块按 to_phase 算 P50/P95/N + lru cache + done invalidate；api.py 加 GET /conductor-state-log + /conductor-phase-estimates。前端 ConductorLogPanel 加横向 Stepper（framer-motion AnimatePresence + motion.div）当前节点 pulse、failed XCircle error 色、连续 paused 合并成一个节点 + i18n '暂停合并' 提示；PhaseEstimate 显示 '已 32s / ~45s' N<5 加 ~ + 灰 + tooltip 解释置信度、超 P95 进度条变 warning；IssueDetailPage + ExecutionProcessesContext 监听 conductor_state_violation 弹 toast。Codex 完成实施，main agent inline 验证 10 条 R 全绿（15 backend tests + 4 frontend node:test + build 通过 + lint 无 error），避免上次 sub-agent 跑全量 pytest 卡死的教训。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `f7c912d` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 6: Fix conductor streaming not live

**Date**: 2026-05-22
**Task**: Fix conductor streaming not live
**Package**: ccgui
**Branch**: `main`

### Summary

Unified the global realtime event stream onto WebSocket with envelope/ring-buffer resume, removed the SSE endpoint, and fixed the conductor drawer refresh gap with resume_gap handling and regression tests.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `2b9dbc4` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 7: Restore live agent streaming in Issue DispatchDrawer

**Date**: 2026-05-24
**Task**: Restore live agent streaming in Issue DispatchDrawer
**Package**: vibe-kanban
**Branch**: `main`

### Summary

Diagnosed missing live token stream after issue-detail redesign (commit 774963c): IssueDetailPage never mounted AgentLiveTimeline and LiveThinkingDock was orphan dead code. Path 1: embedded AgentLiveTimeline inside DispatchDrawer middle section, reusing useExecutionProcessLogStream via item.task.last_execution_process_id (zero new API, zero copy). Widened drawer 480->560px, added Esc close + stop-task action when running, collapsed SubAgentResult while task still running. Deleted LiveThinkingDock.tsx (245 lines, never imported). Verified: tsc/lint/test/build all green (117/117 tests).

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `914a73d` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 8: Refactor IssueDetailPage into a premium Cyber-Console dashboard

**Date**: 2026-05-29
**Task**: Refactor IssueDetailPage into a premium Cyber-Console dashboard
**Package**: ccgui
**Branch**: `main`

### Summary

Overhauled the frontend Issue Detail Page to lock viewport bounds to 100vh with independent scrolling tabs and side panel, and introduced real-time breathing status indicators with HSL glowing styles.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `eb2b407` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 9: Parallel swarm scheduler: per-agent worktree isolation, dispatch_batch, in-flow join+reconcile, batch visualization

**Date**: 2026-05-29
**Task**: Parallel swarm scheduler: per-agent worktree isolation, dispatch_batch, in-flow join+reconcile, batch visualization
**Package**: ccgui
**Branch**: `main`

### Summary

Upgraded the serial Conductor into a true parallel swarm: dispatch_batch fans out N subagents concurrently (capped, partial-join failure semantics), each in an isolated per-agent worktree forked from the issue branch; on completion they squash-merge back sequentially under the issue lock with conflict→Conductor reconcile. Caught+fixed a real bug where squash_merge would fast-forward agent changes onto main (new swarm-safe squash_merge_into_branch). Added batch_key + parallel-swimlane visualization. 4 PRs, each implement→check→commit; full backend suite 432 passed, frontend tsc clean + 121 tests. Cost-aware governance deferred to subtask (Phase 2).

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `ab70812` | (see git log) |
| `8081b86` | (see git log) |
| `f201e8d` | (see git log) |
| `aee6ecf` | (see git log) |
| `e40764f` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 10: Cost-aware conductor scheduling: per-model pricing, per-issue budget awareness, budget-driven steering

**Date**: 2026-05-29
**Task**: Cost-aware conductor scheduling: per-model pricing, per-issue budget awareness, budget-driven steering
**Package**: ccgui
**Branch**: `main`

### Summary

Phase 2 of the swarm work: made cost a first-class input to Conductor decisions. PR1 per-model token pricing (RuntimeModelConfig price fields + model-aware price_tokens, backward compatible). PR2 per-issue budget (global default + override, idempotent migration both stores) + completed-run spend aggregation injected into the loop's COST/BUDGET prompt block. PR3 budget-driven soft steering: sorted candidate prices + selection guidance, budget_warning/budget_exceeded events, wind-down on overage (no hard kill per ADR), and dispatch_batch concurrency downscaled by remaining budget. 3 PRs each implement->check->commit; full backend suite 495 passed. Captured cost/budget soft-semantics contracts into spec.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `1aa4c7f` | (see git log) |
| `41b988e` | (see git log) |
| `592e187` | (see git log) |
| `9595db5` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 11: E2E validation of parallel swarm + cost-aware: integration test, 2 latent bugs fixed, real-executor run

**Date**: 2026-05-29
**Task**: E2E validation of parallel swarm + cost-aware: integration test, 2 latent bugs fixed, real-executor run
**Package**: ccgui
**Branch**: `main`

### Summary

Validated the parallel-swarm + cost-aware work end-to-end across 3 tiers. Tier 1: deterministic real-git integration test (6 scenarios) driving the real dispatch_batch tool. Tier 1.5: live mock-mode run (real MiniMax brain, mock subagents, throwaway repo) that surfaced TWO latent bugs 500+ unit tests missed — a dispatch completion race (signal-before-register, fixed via register-before-launch + bounded registry buffering) and a no-op merge misclassified as a phantom conflict (fixed via commits_ahead==0 pre-check). Tier 2: real claude CLI agents created module_a/b/c in isolated worktrees, dispatch_batch merged all three into the issue branch (real diffs), main never polluted, 0 worktree leaks, real cost $0.3958 under the $1.0 budget, budget-driven concurrency downscaled to 2. Full suite 507 passed + 7 slow integration.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `cef3034` | (see git log) |
| `3815f3e` | (see git log) |
| `31e6c40` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 12: Engineer real-codegen reconciliation + Architect-Review diff-vs-plan guard

**Date**: 2026-05-31
**Task**: Engineer real-codegen reconciliation + Architect-Review diff-vs-plan guard
**Package**: ccgui
**Branch**: `main`

### Summary

4-PR feature: Architect emits expected_files; deterministic tiered review guard (review_guard.py) hard-rejects claim-vs-reality contradictions before invoking the LLM, soft-injects plan_drift + real diff otherwise; Engineer C1/C2 reconcile to git ground truth; QA D1 independent git check. Two AC4 false-positive bugs (completed_tasks treated as landing signal) caught and fixed during check passes. Fast suite 531 passed, slow integration 14 passed. Committed 2cc5b96 to main.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `2cc5b96` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 13: Reliability hardening: swarm worktree terminal cleanup + regression pins

**Date**: 2026-05-31
**Task**: Reliability hardening: swarm worktree terminal cleanup + regression pins
**Package**: vibe-kanban
**Branch**: `main`

### Summary

Verified 8 candidate reliability gaps against real code: 7 were pseudo-gaps already covered by existing infra (DAG-retry-by-conductor, lease liveness guard, signal register-before-launch, GAP-C terminal guard, startup orphan recovery). One genuine gap: dispatch_batch retained swarm worktrees/branches had no cleanup owner at conductor terminal state -> cross-issue disk/ref leak. PR1 added idempotent best-effort cleanup_issue_swarm_worktrees (real-git enumeration, prefix byte-aligned to creation, zero main pollution) wired into _seal_graph_and_issue_status + git_service.list_branch_names/delete_branch. PR2 pinned previously-uncovered invariants (redispatch budget cap, pulse<ttl). PR3 archived two stalled-but-done tasks (recover-orphan-conductor-state, backfill-conductor-mesh). Fast 540 passed, slow 30 passed. Committed 8ad2f60. Third confirmation this session that the codebase is mature (gap surveys over-claim).

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `8ad2f60` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 14: Unified audit logging: audit_log table + 6 choke-point instrumentation + read API + global viewer

**Date**: 2026-06-01
**Task**: Unified audit logging: audit_log table + 6 choke-point instrumentation + read API + global viewer
**Package**: vibe-kanban
**Branch**: `main`

### Summary

User wanted every call/return/tool/command logged. Verified existing coverage first (conductor_turns, log_events, QA all already complete) — added a unified audit_log table as an additive queryable view per user's choice. PR1: table (both stores) + audit_logger singleton (async bounded queue, drop-newest, loop-aware cross-thread enqueue, best-effort). PR2: 6 choke points (conductor LLM/tool/finalize/error, auto-plan, git, CLI spawn w/ prompt redaction, QA cmds, event_bus w/ double-write skip-set). PR3: GET /codex/audit-log with parameterized filters + keyset cursor pagination. PR4: frontend global Audit Log page (filter/search/paginate/expand) + i18n zh+en + sidebar nav. Each PR implement->check; checks caught cross-thread row-loss + missing conductor error audit. Backend 574 passed, tsc+lint clean. Committed 2522c22 to main.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `2522c22` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 15: Fix audit log time-filter boundary minute exclusion

**Date**: 2026-06-03
**Task**: Fix audit log time-filter boundary minute exclusion
**Package**: ccgui
**Branch**: `main`

### Summary

datetime-local since/until are minute-precision but created_at is microsecond ISO compared lexicographically, so an until of HH:MM dropped boundary-minute events. Added pure helpers (timeBoundary.ts) normalizing since->:00 and until->:59.999999 (inclusive, idempotent for second-precision values), wired into AuditLogPage filters, with node:test unit coverage. trellis-implement + trellis-check passed; tsc/tests/lint green. Archived unrelated stub task 05-24-complete-frontend-i18n per user request.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `6376dc9` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 16: Project review background loop

**Date**: 2026-06-08
**Task**: Project review background loop
**Package**: ccgui
**Branch**: `codex/archive-project-review-background-loop`

### Summary

Added a cancellation-safe background loop for scheduled project reviews, wired it into FastAPI lifespan, centralized cadence/limit knobs, updated backend specs, verified locally and merged PR #7.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `3cc5130` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 17: Project review scheduler status

**Date**: 2026-06-08
**Task**: Project review scheduler status
**Package**: ccgui
**Branch**: `codex/archive-project-review-scheduler-status`

### Summary

Added safe project review scheduler operational status, exposed it through diagnostics, documented backend contract, verified locally, and merged PR #9.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `ad2fef8` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 18: GitHub PR follow-up diagnostics

**Date**: 2026-06-08
**Task**: GitHub PR follow-up diagnostics
**Package**: ccgui
**Branch**: `codex/archive-github-pr-followup-diagnostics`

### Summary

Added a safe in-memory GitHub PR follow-up sweep status snapshot, exposed it in diagnostics, covered success/failure transitions with backend tests, and updated the backend quality spec. PR #11 merged with CI green.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `f9aa0f9` | (see git log) |
| `90f613b` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 19: Diagnostics supervisor health

**Date**: 2026-06-08
**Task**: Diagnostics supervisor health
**Package**: ccgui
**Branch**: `codex/archive-diagnostics-supervisor-health`

### Summary

Added diagnostics health derivation so GitHub PR follow-up and project review scheduler snapshots degrade global diagnostics when they report last_error or running=true. PR #13 merged with CI green.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `e6955fb` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 20: Project review scheduler stale health

**Date**: 2026-06-08
**Task**: Project review scheduler stale health
**Package**: ccgui
**Branch**: `codex/archive-project-review-scheduler-stale-health`

### Summary

Merged PR #15 for read-only project review scheduler stale diagnostics. Scheduler health now degrades when last_completed_at is older than interval_s * 2 while preserving last_error and running precedence; backend diagnostics tests and quality gates passed before merge.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `6d42404` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 21: Conductor PR follow-up sweep

**Date**: 2026-06-08
**Task**: Conductor PR follow-up sweep
**Package**: ccgui
**Branch**: `codex/conductor-pr-follow-up-sweep-main`

### Summary

Verified the already-merged scheduled review PR follow-up sweep: ProjectConductor scheduled reviews run sweep_project_github_prs with auto_merge=True, include the summary in result_json and hot memory, and report sweep failures best-effort without failing the conductor task. Archived the completed Trellis task.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `c5293f0` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 22: Archive completed autonomy pipeline tasks

**Date**: 2026-06-08
**Task**: Archive completed autonomy pipeline tasks
**Package**: ccgui
**Branch**: `codex/archive-completed-autonomy-tasks`

### Summary

Verified and archived four already-merged Moonshot autonomy slices: conductor policy intelligence, GitHub PR follow-up automation, GitHub PR auto-merge gates, and project review scheduler tick. Focused tests for conductor policy/self-improvement, PR follow-up/auto-merge, and project review scheduler passed; full backend suite passed with existing aiosqlite event-loop warnings.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `253d2df` | (see git log) |
| `2950cbc` | (see git log) |
| `44a2db7` | (see git log) |
| `57e5414` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 23: Workflow failed node auto retry

**Date**: 2026-06-08
**Task**: Workflow failed node auto retry
**Package**: ccgui
**Branch**: `codex/archive-workflow-failed-node-auto-retry`

### Summary

Merged PR #19 adding bounded automatic retry for failed workflow-backed tasks. Failed nodes with retry budget create a fresh retry task on the same node, emit retry observability events, and fall back to existing failed-node behavior when exhausted or retry dispatch fails. Focused scheduler tests and the full backend suite passed.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `530776d` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 24: Implementation diff completion guard

**Date**: 2026-06-08
**Task**: Implementation diff completion guard
**Package**: ccgui
**Branch**: `codex/archive-implementation-diff-guard`

### Summary

Added scheduler-level diff completion guard for workflow-backed Engineer nodes. A deterministic Engineer claim-vs-empty-git-diff contradiction is now persisted as a failed task, emits workflow_node_diff_guard_failed, and reuses workflow node auto-retry before review/QA. Verified with focused scheduler/reconciliation tests, full backend pytest, import smoke, py_compile, and diff check.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `ac5c0ca` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 25: Self-improvement proposal review API

**Date**: 2026-06-08
**Task**: Self-improvement proposal review API
**Package**: ccgui
**Branch**: `codex/archive-self-improvement-proposal-review-api`

### Summary

Added a status-only review API for self-improvement proposals, including sync/async store load and status update methods, project-scoped PATCH transition handling, backend contract docs, and tests. PR #23 merged after backend and frontend CI passed.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `def982b` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 26: Self-improvement apply plan API

**Date**: 2026-06-08
**Task**: Self-improvement apply plan API
**Package**: ccgui
**Branch**: `codex/archive-self-improvement-apply-plan`

### Summary

Added a non-mutating apply-plan endpoint for accepted self-improvement proposals. The API returns dry-run project-memory append candidates or reviewed PR/task candidates for other target kinds, with tests and backend contract updates. PR #25 merged after CI passed.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `7695be6` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 27: Reviewed self-improvement memory apply

**Date**: 2026-06-08
**Task**: Reviewed self-improvement memory apply
**Package**: ccgui
**Branch**: `codex/archive-self-improvement-apply-execute`

### Summary

Added a hash-gated reviewed apply endpoint for accepted project_memory self-improvement proposals, keeping apply-plan dry-run-only while allowing reviewed team-notes application with tests and backend spec coverage.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `42c1716` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 28: Self-improvement application audit rollback

**Date**: 2026-06-09
**Task**: Self-improvement application audit rollback
**Package**: ccgui
**Branch**: `codex/archive-self-improvement-apply-audit`

### Summary

Added durable self-improvement application events, applications listing, reviewed project-memory apply audit recording, rollback endpoint, rollback service tests/API tests, and backend database spec contracts.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `6720596` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 29: Benchmark eval self-improvement proposals

**Date**: 2026-06-09
**Task**: Benchmark eval self-improvement proposals
**Package**: ccgui
**Branch**: `codex/archive-self-improvement-benchmark-eval`

### Summary

Added deterministic benchmark_eval self-improvement proposal extraction for completed capability issues without benchmark/eval evidence, locked non-memory apply-plan behavior to open_pr_task, updated backend/design specs, and merged PR #31 after CI passed.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `509aa0e` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 30: Activate self-improvement proposal tasks

**Date**: 2026-06-09
**Task**: Activate self-improvement proposal tasks
**Package**: ccgui
**Branch**: `codex/archive-self-improvement-pr-task-activation`

### Summary

Added the reviewed activate-task API for accepted non-memory self-improvement proposals, with idempotent Codex issue/worktree creation, open_pr_task application events, failure audit coverage, backend ledger spec updates, CI-green PR #33, and task archival.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `e39c9dc` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete
