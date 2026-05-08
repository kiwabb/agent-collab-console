"""End-to-end manual workflow verification for architecture -> development transition."""
import urllib.request
import urllib.error
import json
import os
from pathlib import Path

BASE = "http://127.0.0.1:8000/api"

def log(msg):
    print(f"  {msg}")

def step(name):
    print(f"\n[STEP] {name}")

def post(url, data):
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())

def get(url):
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())

# 1. Create workspace
step("1. Create workspace")
status, ws = post(f"{BASE}/codex/workspaces", {"title": "e2e-test-ws", "cwd": ""})
assert status in (200, 201), f"workspace creation failed: {status} {ws}"
ws_id = ws["id"]
print(f"  workspace: {ws_id}")

# 2. Create issue in requirements phase
step("2. Create issue")
status, issue = post(f"{BASE}/codex/issues", {"session_id": ws_id, "title": "E2E 测试需求"})
assert status in (200, 201), f"issue creation failed: {status} {issue}"
issue_id = issue["id"]
print(f"  issue: {issue_id}, phase={issue['current_phase']}")

# 3. Create requirement artifacts manually
step("3. Create requirement artifacts")
cwd = ws.get("cwd") or os.getcwd()
issue_root = Path(cwd) / "issues" / issue_id
issue_root.mkdir(parents=True, exist_ok=True)
(issue_root / "requirement.md").write_text("# 需求\n- 功能 A\n- 功能 B", encoding="utf-8")
(issue_root / "prd.json").write_text(json.dumps({"requirements": ["功能A", "功能B"]}), encoding="utf-8")
(issue_root / "prd.md").write_text("# PRD\n## 功能A\n## 功能B", encoding="utf-8")
print(f"  artifacts at: {issue_root}")

# 4. Transition to architecture
step("4. Transition to architecture")
status, arch_result = post(f"{BASE}/codex/issues/{issue_id}/transition-to-architecture", {})
assert status == 200, f"arch transition failed: {status} {arch_result}"
print(f"  issue phase: {arch_result['issue']['current_phase']}")
arch_task = arch_result.get("task")
print(f"  architect task: {arch_task['id'] if arch_task else 'none'}")

# 5. Create architect artifacts
step("5. Create architect artifacts")
(issue_root / "system_design.json").write_text(json.dumps({"design": "模块化设计"}), encoding="utf-8")
(issue_root / "implementation_plan.json").write_text(json.dumps([
    {"title": "实现功能A", "description": "实现功能A模块", "priority": "P1"},
    {"title": "实现功能B", "description": "实现功能B模块", "priority": "P2"},
    {"title": "实现功能C", "description": "实现功能C模块", "priority": "P1"},
]), encoding="utf-8")
print(f"  3 implementation items created")

# 6. Transition to development
step("6. Transition to development")
status, dev_result = post(f"{BASE}/codex/issues/{issue_id}/transition-to-development", {})
assert status == 200, f"dev transition failed: {status} {dev_result}"
print(f"  issue phase: {dev_result['issue']['current_phase']}")
print(f"  created: {dev_result['created']}, tasks: {len(dev_result['tasks'])}")

# 7. Verify phase == development
step("7. Verify: phase == development")
assert dev_result["issue"]["current_phase"] == "development", f"Expected 'development', got {dev_result['issue']['current_phase']}"
log("PASS")

# 8. Verify one task per item
step("8. Verify: 3 engineer tasks, all pending")
assert len(dev_result["tasks"]) == 3, f"Expected 3 tasks, got {len(dev_result['tasks'])}"
for t in dev_result["tasks"]:
    assert t["role"] == "engineer", f"Expected 'engineer', got {t['role']}"
    assert t["phase"] == "development", f"Expected 'development', got {t['phase']}"
    assert t["status"] == "pending", f"Expected 'pending', got {t['status']}"
    print(f"  - {t['title']} (pending)")
log("PASS")

# 9. Verify no auto-run
step("9. Verify: no engineer task auto-runs")
for t in dev_result["tasks"]:
    assert t["status"] == "pending", f"Task {t['id']} status={t['status']} (auto-ran!)"
log("PASS")

# 10. Verify: endpoint correctly rejects retry when issue is in development phase (409)
step("10. Verify: retry returns 409 for development-phase issue (plan step 7 verification)")
status, retry = post(f"{BASE}/codex/issues/{issue_id}/transition-to-development", {})
assert status == 409, f"Expected 409, got {status} {retry}"
log("PASS: correctly rejects retry for non-architecture issue")

print("\n" + "="*50)
print("ALL MANUAL WORKFLOW CHECKS PASSED")
print("="*50)

# cleanup workspace
print(f"\n[Cleanup] workspace {ws_id}")
urllib.request.urlopen(urllib.request.Request(f"{BASE}/codex/workspaces/{ws_id}", method="DELETE"))