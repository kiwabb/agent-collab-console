# 结构化原型全链路可观测与可复现设计

## 1. 设计原则

“每一步可观测、可复现”是正确性约束，不是上线后补充日志：

- 可观测：每个会产生业务效果的步骤都有 durable identity、状态、phase、attempt、开始/结束时间、输入/输出 hash、固定版本、error code 和完成证据。
- 可复现：能够取得当时的冻结输入、精确版本和已接受输出，重建相同结构化状态，并解释每一个状态变化来自哪个步骤。
- 普通日志、SSE 和 Agent trajectory 是查询视图或审计材料，不是 artifact authority。
- 没有持久化步骤证据时不允许进入下一步；观测存储不可用时操作失败闭合为 `observability_unavailable`。

## 2. 两种“复现”必须区分

### 2.1 Deterministic state replay

以下步骤必须对相同输入和版本产生相同 output hash：

- canonicalization。
- 领域命令应用和 inverse 计算。
- checkpoint + journal 恢复。
- local key 到 entity ID 映射。
- foundation/page assembly。
- schema、semantic、scope 和 reference validation 结果。
- 固定 renderer version 的静态产物生成。

这些步骤的复现失败就是产品缺陷或数据损坏，必须报警并失败闭合。

### 2.2 Agent execution rerun

Claude Code UI Engineer 不是确定性函数。即使输入、prompt 和 runtime profile 相同，再执行一次也不保证生成相同 JSON。因此 AI 步骤定义两种能力：

1. **历史结果还原**：读取冻结 context、提交 artifact 和 task/process evidence，精确还原当时被校验和预览的结果。
2. **诊断重跑**：用相同 manifest 和版本创建新的 operation/task/process，产生新的 output hash，并生成与原结果的结构化 diff。

诊断重跑永远不覆盖原 operation，不自动 Apply/Accept/Publish。把“同输入重新调用 Claude 得到完全相同文本”作为验收条件是不成立的。

## 3. Durable evidence model

### 3.1 PrototypeIngressAttempt

每个 prototype HTTP 请求在进入业务服务前先取得 `correlation_id`，并在 durable audit sink 创建 ingress attempt。它覆盖成功、认证拒绝、Pydantic 拒绝和业务操作创建失败：

```text
id
correlation_id
method
route_template
project_id | null
principal_id | null
request_contract_version | null
raw_body_hash | null
normalized_request_hash | null
auth_decision_code
status: received | accepted | rejected | completed
operation_id | null
http_status | null
error_code | null
received_at
completed_at | null
```

不保存 raw body、Authorization header、cookie 或 token。Mutation 请求只有在 `received` evidence 已提交、认证和 schema 通过、operation 已创建后才进入 application service。Ingress/audit store 不可用时返回 `observability_unavailable`，不启动任何业务副作用。只读请求可以不创建 operation，但仍有 ingress completion evidence。

Ingress 状态变化追加 audit event，summary 行只用于查询。这样即使 Pydantic 无法构造业务 request，也能用 correlation ID 找到被拒绝的边界证据。

### 3.2 PrototypeOperation

一次外部意图对应一个 root operation：

```text
id
operation_kind
project_id
resource_kind
resource_id | null
client_request_id
correlation_id
parent_operation_id | null
status: queued | running | succeeded | failed | interrupted | cancelled
phase
attempt
request_manifest_hash
config_manifest_hash
result_manifest_hash | null
failure_evidence_hash | null
error_code | null
created_at
started_at | null
completed_at | null
```

覆盖的 operation kind 至少包括：

```text
create_document
apply_command_batch
undo
redo
create_checkpoint
recover_draft
generation_job
generation_item
ai_edit
semantic_repair
render_preview
publish
create_runtime_session
apply_runtime_event
replay_runtime_session
gc_run
diagnostic_replay
```

一个 HTTP 请求如果只读取状态，可以使用 trace 而不创建 operation；任何会启动异步工作、写命令、创建对象或改变状态的请求都必须先幂等创建 operation。

### 3.3 PrototypeOperationStep

```text
id
operation_id
parent_step_id | null
step_kind
step_ordinal
attempt
status: pending | running | succeeded | failed | skipped | interrupted
phase
input_manifest_hash
config_manifest_hash
output_manifest_hash | null
completion_evidence_kind | null
completion_evidence_ref | null
error_code | null
started_at | null
completed_at | null
```

`UNIQUE(operation_id, step_ordinal, attempt)`。Step 行提供当前摘要；每次状态变化同时追加 immutable event。

### 3.4 PrototypeOperationEvent

```text
operation_id
event_no
step_id | null
event_kind
status
phase
input_hash | null
output_hash | null
evidence_hash | null
error_code | null
occurred_at
PRIMARY KEY(operation_id, event_no)
```

Event 只追加。Step/Operation 是查询物化视图，不能反过来代替 event history。

### 3.5 Evidence manifest

小型索引字段放 SQLite；包含冻结输入、版本清单或大型结果的 manifest 使用 managed object store：

```text
PrototypeEvidenceManifestV1
  manifestVersion
  operationId
  stepId
  inputRefs[]
  inputHashes[]
  outputRefs[]
  outputHashes[]
  versions
  identities
  decision
  errorCode | null
  createdAt
```

Manifest 本身 canonicalize 后计算 hash。凭据、Claude 认证、MCP bearer token 和密钥不得进入 manifest；只记录不可逆 token ID/fingerprint 和权限声明 hash。

## 4. 必须冻结的版本和身份

每个适用步骤必须在执行前固定：

```text
request_contract_version
document_schema_version
command_contract_version
canonicalizer_version
context_builder_version
prompt_version
submission_contract_version
validation_ruleset_version
assembler_version
renderer_version
runtime_core_version
runtime_core_bundle_hash
state_machine_kernel_version
agent_role = prototype_ui_engineer
executor = claude
runtime_profile_id + runtime_profile_hash
claude_code_version
executor_adapter_version
final_runtime_wire_input_hash
mcp_tool_contract_version
governance_policy_version
source_fingerprint | null
worktree_base_commit | null
checkpoint/object hash
base_sequence_no + expected_result_sequence_no
task_id + execution_process_id
render_runtime_image_hash
browser_version
font_pack_hash
viewport_profile_hash
```

只存 `runtime_profile_id` 不够，因为配置可能原地修改；必须同时保存 profile 的安全规范化 hash。`final_runtime_wire_input_hash` 覆盖 task prompt 经过 managed prompt builder、project memory、team notes 和 transport framing 后实际发送给 Claude 的最终输入，不能只 hash 数据库里的 prompt 字段。运行中读取“当前最新版”配置会破坏复现，禁止这样做。

## 5. 全链路步骤矩阵

| 步骤 | durable identity | 必须保存的输入证据 | 完成证据 | 失败闭合点 |
|---|---|---|---|---|
| HTTP mutation ingress | ingress event/operation/client request/correlation | raw body hash、normalized request manifest hash、request contract、auth decision | accepted/rejected ingress event + operation created event | 无法持久化 ingress/operation 时不启动业务动作 |
| Durable job/run/item | job/run/item IDs | parent operation、source mode、attempt | rows committed + created event | 幂等或约束异常不启动下游 |
| Context freeze | context step ID | request hash、source fingerprint、selected IDs/object hashes、builder version | immutable context object hash + read-back | fingerprint 漂移或对象写失败不调用 Claude |
| Governance/budget | decision step ID | policy version、estimate inputs、runtime availability | typed allow/deny decision hash | gate 异常等同 deny |
| Claude task creation | task step ID | final runtime wire input hash、context hash、task kind、runtime profile/binary/adapter versions | CodexTask ID + isolated worktree/base commit identity | 任一资源不可用不启动 process |
| Execution process | process step ID | task ID、executor=claude、runtime config hash | process terminal state、exit/result code、usage | timeout/异常终态不接收为成功 |
| MCP/staging submission | submission ID | scoped capability fingerprint、expected contract/item | unique finalization + artifact hash/size/path containment evidence | missing、duplicate、越权或 hash 错误直接失败 |
| Strict schema validation | validation step ID | submission object hash、schema/ruleset version | validation report hash | 结构不完整不做宽松补全 |
| Semantic validation | validation step ID | parsed object hash、frozen scope/source | deterministic report hash | scope/reference/source 错误不截断继续 |
| Repair | new child operation/task | original error report hash、original item hash | new submission and comparison evidence | 超过一次或不允许的错误不 repair |
| Assembly | assembly step ID | ordered blueprint/foundation/page hashes、assembler version | candidate object hash | 缺 item/顺序不确定/引用错误拒绝 |
| Command application | batch/operation ID | base seq/hash、command batch hash、contract version | result seq/hash + DB commit evidence | base conflict 或 hash 不一致整批拒绝 |
| Checkpoint | checkpoint/operation ID | head seq/hash、canonicalizer/codec version | object read-back + checkpoint reference commit | object 不可验证时不推进引用 |
| Render | render run/step ID | document object hash、renderer version、runtime image/browser/font/viewport hashes | output hash、artifact descriptor、visual preflight/pixel report | artifact/校验失败不显示 ready |
| Preview | preview ID | candidate hash、render artifact hash | preview_ready event | candidate/artifact 对不上不允许 Apply |
| Accept/Apply | mutation operation ID | expected state/seq、candidate/batch hash、request ID | result seq/checkpoint/document IDs | stale 或事务任一步失败全部回滚 |
| Publish | publish/revision/render IDs | head checkpoint hash、renderer version | public pointer commit event + artifact hash | 未验证 render 不推进 public pointer |
| Runtime session create | session/operation ID | pinned document/scenario/runtime-core hashes | sequence-0 state object/hash + session commit | 任一版本/hash 不可验证时不启动 session |
| Runtime event | event batch/operation ID | expected sequence/state、event hash、core bundle hash | rule/guard/effect report + result sequence/state/view-model hashes | worker/commit/evidence 失败不推进 session head |
| Recovery | replay operation ID | checkpoint hash/seq、ordered batch hashes、all versions | final seq/hash + replay report | 缺序/版本/hash 错误把 draft 标 corrupt |
| Runtime recovery | runtime replay operation ID | state checkpoint、ordered event/report hashes、core bundle | final sequence/state hash | 首个 event/effect/hash 分歧把 session 标 corrupt |
| GC | gc run/item IDs | scan epoch、live-set hash、retention policy version | deleted object hash or retained reason | live set 不完整时不删除任何对象 |

## 6. HTTP、SSE 与查询

所有 mutation response 至少包含：

```json
{
  "operationId": "op-...",
  "correlationId": "corr-...",
  "status": "succeeded",
  "phase": "command_committed",
  "result": {},
  "error": null
}
```

异步工作提供三个查询面：

- `GET resource` 返回业务 snapshot 和当前 operation 摘要。
- `GET /api/prototype-operations/{operation_id}` 返回步骤、版本、hash 和 error code，不返回敏感 payload。
- SSE 发送持久化 snapshot 和 heartbeat；断线后从 GET 恢复，不依赖丢失的 token delta。

SSE event 带 `contractVersion`、`resourceId`、`operationId`、`eventNo` 和 `updatedAt`。前端在 resource identity、event 顺序或 contract 不匹配时拒绝合并，保留最后合法 snapshot 并显示错误。

## 7. Replay manifest

每个成功产生业务效果的 operation 生成或引用一个 `PrototypeReplayManifestV1`：

```text
operation_id
operation_kind
parent_operation_id | null
request_manifest_hash
context_manifest_hash | null
ordered_input_object_hashes[]
versions
agent_task_identity | null
submission_hash | null
ordered_command_batch_hashes[]
base_checkpoint_hash | null
base_sequence_no | null
result_checkpoint_hash | null
result_sequence_no | null
renderer_input_hash | null
renderer_output_hash | null
runtime_session_id | null
runtime_core_bundle_hash | null
ordered_runtime_event_hashes[]
runtime_final_state_hash | null
runtime_final_view_model_hash | null
validation_report_hashes[]
terminal_status
error_code | null
```

Replay manifest 只在所有引用已持久化后创建。Operation 如果无法创建 replay manifest，状态不能是 `succeeded`。如果 object/observability 的一部分在副作用前失败，SQLite operation/step/event 保存 request/config/error/last-step 组成的 bounded `failure_evidence_hash`；该失败可解释，但不伪装成可执行的状态 replay。

## 8. 复现操作

### 8.1 状态重放

`diagnostic_replay` 在隔离进程中：

1. 解析 replay manifest 并校验所有 object references。
2. 装载 manifest 指定的 schema、canonicalizer、command 和 assembler 版本。
3. 从 checkpoint 重放命令或从生成 items 重新 assembly。
4. 对每一步比较 output hash。
5. 生成 immutable replay report。

任何 hash 不一致都标为 `replay_mismatch`，报告首个分歧步骤，不修改 active draft。

### 8.2 Renderer 重放

使用相同 document object 和 renderer version 在隔离目录重新渲染。结构文件 hash 应完全一致；如果产物包含构建时间、随机 ID 或非固定依赖，则 renderer contract 本身不合格，必须移除这些非确定输入。

### 8.3 Claude 诊断重跑

只有具备权限的用户可以请求。系统复用原 frozen manifest 和版本，但创建新的 operation/task/process/submission。结果展示：

- 原 output hash 与新 output hash。
- schema/semantic validation 差异。
- command、页面结构和 render diff。
- runtime profile 是否仍可用。

新结果默认只读，不能替代原证据。

## 9. 日志、Trace 与 Agent trajectory

- INFO 日志只记录 ID、kind、phase、status、duration、版本、usage/cost 和 stable error code。
- 完整 prompt、文档、CodeBlock、源文件、Claude 输出和凭据不进入普通日志。
- Agent trajectory 可以保存 raw frames、thinking、tool calls、messages 和 stdout/stderr，用于调查 Claude 做了什么。
- 成功判定只信 task/process terminal evidence、唯一 MCP/staging submission、严格验证、object hash 和事务提交。
- 即使 trajectory 中出现完整 JSON，也不能从日志恢复 artifact 或绕过 staging/object store。

## 10. 失败与恢复

- 服务启动时把非终态外部执行 step 标为 `interrupted`，不自动重复 Claude 调用。
- 已经提交且 object/reference 完整的 item 可以复用；只有缺 completion evidence 的 item 需要显式 Retry。
- Retry 创建 child operation，保存 `retry_of_operation_id`，不修改原 attempt。
- Cancel 先持久化 cancelled decision，再请求外部 process 停止；晚到 submission 只能进入审计，不能改变业务状态。
- observability store、object store、governance、validation 或 replay 任一不可用时拒绝产生新的业务效果。

## 11. 数据保护和保留

- Manifest/object 读取按 project ownership 授权。
- 用户指令、对话和冻结上下文属于受控业务数据；数据库列表接口只返回摘要和 hash。
- MCP token 只记录 fingerprint、scope hash、issued/expired/revoked time，不保存 bearer value。
- operation、step、event 和 published replay manifest 长期保留。
- rejected/stale candidate 和失败运行对象按 storage design 的 retention policy 回收；删除时保留 hash、删除原因和 GC evidence。

## 12. 最小验收标准

- 任意 Apply/Accept/Publish 都能从 response 的 `operationId` 查到完整步骤链和 replay manifest。
- 每个步骤都有输入 hash、固定版本、终态和 completion evidence；仅有日志不算通过。
- 相同 checkpoint、命令和版本在干净进程中恢复出相同 sequence/document hash。
- 相同 generation items 和 assembler version 产生相同 candidate hash。
- 相同 document object 和 renderer version 产生相同 output hash。
- 相同 document/scenario/runtime-core/event sequence 产生相同 rule/effect reports 和 final runtime-state hash。
- Claude 原结果可从 submission object 精确还原；诊断重跑被标为新 operation，不宣称输出必然相同。
- task/process 成功但 submission 缺失时 operation 失败，不能凭 trajectory 判成功。
- 任一 source fingerprint、scope、contract、hash、sequence 或 identity 不一致都失败闭合。
- SSE 断线、服务重启和进程崩溃后，GET snapshot 与 durable event history 能解释最终状态。
- GC 能证明每个删除对象在两个扫描周期中均无引用；live-set 构造失败时删除数必须为 0。
