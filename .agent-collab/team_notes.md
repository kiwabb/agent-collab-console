## ⚙️ Distilled lessons (auto-curated)
- Co-locate a corresponding test file in `backend/tests/` for every new endpoint, using the naming pattern `test_<endpoint_name>.py`.
- Verify all backend changes with `cd backend && python3 -m pytest tests/<test_name>.py -v` before considering work complete.
- Keep feature changes small and focused; spreading a single feature across many files across both frontend and backend often signals over-scoping.
- Place all new backend API endpoints in the same location (`backend/app/interfaces/api.py`) to maintain consistency.
- Extend existing models as additive attributes only; do not modify core CRUD logic to accommodate new fields.

<!-- issue:85e2b8d2-c126-42bd-a49b-34002aa1b7ab -->
## 2026-05-17 22:27 — 给 Issue 添加 priority 字段，支持在创建时选择，在列表和详情页展示彩色徽章。
_intent: feature · graph status: failed_

**Product goals:**
- 为 Issue 提供明确的优先级标识，帮助团队快速识别和处理重要问题
- 通过彩色徽章在列表和详情页直观展示优先级，无需额外过滤或排序操作
- 保持现有 CRUD 操作简洁，priority 字段仅作为附加属性展示和切换

**Files touched:**
- `frontend/src/features/issues/IssueDetailPage.tsx`
- `frontend/src/features/workbench/workbenchActions.ts`
- `frontend/src/features/workspaces/NewIssueDialog.tsx`
- `frontend/src/lib/api.ts`
- `frontend/src/lib/types.ts`

<!-- issue:1afd5856-134b-4143-892b-1c2a5a2d3d24 -->
## 2026-05-18 15:33 — 添加 GET /api/ping 端点
_intent: feature · graph status: done_

**QA verdict:** `passed`
**Verification commands worth keeping:**
- `cd backend && python3 -m pytest tests/test_ping_endpoint.py -v`
**Actually run by QA:**
- `cd backend && python3 -m pytest tests/test_ping_endpoint.py -v → exit 0`


<!-- issue:44716d9e-8ff4-44d2-b093-8556e241e1d8 -->
## 2026-05-18 19:41 — 添加 GET /api/echo 端点
_intent: feature · graph status: done_

**Product goals:**
- 提供简单可控的调试/测试用 HTTP 端点，无需数据库即可验证系统连通性
- 通过三种输入边界情况（正常/空/超长）的测试覆盖确保端点健壮性
- 保持端点实现简洁，专注于单一职责，便于后续扩展或替换

**Files touched:**
- `backend/app/interfaces/api.py`
- `backend/tests/test_echo_endpoint.py`

**QA verdict:** `passed`
**Verification commands worth keeping:**
- `cd backend && python3 -m pytest tests/test_echo_endpoint.py -v`
**Actually run by QA:**
- `cd backend && python3 -m pytest tests/test_echo_endpoint.py -v → exit 0`


<!-- issue:b07e51c7-89bf-4a29-bb51-110417cca063 -->
## 2026-05-18 20:36 — 给 Approvals 页面加 "QA 已通过待人工确认" 分组
_intent: feature · graph status: failed_

**QA verdict:** `failed`
**Verification commands worth keeping:**
- `cd frontend && npm install && npm test -- --run tests/approvalsQaPassed.test.ts -v`
**Actually run by QA:**
- `cd frontend && npm install && npm test -- --run tests/approvalsQaPassed.test.ts -v → exit 1`


<!-- issue:de6e8747-f7f9-48fb-b015-29ecb33dfd86 -->
## 2026-05-18 21:29 — 给 Approvals 页面加 "QA 已通过待人工确认" 分组
_intent: feature · graph status: done_

**Product goals:**
- 在 Approvals 页面新增 QA 已通过 分组,帮助人工确认流程更清晰
- 通过彩色徽章和状态标识,直观展示等待人工确认的 issue
- 保持与现有 tabs (All/Issues/Task reviews/Agent questions/Tool calls) 视觉一致性

- [Conductor] If backend fails, verify frontend is not hardcoding API contracts from failed implementation. Consider sequential dependency for backend->frontend on API-heavy features.
