# 移除从代码生成原型功能

## Goal

移除基于源码扫描和运行时浏览器证据生成原型的完整功能链路，保留手动创建、迭代修改、批量重生成、版本切换和预览。旧 code-scan 原型继续作为普通原型工作。

## Requirements

- 删除后端代码候选发现、运行时截图采集、code-scan service 方法和两个 API 路由。
- 删除后端 Python Playwright 依赖和已删除模块的 mypy strict 配置项。
- 删除 code-scan 专属 store 方法，但保留 `Prototype.source_*`、核心 CRUD、SQLite 列和 legacy provenance。
- 删除前端“从代码生成”入口、弹窗、进度状态、专属 API、类型、SSE readers、文案和测试。
- 移除原型列表中的来源 badge 和 source reference 展示，但不改变 Prototype API 的 legacy 字段。
- 更新当前 Trellis type-safety 规范，不保留已删除的 `PrototypeCodeCandidate` 现行示例。
- 清理 `.audit_findings.json` 中随 code-scan UI 消失而失效的审计项。
- 保留手动创建、迭代、批量重生成、版本读取和 iframe 预览行为。

## Acceptance Criteria

- [ ] OpenAPI 不再包含 `code-candidates` 和 `generate-from-code/stream`，对应请求返回 404。
- [ ] 后端源码和测试不再引用 `CodePrototypeDiscoveryService`、`RuntimePrototypeCaptureService` 或 `RuntimePrototypeEvidence`。
- [ ] 前端源码和测试不再引用 code-scan API、候选类型、UI 状态或 i18n keys。
- [ ] legacy `source_kind='code'` 原型仍可 list/get/iterate/regenerate-all。
- [ ] 手动创建、单原型生成/迭代和批量重生成测试通过。
- [ ] 后端 Ruff、mypy、import smoke 和 pytest 通过。
- [ ] 前端 tests、typecheck、lint、format check 通过。
- [ ] 原型页浏览器 smoke 显示手动创建和批量重生成入口，且不再显示 code-scan UI。

## Definition of Done

- 变更仅包含本任务内容，不混入当前 Startup Config 的未提交改动。
- 删除后无活跃源码、测试、规范或审计项继续宣称 code-scan 功能存在。
- 不执行 SQLite 删列或历史 prototype 数据迁移。

## Technical Approach

采用两阶段收缩：本任务删除功能入口和专属实现，保留 legacy provenance 契约与物理列；未来只有在明确需要 API/schema 清理时，再单独设计字段弃用和数据迁移。

后端先移除路由和 service 调用链，再删除扫描/采集模块及依赖；前端移除 UI、API 和候选事件解析；最后更新测试、规范和审计清单，并执行零残留搜索。

## Decision (ADR-lite)

**Context**: 原方案同时删除 `Prototype.source_*`，会扩大到核心 CRUD、API contract 和旧数据兼容。

**Decision**: 本次保留 `source_*` 字段、核心 CRUD 和 SQLite schema，仅删除 code-scan 专属查询/更新方法和 UI 展示。

**Consequences**: 功能删除的风险和 blast radius 更小，旧 provenance 仍可读取；数据库会暂时保留不再用于新功能的字段和索引。

## Out of Scope

- 删除 Prototype 表的 `source_*` 列或 `idx_prototypes_project_source` 索引。
- 从 domain/API/frontend Prototype contract 删除 legacy `source_*` 字段。
- 删除历史 Trellis task 记录。
- 清理用户项目目录中已生成的 prototype 或 runtime capture 文件。

## Technical Notes

- `save_prototype_version` 直接更新 `prototypes.current_version`，regenerate-all 不调用 `save_prototype`。
- 当前系统 `python3` 没有 pytest，后端验证使用 `.venv/bin/python`、`.venv/bin/ruff` 和 `.venv/bin/mypy`。
- `frontend/src/lib/i18n/en-US.ts`、`zh-CN.ts`、`lib/types.ts` 和 canonical frontend specs 已有另一任务改动，编辑和暂存必须保留现有 hunks。
