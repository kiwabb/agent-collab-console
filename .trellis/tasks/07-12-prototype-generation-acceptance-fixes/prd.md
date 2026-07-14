# 修复项目驱动原型生成验收阻断

## Goal

修复 2026-07-11 验收中发现的全部确定性缺陷，使 VideoNote 的项目驱动原型流程达到可发布状态：项目证据能够支持 restore 基线，计划可审阅和恢复，批量生成具备事务一致性、幂等、治理门禁和失败重试，桌面与窄屏界面均可操作。

## Scope Decision

- 纳入上一轮验收确认的全部 P0、P1、P2 缺陷，不做“仅修测试”或降级绕过。
- 保持首次生成固定为 `restore`，是否优化继续由用户在基线版本生成后显式决定。
- 不自动触发真实付费 LLM 批量生成；使用 fake runtime、临时数据库和浏览器 smoke 完成可复现验收。
- 保留当前工作区中的既有改动，不回退、不覆盖与本任务无关的用户修改。

## Requirements

### 0. 2026-07-12 acceptance addendum

- All model-authored project context, evidence explanations, diagnostics,
  page titles, summaries, briefs, states, progress messages, and errors must
  follow the plan's persisted `output_locale`; Chinese UI defaults to
  `zh-CN`. Source paths and source excerpts retain their original text.
- Planning and generation progress must be persisted server state rather than
  React-only state. The review page shows analysis batch progress and, during
  generation, processed/total, succeeded, failed, running, pending, current
  pages, elapsed time, output activity, and failure summaries in the first
  viewport. `processed` includes terminal failures and interrupted/skipped
  items, so a terminal 8-success/5-failure run reads 13/13 processed.
- Generation snapshots remain recoverable after refresh. SSE carries event
  identity, heartbeat, and anti-buffering headers; the client reconciles an
  active run through bounded polling when the stream is silent or disconnects,
  preserving stale data while surfacing the connection error.
- Planner and stream payloads are strict, versioned contracts. Pydantic
  rejects extra fields, project context has a fixed string schema, referenced
  evidence IDs are persisted, and the frontend validates every nested SSE
  plan/run/item/evidence object before mutating state.
- Add the built-in `prototype_ui_engineer` role and route it through the
  existing Claude Code executor and Runtime Catalog. MiniMax endpoint, key,
  and model selection are inherited from the catalog; no second Claude SDK,
  hard-coded provider configuration, or ad-hoc subprocess implementation is
  allowed.
- Route both UI-semantic planning and HTML restoration through
  `prototype_ui_engineer`. Deterministic evidence discovery and strict plan
  validation remain backend-owned. Planner `states` are stable machine
  identifiers (`default`, `loading`, `empty`, `error`, `success`, or a safe
  route-derived identifier such as `collections-:id`), not localized prose,
  and must not fail zh-CN copy validation.
- Each generated page runs in an isolated worktree/staging boundary. The UI
  engineer reads the real project source and writes `index.html` to a run-item
  staging directory; its final response is a small strict manifest, never the
  full HTML. Before atomic version completion, validate path containment,
  symlinks, UTF-8, size, complete HTML structure, external URL policy,
  checksum, and absence of source-code edits.
- Claude owns the implementation process used to create the staged file. The
  backend does not whitelist Bash, impose Write/Edit chunking, replay tool logs,
  or compare reconstructed HTML. Audit persists only artifact metadata and
  validation outcomes; it never stores, reconstructs, or generates HTML.
- Keep direct Anthropic-compatible HTTP streaming only for manual prototype
  generation and give it its own configurable token ceiling of at least 16384.
  Project-driven generation must fail closed unless the Claude artifact runtime
  can read the isolated repository; it never falls back to a repository-blind
  model request.
- Project-driven Claude prompts contain only the page title, current target
  routes, locale, and artifact/safety protocol. Claude must discover router
  entries, components, layouts, navigation, styles, tokens, and assets from the
  worktree. Source paths, hashes, evidence, project context, restore seed, and
  routes for other pages remain server-side guards and are never injected.
- Successful versions are written to
  `<project>/prototypes/<prototype-id>/<version-id>/index.html` before database
  completion. Preview and iteration read the persisted file, while DB-only
  fallback is limited to legacy rows with no `disk_path`.

### 1. Evidence and planning contracts

- Evidence manifest 必须携带有界、可解释的 UI 恢复证据，包括路由、主要页面源码摘要、共享布局、导航、样式入口、设计 token 和 UI 文本；不得只给模型路径和行数。
- Evidence ID 必须稳定并进入严格 Pydantic planner response；每个可生成 brief 引用的 evidence ID 都必须由服务端校验。
- React Router import alias、静态可求值 path、不可求值 path diagnostic、重复 Routes tree 去重必须有测试。
- Next.js、React Router、fallback 和样式证据的 hash 必须由规范化内容计算；同行数源码修改和纯 CSS/token 修改必须改变相关 fingerprint。
- 分析期间必须在 LLM 返回后重新验证 fingerprint；变化时进入 `stale` 并提供重新分析动作。
- 仓库、package、file、evidence、candidate 和 prompt 必须有明确上限与用户可见 diagnostic；未知或部分支持的 surface 不得静默返回空结果。
- 空 HTTP body 和空统一要求都能创建计划；同一项目后续计划默认复用上次保存的统一要求。
- 分析任务在进程重启时必须从 `queued/analyzing` 恢复为可重试的 terminal 状态，并提供 retry/reanalyze API。
- 所有计划 API 使用明确的 Pydantic request/response models 和一致的 HTTP 状态语义。

### 2. Generation consistency and governance

- 同一 plan 的重复或并发 POST 必须幂等；不得返回未持久化的 run，不得留下 orphan prototype。
- Active-run 检查、source-backed prototype 映射、run、run items、seed 和 plan links 必须在受控事务中冻结，适配单 SQLite connection 的并发模型。
- HTML/version 保存与 run item `done` 必须原子提交；进程崩溃不能造成版本已存在但 item 仍 `generating`。
- 只有收到 generator 的明确 `done` 事件且版本保存成功才允许标记 item 成功；空流或仅 meta/delta 的流必须失败。
- `source_hash` 仅在生成成功后推进；失败的 update 不得被后续分析误判为 unchanged。
- Generation gate 必须 fail-closed，并接入预算、全局并发和模型并发限制；每个 run 的局部并发仍最多为 2。
- 计划级全局要求、项目上下文和逐页 brief 必须共同组成 restore seed，且 metadata 明确记录 restore baseline。
- 重启时 interrupted item/run 的计数和状态必须一致；retry 只处理 failed/interrupted 项。
- Generation run snapshot 必须包含页面标题、状态、错误、version、started/completed timestamps 和实时 counters。

### 3. Review and recovery UX

- 计划候选按 package/surface 分组，支持 surface/action/status 筛选、组级/全局全选与取消，并包含 missing 状态。
- 项目上下文、统一要求、标题、摘要、brief、states、selection 可编辑且刷新后恢复。
- Evidence 详情正确显示 `start_line/end_line`、kind、confidence、diagnostic；前后端字段一致。
- queued、analyzing、ready、stale、partial、unsupported、analysis_failed、interrupted 使用稳定 i18n key、不同 banner 和明确恢复动作。
- Generation run 在刷新后通过 plan 查询 active/latest run 或 URL run ID 恢复；启动失败即使没有 run 也必须显示用户可见错误。
- 进度列表显示页面标题、本地化状态、失败详情和重试入口；纯 interrupted run 也可重试。
- 所有加载错误保留已加载数据并显示错误，不得清空旧 prototype detail。
- 桌面和 375/390px 窄屏无裁切、重叠或不可操作控件；必要时重排或提供明确横向滚动。
- 键盘焦点、Dialog Escape、表格/选择控件和 ARIA 行为通过浏览器 smoke。

### 4. Release hardening

- 新增分析/生成 duration、count、success/failure/interrupted observability，失败记录可定位 plan/run/item。
- 提供可配置 feature flag，关闭时隐藏入口并拒绝新分析/生成，但不破坏已有手动原型能力和历史数据。
- README/Trellis spec 记录支持矩阵、restore 基线、限制、回滚方式和真实模型人工验收步骤。
- 新增 prototype 模块全部进入 mypy strict coverage，后端完整测试门禁通过。
- 前端 test、typecheck、lint、format check 全部通过。

## Acceptance Criteria

- [ ] VideoNote 扫描稳定得到 19 个主应用页面族，并明确报告 browser extension unsupported。
- [ ] 同行数页面修改和纯 CSS/token 修改会使对应 plan stale/update；无关页面保持 unchanged。
- [ ] 真正空请求体可创建计划，空输入默认 restore，并复用上一计划统一要求。
- [ ] fake planner 生成 19 项带有效 evidence IDs 的计划；非法/未知 evidence ID 被拒绝。
- [ ] 分析进程重启后计划进入可恢复状态，用户可重新分析。
- [ ] 两个同步并发 generate POST 只形成一个持久化 run，不出现事务嵌套错误或 orphan prototype。
- [ ] 空 generator stream、无 done stream、版本保存失败都将 item 标记 failed 且不推进 source hash。
- [ ] 版本与 run item 状态原子一致；重启后 interrupted counters 正确且可重试。
- [ ] 预算或全局/模型并发 gate 不可用/拒绝时生成 fail-closed，并显示用户可见错误。
- [ ] 刷新计划页可恢复 generation run、页面标题、进度、错误和 retry。
- [ ] 审阅页具备 package/surface 分组、筛选、批量选择、正确 evidence 行号和所有恢复动作。
- [ ] 1164px、390px、375px 浏览器 smoke 无溢出或重叠，键盘操作通过。
- [ ] 手动创建、单原型迭代、版本切换、预览和 regenerate-all 不回归。
- [ ] 后端 focused 与完整 pytest、Ruff、mypy strict 全绿。
- [ ] 前端完整 test、typecheck、lint、format check 全绿。
- [ ] 中文界面新建计划后，项目上下文、证据解释、诊断、标题、摘要和 brief
      均为中文；路径与源码片段保持原文且证据引用可追踪。
- [ ] 分析阶段实时显示当前批次/总批次；生成阶段在首屏持续显示已处理、成功、
      失败、运行中、排队中、当前页面、耗时和输出活动。
- [ ] 8 项成功、5 项失败的终态显示“已处理 13/13”，并可逐项查看失败原因和重试。
- [ ] SSE 断线或代理缓冲时自动通过轮询恢复最新持久化快照，保留旧数据并显示连接错误。
- [ ] Claude Code 原型 UI 工程师通过 Runtime Catalog 使用 MiniMax，直接读取项目代码并
      写入隔离 staging HTML；最终模型消息不包含完整 HTML，因而不受单次输出 token 截断。
- [ ] 项目驱动生成提示词只包含当前页面身份、目标路由和产物协议；源码路径、hash、
      evidence、项目上下文、restore seed 与其他页面路由不会传给 Claude。Claude 不可用时
      在冻结 run/prototype 前失败，不回退 direct HTTP。
- [ ] 成功版本存在于项目 `prototypes/<prototype-id>/<version-id>/index.html`，磁盘写入失败
      不创建正版本、不推进 source hash；预览拒绝缺失、越界或与数据库副本不一致的文件。
- [ ] staging 路径穿越、符号链接、非法 UTF-8、不完整 HTML、checksum 不一致和项目源码
      修改均被拒绝，且 prototype/version/run-item 保持原子一致。
- [ ] 合法最终 HTML 不因 Claude 使用 Bash、单次大 Write、非顺序 Edit 或其他工具策略而
      被拒绝；后端与审计不读取工具日志来重放 HTML。
- [ ] 完整保存 Claude stdout/stream-json、思考、工具参数与结果、命令、助手消息、最终
      响应/HTML、trace、状态和审计载荷，供 Agent 调试、复核与续跑；这些数据不参与产物验收。

## Definition of Done

- 所有验收阻断都有实现修复和针对性回归测试，不以跳过测试、放宽类型或静默 catch 规避。
- 跨 API/service/store/frontend 的字段和状态在测试中端到端校验。
- 浏览器 smoke 保存可复现结果；不执行默认付费全量生成。
- 支持矩阵、运行限制、feature flag 回滚与人工真实模型验收步骤有文档。
- 工作区中与本任务无关的既有修改保持不变。

## Technical Approach

1. 先修 evidence/planning schema、hash、limits、recovery 和 API response contracts。
2. 将 generation freeze 和 completion 改为 store-owned 原子操作，增加 plan 级互斥/数据库唯一约束，并把治理限制提升到共享协调器。
3. 扩展 generation snapshot/查询 API，再重构审阅页为可恢复、可分组、响应式的 operational table。
4. 补齐 observability、feature flag、文档和完整质量门禁，最后进行浏览器复验。

## Decision (ADR-lite)

**Context**: 当前实现的 happy-path 单元测试通过，但并发、重启、跨层字段和恢复语义未形成统一契约，继续零散打补丁会重复制造不一致。

**Decision**: 保留现有两阶段产品流程和数据模型方向，以 store 原子操作、严格 typed contracts、持久化恢复和共享治理协调器作为修复边界；UI 只消费持久化 snapshot，不把 run 生命周期留在 React 临时 state。

**Consequences**: 改动横跨 evidence、planning、generation、SQLite、API 和 frontend，测试数量会上升；换取的是可证明的幂等、恢复和发布门禁。真实模型质量仍由显式人工验收负责，自动测试只使用 fake runtime。

## Out of Scope

- 自动运行 VideoNote 或其他任意目标项目采集 DOM/截图。
- 自动登录、构造动态路由数据或访问生产数据。
- 为 VideoMemo browser extension 生成原型。
- 自动执行真实付费的 19 页批量 HTML 生成。
- 与本次验收无关的项目级重构。

## Technical Notes

- 原始产品设计：`.trellis/tasks/archive/2026-07/07-11-project-driven-prototype-generation/prd.md`。
- 分任务 PRD：`07-11-prototype-evidence-foundation`、`prototype-planning-backend`、`prototype-plan-review-ui`、`prototype-generation-runner`、`prototype-integration-hardening`。
- 关键实现：`backend/app/application/project_evidence_service.py`、`prototype_planning_service.py`、`prototype_generation_service.py`、`backend/app/adapters/async_sqlite_store.py`、`frontend/src/features/prototype/PrototypePlanReviewPage.tsx`。
- 防御式编程遵循根目录 `AGENTS.md`：治理错误必须 fail-closed，typed model 直接访问，内部逻辑不使用宽泛兜底，前端错误必须可见且保留旧数据。

## Acceptance Record (2026-07-12)

### Passed

- Backend full test gate: `1425 passed, 77 skipped, 174 deselected`; Ruff and
  mypy strict (`289` source files) passed.
- Frontend full gate: `437/437` tests, TypeScript typecheck, ESLint, Prettier,
  and production build passed.
- Browser smoke on the persisted VideoNote run showed `13/13` processed,
  `8` succeeded, `5` failed, `0` running, and `0` pending. Evidence details
  exposed localized kind/confidence/diagnostic, file path, line range,
  reference index, excerpt, and evidence ID.
- Desktop and 375/390px progress layouts were checked without horizontal
  overflow; the final desktop page had no application console errors.
- Focused regressions cover complete planner envelopes, MiniMax quote repair,
  direct-stream `message_stop`, final artifact manifest/path/checksum/source
  validation independent of Claude's tool sequence, cross-service freeze races,
  v7 semantic backfills, strict nested snapshots, lifecycle/counter matrices,
  SSE identity/heartbeat, and bounded polling recovery.
- UI-semantic planning now runs as a `prototype_planning` task through the
  Claude Code `prototype_ui_engineer` in an isolated read-only worktree. zh-CN
  plans accept stable state identifiers such as `default` while continuing to
  enforce Chinese project context, titles, summaries, and briefs.
- Real database restart loaded schema version `7`; persisted create/update
  evidence references and retryable generation seeds were non-empty.

### Explicit Manual Boundary

- No paid MiniMax planning or generation batch was started during automated
  acceptance. The Runtime Catalog/Claude Code path is covered with fake/runtime
  integration tests; a real-provider quality run remains an explicit user
  action.
- The accepted historical VideoNote plan predates `output_locale` enforcement,
  so its stored project context, titles, summaries, and briefs remain English.
  New zh-CN plans are rejected when model-authored fields are dominantly in the
  wrong language. Replacing the historical text requires an explicit reanalysis
  and is not performed as a migration or silent translation.
