# Cost-Aware Conductor Scheduling

## Goal

让 Conductor 在 tool-use 决策时**感知 token/成本**：知道当前 issue 已花多少、距预算还剩多少，并据此调整调度行为（按预算选便宜/贵模型、必要时并行 dispatch、超预算时收尾）。目标是把成本从"事后记账"变成"决策时的一等输入"。

## What I already know（已扒代码确认）

- **成本现在只是事后记账**：每个 `ExecutionProcess` 记 `input_tokens`/`output_tokens`/`cache_read_tokens`/`total_cost_usd`（`models.py:314`）。`usage_utils.price_tokens()` 用**全局扁平费率**（env `COST_USD_PER_M_INPUT=0.30` / `_OUTPUT=1.20` / `_CACHE_READ=0.075`），**不区分模型**。
- **并行 dispatch 已落地**（2026-05-29 parallel-swarm-scheduler，已合入 main）：`dispatch_batch` 一轮并发起 N 个 subagent，`MAX_PARALLEL_DISPATCH_PER_BATCH` 限并发。← **本任务的"能力4"已不再是缺口**；成本治理现在多了一个接入点：并发度 = 成本乘子，可由预算动态压缩。
- **模型选择**：`RuntimeCatalog` 有 executor/provider/model；`RuntimeModelConfig` 只有 `id/label/enabled`，**没有价格字段**。task 级 `provider/model` > catalog 默认；`ConductorLLMConfig` 单独选 conductor 自己的脑子模型。
- **Conductor 决策时看不到任何预算/累计花费**：没有东西把成本反馈进 tool-use loop 的上下文。
- 并发上限旋钮在 `timeouts.py`：`MAX_CONCURRENT_INSTANCES_PER_ROLE=3`（进程级，跨 issue）/ `MAX_PARALLEL_DISPATCH_PER_BATCH`（batch fan-out 上限）。

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

1. **MVP** = 能力 1+2+3（预算感知 + 分模型定价 + 预算驱动选型）。能力 4 并行 dispatch 已在前一任务完成。
2. **预算粒度** = 全局默认（env/Settings）+ per-issue 可覆盖。创建 issue 时不填则用全局默认。
3. **超预算行为** = **软警告 + 收尾**：到阈值注入警告让 Conductor 优先降级/减派；真超上限引导 `finalize_task` 收尾。不硬杀。
4. **贵/便宜模型映射** = **按 per-model 价格自动排序**（复用能力2要加的价格字段，单一真相源，不额外维护 tier 字段）。
5. **预算治理并发** = **是**：预算紧张时动态压缩 `dispatch_batch` 的有效并发上限（并发度=成本乘子）。

## Requirements

- **能力2 分模型定价**：`RuntimeModelConfig` 加价格字段（input/output/cache_read per-M USD）；`usage_utils.price_tokens` 改为**按实际模型查价**，缺价回落现有全局 env 费率（向后兼容）。catalog DB + 序列化带上新字段。
- **能力1 预算感知**：
  - per-issue 预算：issue 模型加预算字段（USD 上限）+ DB 迁移；创建 issue 不填则取全局默认。
  - 全局默认旋钮进 `timeouts.py`（或同类单一真相源）：默认 per-issue 预算 + 软警告阈值比例（如 0.8）。
  - 成本聚合：从已有 `ExecutionProcess` 按 issue 聚合 `total_cost_usd`（无新数据源）。
  - 注入：每轮 Conductor tool-use 上下文带「已花 $X / 预算 $Y / 剩余 / 各候选模型单价」。
- **能力3 预算驱动选型 + 并发治理**：
  - Conductor 系统提示引导：预算充足可选贵模型，紧张优先便宜模型（便宜/贵由价格排序得出）。
  - 软警告：花费达阈值 → 注入警告（优先降级/减派）；超上限 → 引导 `finalize_task` 收尾。
  - 预算紧张时 `dispatch_batch` 有效并发上限按预算动态下调（取 `min(配置上限, 预算可支撑的并发)`）。

## Acceptance Criteria

- [ ] `price_tokens` 对带价格的模型按其单价计算；无价模型回落全局 env 费率（两条都有测试）
- [ ] per-issue 预算可设、不填用全局默认；DB 迁移幂等
- [ ] Conductor 每轮上下文可见「已花/预算/剩余/候选模型单价」（聚合自 ExecutionProcess）
- [ ] 花费达软警告阈值 → 注入警告事件/上下文；超上限 → 引导收尾（不硬杀）
- [ ] 预算紧张时 `dispatch_batch` 实际并发数被下调（测试断言有效并发 ≤ 预算允许值）
- [ ] 后端单测覆盖：分模型定价、预算聚合、阈值/收尾、并发下调；串行/现有行为零回归

## Definition of Done (team quality bar)

- 后端单测覆盖（pricing 计算、预算聚合、决策注入、并发下调）
- `python3 -m pytest` 快档绿；前端若改 tsc/test 绿（**不跑 npm run build**，dev 在跑会 clobber .next）
- CLAUDE.md / 相关文档若行为变化则更新
- 成本/预算 env 旋钮集中进 `timeouts.py` 单一真相源 + `validate()` 不变量

## Decision (ADR-lite)

**Context**：成本只是事后记账、全局扁平费率、Conductor 决策看不到预算；并行 dispatch 已落地使成本随并发线性放大。
**Decision**：把成本变成决策时一等输入——分模型定价（价格字段单一真相源，便宜/贵由排序得出）+ per-issue 预算（全局默认+覆盖）+ 每轮注入花费/预算 + 软警告收尾（不硬杀）+ 预算动态压缩 batch 并发。
**Consequences**：定价更准但需维护 catalog 价格；预算驱动是 prompt 引导（非强制约束），软语义可能仍超一点，用并发下调兜住成本斜率；不破坏现有 issue（预算可空=用全局默认，价格可空=回落 env）。

## Implementation Plan（small PRs）

- **PR1 分模型定价**：`RuntimeModelConfig` 价格字段 + catalog DB/序列化 + `price_tokens` model-aware（回落 env）+ 单测。
- **PR2 预算感知**：per-issue 预算字段 + 迁移 + 全局默认/阈值旋钮（`timeouts.py`）+ issue 成本聚合 + 注入 Conductor 上下文 + 单测。
- **PR3 预算驱动行为**：选型 prompt 引导 + 软警告/收尾 + `dispatch_batch` 并发按预算下调 + 单测 + CLAUDE.md/可视化（如预算条）。

## Out of Scope (explicit)

- per-project / 跨 issue 预算（先做 per-issue）
- 硬性预算约束/真硬杀（本版软语义 + 并发下调）
- 前端完整成本仪表盘（PR3 至多加最小预算/花费展示）
- 实时按 token 流式中断当前 run（按完成的 run 聚合即可）

## Technical Notes

- 关键文件：`usage_utils.py`（pricing）、`models.py`（RuntimeModelConfig / ExecutionProcess / CodexIssue 预算字段）、`conductor_main_loop.py`（tool-use loop 上下文注入 + prompt）、`conductor_tools.py`（dispatch_batch 并发下调）、`timeouts.py`（预算旋钮）、catalog store/序列化。
- 成本聚合：`ExecutionProcess.total_cost_usd` 按 issue 汇总；注意只算已完成 run。
- 并发下调：`dispatch_batch` 已有 `MAX_PARALLEL_DISPATCH_PER_BATCH`，新增"预算可支撑并发"取 min。
