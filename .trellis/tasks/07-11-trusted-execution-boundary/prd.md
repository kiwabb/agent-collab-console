# 可信执行边界与真实验收闭环

## Goal

把当前项目从“能运行 Agent 流程的本地控制台”收敛为“默认仅本机可达、所有副作用有明确授权、所有完成态有独立证据”的可信本地产品。修复上一轮审计确认的网络暴露、任意 Shell、环境密钥继承、QA 自报通过、Benchmark 假执行以及 secret 密文物化问题。

## What I Already Know

* 产品当前定位是 local-first，真实 CLI 会读写本地仓库并使用本机凭据。
* 推荐启动路径中 Next dev 未指定 hostname；当前安装版本默认监听 `0.0.0.0`，并把 `/api/*` 代理到本机 FastAPI。
* FastAPI REST/WS 当前没有本地会话令牌、Host/Origin 校验或统一 actor 身份。
* `Project.run_command` 可经 API 原样持久化，再由 `create_subprocess_shell` 执行；过滤器是少量黑名单，子进程继承绝大多数后端环境变量。
* `REAL_CLI=true` 不会启用 QA 命令执行；`QA_EXECUTE_COMMANDS` 默认 false，未执行时 LLM 自报状态仍可保留。
* `blocked` / `needs_follow_up` QA 当前可保持任务 `done`；Conductor 终态门禁检查节点状态/角色，不检查真实命令证据。
* Benchmark fixture 声明了 pinned commands，但真实执行器只读取普通 execution-process 退出码；前端不发送真实运行所需的 project/workspace。
* secret env value 保存前加密，store 原样返回，物化 `.env` 前未解密。
* 工作区已有项目启动配置 WIP；本任务必须在当前内容上增量修改，不回退用户改动。

## Requirements

### 1. Strict Local Trust Boundary

* 推荐开发启动必须显式把 backend 和 frontend 绑定到 `127.0.0.1`。
* Docker 端口必须只发布到 loopback，且必须配置非空 `CONSOLE_AUTH_TOKEN`。
* `dev-local.sh` 在调用方未提供 token 时生成高熵、进程生命周期内有效的 token，并同时传给前后端。
* 后端所有 `/api` REST 入口必须校验本地 token；仅允许最小健康检查匿名访问。
* 所有 WebSocket 在 `accept()` 前校验 token、Host 和 Origin。
* Host 只允许 loopback 名称/地址；Origin 只允许配置的本机 frontend origin。任何校验异常必须 fail closed。
* 前端通过同源、no-store 的 server route 获取 token，并由共享 API/WS transport 自动携带；业务组件不得各自拼认证逻辑。
* 测试绕过只能通过显式 test-only 配置启用，真实 CLI 模式下不得关闭认证。

### 2. Side-Effect Capability Boundary

* Project run 不再把任意字符串交给 shell；解析为受限 argv 和受限 cwd，再使用 `create_subprocess_exec`。
* 允许常见 dev-server 命令和安全的 `cd <relative> && <command>` 兼容形态；拒绝管道、重定向、命令替换、后台执行、绝对 cwd 越界、解释器 inline-code 等绕过。
* 子进程环境改为最小 allowlist；模型 key、云凭据、SSH agent、console token、数据库路径不得继承。
* 安全拒绝必须返回稳定 reason，写审计记录，并在前端保持原有数据与显示明确错误。
* 本任务保持“可信用户运行可信本地仓库”的产品边界；不把它宣传为可运行恶意仓库的沙箱。

### 3. Verified Completion Semantics

* Issue 增加一等公民的 `acceptance_criteria` 与确认状态；创建 API 和主要创建 UI 支持用户输入/确认。
* QA 命令在真实 CLI 模式下默认启用，但只能通过窄 allowlist、argv 执行、受限 cwd 和总时限运行。
* QA 执行被关闭、没有命令、全部命令被拒绝/超时，或证据无法读取时，报告必须是 `unverified`，任务不得成为 success status。
* `blocked`、`needs_follow_up`、`unverified` 均不得保持 `done`，不得通过 Conductor finalize success gate。
* 成功 finalize 必须有 verification role 的可审计通过证据；仅节点完成或 LLM 自报 `passed` 不足以完成。
* 用户未确认 acceptance criteria 时，系统可以规划/执行，但不得进入 verified completion。

### 4. Real Benchmark Execution

* RealConductorExecutor 必须在该 epoch 的隔离 issue worktree 中执行 fixture 的 pinned checks，并以这些结果作为 execution score。
* Pinned checks 必须使用结构化 argv/cwd；不通过 shell 执行检查字符串。
* runner 必须保存实际命令、exit code、stdout/stderr 摘要、duration；无检查结果按失败处理。
* 前端关闭 Dry Run 时必须选择并发送 project/workspace；缺失时前端禁止提交，后端也必须拒绝，不能静默回退 FakeExecutor。
* Dry Run 结果必须明确标识为 synthetic，且不得被设为真实 baseline。

### 5. Secret Materialization

* secret 只以密文持久化、只在即将物化/启动的边界解密。
* 解密失败或 encryption key 缺失时必须拒绝启动，不得写 ciphertext、空值或部分 `.env`。
* REST 读取永不返回 plaintext secret；日志、审计和异常不得包含 plaintext/ciphertext。

### 6. Documentation and Release Guard

* README 明确产品为 strict local-only、token 获取方式、手动启动要求、Docker 要求和不支持的部署形态。
* 增加一个轻量 release/security smoke，覆盖匿名拒绝、恶意 Host/Origin、WS Origin、命令绕过、QA unverified 和 secret 物化。
* 现有 CI 继续跑单元/类型/构建；真实付费 Benchmark 作为显式人工 release gate，不在普通 CI 自动消费模型预算。

## Acceptance Criteria

* [x] `dev-local.sh` 启动的 4000/9000 仅监听 loopback，浏览器功能正常。
* [x] 未携带 token 的受保护 REST 返回 401；错误 token 返回 401；合法 token 正常。
* [x] 非 loopback Host 和非允许 Origin 返回 403；WebSocket 在 accept 前拒绝。
* [x] Docker compose 不再把 4000/9000 发布到所有网卡，缺 token 时配置失败。
* [x] `python -c`、`sh -c`、重定向、命令替换、越界 cwd 等 project run 输入均被拒绝且没有创建进程。
* [x] 合法的 npm/pnpm/docker compose/项目脚本启动仍通过 argv 执行；停止和日志行为不退化。
* [x] project child env 不包含 console token、模型 API key、SSH agent 或数据库配置。
* [x] QA disabled/no-command/all-refused/timeout 均产生 `unverified` 或非成功任务状态，Conductor 无法 finalize done。
* [x] 真实通过/失败命令分别产生 verified pass / failed，并驱动 rework/finalize。
* [x] 未确认 acceptance criteria 的 issue 不能 verified finalize。
* [x] 真实 Benchmark 执行 fixture pinned argv；缺 project/workspace 返回 422/409，不再 Fake fallback。
* [x] Dry Run 带 synthetic 标记，不能设为 baseline。
* [x] secret 保存后 materialize 得到原始 plaintext 值；DB/API/日志仍不泄漏 plaintext。
* [x] 相关 backend tests、frontend tests、lint/typecheck 以及针对性启动/HTTP smoke 通过。

## Definition of Done

* 安全、QA、Benchmark、env 四条跨层链路都有失败路径和成功路径测试。
* 没有通过 test-only 默认值削弱生产行为；真实 CLI 与 Docker 配置 fail closed。
* 当前用户 WIP 被保留，未做无关重构。
* README、环境变量说明和 Trellis spec 记录新契约。
* 完成审计逐条对照本 PRD，不以“测试没发现问题”替代正向证据。

## Technical Approach

采用“严格本机控制面 + 认证 capability broker + 证据驱动终态”的分层方案：

```text
same-origin browser
  -> local token + Host/Origin gate
  -> typed REST/WS control plane
  -> argv/cwd/env capability boundary
  -> local process/worktree
  -> immutable verification evidence
  -> verified completion gate
```

前端认证集中在共享 fetch/WS helper；后端认证集中在 middleware/WS guard；命令解析和最小环境集中在 application helper。QA 与 Benchmark 复用结构化检查执行器，但 model-proposed QA commands 和 checked-in benchmark commands维持不同信任来源与策略。

## Decision (ADR-lite)

**Context**: 当前架构既不能安全暴露为团队服务，也无法安全地执行足够真实的验收命令；关闭执行后又错误地把自报状态当作成功。

**Decision**: 本轮选择 strict local-only，而不是引入 OAuth/RBAC 多用户。以 loopback + ephemeral token + Host/Origin 为身份边界，以 argv/cwd/env capability 为副作用边界，以真实 evidence 为完成边界。

**Consequences**: 手动启动和 Docker 必须提供 token；部分自由 Shell run command 会被拒绝并需要改成受支持形态。项目仍不承诺隔离恶意仓库；未来团队模式必须另加用户身份、RBAC、持久 session 和 OS/container sandbox。

## Out of Scope

* OAuth、SSO、组织/团队、多用户 RBAC。
* 允许公网或局域网部署。
* 通用恶意代码沙箱、容器编排平台或远程 worker。
* 自动在普通 CI 中运行付费多 epoch Benchmark。
* 与本任务无关的 UI 重设计和存储层拆分。

## Research References

* [research/trusted-execution-design.md](research/trusted-execution-design.md) - 当前证据、可选架构与收敛理由。

## Technical Notes

* 重点代码：`backend/app/main.py`、`interfaces/{api,codex_ws,ws_events}.py`、`project_run_manager.py`、`qa_workflow.py`、`conductor_tools.py`、`backend/benchmark/*`、`env_materializer.py`、frontend shared API/WS transports。
* 当前 frontend project startup config 文件有未提交用户改动，修改前必须重新读取并做增量补丁。
* `QA_EXECUTE_COMMANDS=true` 不能先于安全 argv runner 单独打开。
