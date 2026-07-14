# 项目驱动的批量原型生成

## Goal

为项目原型工作台补齐“自动理解项目并批量创建页面原型”的完整流程。用户不再逐页手工输入需求；系统先从仓库证据生成可审阅的页面规划，用户确认或编辑后再批量生成 HTML 原型，同时避免恢复旧 code-scan 对少数框架硬编码、直接用截断源码猜设计的缺陷。

## What I Already Know

- “从代码生成原型”在提交 `b73ea0df` 中被有意删除，原因包括框架覆盖窄、源码推断失真，以及 VideoNote 扫描为 0 候选。
- 当前仍保留手动创建、单原型生成与迭代、版本切换、预览和“重新生成全部”。
- “重新生成全部”只处理已经存在的原型，不能发现页面或批量创建 seed brief。
- `Prototype` 与 SQLite 仍保留 `source_kind/source_ref/source_hash/source_meta_json`，新方案可以复用来源追踪字段并兼容历史 code prototype。
- VideoNote 是多包仓库；主前端位于 `VideoMemo_frontend/`，使用 Vite + React Router，路由集中在 `src/App.tsx` 的嵌套 `<Route>` 树中。
- VideoNote 同时包含 Vue 浏览器扩展，项目理解必须先识别 UI package/surface，不能假设仓库只有一个前端。

## Research References

- [`research/video-note-discovery-analysis.md`](research/video-note-discovery-analysis.md) - VideoNote 页面清单、路由证据和旧扫描器失效原因。
- [`research/jsx-route-parser-selection.md`](research/jsx-route-parser-selection.md) - TSX AST 解析器比较与 Tree-sitter 选型。
- [`../07-03-code-driven-generate-all-prototypes/research/axhub-make-code-prototype-design.md`](../07-03-code-driven-generate-all-prototypes/research/axhub-make-code-prototype-design.md) - Axhub 的资源身份、元数据预览、状态与来源追踪模式。
- [`../archive/2026-07/07-10-remove-code-scan/plan.md`](../archive/2026-07/07-10-remove-code-scan/plan.md) - 旧功能删除的产品与技术依据。

## Product Principles

- **先规划，后生成**：先给出页面候选和 brief，用户确认后才产生批量 LLM 生成费用。
- **证据可解释**：每个候选必须展示路由、入口、主要源码、共享布局和发现依据。
- **AI 整理意图，不伪造事实**：页面发现以仓库证据为准；证据不足时标记低置信度或 unsupported，不静默猜测。
- **项目上下文只写一次**：品牌、受众、设计系统和公共布局作为项目级上下文复用到全部页面。
- **增量而非全量重做**：再次分析时按稳定 ID 和证据 hash 区分新增、变化、未变和消失页面。
- **失败可恢复**：单页分析或生成失败不清空已有计划和原型，也不阻断其他页面。

## Requirements (Evolving)

### 1. 两阶段工作流

原型页新增“从项目生成”入口，流程分为：

1. 分析项目并生成页面规划。
2. 用户审阅、选择和编辑候选。
3. 批量创建所选 prototype seed。
4. 串行生成 HTML 并展示逐页进度。
5. 完成后进入现有原型列表和单页迭代流程。

分析和生成必须是两个独立动作；打开候选清单不得自动开始 HTML 生成。

启动分析必须支持零输入：用户点击“从项目生成”即可创建计划。入口可以提供可选的项目级统一设计要求，但不能把填写文字设为前置条件。系统先从仓库证据推导项目上下文和逐页 brief，用户在审阅页再决定是否修改；同一项目后续分析默认复用已保存的统一要求，并允许本次覆盖。

### 2. 项目清单与 UI surface 发现

系统必须先识别仓库中的 UI package，而不是只看仓库根目录。每个 package 记录：

- package root、manifest 和框架证据。
- surface 类型，例如 web、desktop、browser-extension、mobile 或 unknown。
- route entry、共享布局、导航配置、样式入口和 README 证据。
- 是否纳入本次原型规划。

MVP 至少覆盖：

- Next.js App Router / Pages Router。
- Vite/React + React Router JSX route tree，包括嵌套路由、index route 和动态参数。
- 无明确路由但存在稳定页面目录的 React 项目，作为低置信度候选。

VideoNote MVP 只为 `VideoMemo_frontend` 主应用生成候选。`VideoMemo_extension` 仍需被 package inventory 识别为 browser-extension surface，但标记为 unsupported 且不进入默认选择或生成队列。

其他框架必须返回明确的 unsupported/partial 结果，而不是 0 候选且无解释。

### 3. 页面规划模型

每个候选至少包含：

- `candidate_id`：由 package + surface + route/entry 生成的稳定 ID。
- `title`、`route_pattern`、`surface_kind`、`package_root`。
- `primary_source_path`、`source_paths`、`layout_paths`。
- `evidence`：发现信号和对应路径/行号。
- `confidence`：high / medium / low。
- `summary`：页面目标与主要用户任务。
- `brief`：可直接交给现有 HTML generator 的设计需求。
- `states`：默认、空、加载、错误等需要覆盖的代表状态。
- `action`：create / update / unchanged / missing / unsupported。
- `source_hash`：对规范化证据计算，用于增量分析。

候选按“逻辑页面族”生成，而不是机械地按每个 route pattern 生成：

- 动态参数路由按一个页面族处理，例如 `/collections/:id` 只生成一个集合详情原型，而不是为实体实例生成多份。
- 多个路由渲染同一个页面组件且仅模式不同（例如 `ProviderForm` 的 new/edit）时，合并为一个原型，并把差异记录为 `states`。
- 共享 layout 不单独生成原型，但作为所有子页面的设计证据和公共约束。
- redirect、通配兜底和 404 默认不生成；用户可在审阅阶段显式纳入有独立设计价值的异常页。
- 路由不同且主要页面组件或核心用户任务不同，必须保留为独立页面族。

### 4. 项目级设计上下文

分析结果必须包含可编辑的项目级上下文：

- 产品定位、目标用户和核心任务。
- 品牌与视觉关键词。
- 设计 token、主题、字体、间距和组件库证据。
- 全局导航、共享布局和跨页面交互约束。
- 用户补充的一次性统一要求。

所有页面 brief 引用这份上下文，避免用户为每页重复输入相同信息。

零输入首次生成的目标固定为“还原现状”：保留仓库证据中的信息架构、导航、布局、设计 token 和主要交互，不主动重新设计。基线版本生成完成后，用户可以对任意原型显式发起优化；优化必须创建后续版本并保留基线版本，不能覆盖或伪装成首次还原结果。

### 5. 审阅界面

用户可以：

- 按 package/surface 分组查看候选。
- 勾选或取消候选。
- 编辑标题、摘要、brief 和代表状态。
- 合并误拆的候选或忽略非用户页面。
- 查看证据路径、置信度、变化原因和预计生成数量。
- 保存计划但暂不生成。

低置信度候选默认不自动勾选；unsupported 项不能进入生成队列。

### 6. 批量创建与生成

- 确认后先幂等创建或更新 source-backed prototype，再复用现有单原型生成能力。
- 单个页面失败不得中断其余页面。
- 每页展示 pending / generating / done / failed / skipped 状态。
- 重试只处理失败或用户重新选择的页面。
- 创建成功但 HTML 生成失败时保留 seed 和失败状态，不能删除用户已审阅的 brief。
- 手动原型与历史 code prototype 保持可用。

### 7. 增量同步

再次分析同一项目时：

- stable ID 相同且 hash 未变：`unchanged`，默认跳过。
- stable ID 相同但 hash 变化：`update`，用户确认后生成新版本。
- 新 stable ID：`create`。
- 旧 ID 不再发现：`missing`，只提示，不自动删除原型。

## Feasible Approaches

### Approach A: 混合式项目理解（推荐）

确定性 inventory 和框架适配器负责发现 package、route、layout、navigation 与样式证据；LLM 接收结构化证据，生成项目上下文、页面摘要和 brief。

优点：结果可解释、成本可控、可做稳定 diff；VideoNote 的 React Router 可以准确覆盖。缺点：需要逐步维护框架适配器，未知框架只能 partial/unsupported。

### Approach B: 仓库分析 Agent

调度只读 Codex/架构师 agent 在项目目录中搜索并输出结构化 manifest，再由原型服务消费。

优点：对非标准目录和未知框架更灵活。缺点：耗时和成本更高，结果可重复性较弱，还会把原型功能耦合到 agent 调度、并发、预算和执行状态。

### Approach C: 运行时页面遍历

启动项目，通过浏览器遍历导航和路由，以 DOM、截图和可访问性树作为页面证据。

优点：最接近真实界面，可捕获代码静态分析看不到的状态。缺点：受启动配置、登录、测试数据、动态参数和副作用影响，不能作为所有项目都可靠的 MVP 前置条件。

## Recommended Technical Approach

MVP 确认采用 Approach A，并为未来的 B/C 保留 evidence provider 接口：

```text
Project repository
  -> PackageInventoryProvider
  -> RouteEvidenceProvider[]
  -> ProjectSurfaceManifest
  -> LLM BriefPlanner
  -> Reviewable PrototypePlan
  -> User confirmation
  -> Batch Prototype Creator
  -> Existing PrototypeService HTML stream
```

核心边界：

- `ProjectInventoryService` 只读取仓库，输出原始证据，不调用 LLM。
- `PrototypePlanService` 校验边界输入并调用 LLM，把证据转为严格类型的计划。
- `PrototypeBatchService` 只消费用户确认后的计划，负责幂等写入和生成队列。
- `PrototypeService` 继续负责单原型版本、HTML 流和磁盘镜像，不重新承担项目扫描职责。
- 未知 provider、解析失败或 LLM 输出不合法必须返回明确错误/partial 状态，不能降级为“无页面”。

建议新增持久化的 `prototype_plans` 与 `prototype_plan_items`，而不是只把候选保存在 React state。这样审阅可恢复、生成可重试、刷新页面不会丢失已编辑 brief。

## Proposed API Shape

- `POST /api/projects/{project_id}/prototype-plans`：创建分析计划，返回 `plan_id`。
- `GET /api/prototype-plans/{plan_id}/events`：分析进度流，只读计划状态。
- `GET /api/prototype-plans/{plan_id}`：读取项目上下文、候选和状态。
- `PATCH /api/prototype-plans/{plan_id}`：保存项目级统一要求与选择。
- `PATCH /api/prototype-plan-items/{item_id}`：编辑单页 title/brief/states/selected。
- `POST /api/prototype-plans/{plan_id}/generate`：冻结本次选择、启动生成并返回 `run_id`。
- `GET /api/prototype-generation-runs/{run_id}/events`：批量生成进度流与重连 snapshot。
- `POST /api/prototype-plans/{plan_id}/retry`：只为失败或中断项创建新的 generation run。

创建、生成和重试使用 POST；SSE GET 只订阅已经存在的计划或 generation run，避免把有副作用的操作隐藏在 EventSource GET 中。

## Decision (ADR-lite)

**Context**：旧 code-scan 靠少量目录规则和截断源码生成候选，VideoNote 等多包、Vite + React Router 项目无法覆盖。运行时浏览器证据可以提高视觉还原度，但会把项目启动、登录、动态数据和路由参数注入一并带入 MVP。

**Decision**：MVP 采用静态混合式项目理解。确定性 provider 负责 package、route、layout、navigation 与样式证据，LLM 只基于这些证据生成项目上下文和逐页 brief。MVP 不启动目标项目、不采集 DOM 或截图。

**Consequences**：VideoNote 主应用可以在不运行项目的情况下生成可审阅页面清单，结果可解释、可做增量 diff。视觉像素级一致性和运行时专属状态不属于 MVP；接口层保留 evidence provider 扩展点，后续可以显式添加只读分析 agent 或运行时采集，而不改动计划与生成主流程。

**MVP surface scope**：VideoNote 只覆盖 `VideoMemo_frontend`。`VideoMemo_extension` 的 Vue SFC、manifest、popup/options/content surface 适配放到后续阶段；当前分析必须显示该 package 已发现但未支持，不能静默忽略。

**Prototype granularity**：按逻辑页面族归并候选。stable ID 由 package、surface、主页面组件和规范化 route family 共同决定；同组件的 new/edit 等模式成为一个原型的多个状态，redirect、共享 layout 和通配兜底不计入默认生成数量。

**Input threshold**：分析入口零必填。项目级统一设计要求是可选输入，分析完成后仍可编辑，并在同一项目后续计划中复用；逐页 brief 由系统生成，不要求用户逐项填写。

**Design intent**：首次生成固定为 `restore`，以当前源码证据为基线。是否优化由用户在基线生成后显式决定，并复用现有版本迭代能力生成新版本；模型不得在零输入时擅自改造信息架构或视觉方向。

## Expansion Sweep

### Future Evolution

- 增加只读仓库分析 agent，作为静态 provider 无法覆盖时的显式 fallback。
- 增加可选运行时证据，对重点页面做 DOM/截图辅助的高保真迭代。

### Related Scenarios

- 同一项目存在 Web、桌面和浏览器扩展时，需要按 surface 分批规划，避免把不同产品壳混成一套页面。
- 后续可支持从 PRD/用户故事补充源码尚不存在的新页面，但不能和“已从代码发现”混为同一种证据。

### Failure And Edge Cases

- 仓库路径失效、巨型仓库、symlink 越界、二进制/生成目录、路由解析失败、LLM 超时或非法 JSON。
- 分析期间代码变化、计划过期、动态路由无示例数据、页面需要登录或后端初始化。
- 所有治理门禁失败时拒绝启动分析或生成，并向用户展示可重试错误。

## Acceptance Criteria (Evolving)

- [ ] VideoNote 被识别为多包仓库，至少区分主 React 应用与浏览器扩展 surface。
- [ ] 静态分析能从 `VideoMemo_frontend/src/App.tsx` 还原嵌套路由、index route 和动态参数页面族。
- [ ] 使用同一主页面组件的 new/edit 路由合并为一个候选及多个状态，redirect、layout 和通配兜底不产生重复原型。
- [ ] 用户不输入逐页 brief，也能得到带证据、摘要和初始 brief 的可审阅页面清单。
- [ ] 未填写任何设计要求时也能成功创建计划；填写统一要求时会应用到全部所选页面，并可在后续计划中复用。
- [ ] 用户确认前不创建 prototype、不启动 HTML 生成。
- [ ] 用户可一次填写项目级设计要求并批量应用到所选页面。
- [ ] 首次生成的每个原型都有可追踪的 `restore` 基线版本，未收到用户优化指令时不主动重构页面。
- [ ] 用户发起优化时创建新版本并保留基线，可在版本选择器中返回还原版本。
- [ ] 确认后为所有选中项幂等创建/更新 prototype，并逐页显示生成结果。
- [ ] 单页失败不影响其他页面，刷新后计划和失败状态仍可恢复。
- [ ] 再次分析可以区分 create/update/unchanged/missing，且不会自动删除旧原型。
- [ ] unsupported 或解析失败显示具体原因，不表现为静默空列表。
- [ ] 现有手动创建、迭代、版本切换、预览和重新生成全部行为不回归。

## Definition Of Done

- 方案经用户确认，MVP 与后续增强边界明确。
- 前后端契约、数据模型、失败语义和迁移策略有对应测试。
- VideoNote 作为必测 fixture，覆盖多包和 React Router 嵌套路由。
- 后端 Ruff、mypy、相关 pytest 通过；前端 test、typecheck、lint、format check 通过。
- 浏览器 smoke 验证分析、审阅、生成、重试和刷新恢复流程。
- 文档明确旧 code-scan 不应以原实现直接恢复。

## Out Of Scope (Proposed MVP)

- 自动运行任意项目并爬取所有真实页面。
- 登录自动化、动态参数数据构造和生产数据访问。
- 一次性支持所有前端框架；未知框架先提供 partial/unsupported 诊断。
- 为 `VideoMemo_extension` 浏览器扩展生成原型。
- 根据截图像素级复刻现有 UI。
- 自动删除不再发现的历史 prototype。
- 修改用户项目源码或把生成原型写入用户业务代码目录。

## Technical Notes

- 当前原型核心文件：`backend/app/application/prototype_service.py`、`backend/app/interfaces/sse.py`、`frontend/src/features/prototype/ProjectPrototypesPage.tsx`、`frontend/src/features/prototype/PrototypeCanvas.tsx`。
- 项目启动建议模块已经采用“确定性仓库证据 + LLM 结构化建议 + 本地 fallback”的混合模式，可借鉴边界划分，但原型规划失败不能静默返回空结果。
- React Router JSX 使用 `tree-sitter` + `tree-sitter-typescript` 解析 TSX AST，不用正则或目标项目依赖；详见 parser 选型研究。
- 旧 scanner 源码可从 `b73ea0df^:backend/app/application/code_prototype_discovery.py` 查阅，仅用于回归对照，不作为恢复基线。
