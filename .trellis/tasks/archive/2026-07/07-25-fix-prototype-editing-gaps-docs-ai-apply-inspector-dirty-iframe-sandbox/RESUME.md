# RESUME — 重启会话接力包

> 本会话因 harness 文件状态污染（另一个 Claude 会话的 stale 状态跟踪在每次工具调用时恢复 prototype 修改态，清掉主会话写入）决定重启。重启后污染消失。本文档让新会话不依赖丢失的 context 也能接着做。

## 任务

`.trellis/tasks/07-25-fix-prototype-editing-gaps-docs-ai-apply-inspector-dirty-iframe-sandbox/`

Goal: 修复原型编辑功能审计发现的 4 个问题。**用户 `/goal 帮我都改掉`，要求全做完。**

## 4 项修复（PRD 里有完整规格）

- **PR1**: iframe sandbox 统一（3 处 `allow-same-origin` → `allow-scripts`）+ 删 `llm_runner.py` 的 `stream_llm`/`resolve_streaming_context` 死代码（含 `AsyncIterator` import + `conductor_llm.py` 注释 + `test_llm_runner_streaming.py` 的 `test_stream_llm_...` 测试 + `_NoisyStreamClient` helper）+ 重写 CLAUDE.md 原型段。
- **PR2**: inspector dirty guard + 冲突提示（切节点/页/AI apply 前若有未应用编辑弹 ConfirmDialog）。
- **PR3**: 共享 evidence 校验（抽 `validate_and_attest_command_batch_evidence` helper，AI apply 路径在 reducer 前调用）。

## 当前状态（重启时）

- **PR1**: 丢失（被另一个会话回退清掉，主会话重做也被 harness 污染清掉）。需重做。
- **PR2**: trellis-implement agent 写了一半（3 文件 124 insertions 在磁盘：`StructuredPrototypeAiPanel.tsx` +15 / `StructuredPrototypeInspector.tsx` +43 / `StructuredPrototypeStudioPage.tsx` +71），但有**真语法错误**未完成（`activePage used before declaration` line 660、`controller.draft possibly null`、`pendingDirtyDiscard`/`aiApplyTriggerRef`/`requestAiApply`/`registerAiApplyTrigger`/`confirmDirtyDiscard`/`cancelDirtyDiscard` 声明未使用——接线未完成）。需修复 + 完成。
- **PR3**: 丢失（同 PR1）。需重做。
- **i18n keys** (`prototype.structured.dirtyGuard.*`): 未知是否在磁盘，需 `git diff` 确认。
- **测试文件** `frontend/tests/structuredPrototypeInspectorDirtyGuard.test.ts`: 未知是否在磁盘。

## 重启后第一步

1. `git status --short` + `git diff --stat` 看磁盘真实状态（diff 是真相，diagnostics 可能被污染）。
2. 确认 harness 污染已消失（写个无关文件测试，或直接看 prototype 文件 diff 是否干净）。
3. 按下方实现报告重做 PR1 + PR3，修复 PR2。

## PR2 完整实现报告（之前验证过 843 测试绿，照此重做/修复）

### 文件 + 改动

- `frontend/src/lib/i18n/en-US.ts` + `zh-CN.ts`: 加 4 个 key `prototype.structured.dirtyGuard.{title,description,confirm,cancel}`（en: "Unapplied edits"/"Switching will discard your unapplied edits. Continue?"/"Discard and continue"/"Cancel"; zh: "未应用的编辑"/"切换将丢失当前未应用的编辑，是否继续？"/"丢弃并继续"/"取消"）。
- `StructuredPrototypeInspector.tsx`: 加 `onDirtyChange?: ((dirty: boolean) => void) | undefined` prop（接口 + `EditableInspector` 解构）。把 `save()` 内联的 draft 组装 lift 到 `useMemo`，`save()` 和新 `isDirty` memo 共享。`isDirty = buildStructuredPrototypeInspectorBatch(node, inspectorDraft) !== null`（`layoutOverridesValid === false` 也算 dirty）。`useEffect` 调 `onDirtyChange(isDirty)`。
- `StructuredPrototypeAiPanel.tsx`: 加 `onRequireApply?: () => void` + `registerApplyTrigger?: (trigger: () => void) => void` props。AiPanel 用 `useEffect` 把 `applyAiProposal`（`ai.apply()`）注册进 studio ref。Apply 按钮调 `onRequireApply()`（若存在，否则直接 `ai.apply()`）。
- `StructuredPrototypeStudioPage.tsx`: 加 `inspectorDirty` + `pendingDirtyDiscard` state + `aiApplyTriggerRef` ref + `requestAiApply`/`registerAiApplyTrigger`/`confirmDirtyDiscard`/`cancelDirtyDiscard` callbacks。inspector 接 `onDirtyChange={setInspectorDirty}`。`useEffect` on `[selectedNode?.id, controller.draft.documentHash]` 重置 `inspectorDirty`。guard `handleLayerSelect`/`handlePageSelect`（dirty 时 `setPendingDirtyDiscard({kind:"layer"|"page", ...})` 早返回，同节点重选正常走）。AI apply 走 `requestAiApply`（dirty 时 `setPendingDirtyDiscard({kind:"ai"})`，否则调 `aiApplyTriggerRef.current?.()`）。warning variant `ConfirmDialog`（`open={pendingDirtyDiscard !== null}`），confirm 按 kind 执行 layer/page 切换或 AI trigger + 清状态 + `setInspectorDirty(false)`，cancel 只清状态。`aiMutating` 锁在 `ai.apply()` 真跑时才进。
- 测试 `frontend/tests/structuredPrototypeInspectorDirtyGuard.test.ts`: 10 测试（i18n 两语言、dirty predicate、source-contract 断言 inspector 暴露 onDirtyChange + studio 接 dirty state + 三 guard + dialog + AiPanel 路由 Apply 经 studio gate）。
- 更新 `frontend/tests/prototypeReleaseHistory.test.ts` + `frontend/tests/projectShellRouting.test.ts`: 断言 iframe `sandbox` 是 `allow-scripts` only（不匹配 `/allow-same-origin/`）。

### 关键 file:line（重启后需重新确认）

- Inspector remount key: `StudioPage.tsx:3294` `key={`${selectedNode?.id ?? "none"}:${controller.draft.documentHash}`}`
- `handleLayerSelect`: `StudioPage.tsx:1913`
- `handlePageSelect`: `StudioPage.tsx:1797`（清 selection）
- `onApply` 仅持久化路径: `Inspector.tsx:67` + `save()` `:583-619`
- `buildStructuredPrototypeInspectorBatch`: `Inspector.tsx:292-447`（`:441` 返回 null 当无变更）
- ConfirmDialog 现有用法: `StudioPage.tsx:3393-3412`（delete-prototype），import `@/components/ui/confirm-dialog`

## PR3 完整实现报告（之前验证过 ruff/mypy 绿 + 30 AI 测试 + 42 用户路径测试绿，照此重做）

### 文件 + 改动

- `backend/app/application/structured_prototype_service.py`: 加 helper
  ```python
  async def validate_and_attest_command_batch_evidence(
      self, *, document: PrototypeDocumentV1, batch: DomainCommandBatchV1,
      draft_id: str, base_head_sequence_no: int, base_document_hash: str,
      operation_id: str,
  ) -> PrototypeSnapWorkerAttestationResult | None:
  ```
  封装 `apply_command_batch` 内 `:2137-2150` 的逻辑：调 `validate_command_batch_evidence_context(...)`，若 `batch.evidence is not None` 调 `await self._attest_snap_evidence(request_id=_stable_id(operation_id, "snap-attest"), evidence_json=canonical_model_json(batch.evidence))` 返回 attestation，否则 None。mismatch 抛 `StructuredPrototypeContractError`(`command_evidence_mismatch`)，worker 故障抛 `StructuredPrototypeServiceError`。
- 重构 `apply_command_batch`（`:2172`）：helper 调用放**现有 try 块内**（让 `_fail_operation(running, step, exc.code)` handler 仍触发），`_write_replay_manifest` 的 `validation_report_hashes` 保持 `(snap_attestation.evidence_hash,) if snap_attestation is not None else ()`。纯提取，零语义变化。
- `backend/app/application/structured_prototype_ai_service.py`: `apply` 在 `execute_command_batch`（`:1155`）前调 `await self._structured_service.validate_and_attest_command_batch_evidence(document=base_state.document, batch=batch, draft_id=run.draft_id, base_head_sequence_no=run.base_head_sequence_no, base_document_hash=run.base_document_hash, operation_id=<operation_id>)`。把 `operation_id = _stable_id(run.id, client_request_id, "ai-apply-operation")`（原 `:1188`）提前到校验前。`StructuredPrototypeContractError`/`StructuredPrototypeServiceError` 包装成 `StructuredPrototypeAiServiceError(exc.code, str(exc), run_id=run.id)`（匹配现有 `:1140-1145` 的 `recover_draft`/`ensure_mutation_checkpoint` 错误包装模式）。**不改** AI replay manifest / `apply_ai_edit_run` store / reproducibility check / `commands_json` provenance。
- AI run 状态注意：`_fail_run`(`:2169`) 对 `preview_ready` run 是 no-op。匹配现有模式 = 抛 `StructuredPrototypeAiServiceError`，run 保持 `preview_ready`（用户可 reject/retry），**不持久化 batch**（校验在 execute 前 + apply_ai_edit_run 前）。新测试断言这点。
- 测试 `backend/tests/test_structured_prototype_service.py`: 3 helper 测试（mismatch 抛 `command_evidence_mismatch` 且不 spawn worker、valid evidence 返回 attestation hash、`evidence=None` 返回 None no-op）。
- 测试 `backend/tests/test_structured_prototype_ai_service.py`: 2 AI 测试（AI apply 拒绝 `freeformMove` evidence 与 base doc 冲突的 batch → `command_evidence_mismatch` + 不持久化 + run 保持 `preview_ready`；AI apply 对 `evidence=None` batch 仍成功——回归）+ freeform doc/evidence-batch builders。

### 验证命令

- `cd backend && .venv/bin/python -m ruff check app/application/structured_prototype_service.py app/application/structured_prototype_ai_service.py`
- `cd backend && .venv/bin/python -m mypy app/application/structured_prototype_service.py app/application/structured_prototype_ai_service.py`（注意：可能有 3 个预存无关错误在 `codex_process_manager.py`，属 ACP 工作，忽略）
- `cd backend && .venv/bin/python -m pytest tests/test_structured_prototype_service.py tests/test_structured_prototype_ai_service.py -q -k "evidence or attest or ai_apply or freeform"`
- PR1: `cd backend && .venv/bin/python -m ruff check app/application/llm_runner.py app/application/conductor_llm.py tests/test_llm_runner_streaming.py && .venv/bin/python -m pytest tests/test_llm_runner_streaming.py -q`
- PR2: `cd frontend && npx tsc --noEmit && npm run lint && node --import tsx --test tests/structuredPrototypeInspectorDirtyGuard.test.ts tests/prototypeReleaseHistory.test.ts tests/projectShellRouting.test.ts`

## PR1 实现细节（重做时照此）

- iframe 3 处（`StructuredPrototypeShareViewer.tsx:126` / `StructuredPrototypeGenerationPanel.tsx:361` / `StructuredPrototypeReleaseHistory.tsx:444`）：`sandbox="allow-scripts allow-same-origin"` → `sandbox="allow-scripts"`。AiPanel 已正确不动。
- `llm_runner.py`: 删 `resolve_streaming_context`（`:538`）+ `stream_llm`（`:560`）整段（到 `:623`），从 import 移除 `AsyncIterator`，修 `:347` prefill 注释（原 `see stream_llm for the rationale` → 自洽描述），修 `conductor_llm.py:3` docstring（去掉 `resolve_streaming_context` 引用）。**注意**：`call_llm_with_tools_streaming` 和 `StreamingPlanContext` 是活代码（`conductor_llm.py` 在用），不能删！只删 `stream_llm`+`resolve_streaming_context`。
- `test_llm_runner_streaming.py`: 删 `stream_llm,` import、`_NoisyStreamClient` class、`test_stream_llm_skips_non_object_and_malformed_sse_events` 测试。**保留** 4 个活测试（`test_call_llm_with_tools_streaming_*`/`test_llm_http_client_*`/`test_build_llm_runner_*`）。
- CLAUDE.md: 第 49 行整段「类 Claude Design 原型设计」（旧 SSE 系统）替换为「结构化原型编辑 Studio」现状段（PRD Technical Notes 里有最终版文案，含 PR2 dirty guard + PR3 validate_and_attest 描述）。

## harness 污染注意事项（重启后应消失，但留意）

- 现象：主会话每次工具调用可能恢复 stale prototype 修改态，清掉主会话写入。`git diff` 是真相之源，diagnostics 可能被污染。
- 重启后若仍有：所有代码改动走 trellis-implement 子 agent（子 agent 写入持久），主会话只做 git 操作 + 协调。
- 另一个会话的 ACP 工作改动（`codex_process_manager.py`/`json_rpc_client.py`/`runtime_catalog_service.py`/`acp_*.py` 等）**不是本任务的**，commit 时不要包含——只 commit prototype 相关文件 + CLAUDE.md + 本任务测试。

## commit 范围（只这些）

PR1: `frontend/src/features/prototype/structured/StructuredPrototypeShareViewer.tsx` / `...GenerationPanel.tsx` / `...ReleaseHistory.tsx` / `backend/app/application/llm_runner.py` / `backend/app/application/conductor_llm.py` / `backend/tests/test_llm_runner_streaming.py` / `CLAUDE.md`
PR2: `frontend/src/features/prototype/structured/StructuredPrototypeInspector.tsx` / `...AiPanel.tsx` / `...StudioPage.tsx` / `frontend/src/lib/i18n/en-US.ts` / `frontend/src/lib/i18n/zh-CN.ts` / `frontend/tests/structuredPrototypeInspectorDirtyGuard.test.ts` / `frontend/tests/prototypeReleaseHistory.test.ts` / `frontend/tests/projectShellRouting.test.ts`
PR3: `backend/app/application/structured_prototype_service.py` / `backend/app/application/structured_prototype_ai_service.py` / `backend/tests/test_structured_prototype_service.py` / `backend/tests/test_structured_prototype_ai_service.py`

**绝不** commit: `.structured_output_tmp.json` / `output/` / `examples/admin-demo/.env` / `.trellis/tasks/07-24-add-acp-runtime-adapter/` / 任何 ACP 相关文件（`acp_*.py`/`codex_process_manager.py`/`json_rpc_client.py`/`runtime_catalog_service.py`/`timeouts.py`/`bootstrap.py`/`domain/models.py`/`interfaces/api.py`/`RuntimeCatalogEditor.tsx`/`lib/types.ts`/`lib/types/runtime.ts`/`test_acp_runtime.py`/`tsconfig.tsbuildinfo`）。

## PR2 agent 半成品 diff（重启时磁盘状态，未完成有语法错误）

完整 diff 存在 `pr2-partial-diff.patch`。摘要：
- AiPanel.tsx +15: 加 `onRequireApply?`/`registerApplyTrigger?` props + useEffect 注册 trigger + Apply 按钮调 onRequireApply
- Inspector.tsx +43: 加 `onDirtyChange?` prop + 解构 + draft useMemo + isDirty memo + useEffect 报告
- StudioPage.tsx +71: 加 `inspectorDirty`/`pendingDirtyDiscard`/`aiApplyTriggerRef`/`requestAiApply`/`registerAiApplyTrigger`/`confirmDirtyDiscard`/`cancelDirtyDiscard` + inspector onDirtyChange 接线 + handleLayerSelect/handlePageSelect guard + ConfirmDialog

**未完成/有错误**（重启后需修复）：
- `activePage used before declaration`（StudioPage:660）— handlePageSelect guard 引用 activePage 错位
- `controller.draft possibly null`（StudioPage:810）
- `pendingDirtyDiscard`/`aiApplyTriggerRef`/`requestAiApply`/`registerAiApplyTrigger`/`confirmDirtyDiscard`/`cancelDirtyDiscard` 声明未使用 — 接线未完成（这些 callback 定义了但还没在 JSX 里用，或 guard 逻辑没接上）
- i18n keys 还没加
- 测试文件还没建

重启后建议：先 `git checkout -- frontend/src/features/prototype/structured/StructuredPrototypeAiPanel.tsx StructuredPrototypeInspector.tsx StructuredPrototypeStudioPage.tsx` 丢弃半成品，重新派 trellis-implement 按 PR2 完整规格重做（避免在错误基础上修补）。
