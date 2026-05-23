# Research 05: DispatchDrawer 当前结构 + 改造草图

- **Query**: DispatchDrawer 宽度、结构、props、hooks、关闭事件、状态分支；改造草图
- **Scope**: internal
- **Date**: 2026-05-23

## File
- `/Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/frontend/src/features/issues/components/DispatchDrawer.tsx:1-130`（共 131 行）

## 当前 Props（DispatchDrawer.tsx:12-15）

```ts
interface Props {
  item: DecisionTimelineItem | null;
  onClose: () => void;
}
```

注：interface 名只是 `Props`，未 export。`item == null` 时 early return `null`（`:22`），完全不渲染。

## 内部 hooks / state

- `useState<string>("")` → `draft`（textarea 输入，`:19`）
- `useState<"chat" | "refine" | "rerun" | null>(null)` → `busyAction`（按钮 loading，`:20`）
- `useToast()` → `addToast`（`:18`）

**没有**任何 stream / WS hook。**没有** useEffect / useMemo / useCallback。

## 宽度设置

文件 `DispatchDrawer.tsx:45`：

```tsx
<aside className="absolute right-0 top-0 flex h-full w-[480px] max-w-[calc(100vw-24px)] flex-col border-l border-border-subtle bg-background shadow-2xl">
```

- 固定 **`w-[480px]`**（Tailwind arbitrary value，480px）
- `max-w-[calc(100vw-24px)]`（小窗口 fallback）
- 全屏 fixed overlay + 右侧 aside 模式

## 内部结构（5 段）

| 段 | 行号 | 内容 |
|---|---|---|
| 1. Overlay | `:44` | `<button>` 覆盖全屏，点击触发 `onClose` |
| 2. Header | `:46-55` | role / status / title / taskId / Close 按钮 |
| 3. SubAgentResultCard（如有 result） | `:58-64` | 调用 `<SubAgentResultCard result={item.result} />` 或 fallback 文案 |
| 4. Summary section（如有 summary） | `:66-71` | `<pre>` 渲染 `item.summary` |
| 5. Task actions section | `:73-118` | textarea + Chat / Refine / Rerun 三按钮 |
| 6. Raw conductor turns section | `:120-125` | `<pre>` dump `JSON.stringify(item.rawTurns, null, 2)` |

整体外滚容器：`:57` —— `<div className="min-h-0 flex-1 overflow-auto px-5 py-4">`（垂直方向单一滚动区）。

## SubAgentResultCard 渲染位置

行号：`DispatchDrawer.tsx:58-64`
```tsx
{item.result ? (
  <SubAgentResultCard result={item.result} />
) : (
  <div className="rounded-2xl border border-border-subtle bg-surface-raised p-4 text-sm text-text-muted">
    No SubAgentResult was persisted for this dispatch yet.
  </div>
)}
```

这是 **task 终态卡片**（按 PRD `:6`，新版页面"只渲染 SubAgentResult 终态卡片"就是指这一块）。

## 关闭 drawer 的事件

1. **Esc 键**：❌ **没有**。组件没有 `useEffect` 监听 keydown，也没用 `useFocusTrap`。这是一个**已存在的可用性缺陷**。
2. **外部点击**：✓ `:44` overlay `<button onClick={onClose}>`。
3. **关闭按钮**：✓ `:52-54` 右上角 X 按钮 `<Button onClick={onClose}>`。

PRD（`prd.md:103`）没有要求加 Esc，但**改造时可顺手加上**（一行 useEffect），属低成本人机改善。

## task 状态分支（running / done / failed）的现有处理

**几乎没有**。当前 drawer 的逻辑全是"按钮 disabled 与否"：

| 位置 | 分支 |
|---|---|
| `:80` | `disabled={!item.taskId || busyAction != null}` (textarea) |
| `:91` | `disabled={!item.taskId || !draft.trim() || busyAction != null}` (Chat) |
| `:100` | 同上 (Refine) |
| `:110` | `disabled={!item.taskId \|\| busyAction != null}` (Rerun，允许空 draft) |

**没有**对 `item.task.status` 的判断。这意味着：
- task 正在 running 时也允许点 rerun（API 后端会 409 拒绝，但 UI 没拦）；
- task 已 failed 时没有突出的失败标识，用户只能从 header 的 `item.status` 文案隐式看出；
- 没有"任务还在跑"的视觉提示，正是 PRD 抱怨的"看不动了"。

## 改造建议草图

按 PRD `prd.md:54-71` 的要求：
- 宽度 → **`w-[560px]`**（从 480 加宽 80px，给 Live Stream 留视觉宽度）
- Live Stream 段 → 插在 SubAgentResultCard **之上**（新内容优先于终态）
- Summary & Task actions 下推

### 推荐新结构

```
overlay
└─ aside w-[560px] flex flex-col h-full
   ├─ Header (role / status / title / X)          ← 不变, :46-55
   ├─ 滚动容器 flex-1 min-h-0 flex flex-col gap-4 ← 加 gap, 内部改 flex 列
   │   ├─ ⭐ NEW: Live Stream section
   │   │    └─ <AgentLiveTimeline
   │   │         executionProcessId={item.task?.last_execution_process_id ?? null}
   │   │         taskStartedAt={item.task?.created_at ?? null}
   │   │         taskStatus={item.task?.status ?? null}
   │   │         reviewComment={item.task?.review_comment ?? null}
   │   │         taskResult={item.task?.result ?? null}
   │   │         taskRole={item.task?.role ?? null}
   │   │         onStop={item.taskId && taskIsRunning ? () => terminateCodexTask(item.taskId!) : undefined}
   │   │         className="flex-1 min-h-0"   // 让它占满剩余高度
   │   │         emptyHint="This dispatch hasn't produced output yet."
   │   │      />
   │   │    高度建议: 容器内 min-h-[280px] + flex-1，避免压扁 Summary&Actions
   │   ├─ SubAgentResultCard (existing, :58)     ← 不变
   │   ├─ Summary (existing, :66)                 ← 不变
   │   ├─ Task actions (existing, :73)            ← 不变
   │   └─ Raw conductor turns (existing, :120)   ← 不变 (折叠?)
```

### 实施细节注意

1. **滚动区从单层改两层**：当前 `:57` 是单一 `overflow-auto`。Live Stream 内部自己有 `overflow-y-auto`（`AgentLiveTimeline.tsx:343-345`），如果直接套进 `overflow-auto` 父容器，**双重滚动会冲突**。解决方案：
   - 外层 `flex-1 min-h-0 flex flex-col gap-4`（**不**用 overflow-auto）；
   - 内部 Live Stream 段固定高度（如 `h-[40vh]` 或 `flex-1 min-h-[280px]`）让其内部滚动；
   - 内部 SubAgentResult / Summary / Actions 段用一个**单独**的 `overflow-auto` 子容器。
   
   或更简单：Live Stream 段固定高度，下方非 stream 内容仍在原 `overflow-auto` 滚动区。

2. **task 状态条件渲染**：
   - 仅当 `item.kind === "dispatch"` 且 `item.task` 不为 null 时渲染 Live Stream 段（避免 clarification / memory / finalize / user / error 等非 dispatch item 也挂个空 timeline）。

3. **onStop 应只在 running 时传**：
   ```ts
   const running = ["running","responding","pending"].includes(String(item.task?.status ?? "").toLowerCase());
   const onStop = item.taskId && running ? async () => { await terminateCodexTask(item.taskId!); } : undefined;
   ```

4. **onRerun 是否传**？Drawer 已有 Rerun 按钮（`:108-116`），AgentLiveTimeline 的失败 banner 内也会显示 Rerun。**建议不传 onRerun**，避免双按钮。失败时让用户走下方 Task actions 区的 Rerun。

5. **Esc 关闭**：顺手加：
   ```tsx
   useEffect(() => {
     const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
     window.addEventListener("keydown", onKey);
     return () => window.removeEventListener("keydown", onKey);
   }, [onClose]);
   ```

6. **宽度自适应**：`w-[560px] max-w-[calc(100vw-24px)]` 保持 max-w 兜底。

### 改造后预期 vs 现状

| 维度 | 现状 | 改造后 |
|---|---|---|
| 宽度 | 480px | 560px |
| Live token stream | ✗ | ✓ (AgentLiveTimeline) |
| Heartbeat / phase 文案 | ✗ | ✓ |
| ToolBlock / ThinkingBlock | ✗ | ✓ |
| Failed banner | ✗（只 header status 文字） | ✓ |
| Clarify banner | ✗ | ✓（如适用） |
| Stop running task | ✗ | ✓（仅 running） |
| Esc 关闭 | ✗ | ✓（建议加） |
| Chat/Refine/Rerun | ✓ | ✓（保留） |
| Raw turns dump | ✓ | ✓（保留或折叠） |
