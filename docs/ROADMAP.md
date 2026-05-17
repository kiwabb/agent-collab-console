# Roadmap

记录"下一阶段做什么",按 ROI 排序。每个 stage 是 1-2 周的工作量。

---

## Stage 1 · 巩固 (next, started)

底盘加固。不做新功能,但让后续每次改动都不会偷偷退化。

- [ ] **后端测试覆盖**
  - `tests/test_qa_workflow.py`、`tests/test_engineer_workflow.py` 当前是空文件,补完核心断言
  - 新加的端点 (`/cost-stats`, `/checklist`, `/answer`, `/steer`, `/restore`, `/abandon/finalize`) 都没有单元/集成测试,补
  - QA verification command 执行的安全过滤 + reconcile 逻辑要直接测
  - `_scan_and_backfill_artifacts` 的 canonical-file 判定逻辑要测,防 PM/Engineer/Architect/QA backfill 退化
- [ ] **Auto-plan LLM JSON 解析稳健**
  - Orchestrator 经常吐非纯 JSON (markdown fence、有 prose 前缀);现有 `tolerant_json_loads` 仍偶尔失败。补:
    - 增加自动 retry (max 2),失败前不要立刻 fallback to heuristic
    - 第二次重试时往 prompt 加 "Your previous output failed to parse. Reply with **only** the JSON object."
    - 把 raw response 写到 issue artifact 让用户可查
- [ ] **事件链 race / 静默吃异常**
  - 这次发现 `_refresh_task_result` 中 persist 抛出会被吃掉(只 mark failed,不 surface)。补:
    - 任何 persist 异常都要写一条 audit row,issue 头部出 ⚠️ 提示
    - 对每个 role 增加 "expected canonical artifact" 检查,缺失时显式 backfill (现已修了一半,补 architect/engineer)
- [ ] **Anonymous workspace UX**
  - 当前侧栏会显示 "1" "1" "2" 这种从旧数据来的单数字标题,无法区分。补:
    - workspace API 强制 title 非空(至少 3 字符)
    - 旧 row 显示 fallback `Workspace #<id-slice>` 而不是 `1`
    - WorkspaceFormDialog 在编辑时允许改 title 兼容历史
- [ ] **前端测试** (开个口子)
  - 加 Vitest + RTL,先覆盖关键组件:`StatusBadge` / `UndoBar` / `ApprovalsPage` / `InboxDashboard.computeBuckets`
  - CI workflow 跑 `npm test` + `npx tsc --noEmit`

---

## Stage 2 · Devin-killer + GitHub PR 闭环 (after Stage 1)

把"差异化卖点"走到底,核心是接 GitHub remote 真合 PR — Devin 做不到。

- [ ] **A4 narrative timeline**
  - issue 头部一条横向时间轴: PM 13:28 (PRD 3 acceptance criteria) → Architect 13:30 (5 components) → Engineer 13:36 (2 files changed) → QA 13:40 (1 cmd, 0 failures)
  - 纯前端,从现有 task.result 抽
- [ ] **C2 explain decision**
  - 每个 DAG 节点角落 ⓘ 按钮 → 抽屉显示 task.result 的关键 prose 字段(requirement_analysis / architecture_summary / summary / final_recommendation)+ 系统 prompt 摘录
- [ ] **C3 per-hunk attribution**
  - Diff·Merge 每个文件 hunk 头部一行 "by Engineer · run a710ff79 · 13:36"
- [ ] **🔥 GitHub PR 闭环**
  - `POST /api/codex/issues/{id}/pr/create` — 用 `gh pr create` 真提 PR
  - issue 表加 `github_pr_url` 字段
  - Diff·Merge tab 改造: "Open GitHub PR" 与 "Squash-merge" 并列
  - 后端轮询 PR review state (`gh pr view --json reviews`),review comment 回流到 task.review_comment → 自动 rework
  - PR 合上时把 issue 的 `git_merge_status` 改 "merged"
  - 这是 Devin 拿不到的能力(Devin 是云,没法绑你的私仓 remote)

---

## Stage 3 · 多智能体扩展

差异化最大、技术难度最高的一跳。Devin/MetaGPT 都没做。

- [ ] **项目记忆 v2**
  - 现在 team_notes.md 是 deterministic 摘要,堆积式。下一步: 每次 issue 完成喂一次 LLM 让它**精炼** lessons + 抽 anti-patterns,只保留有 signal 的 5-10 条
  - "Forget" UI:用户可以删 / 编辑 memory 块
- [ ] **Custom agent roles**
  - Security reviewer / DBA / Designer / Doc writer — 通过 Agent 表注册
  - UI 可视化拖拽编排 DAG,不局限于 PM/Architect/Engineer/QA 四角
  - 每个 role 自定义 prompt template + JSON schema
- [ ] **Workflow templates**
  - "CRUD endpoint" / "Bug fix" / "Module refactor" / "Migration" / "Hotfix" 五个内置模板
  - 新建 issue 时选模板,自动出对应 DAG
- [ ] **Parallel sub-agents**
  - Engineer 任务拆给 2-3 个 sub-engineer 同时跑(不同文件),最后 merge
  - 需要冲突解决策略

---

## Stage 4 · 生产化

企业发布前必修。不急的话可以后插。

- [ ] **Auth + 多用户**
  - Google OAuth / GitHub OAuth + RBAC + 每用户 cost cap
- [ ] **Cloud sandbox 隔离**
  - 现在 worktree 跑在用户机器上,危险代码会污染 host。Docker container per issue
- [ ] **Cost budget alerts**
  - `$/issue` 上限,超了暂停;Slack/email 推送
- [ ] **Audit log + SOC2**
  - 操作流水可查,过基本合规
- [ ] **企业 SSO + 共享 workspace**
  - 团队协作,issue 可分配,review 走 GitHub

---

## 已完成的阶段

参考 git log,简要回顾:

- **P0**: REAL_CLI=true 默认、QA 真跑测试、QA-fail → Engineer 自动 rework、Codex idle timeout
- **P1**: 跨 issue 项目记忆 (`.agent-collab/team_notes.md` deterministic 摘要 + 自动注入 prompt)
- **P2**: Agent 主动提问 (clarification_question schema field + Approvals 答问 UI + `/answer` 端点)
- **Devin 级交互**: D 闭环 (post-merge redirect / post-answer redirect / 浏览器 tab notifications / abandon undo) + A2 cost meter + A3 plan checklist + B1 Steer / B3 Fork / B4 Take over locally
- **E2E sweep**: 7 个 bug 全修(KPI 双计数 / `_steer.md` 污染 / sidebar nav / header phase / status badge / PM persist / settings hydration)
