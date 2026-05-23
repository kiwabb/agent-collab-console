# Research 01: AgentLiveTimeline Props 接口

- **Query**: 列出 `AgentLiveTimeline` 完整 props + 实际调用样例
- **Scope**: internal
- **Date**: 2026-05-23

## Component location

- File: `/Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/frontend/src/features/runs/AgentLiveTimeline.tsx`
- Function signature: `frontend/src/features/runs/AgentLiveTimeline.tsx:181-192` — `export function AgentLiveTimeline({...}: AgentLiveTimelineProps)`
- Interface定义: `frontend/src/features/runs/AgentLiveTimeline.tsx:14-25`

注意：interface 名是 `AgentLiveTimelineProps`，**未 export**（文件内部使用）。外部组件传 props 时按字段名直接传即可，无需 import 类型。

## Props 完整列表

| Prop | TypeScript 类型 | 必填 | 用途 |
|---|---|---|---|
| `executionProcessId` | `string \| null` | **是** | 喂给 `useExecutionProcessLogStream`（见 `:215`）作为 WS 订阅 key。`null` 时 hook 不连接，timeline 显示 `emptyHint` 或 `agentLive.noActiveAgent`。同时被用作 `WorkingIndicator` 是否渲染的开关（`:407`）。 |
| `taskStartedAt` | `string \| null \| undefined` | 否 | 任务 started_at ISO 时间，用于 `WorkingIndicator` 计算 elapsed（`:115`）。缺省则不显示 elapsed 数字。 |
| `taskStatus` | `string \| null \| undefined` | 否 | task.status 字符串。驱动 `isFailed` / `isTerminal` 派生（`:235-249`），决定渲染失败 banner / done indicator / 是否显示 Stop 按钮。 |
| `reviewComment` | `string \| null \| undefined` | 否 | 用于：(a) failed 情况的 `failureReason` 文案（`:258`），(b) `awaiting_review` 且 `[CLARIFY]` 前缀时弹 warning banner（`:251-254`）。 |
| `taskResult` | `string \| null \| undefined` | 否 | 失败时 fallback 显示。会尝试 JSON.parse；如果是 QA 结构（`status` / `bugs_found` / `final_recommendation`）会格式化显示（`:264-279`）。否则截断 800 char。 |
| `taskRole` | `string \| null \| undefined` | 否 | 失败 banner 标题里"<ROLE> 任务失败"的 role 名（`:294`）。 |
| `onRerun` | `() => Promise<void> \| void \| undefined` | 否 | 失败 banner 上 "Rerun" 按钮的 handler。**不传则不渲染该按钮**（`:296`）。组件内自己管 `rerunBusy` loading state（`:193-202`）。 |
| `onStop` | `() => Promise<void> \| void \| undefined` | 否 | `WorkingIndicator` 内 Stop 按钮的 handler。仅在 `!isTerminal && onStop` 时渲染（`:414`）。组件内管 `stopBusy`（`:203-212`）。 |
| `className` | `string \| undefined` | 否 | 外层 `<div>` 透传 className，会和 `flex flex-col h-full min-h-0` 合并（`:287`）。**注意 `h-full` 是默认**，所以父容器必须有明确高度。 |
| `emptyHint` | `string \| undefined` | 否 | 当 `executionProcessId == null` 且没有任何 entries 时显示的提示文案（`:349`）。如果没传，fallback 到 i18n key `agentLive.noActiveAgent`。 |

## 内部行为（影响调用方）

- **数据源**：通过 `useExecutionProcessLogStream(executionProcessId)` 拿 `{logs, streamingAssistant, heartbeat, finished, disconnected, error}`（`:214-215`）。**调用方完全不用管 WS / 重连 / heartbeat**——hook 内部全包了。
- **空状态分支**（`:284`）：`entries.length === 0 && !streamingAssistant?.text && !heartbeat`。
- **高度需求**：根 `<div>` 用 `flex flex-col h-full min-h-0`。**强烈建议父容器明确高度**（如 `h-[60vh]` 或 flex 子项），否则会撑死布局。
- **没有 onClose / 无 modal 控制**：组件不负责开关，只负责渲染。

## 标准用法样例 (RunDetail.tsx:546-566)

```tsx
<AgentLiveTimeline
  executionProcessId={process?.id ?? null}
  taskStartedAt={process?.started_at ?? null}
  taskStatus={taskMeta?.status ?? null}
  reviewComment={taskMeta?.review_comment ?? null}
  taskResult={taskMeta?.result ?? null}
  taskRole={taskMeta?.role ?? null}
  onRerun={
    onRunAgain
      ? async () =>
          onRunAgain(
            executionConfig.executor as "codex" | "claude",
            executionConfig.provider,
            executionConfig.model,
          )
      : undefined
  }
  onStop={onTerminate}
  className="h-full"
  emptyHint={t("run.noLogs")}
/>
```

引用位置：`frontend/src/features/runs/RunDetail.tsx:546-566`。注意 `className="h-full"` + 父 `<TabsContent>` 有 `absolute inset-0` 撑高度（`:539`）。

## 第二处用法样例 (TasksRunsTab.tsx:345)

`frontend/src/features/issues/tabs/TasksRunsTab.tsx:345-389` 传入：
- `executionProcessId={selectedRunId}`（来自本地 `useState<string | null>`，从 `getExecutionProcesses(null, taskId)` 列表里选第一个 `setSelectedRunId(sorted[0].id)`，`:89`）
- `taskStartedAt`/`taskStatus`/`reviewComment`/`taskResult`/`taskRole` 都从 `selectedTask` / `selectedRun` 取
- `onRerun` 调 `rerunCodexTask(selectedTaskId)` 再 reload
- `onStop` 在 confirm 后调 `terminateCodexTask(selectedTaskId)` 再 reload
- 没传 `className`、`emptyHint`

## 关键观察（给 DispatchDrawer 改造用）

1. 只要传一个 **execution_process_id** 进去，剩下的 streaming / heartbeat / 重连全自动。
2. 失败 banner / awaiting_review banner / done indicator 全在组件内自治，**外面不需要再写一层"任务状态说明"**——会重复。
3. `onRerun` / `onStop` 是可选的；DispatchDrawer 已经有 `chat` / `refine` / `rerun` 三按钮，可以选择不传 `onRerun`（避免双 rerun 按钮）但传 `onStop`（drawer 没有 stop 按钮）。
4. **高度**：必须给 `className="flex-1 min-h-0"` 或类似，让 `h-full` 在 flex 列布局里能拿到真正高度，否则会塌缩成 0。
