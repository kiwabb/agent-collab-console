# 云开发环境：env / 密钥引导机制

> 调研对象：Gitpod、GitHub Codespaces、devcontainer、Replit、Coder、Daytona
> 目的：遇到缺失 env / secret 时如何感知、如何引导用户填写

## 1. Replit Secrets（最贴合"前端展示 + 用户填写"诉求）
- **自动感知**：静态扫描代码里的 `os.environ[...]` / `process.env.X`，
  检测到未定义的密钥引用时，UI 主动提示"你引用了未设置的 secret"。
- **模板驱动**：`.replit` 里可声明模板需要的 secret 清单；fork 项目时 UI
  自动列出待填字段（含描述 / 占位符），用户填完才能跑。
- **UX 关键**：值输入后即遮蔽（masked），仅显示 key 名；secret 与普通 env
  分离存储。

## 2. Gitpod / Codespaces（"缺失即引导"）
- Codespaces 遇到 devcontainer 声明的 `secrets` 缺失时，**在创建流程内嵌
  一个填写表单**，附 `documentationUrl` 链接说明用途。
- 都区分三层：
  - **默认值可跑** — 写进 devcontainer
  - **推荐配置** — `.env.example` 提示
  - **必填密钥** — 引导填写

## 3. `.env.example` 通用约定（跨产品一致）
- 几乎所有工具都认 `.env.example` 作为"需要哪些变量"的事实标准：
  key 齐全、value 留空或占位。
- 标准引导：检测到有 `.env.example` 但无 `.env` → 提示"复制并填写"。

## 对本项目的直接建议
1. **感知层**：静态扫码提取 env 引用 + 解析 `.env.example` 求并集，
   得到"必填 / 可选 / 默认"三态清单。
2. **展示层**：前端按 key 渲染表单，可推断默认值预填、密钥字段遮蔽、
   附用途说明。
3. **启动策略**：有默认值 → 可直接跑；必填缺失 → 阻断并高亮；
   参考 Codespaces「创建流程内嵌表单」把填写点前置到启动前。
4. **落盘**：用户填写 → 生成 `.env`（非 `.env.example`），敏感值遮蔽存储。
