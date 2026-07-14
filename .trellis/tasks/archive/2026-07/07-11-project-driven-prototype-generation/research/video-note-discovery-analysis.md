# VideoNote 页面发现与旧方案失效分析

## 调研范围

- 当前项目的原型前后端实现。
- 已归档的 code-scan 删除方案与删除提交 `b73ea0df`。
- VideoNote 仓库的包结构、路由声明和页面目录。
- 旧 `CodePrototypeDiscoveryService` 的实际匹配规则。

## 当前能力边界

- 当前原型工作台只支持手动填写 `title + brief` 创建原型。
- `PrototypeService.stream_events()` 可以从 seed brief 生成单文件 HTML，并支持后续迭代。
- `PrototypeService.regenerate_all_stream()` 只能重新生成已经存在的原型，不能发现页面或创建候选。
- `Prototype` 数据模型和 SQLite 表仍保留 `source_kind`、`source_ref`、`source_hash`、`source_meta_json`，可以兼容新的来源追踪方案，不需要先做删列或迁移。

## VideoNote 实证

VideoNote 是一个多包仓库，根目录没有 `package.json`。至少包含：

- `VideoMemo_frontend/`：Vite 6、React 19、React Router DOM 7。
- `VideoMemo_extension/`：Vite、Vue 3、浏览器扩展。
- 其他后端、部署和 worker 子目录。

Web/桌面主应用的路由集中声明在：

```text
VideoMemo_frontend/src/App.tsx
```

路由不是由文件目录自动映射，而是通过嵌套的 `<Routes>` / `<Route>` 声明。当前可识别的主要页面族包括：

- `/onboarding`
- `/`
- `/collections`
- `/collections/:id`
- `/knowledge`
- `/tasks`
- `/trends`
- `/subscriptions`
- `/articles`
- `/batch-import`
- `/guide`
- `/settings/model`
- `/settings/model/new`
- `/settings/model/:id`
- `/settings/download`
- `/settings/download/:id`
- `/settings/transcriber`
- `/settings/feishu`
- `/settings/local-downloader`
- `/settings/access-password`
- `/settings/monitor`
- `/settings/about`

这些路由还带有两项重要上下文：

- Web 使用 `BrowserRouter`，Tauri 桌面端使用 `HashRouter`。
- `MainLayout` 和 `SettingPage` 是嵌套布局，页面原型需要继承共同导航和布局语义，而不能把每个叶子组件当成完全独立的页面。

## 旧扫描器为什么得到 0 候选

旧 `CodePrototypeDiscoveryService` 只识别以下模式：

- Next.js App Router 的 `app/**/page.tsx`。
- Next.js Pages Router 的 `pages/**/*.tsx`。
- `src/routes/**/*.tsx` 或 `src/pages/**/*.tsx` 文件名映射路由。
- `src/features/**/*Page.tsx` 命名约定。

它没有处理：

- 多包仓库中的嵌套应用根目录。
- React Router JSX 路由树。
- 路由嵌套、index route、redirect、layout 和动态参数。
- Vue Router、扩展 popup/options/content 页面等不同 UI surface。
- 导航配置、README、设计 token 和共享布局提供的产品语义。

此外，旧实现把主文件和最多四个 import 的截断源码拼成 prompt。这能提供代码片段，但不能稳定还原用户任务、页面信息架构、动态数据、异常状态和跨页面一致性。

## 结论

旧 code-scan 的删除是正确的，但退化成逐页手输不是完整产品方案。新的能力必须把两个问题分开：

1. **页面发现**：从包、路由、导航、布局和源码证据构建可审阅的页面清单。
2. **设计规划**：基于项目级产品上下文，为每个页面生成可编辑的设计 brief，再复用现有 HTML 原型生成器。

推荐采用混合架构：确定性项目清单与框架适配器负责可解释的发现，LLM 只负责把已有证据整理成页面意图和设计 brief。运行时截图可作为后续增强，不作为 MVP 的唯一或前置路径。
