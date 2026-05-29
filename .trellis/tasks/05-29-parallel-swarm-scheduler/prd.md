# Parallel Swarm Scheduler

## Goal

把当前**串行**的 Conductor 编排升级为**真并行 Swarm 调度器**：Conductor 一轮可以同时 dispatch 多个 subagent 并发执行 → 每个 agent 在隔离环境工作避免互相踩踏 → 完成后进入 **join/调和阶段**把多份产物合并。让"Swarm 多 agent 协作"名副其实。成本/预算治理作为调度器的**资源治理层**纳入（对应子任务 [05-29-cost-aware-conductor-scheduling]）。

## 现状（已扒代码 + 研究核实——纠正最初"完全串行"的误判）

> ⚠️ 最初判断"完全串行"是**错的**。并发执行机器**已经在了**，详见 [research](research/parallel-orchestration-patterns.md)。

- **并发执行已存在**：`conductor_main_loop.py:368-380` `_execute_tool_uses` 已对一轮里的多个 tool_use 做 `asyncio.gather` 并发。只要 Conductor 一轮吐 2 个 `dispatch_subagent`，它们就并发跑。`TaskCompletionRegistry` 是 per-task event，天然支持并发 await 多个。
- **系统提示已允许并行**（`:741`）但 `:746` "After each dispatch_subagent returns..." 措辞偏串行，反向引导 LLM 一轮只发一个。
- **真正的踩踏根因 = 共享 worktree**：`worktree_manager.py` 的"一 issue 一 worktree"是**硬编码语义**（docstring 明写 role 串行执行靠共享 worktree 看彼此产物），`task_dispatcher.py:125` 把同一个 `git_worktree_path` 注入每个 task 的 cwd。并行写同一 worktree → 覆盖未提交改动 + git index 竞争。**并行化必须同时改 worktree_manager + dispatcher**。
- **失败语义不明确**：当前裸 `asyncio.gather`（无 `return_exceptions`）→ "fail-fast 但不取消兄弟、丢弃兄弟结果",介于全 abort 和部分 join 之间。
- **本仓库已有参考实现**：`references/vibe-kanban/` 是生产级并行 agent 编排器，per-task worktree + 分叉守卫 + in-memory squash + 结构化冲突上抛，可直接借鉴。
- **git 原语基本够用**：`git_service` 的 `create_worktree`/`squash_merge`(冲突 reset+raise)/`commits_behind`/`commit_all`/`remove_worktree` 已覆盖大部分；唯一缺 `conflicted_files`（一行 `diff --diff-filter=U`）。
- **可视化**：`WorkflowGraph` = Conductor 决策时间线（非 DAG）；`AgentMeshGraph.tsx` SVG 布局。

## 重新校准的真实缺口（这才是要做的）

并行**执行**已有，所以本任务不是"从零造并行",而是"**让并行真正可用且安全**":
1. **隔离**（核心）：per-agent worktree（fork 自 issue 分支）+ 改 dispatcher 注入 agent worktree path。照 vibe-kanban 模式。
2. **Join/reconcile**：在 issue 锁内**顺序** squash_merge 回 issue 分支 + `commits_behind` 分叉检测 + 冲突→Conductor reconcile turn / Approvals。补 `conflicted_files` 原语。
3. **失败语义**：`gather(return_exceptions=True)` 部分 join，失败分支作为坏结果交 reconcile turn 决策。
4. **Prompt 引导**：改写 `:746` 串行措辞,鼓励 fan-out。
5. **资源治理**（子任务 [05-29-cost-aware-conductor-scheduling]）：并发度 = 成本乘子，并发上限 + 预算进 `timeouts.py`。
6. **可视化**：并行批次在 WorkflowGraph / mesh 图分组/泳道。

## 核心设计树（待逐个收敛）

1. **并发表达方式**：Conductor 怎么说"并行派 N 个"？
   - (a) 自然利用一轮多个 `tool_use` block → 并发执行同一轮里的多个 `dispatch_subagent`（最贴合现有协议）
   - (b) 新增 `dispatch_batch` 工具显式批量派发
2. **隔离模型**：并行 agent 编辑冲突怎么避免？
   - per-agent worktree（每个并发 agent 一个 worktree）→ 强隔离，但要解决"N worktree 合并回 issue 分支"
   - 还是 per-role 分目录 / 文件锁 / 只读多写一？
3. **Join / 调和**：N 个并行 agent 完成后产物怎么合？
   - Conductor 一个专门的"reconcile" turn 读所有产物再决策
   - 自动 merge + 冲突上浮给 Conductor/用户
4. **依赖表达**：并行批次里 task 间有依赖吗？纯 fan-out，还是支持批内 DAG（A、B 并行，C 等 A+B）？
5. **失败语义**：N 个并行里挂了 1 个 → 全 abort？继续？部分 join？
6. **资源治理**（= 子任务）：并发数上限、预算/成本作为调度约束、优先级/抢占。
7. **可视化**：并行批次在 WorkflowGraph / mesh 图怎么呈现（并行泳道 / 分组）。

## Assumptions (temporary)

- 仍以单 issue 为调度单元（不跨 issue 并行编排，那是另一个量级）。
- 复用现有 `TaskCompletionRegistry` / `workflow_scheduler` 完成通知机制，扩展成可并发 await 多个。

## Open Questions（待 brainstorm 逐个定）

- 并发表达：复用"一轮多 tool_use"(a) vs 新 `dispatch_batch` 工具(b)？
- 隔离：per-agent worktree（强隔离）vs 共享 worktree + 协调？
- Join：Conductor reconcile turn vs 自动 merge + 冲突上浮？
- 失败语义 + 批内依赖是否纳入 MVP？
- 成本治理纳入 MVP 还是留作并行跑通后的下一阶段？

## 已确认决策（2026-05-29）

1. **并发表达** = 新增显式 `dispatch_batch` 工具（代码控并行度，便于加并发上限/将来挂预算闸）。
2. **冲突处理** = Conductor **reconcile turn** 自动解：冲突文件 + 双方 diff 注入一轮让 LLM 决策。
3. **成本治理** = 不在本 MVP，留第二阶段（子任务 [05-29-cost-aware-conductor-scheduling]）。

## 发散补充的边界（Expansion Sweep）

- **并行是增强、非强制**：保留现有串行路径，`dispatch_batch` 是新增能力；可灰度/回退（旋钮控制是否启用）。
- **批次可能混合 code / 非 code agent**：engineer 产代码需走 worktree+git merge；PM/architect 产 JSON 产物只 persist 到 `result_json`，不需 git merge。reconcile/merge 路径**只对产代码的 agent**生效，非 code 产物按现有方式收。
- **agent worktree 生命周期**：失败/abort 也要清理（`remove_worktree`/`prune_worktrees`），避免泄漏。
- **批次级并发上限**：复用/扩展 `timeouts.py`（现有 `MAX_CONCURRENT_INSTANCES_PER_ROLE` 是 per-role；batch 需要一个 batch 级 fan-out 上限旋钮），进 `validate()` 不变量。
- **reconcile turn 需要的输入**：补 `git_service.conflicted_files` 原语 + 复用 `worktree_diff` 喂 LLM。

## Requirements

- 新增 `dispatch_batch(agents=[{role, prompt, ...}], ...)` 工具：一次声明 N 个独立 subagent，代码层并发起跑（复用现有 `_execute_tool_uses`/registry 机制），受 batch 级并发上限约束。
- `worktree_manager` 新增 `prepare_agent_worktree(issue, agent_key)`：fork 自 issue 集成分支建 per-agent worktree+branch（`swarm/<issue>-<agent_key>`），复用 `_locks` 防并发建同名竞争。
- `task_dispatcher` 改造：并行模式下注入 **agent worktree path** 而非共享 issue worktree path。
- Join：批次完成后在 issue 锁内**顺序** `squash_merge` 各 agent 分支回 issue 分支，每个合并前 `commits_behind` 检测分叉。
- 失败语义：并发 await 用 `return_exceptions=True`（部分 join），失败/超时分支作为坏结果进 reconcile turn。
- 冲突：`squash_merge` 冲突 → 补 `git_service.conflicted_files` 取冲突文件 → 注入 Conductor reconcile turn（LLM 读冲突+diff 决策）。
- Prompt：改写 `conductor_main_loop.py:746` 偏串行措辞，引导合适时机用 `dispatch_batch` fan-out。
- 可视化：WorkflowGraph / mesh 图把同批并行 agent 分组/泳道呈现。
- 现有串行路径保持可用（并行为可选增强）。

## Acceptance Criteria

- [ ] Conductor 经 `dispatch_batch` 能在一个决策点并发启动 ≥2 个 subagent，真实并发（非伪并行）
- [ ] 每个并行 agent 在独立 worktree 工作，文件改动互不踩踏
- [ ] 批次完成后各 agent 产物顺序 merge 回 issue 分支，无丢失/覆盖
- [ ] merge 冲突触发 reconcile turn，LLM 拿到冲突文件+diff 并能产出决策
- [ ] 失败/超时的并行分支不拖垮整批（部分 join），其余产物正常收
- [ ] agent worktree 在完成/失败后都被清理
- [ ] batch 级并发上限旋钮在 `timeouts.py` + `validate()` 不变量
- [ ] 后端单测覆盖：并发派发、顺序 merge、分叉检测、冲突→reconcile、部分 join 失败路径
- [ ] 现有串行流程回归不破

## Definition of Done (team quality bar)

- 后端单测覆盖并发/join/失败路径；`python3 -m pytest` 快档绿
- 前端若改 build + lint + tsc 绿
- 并发/超时旋钮进 `timeouts.py` 单一真相源 + `validate()` 不变量
- CLAUDE.md 架构段更新（串行 → 并行的说明）
- 现有串行行为可回退 / 灰度（并行是增强非强制）

## Decision (ADR-lite)

**Context**：Conductor 并发执行机器（gather over multi-tool_use）已存在，但因共享 worktree 不安全、无 join/失败语义、prompt 偏串行而实际跑不起来。本仓库 `references/vibe-kanban/` 有可借鉴的 per-task worktree 并行编排实现。
**Decision**：做"让并行可用且安全"而非从零造并行——显式 `dispatch_batch` 工具 + per-agent worktree 隔离 + 顺序 squash_merge join + reconcile turn 解冲突 + 部分 join 失败语义；纯 fan-out（不做批内 DAG）；成本治理留第二阶段。
**Consequences**：并行度可控可治理（为成本子任务铺路）；隔离彻底但合并需顺序串行（merge-back 不并行，可接受）；批内依赖靠 Conductor 多轮决策表达；新增 worktree 生命周期管理与清理复杂度；保留串行回退降低风险。

## Implementation Plan（small PRs，纯 fan-out MVP）

- **PR1 隔离地基**：`worktree_manager.prepare_agent_worktree` + `task_dispatcher` 注入 agent worktree path + worktree 清理；单测（建/隔离/清理）。串行路径不变。
- **PR2 批量派发**：`dispatch_batch` 工具 + batch 级并发上限旋钮（`timeouts.py`+`validate()`）+ `return_exceptions=True` 部分 join；单测（并发派发、失败部分 join）。
- **PR3 Join + reconcile**：issue 锁内顺序 `squash_merge` + `commits_behind` 分叉检测 + `git_service.conflicted_files` 原语 + Conductor reconcile turn 接线；单测（顺序 merge、分叉、冲突→reconcile）。
  - ⚠️ **PR1 check 抓出的 PR3 必处理项**：
    1. **agent 分支 lineage 持久化**：swarm 路径下 worktree 实际 base 是 issue 分支，但 `task.git_base_branch` 仍记 project default、per-agent worktree path 未持久化到任何 model。PR3 merge-back 前需明确持久化 agent 分支 lineage（否则无法按存储路径清理/合并）。
    2. **上游产物可见性（关键）**：隔离 worktree 只能看到 fork 时**已 commit 到 issue 分支**的产物。`architect/engineer_workflow`、`codex_task_runner` 从 `task.workspace_path` 读上游 PM/architect 产物——若上游产物只落在共享 issue worktree 未 commit，隔离 agent 读不到。**fan-out 前必须保证上游产物已 commit 或显式同步到 issue 分支**。
- **PR4 引导 + 可视化 + 文档**：改写 prompt 串行措辞、WorkflowGraph/mesh 并行分组、CLAUDE.md 架构段更新；前端 build+lint+tsc。
- **（第二阶段，子任务）** 成本/预算资源治理挂到 `dispatch_batch` 的并发闸上。

## Out of Scope (explicit)

- **成本/预算治理**（子任务 [05-29-cost-aware-conductor-scheduling]，第二阶段）
- **批内 DAG**（依赖表达靠 Conductor 多轮，纯 fan-out only）
- **保留每 agent git 历史 / rebase 线性化**（`git_service` 无 rebase 原语，顺序 squash 足够；要历史另补 `rebase_onto`）
- 跨 issue / 跨 project 并行编排
- 远程 PR、RAG 记忆等其它大方向（各自独立任务）

## Research References

- [`research/parallel-orchestration-patterns.md`](research/parallel-orchestration-patterns.md) — 并发原语(gather)已存在；真缺口=隔离+reconcile turn+失败语义+prompt；MVP 纯 fan-out，join 用"deterministic git merge + 冲突上浮"两层。
- [`research/concurrent-worktree-isolation.md`](research/concurrent-worktree-isolation.md) — per-agent worktree(base=issue 分支) + issue 锁内顺序 squash_merge + 分叉检测是最契合现有 git_service 的最简实现；vibe-kanban 已用同模式可抄；唯一需补 `conflicted_files` 原语。

## Technical Notes

- 关键文件：`conductor_main_loop.py`（tool-use loop，并发执行 tool_use 的改造点）、`conductor_tools.py`（dispatch_subagent / 可能新增 batch）、`task_completion_registry.py`（并发 await）、`worktree_manager.py` + `git_service.py`（隔离与 merge）、`workflow_scheduler.py`（完成回写）、`timeouts.py`（并发旋钮）、`WorkflowGraphView` / `AgentMeshGraph.tsx`（可视化）。
- 子任务：[05-29-cost-aware-conductor-scheduling] 承载资源治理（预算=全局默认+per-issue 覆盖；分模型定价；预算驱动选型）。
