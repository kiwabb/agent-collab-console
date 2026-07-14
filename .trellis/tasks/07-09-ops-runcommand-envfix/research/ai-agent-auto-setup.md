# AI coding agent：项目自动装配 / 缺配置修复

> 调研对象：Devin、Replit Agent、aider、Cursor / Copilot Workspace、Cline
> 目的：agent 遇到"项目跑不起来、缺配置"时如何修

> **关键洞察**：没有一个成熟产品让 AI 凭空捏造并静默写入 secret 值——
> 这与本项目 Operations Engineer 的设计红线一致。

## 四种主流模式

### 1. 感知-申报-等待填写（Replit Agent 最典型）
Agent 静态扫描代码提取 env 引用 → 检测缺失 → 在 UI 申报"需要这些变量"
并**暂停等用户填**，而非猜值。密钥字段遮蔽输入。

### 2. `.env.example` 作为契约（aider / Cline）
Agent 优先读 `.env.example` 确定"需要什么"，据此生成 `.env` 骨架
（值留空或占位），**从不填真实凭据**。

### 3. 崩溃-读日志-自愈循环（Devin）
Agent 真跑命令 → 捕获失败日志 → 解析缺失变量 → 修复可推断的
（端口 / host / 路径），**但遇到 secret 类必填项就停下来问人**。
→ 与本项目 `qa_workflow` 真跑命令、`verify_project_launch` 探活思路同源。

### 4. 可推断 vs 必须问人的二分法（所有产品共识）
- **可自动填**：端口、host、`NODE_ENV`、路径、URL base
  —— 有合理默认、非敏感
- **必须问人**：API key、token、DB 密码、第三方凭据
  —— 无法推断、敏感

## 对本项目的直接建议
- Operations Engineer 生成 `.env` 时应**只填可推断的非敏感默认值**
  （`APP_PORT=8080` / `BACKEND_HOST=0.0.0.0`），secret 项留空 + 标记 required。
- 采纳 Devin 式**结构化区分**：把缺失变量分成 `auto_filled` 和
  `needs_user_input` 两类返回，前端据此决定"直接启动"还是"等填写"。
- `.env.example` 缺失时（VideoNote 正是如此），Agent 应从 compose `${VAR}`
  + README + `backend/.env.example` **推断出变量清单**，生成一份带默认值的
  `.env` 骨架。
- 落盘遵循幂等 + 不覆盖 + 不写 secret 值的红线（与已有 `command_safety` 一致）。
