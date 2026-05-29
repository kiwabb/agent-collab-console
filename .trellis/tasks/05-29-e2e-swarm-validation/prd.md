# E2E Live Validation: Parallel Swarm + Cost-Aware

## Goal

把 parallel-swarm-scheduler + cost-aware-conductor-scheduling 两个阶段（十几层叠加、单测全绿但**从未端到端实跑**）在真实运行环境跑一遍，证明它们不只是"逻辑符合单测假设"，而是真能在执行器下跑通。暴露问题就修，全程截图/日志存证，产出 walkthrough 报告。

## 为什么需要

- 单测 495 passed 只覆盖"我们写的假设"，并发/worktree 合并/reconcile/预算 steering **全靠 mock**。
- PR3 那个会污染 `main` 的 bug 是 check **读代码**抓到的、不是跑出来的——真跑很可能还有别的。
- 这些是运行时行为：dispatch_batch 并发、per-agent worktree 隔离、顺序 merge 回 issue 分支、冲突 reconcile、预算软警告/收尾/并发下调。

## 环境现状（已探测 2026-05-29）

- dev 未运行（端口 9000/4000 空）；可 `./dev-local.sh` 起。
- `claude`（cmux）+ `codex`（npm-global）CLI 均在；**是否已认证未知**。
- 未设 `REAL_CLI`/API env（走默认；CLAUDE.md 默认 `REAL_CLI=true`）。
- 既有 walkthrough 报告 `.walkthrough/REPORT-2026-05-25.md` / `-26.md` 可循格式。
- 后端 log `/tmp/agent-collab-backend.log` 有历史活动（含 `/api/codex/cost-stats` 端点——说明可能已有成本相关 UI/端点）。

## 待验证清单（新代码路径）

**并行 swarm**：
- [ ] `dispatch_batch` 一轮真并发起 ≥2 agent（非伪并行）
- [ ] 每个 agent 独立 worktree，文件互不踩踏
- [ ] fan-out 前 `commit_issue_worktree` 让隔离 agent 看到上游产物
- [ ] 跑完顺序 squash-merge 回 issue 分支，无丢失；**主仓 `main` 不被污染**（PR3 修复的回归）
- [ ] 冲突 → reconcile turn 拿到冲突文件+diff
- [ ] agent worktree 完成/失败都清理，无泄漏
- [ ] WorkflowGraph 并行泳道可视化呈现

**成本治理**：
- [ ] `## COST / BUDGET` 块注入 Conductor 上下文（已花/预算/剩余 + 候选模型单价排序）
- [ ] 达阈值发 `budget_warning`、超预算发 `budget_exceeded` + 收尾引导（**loop 不被硬杀**）
- [ ] 预算紧张时 `dispatch_batch` 实际并发被下调
- [ ] 分模型定价：成本按实际模型单价算

## 已确认决策 + 机制核实（2026-05-29）

- **模式 = 两档**：先 mock 验机制，再授权一次真跑验产物。
- **机制核实（已扒代码 + 查 console.db catalog）**：
  - `REAL_CLI` 只在 `bootstrap.py` gate subagent 的 CodexProcessManager（真/mock CLI）+ QA 命令；**不 gate conductor 大脑**。
  - conductor 大脑（`llm_runner` httpx → Anthropic 协议）用 catalog 的 `claude` executor（`api_endpoint`+`api_key` 已配），`conductor_llm.model=MiniMax-M2.7`（便宜）。
  - ∴ **Tier 1（REAL_CLI=false）= 真大脑决策 + mock subagent + 真 git/DB/worktree**：验证几乎所有新编排路径，只有 agent 产物是合成的，只烧便宜大脑 token。
- **诱发 dispatch_batch**：大脑自己决定是否并行。需构造"明显可并行"的 issue（PR4 prompt 已加 fan-out 引导）；若诱发不出，回退手段：直接对 conductor 注入引导消息 / 或用一个最小集成脚本直接驱动 `dispatch_batch`。
- **观察**：后端日志 + DB（conductor_turns/events/workflow_nodes）+ git（worktree/分支/main 未污染）为主；UI 走查（WorkflowGraph 泳道、预算块）用 chrome-devtools 截图存 `.walkthrough/`。

## Plan（两档）

**Tier 1 — mock 验机制（REAL_CLI=false，先做，便宜）**
1. `REAL_CLI=false ./dev-local.sh` 起服务，确认健康。
2. 造一个明显可并行的 issue（如"并行写 3 个互不相关的文件/模块"），跑 conductor loop。
3. 验证清单（见下）逐条：dispatch_batch 并发、worktree 隔离、合并回 issue 分支、**main 未污染**、预算注入/事件/并发下调、泳道可视化。
4. 诱发不出并行就用回退手段触发；冲突路径若 mock 产物无冲突，构造冲突场景或确认走集成测试覆盖。
5. 暴露的 bug → trellis-implement 修 → 重验。

**Tier 2 — 一次真跑（REAL_CLI=true，授权后）**
6. 真 claude/codex 跑一个完整 issue，确认真实 agent 产物正确 merge、成本真实记账。
7. 截图 + 写 `.walkthrough/REPORT-2026-05-29.md`。

## 执行中发现 + 计划调整（2026-05-29）

- ✅ **证据#1**：`REAL_CLI=false ./dev-local.sh` 启动健康（backend `/api/codex/ready`=200，frontend 4000=200）。
- ⚠️ **风险**：唯一 project 指向真仓库本身（`/Users/.../agent-collab-console`，main）；在真仓库跑 worktree+合并验证有风险。
- ⚠️ **触发难点**：conductor 大脑（真调 API，MiniMax）自己决定是否用 dispatch_batch，非确定性；full live run 装配深（codex_workspaces 表尚未建过、conductor 自动启动链路）。
- **调整**：Tier 1 正确性验证改为**确定性真 git 集成测试**（throwaway 临时仓库 + 脚本化驱动，最安全可靠且免费），Tier 2 保留 live UI 走查（临时 project，截图证据）。

## Acceptance Criteria

- [ ] Tier1：上面"待验证清单"全部在真运行环境逐条过（或暴露并修复）
- [ ] 关键回归：实跑中 `main` 分支 ref/tree 未被 agent 改动污染
- [ ] 预算：实跑触发并观察到 `## COST/BUDGET` 注入 + budget_warning/exceeded 事件 + loop 不被硬杀
- [ ] Tier2：一次真执行器跑通，产物 merge 正确、成本记账非零
- [ ] `.walkthrough/REPORT-2026-05-29.md` 含证据（截图/日志/git 状态）
- [ ] 暴露的 bug 全部修复且回归测试补齐

## Out of Scope

- 新功能开发（只验证 + 修实跑暴露的 bug）
- 重写既有走查报告

## Technical Notes

- 起服务：`./dev-local.sh`（前 4000 / 后 9000）；**dev 在跑时别 `npm run build`**（clobber .next）。
- 触发并行：需 Conductor 在一个决策点用 `dispatch_batch` 派多个独立 agent——可能要构造一个"明显可并行"的 issue 或注入引导。
- 证据：截图存 `.walkthrough/`；git log/worktree 状态证明 merge 正确、main 未污染；事件流证明 budget_warning/exceeded。
