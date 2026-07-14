# 重构前端卡片式布局

## Goal

将当前前端从「浮起工作台外框 + route 内重复卡片集合」重构为层级清晰、空间连续、适合长时间工作的桌面 Pane Graph；覆盖全局工作台壳层和主要结构性卡片页面，同时保留真正表示独立业务对象、预览坐标系或浮层的卡片，且不破坏现有功能、交互语义和正在进行的未提交改动。

## What I already know

- 用户明确反馈当前前端卡片式布局观感不好，希望协助重构。
- 当前工作树已经包含 `ProjectShell.tsx` 和多个 `frontend/src/features/prototype/structured/*` 文件的未提交修改，后续实现必须在此基础上增量调整，不能覆盖或回退。
- 当前 `frontend/package.json` 的实际基线是 Next.js 15.5、Tailwind CSS v4、Base UI 1.4（项目说明中的 Next.js 14 已滞后）；设计调整应以 checkout 为准并沿用现有栈，不新增无必要的 UI 框架。
- 这是桌面开发者工具，不应套用营销页式的等宽卡片矩阵；结构性区域更适合使用应用框架、分栏、工具栏、轨道、检查器和分隔线表达。
- 实机审计已推翻初步猜测：在 `/projects`、`/projects/[id]`、`/projects/[id]/prototypes` 三个目标界面中，当前最过度卡片化的是 `/projects` 项目配置页；结构化原型工作台的未提交版本已经基本完成连续编辑器化。
- `/projects` 目前是左侧浮起项目面板 + 右侧最多五个同权重 Card，项目身份、设置、分支和活动没有层级区分，分支信息还出现两次；移动端文档约 2308px 高且项目卡头部存在横向裁切。
- `/projects/[id]` 的工作区列表本身已正确使用连续表格行，但上方四个 KPI 卡片仍造成重复容器；移动端工具栏和固定六列表格存在明确的横向溢出与不可见内容。
- 当前未提交代码已经开始把结构化原型页改成连续编辑器：`ProjectShell layout="workspace"`、三栏 Grid、单边分隔线、行式 Page Rail/Palette，以及无外层圆角卡片的 Generation 区域；后续应将其视为必须保留和完善的基线，而不是回退到 `HEAD`。
- 仓库已有完整的 surface 层级：app ground → 结构 pane → 行/控件 → 独立内容对象 → 真实预览边界 → 浮层；无需创建新调色板或平行设计系统。
- 完整 route-map 确认全局 `WorkbenchShell` 是跨路由最高杠杆的结构性卡片来源；同时补出首版计划遗漏的 Settings、项目 Conductor/启动配置。
- 根路由 `/` 使用独立的 `WorkbenchPage`，不会继承 `WorkbenchShell` 修改；其中 workspace、issue、Kanban task 多数是真正可选择/可操作的业务对象卡，不应被机械拍平，只做全局语言一致性审查。
- Benchmarks 同样不挂载 `WorkbenchShell` 且未在已检查的侧栏入口中发现，需要单独处理 route-shell 一致性，不能假设全局壳层改造会自动覆盖。

## Constraints and assumptions

- 本次重点是重构布局和视觉层级，而不是改变业务流程、数据模型或 API。
- 「减少卡片」不等于完全取消容器；只有表示独立对象、可选择内容、浮层或确有分组必要时才保留卡片语义。
- 优先面向桌面工作台体验，同时保持现有窄屏降级路径不退化。

## Open Questions

- 无。范围、外框模式、交付拆分、pane 能力、内容宽度和视觉气质均已确认。

## Requirements

- 识别并按影响排序当前主要卡片式布局问题，不凭印象全局重写。
- 将页面级结构区域改为连续画布/分栏/轨道等结构性容器，减少嵌套边框、重复阴影和同半径圆角。
- 保留真正有对象语义或浮层语义的卡片，并明确它们与页面 chrome 的视觉差异。
- 保持原型生成、页面选择、画布预览、属性/状态查看、项目导航等现有交互可用。
- 全局范围包含：`WorkbenchShell`/`AppSidebar`/`PageFrame`、Projects、Project Workspaces、Project Conductor、启动与环境配置、Settings、Knowledge、Benchmarks、Issue detail/insight rail，以及 structured prototype 剩余结构不一致处。
- 根工作台 `/`、Help、Audit、Artifacts 与 Conductor Monitor 纳入最终一致性审计：只清除结构性容器；workspace/issue/task/artifact/conductor 等独立业务记录继续允许卡片表达。
- 复用现有设计 token、共享组件与 Tailwind v4 约束，不引入平行设计系统。
- 主内容宽度按任务密度分型：表格、时间线、画布和分析页使用可用宽度；设置、表单和文档 section 在主 pane 内限制可读宽度，但不重新套圆角卡片。
- 尊重并融合当前未提交修改。

## Acceptance Criteria

- [ ] 目标页面不再呈现为多个同权重圆角卡片的堆叠，主次区域一眼可辨。
- [ ] 页面 shell、结构分栏、可交互对象、浮层四种层级有明确且一致的 surface/border/radius 规则。
- [ ] 整体呈现克制工具感：品牌色只承担 active/focus/status 信号；结构 pane 使用中性 surface 与 1px subtle divider；渐变、blur 和装饰性 shadow 不再承担页面分组，阴影主要保留给浮层。
- [ ] 结构化原型现有核心功能和状态展示均保留，相关前端测试通过。
- [ ] 常用桌面宽度下画布获得更连续、更大的工作空间；窄屏下无不可达控件或严重溢出。
- [ ] 键盘焦点、hover/pressed、选中和禁用状态可辨识，且不只依赖颜色。
- [ ] TypeScript 类型检查与目标测试通过，并通过实机浏览器验证关键流程。

## Definition of Done

- 相关实现与测试完成，且不覆盖无关工作树改动。
- `npx tsc --noEmit` 和目标前端测试通过；若开发服务正在运行，不执行会破坏 `.next` 的 `npm run build`。
- 使用真实浏览器验证目标页面的桌面与窄屏布局、交互状态和控制台错误。
- 如形成可复用的前端布局规范，更新对应 Trellis component guideline。
- 记录风险、验证结果和明确的 out-of-scope。

## Research References

- [`research/current-layout-audit.md`](research/current-layout-audit.md) — 以 1440/900/390px 实机审计 `/projects`、项目工作区和结构化原型；确认 `/projects` 是目标范围中最过度卡片化页面，并发现两个项目页的移动端横向溢出，而结构化原型当前已基本连续化。
- [`research/comparable-layout-patterns.md`](research/comparable-layout-patterns.md) — ccgui、vibe-kanban、VS Code、GitHub Projects、JetBrains 与 Linear 一致采用「rail/list pane → 主工作面 → inspector/output」的区域模型；重复集合优先表格/行，检查器内部优先 section/divider，卡片只用于独立对象。
- [`research/design-system-surface-hierarchy.md`](research/design-system-surface-hierarchy.md) — 仓库现有 token 足以形成「结构区域靠分隔线连接、对象才使用卡片、浮层才产生阴影」的完整层级；同时指出 `lg` 三栏的实际宽度门槛与局部焦点语义问题。
- [`research/recovered-global-route-map.md`](research/recovered-global-route-map.md) — 补跑原 Workflow 唯一失败的全局 route-map；补出 Settings、项目 Conductor/启动配置、根工作台与 Benchmarks 的独立壳层差异，并建立“结构性卡片 vs 独立业务对象卡”的全局边界。

## Expansion Sweep

### Future evolution

- 为未来多文件/多页面原型、可折叠检查器和更复杂画布操作保留稳定的工作台分区。
- 让 surface 层级规则可复用到项目内其他工具页，而非依靠页面内一次性 class 组合。

### Related scenarios

- 项目顶层导航与结构化原型内部导航需要保持层级连续，避免「壳层卡片包工作台卡片」的二次框选。
- 空状态、生成中、错误、无页面和窄屏状态应使用同一布局骨架，避免状态切换时整体跳变。

### Failure and edge cases

- 不能因减少容器而损失可点击范围、选中态、键盘焦点或语义分组。
- 不能回退当前未提交的结构化原型工作流整合与路由改动。
- 需要防止固定侧栏宽度在中等屏幕挤压画布，并定义合理的折叠/堆叠行为。

## Technical Approach

采用边到边的编辑器式 Pane Graph：`WorkbenchShell` 不再将侧栏与 route 内容呈现为独立浮起圆角面板，而是使用 CSS Grid/Flex 将全局导航、header、主工作面与上下文区域组织为连续 sibling panes。结构区域通过中性 surface、留白与单边分隔线表达；重复记录使用行/表格；只有真实独立对象、预览边界与浮层保留完整容器语义。数据密集页面使用可用宽度，设置/文档型内容在 pane 内限制可读宽度。

已锁定的实现原则：

1. 顶层 `WorkbenchShell` 改为边到边 pane graph；全局侧栏、header 与 route 内容是由细分隔线连接的 sibling panes，不再保留 22/30px 浮起圆角外框。
2. toolbar、rail、canvas well、inspector 采用 `bg-surface`/`bg-background` 与单边 `border-border-subtle` 连接，结构区域半径为 0 且无阴影。
3. Page/Palette 等集合默认使用行与 `divide-y`，通过左/下品牌边、文本与 ARIA 状态共同表达选择。
4. 只有 evidence、blueprint、alert 等独立领域记录允许 `rounded-lg` raised surface；真实浏览器/设备预览保留完整边界但不做装饰性浮起。
5. 菜单、对话框、sheet 等浮层继续使用 `bg-popover`、完整边界和阴影。
6. 保留 `min-h-0`/`min-w-0` 的全高工作区链路；重新评估当前 `lg` 即切到 `240px + 440px + 300px` 三栏造成的约 1272px 实际视口门槛。
7. 布局减法不能牺牲共享控件的 `focus-visible`、44px 常用触达尺寸、非颜色选中信号、compact mode 或 reduced-motion 支持。
8. 本阶段固定 pane 的语义宽度并使用响应式折叠/切换，不引入新 splitter 依赖或拖拽宽度持久化；先让结构和断点稳定。
9. 视觉气质采用克制工具感：结构层使用中性背景与 hairline divider；品牌色集中于当前项、键盘焦点和状态；移除用于页面分组的 ambient gradient、backdrop blur 与装饰阴影。

## Feasible approaches

### A. 项目区域整体重构（推荐）

- `/projects` 改成连续 master/detail：左侧项目列表是结构 rail，右侧以项目标题/动作条、紧凑摘要、分隔 section、行式分支/活动组成一个连续详情面。
- 删除重复分支区；setup/run command 变成同一配置文档中的边界 section，而不是会 hover 浮起的大 Card。
- `/projects/[id]` 将四个 KPI 卡改为一条紧凑 summary strip；保留已有行式工作区列表，并修复移动端工具栏与固定列溢出。
- 结构化原型不再大改，只收尾剩余的 Flow/inspector 层级、焦点语义与中间宽度回归，保护现有未提交改造。
- 优点：直接解决实机中最明显的问题，同时让「项目选择 → 项目工作区 → 原型编辑器」形成一致的工具界面。
- 代价：涉及两个项目主页面及结构化原型回归，范围大于单页润色，但仍围绕同一产品路径。

### B. 只重构 `/projects`

- 将最差的项目配置页改为连续 master/detail，去重分支，修复移动端头部裁切。
- `/projects/[id]` 与结构化原型只做测试，不调整布局。
- 优点：改动最聚焦、回归面最小。
- 代价：进入项目后仍会看到 KPI 卡片和移动端表格溢出，产品路径的视觉语言不完整。

### C. 全局工作台去卡片化

- 在 A 的基础上继续调整全局 `WorkbenchShell`，并扩展到 Knowledge、Benchmarks、Issue insight rail 等已识别的卡片密集页面。
- 优点：可一次形成覆盖全产品的结构性 surface 语言。
- 代价：跨功能面过大，当前任务难以在充分实机回归下保持可审阅；也更容易干扰工作树中的其他进行中修改。

## Decision (ADR-lite)

**Context**: 实机审计确认问题不是结构化原型单页，而是项目入口与项目概览仍将结构容器、配置字段、摘要指标和记录集合都表达为同权重圆角卡片；结构化原型当前未提交版本已基本转为连续编辑器。

**Decision**: 用户选择 C「全局工作台去卡片化」，并选择最外层采用「边到边 Pane Graph」：取消侧栏与主内容区的装饰性浮起圆角外框，让全局导航、header、route 内容与上下文工具成为由细分隔线连接的 sibling panes。实现范围覆盖全局 shell、Projects、Project Workspaces、Knowledge、Benchmarks、Issue detail/insight rail，以及结构化原型剩余不一致处。

**Consequences**: 这是跨 feature 的前端布局系统重构。产品将明显从“企业仪表盘卡片集”转向桌面开发工具；用户选择拆成多个子任务：先建立共享 pane/page-section 规则，再分页面落地，最后集中做全局回归。会调整多个页面、feature-local 组件、测试与 component guideline，但不修改后端契约、不引入新 UI 框架、不重置当前工作树。

## Implementation Plan (child tasks)

1. [`07-14-global-pane-graph-foundation`](../07-14-global-pane-graph-foundation/) — 将 `WorkbenchShell`/`AppSidebar` 改成边到边 sibling panes，建立共享 page section、summary strip 与 divider 规则，并更新全局规范。
2. [`07-14-projects-workspace-continuous-layouts`](../07-14-projects-workspace-continuous-layouts/) — 重构 `/projects` master/detail，去重分支；精简 `/projects/[id]` KPI 并修复移动端工具栏/表格溢出。
3. [`07-14-knowledge-benchmarks-structural-layouts`](../07-14-knowledge-benchmarks-structural-layouts/) — 将 Knowledge 改为 command bar + result list，将 Benchmarks 改为分析工作面 + 上下文区域。
4. [`07-14-issue-prototype-layout-consistency`](../07-14-issue-prototype-layout-consistency/) — 将 Issue insight stack 改成连续 inspector section，并收尾 structured prototype 的 Flow、焦点语义与中间宽度一致性。
5. [`07-14-global-layout-regression-verification`](../07-14-global-layout-regression-verification/) — 覆盖 Settings、Project Conductor/启动与环境配置，并审计独立根工作台、Help、Audit、Artifacts、Conductor Monitor 的结构一致性；随后汇总测试、浏览器桌面/中间/移动视口、主题/compact/reduced-motion 与关键交互回归。

依赖顺序：1 →（2、3 可并行）→ 4 → 5。第 2 项明确包含 Project Conductor、startup config 和 env config；第 3 项包含 Settings（必要时根据代码体量再拆实现批次，但不再另开 Workflow）。所有子任务共享父任务的设计决策与四份研究文件，并保持当前工作树中的结构化原型与原型删除改动。

## Out of Scope (explicit)

- 后端 API、数据库或原型生成协议重构。
- 引入新的组件库、图标库或完整品牌重塑。
- 与卡片布局无关的新业务功能。
- 不把根工作台的 workspace/issue/Kanban task、Artifacts issue group、Conductor record 等独立可操作业务对象强制改成无边界行；如需新增 list/table 模式，另作产品功能。
- 不为未挂载的 `InboxDashboard` 做视觉重构，除非后续发现真实路由入口。
- 本阶段不加入可拖拽 splitter、键盘调宽或 pane 宽度持久化；使用固定语义宽度、响应式断点和现有移动端 pane 切换。该能力可在布局稳定后作为独立增强。

## Technical Notes

- 共享基础：`frontend/src/features/workbench/WorkbenchShell.tsx`、`components/AppSidebar.tsx`、`components/PageFrame.tsx`、`frontend/src/app/globals.css`。
- 页面范围：Projects/ProjectWorkspaces/ProjectConductor/ProjectStartupConfig/ProjectEnvVarEditor、Settings/MCP/AgentCatalog/RuntimeCatalog、Knowledge、Benchmarks、IssueDetail/IssueSideStack、structured prototype Flow 与相关 inspector 语义。
- 一致性审计：独立根 `WorkbenchPage`、Help、Audit、Artifacts、Conductor Monitor；只处理结构性容器，不抹除独立对象语义。
- Tailwind v4 自定义颜色必须在 `@theme` 中提供别名；不能只依赖 `:root` 变量。
- Base UI 组件沿用仓库既有用法与可访问性语义。
- 当前分支为 `main` 且工作树存在多组并行未提交工作；实现时只做可追踪的增量编辑，不清理、reset 或 broad-rewrite。
- 必须保护结构化原型连续布局和删除功能的交织改动、startup-service-identity 任务及其研究；不得读取、覆盖、清理或暂存 `examples/admin-demo/.env`。
