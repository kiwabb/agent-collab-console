# Cost-Aware Conductor Scheduling

## Goal

让 Conductor 在 tool-use 决策时**感知 token/成本**：知道当前 issue 已花多少、距预算还剩多少，并据此调整调度行为（按预算选便宜/贵模型、必要时并行 dispatch、超预算时收尾）。目标是把成本从"事后记账"变成"决策时的一等输入"。

## What I already know（已扒代码确认）

- **成本现在只是事后记账**：每个 `ExecutionProcess` 记 `input_tokens`/`output_tokens`/`cache_read_tokens`/`total_cost_usd`（`models.py:314`）。`usage_utils.price_tokens()` 用**全局扁平费率**（env `COST_USD_PER_M_INPUT=0.30` / `_OUTPUT=1.20` / `_CACHE_READ=0.075`），**不区分模型**。
- **dispatch 现在是串行**：`conductor_tools.dispatch_subagent` → 占 role slot → `dispatch_role` 建 task/node → `TaskCompletionRegistry.wait_for_active` **await 到完成**（idle/hard timeout）。Conductor tool-use loop 一次一个工具，**没有并行 dispatch**。
- **模型选择**：`RuntimeCatalog` 有 executor/provider/model；`RuntimeModelConfig` 只有 `id/label/enabled`，**没有价格字段**。task 级 `provider/model` > catalog 默认；`ConductorLLMConfig` 单独选 conductor 自己的脑子模型。
- **Conductor 决策时看不到任何预算/累计花费**：没有东西把成本反馈进 tool-use loop 的上下文。
- 并发上限旋钮在 `timeouts.py`：`MAX_CONCURRENT_INSTANCES_PER_ROLE=3`（进程级，跨 issue）。

## 能力拆解（用户原始描述 = 4 个独立能力）

1. **预算感知（budget awareness）** — Conductor 上下文里注入「本 issue 已花 $X / token N、预算上限 $Y」，每轮决策可见。
2. **分模型定价（per-model pricing）** — catalog `RuntimeModelConfig` 加价格字段，`price_tokens` 按实际模型算，成本估算才准。
3. **预算驱动选型（budget-driven model selection）** — Conductor 按预算/任务难度选便宜或贵模型（dispatch_subagent 带 model 决策）。
4. **并行 dispatch** — 一次派多个 subagent 并发跑（**架构最大改动**：当前 loop 串行，Anthropic tool-use 每轮一个工具，需要批量 dispatch + 并发 await 机制）。

> 注：用户把 4 件事一句话带过，但它们复杂度和风险差别很大。并行 dispatch (4) 是对现有串行 loop 的根本性改造，独立性最强；(1)(2)(3) 是一条递进链（先能看见成本 → 定价准 → 才能据此选型）。

## Assumptions (temporary)

- 预算是 **per-issue** 级别（不是全局/per-project），先做单 issue 维度。
- 成本/token 数据从已有的 `ExecutionProcess` 聚合即可，不需要新数据源。

## MVP 边界（已确认 2026-05-29）

**MVP = 能力 1+2+3「成本感知决策内核」**：预算感知 + 分模型定价 + 预算驱动选型。
**能力 4（并行 dispatch）明确不在本版**，拆到后续单独任务（理由：对现有串行 loop 是根本性架构改造，独立性强，混进来会拖长且抬高风险）。

## 已确认决策（2026-05-29）

- **预算粒度** = 全局默认（env/Settings）+ per-issue 可覆盖。创建 issue 时不填则用全局默认。

## Open Questions

- 超预算行为：硬停 vs 软告警 vs 仅强制降级？
- "贵/便宜模型"映射怎么定义——靠 per-model 价格自动排序，还是 catalog 显式标 tier？

## Requirements (evolving)

- TBD（随讨论填充）

## Acceptance Criteria (evolving)

- [ ] TBD

## Definition of Done (team quality bar)

- 后端单测覆盖（pricing 计算、预算聚合、决策注入）
- `python3 -m pytest` 快档绿；前端若改 build + lint 绿
- CLAUDE.md / 相关文档若行为变化则更新
- 成本/预算相关 env 旋钮集中进 `timeouts.py` 或同类单一真相源

## Out of Scope (explicit)

- TBD（随讨论填充）

## Technical Notes

- 关键文件：`conductor_tools.py`（dispatch_subagent）、`conductor_main_loop.py`（tool-use loop）、`usage_utils.py`（pricing）、`models.py`（RuntimeModelConfig / ExecutionProcess）、`timeouts.py`（旋钮单一真相源）。
- TaskCompletionRegistry（asyncio.Event 单例）是 await 子 agent 完成的机制；并行 dispatch 需绕开"一次 await 一个"的形态。
