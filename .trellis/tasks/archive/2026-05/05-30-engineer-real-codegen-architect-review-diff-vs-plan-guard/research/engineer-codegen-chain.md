# Research: Engineer codegen + QA verification chain (本项目代码勘查，已亲验)

> 全部断言已对照 `backend/app/application/` 真代码逐行核实（非 LLM 二手结论）。

## Engineer 工作流 (`engineer_workflow.py`)

### Prompt 已强硬要求真落代码 —— 不是"缺要求"
- `:182-184` TOOL USE REQUIREMENT：status∈{completed,partial} 时 **MUST call Write/Edit/Bash**，"A description is NOT acceptable"。
- `:184` 要求跑 `git diff --name-only`，把结果 verbatim 作 `changed_files`。
- `:185` prompt 明确告知模型"框架会跑 post-execution git-diff 交叉检查"。
- **`:186`（关键边界，亲验）**：`changed_files=[]` **合法**仅当 `status='blocked'` 或"需求已实现无需改动（须在 summary 明说）"。
  → 这证实"合法空 diff"是系统已承认状态。**硬判据必须是「声称落码 vs 零 diff 的矛盾」，不能是「diff 为空」**，否则误杀"已实现"正常情况。

### Schema `EngineerReportDocument` (`:216-231` required_schema)
关键字段：`status: completed|partial|blocked|failed`、`changed_files: ["string"]`、`completed_tasks/deferred_tasks: [{title,description,priority}]`、`qa_notes: ["string"]`、`verification_commands`。

### 现有空-diff 兜底 (`persist_result`, `:260-275`) —— 有洞
```python
if report.status == "completed":              # ← :264 只覆盖 completed
    actually_changed = self._git_changed_files(task.workspace_path)
    if not actually_changed:
        report.status = "partial"             # 降级
        report.qa_notes = [claim_note, ...]   # [framework] 标注
        report.changed_files = []
```
- **洞 1（→ 本任务 C1）**：只覆盖 `completed`，`partial`+零改动漏过。
- **洞 2（→ 本任务 C2）**：未把 `changed_files` 与实际 diff 对账（可声称改了没改 / 改了没声称）。
- 产物落盘的是 **markdown 报告** `issues/<id>/engineer/implementation-<task>.md`（`:284-287`），**代码文件由 CLI 会话直接写盘**。

### 可复用 git helper (`_git_changed_files`, `:299-344`)
- `git diff --name-only {base}..HEAD`，base 回落顺序：`merge-base origin/main HEAD` → `main` → `HEAD~1`。
- 无 git 机制可达时返回 `[]`（安全降级）。**guard 计算实际 changed_files 直接复用它**。

## QA 工作流 (`qa_workflow.py`)
- 只读 Engineer markdown 报告 + 跑 `recommended_commands`（worktree cwd，`:188-209`）。
- `_reconcile_status_with_execution` (`:340-392`)：任一命令非零退出 → 硬 `failed`；零命令真跑 → 软 `needs_follow_up`；否则信 LLM。
- **洞（→ 本任务 D1）**：无独立 git-diff 核查。Engineer 不推荐命令时，QA 看不出"代码根本没改"。
- **本库既定哲学**（D1 要沿用）：事实确凿处硬约束（非零退出→failed），判断模糊处软信号（零命令→needs_follow_up）。

## Executor 环境 (`claude_process_runtime.py:114-217`)
- Engineer 跑 Claude CLI，cwd=隔离 worktree，`--permission-mode=bypassPermissions` → 确有写盘能力。不在本任务范围内改。
