# 修 createWorkspace 422 错误展示和前端校验

## Goal

修两个相关 bug：(1) 后端 422 校验错误在前端被渲染成 `[object Object]`，丢失真实信息；(2) NewWorkspaceDialog 没有 client-side 校验前后端契约里的 `title min_length=3`，让用户能提交注定失败的请求。

## Root Cause

- `backend/app/interfaces/api.py:2071`：`title: str = Field(min_length=3)`
- `frontend/src/lib/api.ts:82`：`errorMessage = (err as { detail?: string }).detail || errorMessage`
  - 假设 `detail` 是 string，但 FastAPI 422 的 `detail` 是 **array of validation errors**：
    ```json
    {"detail": [{"type":"string_too_short","loc":["body","title"],"msg":"String should have at least 3 characters",...}]}
    ```
  - array truthy → 进入 `.detail || ...` → `throw new Error(array)` → toString → `[object Object]`
- `frontend/src/features/projects/ProjectWorkspacesPage.tsx:455`：`canSubmit = titleDraft.trim().length > 0`（与后端 min 3 不一致）

## Requirements (MVP)

- [x] `handleResponse` 处理 `detail` 数组：detect `Array.isArray(detail)` → 把每条 `{loc, msg}` 拼成可读 `body.title: String should have at least 3 characters`，多条用 `; ` 连
- [x] `handleResponse` 保留 `typeof detail === 'string'` 分支（向后兼容业务异常的 `HTTPException(detail="...")`）
- [x] NewWorkspaceDialog 把 `canSubmit` 改成 `titleDraft.trim().length >= 3 && !saving`
- [x] NewWorkspaceDialog 在 title 字段下方加 helper text：`workspace.field.titleMinLengthHint` = "至少 3 个字符"，仅在 `titleDraft.trim().length > 0 && titleDraft.trim().length < 3` 时显示（避免初次进对话框就报错）
- [x] 新增 i18n key `workspace.field.titleMinLengthHint`
- [x] 加 1 个 unit test 覆盖 `handleResponse` 对 422 array detail 的解析
- [x] 加 1 个 unit test 覆盖 NewWorkspaceDialog 的 min length 3 disabled 行为

## Out of Scope

- 不动后端 schema（min_length=3 是合理约束，保留）
- 不重写整个错误 toast 系统
- 不动其他 dialog 的校验（ProjectDashboard 也调 createWorkspace 但没经过 dialog，不在本任务范围）

## Acceptance Criteria

- [x] 用户输 1-2 个字符的 title 时，submit 按钮 disabled + 显示 "至少 3 个字符" 提示
- [x] 万一别的接口绕过 dialog 触发 422，错误 toast 显示可读消息（如 `body.title: String should have at least 3 characters`），不再是 `[object Object]`
- [x] frontend `npm run build && npm run lint && npm test` 全绿

## Definition of Done

- 旧的 `(err as { detail?: string }).detail || errorMessage` 行被替换，不留 `// removed` 注释
- 测试 + lint + build 全绿
- i18n key 新增，不重命名旧的

## Technical Notes

- 主要文件：
  - `frontend/src/lib/api.ts:77-99`（handleResponse）
  - `frontend/src/features/projects/ProjectWorkspacesPage.tsx:441,455`（dialog）
  - `frontend/src/lib/i18n.ts`（i18n key）
- 测试：可以新建 `frontend/tests/apiErrorParsing.test.ts` 单测 handleResponse；NewWorkspaceDialog 测试可以加到现有 workspace 相关 test 文件
- FastAPI 422 detail 结构参考：`{type, loc, msg, input?, ctx?}`，loc 是 array（如 `["body", "title"]`）

## Decision (ADR-lite)

**Context**: 前端 `handleResponse` 把 FastAPI 校验错误的 `detail` array 当作 string 处理 + dialog 校验跟后端 schema 不一致 → 用户体验崩溃（[object Object] + 无前置提示）。

**Decision**: 双管齐下，前端 dialog 加 client-side 校验前置拦截（理想路径不出错），同时 handleResponse 鲁棒地展示 422（保底路径出错时人类可读）。**不动后端**：min_length=3 是合理约束，前端契约应该同步。

**Consequences**:
- ✅ 用户输短 title 立刻看到提示，不会触发后端 422
- ✅ 任何 422（不止 title）都能可读地显示
- ✅ 后端约束权威，前端跟随
- ⚠️ helper text + canSubmit 跟后端 min_length 是隐式契约，将来后端改了前端要跟改 → 接受（typing 全自动同步成本太高，且这种约束改动频率低）

## Implementation Plan

- **PR1（本任务一次性完成）**:
  - 改 `handleResponse` 处理 array detail（保留 string 分支）
  - 改 `ProjectWorkspacesPage.tsx` `canSubmit` + 加 helper text + 新增 i18n key
  - 新增 2 个测试（handleResponse + dialog）
  - frontend build + lint + test 全绿
