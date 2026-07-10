# 移除「从代码生成原型」功能重构方案 (v4 · 收窄 legacy 契约改造)

## 背景

代码扫描生成原型（code-scan → `CodePrototypeDiscoveryService`）存在根本性问题：

1. **框架耦合严重** — 只硬编码识别 Next.js App Router / Pages Router / `src/features/*Page` 模式，Vite / Remix / CRA 等框架零检出
2. **源码推断失真** — 把 imports + 截断 JSX 喂给 LLM，丢失设计意图、UX 决策、动态数据流
3. **用户侧结论已验证** — VideoNote（Vite + React）扫出 0 候选，说明该功能实用性有限

核心认知：**原型设计是设计工作，应由人（UI/UX 工程师）输入意图，LLM 负责执行，而不是从代码反向猜测。**

## 关键范围决策

**本次不删除 `Prototype` 模型、API、前端类型和 SQLite 中的 `source_*` 字段。**

删除 code-scan 不依赖这项 API breaking change。旧字段作为 legacy provenance 保留，避免改动核心 CRUD；未来如需清理字段和物理列，单独设计弃用与迁移。

`load_prototype_by_source`、`update_prototype_source_metadata` 和 `list_code_prototypes` 是 code-scan 专属，可删除。`save_prototype`、`_prototype_from_row`、`load_prototype` 和 `list_prototypes` 保持不变。

---

## 变更范围

### 后端删除文件

| 文件 | 操作 | 理由 |
|---|---|---|
| `backend/app/application/code_prototype_discovery.py` | **删除** | 核心扫描器，整文件只被 code-scan 使用 |
| `backend/app/application/runtime_prototype_capture.py` | **删除** | 浏览器截图证据收集，仅 code-scan 使用 |

### 后端依赖清理

| 文件 | 操作 | 理由 |
|---|---|---|
| `backend/pyproject.toml` (:17) | 删除 `"playwright>=1.51.0",` 行；删除两个待删模块的 mypy strict 清单项 | `runtime_prototype_capture.py` 是后端唯一 Python Playwright 使用方 |
| `backend/requirements.txt` (:14) | 删除 `playwright>=1.51.0` | 同上 |

### 后端修改文件

| 文件 | 改动 |
|---|---|
| `backend/app/application/prototype_service.py` | **移除 code-scan 逻辑（约 400 行）**：`RuntimePrototypeEvidence` 类 + `RuntimeCaptureService` Protocol + `from_payload` / `to_prompt_block` / `to_meta` / `compact_code_source_excerpt` / `_split_source_excerpt_units` / `_is_high_signal_source_line` / `build_editable_code_candidate_brief` / `build_code_backed_brief` / `list_code_candidates` / `generate_all_from_code_stream` / `_create_code_prototype` / `_refresh_code_seed` / `_build_code_seed_brief` / `_combined_code_instruction` / `_capture_runtime_evidence` / `_candidate_meta`。**移除辅助残留**：`_trim_optional_text` / `_safe_viewport` / `_safe_console_errors` / `_SOURCE_UNIT_RE` 正则 / `CODE_BRIEF_MAX_SOURCE_CHARS` / `CODE_BRIEF_MAX_UNIT_CHARS` / `CODE_BRIEF_HEAD_CHARS` 常量。**清理 import**：删 `field` 和 code discovery import，保留 `dataclass`；删仅供 code-scan 使用的 `json`。保留 `from app.json_safety import object_dict, parse_json_object, string_value`（`_stream_html` 用）。简化 `__init__` 去掉 `discovery_service` + `runtime_capture_service` 参数，保留 `create()` 的 `source_kind="manual"` legacy provenance。保留 `RuntimeCatalogLoader` Protocol。 |
| `backend/app/interfaces/sse.py` | **删除两个路由**：`generate-from-code/stream` 和 `code-candidates`。删除 `_parse_candidate_text_map` / `_parse_runtime_evidence`、`RuntimePrototypeEvidence`、`MAX_CANDIDATE_QUERY_TEXT_CHARS`，并清理失去用途的 `Query` / `parse_json_object` import。保留 `regenerate-all/stream`。 |
| `backend/app/bootstrap.py` | 删 L27 import `from app.application.runtime_prototype_capture import RuntimePrototypeCaptureService` + 删 L197 构造器 kwarg `runtime_capture_service=RuntimePrototypeCaptureService()`。删 `discovery_service` 相关。 |
| `backend/app/domain/models.py` | **无改动**；保留 legacy `Prototype.source_*` contract |
| `backend/app/adapters/async_sqlite_store.py` | 仅删除 code-scan 专属方法：`load_prototype_by_source`、`update_prototype_source_metadata`、`list_code_prototypes`。核心 CRUD、旧列和索引保持不变。 |

### 前端删除文件

| 文件 | 操作 | 理由 |
|---|---|---|
| `frontend/src/features/prototype/codeCandidateBriefs.ts` | **删除** | 仅 code-scan 使用 |
| `frontend/tests/prototypeCandidateBriefs.test.ts` | **删除** | 仅 code-scan 使用 |
| `frontend/tests/prototypeApi.test.ts` | **删除** | 98 行全是 code-scan 专属测试（4 tests），无保留功能测试可留 |

### 前端修改文件

| 文件 | 改动 |
|---|---|
| `frontend/src/features/prototype/ProjectPrototypesPage.tsx` | 移除「从代码生成」按钮、scan dialog、code progress dialog、所有 code-scan 状态 + 事件处理。移除 `SourceBadge` 组件 (`:1431-1451`) + 侧栏调用 (`:970`)。移除 `p.source_kind === "code" && p.source_ref` 渲染块 (`:978-980`)。 |
| `frontend/src/features/prototype/prototypeStreamEvents.ts` | 移除 `PrototypeCodeCandidate` / `CodeGenerationSummary` / `PrototypeCodeCandidateAction` 类型验证器及仅供 code-scan 使用的 `readSseNullableString`；保留 regenerate-all 和 PrototypeCanvas 使用的通用 readers。 |
| `frontend/src/lib/api/prototypes.ts` | 移除 `listPrototypeCodeCandidates` / `getGenerateFromCodeStreamUrl` / `MAX_CANDIDATE_QUERY_TEXT_CHARS` / `RuntimePrototypeEvidenceInput` 接口 (`:11-22`)。 |
| `frontend/src/lib/api.ts` | 删 barrel re-export (`:156-168`)：`getGenerateFromCodeStreamUrl` / `listPrototypeCodeCandidates` / `MAX_CANDIDATE_QUERY_TEXT_CHARS` / `export type RuntimePrototypeEvidenceInput`。 |
| `frontend/src/lib/types/prototypes.ts` + `frontend/src/lib/types.ts` | 移除 `PrototypeCodeCandidate` / `PrototypeCodeCandidateAction` / `PrototypeCodeCandidatesResponse` 定义和 barrel exports；保留 `Prototype.source_*` legacy 字段。 |
| `frontend/src/lib/i18n.ts` | **baseDictionaries** 内联对象删 `generateFromCode.*` ~88 条 key + 额外删 `prototype.source.manual` / `prototype.source.code` 各两组（`:1070-1071` 中文，`:1504-1505` 英文）。 |
| `frontend/src/lib/i18n/en-US.ts` | 删 `prototype.generateFromCode.*` 全部 key + 删 `prototype.source.code` (`:280`) + `prototype.source.manual` (`:279`)。 |
| `frontend/src/lib/i18n/zh-CN.ts` | 同上 + 删 `prototype.source.code` (`:258`) + `prototype.source.manual` (`:257`)。 |

### 测试修改

| 文件 | 改动 |
|---|---|
| `backend/tests/test_prototype_service.py` | 移除所有 code discovery/generation/runtime capture import、helpers 和测试；新增 legacy code prototype 的 list/get/iterate/regenerate-all 兼容测试 |
| `backend/tests/test_prototypes_api.py` | 移除 `code-candidates` 端点测试 + `generate-from-code/stream` 端点测试。额外移除 `_parse_runtime_evidence` parser 单测 (`:135` 起)、相关常量 import、`RuntimePrototypeEvidence` import (`:20`)。 |
| `frontend/tests/prototypeStreamEvents.test.ts` | 删除 candidate/summary 专属断言；拆分混合测试并保留 `readFailedPrototypeItems` 的 regenerate-all 覆盖。 |

### 文档

| 文件 | 改动 |
|---|---|
| `CLAUDE.md` | **无改动**。当前原型段只描述手动原型 + regenerate-all，无 code-scan / runtime evidence / source_kind 内容。 |

### 规约与审计文件

历史 task 记录保留；`.trellis/spec/ccgui/frontend/type-safety.md` 与 `.trellis/spec/vibe-kanban/frontend/type-safety.md` 是当前规范，删除 code-candidate 现行示例。清理 `frontend/.audit_findings.json` 中随扫描 UI 删除而失效的两条 finding。

---

## 保留的功能（不变）

- ✅ **手动创建** — 写 brief → `POST /api/projects/{id}/prototypes` → `stream_events` → `build_html_system_prompt`
- ✅ **迭代修改** — instruction → `build_iteration_system_prompt` → 版本递增
- ✅ **批量重生成** — `regenerate-all/stream`（对已有 prototype 用 v0 seed brief 文本重新生成；**老 code-scan 创建的 prototype 仍可重生成**，因为 seed 行存的是文本不是 builder）
- ✅ **版本切换 / 历史加载 / iframe 沙箱预览** — 不变

## 数据迁移

**零迁移**。旧 DB 行和 API 中的 `source_kind='code'` 等 legacy provenance 保留；旧 prototype 仍可查看、迭代和重生成，只是侧栏不再显示来源 badge。

## 执行步骤

1. **后端删文件**：`code_prototype_discovery.py` + `runtime_prototype_capture.py`
2. **删依赖**：`pyproject.toml` + `requirements.txt` 的 playwright 行
3. `async_sqlite_store.py`：仅删 `load_prototype_by_source`/`update_prototype_source_metadata`/`list_code_prototypes`
4. `prototype_service.py`：删全部 code-scan 方法 + 辅助残留 + 清理 import；`__init__` 减参；保留 `create()` 的 `source_kind="manual"`
5. `sse.py`：删两个路由 + helper + import + 常量
6. `bootstrap.py`：删 import 行 + 构造器 kwarg
7. 前端删文件：`codeCandidateBriefs.ts`、`prototypeApi.test.ts`、`prototypeCandidateBriefs.test.ts`
8. 前端改：`ProjectPrototypesPage.tsx`（含 SourceBadge + source_kind 渲染块）、`prototypeStreamEvents.ts`、`prototypes.ts`、`api.ts` barrel、`types.ts`、`i18n.ts`(baseDictionaries + prototype.source.*)、`en-US.ts`+`zh-CN.ts`
9. 测试：清理 code-scan 测试；补 legacy row 兼容和删除后 endpoint contract 测试；保留 regenerate-all readers 覆盖
10. 更新当前 Trellis type-safety 规范和失效的 audit findings
11. **验证**：
    ```bash
    cd frontend && npm test && npm run typecheck && npm run lint && npm run format:check
    cd backend && .venv/bin/ruff check app tests
    cd backend && .venv/bin/mypy app benchmark tests --show-error-codes --no-pretty
    cd backend && .venv/bin/python -c "from app.main import app"
    cd backend && .venv/bin/python -m pytest tests/test_prototype_service.py tests/test_prototypes_api.py -v
    cd backend && .venv/bin/python -m pytest -v
    cd backend && .venv/bin/python -m pytest --runslow -v  # 全量（可选）
    ```
12. 浏览器 smoke + 零残留 `rg`，然后只暂存本任务 hunks；不得混入 Startup Config 改动

## 后期可移除（可选）

- legacy `source_*` API contract、数据库列和 `idx_prototypes_project_source` 另开迁移任务评估
- `frontend/tests/prototypeStreamEvents.test.ts` 中的 `readFailedPrototypeItems` 保留读者（regenerate-all 用）。
