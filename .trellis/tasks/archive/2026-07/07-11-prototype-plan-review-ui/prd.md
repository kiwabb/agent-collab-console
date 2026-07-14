# PR3 - 原型计划审阅界面

## Goal

把项目分析计划接入原型工作台，提供零输入入口、可恢复的分析状态、按 surface 分组的候选表格以及项目级/页面级编辑能力，让用户在产生 HTML 生成费用前完成确认。

## Parent Design

- [`../07-11-project-driven-prototype-generation/prd.md`](../07-11-project-driven-prototype-generation/prd.md)
- [`../07-11-project-driven-prototype-generation/info.md`](../07-11-project-driven-prototype-generation/info.md)

## Dependencies

- 依赖 `07-11-prototype-planning-backend` 的计划 API 和 SSE snapshot 契约。

## Requirements

- 原型工作台工具栏新增带图标的“从项目生成”命令。
- 点击可零输入创建计划；可选统一设计要求默认加载项目上次保存值。
- 新增项目内计划 route：`/projects/:projectId/prototypes/plans/:planId`。
- 分析阶段展示明确 phase、package/surface 状态和 diagnostics，不使用营销式页面或大型 hero。
- ready 阶段使用紧凑 operational table，按 package/surface 分组。
- 支持 all/create/update/unchanged/low/unsupported 等筛选和固定尺寸状态控件。
- checkbox 控制 selected；用户可以编辑项目上下文、统一要求以及单项 title/summary/brief/states。
- evidence 详情显示路径、行号、发现类型与置信度，不显示未经处理的大段源码。
- 默认选择 high/medium 的 create/update；unchanged、low、unsupported 不选中。
- 保存采用明确 saving/saved/error 状态；失败时保留已加载数据和未提交编辑。
- stale、partial、unsupported、analysis_failed 必须有不同的 banner/status 和恢复动作。
- 本任务只展示“生成所选原型”的预留位置或 capability 状态，不调用尚未实现的生成 API。
- 使用项目既有组件、i18n 和错误处理模式；禁止 silent `.catch(() => {})`、错误清空旧数据或对必填类型加冗余空值保护。

## Acceptance Criteria

- [ ] 用户不填写文字即可从 VideoNote 原型页进入分析计划。
- [ ] 分析完成后显示 19 个逻辑页面族，并单独显示扩展 unsupported 状态。
- [ ] redirect、layout、404 不作为默认候选出现。
- [ ] 用户可按 surface/状态筛选和批量选择。
- [ ] 编辑项目统一要求与页面 brief 后刷新仍保持。
- [ ] SSE/GET/PATCH 失败不会清空已有候选或用户草稿。
- [ ] unsupported 和 partial 状态包含具体原因与证据入口。
- [ ] 键盘可操作表格选择、编辑面板和返回导航，焦点顺序正确。
- [ ] 桌面和窄屏下无文本溢出、控件重排或重叠。
- [ ] 现有手动创建、重新生成全部和 PrototypeCanvas 不回归。

## Definition Of Done

- API/types/hooks/components/i18n 和针对性前端测试齐全。
- 前端 test、typecheck、lint、format check 通过。
- 使用浏览器 smoke 验证分析、审阅、编辑、刷新恢复和错误状态。
- 不启动或模拟真实批量 HTML 生成。

## Out Of Scope

- generation run、进度队列和失败重试。
- 优化设计模式或批量优化。
- 浏览器扩展原型。
- 重新设计现有原型工作台视觉系统。

## Delivery Boundary

本任务完成后，用户可以完成“分析 → 审阅 → 保存”，但不能提交 HTML 生成。
