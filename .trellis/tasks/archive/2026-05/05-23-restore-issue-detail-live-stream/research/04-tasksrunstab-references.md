# Research 04: TasksRunsTab 残留引用 grep 结果

- **Query**: `TasksRunsTab` 在整仓的所有出现位置；删除是否安全；PRD "保留" 的决定是否合理
- **Scope**: internal
- **Date**: 2026-05-23

## Grep 命令

```bash
grep -rn "TasksRunsTab" /Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/ \
  --include="*.ts" --include="*.tsx" --include="*.md"
```

## 完整结果（按用途分类）

### 1. 自身定义（1 处）

| 位置 | 类型 |
|---|---|
| `frontend/src/features/issues/tabs/TasksRunsTab.tsx:38` | `export function TasksRunsTab({ issueId, issue }: Props)` —— 组件本体 |

### 2. 当前**活跃** import / 调用（0 处）

无。整个 `frontend/src/app/` 和 `frontend/src/features/`（除 TasksRunsTab.tsx 自身）都没有任何 import 或 JSX 调用。

证据：
```bash
# app 路由 - 0 hit
grep -rn "TasksRunsTab" frontend/src/app/  → (empty)
# features 目录除自身 - 仅自身
grep -rn "TasksRunsTab" frontend/src/features/
  → frontend/src/features/issues/tabs/TasksRunsTab.tsx:38: export function TasksRunsTab(...)
```

### 3. 测试断言（1 处，反向断言）

| 位置 | 用途 |
|---|---|
| `frontend/tests/issueCommandCenter.test.ts:52` | `assert.doesNotMatch(source, /TabsList\|TabsTrigger\|DagTab\|TasksRunsTab\|AgentTabContent/);` |

**这条是"反向断言"**：测试 `IssueDetailPage.tsx` 源码里**不应**出现 `TasksRunsTab` 字符串。这是上一次"redesign-issue-detail-page" 任务留下的回归 guard，确保新页面不再走老六 tab 布局。

意义：**删 TasksRunsTab.tsx 不会破这个测试**（测的是 IssueDetailPage 源码里没有该 token，与文件是否存在无关）。但**保留 TasksRunsTab.tsx 也不会破**，因为 import 链断开后，测试的字符串匹配语义不变。

### 4. 历史 / 文档引用（5 处，无运行时影响）

| 位置 | 类型 |
|---|---|
| `docs/walkthrough-report.md:59` | 历史文档描述 polling fallback |
| `docs/walkthrough-report.md:132` | 历史描述 4.7 阶段的 stream toggle |
| `docs/optimization-validation.md:68` | 历史优化备忘 |
| `.trellis/tasks/archive/2026-05/05-23-redesign-issue-detail-page/prd.md:95, 125, 196` | 上一次重构 PRD 的归档 |
| `.trellis/tasks/05-23-restore-issue-detail-live-stream/prd.md:16, 65, 94, 121, 142, 157` | 本任务 PRD 自身的引用 |

这些都是纯文档，不影响构建/运行/测试。

### 5. TasksRunsTab.tsx 自身的内部 import 依赖

`frontend/src/features/issues/tabs/TasksRunsTab.tsx:1-27` import 链：
- `next/navigation` (useSearchParams)
- `@/lib/api`(chatCodexTask/getCodexTasks/getExecutionProcesses/getRuntimeCatalog/refineCodexTask/rerunCodexTask/runCodexTask/terminateCodexTask/updateCodexTask)
- `@/hooks/useExecutionProcessLogStream` + `useExecutionProcessMessageStream`
- `@/lib/types`
- `@/components/ui/button` + `toast`
- `@/providers/I18nProvider`
- `@/components/runtime/ExecutionConfigSelector` + `normalizeExecutionConfig` + `ExecutionConfigValue`
- `@/components/ui/empty-state`
- `@/lib/utils`
- `@/features/runs/AgentLiveTimeline`  ← **关键**
- `@/features/issues/components/TasksOverviewBar`
- `@/hooks/useBusEventEffect` + `busEventMatchers`

这些 import 的目标文件（包括 `AgentLiveTimeline` 自身）在别处仍被使用，所以即使删 TasksRunsTab.tsx，那些目标文件不会成孤儿。

---

## 判断：删 TasksRunsTab.tsx 是否会破东西？

| 维度 | 状态 |
|---|---|
| 路由 (app/) | ✗ 无引用 |
| Feature 内 import | ✗ 无引用（除自身） |
| 测试断言（运行时） | ✗ 不依赖文件存在 |
| 文档 / archived PRD | ✓ 有，但纯文字、不阻塞 |
| AgentLiveTimeline 等依赖项 | ✗ 不会成孤儿（被 RunDetail.tsx 用） |

**结论：TasksRunsTab.tsx 实际上是孤儿文件（dead code）**。物理删除不会引起任何 build / lint / test 失败。

## PRD "保留 TasksRunsTab.tsx 不删" 的决定是否合理？

**保留是保守但可接受的选择，原因：**

### 支持保留的理由（弱）
1. **作为 AgentLiveTimeline 第二处 usage 例**：除 RunDetail.tsx 外，TasksRunsTab 提供了完整的"task 选择 → run history 选择 → live stream"流程示范，未来如果想再做"切 run history"功能可以照抄。
2. **回滚保险**：万一 IssueDetailPage 改造翻车，可以临时把它挂回去当 fallback。
3. **风险隔离**：本任务（restore live stream）的 PR 越小越好，删孤儿文件应该单独走一个 cleanup PR，不和功能修复混。

### 支持删除的理由（中等）
1. 真就是孤儿，路由和组件树都不引用；
2. ~700 行 dead code 增加心智负担；
3. 任何"参考用例"作用都被 `RunDetail.tsx:546` 完全覆盖（且 RunDetail 是活跃路径）。

### 建议
- **本任务（restore live stream）按 PRD 保留 TasksRunsTab.tsx**，符合"小 PR / 不混 concern" 的原则；
- 在 `.trellis/tasks/05-23-restore-issue-detail-live-stream/research/` 留个跟踪记录（本文件），**单独开一个 cleanup task** 把 `TasksRunsTab.tsx` + `frontend/src/features/issues/tabs/` 整个目录是否还有其他孤儿（如 DagTab / ArtifactsTab / DiffMergeTab / CollabFeedTab / AgentTabContent，参考 archived PRD `:125`）扫一次再删。

## 顺便：tabs/ 目录其他可能的孤儿

PRD archive 提到过的 tab 组件（`.trellis/tasks/archive/2026-05/05-23-redesign-issue-detail-page/prd.md:125`）：
- `DagTab`
- `TasksRunsTab` （本文件）
- `ArtifactsTab`
- `DiffMergeTab`
- `CollabFeedTab`
- `AgentTabContent`

如果它们也是孤儿，未来 cleanup 一并清理。**本任务不展开**。
