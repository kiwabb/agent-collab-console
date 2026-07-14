# 项目驱动的批量原型生成 - 技术设计

## 1. 设计摘要

本设计新增一个可持久化的“原型计划”领域，把项目理解与 HTML 生成彻底分离：

```text
Repository (read-only)
  -> Package inventory
  -> Route/layout/style evidence providers
  -> Surface manifest
  -> LLM brief planner
  -> Persisted review plan
  -> User confirmation
  -> Persisted generation run
  -> Existing PrototypeService
```

系统不会恢复已删除的 `CodePrototypeDiscoveryService`。旧实现把目录匹配、源码截断、brief 组装、prototype 写入和批量生成混在一个 service 中；新实现为每一层定义类型化输入输出和失败状态。

## 2. MVP 产品流程

### 2.1 入口

原型页工具栏新增“从项目生成”。点击后直接创建分析计划，无必填字段。入口只提供一个可选的“统一设计要求”，默认复用该项目上次保存的内容。

### 2.2 分析状态

创建计划后进入独立的计划视图，而不是在小弹窗中承载 19 个以上候选。页面展示：

- 当前阶段：发现 package、解析路由、整理项目上下文、生成页面 brief。
- package/surface 清单及 supported / partial / unsupported 状态。
- 分析失败时的明确原因和重试动作。

分析不会创建 prototype，也不会启动 HTML 生成。

### 2.3 审阅状态

计划完成后显示密集表格，按 package/surface 分组。表格列包括选择、页面族、route、主组件、状态、置信度、变更类型和证据。右侧详情面板编辑项目级上下文或当前候选的 title、summary、brief 和 states。

默认选择规则：

- high/medium 且 action 为 create/update 的候选选中。
- unchanged、low、unsupported、redirect、wildcard 不选中。
- 用户可以保存计划后离开，返回时继续审阅。

### 2.4 批量生成

“生成所选原型”提交一个持久化 generation run。界面显示固定尺寸的队列表格和总进度，不渲染每个模型 token。每页完成后即可打开原型；失败项保留 brief 并支持只重试失败项。

初次版本固定为 `restore`。用户查看基线后，通过现有迭代输入明确提出优化，生成 v2+；v1 不被覆盖。批量优化不属于本 MVP。

## 3. 领域模型

### 3.1 PrototypePlan

```text
id
project_id
status: queued | analyzing | ready | analysis_failed | stale
repository_fingerprint
scope_json
project_context_json
global_instruction
diagnostics_json
error_message
created_at / updated_at
```

`repository_fingerprint` 包含 git HEAD（可为空）和实际读取证据文件的内容 hash。它不是只看 commit，因此能检测 dirty worktree 中的变化。

### 3.2 PrototypePlanItem

```text
id
plan_id
candidate_id
package_root
surface_kind
route_patterns_json
component_ref
title / summary / brief
states_json
evidence_json
confidence: high | medium | low
action: create | update | unchanged | missing | unsupported
selected
source_hash
prototype_id
created_at / updated_at
```

`candidate_id` 只由规范化结构决定，不包含会频繁变化的标题或源码 hash。`source_hash` 单独表示 evidence 内容变化。

### 3.3 PrototypeGenerationRun

```text
id
plan_id
status: queued | running | completed | partial_failed | failed | interrupted
selected_count
completed_count
failed_count
error_message
created_at / started_at / completed_at
```

### 3.4 PrototypeGenerationRunItem

```text
id
run_id
plan_item_id
prototype_id
status: pending | running | done | failed | skipped
version_no
error_message
started_at / completed_at
```

运行状态不能只存在内存或 React state。服务进程重启时，未完成 run 标记为 `interrupted`，用户可以创建只包含未完成项的新 retry run。

## 4. 项目证据层

### 4.1 RepositoryBoundary

所有 provider 共用同一边界：

- `Project.repo_path` 必须存在、为目录并 resolve 后固定为 root。
- 读取的每个文件必须 resolve 后仍位于 root 内；symlink 越界拒绝。
- 忽略 `.git`、`node_modules`、构建产物、缓存、虚拟环境和 `.agent-collab`。
- 设定 package 数、文件数、单文件大小和总证据字符上限。
- 只读文件，不执行目标仓库脚本，不加载目标模块，不访问其凭据。
- 边界或上限错误返回 diagnostics/analysis_failed，不返回空成功。

### 4.2 PackageInventoryProvider

扫描有限深度内的 manifest 与 workspace 配置，输出：

```text
package_root
manifest_path
framework_signals
surface_kind
entry_candidates
style_candidates
status + diagnostics
```

VideoNote 必须发现 `VideoMemo_frontend` 和 `VideoMemo_extension`。前者进入 React provider；后者显示 browser-extension / unsupported，不进入生成队列。

### 4.3 RouteEvidenceProvider

定义统一协议：

```text
supports(package_manifest) -> support level
collect(package, repository_boundary) -> SurfaceEvidence
```

MVP providers：

- `NextAppRouterProvider`
- `NextPagesRouterProvider`
- `ReactRouterJsxProvider`
- `ReactPageDirectoryFallbackProvider`

provider 按证据强度选择，不能对同一 package 重复生成候选。fallback 只生成 low-confidence 候选并说明没有发现正式路由声明。

### 4.4 ReactRouterJsxProvider

采用锁定版本的 `tree-sitter` + `tree-sitter-typescript` TSX grammar：

1. 从 package dependencies 和入口文件发现 React Router 使用。
2. 解析 import，识别 `Routes`、`Route`、`Navigate` 的本地 alias。
3. 遍历 JSX AST，组合父子静态 path、index route 和无 path layout。
4. 解析 `element={<Component />}` 的 component reference，并追溯本地 import。
5. 把 layout component、主页面 component、route source line range 写入 evidence。
6. 将同主组件、同用户任务的 new/edit route 归并为 states。
7. 变量计算、spread、运行时 route builder 等无法静态求值的结构标记 partial，禁止猜测。

VideoNote 当前 fixture 应得到 19 个默认逻辑页面族：onboarding、home、collections list/detail、knowledge、tasks、trends、subscriptions、articles、batch import、guide、model settings、download settings、transcriber、Feishu、local downloader、access password、monitor、about。

### 4.5 ContextEvidenceCollector

对每个 surface 收集有上限的结构化证据：

- README/package metadata。
- route tree 与导航配置。
- 全局 layout 和页面主组件。
- CSS variables、Tailwind config、主题 provider、组件库依赖。
- 页面内的标题、按钮、表格字段、空/加载/错误状态等高信号 UI 文本。

collector 不把任意 import 树完整塞给 LLM。每条 evidence 保留 path、line range、kind 和 hash。

## 5. Brief Planner

`PrototypePlanService` 将类型化 evidence 交给配置的原型 LLM runtime，输出严格 Pydantic schema：

- 一次项目级调用生成产品上下文和公共设计约束。
- 页面候选分批规划，避免一个巨型 prompt；每批共享同一项目上下文。
- prompt 明确 `mode=restore`：只描述证据支持的现状，不主动重新设计。
- 输出必须引用 evidence ID。没有引用或 schema 校验失败的 item 标记 planning_failed，并显示重试，不能回退成旧式截断源码 brief。
- 外部模型响应是系统边界，必须完整验证；内部 typed models 直接访问字段，不加隐藏 schema 错误的 `getattr`/默认值。

## 6. 幂等与增量规则

### 6.1 Stable Identity

```text
candidate_id = hash(package_root, surface_kind, component_ref, normalized_route_family)
```

标题、LLM summary 和 source hash 不参与 identity。

### 6.2 Source Hash

hash 输入为排序后的 evidence path、kind 和原始内容 hash。分析后生成前再次计算所选项 hash；若不一致，计划标记 stale 并拒绝生成，要求重新分析。

### 6.3 Prototype Mapping

- create：新建 `source_kind=code` prototype，`source_ref=candidate_id`。
- update：复用已映射 prototype，保存新的 seed metadata，生成下一版本。
- unchanged：默认不进入 run。
- missing：保留旧 prototype，只显示来源已消失。
- 同一 project + candidate_id 必须唯一，数据库加唯一约束或使用显式 upsert。

批量写入 seed 与 run item 应在事务中完成；HTML 生成和文件写入在事务外逐项执行。单项生成成功后再原子保存版本和 run item 状态。

## 7. 后台运行与事件

有副作用的操作使用 POST：

- `POST /api/projects/{project_id}/prototype-plans`
- `POST /api/prototype-plans/{plan_id}/generate`
- `POST /api/prototype-plans/{plan_id}/retry`

POST 返回持久化 ID 和 `202 Accepted`。SSE GET 只订阅状态：

- `GET /api/prototype-plans/{plan_id}/events`
- `GET /api/prototype-generation-runs/{run_id}/events`

runner 独立于 SSE 连接，关闭页面不会取消任务。默认最多并行生成 2 个页面，并受现有模型 runtime、预算和全局并发门禁约束；任何门禁读取失败都拒绝启动 run。后端持久化阶段/计数，SSE 重连先发送 snapshot，再推送后续变化。

## 8. API Contract

### 8.1 Create Plan

```json
POST /api/projects/{project_id}/prototype-plans
{
  "global_instruction": ""
}
```

响应：

```json
{
  "plan_id": "...",
  "status": "queued"
}
```

### 8.2 Update Plan

plan PATCH 只允许更新 `global_instruction` 和项目上下文字段；item PATCH 只允许更新 title、summary、brief、states、selected。分析生成的 evidence、hash、action 和 confidence 不能由普通编辑接口伪造。

### 8.3 Start Generation

```json
POST /api/prototype-plans/{plan_id}/generate
{
  "expected_updated_at": "..."
}
```

服务端验证计划为 ready、至少一个可生成项、没有活动 run、版本未冲突、source hash 未过期以及治理门禁可用。任一验证失败返回明确 4xx/503，不创建半成品 run。

## 9. 前端信息架构

### 9.1 原型工作台

保留当前两栏原型工作台。工具栏命令顺序：从项目生成、重新生成全部、新建原型。无原型时仍直接显示实际工作台空态，不使用营销页。

### 9.2 计划视图

计划使用项目内独立 route，例如：

```text
/projects/:projectId/prototypes/plans/:planId
```

布局采用紧凑的 operational table + 详情面板，不使用卡片嵌套。筛选使用 tabs/menus，选择使用 checkbox，状态使用 status badge，证据路径使用等宽文本与 tooltip。

### 9.3 错误与旧数据

- 加载或流订阅失败保留上一次计划数据，显示 banner/toast，不清空列表。
- 分析失败、部分支持、计划过期和生成失败必须有独立可见状态。
- 历史 manual/code prototype 继续显示和迭代；不要求迁移或删除。

## 10. 测试设计

### Backend Unit

- repository boundary、symlink、limits 和 ignore rules。
- package inventory 的多包识别。
- Next route adapters。
- React Router TSX AST：alias、nested/index/layout/dynamic/redirect/wildcard/partial。
- logical family grouping、stable ID 和 source hash。
- LLM schema validation 与 evidence 引用校验。
- stale plan、唯一映射、事务和 fail-closed governance gates。

### Backend Integration

- VideoNote 最小 fixture 得到预期 19 个页面族和 extension unsupported 诊断。
- create plan -> ready -> edit -> generate -> partial failure -> retry。
- SSE 重连 snapshot、客户端断开后 runner 继续。
- 历史 prototype CRUD/regenerate-all 不回归。

### Frontend

- 零输入创建计划。
- 分组、筛选、勾选、编辑与保存。
- stale/partial/unsupported/error 状态。
- generation snapshot、增量事件、失败重试。
- 加载失败不清空已有计划。

### Browser Smoke

- VideoNote 分析显示主应用 supported、扩展 unsupported。
- 审阅页显示 19 个逻辑页面族，无 redirect/404 重复项。
- 批量生成完成后 v1 均为 restore baseline。
- 用户迭代一个页面后出现 v2，仍可切回 v1。

## 11. 迁移与回滚

- 新表通过现有 SQLite 初始化/增量 schema 机制创建，不修改历史 prototype 行。
- 旧 `source_kind=code` 数据继续作为普通 prototype 工作；只有存在新 plan mapping 的项参与增量同步。
- UI 入口可由 feature flag 临时隐藏，但后端数据不删除。
- 回滚代码时新表保留且无人读取，不影响现有手动原型链路。

## 12. 实施拆分

所有子任务已经创建，按以下顺序串行交付；不得跳过前置依赖直接启动后续任务：

1. **PR1 - Evidence foundation**：[`07-11-prototype-evidence-foundation`](../07-11-prototype-evidence-foundation/prd.md) - 领域模型、repository boundary、package inventory、Tree-sitter parser 与 VideoNote fixture。
2. **PR2 - Planning backend**：[`07-11-prototype-planning-backend`](../07-11-prototype-planning-backend/prd.md) - providers、brief planner、计划持久化、create/read/patch API 与分析 runner。
3. **PR3 - Review UI**：[`07-11-prototype-plan-review-ui`](../07-11-prototype-plan-review-ui/prd.md) - 入口、计划 route、分析状态、候选表格、编辑和保存。
4. **PR4 - Generation runner**：[`07-11-prototype-generation-runner`](../07-11-prototype-generation-runner/prd.md) - 幂等 prototype mapping、持久化 run、SSE snapshot、失败重试和并发门禁。
5. **PR5 - Integration hardening**：[`07-11-prototype-integration-hardening`](../07-11-prototype-integration-hardening/prd.md) - 增量/stale、浏览器 smoke、可访问性、性能与文档。

每个子任务都停留在 `planning`，后续只启动当前要实现的一个子任务。
