# 前端 lib 按域拆分（lib/api.ts + lib/types.ts）

## Goal

延续 06-27 重构的 Phase 3b/4 收尾：把前端两个超大文件按资源域拆分，恢复可读、可独立编辑的粒度。零行为变化。

- `lib/api.ts`（2061 行 / 164 export）→ 按域拆 `lib/api/<domain>.ts`，`lib/api.ts` 收缩为 re-export 聚合壳（保 68 处 `from "@/lib/api"` 调用点零改动）。
- `lib/types.ts`（999 行 / 97 export）→ 按域拆 `lib/types/<domain>.ts`，`lib/types.ts` 收缩为 re-export 聚合壳。

**与后台 agent 隔离**：本任务只动 `frontend/`，后台 agent 正在改的 `backend/app/application/audit*` 等后端文件零交集。

## What I already know

- `lib/api/fetch.ts` 已存在（Phase 3b 抽出 API_BASE/WS_BASE/formatApiErrorDetail/dedupedFetch/handleResponse）。本任务在其旁继续建 `lib/api/<domain>.ts`。
- api.ts 当前结构：顶部 import types + re-export fetch helpers，然后 164 个 wrapper 顺序排列。
- 域划分（按函数名前缀聚类）：
  - `workspaces`：getWorkspaces/createWorkspace/updateWorkspace/getWorkspace/deleteWorkspace/deleteAllWorkspaces/sendWorkspaceInput/terminateWorkspace/getWorkspaceStreamUrl
  - `projects`：listProjects/getProject/createProject/updateProject/deleteProject/selectDirectory/getProjectBranches/repairProject/getProjectStats/getProjectRemoteStatus/pullProject/项目 run/项目 conductor
  - `issues`：所有 CodexIssue 相关 + bulk + export/import
  - `tasks`：所有 CodexTask 相关 + execution process
  - `agents`：listAgents/getAgent/createAgent/updateAgent/deleteAgent/getAgentMessages/getAgentMesh
  - `conductors`：getConductorLog/Turns/State/StateLog/PhaseEstimates/sendConductorMessage/pause/resume/restartConductor + getIssueGraph/autoStartIssueGraph
  - `skills`：所有 Skill 相关
  - `prototypes`：所有 Prototype 相关
  - `runtimeCatalog`：getRuntimeCatalog/updateRuntimeCatalog/validateRuntimeCatalog/testRuntimeExecutor
  - `knowledge`：searchKnowledge/getSimilarIssues/getEmbeddingStatus/triggerKnowledgeReindex/team notes
  - `benchmarks`：所有 Benchmark 相关 + calibration
  - `audit`：getProjectAudit/getAuditLog
  - `approvals`：resolveApproval/getPendingApprovals
  - `stats`：getCodexStats/getCodexCostStats/getIssueBudget/getIssueOrchestrationPolicy
  - `health`：checkBackendHealth/getCodexStatus/getGlobalEventsStreamUrl
- types.ts 97 export，按相同资源域分组。

## Open Questions

- Q1 ✅ 决议：调用点保持 `from "@/lib/api"`（聚合壳 re-export），**不**强制迁到 `from "@/lib/api/projects"`。理由：68 处调用点零改动 = 零回归风险；深 import 迁移可作未来 follow-up。
- Q2：拆分 PR 粒度？→ 本任务一次性拆完（单 PR），因为是纯机械搬移 + 验证 tsc/test 全绿即可信任。

## Requirements

- R1：建 `lib/api/<domain>.ts`（~15 个文件），每个文件 import 自 `./fetch` + `../types`，搬入该域 wrapper。
- R2：`lib/api.ts` 收缩为 `export * from "./api/<domain>"` 聚合（+ 现有 fetch re-export），< ~60 行。
- R3：建 `lib/types/<domain>.ts`，搬入该域 type/interface。
- R4：`lib/types.ts` 收缩为 `export * from "./types/<domain>"` 聚合壳。
- R5：所有 64+ 调用点 import 路径不变；tsc/test/lint 全绿。

## Acceptance Criteria

- [ ] AC1：`wc -l frontend/src/lib/api.ts` < ~60（聚合壳）。
- [ ] AC2：`wc -l frontend/src/lib/types.ts` < ~60（聚合壳）。
- [ ] AC3：每个 `lib/api/<domain>.ts` < ~400 行。
- [ ] AC4：`npx tsc --noEmit` 在非 WIP 文件 0 error（WIP audit-* 的既有 error 不计）。
- [ ] AC5：`npm test` 通过率不低于拆分前（projectsPageMotion WIP 失败除外）。
- [ ] AC6：`npm run lint` 绿。
- [ ] AC7：所有 `from "@/lib/api"` / `from "@/lib/types"` 调用点零改动。

## Definition of Done

- 单 PR；纯机械搬移，零语义变化。
- tsc/test/lint 全绿。
- 不动 backend/、不动后台 agent 的 audit 文件。

## Out of Scope

- 调用点深 import 迁移（保留聚合壳）。
- 大组件（SkillsLibraryPage/ConductorLogPanel/InboxDashboard）抽 hook —— 独立 follow-up。
- 任何业务行为变更。
- backend 任何改动。

## Technical Notes

- 参考 spec：`.trellis/spec/ccgui/frontend/{directory-structure,type-safety,quality-guidelines}.md`。
- 验证命令：`cd frontend && npx tsc --noEmit && npm test && npm run lint`。
- 风险：搬移时漏 export / 循环 import。缓解：聚合壳用 `export *`；每个域文件只依赖 `./fetch` + `../types`，无横向依赖。
