<!-- issue:78729118-15cb-4f66-8bfe-3ac6ef4c4585 -->
## 2026-05-16 13:40 — P0 real-CLI: add /api/ping endpoint
_intent: feature · graph status: done_

**Files touched:**
- `backend/app/interfaces/api.py`
- `backend/tests/test_ping_endpoint.py`

**QA verdict:** `passed`
**Verification commands worth keeping:**
- `cd backend && python3 -m pytest tests/test_ping_endpoint.py -v`
**Actually run by QA:**
- `cd backend && python3 -m pytest tests/test_ping_endpoint.py -v → exit 0`


<!-- issue:4034678b-0479-49fd-8ee8-bf5c645f5b5a -->
## 2026-05-16 21:05 — Browser smoke walkthrough: add a tiny /api/browser-smoke end
_intent: feature · graph status: done_

**Product goals:**
- Provide a minimal health-check endpoint for browser smoke testing the application

**Files touched:**
- `backend/app/interfaces/api.py`

**QA verdict:** `passed`
**Verification commands worth keeping:**
- `cd backend && python3 -m pytest tests/test_browser_smoke_endpoint.py -v`
**Actually run by QA:**
- `cd backend && python3 -m pytest tests/test_browser_smoke_endpoint.py -v → exit 0`


<!-- issue:f0b1d10d-d85b-4eb9-9476-73e55221f7b3 -->
## 2026-05-17 16:57 — 加 /api/codex/version 端点
_intent: feature · graph status: done_

**Product goals:**
- 提供 Codex 服务本身的版本信息端点，供前端和管理界面查询服务状态
- 记录服务启动时间，方便排查服务运行周期相关问题

**Files touched:**
- `backend/app/interfaces/api.py`
- `backend/app/main.py`
- `backend/tests/test_codex_version_endpoint.py`

**QA verdict:** `passed`
**Verification commands worth keeping:**
- `cd backend && python3 -m pytest tests/test_codex_version_endpoint.py -v`
**Actually run by QA:**
- `cd backend && python3 -m pytest tests/test_codex_version_endpoint.py -v → exit 0`
