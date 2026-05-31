# Engineer real-codegen reconciliation + Architect Review deterministic diff guard

## Goal

让 swarm 的"实现 → 评审"闭环对**真实代码改动**有确定性保障，不再纯靠 LLM 主观判断"报告 vs 代码是否一致"。两个根因：(1) Engineer 声称的产物与真实 git diff 可能脱节；(2) Architect Review 的 LLM 决策时**拿不到真实 diff**，只能读报告 markdown，判断脆弱（当初能驳回只是运气）。

## What I already know (扒码核实)

- **Engineer prompt 已强硬要求真落代码** (`engineer_workflow.py:182-186`)：必须调 Write/Edit/Bash，"描述"不接受；并要求跑 `git diff --name-only`。
- **框架已有 git-diff 交叉检查** (`engineer_workflow.py:264-275`)：`status=completed` 但 git diff 为空 → 自动降级 `partial` + 加 `[framework]` qa_note。复用 `_git_changed_files()` (`engineer_workflow.py:299-344`，base 回落 origin/main→main→HEAD~1)。
- **Engineer 跑在 Claude CLI**，cwd=隔离 worktree，`--permission-mode=bypassPermissions`，确实有写盘能力 (`claude_process_runtime.py:114-217`)。
- **QA 只读 markdown 报告 + 跑 recommended_commands** (`qa_workflow.py:188-209,417-427`)；非零退出强制 failed，但**无独立 git-diff 核查**——Engineer 不推荐命令时 QA 看不出"代码没改"。
- **Architect Review prompt 不含 git diff** (`architect_workflow.py:276-309`，只传 pm/architect/engineer markdown)。决策 `approve|reject` 解析后写 parent `status=done|rework` + `review_comment` (`api.py:319-351`)。
- **implementation_plan.json schema = `[{title, description, priority}]`** (`architect_workflow.py:387-395`)，**无预期改动文件字段** → 字面"diff-vs-plan"不可行。
- 现成 git 工具：`git_service.worktree_diff(base)` (line 427)、`conflicted_files` (562)、`commits_ahead` (505)、`diff_shortstat` (533)、`status_porcelain` (469)。
- 测试缺口：无 `submit_codex_task_for_review` / review 决策 / diff-guard 的测试。

## Assumptions (temporary)

- 最有价值且零 schema 变更的 guard = **diff-vs-claim**（Engineer 声称的 `changed_files` vs 实际 `git diff --name-only`），而非 diff-vs-plan。
- Review guard 既要"把真实 diff 喂给 LLM"，也要"empty-diff 时确定性短路 reject 不依赖 LLM"。

## Open Questions

- [Q1] ✅ **已定：diff-vs-plan** — 扩展 Architect 输出 `expected_files`（per implementation task 预测预期改动文件），guard 比对 plan.expected_files vs 实际 git diff。
- [Q2] guard 触发后行为（关键风险：Architect 写码前预测文件不会全准，纯文件缺失硬 reject 会误报）：硬短路 vs 软信号 vs 分级？
- [Q3] 范围是否含 Engineer 侧加固（partial-zero-change、claimed-vs-actual 对账重写）+ QA 独立 git 核查？还是只做 Review guard？

## Decision (ADR-lite)

**[Q1] guard 基准：diff-vs-plan**
- Context: implementation_plan.json 当前无文件字段；用户要更精细的 plan 对齐而非仅 claim 对齐。
- Decision: 扩展 `ImplementationTask` schema 加 `expected_files: list[str]`，Architect prompt 要求预测每个 task 的预期改动文件；plan 渲染 + review guard 消费它。
- Consequences: 需改 Architect schema/prompt/render + tolerant_json 兼容旧产物（无该字段时降级）；Architect 预测不准会引入误报风险 → 由 [Q2] 的触发行为吸收。

**[Q2] guard 触发行为：分级（硬/软分界，沿用本库既定哲学）**
- Context: 本库既定模式=「事实确凿处硬约束，判断模糊处软信号」（QA 非零退出硬 failed vs 零命令软 needs_follow_up；Engineer 空 diff 硬降级；budget 软语义）。Architect 写码前预测 expected_files 必然不准，纯文件缺失硬 reject 会误报。
- Decision:
  - **空 diff（声称实现但实际零改动）= 铁证 → 确定性 reject，跳过 LLM**（与 QA 非零退出同级）。
  - **expected_files 部分缺失/多改 = 模糊 → 软信号**：把 `{expected, actual, missing, extra}` 结构化差异 + 真实 diff 注入 review prompt，LLM 权衡决策。
- Consequences: 杜绝"实现造假"硬底线，又不因 Architect 预测误差误杀正常实现；review LLM 首次拿到真实 diff 作 ground truth。

## Requirements

**Q3 范围已定：全链路加固（Architect + Engineer + QA）**

### A. Architect 侧（diff-vs-plan 数据源）
- A1. `ImplementationTask` schema 加 `expected_files: list[str] = []`（repo-relative 预期改动文件）。
- A2. Architect 设计 prompt 要求每个 implementation task 预测 `expected_files`（含将新建的文件）；明示"尽力预测，不必精确"。
- A3. `_render_implementation_plan` 输出含 `expected_files`；`tolerant_json` 读旧产物缺字段时降级为 `[]`（向后兼容）。

### B. Architect Review 侧（分级 guard）—— 核心
- B1. review 决策前，确定性计算实际改动：复用 `_git_changed_files()` / `git_service.worktree_diff(base)`，base 回落 origin/main→main→HEAD~1。
- B2. **硬底线（claim vs reality 矛盾 → 确定性 reject，跳过 LLM）**：Engineer 报告声称落码（`changed_files` 非空，或 status∈{completed,partial} 且 completed_tasks 暗示实现）**但**实际 git diff 为零 → 写 `decision=reject` + `[FRAMEWORK] report-claim mismatch: claimed implementation but zero file changes`。
- B3. **合法空 diff 放行**：Engineer 诚实 `changed_files=[]` 且实际 diff 也为零（已存在/无需改码）→ 声称=现实，**不触发硬 reject**，交 LLM 正常判。
- B4. **软信号（expected_files vs 实际 diff 部分偏差）**：计算 `{expected, actual, missing, extra}`，把差异 + 真实 diff 摘要结构化注入 review prompt，LLM 权衡；不短路。
- B5. review artifact 记录 guard 结论（如 `framework_guard: {verdict, missing, extra}`）供观测/前端。

### C. Engineer 侧加固
- C1. 现有空-diff 降级只覆盖 `completed` → 扩展到 `partial`（partial+零改动同样降级/标注）。
- C2. **claimed vs actual 对账**：以 `git diff --name-only` 为准重写 `changed_files`；若声称≠实际，加 `[framework]` qa_note 记录差异。

### D. QA 侧独立核查
- D1. QA 在跑 recommended_commands 之外，独立核查 worktree 相对 base 的 changed_files：若 Engineer 报告暗示实现但实际零改动，置 `needs_follow_up`（沿用 reconcile 软语义），即使无推荐命令也能发现"代码没改"。

## Acceptance Criteria

- [ ] AC1: Architect 产出的 implementation_plan.json 含 `expected_files`；旧产物（无字段）读取降级为 `[]` 不报错
- [ ] AC2: review LLM prompt 首次包含真实 diff 摘要 + expected/actual 差异
- [ ] AC3: 「声称落码 + 零 diff」→ 确定性 reject，不调 LLM（可断言无 LLM 调用）
- [ ] AC4: 「诚实 changed_files=[] + 零 diff（已存在）」→ 不被硬 reject
- [ ] AC5: 「expected_files 部分缺失」→ 软信号注入 prompt，不短路
- [ ] AC6: Engineer partial+零改动 被降级/标注；claimed≠actual 时 changed_files 重写为实际
- [ ] AC7: QA 无推荐命令但代码零改动时置 needs_follow_up
- [ ] AC8: 新增测试覆盖 B2/B3/B4/C1/C2/D1；串行 + 并行 swarm 路径零回归（后端快档全绿）

## Expansion notes (edge cases)
- 合法空 diff（已存在功能）必须放行——硬判据是 claim-vs-reality 矛盾，非"diff 为空"。
- 并行 swarm：Engineer 跑隔离 per-agent worktree，review 任务继承 workspace_path；guard 的 base 回落需在 worktree 内成立（_git_changed_files 已处理）。集成测试需覆盖 swarm worktree 场景。
- 路径归一化：expected_files 与 git diff --name-only 都按 repo-relative 比对，去 `./` 前缀。
- expected_files 为空（纯配置/文档任务 Architect 没预测）→ 软层跳过 plan 比对，仅保留 B2/B3 硬层。

## Definition of Done

- 后端快档测试绿 + 新增针对性测试
- 不污染 main（动 git 合并相关先读 `.trellis/spec/vibe-kanban/backend/quality-guidelines.md`）
- 行为变更记进 spec / team_notes

## Out of Scope (explicit)

- 不改 executor / CLI 启动机制（Engineer 已有写盘能力）。
- 不做前端 guard 可视化的大改（仅后端把 guard 结论塞进 artifact，前端展示留后续）。
- 不引入 LLM 调用做"语义级"diff-plan 比对（guard 全程确定性 + 现有 review LLM）。
- 不动 budget / 并发调度逻辑。

## Implementation Plan (small PRs)

- **PR1 — Architect expected_files 数据通道**：`ImplementationTask.expected_files` schema + 设计 prompt 预测 + render + tolerant_json 向后兼容 + 测试（AC1）。
- **PR2 — Review 分级 guard（核心）**：review 决策前确定性算 changed_files/diff；硬底线 claim-vs-reality 矛盾短路 reject（AC3/AC4）；软信号 expected/actual 差异注入 prompt（AC2/AC5）；guard 结论入 artifact（B5）+ 测试。
- **PR3 — Engineer + QA 加固**：Engineer partial 空-diff 降级 + claimed/actual 对账重写（C1/C2/AC6）；QA 独立 git 核查（D1/AC7）+ 测试。
- **PR4 — 集成 + 回归**：串行 + 并行 swarm 端到端确定性集成测试覆盖三态（AC8）；记 spec / team_notes。

## Technical Notes

- 关键文件：`engineer_workflow.py` / `architect_workflow.py` / `qa_workflow.py` / `git_service.py` / `api.py:319-351,4265-4327`
- 参见 memory [[feedback_verify_before_claiming_gaps]]：本任务前提已部分被现有兜底覆盖，范围据实收敛。
