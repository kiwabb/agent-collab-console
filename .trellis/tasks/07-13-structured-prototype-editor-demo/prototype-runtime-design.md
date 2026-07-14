# 结构化原型业务运行时设计

## 1. 结论

结构化原型必须同时包含两种事实：

```text
Design document：页面、组件、布局、导航和流程可视化
Runtime definition：状态、数据、角色、事件、条件和效果
```

只有 design document 时，产品只能验证“页面长什么样、点击后跳到哪里”；加入 runtime definition 后，产品才能验证“什么角色在什么状态下执行什么操作，数据如何变化，为什么走到这个结果”。

首版业务运行时采用受限、类型化、确定性的规则模型，不执行任意 JavaScript，不连接真实 API，不模拟真实认证。浏览器预览和后端重放使用同一份 versioned TypeScript runtime core，避免前后端各写一套解释器产生语义漂移。

## 2. 目标与非目标

### 2.1 目标

- 表达常见后台业务流程：填写、校验、提交、状态变化、角色操作、审批/驳回、列表数据变化和结果提示。
- 产品经理可以从 Flow 模式查看和调整 trigger、guard、effect、目标页面与业务状态。
- AI generation 和 conversation edit 可以生成或修改严格 runtime contracts，不能写隐藏脚本。
- 相同 document/scenario/runtime version/event sequence 必须得到相同 transition/state hashes。
- Studio preview 和明确录制的 review session 在刷新、断线和服务重启后可恢复、可解释、可重放。

### 2.2 首版不做

- BPMN 全规范、补偿事务、并行网关、定时器和长事务编排。
- 任意表达式字符串、`eval`、用户脚本、插件代码或自定义网络请求。
- 真实 API、真实数据库、真实身份认证、真实权限控制或生产数据。
- 多人同时操作同一个 runtime session。
- 随机数、真实系统时间和不可固定的外部输入。
- 把 CodeBlock 内部状态当作结构化 runtime state。

## 3. 唯一事实来源

### 3.1 RuntimeDefinitionV1

`PrototypeDocumentV1` 增加 required `runtime`：

```text
RuntimeDefinitionV1
  runtimeSchemaVersion: 1
  roles: RuntimeRoleV1[1..20]
  variables: RuntimeVariableDefinitionV1[0..100]
  entitySchemas: MockEntitySchemaV1[0..30]
  forms: RuntimeFormDefinitionV1[0..50]
  viewBindings: RuntimeViewBindingV1[0..300]
  rules: BehaviorRuleV1[0..300]
  scenarios: RuntimeScenarioV1[1..30]
  flowLayout: RuntimeFlowLayoutV1
```

Runtime definition 是 document 的一部分，参与 document hash、checkpoint、revision、AI context、validation 和 renderer compatibility。

### 3.2 Flow 不是第二份规则

可执行事实只存在于 `BehaviorRuleV1`：

- Flow canvas 的边引用 `ruleId`，不复制 trigger/guard/effects。
- Flow 节点引用 page、overlay、business state 或 decision projection。
- 拖动 Flow 节点只修改 `flowLayout`，不改变业务执行结果。
- 在画布创建业务连接时，后端实际创建一个 BehaviorRule；删除连接实际删除或解绑 rule。
- Renderer 和 runtime engine 不读取 SVG edge、坐标或展示 label 决定行为。

这样不会出现“画布显示 A -> B，但按钮实际执行 A -> C”的双事实来源。

## 4. 类型化运行时值

### 4.1 RuntimeValueV1

运行时不接受任意 JSON object。值使用 discriminated union：

```text
NullValue       {type=null}
BooleanValue    {type=boolean, value}
IntegerValue    {type=integer, value}
DecimalValue    {type=decimal, value: DecimalString}
StringValue     {type=string, value}
DateValue       {type=date, value: YYYY-MM-DD}
DateTimeValue   {type=datetime, value: UTC ISO-8601}
EnumValue       {type=enum, value: TechnicalKey}
EntityRefValue  {type=entityRef, schemaId, entityId}
ListValue       {type=list, items: RuntimeValueV1[]}
RecordValue     {type=record, fields: RuntimeFieldValueV1[]}
```

Record fields 按 field key canonical order 保存，key 唯一。Decimal 使用规范字符串，禁止依赖 JSON 浮点序列化。

### 4.2 Variables

```text
RuntimeVariableDefinitionV1
  id
  key
  label
  valueType: RuntimeValueTypeV1
  nullable
  defaultValue
  visibility: session | page
```

Variable key 只用于可读 contract，持久化 rule 引用稳定 `variableId`。修改 key 不破坏 rule。

### 4.3 Mock entities

```text
MockEntitySchemaV1
  id
  key
  label
  fields: MockEntityFieldV1[1..50]
  primaryDisplayFieldId

MockEntityFieldV1
  id
  key
  label
  valueType
  nullable
  enumOptions[]
  validationRules[]
```

Entity record ID 由 scenario fixture 或 create effect 确定性生成。Entity schema 不是数据库迁移，也不能连接真实表。

## 5. Role 与 Scenario

### 5.1 RuntimeRoleV1

```text
id
key
label
description
```

Role 只用于 prototype guard 和场景切换，不是安全权限。UI 必须明确显示“模拟角色”，不能把隐藏按钮误解为真实授权。

### 5.2 RuntimeScenarioV1

```text
id
key
title
description
actorRoleId
startPageId
initialVariables: RuntimeVariableValueV1[]
entityFixtures: MockEntityFixtureSetV1[]
  fixedClock: UTC Timestamp
  seed: string
  scriptedEventBatches: RuntimeScenarioEventBatchV1[0..100]
  expectedMilestones: RuntimeMilestoneV1[]
```

每个 document 至少有一个 scenario。Scenario 固定角色、初始数据、时钟和 seed，是演示重置和重放的起点。

`RuntimeMilestoneV1` 包含 `afterBatchIndex`、typed predicate 和 label。首次 AI generation 至少有一个主 scenario 提供 scripted event batches；Assembler 用 shared runtime core 执行，并要求每个 milestone predicate 在指定 batch 后成立。手工创建的探索场景可以没有 script，但不能被标记为“已验证业务路径”。

`RuntimeScenarioEventBatchV1.events` 只允许 `SetFormFieldScenarioEvent {formId, fieldId, value}`、`FireNodeScenarioEvent {nodeId, event, payload|null}` 和 `SwitchSimulatedRoleScenarioEvent {roleId}`。它不包含 session/client IDs；运行验证时由 harness 按 batch index 确定性生成。Blueprint 阶段使用 technical keys，Assembler 完成 ID 映射后才形成最终 scenario contract。

首版 runtime 不提供随机函数；`seed` 仅用于确定性 entity ID 和未来兼容，不允许调用系统随机源。`fixedClock` 是规则读取的唯一“当前时间”。

## 6. Form 与节点绑定

### 6.1 Form node

`UINodeV1` 增加 `Form` container：

```text
FormNodeV1
  type: Form
  id
  name
  formDefinitionId
  children
  layout fields
```

Input、Select 等可编辑节点增加 optional binding：

```text
RuntimeFieldBindingV1
  formId
  fieldId
```

Button 的 submit trigger 明确引用 form ID。不存在通过 DOM selector 或节点 name 查找表单。

### 6.2 RuntimeFormDefinitionV1

```text
id
key
fields: RuntimeFormFieldV1[1..100]

RuntimeFormFieldV1
  id
  key
  label
  valueType
  initialValue
  validationRules
```

Validation 首版支持：required、min/max length、integer/decimal range、enum membership、date range。Regex、自定义函数和跨字段表达式不进入 MVP；跨字段条件使用 typed predicate。

### 6.3 Runtime view bindings

业务状态通过类型化 binding 映射回节点属性：

```text
RuntimeViewBindingV1
  id
  nodeId
  target: textContent | visibility | disabled | tableRows | selectOptions
  value: RuntimeValueExpressionV1 | RuntimeCollectionExpressionV1
```

Target 与 node type 必须匹配：Text 支持 `textContent`，所有 structured node 支持 boolean `visibility`，Button/Input/Select 支持 boolean `disabled`，Table 支持 `tableRows`，Select 支持 `selectOptions`。同一 node/target 最多一个 binding。

```text
RuntimeCollectionExpressionV1
  schemaId
  filter: RuntimePredicateV1 | null
  sort: {fieldId, direction: asc | desc} | null
  limit: integer[1..200]
```

Filter 中可以使用 `CurrentEntityFieldExpression`，不支持 join、group、aggregate 或任意查询字符串。Runtime binding 的结果覆盖 session 中的静态 node payload，但不修改 design document。

Runtime core 提供：

```text
deriveViewModel(document, runtimeState) -> RuntimeViewModelV1
```

View model 是派生结果，不作为 state authority；每次 transition 记录 `result_view_model_hash`，保证状态变化确实能以相同方式映射到 UI。

## 7. Trigger、Guard 与 Effect

### 7.1 BehaviorRuleV1

```text
BehaviorRuleV1
  id
  key
  name
  enabled
  trigger: RuntimeTriggerV1
  guard: RuntimePredicateV1 | null
  effects: RuntimeEffectV1[1..20]
  guardFalseEffects: RuntimeEffectV1[0..5]
```

同一个 source node/event 在一个 scenario scope 内最多绑定一个 enabled rule。首版不引入 rule priority，避免多个 rule 的隐式执行顺序。

### 7.2 Trigger

```text
NodeEventTrigger
  kind: nodeEvent
  nodeId
  event: click | changeCommitted | submit | rowActivated
  formId | null

PageEnterTrigger
  kind: pageEnter
  pageId
```

输入框 keypress 是浏览器临时状态，不逐键持久化。Blur、选择完成或 Submit 前 flush 形成 `changeCommitted`。Submit event batch 必须先包含所有未提交 field changes，再执行 submit rule。

Runtime event union：

```text
FieldValueCommittedEvent {kind=fieldValueCommitted, nodeId, formId, fieldId, value}
NodeActivatedEvent {kind=nodeActivated, nodeId, event: click|submit, payload: null}
TableRowActivatedEvent {kind=tableRowActivated, nodeId, entityRef}
SwitchSimulatedRoleEvent {kind=switchSimulatedRole, roleId}
```

`TableRowActivatedEvent.entityRef` 必须存在于该 Table 当前 derived view binding 的 rows 中，且 schema ID 匹配；客户端不能用事件 payload 访问未展示或其他项目的 entity。

`SwitchSimulatedRoleEvent` 只允许 authenticated Studio preview/recorded review 使用，用于在同一 mock state 上演示申请人到审批人的交接。它不是 BehaviorRule trigger，也不能由页面按钮或 effect 发出；shared preview 是否允许切换由创建 session 时的固定 policy 决定，默认禁止。

### 7.3 Value expression

```text
RuntimeValueExpressionV1 =
  LiteralExpression
  VariableExpression {variableId}
  FormFieldExpression {formId, fieldId}
  EntityFieldExpression {schemaId, entityIdExpression, fieldId}
  CurrentRoleExpression
  EventValueExpression
```

Expression 是 AST，不是字符串。每个 expression 在 schema validation 时可以确定返回类型；类型不匹配时 document 不能进入 preview_ready/published。

### 7.4 Predicate

```text
RuntimePredicateV1 =
  AllPredicate {items[1..10]}
  AnyPredicate {items[1..10]}
  NotPredicate {item}
  ComparePredicate {operator: eq|ne|gt|gte|lt|lte, left, right}
  ExistsPredicate {value}
  RoleIsPredicate {roleId}
  FormValidPredicate {formId}
```

Predicate 最大嵌套深度 8、总节点数 50。没有字符串 parser、函数调用、属性路径或隐式类型转换。

### 7.5 Effect

```text
RuntimeEffectV1 =
  SetVariableEffect {variableId, value}
  ResetFormEffect {formId}
  ValidateFormEffect {formId, failurePolicy=stopRule}
  CreateEntityEffect {schemaId, resultVariableId, values[]}
  UpdateEntityEffect {schemaId, entityId, updates[]}
  DeleteEntityEffect {schemaId, entityId}
  NavigateEffect {targetPageId}
  BackEffect
  OpenOverlayEffect {targetNodeId}
  CloseOverlayEffect {targetNodeId}
  OpenDrawerEffect {targetNodeId}
  CloseDrawerEffect {targetNodeId}
  SetTabEffect {targetNodeId, tabKey}
  NotifyEffect {level: info|success|warning|error, message}
```

Effects 按数组顺序应用到 candidate state。`ValidateFormEffect` 失败时写入 typed form errors 并停止后续 effects；这是成功处理的 `validation_failed` transition，不是系统异常。

Create entity ID：

```text
uuid5(PROTOTYPE_RUNTIME_ENTITY_NAMESPACE,
      session_id + ":" + result_sequence_no + ":" + effect_index)
```

同一事件重放得到相同 ID。

## 8. Runtime state

```text
PrototypeRuntimeStateV1
  runtimeStateSchemaVersion: 1
  sessionId
  scenarioId
  scenarioHash
  pinnedDocumentObjectHash
  runtimeCoreVersion
  runtimeCoreBundleHash
  stateMachineKernelVersion
  sequenceNo
  actorRoleId
  currentPageId
  navigationStack: EntityId[]
  variableValues: RuntimeVariableValueV1[]
  entitySets: RuntimeEntitySetV1[]
  formStates: RuntimeFormStateV1[]
  overlayState: RuntimeOverlayStateV1[]
  activeTabs: RuntimeTabStateV1[]
  notifications: RuntimeNotificationV1[]
```

所有集合按定义 ID 或稳定业务顺序 canonicalize。State 不保存 DOM、React state、焦点或动画进度。

## 9. 单一运行引擎

### 9.1 Shared TypeScript core + proven state-machine kernel

实现一个无 UI、无网络、无文件访问的 versioned TypeScript package，并使用精确 pin 的 XState v5 作为 transition/event kernel：

```text
prototype-runtime-core
  createInitialState(document, scenario)
  validateRuntimeDefinition(document)
  applyEvent(document, state, eventBatch)
  deriveViewModel(document, state)
  canonicalizeRuntimeState(state)
  hashRuntimeState(state)
```

- 自定义代码只负责把 strict RuntimeDefinition 编译成 XState machine，并提供 allowlisted pure guards/actions；document 不能提交 JavaScript function。
- 不使用 XState invoked service、delayed event、系统 clock、actor network 或异步 action。首版所有 effect 同步、纯函数、可确定重放。
- 持久化格式始终是 `PrototypeRuntimeStateV1` 和 domain event/transition reports，不保存 XState 私有 snapshot；升级 XState 不得改变 durable schema。
- 浏览器 Studio/Published Preview 使用固定 bundle hash 的同一 package。
- Python backend 不重新实现 predicate/effect 语义；它在事务外调用 pinned Node worker 执行权威 transition/replay。
- Node worker 输入输出使用 strict JSON contract，不访问网络和项目源码。
- Runtime core 不读取当前时间、locale default、系统随机数或对象枚举的非规范顺序。
- Core version/bundle hash 同时记录在 document compatibility、runtime session 和 transition evidence。

这是复现能力的关键。浏览器 TypeScript + 后端 Python 两套 evaluator 即使单测齐全也会持续产生边界差异，禁止采用；完全手写事件调度/状态机内核也不采用。

本地依赖盘点和引擎选择依据见 [`research/runtime-engine-decision.md`](research/runtime-engine-decision.md)。

### 9.2 Authoritative event path

Studio preview 可以用同一 runtime core 乐观计算 UI，但 durable backend transition 是权威结果：

```text
Browser semantic event
  -> POST event batch(expected sequence/state hash)
  -> backend operation/step running evidence
  -> pinned Node worker applyEvent
  -> strict output + state/transition hash validation
  -> SQLite append event batch + advance session head
  -> optional state checkpoint
  -> response authoritative state/patch/hash + derived view-model hash
  -> browser reconcile
```

后端或 evidence store 不可用时，已录制 session 暂停并保留最后状态；不能继续产生无法重放的隐藏步骤。普通输入法组合/键盘临时状态可以留在浏览器，但提交、blur、选择和点击必须走 semantic event。

## 10. Runtime session persistence

### 10.1 prototype_runtime_sessions

```text
id
project_id
document_id
source_kind: draft | ai_preview | published_revision
source_id
pinned_document_object_hash
runtime_core_version
runtime_core_bundle_hash
state_machine_kernel_version
scenario_id
scenario_hash
status: active | completed | interrupted | corrupt
head_sequence_no
head_state_hash
head_view_model_hash
latest_checkpoint_id
recording_kind: studio_preview | recorded_review | shared_preview
allow_simulated_role_switch
actor_subject_id | null
created_at
updated_at
completed_at | null
```

Session 一旦创建就固定 document object、scenario 和 runtime core。Draft 后续编辑不会改变已开始 session；用户点击“使用最新草稿重开”创建新 session。

### 10.2 prototype_runtime_event_batches

```text
id
session_id
client_event_id
base_sequence_no
result_sequence_no
events_json
event_batch_hash
matched_rule_ids_json
guard_report_hash
effect_report_hash
outcome: applied | guard_false | validation_failed
base_state_hash
result_state_hash
result_view_model_hash
runtime_core_version
runtime_core_bundle_hash
state_machine_kernel_version
operation_id
created_at
```

约束：

- `UNIQUE(session_id, client_event_id)`。
- `UNIQUE(session_id, result_sequence_no)`。
- `result_sequence_no = base_sequence_no + 1`。
- Event batch、rule/guard/effect reports 是不可变证据，不修改历史。

### 10.3 Runtime checkpoints

完整 runtime state 保存为 `payload_type=prototype_runtime_state` 的 managed object。采用与 design draft 相同原则：

- 30 秒 dirty。
- 50 event batches。
- session close/complete。
- recorded review 创建分享点。
- replay tail 硬限制 200，超出前 checkpoint 失败则暂停 session。

恢复加载最近 state checkpoint，按 sequence 重放 event batches，并逐步比较 batch、guard、effect 和 state hashes。任一不一致将 session 标为 `corrupt`。

## 11. Runtime API

```text
POST /api/prototype-documents/{document_id}/runtime-sessions
GET  /api/prototype-runtime-sessions/{session_id}
POST /api/prototype-runtime-sessions/{session_id}/event-batches
POST /api/prototype-runtime-sessions/{session_id}/reset
POST /api/prototype-runtime-sessions/{session_id}/complete
GET  /api/prototype-runtime-sessions/{session_id}/events
POST /api/prototype-runtime-sessions/{session_id}/diagnostic-replays
```

Create session request 必须携带 source object hash、scenario ID 和预期 runtime version。Event request：

```text
RuntimeEventBatchRequestV1
  contractVersion
  clientEventId
  expectedSequenceNo
  expectedStateHash
  events: RuntimeEventV1[1..20]
```

Response 包含 operation ID、result sequence/state/view-model hashes、outcome、matched rule/effect summaries、完整 authoritative runtime state 和 derived view model。409 返回 current sequence/state/view-model hashes。

Reset 不删除历史；它关闭旧 session 并基于同一或新 scenario 创建新 session。这样“重置”也可观察，不会让一条 session timeline 突然回到 sequence 0。

## 12. Flow mode

### 12.1 画布语义

MVP Flow canvas 支持四种 projection node：

```text
screen      page/overlay/drawer/tab
state       enum variable or entity status value
decision    predicate summary
scenario    scenario start
```

Edge 始终引用 BehaviorRule。选中 edge 的 inspector 编辑：

- trigger。
- guard。
- ordered effects。
- source/target screen。
- business state before/after。
- applicable simulated role。

当前页面卡片 Flow 原型可以保留作为第一版 shell，但在加入 runtime 前不能对外宣称已支持业务流程设计。

### 12.2 Commands

Runtime/Flow 增加领域命令：

```text
addRuntimeVariable
replaceRuntimeVariable
removeRuntimeVariable
addRuntimeRole
replaceRuntimeRole
removeRuntimeRole
addMockEntitySchema
replaceMockEntitySchema
removeMockEntitySchema
addRuntimeForm
replaceRuntimeForm
removeRuntimeForm
addRuntimeViewBinding
replaceRuntimeViewBinding
removeRuntimeViewBinding
addRuntimeScenario
replaceRuntimeScenario
removeRuntimeScenario
addBehaviorRule
replaceBehaviorRule
removeBehaviorRule
bindNodeRuntimeField
unbindNodeRuntimeField
setRuntimeFlowNodePosition
```

这些命令继续使用 design draft 的单调 journal、expected head sequence/hash、atomic batch 和服务端 inverse。删除被 rule/scenario/form 引用的 definition 必须拒绝，直到引用被移除或显式重定向。

## 13. AI generation 与对话修改

### 13.1 Blueprint

`GenerationBlueprintV1` 增加：

```text
roleIntents[]
entityIntents[]
variableIntents[]
formIntents[]
viewBindingIntents[]
behaviorIntents[]
scenarioIntents[]
```

行为 intent 使用 page/flow/entity technical keys，不能引用尚未生成的 node ID。

### 13.2 Page output

`GeneratedPageV1` 增加：

```text
formBindings[]
viewBindings[]
behaviorBindings[]

BehaviorBindingV1
  sourceNodeKey
  event
  behaviorIntentKey
```

页面 task 只把 node local key 绑定到已确认 blueprint behavior intent，不能私自创建跨页面业务能力。

### 13.3 Deterministic runtime assembly

Assembler：

1. 将 blueprint role/entity/variable/form/scenario intents 映射为稳定 IDs。
2. 将 page form/view/behavior bindings 的 local keys 解析为 node IDs。
3. 编译 typed view expressions、predicates/effects，拒绝未绑定 intent。
4. 确保每个 scenario 有合法起始页、角色和完整 fixture。
5. 运行 runtime core definition validation。
6. 为每个 scenario 创建 initial state 并计算 hash；对 scripted scenario 执行 event batches 并验证 milestones，保存 final state/transition report hashes。

Runtime assembly 是纯确定性应用逻辑，不调用 Claude repair 补齐未声明行为。

### 13.4 Conversation edit

AI context 根据 scope 加载相关 rule、variable/entity/form definitions、scenario 和最近一次可选 recorded runtime trace。AI 只能返回第 12.2 节的领域命令，不能返回脚本或完整 runtime replacement。

当用户说“审批通过后状态没变化”，可附加 runtime session/transition ID。Context Builder 加载对应 frozen transition report，而不是依赖用户自然语言复述。

## 14. 可观测与复现

每个 semantic event 至少记录：

```text
session/document/scenario/runtime identities
client event + operation IDs
base/result sequence
base/result state hash
event batch hash
matched rule IDs
guard input/result/report hash
每个 effect 的 index、kind、input/output substate hash
result view-model hash
outcome/error code
runtime core version/bundle hash
state-machine kernel exact version
started/completed timestamps
```

Runtime replay manifest：

```text
pinned_document_object_hash
scenario_id + scenario_hash
runtime_core_version + bundle_hash
state_machine_kernel_version
initial_state_object_hash
ordered_event_batch_hashes[]
ordered_transition_report_hashes[]
final_sequence_no
final_state_hash
final_view_model_hash
```

相同 manifest 在 pinned Node worker 中必须得到相同 final state hash。浏览器截图不是 runtime state authority；它可以作为 renderer/visual evidence 附加。

## 15. 隐私与安全

- Runtime 只允许 mock data，UI 明确提示不要输入生产凭据或真实敏感数据。
- 普通 INFO/audit 不记录 form 文本、entity field values 或完整 state；只记录 IDs、hash、outcome 和错误码。
- Exact recorded event/state object 按 project ownership 授权并受 retention 控制。
- Shared preview 使用匿名 session ID，不把 IP、cookie 或浏览器身份写入 runtime state。
- CodeBlock iframe 不能直接读取/修改 host runtime state。未来如需 bridge，只允许 schema-validated event message allowlist；首版关闭 bridge。
- Runtime effects 没有 network、filesystem、clipboard、cookie、storage 或 host command 权限。

默认保留建议：Studio preview 7 天、recorded review 30 天、shared preview 7 天。用户显式固定的 review replay manifest 和关联 objects 按项目保留。

## 16. 失败闭合

- Runtime document/schema/core version 不兼容：不启动 session。
- Source object/scenario hash 不匹配：创建 session 失败。
- Event expected sequence/state hash stale：409，不自动应用到新状态。
- Runtime worker timeout/crash/invalid output：event 不落 journal，session 保持上一个 head。
- Guard false/validation failed：是 typed domain outcome，记录 transition，不映射成 500。
- Event commit 结果不明确：按 `(session_id, client_event_id)` 对账，不重复执行。
- Recovery hash mismatch：session corrupt，停止操作，不跳过 event。
- Evidence/checkpoint hard gate 不可用：session paused/failed closed，不继续无记录演示。

## 17. 最小测试矩阵

### Runtime core

- 每种 value、predicate、effect 的合法/非法类型组合。
- 每种 view-binding target/node/value 类型组合和 collection filter/sort/limit。
- 相同 document/scenario/event sequence 产生相同 initial/final state hash。
- 多角色 scripted scenario 的 role switch、RoleIs guard 和共享 mock entity state 可确定重放。
- 相同 document/state 产生相同 view-model hash，entity update 后 Table/Text/visibility/disabled 派生结果正确。
- Create entity 在重放中生成相同 ID。
- Guard false、validation failed 和 applied outcome 稳定。
- 不读取系统时间、随机数、locale default、网络或环境变量。

### Cross-runtime

- Browser bundle 与 backend pinned Node worker 对共享 fixtures 产生相同 hashes。
- Runtime core bundle hash 不同不能复用既有 session evidence。
- Python 只校验 worker contract，不存在第二套 predicate/effect evaluator。

### Persistence/recovery

- 同 client event retry 不重复 transition。
- 两个客户端竞争同 session 只有一个 sequence 成功。
- 50 events/30 秒/close 触发 checkpoint，201 tail 被 hard gate 拒绝。
- checkpoint + events 恢复逐步匹配 guard/effect/state hashes。
- reset 创建新 session，不删除旧 history。

### Flow/AI

- Flow edge 与 BehaviorRule 一一关联，layout 改动不改变 runtime hash（除 flowLayout document hash）。
- 删除仍被引用的 variable/entity/form/rule 被拒绝。
- Blueprint behavior intent 必须被页面 binding 消费，未绑定不能 candidate ready。
- 首次生成至少一个主 scenario 的 scripted event/milestone 全部通过；失败时不能 candidate ready。
- AI 越 scope、提交脚本、任意表达式或真实 URL 整批拒绝。

### Observability/security

- 每个 semantic event 能按 operation ID 查看 rule/guard/effect/state evidence。
- 普通日志不出现 exact form/entity values。
- CodeBlock、外部 URL 和 network effect 无法修改 runtime。
- Runtime replay mismatch 报告首个 event/effect 分歧且不修改 session。

## 18. 实施顺序

1. 定义 RuntimeValue/Definition/State/Event/Transition strict contracts 和 fixtures。
2. Pin XState v5 exact version，实现 strict definition compiler、共享 TypeScript runtime core 与 deterministic canonical/hash tests。
3. 实现 backend pinned Node worker adapter、session/event/checkpoint store 和 replay。
4. 给 document/command schema 增加 Form、bindings、runtime definitions 和 runtime commands。
5. 给 renderer 接入固定 runtime core bundle 和 runtime input manifest。
6. 实现 Studio session API、场景切换、重置、事件 flush 和错误恢复。
7. 将 Flow edge 改为 BehaviorRule projection，并增加 guard/effect inspector。
8. 扩展 AI blueprint/page contracts、assembler、conversation scope 和 runtime validation。
