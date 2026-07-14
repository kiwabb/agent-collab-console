# env schema / 校验生态：三态建模与暴露

> 调研对象：dotenv-safe、envalid、t3-env、znv、dotenv-linter、
> `.env.example` / `.env.schema` 约定、docker-compose env 处理
> 目的："必填 / 可选 / 默认"如何建模并暴露给用户

## 1. 三态建模的行业共识
所有主流工具（envalid、t3-env、znv、dotenv-safe）都用同一套模型：
- **必填**：无默认值 + schema 声明 → 缺失即报错
- **可选带默认**：`default` 字段 → 缺失时回填
- **可选无默认**：显式 `optional()` → 可为 undefined

→ 正好映射到"我不填用默认 / 我需要填等我填完"的交互。

## 2. 校验时机：fail-fast at startup
行业铁律是**启动即校验、缺失就中止并列出全部问题**（envalid / t3-env 都
一次性报告所有缺失项，而非逐个失败）。
→ `project_run_manager` 应在 spawn 子进程**之前**做一次 env 预检。

## 3. `.env.example` 是事实标准的 schema 载体
dotenv-safe 直接用 `.env.example` 作为"必填清单"—— 文件里列出的 key 就是
必填项。VideoNote 的 `.env.example` 缺失，正是它无法明确"需要哪些变量"的根因。

## 4. 结构化错误输出
envalid 的 `reporter` / t3-env 的 `onValidationError` 都把缺失项收集成
**结构化清单**（变量名 + 期望类型 + 描述），而非纯文本报错。
→ 这是"后端感知、前端展示"的关键：错误必须是机器可读的结构。

## 5. docker-compose 原生三态语法
- `${VAR}` → 未设为空
- `${VAR:-default}` → 缺省值（可选带默认）
- `${VAR:?error}` → 必填（缺失中止）

VideoNote 的 compose 用了 `${APP_PORT}`（无默认），所以为空。
若改用 `${APP_PORT:-8080}` 即可自愈 —— 最轻量的修复方向之一。

## 对本项目的落地建议
1. **感知**：解析 compose 的 `${VAR}` / `${VAR:-default}` / `${VAR:?err}`
   + 读 `.env.example` 求并集，构建三态 env 清单。
2. **数据结构**：定义 `EnvVarSpec{name, required, default, description, secret}`，
   作为后端 → 前端契约。
3. **预检**：`project_run_manager` 启动前校验，缺失必填项则中止并返回结构化清单。
4. **前端**：按 spec 渲染表单，`required && !default` 高亮必填，`secret` 用密码框。
5. **落盘**：填写后生成 `.env`（幂等保护，不覆盖已有）。
