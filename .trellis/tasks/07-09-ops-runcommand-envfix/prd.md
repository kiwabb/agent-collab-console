# 运维工程师：Agent 驱动 .env 自举 + 确定性安全落盘

## Goal（一句话）

让**运维工程师 Agent** 看懂一个项目怎么启动，产出完整启动计划（含 env vars + 默认值 + 填写指引），**确定性代码层**只做安全校验 + 加密落盘 + 物化执行。彻底告别"裸 `docker compose up` + 撞 `env file .env not found`"。

## 方向修正（2026-07-09，VideoNote 走查后）

旧方案（`env_detection.py` 规则引擎）被否决，原因：

| 问题 | 旧方案（规则引擎） | 新方案（Agent 驱动） |
|---|---|---|
| 谁来理解项目怎么启动 | regex + 文件扫描 | Agent 读 README + compose + package.json + .env.example 综合推理 |
| 默认值推断 | 仅 Dockerfile ENV / .env.example 正则 | Agent 能从 README 里"访问 `http://localhost:3000`"推断 `APP_PORT=3000` |
| 遇到不规范项目（根 .env.example 缺失） | 哑火 | Agent 能弥补：从 backend/.env.example API_BASE_URL 里的 `:8000` 推断 `BACKEND_PORT` |
| 安全红线 | 同 | 同（规则校验层） |
| 维护成本 | 每遇到新格式加正则 | Agent prompt 迭代 |

**正确分工**：
- **Agent（运维工程师）** = 理解 + 判断：怎么启动、需要哪些 env、合理默认值、secret 标记
- **确定性代码** = 安全 + 落盘：校验不瞎编 secret、不覆盖用户手填值、加密存储、幂等物化 .env、命令安全过滤

## 背景 / 根因（已扒代码确认）

- VideoNote 的 `run_command = "docker compose up"` 来自确定性回退 `infer_project_script_suggestion()`（`:321-328`）：只要有 compose 就无脑吐命令，不检测 compose 是否依赖 `.env`。
- VideoNote `docker-compose.yml` 硬依赖根 `.env`（`env_file: - .env` + `${APP_PORT}/${BACKEND_PORT}/${BACKEND_HOST}` 插值）。
- VideoNote 根目录无 `.env.example`（README 第 99 行说 `cp .env.example .env` 但文件从未提交），只有 `backend/.env.example` 且不含那三个端口变量。
- README 第 108 行提到 `FRONTEND_PORT` / `BACKEND_PORT` 可在 `.env` 自定义——agent 能读到这个，规则引擎不能（变量名不在 regex 匹配范围）。
- README 第 120-122 行写了直接启动方式：`python3.11 -m venv venv && ./venv/bin/pip install -r requirements.txt && ./venv/bin/python main.py`，监听 `0.0.0.0:8483`——`BACKEND_PORT=8483` 的默认值来源，agent 能读到。

## 架构

```
运维工程师 Agent（项目启动时调用，或 Project 页 "生成启动方案" 按钮）
  ↓ 产出：启动计划 JSON（扩展 ProjectScriptSuggestion）
  {
    "run_command": "docker compose up",
    "setup_script": "",
    "access_url": "http://localhost:3000",
    "env_vars": [                                          ← 新增字段
      {"name": "APP_PORT", "value": "3000", "source": "inferred from README port mention"},
      {"name": "BACKEND_PORT", "value": "8483", "source": "inferred from README python main.py"},
      {"name": "BACKEND_HOST", "value": "0.0.0.0", "source": "docker networking convention"},
      {"name": "OPENAI_API_KEY", "secret": true, "value": null, "source": "LLM provider config"}
    ],
    "notes": ["Root .env.example is missing; created .env from inferred defaults."]
  }
  ↓
确定性规则层（系统代码）
  1. 校验：secret 类变量的 value 不能是 agent 瞎编的（value 必须为 null）
  2. 校验：run_command 不含危险操作（复用现有 command_safety）
  3. 合并：用户之前在 env 面板手填的值优先（不从 agent 覆盖）
  4. 加密：secret 值走 env_crypto 加密后存 project_env_vars 表
  5. 物化：非 secret 值 + 用户手填 secret → 写 .env 到项目根目录（幂等、gitignore 已含）
  6. 审计：物化 .env 时启动日志记一条
  7. 启动：调用 project_run_manager.start()
```

## 设计决策（ADR-lite）

### D1: Agent 扩展产出 env_vars

**Context**: 当前 `ProjectScriptSuggestion` 只有 `setup_script` + `run_command` + `access_url` + `notes`，没 env 信息。
**Decision**: 扩展 prompt + 模型，让 Agent 额外产出 `env_vars` 数组。每个 env var 含 `name`, `value` (null = 需用户填), `secret` (bool), `source` (agent 自述来源)。
**Consequences**: Agent 调用成本不变（同一次 LLM 调用多输出一个字段）；确定性 fallback `infer_project_script_suggestion` 不产出 env_vars（env_vars 为空时系统只校验 compose 是否缺 .env 并提示用户）。

### D2: 用户手填值永远优先

**Context**: 用户在 env 配置面板手动填的值不应被 agent 重新生成覆盖。
**Decision**: 物化 .env 时，`project_env_vars` 表中已存在的 key → 用表中值；表中没有的 key → 用 agent 推断值；agent 推断值也没有 → 阻断（secret 必填）或用空字符串（非 secret 可选）。
**Consequences**: 需要 `project_env_vars` 表作为 truth source；Agent 重新生成不影响已填值。

### D3: secret 绝不自动填值

**Context**: 全行业铁律。
**Decision**: agent 产出的 env_vars 中 `secret=true` 的项，`value` 必须为 null。确定性校验层二次确认：若 agent 给 secret 填了值 → 丢弃该值并记 warning 日志。`env_crypto` 加密存储用户手填的 secret。
**Consequences**: 安全红线守住；agent prompt 需明确指示"secret 类变量 value 必须为 null"。

### D4: .env 物化时机

**Context**: 要在启动前有 .env 但不想污染仓库。
**Decision**: `project_run_manager.start()` 调用前，先 `materialize_env_file(project_id, repo_path)` → 校验必填项 → 通过则启动。物化幂等：已有 .env 且内容与待写入一致则跳过。
**Consequences**: start 流程增加一个前置步骤；.env 已在 .gitignore 中，不会误提交。

### D5: 加密存储保留

**Context**: 旧方案建的 `env_crypto.py` 仍然有用。
**Decision**: 保留 `env_crypto.py`，用于 `project_env_vars` 表中 `secret=true` 的 value 列加密存储。`GET` 端点不回显 secret 明文。
**Consequences**: 需要建 `project_env_vars` 表 + CRUD。

## Requirements

1. **Agent 产出扩展**：运维工程师 prompt 增加 `env_vars` 输出要求，Agent 从 README/compose/.env.example/Dockerfile 综合推断
2. **确定性 fallback 不退化**：`infer_project_script_suggestion` 保持现有行为，不尝试产出 env_vars（避免规则引擎陷阱）
3. **project_env_vars 表**：`(project_id, name)` 唯一键，`value` 列存明文非 secret / 密文 secret，`secret` bool，`source` str
4. **物化 .env**：启动前从表 + agent 产出合并，写 `.env` 到项目根，幂等不覆盖
5. **校验阻断**：启动前检查，secret 类变量未填 → 返回结构化缺失清单，不启动
6. **env 管理端点**：`GET /projects/{id}/env`（列清单，secret 只回是否已设）、`PUT /projects/{id}/env`（保存单/多变量）
7. **前端 env 配置面板**：Project 页新增「环境配置」nav 项，常驻 key-value 管理表，secret 遮蔽，默认值预填

## Acceptance Criteria

- [ ] VideoNote：Agent 重新生成启动方案 → `env_vars` 含 `APP_PORT=3000`, `BACKEND_PORT=8483`, `BACKEND_HOST=0.0.0.0` → 启动前自动物化 `.env` → `docker compose up` 一把跑通
- [ ] 含 secret 的项目：secret 项的 `value` 为 null → 面板高亮必填 → 未填则阻断启动
- [ ] 用户手填值：agent 重新生成后，已填的值不被覆盖
- [ ] 已有 `.env` 的项目：物化跳过（幂等），直接启动，零回归
- [ ] 无 env 依赖的项目（dev-local.sh / package.json dev / python main.py）：零回归
- [ ] 旧 `env_detection.py` 标记废弃（文件头注释 + 不导入）
- [ ] 后端单测：agent prompt 含 env_vars schema、物化幂等、校验阻断、加密 roundtrip
- [ ] 快档 pytest 绿；ruff/mypy 绿；前端 build + lint 绿

## Definition of Done

- 后端单测（agent env_vars 解析、物化、校验、加密）
- 前端组件测试（env 面板渲染、secret 遮蔽、必填阻断）
- CLI 一键验证：`python3 -m app.application.env_crypto` 可生成密钥
- CLAUDE.md 补 env 自举闭环文档
- i18n key 补齐（面板文案）

## Out of Scope

- 修 VideoNote 仓库本身（外部仓的债）
- 非 `.env` 类前置（DB 初始化、migrations、依赖安装）
- 密钥轮换 / 多密钥版本管理
- 团队共享 / 多租户隔离
- 前端 env 面板之外的 UI 改动

## Technical Notes

- 核心修改文件：
  - `backend/app/application/project_script_suggestions.py` — prompt 扩展 + `ProjectScriptSuggestion` 模型增加 `env_vars`
  - `backend/app/application/project_run_manager.py` — start 前置物化 .env + 校验
  - `backend/app/application/env_crypto.py` — 保留，用于 secret 加密
  - `backend/app/adapters/async_sqlite_store.py` — 新增 `project_env_vars` 表 + CRUD
  - `backend/app/interfaces/api.py` — 新增 `/projects/{id}/env` GET/PUT 端点
  - `backend/app/application/role_workflow_service.py` — _persist_operations_engineer_result 处理 env_vars
- 废弃文件：`backend/app/application/env_detection.py`（文件头注释标记废弃，保留不删供参考）
- 前端新增/修改：
  - `frontend/src/features/projects/` — env 配置面板组件
  - `frontend/src/lib/api.ts` — env API 调用
  - `frontend/src/lib/i18n.ts` + 语言文件 — env 面板文案
- 调研存档：`research/paas-env-detection.md`、`research/cloud-dev-env-bootstrap.md`、`research/env-schema-validation.md`、`research/ai-agent-auto-setup.md`