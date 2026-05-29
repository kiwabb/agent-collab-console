# Research: 并发 Agent 同改一个 Git 仓库的隔离与合并策略

- **Query**: N 个并发 agent 同时改同一个 git 仓库时的隔离与合并策略（per-agent worktree 合并回 issue 分支 / 共享 worktree 替代方案 / 业界做法 / 基于现有 git_service 的最简实现）
- **Scope**: mixed（internal: 本仓库 + vibe-kanban 参考实现；external: 业界 AI coding 工具的领域知识）
- **Date**: 2026-05-29

---

## 0. 现状（本仓库）

| File Path | 说明 |
|---|---|
| `backend/app/application/worktree_manager.py` | issue-scoped worktree 生命周期。**关键约束在 module docstring**：`All tasks under one issue share the issue's worktree (PM, architect, engineer, qa run sequentially and need to see each other's artifacts)` |
| `backend/app/application/git_service.py` | 异步 git CLI 封装，提供所有原语 |
| `backend/app/application/task_dispatcher.py:125-128` | dispatch 时把 `issue.git_worktree_path` 作为 `workspace_path` / `git_worktree_path` 传给 task —— **所有 subagent 拿到同一个路径** |
| `backend/tests/test_worktree_manager.py` | 现有 worktree 行为测试 |

**踩踏根因**（`worktree_manager.py:1-6` + `task_dispatcher.py:125`）：`prepare_issue_worktree` 每个 issue 只建一个 worktree，`dispatch_role` 把同一个 `git_worktree_path` 注入每个 task 的 cwd。当前设计**显式假设 role 串行执行**（PM→architect→engineer→qa），靠串行避免冲突。要并行，这个假设被打破。

现有 git 原语（`git_service.py`）：
- `create_worktree(repo, branch, worktree_path, base_branch)` → `git worktree add -b <branch> <path> <base>`（L183-208，含 `worktree prune` 防 stale）
- `squash_merge(repo, source_branch, base_branch, message)` → **用临时 detach worktree 做 `merge --squash` + commit，再 ff-only/update-ref 推回主仓**（L224-313）。注意：**conflict 时直接 `reset --hard` + 抛 `GitError`，不留半成品**（L269-273）
- `worktree_diff(worktree_path, base_branch)`（L317-352，含 untracked 合成 patch）
- `commit_all(worktree_path, message)` → `add -A` + commit，nothing-to-commit 返回 None（L365-381）
- `commits_ahead/commits_behind(worktree_path, base)`（L395-421）—— 检测分叉的现成原语
- `status_porcelain` / `head_commit` / `remove_worktree` / `prune_worktrees` / `list_worktree_paths`

---

## 1. Per-agent worktree → 合并回 issue 分支

### 1.1 拓扑

```
project repo (.git)
└─ issue/abcd1234-title              ← issue 集成分支 (base for agents)
   ├─ swarm/abcd1234-engineerA       ← agent A 的 worktree+branch (从 issue 分支 fork)
   ├─ swarm/abcd1234-engineerB
   └─ swarm/abcd1234-engineerC
```

每个并发 agent 一个 worktree + branch，base 都指向 **issue 集成分支**（不是 project default），跑完按某种策略依次合并回 issue 分支，issue 完成后再 `squash_merge` 到 default（已有 `merge_issue` 流程）。

### 1.2 git 层合并做法对比

| 做法 | 命令 | 适用 | 代价/坑 |
|---|---|---|---|
| **顺序 squash merge**（推荐基线） | 逐个 `git merge --squash <agentBranch>` 进 issue 分支，每个一条 commit | N 个 agent 改不同文件/不同区域 | 串行；第 2 个开始 base 已变，**必须先 rebase/检测分叉**否则 patch 不 apply 或冲突；任一冲突需暂停 |
| **顺序 three-way merge**（保留每 agent 历史） | 逐个 `git merge --no-ff <agentBranch>` | 想保留多分支历史图 | 同上需顺序；merge commit 多；冲突处理同 squash |
| **顺序 rebase**（线性化） | 每个 agent 分支 `git rebase issue` 后再 ff-merge | 想要线性历史 | 改写 SHA；rebase 中途冲突需逐 commit 解；vibe-kanban 即走此路（见 §3） |
| **Octopus merge** | `git merge branchA branchB branchC`（一条命令多 parent） | 多分支**完全无冲突** | git 的 octopus 策略**遇到任何需要手动解的冲突直接整体 abort**，不能解冲突；只适合"保证不冲突"的场景（如严格子目录划分），否则没用 |
| **Patch apply / format-patch** | `git format-patch` + `git am` 或 `git diff | git apply --3way` | 想跨仓/松耦合搬运 | `git apply` 默认严格，行号漂移就 fail；`--3way` 才回退三方合并；本质等价于 cherry-pick 但更脆 |
| **Cherry-pick** | `git cherry-pick <commits>` 逐 commit 搬到 issue 分支 | agent 产了干净的小 commit 序列 | 重复内容会冲突；vibe-kanban 提供 `abort_cherry_pick` 善后 |

**结论**：octopus 只在"保证零冲突"时可用；通用情况是**顺序应用（squash 或 rebase）+ 分叉检测 + 冲突即暂停**。

### 1.3 冲突处理的本质

并发 agent 改**同一文件同一区域** = 真冲突，git 无法自动解，只有三条路：
1. **预防**（最优）：调度层把任务按文件/目录划分，让 agent 物理上不碰同一文件（见 §2 子目录划分）。
2. **顺序 + 检测**：第一个 agent 先合，后续 agent 在合并前 `rebase` 到最新 issue 分支；冲突 → 把 conflicted files + 双方 diff 喂回一个 LLM（merge-resolver agent）让它产出解，或转人工 review（本仓库已有 `awaiting_review` / Approvals 机制可复用）。
3. **整体 abort 重跑**：冲突就丢弃后到的 agent 改动，带着"已有人改了这些文件"的上下文重派。

---

## 2. 替代方案：共享 worktree + 协调

| 方案 | 机制 | 代价 |
|---|---|---|
| **文件级锁** | 每个 agent 写文件前抢一把锁（advisory lock / 内存锁表 / lockfile） | 实现复杂；agent 是黑盒 CLI（claude/codex 进程），**很难在它写文件的瞬间拦截**——锁粒度只能粗到"整个 task 串行"，等于退化成现状 |
| **子目录划分**（partitioning） | 调度时给每个 agent 划定只允许改的目录/文件集，物理隔离 | 干净、可配合 octopus；但需要前置能把任务拆成不相交文件集的"规划"步骤，且 agent 可能越界（需 hook/校验拦截越界写） |
| **串行写 + 并行读** | 多 agent 并行"读/规划/产 diff"，但实际落盘串行 | 失去并行落盘的收益；适合"并行分析、串行实施"模式 |
| **共享 worktree 直接并行写**（现状若强行并行） | 无隔离 | **会互相覆盖未提交改动 + git index 竞争**，`git add -A`/commit 会把别人半成品也带上；不可行 |

**代价总结**：共享 worktree 系方案要么退化成串行（锁），要么需要昂贵的前置任务划分（子目录），要么牺牲并行落盘。Per-agent worktree 是隔离最彻底、与现有原语最契合的方向。

---

## 3. 业界 AI coding 工具怎么做

### 3.1 vibe-kanban（本仓库 `references/vibe-kanban/`，**最直接可借鉴的生产实现**）

这是一个并行跑多 task 的 agent 编排器，做法就是 **per-task worktree + branch**：

| File Path | 说明 |
|---|---|
| `references/vibe-kanban/crates/worktree-manager/src/worktree_manager.rs` | 每 task 一个 worktree；`WORKTREE_CREATION_LOCKS: HashMap<String, Mutex>` **per-key 锁防并发建同一 worktree 竞争**（与本仓库 `worktree_manager._locks` 模式一致，L16-17 / 49-64） |
| `references/vibe-kanban/crates/git/src/lib.rs:575` `merge_changes` | task 分支合并回 base 的核心 |
| `references/vibe-kanban/crates/git/src/lib.rs:1082` `perform_squash_merge` | **in-memory 合并**，`merge_opts.fail_on_conflict(true)`，`index.has_conflicts()` → 返回 `MergeConflicts{conflicted_files}`，**不触碰工作树**（L1091-1103） |
| `references/vibe-kanban/crates/git/src/cli.rs:646` `merge_squash_commit` | base 已 checkout 时走 CLI：`checkout base` + `merge --squash --no-commit` + `commit`（L653-656） |
| `references/vibe-kanban/crates/git/src/lib.rs:1129` `rebase_branch` / `cli.rs:527` `rebase_onto` | task 分支 rebase 到新 base，含 `is_rebase_in_progress` 守卫、`abort/continue/quit_rebase` 善后 |

**关键设计点（直接抄）**：
1. **合并前分叉守卫**（`lib.rs:587-596`）：`merge_changes` 先 `get_branch_status`，若 **base 比 task 分支还 ahead（task_behind > 0）就拒绝合并**，报 `BranchesDiverged`——逼调用方先 rebase。这正是 §1.2"第 2 个开始 base 已变"问题的处理方式。
2. **两条合并路径**：base 分支被某 worktree checkout 着 → 走 CLI squash；没被 checkout → 走 libgit2 纯 ref 操作（in-memory，不需要工作树）。本仓库 `squash_merge` 用的是"临时 detach worktree"折中方案，等价于前者但更省心。
3. **冲突 = 结构化错误**：`MergeConflicts { conflicted_files }` + `get_conflicted_files`（`diff --name-only --diff-filter=U`），把冲突文件列表抛给上层决策（人工/再派 agent）。
4. **合并后把 task 分支 ref 也指向 squash commit**（`lib.rs:660-668`），让后续在该分支上继续工作不再冲突。

### 3.2 其他工具（领域知识，未在本仓库验证）

- **Conductor / Crystal / 各类 "git worktree based swarm" 工具**：清一色 per-agent/per-task `git worktree`，每个 agent 一个分支，UI 里逐个 review diff 后合并。这是当前并行 agent 编排的事实标准模式。
- **Devin（多 Devin 并行）**：每个 Devin 实例独立工作空间 + 独立分支，最终各自开 PR，由人或上层在 PR 层面解决冲突——本质是"每 agent 一个分支 + PR 合并队列"。
- **OpenHands（前 OpenDevin）**：单 agent 在一个 sandbox 工作区；并行更多是多个独立 session/runtime 各自隔离的容器+工作目录，而非共享工作树。
- **aider**：单进程、单工作树，靠 repo map + 每次编辑后自动 commit 来保证可追溯；**不是并行编辑模型**，并行要在外层起多个 aider 各管一个分支。
- **Claude Code subagents**：subagent 共享同一文件系统/工作目录、串行交还控制权，**本身不做文件系统隔离**——并行隔离要靠外层 worktree（即本任务要做的事）。

**共识**：业界没有"共享工作树 + 细粒度文件锁让多 agent 同时写"的成熟方案；隔离统一靠 **per-agent worktree/branch**，合并统一靠 **顺序 squash/rebase + 分叉检测 + 冲突上抛（人工或再派 agent）**。

---

## 4. 基于现有 git_service 的最简可行实现

现有原语**已经够用**，几乎不用加新 git 函数。建议在 `worktree_manager.py` 加一层 swarm 编排（不改 git_service）：

### 4.1 起 N 个 agent worktree

复用 `git_service.create_worktree`，base 用 **issue 分支**而非 default：
```
# 伪代码，放进 worktree_manager 新方法 prepare_agent_worktree(issue, agent_key)
branch  = f"swarm/{issue.id[:8]}-{agent_key}"
path    = _worktree_path(project, "swarm", f"{issue.id}-{agent_key}")
await git.create_worktree(repo_path=project.repo_path,
                          branch=branch,
                          worktree_path=path,
                          base_branch=issue.git_branch)   # ← fork 自 issue 集成分支
```
- 用现有 `self._locks` 模式 key=`swarm:{issue.id}:{agent_key}` 防并发建同名竞争（与 vibe-kanban `WORKTREE_CREATION_LOCKS` 同构）。
- `task_dispatcher.py:125-128` 这里要改成注入 **agent worktree path** 而非 issue worktree path（否则还是共享踩踏）。

### 4.2 合并回 issue 分支（顺序）

跑完后，**串行**逐个把 agent 分支合进 issue 分支，每个合并前用现有原语检测分叉：
```
async with self._lock_for(f"issue:{issue.id}"):          # 序列化所有 merge-back
    for agent_branch in agent_branches:
        # 1. 落盘 agent 未提交改动
        await git.commit_all(agent_worktree, f"chore: agent {k} changes")
        # 2. 分叉检测（issue 分支可能已被前一个 agent 推进）
        behind = await git.commits_behind(agent_worktree, issue.git_branch)
        if behind > 0:
            # issue 分支已前进 → 需要先把 agent 分支 rebase/merge 到最新
            #   现有 git_service 没有 rebase 原语，最简做法：
            #   直接用 squash_merge，它内部在临时 worktree 做 merge --squash，
            #   冲突会 reset+raise GitError（见 git_service.py:269-273）
        # 3. squash 合并进 issue 分支
        try:
            sha = await git.squash_merge(
                repo_path=project.repo_path,
                source_branch=agent_branch,
                base_branch=issue.git_branch,     # ← 合进 issue 分支，不是 default
                message=f"merge agent {k}: ...")
        except GitError as e:        # 冲突 → 上抛
            # 走现有 awaiting_review / Approvals 让人解，或再派 merge-resolver agent
```
- **`squash_merge` 已经是"在临时 worktree 做 merge --squash、冲突 reset+raise"** —— 正好满足"冲突即暂停、不留半成品"的需求，且不碰 issue worktree 工作树。
- 第二个 agent 开始 `squash_merge` 的 base（issue 分支）已被前一个推进，git 的 `merge --squash` 会做三方合并：**不冲突就自动合，冲突就 raise**。所以**严格顺序 + 现有 squash_merge 就能覆盖大部分情况**，无需额外 rebase 原语。

### 4.3 冲突兜底（需补的最小能力）

`git_service.squash_merge` 冲突时只 raise `GitError`，**不返回 conflicted_files 列表**。要做 LLM/人工解冲突，需补一个轻量原语（参考 vibe-kanban `get_conflicted_files`）：
```
# git diff --name-only --diff-filter=U
async def conflicted_files(worktree_path) -> list[str]: ...
```
然后冲突时把文件名 + 双方 diff（用现有 `worktree_diff`）喂给 merge-resolver agent 或 Approvals 页。

### 4.4 清理

复用 `git_service.remove_worktree` + `prune_worktrees`，agent worktree 合并完即删（`worktree_manager._cleanup_path` 模式）。

### 4.5 最简实现清单

| 动作 | 用现有 | 需新增 |
|---|---|---|
| 起 N agent worktree | `git.create_worktree`（base=issue 分支） | `worktree_manager.prepare_agent_worktree` 包一层 + 改 dispatcher 注入 agent path |
| 落盘 | `git.commit_all` | — |
| 分叉检测 | `git.commits_behind` / `commits_ahead` | — |
| 顺序合并回 issue 分支 | `git.squash_merge`（冲突 reset+raise） | 编排循环（在 issue 锁内串行） |
| 冲突文件列表 | — | `git.conflicted_files`（一行 `diff --diff-filter=U`） |
| 冲突上抛 | 现有 `awaiting_review`/Approvals | 接线 |
| 清理 | `git.remove_worktree` / `prune_worktrees` | — |

---

## Caveats / Not Found

- **exa MCP 工具不可用**：本环境未挂载 `mcp__exa__*`，§3.2 中 Devin/OpenHands/aider/Claude Code 的描述基于领域知识、**未经在线源逐条核实**；§3.1 vibe-kanban 与 §0/§4 本仓库的描述均有 file:line 佐证。
- **`git_service` 无 rebase 原语**：当前只有 squash/merge/diff/commit。§4.2 论证了"严格顺序 + squash_merge 三方合并"可绕开显式 rebase；若要"保留每 agent 历史/线性化"则需照 vibe-kanban `rebase_onto`（`cli.rs:527`）补 `git rebase --onto` 封装，本研究未实现。
- **`prepare_issue_worktree` 的串行假设是硬编码语义**（`worktree_manager.py:1-6`），不只是注释——整个 dispatch 链（`task_dispatcher.py:125`）都按"一个 issue 一个 worktree"注入 cwd。并行化需同时改 worktree_manager + dispatcher，单改一处不够。
- **agent 越界写**：子目录划分方案依赖 agent 不写划定范围外的文件，本仓库现有 `worktree_claude_hooks`（`inject_worktree_claude_hooks`）是潜在的拦截点，但是否能拦写未核实。
