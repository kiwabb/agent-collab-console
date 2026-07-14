# PR4 - 原型批量生成运行器

## Goal

把用户确认的计划转换为幂等的 source-backed prototype，并通过独立于浏览器连接的持久化 generation run 批量生成 restore 基线，支持进度重连、单项失败隔离和失败重试。

## Parent Design

- [`../07-11-project-driven-prototype-generation/prd.md`](../07-11-project-driven-prototype-generation/prd.md)
- [`../07-11-project-driven-prototype-generation/info.md`](../07-11-project-driven-prototype-generation/info.md)

## Dependencies

- 依赖 `07-11-prototype-planning-backend` 的 plan/store/API。
- 依赖 `07-11-prototype-plan-review-ui` 的候选选择与审阅交互。

## Requirements

- 定义并持久化 `PrototypeGenerationRun` 与 run item 状态。
- 实现：
  - `POST /api/prototype-plans/{plan_id}/generate`
  - `GET /api/prototype-generation-runs/{run_id}`
  - `GET /api/prototype-generation-runs/{run_id}/events`
  - `POST /api/prototype-plans/{plan_id}/retry`
- POST 返回 `202 + run_id`；SSE GET 只订阅已存在 run，不承载副作用。
- 启动前验证 plan ready、乐观版本、selected count、无活动 run、source hash 未过期、runtime/budget/concurrency gates 可用。
- 任一治理门禁读取失败时拒绝创建 run，不允许 fail-open。
- 对 create/update 候选幂等映射 `source_kind=code` prototype；重复请求不能创建重复 prototype。
- `source_ref` 使用 stable candidate ID，`source_meta_json` 保存 plan/evidence/restore metadata。
- 先在事务内冻结 run 与 seed，再在事务外执行模型生成；成功后原子保存版本与 run item 状态。
- runner 独立于 SSE subscriber，默认最多并行 2 个页面，并受全局/模型并发上限约束。
- 单项失败不能中止其他页面；失败保留 seed、错误和可重试状态。
- SSE 重连先发 snapshot，再发状态变化；不需要重放所有 token delta。
- 服务重启把运行中任务标为 interrupted，retry 只创建失败/中断项的新 run。
- 前端接入生成确认、固定尺寸进度队列、完成摘要、失败详情和只重试失败项。
- 新 prototype 首个生成版本标记 restore baseline；用户后续优化复用现有迭代并创建新版本，不能覆盖基线。

## Acceptance Criteria

- [ ] 用户确认 VideoNote 所选候选后只创建一个 generation run。
- [ ] 同一 plan 重复提交或并发提交不会产生重复 source-backed prototype。
- [ ] 生成前源码变化会被 stale gate 拒绝并要求重新分析。
- [ ] 最多并行 2 项，且 gate 不可用时整个 run 拒绝启动。
- [ ] 一个页面生成失败时其余页面继续完成。
- [ ] 关闭或刷新浏览器后 runner 继续，重连显示准确 snapshot。
- [ ] retry 只包含失败/中断项，不重新生成成功项。
- [ ] 新原型保留可切换的 restore baseline；显式优化产生下一版本。
- [ ] 历史 manual/code prototype 的 list/get/iterate/regenerate-all 不回归。
- [ ] 生成 API、store 事务、runner 恢复和 UI 进度都有测试。

## Definition Of Done

- 后端 Ruff、mypy、相关 pytest、app import smoke 通过。
- 前端 test、typecheck、lint、format check 通过。
- 浏览器 smoke 验证提交、进度、刷新重连、部分失败和 retry。
- 真实付费模型批量生成只作为显式人工验收，不由普通自动测试触发。

## Out Of Scope

- 批量优化或 AI 主动重新设计。
- 运行时截图辅助生成。
- 自动删除 missing prototype。
- 新框架 provider。

## Delivery Boundary

本任务完成后，核心“分析 → 审阅 → 批量生成 → 失败重试”链路可用；全面增量与性能加固由 PR5 完成。
