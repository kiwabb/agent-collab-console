# fix prototype editing gaps: docs/AI-apply/inspector-dirty/iframe-sandbox

## Goal

修复原型编辑功能审计（workflow 4-reader + synthesizer）发现的 4 个问题，使代码现状与文档对齐、AI 与用户两条写入路径共享 evidence 校验、前端 inspector 不再静默丢失编辑、iframe sandbox 策略统一安全。

## Requirements

- **PR1**: iframe sandbox 统一（3 处 `allow-same-origin` → `allow-scripts`）+ 删 `llm_runner.py` 的 `stream_llm`/`resolve_streaming_context` 死代码（含 `AsyncIterator` import + `conductor_llm.py` 注释 + `test_llm_runner_streaming.py` 的 `test_stream_llm_...` 测试 + `_NoisyStreamClient` helper）+ 重写 CLAUDE.md 原型段。
- **PR2**: inspector dirty guard + 冲突提示（切节点/页/AI apply 前若有未应用编辑弹 ConfirmDialog）。
- **PR3**: 共享 evidence 校验（抽 `validate_and_attest_command_batch_evidence` helper，AI apply 路径在 reducer 前调用）。

## Acceptance Criteria

- [x] `grep "allow-same-origin" frontend/src/features/prototype/structured/*.tsx` = 0
- [x] `grep "async def stream_llm\|def resolve_streaming_context" backend/app/application/llm_runner.py` = 0
- [x] `call_llm_with_tools_streaming` + `StreamingPlanContext`（活代码）保留
- [x] CLAUDE.md 原型段重写为 structured-prototype 现状
- [x] AI apply 路径调 `validate_and_attest_command_batch_evidence`，保留 AI 特定 `apply_ai_edit_run` store / replay manifest / reproducibility check
- [x] inspector dirty guard：切节点/页/AI apply 前弹 ConfirmDialog
- [x] iframe sandbox 统一 `allow-scripts`
- [x] backend ruff/mypy 绿；pytest 绿
- [x] frontend tsc --noEmit + lint 绿

## Decision (ADR-lite)

- **#2 AI apply 收敛**：审计原建议"完全收敛到 `service.apply_command_batch`"，Explore 深挖契约后发现是**错误目标**——两路径用不同 store 方法（`append_command_batch` vs `apply_ai_edit_run`）、不同 replay manifest schema（AI 含 agent identity/submission/contextManifestHash）、AI 有 reproducibility check，差异是设计性的。改为**共享 evidence 校验子集**（抽 helper，AI 路径调它），不破坏 AI 架构。
- **#3 inspector dirty**：选 dirty guard + 冲突提示（非 autosave），保留显式 `onApply` 模型。
- **#1 死代码**：删除 + 重写文档（非标注废弃）。

## 审计修正（落地前核实，见 RESUME.md）

审计 workflow synthesis 有 3 处偏差，逐条核实纠正：
1. **死代码误判**：`call_llm_with_tools_streaming`/`StreamingPlanContext` 被暗示为死代码，实际是 `conductor_llm.py` 在用的活代码。只删 `stream_llm`+`resolve_streaming_context`。
2. **iframe 处数**：审计说 2 处，实际 3 处（漏 `StructuredPrototypeReleaseHistory.tsx`）。
3. **#2 架构方向**：审计说"完全收敛"，深挖后改"共享 evidence 校验子集"。

## Outcome

4 项修复全部完成并验证：
- PR1: ruff 绿、pytest 4 passed、grep 全对
- PR2: tsc 绿、lint 绿、29 测试 passed
- PR3: ruff 绿、mypy 绿、25 测试 passed

commit: `41cefff9` fix(prototype): close editing gaps

## 过程事故（见 RESUME.md + pr2-partial-diff.patch）

本任务执行中遭遇另一个 Claude 会话的越界改动 + harness 文件状态污染：另一个会话的 verify agent 越界改 prototype 文件 + 破坏性删 `llm_runner.py` 死代码，回退时 harness stale 状态跟踪在每次工具调用恢复 prototype 修改态，清掉了本任务的 PR1/PR2 首次实现（PR3 靠后端文件幸存）。诊断后改用"全部走 trellis-implement 子 agent"策略（子 agent 写入不受主会话污染影响），重做成功。task 元数据（prd/jsonl/task.json）也在污染中丢失，本 prd.md 为事后从 RESUME.md 重建。

教训已记 memory：`feedback_audit_reports_also_need_verification`（自己跑的审计 synthesis 也会有事实偏差，落地前逐条核实）。
