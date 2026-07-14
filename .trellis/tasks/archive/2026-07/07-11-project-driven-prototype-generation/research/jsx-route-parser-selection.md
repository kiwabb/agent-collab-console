# JSX/TSX 路由解析器选型

## 问题

VideoNote 的页面关系定义在 `VideoMemo_frontend/src/App.tsx` 的嵌套 React Router JSX 中。旧扫描器按目录和文件名推断路由，既无法组合嵌套 path，也无法可靠识别 index、layout、redirect、动态参数和实际渲染组件。

新的 deterministic provider 需要解析 TSX 语法树，不能继续用正则匹配 JSX。

## 候选方案

### 1. Python Tree-sitter + TypeScript/TSX grammar（推荐）

来源：

- [tree-sitter/py-tree-sitter](https://github.com/tree-sitter/py-tree-sitter)
- [tree-sitter/tree-sitter-typescript](https://github.com/tree-sitter/tree-sitter-typescript)
- PyPI 当前可见版本：`tree-sitter 0.26.0`、`tree-sitter-typescript 0.23.2`（2026-07-11 查询）。

证据：

- Python binding 和 TypeScript grammar 都由 Tree-sitter 官方组织维护，MIT 许可。
- `py-tree-sitter` 官方 README 明确提供主流平台预编译 wheel，无额外库依赖。
- `tree-sitter-typescript` 同时提供 TypeScript 和 TSX 两种 grammar，并发布 Python wheel。
- Python 后端可以直接读取 AST 节点的 byte range 与行列位置，适合输出候选 evidence。

优点：

- 后端进程内解析，不依赖目标仓库的 `node_modules`。
- 容错解析适合正在编辑、存在局部语法错误的工作树。
- 可复用到后续 Vue/JSX/其他语言 provider。
- 可以精确定位 evidence 行号，避免正则误配。

约束：

- Tree-sitter 只提供语法树，不负责 TypeScript 类型求值或完整模块解析。
- MVP 只处理静态可判定的 JSX `<Route>` 属性、import alias 和有限的本地模块引用；变量拼装、运行时生成路由必须标记 partial。
- 依赖版本需要成对锁定，并用 VideoNote fixture 覆盖 grammar/API 兼容。

### 2. TypeScript Compiler API 子进程

优点：TypeScript/TSX 语义最完整，熟悉 TypeScript AST 的开发者容易维护。

缺点：后端容器和独立部署需要额外携带 Node runtime、内部 analyzer 包及其 `typescript` 版本；不能依赖目标项目恰好安装 TypeScript。Python 与 Node 之间还需要定义进程超时、输出协议和错误恢复，扩大部署边界。

### 3. 正则或手写文本解析

实现成本看似较低，但无法正确处理 JSX 嵌套、格式变化、表达式属性、alias 和注释，正是旧方案失败的同类原因，不采用。

## 决策

MVP 采用 `tree-sitter` + `tree-sitter-typescript`：

- 在 backend requirements/pyproject 中成对锁定经测试的兼容版本。
- `ReactRouterJsxProvider` 只消费 AST，不运行目标代码。
- provider 输出 route tree、component reference、import evidence、line range 和 diagnostics。
- 静态无法求值的 route 进入 `partial` diagnostics；不得猜出一个看似完整的路由。
- Next.js 文件路由继续使用确定性路径规则，不为所有框架强制经过 TSX AST。

## VideoNote 验收样例

provider 必须从 `VideoMemo_frontend/src/App.tsx` 识别：

- `BrowserRouter` / `HashRouter` 只是不同运行容器，不重复生成两套页面。
- 无 path 的 layout route 将 `MainLayout` 记录为子页面 layout evidence。
- index route 映射 `/` 到 `HomePage`。
- 嵌套 settings route 正确组合完整路径。
- `model/new` 与 `model/:id` 都指向 `ProviderForm`，可归并为同一页面族的 new/edit 状态。
- `<Navigate>` redirect、`path="*"` 和默认 404 不进入默认生成集合。
