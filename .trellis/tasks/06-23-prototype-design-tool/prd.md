# 类 Claude Design 的原型设计工具

## Goal

让用户在 Console 的某个 **Project** 下，输入一句设计需求（如「一个 SaaS 定价页，三档卡片」），由 LLM **流式**生成可在 iframe 沙箱里**实时预览**的**单文件 HTML** 原型，并通过**聊天指令迭代**产生版本（v1→v2→…）。产物落盘到 repo 的 `.agent-collab/prototypes/`，供后续复用。当前 console 全仓**零** HTML 生成 / iframe 沙箱 / 原型预览能力。

## Scope（已与用户确认）

- **产物形态**：**单文件 HTML**（Tailwind 走 CDN `<script src="https://cdn.tailwindcss.com">` + 内联 JS，禁外部依赖）。`<iframe sandbox="allow-scripts" srcDoc>` 预览（不给 `allow-same-origin`，保持隔离）。
- **迭代方式**：整文件重生成 + 版本化。聊天指令 → 载入最新版 HTML + 指令 → 生成完整新 HTML 存为 v+1。
- **归属**：**挂在 Project 下**。`prototype.project_id` 外键；产物落盘 `<repo_path>/.agent-collab/prototypes/<id>/v<n>/index.html`。
- **生成 UX**：**SSE 流式** —— 边吐 token 边显示代码，`done` 后自动渲染预览。
- **生成路径**：走**直连 Anthropic HTTP**（`llm_runner` 系列），**不走** conductor/CLI worktree 派发路径（原型生成只是单次「需求→HTML」往返，无需 worktree/merge/budget 重机器）。

## Requirements

### 后端

**DB schema**（`backend/app/adapters/async_sqlite_store.py`，沿用现有 `CREATE TABLE IF NOT EXISTS` + `schema_version` bump 模式，见 line 441/490/505）：
- `prototypes`: `id, project_id, title, framework('html'), current_version INT, created_at, updated_at`（FK project_id → projects.id）。
- `prototype_versions`: `id, prototype_id, version_no, instruction TEXT, html TEXT, disk_path TEXT, created_at`。
- store 方法（对齐现有命名）：`save_prototype` / `load_prototype` / `list_prototypes(project_id)` / `delete_prototype` / `save_prototype_version` / `list_prototype_versions(prototype_id)` / `load_prototype_version(prototype_id, version_no)`。HTML 直接进 DB（单文件够小），`disk_path` 仅记落盘位置。

**Domain models**（`backend/app/domain/models.py`，紧邻 `Project` line 94）：pydantic `Prototype` + `PrototypeVersion`。

**新服务**（`backend/app/application/prototype_service.py`）：
- 复用 `resolve_streaming_context(catalog)`（`llm_runner.py:292`）拿 endpoint/key/model。
- `_stream_html(prompt, ctx) -> AsyncIterator[str]`：**复制** `stream_llm`（`llm_runner.py:318`）的 SSE 解析循环（line 357-384），但**去掉硬编码的 assistant-prefill `{`**（该 prefill 强制 JSON，会破坏 HTML 输出）；prompt 末尾用 `<!DOCTYPE html>` 引导。
- `generate_stream(project_id, brief)`：构造单文件 HTML system prompt（完整 HTML 文档、Tailwind CDN、JS 内联、禁外部依赖）→ 流式 → 结束后裁 markdown code fence → `save_prototype_version` + bump `current_version` → 落盘（新 helper，镜像 `issue_artifact_documents.py` 的 `Path.mkdir(parents=True)` + write，路径 `<repo_path>/.agent-collab/prototypes/<id>/v<n>/index.html`）。
- `iterate_stream(prototype_id, instruction)`：载入最新版 HTML + 指令拼 prompt → 同上流程 → 写 v+1。
- 在 `bootstrap.py` 实例化 `prototype_service`（对齐 `project_service`），注入 `api.py` 模块级全局（同 `codex_store`/`project_service` 模式）。

**端点**（`backend/app/interfaces/api.py`，inline Pydantic 约定）：
- `POST /api/projects/{id}/prototypes` `{title, brief}` → 建 prototype 行（空版本），返回 `{id, brief}`。
- `GET /api/projects/{id}/prototypes` → 列表。
- `GET /api/prototypes/{pid}` → 详情 + 版本元数据（不含每版全文 html）。
- `GET /api/prototypes/{pid}/versions/{n}` → 该版完整 html。
- `GET /api/prototypes/{pid}/stream?instruction=` → **SSE 生成**：无 instruction 用存储的 brief 生成 v1，有则 iterate。`event: meta`(model 名) → 多个 `event: delta`(token) → `event: done`(`{version_no, html}`)。**镜像** `/codex/projects/{id}/conductor/stream`（`api.py:6513`）的 `StreamingResponse` + `text/event-stream` + headers 写法。
- `DELETE /api/prototypes/{pid}`。

### 前端

- **路由 + 导航**：新建 `frontend/src/app/projects/[id]/prototypes/page.tsx`（薄包装）；`frontend/src/features/projects/ProjectShell.tsx` 的 `navItems`（line 22）加第三项 `{ href: /projects/${projectId}/prototypes, label: t("project.nav.prototypes"), icon: <lucide Palette/Wand2> }`。
- **Feature**（`frontend/src/features/prototype/`）：
  - `ProjectPrototypesPage.tsx`：左侧原型列表（`listPrototypes` + 新建）+ 右侧画板。
  - `PrototypeCanvas.tsx`：需求/指令输入框 → 点生成走 **EventSource**（SSE GET 天然匹配 `/stream`）消费 `meta/delta/done`；`delta` 累积进代码视图，`done` 灌入预览；底部版本切换器（点旧版调 `getPrototypeVersion` 重渲染）。
  - `PreviewFrame.tsx`：**从零新建**（全仓无先例）。`<iframe sandbox="allow-scripts" srcDoc={html} className="h-full w-full" />`。
  - 复用 `src/components/ui/*`（button/card/textarea/tabs/loader/empty-state），样式走 `globals.css` 的 `@theme` token（`bg-surface-raised`/`text-brand`，禁硬编码 hex）。
- **API client + 类型**：`lib/api.ts` 加 `listPrototypes/createPrototype/getPrototype/getPrototypeVersion/deletePrototype` + `getPrototypeStreamUrl(pid, instruction?)`（沿用 `API_BASE`）；`lib/types.ts` 加 `Prototype` / `PrototypeVersion`。
- **i18n**（`lib/i18n.ts`）：zh-CN + en-US 两 locale 各补齐 `project.nav.prototypes` + `prototype.*`（标题/新建/需求占位/生成中/版本/空态/预览）。zh-CN 是 key 真相源。

## Acceptance Criteria

- [ ] `POST /api/projects/{id}/prototypes` 建行成功；`GET .../prototypes` 列出；`DELETE` 删除。
- [ ] `GET /api/prototypes/{pid}/stream`（无 instruction）按 brief 流式生成 v1：先 `meta`，多个 `delta`，末 `done` 带 `{version_no:1, html}`；HTML 经 code-fence 裁剪、以 `<!DOCTYPE html>` 开头。
- [ ] 带 `instruction` 再调 `/stream` 基于最新版迭代，产出 v2，`current_version` 递增。
- [ ] 每版 HTML 落盘 `<repo_path>/.agent-collab/prototypes/<id>/v<n>/index.html` 且 DB `disk_path` 记录正确。
- [ ] 前端 Project 页出现「原型设计」Tab；输入需求 → 代码区流式增长 → 生成完 iframe 沙箱自动渲染；迭代出 v2；版本切换器可回看 v1。
- [ ] 后端单测：`test_prototype_service.py`（monkeypatch `_stream_html` 吐假 HTML，断言版本化 + 落盘 + fence 裁剪）、`test_prototypes_api.py`（CRUD + SSE 端点）。磁盘/DB 重的标 `@pytest.mark.slow`。
- [ ] `cd backend && timeout 300 python3 -m pytest tests/test_prototype_service.py tests/test_prototypes_api.py -v` 全绿；`cd frontend && npx tsc --noEmit` 通过（**不跑** `npm run build`，dev 运行时会 clobber `.next`）。

## Definition of Done

- 后端/前端代码 + 单测新增并通过；typecheck 绿。
- CLAUDE.md「核心闭环」简述新特性（新增端点 + Project 页入口 + 落盘路径）。

## Out of scope

多文件 React 工程 / Vite 沙箱（数据模型已留 `framework` 字段供后续扩展）、原型导出到 git 分支、设计系统选择、多屏联动、协作共享。
