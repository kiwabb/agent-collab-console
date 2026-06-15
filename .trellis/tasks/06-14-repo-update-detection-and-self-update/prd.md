# 项目仓库远程更新检测与 fast-forward 同步

> **追加范围 (2026-06-14)：项目一键启动 dev server**
> 同一分支内追加「一键启动项目运行命令」功能（与远程更新检测同属 ProjectWorkspacesPage 增强）。
> - **配置**：Project 新增持久字段 `run_command`（在 setup_script 旁编辑；默认在 repo_path 执行）。
> - **运行器**：精简 in-memory `ProjectRunManager`（不持久化，后端重启即停，启动时杀残留）。每项目单实例；`asyncio.create_subprocess_shell` + 独立进程组（`start_new_session`），stop 时 `killpg`(term→grace→kill)；两个 reader task 把 stdout/stderr 打 tag 进有上限的 ring buffer(带单调 seq)。命令复用 QA `_refuse_reason` 安全过滤（拒 rm -rf/sudo/git push 等）；env 沿用 worktree 同款白名单(去掉 CODEX_*/SQLITE_DB_PATH)。
> - **端点**：`POST /api/projects/{id}/run/start`(404 / 409 reason∈no_run_command|already_running|refused / 200 status)、`POST .../run/stop`(幂等)、`GET .../run/status`、`GET .../run/logs?after=<seq>`。app 关停 hook 杀全部。
> - **前端**：ProjectsPage 加 `RunCommandCard`(仿 SetupScriptCard) 配置命令；ProjectWorkspacesPage 工具栏加「启动项目/停止」按钮(运行态绿点) + 可折叠日志面板(运行中每~2s 轮询 `run/logs?after=seq` 增量追加、自动滚动)；未配置 run_command 则按钮禁用并提示去配置。i18n 中英双写。
> - **Out of scope**：WS 实时流(用轮询)、进程持久化/跨重启恢复、多实例、自动重启。

## Goal

让用户在 Console 里直接看到每个被管理的 **project 仓库** 是否落后于其远程默认分支，并在可安全 fast-forward 时一键拉取更新——无需切到终端手动 `git fetch/pull`。当前 `GET /api/projects` 只返回静态信息，用户无从得知 origin 上是否有新提交。

## Scope（已与用户确认）

- **针对对象**：被 Console 管理的 project 仓库（`Project.repo_path`），**不是** console 自身。
- **更新方式**：**仅 fast-forward**。工作区干净 + 当前在默认分支 + `ahead==0 && behind>0` 才允许 pull；否则拒绝并给出原因，绝不 stash / 不 force / 不丢改动。
- **UI 入口**：ProjectsPage 项目卡片头部 —— 分支行展示「落后 N / 最新」徽章，头部按钮组加「检查更新」+「同步」。
- **自动检测**：定时轮询（进入项目页后台 fetch，默认每 5 分钟一次；进页时立即跑一次）。

## Requirements

### 后端
- `git_service.py` 新增（均接受任意 `repo_path`，复用现有子进程/白名单/审计模式）：
  - `fetch(repo_path, remote="origin", branch=None, timeout=60)` —— `git fetch` 更新远程跟踪分支。
  - `remote_status(repo_path, branch)` 或在端点内组合：`behind = rev-list --count {branch}..origin/{branch}`、`ahead = rev-list --count origin/{branch}..{branch}`、`status --porcelain` 判脏。
  - `fast_forward(repo_path, branch, remote="origin")` —— `merge --ff-only origin/{branch}`，返回新 HEAD SHA；不可 ff 时抛错（不留中间态）。
- 新端点：
  - `GET /api/projects/{project_id}/remote-status?fetch=true|false`
    → `{ branch, behind, ahead, can_fast_forward, dirty, current_branch, has_origin, fetched, fetched_at, error }`
    - `fetch=true` 先 `git fetch` 再算；`fetch=false` 用本地已有远程跟踪分支快速算（轮询省网络可按需）。
    - 无 origin / 非 git repo / fetch 失败 → 不抛 500，返回结构里带 `error`、`has_origin=false`。
  - `POST /api/projects/{project_id}/pull`（fast-forward）
    → 成功 `{ success:true, new_sha, behind_before, branch }`；不可 ff → `409` + `{ success:false, reason }`（reason ∈ dirty / diverged / not_on_default / no_origin / already_up_to_date）。
- 安全前置：pull 前重新校验 `current_branch == default_branch && clean && ahead==0 && behind>0`，条件不满足直接拒绝（不信前端传来的状态）。

### 前端
- `lib/api.ts` 新增 `getProjectRemoteStatus(projectId, {fetch})` 与 `pullProject(projectId)`，走现有 `handleResponse`。
- `types.ts` 新增 `ProjectRemoteStatus` 接口。
- ProjectsPage 项目卡片：
  - 分支行旁徽章：`检查中…` / `落后 N` / `最新` / `本地有改动` / `已分叉` / `无远程`。
  - 头部按钮组：「检查更新」（强制 `fetch=true` 刷新）、「同步」（仅 `can_fast_forward` 时可点，调用 pull，成功后刷新徽章 + toast）。
- 定时轮询 hook：复用现有 `setInterval` 模式（ConductorMonitorPage/AppStatusBar 同款），进入项目页立即跑一次 `fetch=true`，之后每 5 分钟一次；卸载清理。并发对「当前可见/选中项目」做即可，避免对所有 project 同时 fetch。
- i18n：在 `lib/i18n.ts` 的 `zh-CN` 与 `en-US` 同步加 `project.update.*` 键（badge 文案、按钮、toast、各 reason）。

## Acceptance Criteria

- [ ] 后端 `GET /remote-status` 对「落后于 origin」的 repo 返回 `behind>0, can_fast_forward=true`；对干净最新 repo 返回 `behind=0`。
- [ ] `dirty` / `ahead>0`（已分叉）/ 不在默认分支 / 无 origin 各场景 `can_fast_forward=false` 且 reason 正确，端点不 500。
- [ ] `POST /pull` 在可 ff 时成功推进 HEAD 并返回新 SHA；脏树/分叉时返回 409 且**仓库未被改动**（无 stash、无丢失）。
- [ ] 前端项目卡片显示正确徽章；「同步」仅在 `can_fast_forward` 时可点；点完徽章刷新为「最新」。
- [ ] 进入项目页自动 fetch 一次并展示状态；5 分钟轮询生效；离开页面清理 interval。
- [ ] 后端单测覆盖 git_service 新方法（用临时 git repo fixture：构造落后/分叉/脏树三态）与端点；前端测试覆盖 api + 卡片状态渲染。
- [ ] `cd backend && python3 -m pytest -v` 与 `cd frontend && npm test` 全绿；`npm run lint` 通过。

## Definition of Done

- 后端/前端单测新增并通过；lint/typecheck 绿。
- 行为变更已在 README 或 CLAUDE.md 简述（新增端点 + 入口）。
- 失败路径（网络断、无 origin、脏树）均有用户可见的明确提示，不静默。

## Technical Approach

- 复用 `git_service` 现有子进程封装与参数白名单；新增 `fetch/fast_forward` 与一组 rev-list 计数。
- 端点放在 `api.py` 现有 `/api/projects/{id}/...` 资源组下，与 `branches`/`stats`/`repair` 并列。
- pull 采用 `git -C <repo> merge --ff-only origin/<branch>`，**仅当 repo 当前 checkout 在默认分支**（issue 用独立 worktree，主 repo 常驻默认分支，符合现状）；否则拒绝，避免把远程默认分支 ff 进无关分支。
- 轮询只针对选中/可见项目，`fetch=false` 的本地快速比较可用于卡片首屏，`fetch=true` 用于「检查更新」与定时刷新。

## Decision (ADR-lite)

**Context**：用户需知道 project 仓库是否落后远程并能就地更新；现有 API 无远程对比、git_service 无 fetch/pull。
**Decision**：新增 git_service `fetch/fast_forward` + 两个 project 端点；UI 落在项目卡片头部徽章 + 检查/同步按钮；定时轮询自动检测；更新严格限定 fast-forward。
**Consequences**：安全（绝不动用户改动），但脏树/分叉时只能提示无法自动更新，需用户手动处理——可接受。未来可扩展：批量检查所有项目、stash 选项、console 自更新（本期 Out of Scope）。

## Out of Scope

- console 自身仓库的自更新。
- 非 fast-forward 的合并 / rebase / stash 自动恢复 / force pull。
- 推送（push）、远程管理（add/set-url remote）。
- 跨所有项目的批量「全部更新」一键操作（先做单项目；轮询也只针对可见项目）。
- 更新后自动重启服务（dev 下 `--reload` / `next dev` 自动热重载，无需处理）。

## Technical Notes

- Project 模型：`backend/app/domain/models.py:94-108`（`repo_path` 绝对路径、`default_branch`、`origin_url`）。
- 端点注册：`backend/app/interfaces/api.py`（`/api/projects/...` 资源组，`branches` 在 921-929、`stats` 932-963、`repair` 236-239 附近）。
- git_service：`backend/app/application/git_service.py`（`default_branch` 168-186、`status_porcelain` 516-520、`head_commit` 511-514、`commits_behind` 566-578；**缺 fetch/pull**）。
- 前端落点：`frontend/src/features/projects/ProjectsPage.tsx`（卡片头部按钮组 334-365、分支展示 371-372；60s tick 模式 125-128）。
- API 封装：`frontend/src/lib/api.ts`（project 函数 186-244、`handleResponse`）；类型 `frontend/src/lib/types.ts`。
- 轮询参考：`ConductorMonitorPage.tsx:42-46`、`AppStatusBar.tsx:34-44`（15s setInterval）。
- i18n：`frontend/src/lib/i18n.ts`（`zh-CN`/`en-US` 双写）。
- origin 形如 `git@github.com:.../agent-collab-console.git`（SSH，fetch 走用户本地凭证）。
