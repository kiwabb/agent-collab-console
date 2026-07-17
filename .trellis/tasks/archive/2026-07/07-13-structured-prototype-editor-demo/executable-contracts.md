# 结构化原型可执行契约

## 1. 目的

本文把总设计收敛为实现时不能自由解释的边界：类型化命令、HTTP 请求、Claude MCP/staging 提交、ID 分配、renderer 输入输出和版本兼容。实际 Pydantic 模型、dataclass 和 TypeScript 类型必须由同一份 contract fixtures 验证。

所有 Pydantic v2 request/output models 使用：

```text
extra = forbid
strict = true
str_strip_whitespace = false
```

除明确标注 `optional` 外，字段全部 required。未知 discriminator、未知字段、空字符串、越界整数、重复 ID 和非 canonical hash 都拒绝。

## 2. 版本注册表

首版独立维护以下版本，禁止用一个全局 `v1` 掩盖不同兼容边界：

```text
http_contract_version
document_schema_version
command_contract_version
runtime_schema_version
runtime_state_schema_version
runtime_core_version
state_machine_kernel_version
generation_contract_version
assistant_outcome_contract_version
context_manifest_version
canonicalizer_version
validation_ruleset_version
assembler_version
renderer_version
renderer_environment_version
mcp_tool_contract_version
staging_manifest_version
operation_evidence_version
replay_manifest_version
```

兼容规则：

- Reader 可以支持多个旧版本，但每个 run/operation 固定一个精确版本。
- Writer 只写当前版本，不原地升级既有 object 或 command batch。
- 不支持的版本返回 `contract_version_unsupported`，不能尝试按最新版解释。
- Version registry 在进程启动时校验所有必要实现存在；缺任一实现则对应能力 unavailable。

## 3. 通用标量

```text
EntityId       = UUID string，服务端分配
ClientRequestId = UUID string，调用方生成
TechnicalKey   = ^[a-z][a-z0-9-]{0,63}$
Sha256         = ^sha256:[0-9a-f]{64}$
RoutePath      = 以 / 开头的规范化站内路径，不含 scheme、host、query、fragment
Locale         = 受支持 BCP-47 allowlist
Timestamp      = UTC ISO-8601，微秒精度，Z 结尾
SequenceNo     = integer >= 0
ByteSize       = integer >= 0
DecimalString  = ^-?(0|[1-9][0-9]*)(\.[0-9]{1,4})?$
```

哈希字段必须带 `sha256:` 前缀。数据库可以保存纯 hex 内部值，但 domain/API 必须使用一种固定表示，不能混用。

## 4. PrototypeDocumentV1

### 4.1 Top-level

```text
PrototypeDocumentV1
  schemaVersion: 1
  id: EntityId
  title: string[1..120]
  locale: Locale
  settings: PrototypeSettingsV1
  tokens: DesignTokensV1
  componentDefinitions: ComponentDefinitionV1[0..50]
  pages: PrototypePageV1[1..20]
  navigation: NavigationDefinitionV1
  flows: PrototypeFlowV1[0..100]
  runtime: RuntimeDefinitionV1
  assetRefs: AssetRefV1[0..200]
```

全局语义约束：

- 所有 entity/node IDs 在文档内唯一。
- page route、component key、navigation item key 和 flow key 唯一。
- 所有引用必须存在且 entity kind 正确。
- 数组顺序是用户可见顺序，不由 renderer 重新排序。
- document 不含 createdAt/updatedAt、运行 ID、renderer 字段或数据库路径；这些是外部 metadata。

### 4.2 Page and node identity

```text
PrototypePageV1
  id: EntityId
  key: TechnicalKey
  title: string[1..80]
  route: RoutePath
  viewport: ViewportSettingsV1
  root: UINodeV1
```

持久化 document 中的每个 node 都有 `id: EntityId`。Claude generation page 产物不允许生成 `id`，只生成 `localKey: TechnicalKey`；Assembler 解析后才能形成 `PrototypeDocumentV1`。

### 4.3 UINode discriminated union

共同字段：

```text
id
type
name: string[1..80]
visibility: visible | hidden
layoutItem: LayoutItemV1
responsive: ResponsiveOverrideV1[0..3]
```

首版节点：

| `type` | 必填 payload | children contract |
|---|---|---|
| `Freeform` | no extra payload; fixed non-zero px width/height in `layoutItem` | `children[0..500]` |
| `Stack` | direction, gap, align, justify, padding | `children[0..500]` |
| `Grid` | columns, gap, padding, columnOverrides | `children[0..500]` |
| `Form` | formDefinitionId, gap, padding | `children[1..200]` |
| `Text` | content, semantic, tone | none |
| `Button` | label, variant, size, disabled, iconName nullable | none |
| `Input` | label, placeholder, value, inputType, required, disabled | none |
| `Select` | label, value nullable, options[1..100], required, disabled | none |
| `Table` | columns[1..30], rows[0..200], density | none |
| `Image` | assetId, alt, fit, aspectRatio nullable | none |
| `ComponentInstance` | definitionId, propOverrides, slots | only declared slots |
| `Overlay` | presentation, title nullable, openByDefault | exactly one root child |
| `CodeBlock` | payload, sandboxPolicyVersion | none; payload opaque |

`Grid.columnOverrides` 按 `minWidth` 严格递增，最多 3 项；每项只覆盖列数。基础
`columns` 和 override `columns` 均为 `1..12`，`minWidth` 为 `320..2560`。`Stack`、
`Grid` 和 `Form` 是约束布局容器。`Freeform` 是唯一自由定位容器，且自身
`width`/`height` 必须是 `1..4096px` 的非零固定长度。

### 4.4 Layout

```text
LengthV1 = {unit: px | percent | rem | auto, value: DecimalString | null}

LayoutItemV1
  width: LengthV1
  minWidth: LengthV1 | null
  maxWidth: LengthV1 | null
  height: LengthV1
  minHeight: LengthV1 | null
  maxHeight: LengthV1 | null
  grow: integer[0..12]
  shrink: integer[0..12]
  alignSelf: auto | start | center | end | stretch
  position?: FreeformPositionV1

FreeformPositionV1
  x: canonical non-negative DecimalString[0..4096]
  y: canonical non-negative DecimalString[0..4096]
```

`unit=auto` 时 `value=null`，其他 unit 必须有 `DecimalString`。用规范字符串而不是 JSON 浮点数，保证 Python/TypeScript canonical hash 一致。百分比限定 0..100，px/rem 使用配置上限。页面 root 的 `position` 必须缺省；Freeform 的直接子节点必须有 `position`；其他父节点的直接子节点禁止 `position`。Responsive override 永远禁止 `position`。Responsive override 的 breakpoint 只允许 `sm | md | lg`，每个 breakpoint 最多一条；数组必须按 `sm < md < lg` 严格递增。`LayoutItemUpdateV1` canonical JSON 只输出调用方显式提交的字段，未设置字段不能被序列化成 `null`。

### 4.5 Runtime behavior and flows

可执行行为只保存为 [`prototype-runtime-design.md`](prototype-runtime-design.md) 定义的 `BehaviorRuleV1` trigger/guard/effects。`PrototypeFlowV1` 和 `RuntimeFlowLayoutV1` 只保存 rule projection、分组与坐标，不复制 action。Navigation、back、overlay、drawer 和 tab 都是 typed runtime effects。

External URL、任意 JavaScript callback、HTTP request 和字符串 expression 不在首版 contract 中。

## 5. DomainCommandBatchV1

### 5.1 Envelope

```text
DomainCommandBatchV1
  commandContractVersion: 1
  commands: DomainCommandV1[1..100]
  summary: string[1..240]
```

Envelope 不含 inverse、result sequence、document hash 或服务端 entity ID 分配结果。它们由服务端计算。

### 5.2 Insert and duplicate IDs

新节点使用 batch-local `newNodeKey: TechnicalKey`。`NewNodeV1` 是不含持久化 `id` 的 node union，每个节点（包括嵌套 children）都带 `newNodeKey`，且同一 batch 内唯一。同一 batch 内后续命令可通过 `NodeRefV1` 引用：

```text
NodeRefV1 =
  ExistingNodeRef {kind=existing, nodeId}
  NewNodeRef {kind=new, newNodeKey}
```

服务端确定性分配：

```text
uuid5(PROTOTYPE_ENTITY_NAMESPACE,
      draft_id + ":" + client_request_id + ":node:" + new_node_key)
```

Duplicate 的后代 ID 使用 `newNodeKey + ":" + source-relative-path`。相同 idempotent request 得到相同 IDs；不同 request 不能因客户端复用 key 而碰撞。

Generation local key 使用：

```text
uuid5(PROTOTYPE_ENTITY_NAMESPACE,
      job_id + ":" + scope_kind + ":" + scope_key + ":" + local_key)
```

### 5.3 Command union

```text
InsertNodeCommand
  kind: insertNode
  parent: NodeRefV1
  slot: string | null
  index: integer >= 0
  node: NewNodeV1

MoveNodeCommand
  kind: moveNode
  node: NodeRefV1
  targetParent: NodeRefV1
  targetSlot: string | null
  targetIndex: integer >= 0
  targetPosition?: FreeformPositionV1

RemoveNodeCommand
  kind: removeNode
  nodeId: EntityId

DuplicateNodeCommand
  kind: duplicateNode
  sourceNodeId: EntityId
  targetParentId: EntityId
  targetSlot: string | null
  targetIndex: integer >= 0
  newNodeKey: TechnicalKey

SetNodePropertyCommand
  kind: setNodeProperty
  node: NodeRefV1
  update: NodePropertyUpdateV1

ContainerLayoutUpdateV1 =
  StackLayoutUpdate {
    kind=stackLayout, direction, gap, align, justify, padding
  }
  GridLayoutUpdate {
    kind=gridLayout, columns, gap, padding, columnOverrides
  }
  FormLayoutUpdate {kind=formLayout, gap, padding}
  ResponsiveLayoutUpdate {kind=responsiveLayout, responsive}

Stack/Grid/Form updates are full-value replacements for their matching node
type. ResponsiveLayoutUpdate is valid for every structured node. A mismatched
node/update pair is refused with `command_property_invalid`; inverse commands
store the complete previous value.

SetNodeLayoutCommand
  kind: setNodeLayout
  node: NodeRefV1
  update: LayoutItemUpdateV1

ReorderPageCommand
  kind: reorderPage
  pageId: EntityId
  targetIndex: integer >= 0

ReorderNavigationItemCommand
  kind: reorderNavigationItem
  itemId: EntityId
  targetIndex: integer >= 0

Studio page sorting submits `reorderPage` and the required
`reorderNavigationItem` commands in one atomic batch. The local projected
document reorders both `pages` and `navigation.items`; failure restores both,
and inverse execution restores their exact prior order.

UpdateNavigationCommand
  kind: updateNavigation
  update: NavigationUpdateV1

ReplaceCodeBlockPayloadCommand
  kind: replaceCodeBlockPayload
  nodeId: EntityId
  payload: string[0..131072 bytes UTF-8]
  sandboxPolicyVersion: integer
```

`InsertNode` 向 Freeform 插入时，`node.layoutItem.position` 必填；向其他容器插入时禁止。
`MoveNode.targetPosition` 在目标父节点为 Freeform 时必填，目标为普通容器时禁止并由命令应用器清除来源坐标。
inverse Move 必须恢复来源父节点、index 和来源 position。Freeform 的 west/north/Alt-center Resize
必须通过一个 `SetNodeLayoutCommand` 同时提交 `position`、`width` 和 `height`，不能拆成两个 batch。

Runtime/Flow command union：

```text
AddRuntimeRoleCommand {kind=addRuntimeRole, newRoleKey, definition}
ReplaceRuntimeRoleCommand {kind=replaceRuntimeRole, roleId, definition}
RemoveRuntimeRoleCommand {kind=removeRuntimeRole, roleId}

AddRuntimeVariableCommand {kind=addRuntimeVariable, newVariableKey, definition}
ReplaceRuntimeVariableCommand {kind=replaceRuntimeVariable, variableId, definition}
RemoveRuntimeVariableCommand {kind=removeRuntimeVariable, variableId}

AddMockEntitySchemaCommand {kind=addMockEntitySchema, newSchemaKey, definition}
ReplaceMockEntitySchemaCommand {kind=replaceMockEntitySchema, schemaId, definition}
RemoveMockEntitySchemaCommand {kind=removeMockEntitySchema, schemaId}

AddRuntimeFormCommand {kind=addRuntimeForm, newFormKey, definition}
ReplaceRuntimeFormCommand {kind=replaceRuntimeForm, formId, definition}
RemoveRuntimeFormCommand {kind=removeRuntimeForm, formId}

AddRuntimeScenarioCommand {kind=addRuntimeScenario, newScenarioKey, definition}
ReplaceRuntimeScenarioCommand {kind=replaceRuntimeScenario, scenarioId, definition}
RemoveRuntimeScenarioCommand {kind=removeRuntimeScenario, scenarioId}

AddBehaviorRuleCommand {kind=addBehaviorRule, newRuleKey, definition}
ReplaceBehaviorRuleCommand {kind=replaceBehaviorRule, ruleId, definition}
RemoveBehaviorRuleCommand {kind=removeBehaviorRule, ruleId}

BindNodeRuntimeFieldCommand {kind=bindNodeRuntimeField, nodeId, formId, fieldId}
UnbindNodeRuntimeFieldCommand {kind=unbindNodeRuntimeField, nodeId}
AddRuntimeViewBindingCommand {kind=addRuntimeViewBinding, newBindingKey, definition}
ReplaceRuntimeViewBindingCommand {kind=replaceRuntimeViewBinding, bindingId, definition}
RemoveRuntimeViewBindingCommand {kind=removeRuntimeViewBinding, bindingId}
SetRuntimeFlowNodePositionCommand {kind=setRuntimeFlowNodePosition, flowNodeId, x, y}
```

`SetRuntimeFlowNodePositionCommand` 的 `flowNodeId` 当前只接受 document 中
存在的 page、runtime variable、behavior rule 或 scenario ID。`x/y` 必须是
`[-32768, 32768]` 内整数；`flowLayout.nodes` 最多 300 项、按 `nodeId` canonical
排序且禁止重复。删除最后一个位置时不序列化空 `flowLayout`，旧文档的 canonical
JSON 与 hash 必须保持不变。服务端 inverse 精确恢复原坐标；原节点此前没有显式
坐标时，Undo 必须完全移除该 entry 和空 layout。

`definition` 不是任意 dict，分别是去掉持久化 `id` 的 strict RuntimeRole/Variable/EntitySchema/Form/Scenario/BehaviorRule definition。Replace 是整份 typed definition replacement，避免 field path/value 形式的半类型化 patch。所有 inbound references 在执行前验证。

### 5.4 Property and navigation update unions

`NodePropertyUpdateV1` 是 discriminated union，不是任意 property path/value：

```text
TextContentUpdate {kind=textContent, content}
LabelUpdate {kind=label, label}
PlaceholderUpdate {kind=placeholder, placeholder}
ButtonVariantUpdate {kind=buttonVariant, variant}
DisabledUpdate {kind=disabled, disabled}
InputValueUpdate {kind=inputValue, value}
SelectOptionsUpdate {kind=selectOptions, options}
ImageAssetUpdate {kind=imageAsset, assetId, alt}
TableDataUpdate {kind=tableData, columns, rows}
VisibilityUpdate {kind=visibility, visibility}
```

Validator 根据 node type 限制合法 update。`LayoutItemUpdateV1` 所有字段 optional、extra forbidden，且 model validator 要求至少一个字段出现；显式 null 仅用于 schema 声明 nullable 的字段。

`NavigationUpdateV1`：

```text
AddNavigationItem {kind=addItem, item, index}
RemoveNavigationItem {kind=removeItem, itemId}
MoveNavigationItem {kind=moveItem, itemId, targetIndex}
SetNavigationLabel {kind=setLabel, itemId, label}
SetNavigationTarget {kind=setTarget, itemId, targetPageId}
```

### 5.5 Inverse ownership

服务端纯函数执行器返回：

```text
CommandExecutionResultV1
  resolvedCommands
  inverseCommands
  allocatedEntityIds
  baseDocumentHash
  resultDocumentHash
  assetReferenceDelta
  affectedEntityIds
```

Inverse 按 commands 的反向顺序排列。Remove/Duplicate 的 inverse 可以包含完整、受 256 KiB batch 上限约束的 node subtree；超过上限时原命令在应用前被拒绝。客户端和 Claude 提交 inverse 字段一律 422。

## 6. HTTP mutation contracts

### 6.1 Apply command batch

```text
ApplyCommandBatchRequestV1
  contractVersion: 1
  clientRequestId: ClientRequestId
  expectedHeadSequenceNo: SequenceNo
  expectedDocumentHash: Sha256
  batch: DomainCommandBatchV1

ApplyCommandBatchResponseV1
  contractVersion: 1
  operationId: EntityId
  correlationId: EntityId
  draftId: EntityId
  headSequenceNo: SequenceNo
  documentHash: Sha256
  appliedBatchId: EntityId
  allocatedEntityIds: AllocatedEntityIdV1[]
  affectedEntityIds: EntityId[]
  document: PrototypeDocumentV1
```

`AllocatedEntityIdV1 = {newNodeKey, entityId}`，按 `newNodeKey` 排序，禁止重复 key。

### 6.2 Undo, Redo and Publish

```text
DraftMutationRequestV1
  contractVersion
  clientRequestId
  expectedHeadSequenceNo
  expectedDocumentHash

PublishRequestV1 = DraftMutationRequestV1
```

Undo/Redo 请求不接受 target batch 或 commands。服务端从当前 head 计算合法目标并在事务内复核。Publish 的 renderer/runtime/kernel 版本由服务端 compatibility matrix 选择并在 render run 上冻结，客户端不能指定。

### 6.3 Conversation message and Apply

```text
CreateAiMessageRequestV1
  contractVersion
  clientRequestId
  expectedHeadSequenceNo
  expectedDocumentHash
  content: string[1..8000]
  selection: PrototypeSelectionV1

ApplyAiProposalRequestV1
  contractVersion
  clientRequestId
  expectedHeadSequenceNo
  expectedDocumentHash
  expectedCandidateObjectHash
  expectedPreviewArtifactHash
```

Apply 不接受 commands；它只能应用 run 已持久化并预览过的 proposal。

### 6.4 Initial generation

Create request 使用 `RequirementsGenerationRequestV1 | RepositoryGenerationRequestV1` discriminated union。

```text
ConfirmGenerationBlueprintRequestV1
  contractVersion
  clientRequestId
  expectedBlueprintVersion
  expectedBlueprintHash

AcceptGenerationCandidateRequestV1
  contractVersion
  clientRequestId
  expectedCandidateObjectHash
  expectedPreviewOutputHash
  expectedSourceFingerprint
```

Confirm 在创建 Foundation run 的同一 SQLite 事务内复核 blueprint version/hash，并且必须在
`awaiting_confirmation` 状态门之前按 `clientRequestId` 和完整 canonical request hash 查询既有
Foundation scheduling operation：同请求在 operation 完成后返回当前权威 job snapshot，运行中返回
`generation_confirm_in_progress`，相同 request ID 不同 body 返回
`generation_confirm_idempotency_conflict`。Accept 在 job、document、draft、checkpoint 和 terminal
evidence 的同一事务内复核 candidate、preview 和 source fingerprint。Accept 必须先按
`clientRequestId` 和完整 canonical request hash 查询既有 operation：同请求成功重试返回原
document/draft/checkpoint；相同 request ID 不同 body 返回
`generation_accept_idempotency_conflict`，不能先因 job 已是 `accepted` 而拒绝响应丢失后的重试。

### 6.5 Error envelope

```text
PrototypeErrorResponseV1
  contractVersion
  correlationId
  operationId | null
  error
    code
    message
    retryable
    currentHeadSequenceNo | null
    currentDocumentHash | null
    resourceUrl | null
```

`retryable` 由稳定 error-code registry 决定，不由捕获的 exception 动态猜测。

### 6.6 Operation outcome recovery

```text
GET /api/projects/{projectId}/structured-prototype-operations/outcome
  ?operationKind=PrototypeOperationKind
  &clientRequestId=ClientRequestId

OperationOutcomeResponseV1
  contractVersion: 1
  known: true
  terminal: boolean
  operationId, operationKind, projectId
  resourceKind, resourceId | null
  clientRequestId, correlationId, parentOperationId | null
  status, phase, attempt
  requestManifestHash, configManifestHash
  resultManifestHash | null, failureEvidenceHash | null, errorCode | null
  createdAt, startedAt | null, completedAt | null
```

查询键严格为 `projectId + operationKind + clientRequestId`。未知请求和跨项目请求都返回
`404 operation_outcome_unknown`，不能泄漏另一项目的 operation。客户端对所有结构化原型请求使用
总 deadline；deadline、断网或响应丢失后必须保留持久化 pending descriptor 和编辑锁。只有查询到
terminal outcome，并重新读取对应 current draft/runtime/publication/job/thread 收敛到权威资源后，才能
清除 pending；`unknown` 或非 terminal outcome 不能被当作失败，也不能换 request ID 重发。

实现证据：前端 outcome parser 拒绝未知字段、身份漂移以及 status/terminal/时间/证据不一致；
localStorage pending descriptor 使用严格 schema，损坏时保持可见错误和编辑锁。Studio、AI
send/apply/reject、generation start/confirm/accept/delete 都使用同一 pending/outcome 协议，恢复路径
不存在接受 non-terminal outcome 的旁路。

## 7. Claude submission contracts

### 7.1 Capability claims

MCP bearer capability 的签名 claims：

```text
jti
issuer
audience = prototype-ui-engineer-mcp
project_id
job_id | null
edit_run_id | null
run_id
item_id
task_id
execution_process_id
task_kind
allowed_tool
expected_contract_version
staging_root_fingerprint
max_bytes
issued_at
expires_at
nonce
```

Store 只保存 `sha256(jti)`、claims hash、issued/consumed/revoked timestamps 和 request hash，不保存 bearer value。Capability 仅 loopback、单 task、单 tool、单 item、短期有效。

### 7.2 Staged artifact manifest

```text
StagedPrototypeArtifactManifestV1
  manifestVersion: 1
  projectId
  jobId | null
  editRunId | null
  runId
  itemId
  taskId
  executionProcessId
  taskKind
  payloadType
  payloadContractVersion
  relativePath
  stagingByteHash: Sha256
  byteSize: ByteSize
  complete: true
```

`stagingByteHash` 是 staging 文件原始字节的 SHA-256；object `content_hash` 是解析并 canonicalize 后字节的 SHA-256，两者是不同证据。`relativePath` 必须落在 capability 绑定 staging root 内。服务端拒绝 absolute path、`..`、symlink、hardlink escape、非 regular file、size/hash 不符和 `complete != true`。

### 7.3 MCP tools

```text
finalize_prototype_blueprint(manifest)
finalize_prototype_foundation(manifest)
finalize_prototype_page(manifest)
finalize_prototype_repair(manifest)
submit_prototype_assistant_outcome(outcome)
```

工具名必须与 capability `allowed_tool` 完全一致。Finalization 返回：

```text
SubmissionReceiptV1
  submissionId
  requestHash
  acceptedAt
  status: staged
```

`staged` 只表示 MCP 边界接收成功，不表示 schema/semantic validation、object registration 或业务 job 成功。

### 7.4 MCP idempotency

- 首次调用在事务内消费 capability jti 并写 submission request hash/receipt。
- 网络重试使用同一个 jti 和相同 canonical args 时返回同一 receipt。
- 同一个 jti 使用不同 args 返回 `submission_conflict`。
- 其他 task/item/tool、过期、已撤销或未知 jti 返回 `submission_scope_violation`。
- Duplicate finalization 不产生第二个 output；同 item/attempt 只能有一个 accepted submission。
- Cancel 提交后撤销 capability；晚到请求只写安全 audit outcome，不进入 validation。

### 7.5 Assistant outcome

```text
PrototypeAssistantOutcomeV1 =
  AnswerOutcome {kind=answer, message}
  ClarificationOutcome {kind=clarification, message, questions[1..3]}
  CommandProposalOutcome {
    kind=commandProposal,
    summary,
    batch: DomainCommandBatchV1,
    affectedEntityIds
  }
```

Outcome 上限 256 KiB。`affectedEntityIds` 只是声明，服务端按 command execution 重新计算并要求集合一致。

## 8. Generation artifact contracts

Blueprint、Foundation 和 Page 的业务字段沿用 [`ai-generation-design.md`](ai-generation-design.md)，并增加统一 envelope：

```text
GeneratedArtifactEnvelopeV1<T>
  generationContractVersion: 1
  jobId
  runId
  itemId
  taskKind
  contextObjectHash
  sourceFingerprint | null
  payload: T
```

Envelope identity 必须和 capability、task/process 和 SQLite item 完全一致。Claude 不提交 output hash 字段；外层 staging manifest 对完整 canonical envelope 计算 hash。

Page `localKey` 在 page 内唯一。Foundation component key 和 blueprint page/flow/navigation keys 全局唯一。Assembler 输入是按 blueprint page order 排列的 object hash 列表，不能依赖任务完成时间或数据库无排序查询。

## 9. Operation evidence contracts

每个 application step 按以下顺序执行：

```text
persist step running(input/config hashes)
  -> commit
  -> execute pure/external action
  -> persist succeeded(output/evidence hash) or failed(error/failure hash)
  -> commit
```

下游 step 只有在查询到上游 `succeeded` 和 completion evidence 后才能启动。纯计算也必须记录版本与 hash；允许在一个短事务内同时完成极小纯步骤，但仍要产生独立 event ordinals。

`final_runtime_wire_input_hash` 对 runtime adapter 实际发送内容计算，而不是只对 application prompt template。Claude task/process、MCP submission、validation 和 object registration 使用不同 step IDs，不能合并成一个模糊的 `generating` 日志。

## 10. RendererContractV1

### 10.1 Input manifest

```text
RendererInputManifestV1
  rendererVersion
  rendererEnvironmentVersion
  runtimeCoreVersion
  runtimeCoreBundleHash
  stateMachineKernelVersion
  renderRuntimeImageHash
  browserVersion
  fontPackHash
  viewportProfileHash
  documentObjectHash
  documentSchemaVersion
  assetObjectHashes[]
  sandboxPolicyVersion
  outputLocale
```

资产 hash 按 asset ID 排序。Renderer 禁止读取当前时间、随机数、网络、未列出的环境变量或 mutable “latest” asset。

### 10.2 Deterministic mapping

- 每个 structured node 输出 `data-prototype-node-id`，DOM 顺序与 document 数组顺序相同。
- DOM id、CSS class suffix 和 BehaviorRule binding 由 entity ID 确定性派生，不使用随机值。
- Design tokens 按 canonical key order 输出 CSS custom properties。
- Page route table 按 document page order 输出，导航 target 只通过 page ID 解析。
- BehaviorRule trigger/guard/effects 和 scenarios 以 canonical runtime definition 嵌入；preview 只加载 input manifest 固定的 runtime core bundle hash。
- Unknown node/schema/renderer compatibility 直接 preflight 失败，不输出占位节点。
- CodeBlock 使用独立 `srcdoc` iframe 和固定 CSP/sandbox flags；payload 不拼入 host script context。
- Content-addressed assets 只从 input manifest 解析，不允许 runtime external URL。

### 10.3 Output manifest

```text
RendererOutputManifestV1
  rendererVersion
  rendererEnvironmentVersion
  runtimeCoreVersion
  runtimeCoreBundleHash
  stateMachineKernelVersion
  inputManifestHash
  documentObjectHash
  artifactId
  files
    relativePath
    byteSize
    contentHash
  bundleHash
  visualPreflightReportHash
  completedAt
```

`completedAt` 存在 manifest/DB，不写入生成 HTML/CSS/JS，因此不影响 bundle hash。Files 按 relative path 排序后计算 bundle hash。

### 10.4 Preflight and visual proof

Preflight 至少验证：

- document/renderer schema compatibility。
- 所有 asset 可读取且 hash 一致。
- route、navigation、BehaviorRule、view/form binding 和 DOM node binding 完整。
- HTML/CSS/JS 文件可解析，CSP/sandbox policy 生效。
- 固定 desktop/mobile viewport 的页面无加载错误、空白主画布和非预期水平溢出。
- browser console error、page error、failed request 均为零；被策略明确阻止的外部请求单独记录并导致失败。

视觉 pixel hash 只有在相同 render runtime image/browser/font/viewport 下比较。环境不同只能创建新 render run，不能声称是相同 renderer evidence。

## 11. Compatibility matrix

启动时装载显式矩阵：

```text
document_schema_version
  -> supported command_contract_versions
  -> supported runtime_schema/core_versions
  -> supported validation_ruleset_versions
  -> supported renderer_versions
  -> supported sandbox_policy_versions
```

Publish/preview 在创建 run 前选定一行并持久化。矩阵变化不影响既有 run；旧 renderer 被移除前必须保证 published revision 仍可读取既有 artifact，重渲染能力可以明确标为 unavailable。

## 12. Contract fixtures and tests

实现阶段必须建立共享 fixtures，至少覆盖：

- 每种 node、command、assistant outcome 和 generation artifact 的合法最小/最大样本。
- 每个 discriminator 的 unknown value、extra field、错误 ID kind、重复 key 和边界长度拒绝。
- Python Pydantic parse -> canonical JSON -> TypeScript parse -> canonical JSON hash 不变。
- 相同 batch/client request 的确定性 entity IDs；不同 request 不碰撞。
- Command inverse round-trip 回到原 document hash。
- MCP exact retry 返回同 receipt，different-args retry 冲突，跨 task/item/tool token 拒绝。
- Staging path escape、symlink、size/hash/identity mismatch 全部拒绝。
- Assembler 对相同 ordered objects 产生相同 candidate hash。
- Renderer 对相同 input/environment manifest 产生相同 bundle hash。
- Shared runtime core 对相同 document/scenario/event fixtures 在浏览器和 backend Node worker 产生相同 state hashes。
- 每个成功 mutation 可由 operation/replay manifest 定位 request、base、command、result 和 renderer evidence。
