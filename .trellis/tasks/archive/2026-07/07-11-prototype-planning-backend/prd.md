# PR2 - 原型规划后端与持久化

## Goal

在证据层之上实现可持久化的原型分析计划：零输入启动分析，LLM 基于严格证据生成项目上下文和逐页 restore brief，用户可以读取、编辑和恢复计划，但本任务不启动 HTML 生成。

## Parent Design

- [`../07-11-project-driven-prototype-generation/prd.md`](../07-11-project-driven-prototype-generation/prd.md)
- [`../07-11-project-driven-prototype-generation/info.md`](../07-11-project-driven-prototype-generation/info.md)

## Dependencies

- 依赖 `07-11-prototype-evidence-foundation` 提供 evidence models 和 providers。

## Requirements

- 定义 `PrototypePlan` 与 `PrototypePlanItem` typed models 和状态枚举。
- 新增 SQLite 表、索引和 store CRUD，遵循现有增量 schema 机制，不修改历史 prototype 行。
- 实现分析 runner，状态至少覆盖 queued、analyzing、ready、analysis_failed、stale/interrupted。
- runner 独立于 SSE 订阅；客户端断开不能取消分析。
- 服务启动恢复时将无法继续的 analyzing 计划标记 interrupted/failed，并提供重试入口。
- 实现 `PrototypePlanService`：调用 PR1 evidence providers，生成 repository fingerprint，调用配置的原型 LLM runtime。
- 首次分析允许 `global_instruction` 为空；同一项目后续计划复用已保存的统一要求。
- LLM 输出使用严格 Pydantic schema，并校验每个页面 brief 引用有效 evidence ID。
- prompt 固定 `mode=restore`，不得在零输入时主动重新设计。
- 单批 prompt 有候选数量和字符上限；大项目分批规划并持久化阶段进度。
- 外部模型失败、超时、非法 JSON 或 evidence 引用错误必须显示失败/partial 状态，不回退成截断源码 brief。
- 实现 API：
  - `POST /api/projects/{project_id}/prototype-plans`
  - `GET /api/prototype-plans/{plan_id}`
  - `GET /api/prototype-plans/{plan_id}/events`
  - `PATCH /api/prototype-plans/{plan_id}`
  - `PATCH /api/prototype-plan-items/{item_id}`
- PATCH 只允许编辑用户字段；evidence、hash、action、confidence 不可由客户端覆盖。
- 不创建/更新 prototype，不实现 generation run。

## Acceptance Criteria

- [ ] 空请求体或空统一要求可以创建计划并返回 `202 + plan_id`。
- [ ] VideoNote fixture 计划最终包含 19 个可审阅页面族及扩展 unsupported diagnostic。
- [ ] 每个可生成 item 都有 title、summary、restore brief、states、evidence、confidence 和 source hash。
- [ ] 用户编辑 title/brief/states/selected 后刷新仍可恢复。
- [ ] SSE 首次连接与重连都会发送当前 snapshot。
- [ ] 断开 SSE 后分析继续运行并持久化最终状态。
- [ ] LLM 非法输出不会生成伪造计划，用户看到可重试错误。
- [ ] 分析期间证据变化会使计划进入 stale 或产生明确 diagnostic。
- [ ] HTTP 边界使用 Pydantic request/response models，不接收未验证的裸 dict。
- [ ] 现有 prototype API 测试不回归。

## Definition Of Done

- store migration、service、runner、API 和恢复逻辑都有 targeted tests。
- 后端 Ruff、mypy、相关 pytest 和 app import smoke 通过。
- OpenAPI 契约与前端可消费的字段命名稳定。
- 没有 broad fail-open gate 或静默空结果。

## Out Of Scope

- 前端计划审阅界面。
- prototype 创建、HTML 生成、generation run 和失败重试。
- 运行时 DOM/截图证据。
- 新增 PR1 之外的框架 provider。

## Delivery Boundary

本任务完成后，可以通过 API 创建、订阅、读取和编辑原型计划；“生成所选原型”尚不可用。
