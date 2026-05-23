# Research 03: 从 task_id 拿 execution_process_id 的最便宜路径

- **Query**: DispatchDrawer 拿到 `DecisionTimelineItem.task_id` 后，怎么找最近的 execution_process_id
- **Scope**: internal
- **Date**: 2026-05-23

## 关键结论

**`task.last_execution_process_id` 字段已经存在。** 不需要新加 API、不需要发请求列 execution_processes。

`DecisionTimelineItem.task` 已经是一个完整的 `CodexTask` 对象（`DecisionTimelineItem.task: CodexTask | null`），直接读 `item.task?.last_execution_process_id ?? null` 即可。

---

## 证据 1：CodexTask 类型有 `last_execution_process_id` 字段

文件：`frontend/src/lib/types.ts:162-193`，关键字段：

```ts
export interface CodexTask {
  id: string;
  // ...
  resume_session_id: string | null;
  resume_message_id: string | null;
  last_execution_process_id: string | null;  // ← :187
  sequence_index?: number | null;
  // ...
}
```

字段类型 `string | null`。任务从未跑过为 `null`；跑过 1 次以上为最近那次 ExecutionProcess.id。

## 证据 2：后端 list_codex_tasks 返回该字段

文件：`backend/app/adapters/async_sqlite_store.py:1260-1280`

```python
select_sql = (
    "SELECT id, session_id, project_id, issue_id, phase, title, prompt, role, executor, status, result, result_json, "
    "parent_task_id, task_kind, blocked_by_help_id, workspace_path, "
    "git_branch, git_base_branch, git_worktree_path, git_merge_status, git_last_commit_sha, "
    "resume_session_id, resume_message_id, last_execution_process_id, "  # ← included
    "sequence_index, sequence_group, review_comment, created_at, updated_at FROM codex_tasks"
)
```

`GET /api/codex/tasks?issue_id=...` 直接走这个 SQL，每条 task dict 都含 `last_execution_process_id`（`backend/app/interfaces/api.py:3776-3781`）。

## 证据 3：codex_task_runner 写入该字段

文件：`backend/app/application/codex_task_runner.py:52`

```python
task.last_execution_process_id = process.id
```

每次 `runCodexTask` 创建 ExecutionProcess 后立即更新，所以这个字段总是指向最新 run。

## 证据 4：DecisionTimelineItem.task 已经携带 CodexTask 完整对象

文件：`frontend/src/features/issues/hooks/useDecisionTimeline.ts:13-29`

```ts
export interface DecisionTimelineItem {
  id: string;
  // ...
  taskId?: string | null;
  task?: CodexTask | null;   // ← 完整 task 对象
  result?: SubAgentResultPayload | null;
  // ...
}
```

赋值位置：`useDecisionTimeline.ts:149`：

```ts
const task = taskId ? taskById.get(taskId) ?? null
  : tasks.find((candidate) => candidate.role === role) ?? null;
// ...
items.push({ /* ... */ task, /* ... */ });  // :185
```

`tasks` 列表来自 `IssueDetailPage` 的 `useState<CodexTask[]>`（`IssueDetailPage.tsx:43, 59`），通过 `getCodexTasks(null, issueId)` 拉取——也就是后端返回的全字段对象。

## 证据 5：现有引用先例

`frontend/src/features/runs/RunDetail.tsx:547` —— 直接传 `process?.id`（同样的语义，只不过那边的 process 是 props 传进来的）。

`backend/app/application/codex_app_server_runtime.py:311, 452`：

```python
execution_process_id = task.last_execution_process_id if task else None
```

后端自己也在用这个字段当"最近一次 run"语义。

---

## 推荐方案（给 DispatchDrawer 改造用）

### 方案 A（推荐）：直接读 props 上的 task

DispatchDrawer 当前 props（`DispatchDrawer.tsx:12-15`）：
```ts
interface Props {
  item: DecisionTimelineItem | null;
  onClose: () => void;
}
```

`item.task?.last_execution_process_id ?? null` 就是要喂给 `AgentLiveTimeline` 的值。**零额外请求、零新 API、零状态同步**。

伪代码示例：
```tsx
const executionProcessId = item.task?.last_execution_process_id ?? null;

<AgentLiveTimeline
  executionProcessId={executionProcessId}
  taskStartedAt={item.task?.created_at ?? null}
  taskStatus={item.task?.status ?? null}
  reviewComment={item.task?.review_comment ?? null}
  taskResult={item.task?.result ?? null}
  taskRole={item.task?.role ?? null}
  onStop={item.taskId ? () => terminateCodexTask(item.taskId!) : undefined}
  className="flex-1 min-h-0"
  emptyHint="This dispatch hasn't started running yet."
/>
```

### 是否需要新增 API endpoint？

**不需要。**

### 边界情况

1. **`item.task` 为 null**（DecisionTimelineItem 是 clarification / memory / finalize / user / error 等非 dispatch 项时）：传 null 给 AgentLiveTimeline，它会显示 `emptyHint`。可以在 drawer 里加 `if (item.kind !== 'dispatch' && item.kind !== 'tool') 不渲染 timeline 段`，节省视觉空间。
2. **`item.task` 非 null 但 `last_execution_process_id` 为 null**（task 创建了还没跑）：同 1 处理，AgentLiveTimeline 显示 emptyHint。
3. **task 已 done**：AgentLiveTimeline 内部用 `isTerminal` 判断（`AgentLiveTimeline.tsx:240-249`），既会 hook 进 WS（拿历史 logs/messages 回放），也会显示绿色 "Done in Ns" 指示，没有"还在 streaming"的误导。
4. **rerun 后 last_execution_process_id 会变**：DecisionTimelineItem 通过 useDecisionTimeline → tasks 列表 → useBusEventEffect 监听 `task_status` 自动刷新（`IssueDetailPage.tsx:75-91`），drawer 因为 props 重渲会拿到新 id，AgentLiveTimeline 内部 useEffect 监听 processId 变化自动断旧 WS、连新 WS（`useExecutionProcessLogStream.ts:206-273`）——**自动收敛**。

### TasksRunsTab 当前怎么拿（参考但不一样的路径）

TasksRunsTab 用的是 `getExecutionProcesses(null, taskId)` 列出所有 runs 再 `setSelectedRunId(sorted[0].id)`（`TasksRunsTab.tsx:84-90`），因为它要让用户在多次 run 之间手动切换。**DispatchDrawer 不需要这个能力**（PRD 没要求 run history），用 `last_execution_process_id` 拿最近一次足够。

如果未来想加"切 run history"，再用 `getExecutionProcesses(null, taskId)`。当前 PRD 没要求。
