# Roadmap

记录"下一阶段做什么",按 ROI 排序。上次全面刷新: 2026-07-20 (旧版 Stage 1-4 见 git 历史,其中大部分已交付或被架构演进取代)。

---

## 当前主线 · Penpot 级结构化原型编辑器 (进行中)

唯一排队中的大型程序,PRD 与 ADR 见
`.trellis/tasks/07-19-penpot-grade-structured-prototype-editor/prd.md`。
确认范围是"do all of it" — 7 个里程碑顺序交付:

1. **Transform foundation** — 统一选择/命中模型、修饰键语义、旋转、显式 auto/absolute 定位、原子多选变换
2. **Layer operations** — lock、z-order、group/ungroup、重叠循环选择、图层搜索
3. **Precision system** — 标尺、持久参考线、统一吸附仲裁、constraints
4. **Direct editing** — 画布内联 Text/语义文案/Table 编辑,共享 typed command 通道
5. **Reusable design system** — 组件定义/实例/overrides、样式与图片资产、有界矢量图元
6. **Collaboration & scale** — presence、评论、冲突安全编辑、历史 UX、1000 节点性能预算
7. **End-to-end parity audit** — 桌面/移动矩阵、多会话验证、deterministic replay、AI parity、发布、双 fixture

**首刀** (PRD Technical Notes 指定): Stack/Grid/Form 容器内显式 absolute 定位,
复用 V1 `layoutItem.position`、`moveNode`、`setNodeLayout`、群组变换、吸附、inverse、replay。

---

## 待清点 backlog (`.trellis/tasks/` 未归档任务)

2026-07-20 按 PRD 验收框 + 代码证据清点后仍挂起的任务,分三类:

- **疑似废弃** (针对已移除的旧 code-scan/HTML 流生成链路,建议确认后关闭):
  `06-23-prototype-batch-regenerate` (regenerate-all 端点已不存在)、
  `07-12-prototype-generation-acceptance-fixes`、`07-13-prototype-workbench-redesign`
  (structured studio 已是唯一工作流)
- **未动工**: `06-27-audit-log-one-click-clear-button`、`06-27-audit-role-call-chain`
  (前端 audit 页尚无按角色分组的调用链视图)、`07-06-project-excellence-24h`、
  `07-10-startup-config-interaction`、`07-12-startup-config-claude-mcp`、
  `07-12-vue3-springboot-admin-demo` (admin-demo 仍是 07-19 验收 fixture,别删)
- **有进度未收尾**: `07-03-restore-operations-engineer-startup-scripts`、
  `07-08-fix-over-defensive-programming-patterns`、`07-09-ops-runcommand-envfix`、
  `07-14-fix-project-startup-service-identity-detection`

---

## 后续方向 (主线之外,按 ROI)

- [ ] **项目记忆 v2** — team_notes.md 从堆积式 deterministic 摘要升级:
  issue 完成后 LLM 精炼 lessons + anti-patterns 只留 5-10 条高 signal;"Forget" UI 可删/改记忆块
- [ ] **GitHub PR 闭环前端化** — `github_pr_followup.py` 后端已在
  (含测试与模型字段);把 Diff·Merge tab 与 PR 创建/review 回流打通成完整闭环
- [ ] **run manager WS 日志实时流** — 现前端轮询 `run/logs?after=<seq>`;
  接入全局 WS events 推增量
- [ ] **Workflow templates** — "CRUD endpoint / Bug fix / Refactor / Migration / Hotfix"
  内置模板,建 issue 时选用引导 Conductor
- [ ] **原型多文件沙箱** — structured prototype `framework` 字段预留的
  React/Vite 多文件运行时
- [ ] **生产化** — auth/多用户、per-issue 容器沙箱、SOC2 审计
  (07-11 trusted execution boundary: loopback token / secret fail-closed / Docker 加固已打底)

---

## 文档债

- [ ] CLAUDE.md「类 Claude Design 原型设计」段落仍在描述已删除的
  `prototype_service.py` + SSE HTML 流 + `regenerate-all` 端点;
  现实是 `structured_prototype_*` 服务家族 + typed command journal + deterministic
  replay + 发布。待按新架构重写该段。
- 旧 roadmap 的 "Auto-plan LLM JSON 解析" 条目随固定 DAG 编排一起被
  Conductor tool-use 架构整体取代,不再适用;"Anonymous workspace UX" 状态未核实。

---

## 已完成 (简要,证据在 CLAUDE.md / `.trellis/workspace/*/journal-*.md`)

- **2026-05**: Conductor 决策可视化 + 流式;并行 swarm (`dispatch_batch` +
  per-agent worktree 隔离 + in-flow join);成本感知调度 (per-issue 预算/软警告/并发压缩);
  统一审计日志 (audit_log + 6 choke-point + 全局 viewer);QA 真跑命令闭环
- **2026-06**: Conductor policy 与 decision explanation;self-improvement proposal
  ledger;coordinator source-informed upgrade;audit 时间过滤边界修复
- **2026-07**: QA framework-owned 完成证据;trusted execution boundary;
  agent 驱动 .env 自举 (加密入库 + 物化校验);项目一键 run manager;
  structured prototype 平台 (多页文档/图层树/typed commands/checkpoint/replay/
  runtime/发布/AI 提案/Penpot 式 freeform 交互);pane graph 前端重构;
  GitHub PR followup 后端;MCP 管理中心;本地 agent 原型协作边界
