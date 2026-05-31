# Research: Architect Review + diff guard 落点 (本项目代码勘查，已亲验)

> 全部断言已对照真代码逐行核实。

## Review 触发 & 写回链路
- **入口**：`api.py:4265-4327` `submit_codex_task_for_review(task_id)` → 原 Engineer task 置 `awaiting_review` → 建 review task（`role="architect"`, `task_kind="review"`, `parent_task_id`=engineer task, 继承 `workspace_path`）→ `run_codex_task(review_task_id)`。
- **决策解析/写回**：`api.py:319-351` —— 解析 `ReviewReportDocument` → `decision=="approve"` 则 parent `status="done"`，否则 `status="rework"`；review 反馈写 parent `review_comment`；发 `task_status` WS 事件。
- 人工评审同字段：`api.py:4336-4362` `POST /codex/tasks/{id}/review`。

## Review prompt 现状 —— 核心缺口（亲验 `architect_workflow.py:276-309`）
```python
def _build_review_prompt(...):
    # context_documents 只有三样：
    f"requirement: {pm_artifacts.get('requirement','N/A')}\n"
    f"system_design: {architect_artifacts.get('system_design_json','N/A')}\n"
    f"implementation_report: {engineer_artifacts.get('implementation_md','N/A')}\n"
    # ❌ 零 git diff、零 changed_files —— LLM 闭眼判
```
- `ReviewReportDocument` schema (`:39-47`)：`decision: ^(approve|reject)$`、`reason`、`suggestions[]`、`risks_identified[]`。
- **本任务 B5**：guard 结论需进 artifact（可加 `framework_guard` 字段）。

## implementation_plan.json schema —— PR1 落点（亲验）
```python
# architect_workflow.py:14-17
class ImplementationTask(BaseModel):
    title: str
    description: str
    priority: str = "P1"        # ← 无 expected_files
# :387-395 render 也只吐这三个字段
```
- 存储：`issue_artifact_documents.py` → `issues/<id>/architect/implementation_plan.json`。
- **PR1**：加 `expected_files: list[str] = []` 到 `ImplementationTask`；`_render_implementation_plan` 输出该字段；Architect 设计 prompt 要求预测（明示"尽力，不必精确"）；`tolerant_json` 读旧产物缺字段降级 `[]`。

## 现成 git 工具 (`git_service.py`) —— guard 复用
- `worktree_diff(worktree_path, base_branch)` (`:427`)：diff 内容 + untracked。
- `conflicted_files` (`:562`)、`commits_ahead` (`:505`)、`diff_shortstat` (`:533`)、`status_porcelain` (`:469`)。
- 另有 Engineer 私有 `_git_changed_files()`（见 [engineer-codegen-chain.md]）——guard 取 changed_files **名单**用它，取 diff **内容**用 `worktree_diff`。

## guard 设计（分级，沿用本库 hard/soft 哲学）
- **硬底线（确定性 reject，跳过 LLM）**：报告声称落码（`changed_files` 非空，或 status∈{completed,partial} 且 completed_tasks 暗示实现）**但**实际 git diff 为零 → `decision=reject` + `[FRAMEWORK] report-claim mismatch`。
- **合法放行**：诚实 `changed_files=[]` 且实际零改动（已实现/无需改）→ 不硬 reject（见 engineer prompt `:186` 明文）。
- **软信号**：`expected_files`(plan) vs 实际 changed_files 部分偏差 → `{expected,actual,missing,extra}` + 真实 diff 摘要注入 review prompt，LLM 权衡，不短路。expected_files 空则跳过软层。
- **路径归一化**：两边都 repo-relative，去 `./` 前缀。

## git 合并安全契约（动 worktree/git 必读）
- `.trellis/spec/vibe-kanban/backend/quality-guidelines.md` 的 "Worktree-Scoped Branch Merge (Swarm-Safe)" 场景（注：该 spec 挂在参考仓库命名空间下，但内容是**本项目** `05-29-parallel-swarm-scheduler` 写的真契约）：`squash_merge` 会 ff 主仓 main，swarm 路径须用 `squash_merge_into_branch`。本任务不改合并逻辑，但 PR4 集成测试涉及 swarm worktree 场景需遵守。

## 测试缺口
- 无 `submit_codex_task_for_review` / review 决策 / diff-guard 测试。
- 现有 `test_architect_workflow.py` 覆盖 schema 校验 + development_task_list 对齐 —— **新 expected_files 字段需扩这里的测试**。
