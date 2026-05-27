# 浏览器走查报告：创建需求 → Conductor 编排

走查时间：2026-05-24 13:47–13:51
走查人：Claude（Chrome DevTools MCP）
被测需求：`ab143b62-2f4b-459b-a9a0-d766a4eb61bb`「添加 GET /api/codex/walkthrough 健康检查端点」
执行器：minimax / MiniMax-M2.7

---

## 一句话结论

**流程本身能跑通**（conductor 启动、决策、dispatch engineer 都正常），但有一个 **P0 缺陷导致"走不通"**：conductor 等待 subagent 期间不续租，租约（180s）短于 subagent 超时（900s），watchdog 误判 conductor 为"孤儿"并重启第二个，两个 conductor 并发竞争 → 同一需求堆出 3 个重复 engineer 任务。

---

## 逐步走查记录

| 步 | 操作 | 观察 | 截图 |
|----|------|------|------|
| 1 | 打开 `localhost:4000` Inbox | 5 个需求全部「排队中」，0 running/done。无 console 报错。backend ✓ | `01-inbox.png` |
| 2 | 侧栏「需求」→ 进工作区「测试1」| 需求看板正常，有「新建需求」按钮 | `02-requirements-board.png` |
| 3 | 点「新建需求」填表 | 弹窗文案写「启动 PM→Architect→Engineer→QA 流水线；PM 完成后会暂停等你确认 PRD」 | `03-new-issue-dialog.png` |
| 4 | 点「创建并启动」| toast「需求已创建」。网络：`POST /api/codex/issues 201` + `POST .../graph/auto-start 201` | — |
| 5 | 进 issue 详情页 | CONDUCTOR 阶段 `awaiting_subagent`，当前任务 `engineer#d46e73 responding`，决策时间线 1 条「已分发 engineer」，思考 2 轮。顶部徽章却显示「排队中」 | `04-issue-detail-running.png` |
| 6 | 轮询 30×8s 等 engineer | 第 17 次：`engineer=failed`，conductor 回到 `awaiting_llm`，并冒出**第二个** `engineer=running` | — |
| 7 | 查 conductor turns / tasks | 本 issue 出现 **3 个 engineer task**，**2 个 conductor 实例**（`6595d665` 2 次 dispatch + `f47e2aea` 1 次） | — |

---

## 发现 1（P0｜真正的"走不通"）：lease 不续租 → watchdog 误杀 → conductor 自我克隆

### 时间线（后端日志）
- `13:47:02` auto-start **只调用一次**，起 conductor `6595d665`
- conductor → 推理 2 轮 → `dispatch_subagent(role=engineer)` → 阻塞在 `await registry.wait_for(task_id, timeout=900)`
- engineer（minimax）跑了 **3 分多钟**
- `13:50:33` **conductor recovery watchdog** 判定 `6595d665` 为孤儿，relaunch 第二个 conductor `f47e2aea`
  - 日志原文：`conductor relaunch: starting new loop for issue ab143b62 ... Recovered and relaunched 1 orphan conductor task(s)`
- 两个 conductor 并发，各自 dispatch engineer → 3 个 engineer

### 根因
| 参数 | 值 | 文件 |
|------|----|----|
| `CONDUCTOR_LEASE_TTL_S` | **180s** | `conductor_lease.py:25` |
| `CONDUCTOR_RECOVERY_INTERVAL_S` | 30s | `conductor_lease.py:29` |
| subagent `wait_for` 超时 | **900s** | `conductor_tools.py:88` |

`heartbeat()`（续租）只在 `persist_turn`（`conductor_main_loop.py:376`）和 `set_phase`（:426）里调用——**只在轮次边界/阶段切换续租**。真正等 subagent 的 `await registry.wait_for(..., 900)` 在工具执行内阻塞，**这段时间不续租**。

→ 进入 `awaiting_subagent` 续租一次（到期 = now+180s）→ subagent 跑 >180s → 租约过期 → watchdog 判孤儿 → 重启。**只要任何 subagent 跑超过 3 分钟（真实 LLM 编码任务的常态），就必然触发。**

### 次级缺陷：relaunch 去重 guard 失效
`conductor_recovery.py:_try_relaunch` 的 guard 检查"是否已有 `running`/`paused` 的 conductor"。但 `_mark_stalled`（:129）在 `_try_relaunch`（:137）**之前**就把存活的 conductor 状态从 `running` 改成了 `stalled`，所以 guard 的 `{running, paused}` 判断查不到它 → 仍然重启。

### 建议修复（按推荐度）
1. **（首选）等待 subagent 期间持续续租**：在 `awaiting_subagent` 阶段起一个后台心跳任务（如每 `TTL/3` 秒调一次 `heartbeat()`），subagent 返回后停。架构上最正确——租约短利于快速发现真孤儿，但存活但阻塞的 conductor 必须续租。
2. **`_is_stale` 加同进程存活判断**：即使 `lease_expires_at` 过期，若 `lease_owner` 的 pid == `os.getpid()` 且 runner 协程仍注册存活，则不算孤儿（同一进程不该重启自己还在跑的 conductor）。
3. **guard 顺序修正**：`_try_relaunch` 的去重判断应在 `_mark_stalled` 之前做，或改为按 conductor_task_id 排重而非按 status。

---

## 发现 2（UX 不一致｜非 bug）：PM / Architect 这次被 conductor 主动跳过

页面上看不到 PM/Architect，**不是渲染问题**。本 issue conductor turn 0 原话：

> "Since the requirements are crystal clear, I'll go directly to the `engineer` to implement this, then `qa` to verify."

即 conductor 按"自主决策"新架构判定需求清晰，**主动跳过 PM/Architect 直接上 engineer**。这符合 CLAUDE.md 的 Conductor-driven 设计。

**但**「新建需求」弹窗文案仍写着旧的固定流水线：
> "启动 PM→Architect→Engineer→QA 流水线。PM 完成后会暂停等待你确认 PRD..."

→ 文案与实际行为矛盾，会让用户误以为一定会有 PM/Architect 步骤和 PRD 确认 gate。建议改文案为"启动 Conductor 自主编排（按需调用 PM/Architect/Engineer/QA）"。

---

## 发现 3（小｜状态映射）：conductor 运行中，issue 仍显示「排队中」

conductor 实际 `running`（`awaiting_subagent`）时，看板和详情页顶部徽章都显示「排队中」、运行计数 0。因为 `issue.status` 仍是 `open`，`StatusStrip` 把 `open` 映射成「排队中」。conductor 跑起来时没有把 issue 翻成 `in_progress`，对用户有误导。

---

## 附：本次 issue 真实任务清单
```
ab143b62 tasks: 3 × engineer (1 done, 2 responding) — 无 pm / 无 architect
conductors: 6595d665 (7 turns, 2 dispatch) + f47e2aea (3 turns, 1 dispatch)
```
