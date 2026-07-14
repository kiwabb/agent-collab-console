# PR1 - 原型项目证据解析基础

## Goal

建立只读、可解释、可扩展的项目证据层，准确识别多包仓库中的 UI surface，并从 Next.js 文件路由及 React Router JSX 路由树生成逻辑页面族。VideoNote 是本任务的强制验收 fixture。

## Parent Design

- [`../07-11-project-driven-prototype-generation/prd.md`](../07-11-project-driven-prototype-generation/prd.md)
- [`../07-11-project-driven-prototype-generation/info.md`](../07-11-project-driven-prototype-generation/info.md)
- [`../07-11-project-driven-prototype-generation/research/jsx-route-parser-selection.md`](../07-11-project-driven-prototype-generation/research/jsx-route-parser-selection.md)

## Dependencies

- 无前置开发任务。

## Requirements

- 实现统一 `RepositoryBoundary`，限制读取范围、symlink、忽略目录、文件数量、单文件大小和总证据大小。
- 仓库边界失败必须返回明确错误并拒绝分析，不能返回空成功。
- 实现 `PackageInventoryProvider`，在多包仓库中发现 manifest、框架信号、入口、样式入口和 surface 类型。
- 引入并锁定兼容的 `tree-sitter` 与 `tree-sitter-typescript` 版本，不依赖目标项目 `node_modules`。
- 定义类型化的 package、surface、route、layout、component、evidence、diagnostic 和 logical-family models。
- 实现以下 provider：
  - Next.js App Router。
  - Next.js Pages Router。
  - React Router JSX `<Routes>/<Route>`。
  - React 页面目录低置信度 fallback。
- React Router provider 必须支持 import alias、嵌套路由、index、无 path layout、动态参数、redirect、wildcard 和静态不可求值 diagnostics。
- 实现逻辑页面族归并：同主组件的 new/edit route 合并为 states；layout/redirect/wildcard 默认不生成。
- 计算稳定 `candidate_id` 与独立 `source_hash`，结果不依赖文件遍历顺序。
- 不调用 LLM、不写 SQLite、不创建 prototype。

## Acceptance Criteria

- [ ] VideoNote inventory 同时发现 `VideoMemo_frontend` 和 `VideoMemo_extension`。
- [ ] 主 React 应用标记 supported，浏览器扩展标记 browser-extension/unsupported 且有明确原因。
- [ ] 从 `VideoMemo_frontend/src/App.tsx` 得到 19 个默认逻辑页面族。
- [ ] `BrowserRouter` 与 `HashRouter` 不重复生成两套候选。
- [ ] `ProviderForm` 的 new/edit 合并为一个页面族及两个状态。
- [ ] `<Navigate>`、共享 layout、`path="*"` 不进入默认候选。
- [ ] 静态无法求值的 route 返回 partial diagnostic，不猜测 path。
- [ ] symlink 越界和读取上限触发 fail-closed 错误。
- [ ] Next.js 现有路由 fixture 保持确定性结果。
- [ ] parser import smoke 与相关 backend unit tests 通过。

## Definition Of Done

- 新 provider 协议和 evidence models 有类型检查与单元测试。
- VideoNote 使用最小测试 fixture，不在测试中依赖用户本机绝对路径。
- 后端 Ruff、mypy 和本任务相关 pytest 通过。
- 依赖与 provider 支持范围写入项目规范或模块文档。

## Out Of Scope

- LLM 生成项目上下文或页面 brief。
- 计划持久化与 HTTP API。
- Vue Router、浏览器扩展页面和运行时浏览器采集。
- 执行目标项目脚本或加载目标源码模块。
- HTML 原型生成。

## Delivery Boundary

本任务完成后，调用方可以对任意项目获得类型化 `ProjectSurfaceManifest`；尚不能在产品 UI 中创建或审阅原型计划。
