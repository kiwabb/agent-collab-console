# Research: 可靠性缺口逐条核实 (已亲验真代码)

> 8 个候选缺口对真代码逐条核实。7 个伪缺口，1 个真缺口。第三次印证本库成熟 [[feedback_verify_before_claiming_gaps]]。

## 伪缺口 / 已覆盖（不做）

1. **DAG 单节点失败无重试** — 失败传播链完整：runner except → `workflow_scheduler.on_task_completed` → `task_completion_registry.signal` → Conductor 收到 tool_result。重派由 `_check_redispatch_budget` 限 4 次 + hard_timeout/loop_max 双层兜底。无机械 back-off 是**有意设计**（重试交 Conductor LLM 决策）。

2. **租约过期竞态（心跳非原子）** — `conductor_recovery.py:117-122` `_is_stale` 在判过期前先查 `is_conductor_task_alive`（进程内 ConductorSessionRegistry liveness），**活循环绝不被回收**。启动期 `timeouts.check_invariants` 断言 `pulse < ttl < idle`。

3. **完成信号丢失** — commit `3815f3e` 已闭环：register-before-launch + bounded `_pending` 缓冲 + drain，有专测覆盖。

4. **终态非原子并发 finalize** — GAP C 复活守卫（`conductor_main_loop.py:1095-1120`）阻断离开终态相的非法 phase 跳变。

5. **executor 启动失败恢复** — fail-fast（issue task 无 worktree cwd 拒跑）+ runner except + `main.py:40-72` 启动期孤儿 execution_process/conductor task 恢复，三层覆盖。

6/7. **停滞任务 #7 recover-orphan-conductor-state / #8 backfill-conductor-mesh** — PRD 全部 AC 已满足，分别有 `test_conductor_recovery.py`/`test_stall_watchdog_recovery.py` 和 `test_task_dispatcher.py:290-331` 覆盖。仅 task.json 还挂 in_progress → PR3 归档。

## 唯一真缺口（PR1）

`dispatch_batch` 保留的 per-agent worktree（`swarm/<issue>-<key>`）在 conductor 终态无清理 owner。亲验：

- `conductor_tools.py:400-414`：`_run_one` 的 `cleanup_on_exit` **仅在异常 except 路径**置 True（:401）；正常返回（:392-399）与冲突保留路径**故意留存** worktree 待 merge/reconcile。
- `conductor_main_loop.py:996-1021` `_seal_graph_and_issue_status`：终态收尾只改 graph.status / issue.status + `record_project_memory` + `issue_updated` 事件，**从不碰 worktree**。
- `api.py:402` 调 `cleanup_issue_worktree` 仅在 API merge/delete 路径，**不覆盖 conductor 终态**。
- 现有清理原语齐全可复用：`worktree_manager.cleanup_agent_worktree`(:224)、`cleanup_issue_worktree`(:105)、`prune`(:482)、`git_service.remove_worktree`/`prune_worktrees`。

后果：conductor 自行 finalize/max_wall/relaunch-exhausted 收尾的 issue，残留 swarm worktree + 分支 ref 跨 issue 累积 → 磁盘/ref 泄漏（数据卫生，中严重度，非死锁）。

修复：终态 `_seal_graph_and_issue_status` 末尾加幂等 best-effort `cleanup_issue_swarm_worktrees`，只删 worktree + `swarm/*` ref，绝不碰 main。
