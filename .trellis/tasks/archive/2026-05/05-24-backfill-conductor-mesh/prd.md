# backfill conductor dispatch into mesh

## Goal

Issue 详情页的 **Mesh 折叠面板**（`MeshPanel` → `CollabFeedTab` → `getAgentMessages`）实测整张 `agent_messages` 表 0 行 —— 因为 Conductor-as-Orchestrator 新架构下，主线 dispatch 不写 mesh，只有 3 个 escape-hatch（`peer_critique` / `specialist_request` / specialist 完工）会写，而这些路径在常规 PM→Architect→Engineer→QA 流程里基本没人触发。结果就是 Mesh 永远是 dead panel。

这次修复：**回灌 Conductor dispatch** —— 每次 `task_dispatcher.dispatch_role` 创建 task 时，顺手写一条 `handoff` 类型的 `AgentMessage`，让 Mesh 显示真实的 dispatch 链时间流（`conductor→pm`、`pm→architect`、`architect→engineer`、`engineer→qa`、`conductor→specialist:xxx` 等）。

## What I already know

### 现状

- `task_dispatcher.dispatch_role`（`backend/app/application/task_dispatcher.py:26-165`）—— Conductor `dispatch_subagent` 工具最终的统一收口；spawn_custom_subagent (specialist) 也走它
- 已有 `prev_node_key` 入参（line 34）—— 这就是天然的 "from"
- 已有 `event_bus.append("task_created" / "workflow_node_updated")`（line 142-152）—— 在它们旁边加 `agent_message_posted` 是 1:1 镜像
- DB 表 `agent_messages` 已建（`async_sqlite_store.py:665` schema、`save_agent_message` 在 line 2232）
- 前端 `CollabFeedTab` 已经监听 `agent_message_posted` 事件实时刷新（`tabs/CollabFeedTab.tsx:102-110`）—— **前端零改动**
- `AgentMessage.message_type` 枚举（domain model）已含 `handoff`；前端 `TYPE_CONFIG.handoff`（CollabFeedTab.tsx:39-44）有 UI

### 现有 mesh 写入路径（保留不动）

| 触发 | 路径 | message_type |
|---|---|---|
| Engineer/QA 输出 peer_critique | `role_workflow_service._record_critique` | `critique` |
| Engineer/QA 输出 specialist_request | `role_workflow_service._request_specialist` | `specialist_call` |
| Specialist 子任务完工 | `workflow_scheduler._maybe_resume_from_specialist` | `specialist_result` |

新增路径只追加，不和现有路径冲突。

## Requirements

### A. `task_dispatcher.dispatch_role` 写 mesh 消息

在 line 137（`add_workflow_edge` 之后、`event_bus.append("task_created")` 之前）加：

```python
# Backfill Mesh: record a handoff message so the UI shows the real dispatch chain.
from_key = prev_node_key or "conductor"
mesh_msg = AgentMessage(
    id=str(uuid4()),
    issue_id=issue.id,
    graph_id=graph.id,
    from_node_key=from_key,
    to_node_key=node_key,
    message_type="handoff",
    body=_summarize_dispatch_body(role, effective_prompt),
    created_at=now,
)
try:
    await store.save_agent_message(mesh_msg)
except Exception as exc:
    logger.warning("dispatch_role mesh write failed: %s", exc)
```

并在 event 段（line 144 附近）加：

```python
await event_bus.append({
    "type": "agent_message_posted",
    "issue_id": issue.id,
    "session_id": issue.session_id,
    "message": {
        "id": mesh_msg.id,
        "issue_id": mesh_msg.issue_id,
        "graph_id": mesh_msg.graph_id,
        "from_node_key": mesh_msg.from_node_key,
        "to_node_key": mesh_msg.to_node_key,
        "message_type": mesh_msg.message_type,
        "body": mesh_msg.body,
        "created_at": mesh_msg.created_at.isoformat() if mesh_msg.created_at else None,
    },
})
```

### B. body 摘要 helper

`_summarize_dispatch_body(role, prompt) -> str`：
- 如果 prompt 是 issue 标题/描述 fallback → 返回 `"Dispatch {role}"`
- 否则取 prompt 前 200 字符，超长加 `…`
- 用途：让 Mesh 行显示"做什么"而不是只显示"派给谁"

### C. 幂等性

- `dispatch_role` 已经处理"已有完工 node → 直接返回 task_id"分支（line 65-67）—— 这条不写 mesh（保持幂等，避免重复消息）
- 仅在真正新建 task 的路径写 mesh

### D. 失败模式

- `save_agent_message` 失败不能阻塞 dispatch —— wrap try/except + log.warning，跟现有 _record_critique 同一风格
- event_bus.append 已在外层 try 内（line 141-154），保持现状

### E. 后端测试

`backend/tests/test_task_dispatcher_mesh.py`：
- 新建 fake store 调 `dispatch_role(prev_node_key=None, role="pm", ...)` → 断言写了一条 `from=conductor to=pm type=handoff` 消息
- 调 `dispatch_role(prev_node_key="pm", role="architect", ...)` → 断言 `from=pm to=architect type=handoff`
- 调 `dispatch_role` 命中"已存在 node"分支 → 断言**不**写 mesh
- 断言 event_bus 收到 `agent_message_posted` 事件

## Acceptance Criteria

- [ ] 后端新增 mesh 写入 + event 发射，4 个测试全绿
- [ ] 跑全量 `cd backend && python3 -m pytest -v` 不破坏现有测试
- [ ] 手动起一个新 issue → 看到 Mesh 面板逐步出现 `conductor→pm`、`pm→architect`、`architect→engineer`、`engineer→qa` 等 handoff 卡片
- [ ] specialist 调用仍正常显示 `specialist_call` + `specialist_result`（不破坏现有路径）
- [ ] 前端不需要任何改动（event 已订阅、UI 已经有 handoff 配色）
- [ ] `task_dispatcher.dispatch_role` 仍幂等 —— 老 issue 重启 Conductor 不会重复灌消息

## Definition of Done

- 后端 lint / pytest 全绿（含新测试 + 全量回归）
- 不动 `role_workflow_service` / `specialist_orchestrator` / `workflow_scheduler` 三条原有 mesh 路径
- 前端零改动验证：grep `agent_message_posted` 前端订阅未变
- 文档：本文档 + 跑通后简短更新 `CLAUDE.md` Mesh 一段

## Out of Scope

- 不改 mesh 表 schema
- 不改前端 `MeshPanel` / `CollabFeedTab` UI（已经有 handoff 配色）
- 不补 `tool_use` / `clarification` 等其他 Conductor 工具调用进 mesh —— 那些有专门的 Decision Timeline / Approvals 入口
- 不引入新的 message_type 枚举值（用现有 `handoff`）

## Technical Approach

**One file, one helper, ~30 lines diff.**

修改：
- `backend/app/application/task_dispatcher.py` —— 加 `_summarize_dispatch_body` helper + 在 dispatch_role 内写 mesh 消息 + emit event

新增：
- `backend/tests/test_task_dispatcher_mesh.py` —— 4 个用例

## Decision (ADR-lite)

**Context**：Mesh 面板 0 数据 = dead panel；Conductor 新架构下 dispatch 不再过 scheduler 的旧 mesh 写入路径。

**Decision**：让 `task_dispatcher.dispatch_role`（Conductor dispatch 的统一收口）顺带写 mesh handoff 消息。复用现有 schema / event / UI，零前端改动。

**Consequences**：
- + Mesh 立即有内容，跟 Decision Timeline 互补（Timeline 看节点状态、Mesh 看消息流）
- + 单文件改动，回滚成本低
- − Mesh 和 Timeline 信息有重叠（都看得到角色顺序）—— 但呈现视角不同，用户接受度待手测验证
- − 每次 dispatch 多一次 DB 写 + event —— 量级可忽略（一个 issue 才几次 dispatch）

## Implementation Plan

1. 加 `_summarize_dispatch_body` helper
2. 在 `dispatch_role` 真新建 task 分支里写 mesh 消息 + emit event（不在"已存在完工 node"分支里写）
3. 新增 `test_task_dispatcher_mesh.py` 4 用例
4. 全量 pytest 回归
5. 手测：新建 issue → 验 Mesh 出现 handoff 卡片

## Technical Notes

- 已存在的 3 条 mesh 写入路径不要碰
- `prev_node_key` 在 conductor_tools 里怎么传？看 `conductor_tools.dispatch_subagent` 调用 `dispatch_role(prev_node_key=...)` 的语义 —— 若 prev 为 None 表示第一棒，from_key 走 "conductor"
- Body 200 字符截断够用；不需要做 markdown 渲染
