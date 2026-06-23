# 项目级一键批量重生成所有原型

## Goal

在原型设计工具上加一个**项目级批量操作**：一键对项目下**所有现有原型**各跑一次 LLM 生成，基于各自**原始 brief** 产出新版本。适合改了设计语言、清了磁盘、或想整体刷新一版时批量重做，不必逐个点。

## Scope（已与用户确认）

- **生成源**：每个原型用其 **v0 seed 的原始 brief** 重新生成（与初次生成同路径 = `stream_events(pid, instruction=None)`），产出新版本 v+1。**不**走迭代路径、不受中途迭代漂移影响。
- **调度**：**串行**（逐个原型顺序生成），**单条 SSE 流**报进度。复用现有 stream 模式，最简、可观察。
- **失败处理**：**跳过继续** —— 单个原型生成失败不中断整批，记录失败项，末尾汇总 `{ok:[...], failed:[{id,message}]}`。
- **归属**：项目级（对 `GET .../projects/{id}/prototypes` 列出的全部原型操作）。

## Requirements

### 后端

**服务**（`backend/app/application/prototype_service.py`，`PrototypeService` 新增方法）：
- `async def regenerate_all_stream(self, project_id) -> AsyncIterator[StreamEvent]`：
  - `load_project` 校验，不存在 → `PrototypeError`。
  - `prototypes = await self.list_for_project(project_id)`；先 yield `StreamEvent("batch_meta", {"count": len(prototypes)})`。
  - 空项目 → 直接 yield `StreamEvent("all_done", {"ok": [], "failed": []})` 返回。
  - 逐个原型：
    - yield `StreamEvent("prototype_start", {"prototype_id": p.id, "title": p.title})`。
    - **复用** `self.stream_events(p.id, instruction=None)`（None → 按 seed brief 生成新版）；`async for ev in ...` 转发内层事件：内层 `delta` → 重发为 `prototype_delta {prototype_id, chunk}`；内层 `done` → 记入 `ok`、重发 `prototype_done {prototype_id, version_no}`；内层 `error` → 记入 `failed`、重发 `prototype_error {prototype_id, message}` 后 **continue 下一个**（不抛）。
    - 内层若抛异常（非 error 事件）也捕获记 failed 并继续。
  - 末尾 yield `StreamEvent("all_done", {"ok": [...prototype_id], "failed": [{"prototype_id","message"}]})`。
  - 设计要点：批量逻辑放 service 层（可测）；事件命名空间化（带 `prototype_id`）让前端按原型分组显示。

**端点**（`backend/app/interfaces/api.py`，紧邻现有 prototype 端点 `~966-1023`，复用 `_require_prototype_service()` + `StreamingResponse`/`text/event-stream` 镜像现有 `/prototypes/{pid}/stream`）：
- `GET /api/projects/{id}/prototypes/regenerate-all/stream` → SSE：`event: batch_meta` → 多组 `prototype_start`/`prototype_delta`/`prototype_done`|`prototype_error` → `event: all_done`。
  - 项目不存在 → 404；无原型 → 正常返回 `batch_meta{count:0}` + `all_done`。

### 前端

- `frontend/src/features/prototype/ProjectPrototypesPage.tsx`：列表区工具栏加「重新生成全部」按钮（有原型才启用；点按弹 `ConfirmDialog` 确认，因为会覆写各原型新版本）。
- 进度 UI：点确认后开 `EventSource` 连批量 stream（复用 `PrototypeCanvas` 的 EventSource 消费 + `done/error` 后 `close()` 防重连模式）。展示 per-prototype 状态行（`prototype_start`→生成中、`prototype_done`→✓vN、`prototype_error`→✗ + 原因）；`all_done` → toast 汇总「成功 N / 失败 M」并刷新列表。
- `frontend/src/lib/api.ts`：加 `getRegenerateAllStreamUrl(projectId)`（拼 SSE URL，沿用 `API_BASE`）。类型按需加到 `types.ts`。
- i18n（`frontend/src/lib/i18n.ts`，zh-CN + en-US 双写）：`prototype.regenerateAll.*`（按钮、确认标题/正文、生成中、完成汇总、失败原因前缀、空态禁用提示）。

### 测试

- `backend/tests/test_prototype_service.py`：新增 `regenerate_all_stream` 用例（monkeypatch `_stream_html`）：
  - 多原型全成功 → 各出 v+1、`all_done.ok` 全含、`failed` 空。
  - 其中一个原型生成抛错 → 该项进 `failed`、其余照常成功、批不中断。
  - 空项目 → `batch_meta{count:0}` + 空 `all_done`。
- `backend/tests/test_prototypes_api.py`：批量 stream 端点 happy path + 404（项目不存在）。

## Acceptance Criteria

- [ ] `GET /api/projects/{id}/prototypes/regenerate-all/stream` 串行重生成全部原型，事件序列 `batch_meta → (prototype_start, prototype_delta*, prototype_done|prototype_error)* → all_done` 正确。
- [ ] 每个原型基于其**原始 brief**（v0 seed）生成，`current_version` 各 +1，新版 HTML 落盘 `<repo>/.agent-collab/prototypes/<id>/v<n>/index.html`。
- [ ] 单原型失败被记入 `all_done.failed[{prototype_id,message}]` 且**不中断**其余；全成功时 `failed` 为空。
- [ ] 空项目返回 `batch_meta{count:0}` + 空 `all_done`，不报错。
- [ ] 前端「重新生成全部」按钮 + 确认弹窗 + per-prototype 进度行 + 完成 toast 汇总；无原型时按钮禁用。
- [ ] 后端新测试通过：`cd backend && .venv/bin/python -m pytest tests/test_prototype_service.py tests/test_prototypes_api.py -v`（REAL_CLI=false mock）；前端 `npx tsc --noEmit` 干净（**不跑** `npm run build`）。

## Definition of Done

- 后端 service+端点+测试、前端按钮+进度 UI+i18n 完成并通过；typecheck 绿。
- CLAUDE.md「核心闭环」原型条目补一句批量重生成端点。

## Out of scope

并发批量（仅串行）、后台任务+轮询（仅 SSE）、跨重启恢复、选择性子集重生成（只全量）、基于最新版的刷新（仅原始 brief）、批量导出到磁盘/gallery 聚合页（另需求）。
