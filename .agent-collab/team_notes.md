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

<!-- issue:12b81f91-7465-421a-9816-db7c7683b6e7 -->
## 2026-05-24 12:52 — Add GET /api/health endpoint
_intent: feature · graph status: done_

**Product goals:**
- 提供简单可控的健康检查端点，无需数据库即可验证系统连通性
- 遵循现有 /api/ping 和 /api/echo 端点的实现模式
- 通过测试覆盖确保端点健壮性

**Files touched:**
- `backend/app/interfaces/api.py`

**QA verdict:** `failed`
**Verification commands worth keeping:**
- `cd backend && python3 -m pytest tests/test_health_endpoint.py -v`
**Actually run by QA:**
- `cd backend && python3 -m pytest tests/test_health_endpoint.py -v → exit 4`
**Bugs / lessons:**
- 测试文件 tests/test_health_endpoint.py 不存在，无法运行测试验证
- 后端服务因缺少 python-multipart 依赖无法启动，无法通过实际请求验证端点
- 旧服务仍在运行返回旧响应格式 {"service":"agent-collab-console","version":"1.0"}，与新代码不一致

<!-- issue:ab143b62-2f4b-459b-a9a0-d766a4eb61bb -->
## 2026-05-24 14:06 — 添加 GET /api/codex/walkthrough 健康检查端点
_intent: feature · graph status: done_

**Product goals:**
- 提供 /api/codex/walkthrough 健康检查端点，返回 {"status": "ok"}
- 遵循现有 /api/health 端点的实现模式
- 通过 pytest 测试覆盖确保端点健壮性

**Files touched:**
- `backend/app/interfaces/api.py`

**QA verdict:** `failed`
**Verification commands worth keeping:**
- `cd backend && pip3 install python-multipart && python3 -m pytest tests/test_walkthrough_endpoint.py -v`
**Actually run by QA:**
- `cd backend && pip3 install python-multipart && python3 -m pytest tests/test_walkthrough_endpoint.py -v → exit 1`
**Bugs / lessons:**
- Python 3.14 环境的 pyexpat 模块与系统 expat 库版本冲突，导致无法安装 python-multipart 依赖，FastAPI 无法加载应用，测试无法运行。这是本地环境配置问题，非代码问题。


<!-- issue:d0594c95-e92e-47bf-8eff-b9e549c1c690 -->
## 2026-05-25 11:24 — 添加 GET /api/codex/heartbeat 端点
_intent: feature · graph status: done_

**Files touched:**
- `backend/app/interfaces/api.py`
- `backend/tests/test_codex_heartbeat_endpoint.py`

**QA verdict:** `passed`
**Verification commands worth keeping:**
- `cd backend && python3 -m pytest tests/test_codex_heartbeat_endpoint.py -v`
**Actually run by QA:**
- `cd backend && python3 -m pytest tests/test_codex_heartbeat_endpoint.py -v → exit 0`


<!-- issue:9e554e37-8a46-4d0f-8ee4-5a86fb29d8ac -->
## 2026-05-25 13:26 — 添加 GET /api/codex/ping 端点返回 {"pong": true}
_intent: feature · graph status: done_

**Product goals:**
- 提供一个简单、稳定的 Codex 服务连通性检查端点。
- 让开发、QA 或自动化流程可以快速确认后端 API 是否可访问。
- 延续项目中 /api/ping、/api/echo、/api/codex/heartbeat 等轻量端点的实现和测试模式。


<!-- issue:e2e18657-e9d4-499e-a740-eb5db21c8ee1 -->
## 2026-05-25 14:54 — 添加 GET /api/codex/version 端点返回 {"version": "1.0"}
_intent: feature · graph status: done_

**Files touched:**
- `backend/app/interfaces/api.py`
- `backend/tests/test_codex_version_endpoint.py`

**QA verdict:** `passed`
**Verification commands worth keeping:**
- `cd backend && python3 -m pytest tests/test_codex_version_endpoint.py -v`
**Actually run by QA:**
- `cd backend && python3 -m pytest tests/test_codex_version_endpoint.py -v → exit 0`


<!-- issue:bf7ff908-c9eb-4e45-a587-6987a66a2901 -->
## 2026-05-25 15:50 — 添加 GET /api/codex/status 端点返回 {"ok": true}
_intent: feature · graph status: done_

**Files touched:**
- `backend/app/interfaces/api.py`
- `backend/tests/test_codex_status_endpoint.py`

**QA verdict:** `passed`
**Verification commands worth keeping:**
- `cd backend && python3 -m pytest tests/test_codex_status_endpoint.py -v`
**Actually run by QA:**
- `cd backend && python3 -m pytest tests/test_codex_status_endpoint.py -v → exit 0`
