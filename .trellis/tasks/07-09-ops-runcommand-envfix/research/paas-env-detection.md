# PaaS / 部署平台：环境变量探测与提示机制

> 调研对象：Vercel、Netlify、Railway、Render、Coolify、Dokku
> 目的：部署时如何探测所需 env、如何提示用户填、required vs 默认值如何区分

## 三种"探测所需 env"的技术路线

### 1. 框架预设注入（Vercel / Netlify）
不解析用户代码找变量，而是按检测到的框架自动注入构建期系统变量
（`VERCEL=1`、`URL`、`COMMIT_REF` 等）。业务 env 靠用户自己声明。

### 2. 运行时崩溃反馈（Railway / Render）
不做静态探测，让服务启动失败后从日志暴露缺失变量。
Railway 用 `${{...}}` 引用语法在部署前做**引用完整性校验**：引用了不存在
的变量会阻断部署。

### 3. Compose / Dockerfile 解析（Coolify / Dokku）
Coolify 解析 `docker-compose.yml` 的 `${VAR}` 和 `${VAR:-default}`，
**自动提取为可编辑的 UI 字段并回填默认值**。
→ 与本项目 Operations Engineer 解析 compose 的思路最接近。

## required vs 默认值区分（对本项目最有借鉴价值）

- **Bash 风格默认值语义**（Compose 原生支持）：
  - `${VAR:-default}` — 未设或空时用默认（= 可选带默认）
  - `${VAR:?error}` — 未设则报错并阻断（= 必填）
  - `${VAR}` — 未设为空（= 可选无默认 / 隐式必填）
  这是"必填 vs 可选带默认"最成熟的声明式表达。
- **敏感值处理**：Railway sealed variables、Render `sync: false`、
  Netlify secrets scanning —— 敏感值不回显、不写入产物。
- **Render Blueprint `generateValue: true`**：声明式让平台自动生成随机值
  （如密钥），用户无需填写。

## 对 Operations Engineer 的直接建议

1. 解析 compose 时同时识别 `${VAR}` / `${VAR:-default}` / `${VAR:?err}`
   三种语法，据此判定 required / optional / default。
2. 缺失变量时优先采用 **Coolify 模式**：提取为结构化清单 + 回填可推断默认值，
   而非直接崩溃。
3. 敏感变量应支持"生成默认值"或"标记必填且不回显"，
   参考 Render `generateValue` 与 Railway sealed。
4. 借鉴 Railway 的**引用完整性预校验**：启动前先验证 compose 引用的所有变量
   都能被解析（有值或有默认），避免运行时才发现。
