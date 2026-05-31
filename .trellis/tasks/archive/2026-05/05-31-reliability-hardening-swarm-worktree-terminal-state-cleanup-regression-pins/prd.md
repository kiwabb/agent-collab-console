# Reliability hardening: swarm worktree terminal-state cleanup + regression pins

## Goal

补齐 swarm 系统经核实确认的**唯一真可靠性缺口**（conductor 终态不清理残留 swarm worktree → 跨 issue 磁盘/ref 泄漏），并把已验证正确但缺保护的可靠性不变量钉成回归测试，最后归档两个"已完成仅未归档"的停滞任务。

来源：本任务由 plan 阶段对 8 个候选可靠性缺口逐条核实真代码后收敛而来（已批准计划 `~/.claude/plans/sleepy-stargazing-hearth.md`）。**7/8 为伪缺口**（已有基建覆盖），详见 `research/reliability-gap-verification.md`。参见 memory `[[feedback_verify_before_claiming_gaps]]`。

## Requirements

### PR1 — swarm worktree 终态清理（唯一写产品代码）
- 新增 `worktree_manager.py` 幂等方法 `cleanup_issue_swarm_worktrees(project, issue)`：枚举 issue 的 `swarm/<issue>-*` worktree + 分支，复用 `cleanup_agent_worktree`(:224)/`git_service.remove_worktree`/`prune_worktrees` 清理，已不存在的静默跳过。
- 接入 `_seal_graph_and_issue_status`（`conductor_main_loop.py:996-1021`）末尾 best-effort 调用（try/except 包裹，失败只 warning，与现有 `record_project_memory` 容错风格一致）；按 `issue.project_id` 取 project。
- **硬约束**：只删 worktree + `swarm/*` 分支 ref，绝不 merge、绝不碰主仓 main（守 Worktree-Scoped Branch Merge 契约）。

### PR2 — 回归钉子（纯测试）
钉死已亲验正确的不变量：GAP C 终态复活守卫（`conductor_main_loop.py:1095-1120`）、`_is_stale` 活会话守卫（`conductor_recovery.py:117-122`）、`timeouts.check_invariants`（pulse<ttl<idle）、dispatch 重派预算上界（`_check_redispatch_budget` 限 4）。

### PR3 — 归档对账
核对 AC 与现有测试后归档 `05-24-recover-orphan-conductor-state`、`05-24-backfill-conductor-mesh`。

## Acceptance Criteria

- [ ] AC1: `cleanup_issue_swarm_worktrees` 幂等（重复调用/清理不存在 worktree 不报错）
- [ ] AC2: conductor 终态 seal 后，该 issue 的 swarm worktree 目录 + `swarm/*` 分支 ref 被清除
- [ ] AC3: 清理后主仓 `main` byte-for-byte 不变；issue/graph 状态正确
- [ ] AC4: 清理失败不影响终态收尾（best-effort，只 warning）
- [ ] AC5: PR2 不变量回归单测绿（GAP C / _is_stale / timeouts invariants / redispatch budget）
- [ ] AC6: 快档 531+ 不回归；串行 + 并行 swarm 路径零回归

## Definition of Done
- 后端快档 + 相关 slow 集成测试绿
- 不污染 main；遵守 timeouts.py 不变量
- 两个停滞任务归档

## Out of Scope
- 不做 7 个伪缺口（DAG 重试/租约竞态/信号丢失/终态原子/executor 恢复——已有基建覆盖，证据见 research）
- 不改 merge 逻辑本身（已逐行核实正确）
- 不引入机械 back-off 重试（重试交 Conductor LLM 是有意设计）

## Technical Approach

ADR-lite：
- **Context**: conductor 自行 finalize 的 issue，残留 swarm worktree 无清理 owner。
- **Decision**: 在终态收尾 `_seal_graph_and_issue_status` 加 best-effort 幂等清理，复用既有 cleanup 原语，不造 git 新逻辑。
- **Consequences**: 消除跨 issue 资源泄漏；best-effort 不阻断收尾；零 merge/main 风险。

## Technical Notes
- 关键文件：`worktree_manager.py`(:105/:224/:482) `conductor_main_loop.py`(:996) `conductor_tools.py`(:409) `git_service.py`(remove_worktree/prune_worktrees) `test_swarm_integration.py` `test_worktree_manager.py`
- 已批准计划：`~/.claude/plans/sleepy-stargazing-hearth.md`
- 验证依据：`research/reliability-gap-verification.md`
