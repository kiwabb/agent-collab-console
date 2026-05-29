# Research: Parallel Fan-out + Join/Reconcile + Failure Semantics in Multi-Agent Systems

- **Query**: 生产级多 agent 系统如何做并行 fan-out + join/调和 + 失败语义，并映射到本项目 Conductor (Anthropic tool-use loop / asyncio / 单 issue 调度单元)
- **Scope**: mixed (external system survey + internal code grounding)
- **Date**: 2026-05-29

> 注意：本环境未提供 exa/web 搜索工具，下述外部系统对比基于已建立的公开架构知识（Anthropic multi-agent research 工程博客、LangGraph/CrewAI/AutoGen/OpenAI Swarm 文档与源码语义），非本次实时抓取。结论级别的设计语义稳定可用；具体 API 名/版本请在落地前对官方文档二次核对。

---

## 0. 内部基线（先纠正 PRD 的"完全串行"表述）

扒代码发现现状与 PRD 描述**有出入**，这对方案选型是 load-bearing 的：

- `conductor_main_loop.py:368-380` `_execute_tool_uses` **已经**对一轮里的多个 tool_use 做 `asyncio.gather` 并发执行：
  ```python
  if len(tool_uses) == 1:
      return [await _execute_tool_use(tool_uses[0], tools)]
  return list(await asyncio.gather(*(_execute_tool_use(tu, tools) for tu in tool_uses)))
  ```
- `conductor_main_loop.py:741` 系统提示已写 "You may dispatch several INDEPENDENT subagents in a single turn (multiple `dispatch_subagent` calls at once)"。但 `:746` 又写 "After each dispatch_subagent returns, analyze..."（措辞偏串行，会反向引导 LLM 一轮只发一个）。
- `task_completion_registry.py` 是 **per-task** event（`register(task_id)` / `wait_for_active(task_id)`），多个 dispatch 各自 await 自己的 event，**天然支持并发 await**，不是单事件瓶颈。

→ 结论：**并发原语（option a：一轮多 tool_use + gather）几乎已具备**。真正缺口在 (1) prompt 没有强引导并行、(2) **隔离**（共享 per-issue worktree 会踩踏）、(3) **显式 join/reconcile 步骤**、(4) **失败语义**（gather 默认行为 vs 期望行为）。下面外部对比聚焦这四点。

---

## Findings

### 对比矩阵（4 个代表性系统/模式）

| 维度 | Anthropic Multi-Agent Research (orchestrator-worker) | LangGraph | CrewAI | OpenAI Swarm / AutoGen |
|---|---|---|---|---|
| **并发表达** | LLM 一轮**多 tool_use block 并发执行**子 agent（与本项目 option a 同源） | 图原语：`Send` API 做动态 map（fan-out），或并行边（多出边自动并发） | 显式 `async_execution=True` 的 task + `Process.hierarchical/sequential`；kickoff_for_each 做 batch map | Swarm: handoff 单线为主，无原生 fan-out；AutoGen: GroupChat / 显式并行 agent 调用 |
| **Join/调和** | 专门的 **synthesis/lead agent reduce 步骤**（orchestrator 读所有子结果再合成），不是自动 merge | reducer 函数在 state channel 上 merge（`Annotated[list, operator.add]`）；join 节点等所有入边 | hierarchical manager agent 汇总，或下游 task 把多个 context 作为输入 | 由收口 agent 显式读取多份输出后续写 |
| **失败语义** | 子 agent 失败 → orchestrator 看到错误后**重试/换策略**（agent 级 retry，不全 abort） | 节点级 `retry_policy`；分支异常默认冒泡，可用 try 节点 / fallback 边 | task 级 retry + guardrail；一个 task 失败默认中断 crew（可配 `respect_context_window` 等容错） | 通常单分支失败由编排 agent 决策重试或降级 |
| **批内依赖 (DAG)** | 纯 fan-out 为主（同层 worker 独立），层间靠 orchestrator 串接 | **完整 DAG**：节点+边显式依赖，`Send` 也可链式 | task 间 `context=[task_a, task_b]` 表达依赖，支持有向依赖 | AutoGen 可编程 DAG；Swarm 偏线性 handoff |

---

### 1. 并发表达：LLM 一轮多 tool_use vs 显式 batch 原语

- **Anthropic 自家 multi-agent research 系统**（orchestrator-worker 模式）正是 **option (a)**：lead agent 在一次推理里产出多个 subagent 调用，运行时并发执行子 agent，再把结果回收。这与本项目 `_execute_tool_uses` 的 gather 完全同构 → **option a 是 Anthropic 协议的"原生"并行表达，本项目已实现一半**。
  - 关键经验：Anthropic 报告并行子 agent 是其能力/速度提升的主因之一，但**token 成本随并行度近似线性放大**（每个子 agent 各自吃上下文）——对应本项目的 cost-aware 子任务。
- **显式 batch 原语 = option (b)**：
  - LangGraph 的 `Send(node, state)` 是"动态 fan-out"原语——orchestrator 节点返回一个 `Send` 列表，运行时为每个 Send 并发起一个分支（典型 map-reduce）。这是"显式 map"而非"依赖 LLM 一轮多 call"。
  - CrewAI 的 `kickoff_for_each` / `async_execution=True` 是显式批量/异步声明。
- **取舍**：option (a) 把"派几个"交给 LLM 判断（灵活、贴协议，但并行度不可控/不可预算约束）；option (b) 由代码显式控制 batch（可控、可加并发上限与预算闸，但需要新工具 + 引导 LLM 用它）。LangGraph 经验：**纯 LLM 决策的 fan-out 难做资源治理**，所以它把 fan-out 上升为图原语以便框架管控——这点直接呼应本项目的 cost-aware 诉求。

### 2. Join / 调和：reduce 步骤 vs 自动 merge

- 主流生产做法**几乎都是"专门的 reduce/synthesis 步骤"，不是自动 merge**：
  - Anthropic：lead/synthesis agent 显式读全部子结果再合成最终答案。
  - LangGraph：join 节点 + state reducer（`operator.add` 累加，或自定义 merge 函数）——merge 是**确定性代码**，不是 LLM。
  - CrewAI hierarchical：manager agent 汇总。
- **关键区分（对本项目尤其重要）**：上述系统的产物多是**文本/结构化 state**，merge 是语义合并。本项目子 agent 产物含 **代码文件改动**，"join" 实际是 **git 层 merge**（per-agent worktree → issue 分支），冲突无法靠 LLM 文本合并 deterministically 解决。
  - → 推荐**两层 join**：(1) deterministic git merge（无冲突直接合）；(2) 冲突上浮给一个 Conductor **reconcile turn**（LLM 读冲突 + 各产物摘要再决策），即 LangGraph 的"自动 merge"与 Anthropic 的"synthesis step"的结合。

### 3. 失败语义：全 abort vs 部分 join vs 重试

- **没有系统默认"一个失败全 abort"**；主流是 **agent/node 级 retry + 编排层决策降级**：
  - Anthropic：子 agent 失败 → orchestrator 当作一条"坏结果"，重试或调整计划，其余子 agent 结果照常 join（**部分 join + 选择性重试**）。
  - LangGraph：节点 `retry_policy`（指数退避）；分支失败默认冒泡，但可用 fallback 边/默认值实现部分 join。
  - CrewAI：task 级 retry + guardrail；默认一个 task 失败会中断该 crew（偏 fail-fast），需显式容错配置。
- **asyncio 落地陷阱（直接关系本项目）**：
  - `asyncio.gather(*tasks)` **默认 `return_exceptions=False`**：任一子任务抛异常会立即向上 propagate，其余任务**不会被自动取消**（仍在后台跑，但结果被丢弃）→ 这正是"部分完成但产物丢失"的隐患。
  - 期望"部分 join"应使用 `asyncio.gather(..., return_exceptions=True)`，把异常作为结果项收集，再让 reconcile turn 决策；想"全 abort"则用 `asyncio.TaskGroup`（Py3.11+，一个失败自动 cancel 兄弟任务）。
  - 当前 `_execute_tool_uses` 用的是**裸 `asyncio.gather`（无 return_exceptions）**——所以现状是"fail-fast 但不取消兄弟、丢弃兄弟结果"，介于两种语义之间，**语义不明确**，是需要明确定义的点。

### 4. 批内依赖：纯 fan-out vs DAG

- **谱系**：Swarm（线性 handoff，几乎无并行）< Anthropic research（同层纯 fan-out + 层间 orchestrator 串接）< CrewAI（task `context=[...]` 有向依赖）< LangGraph / AutoGen（完整 DAG）。
- **生产经验**：多数"orchestrator-worker"系统**先做纯 fan-out**（同层 worker 独立），层间依赖交给 orchestrator 的下一轮决策来表达，而**不在单批次内做 DAG**——因为批内 DAG 会把调度复杂度推回编排器，得不偿失。LangGraph 才把 DAG 上升为一等公民，但代价是用户要显式建图。
- → 对本项目：MVP **纯 fan-out** 最稳（一轮并行派 N 个独立 subagent，依赖交给 Conductor 下一 turn）。Conductor loop 本就是"决策时间线"（CLAUDE.md: WorkflowGraph 非预设 DAG），天然适配"层间靠多轮、层内纯 fan-out"。批内 DAG 留作后续。

---

## 映射到本项目约束

| 外部模式 | 本项目落点 |
|---|---|
| Anthropic option (a) 一轮多 tool_use 并发 | **已存在**：`_execute_tool_uses` 的 `asyncio.gather`（`conductor_main_loop.py:380`）+ per-task `TaskCompletionRegistry`。需做：强化 prompt 引导（`:746` 串行措辞改写）、确认 dispatch 内部 await 不互相阻塞、并发度上预算闸 |
| LangGraph `Send` 显式 fan-out + 框架管控 | 若要可控并行度/预算治理（cost-aware 子任务），考虑 option (b) `dispatch_batch` 工具显式表达 N，便于在调度器层加 `MAX_CONCURRENT_*` 与预算约束 |
| synthesis/reduce step（非自动 merge） | 新增 Conductor **reconcile turn**：所有并行 task 完成后注入一轮，LLM 读各产物摘要 + git merge 结果再决策。对应 PRD 设计树 #3 |
| 两层 join：deterministic merge + 冲突上浮 | **per-agent worktree**（PRD 设计树 #2 强隔离）+ `git_service` 做无冲突自动 merge，冲突 → reconcile turn / `request_user_clarification`。解决"N worktree 合并回 issue 分支" |
| asyncio 失败语义 | 现状裸 `gather` 语义不明确。MVP 建议 `return_exceptions=True`（部分 join，失败分支作为坏结果交 reconcile turn），把"全 abort"（TaskGroup）作为可配策略。对应 PRD 设计树 #5 |
| 纯 fan-out 优先于批内 DAG | MVP 纯 fan-out，层间依赖靠 Conductor 多轮决策（贴合 WorkflowGraph "决策时间线"语义）。批内 DAG 出 MVP。对应 PRD 设计树 #4 |
| 并行度/token 成本线性放大 | 与 cost-aware 子任务 [05-29-cost-aware-conductor-scheduling] 直接耦合：并发度即成本乘子，需进 `timeouts.py` 旋钮 + 预算约束 |

---

## Related Specs / Code

| Path | 说明 |
|---|---|
| `backend/app/application/conductor_main_loop.py:368-380` | `_execute_tool_uses` 已对多 tool_use 做 `asyncio.gather`（并发原语半成品） |
| `backend/app/application/conductor_main_loop.py:726-746` | Conductor 系统提示：已允许一轮多 dispatch，但 `:746` 措辞偏串行 |
| `backend/app/application/task_completion_registry.py` | per-task asyncio.Event 注册表，天然支持并发 await 多个 task |
| `backend/app/application/conductor_tools.py` | `dispatch_subagent`（可能新增 `dispatch_batch` 的落点） |
| `backend/app/application/timeouts.py` | 并发/超时旋钮单一真相源（`MAX_CONCURRENT_INSTANCES_PER_ROLE` 等） |
| `.trellis/tasks/05-29-parallel-swarm-scheduler/prd.md` | 本任务 PRD（设计树 #1-#7） |

## Caveats / Not Found

- **未做实时 web 抓取**（环境无 exa 工具）。外部系统的 API 名称/版本（如 `Send`、`async_execution`、`kickoff_for_each`、`return_exceptions` 行为）基于稳定的公开架构语义，落地前请按官方文档二次核对当前版本。
- **PRD "完全串行" 表述与代码不符**：并发 gather 已存在（见 §0）。建议把任务重定义为"补齐隔离 + join/reconcile + 明确失败语义 + prompt 引导"，而非"从 0 实现并行"。
- 未深入读 `worktree_manager.py` / `git_service.py` 的 merge 能力细节（per-agent worktree → issue 分支的具体合并 API 是否就绪），join 落地前需单独扒一次这两个文件。
