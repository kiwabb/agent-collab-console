# 结构化原型 Checkpoint 与命令日志设计

## 1. 结论

结构化原型不把完整文档长期保存在 SQLite，也不把事实对象写入项目源码目录。运行时采用三层模型：

```text
进程内 active state
  + SQLite 单调命令日志、状态和对象引用
  + managed object store 中不可变压缩 checkpoint
```

- 进程内状态负责低延迟读取、拖拽和预览，它是缓存，不是事实来源。
- SQLite 负责顺序、幂等、乐观并发、工作流状态、对象引用和审计索引。
- object store 负责完整结构化文档、冻结上下文、AI 大型输出和其他不可变对象。
- HTML/CSS/JS 是 renderer 产物，不是 checkpoint，也不能用于恢复结构化文档。
- 恢复结果只允许由“最近 checkpoint + 后续连续命令批次”得到；缺序、哈希错误或不支持的版本必须失败闭合。

这套设计适用于本地单机部署，也保留未来将 managed object store 从本地文件系统替换为 S3 兼容存储的边界。

## 2. 存储布局

本地实现使用应用管理的数据根目录，不使用 Git 项目源码目录：

```text
<data_root>/projects/{project_id}/prototype-store/
  objects/<hash-prefix>/<sha256>.json.zst
  assets/<hash-prefix>/<sha256>
  renders/<document_id>/<artifact_id>/index.html
  tmp/<writer-id>.partial
```

规则：

1. `objects/`、`assets/` 和 `renders/` 由服务端解析 project ownership 后生成，调用方不能提交绝对路径或相对路径。
2. `sha256` 是解压后 canonical bytes 的内容哈希，不依赖 zstd 实现或压缩级别。
3. `storage_hash` 是实际落盘压缩字节的 SHA-256，用于发现磁盘损坏；它不作为业务对象身份。
4. 对象一旦可见就不可覆盖。相同 `content_hash` 的既有对象必须解压并复核，不能仅凭文件名复用。
5. 项目目录导出是独立能力。导出文件不是 canonical object，也不能被数据库作为恢复来源引用。

## 3. Canonical object contract

### 3.1 Canonical bytes

结构化 JSON 对象在写入前执行固定版本的 canonicalizer：

- UTF-8，无 BOM。
- 对象键按 code point 排序。
- 数组保持业务顺序。
- 不写无意义空白。
- 数字必须通过 schema 限定为整数或可确定序列化的小数形式，拒绝 NaN 和 Infinity。
- Unicode normalization 和空值省略规则由 `canonicalizer_version` 固定，不能依赖运行时默认行为。

对象身份：

```text
content_hash = sha256(canonical_bytes)
storage_bytes = zstd(canonical_bytes, storage_codec_version)
storage_hash = sha256(storage_bytes)
```

### 3.2 Object descriptor

SQLite 只保存小型 descriptor 和引用：

```text
PrototypeObjectRecord
  content_hash
  project_id
  media_type
  storage_codec: zstd
  storage_codec_version
  canonical_byte_size
  stored_byte_size
  storage_hash
  storage_key
  created_at
```

Object record 只描述内容和存储编码，不绑定业务 schema。`prototype_object_references` 的 `payload_type` 描述 canonical bytes 应使用的 schema，`role` 描述 candidate、checkpoint 或 revision 生命周期。首版 payload type 包括：

```text
prototype_document
generation_request_manifest
generation_context_manifest
generation_blueprint
generation_foundation
generation_page
ai_edit_context_manifest
agent_submission
validation_report
replay_manifest
prototype_runtime_state
runtime_transition_report
runtime_replay_manifest
```

因此 generation candidate、AI edit preview、draft checkpoint 和 revision 可以引用同一个 object，并都声明 `payload_type=prototype_document`。如果两种 payload schema 恰好产生完全相同的 canonical bytes，也可以共享同一 storage object，但每个 owner reference 仍声明自己的 payload type/schema 并在读取时重新严格校验。

同一项目内，同一个 `content_hash` 只对应一组 canonical bytes，数据库主键为 `(project_id, content_hash)`。不同项目即使内容相同也保持独立 ownership、storage key 和授权边界，不跨项目复用引用。既有对象的内容、media type 或 codec descriptor 不匹配时拒绝注册，不静默覆盖。

## 4. SQLite 事实模型

### 4.1 prototype_documents

```text
id
project_id
title
published_revision_no | null
active_draft_id | null
created_at
updated_at
```

### 4.2 prototype_drafts

```text
id
document_id
base_revision_no | null
status: active | publishing | closed | corrupt
head_sequence_no
head_document_hash
latest_checkpoint_id
publish_revision_no | null
created_at
updated_at
closed_at | null
```

`head_sequence_no` 是草稿唯一的并发版本，不再额外维护含义重复的 `draft_version`。新草稿从 sequence `0` 的 checkpoint 开始。所有写请求携带 `expected_head_sequence_no`。

### 4.3 prototype_checkpoints

```text
id
document_id
draft_id | null
revision_id | null
checkpoint_kind: draft | revision | generation_accept | ai_apply
checkpoint_sequence_no
document_object_hash
document_schema_version
command_contract_version
document_hash
created_by_operation_id
created_at
```

约束：

- `UNIQUE(draft_id, checkpoint_sequence_no)`。
- `document_hash = document_object_hash`，字段同时保留是为了让领域查询不依赖通用对象表命名。
- draft checkpoint 的 sequence 不能大于 draft head。
- revision checkpoint 必须与 revision 一一对应。
- checkpoint 行只能引用已完成写入并通过 read-back 校验的 object。

### 4.4 prototype_command_batches

```text
id
draft_id
base_sequence_no
result_sequence_no
client_request_id
origin: user | ai | system
operation_kind: forward | undo | redo
target_batch_id | null
command_contract_version
commands_json
inverse_commands_json
command_batch_hash
base_document_hash
result_document_hash
operation_id
created_at
```

约束：

- `result_sequence_no = base_sequence_no + 1`。
- `UNIQUE(draft_id, result_sequence_no)`。
- `UNIQUE(draft_id, client_request_id)`。
- 行只追加，不更新 status，不删除，不改写 commands。
- `inverse_commands_json` 由服务端在首次应用时计算，客户端和 Claude 都不能提供。
- `command_batch_hash` 覆盖 contract version、draft、base/result sequence、origin、operation kind、target、commands 和 inverse commands 的 canonical envelope。

### 4.5 prototype_objects 与 prototype_object_references

`prototype_objects` 保存 object descriptor。`prototype_object_references` 保存统一反向引用：

```text
owner_kind
owner_id
role
project_id
content_hash
payload_type
schema_version
created_at
PRIMARY KEY(project_id, owner_kind, owner_id, role, content_hash, payload_type, schema_version)
```

owner 包括 checkpoint、generation job/run/item、AI edit run、render run、runtime session/checkpoint 和 replay manifest。GC 只依据 durable references 建立 live set，不解析普通日志或 Agent trajectory。

## 5. 进程内 active state

`ActivePrototypeState` 至少包含：

```text
draft_id
head_sequence_no
document_hash
validated PrototypeDocument
loaded_checkpoint_id
loaded_checkpoint_sequence_no
applied_tail_batch_ids[]
schema_version
command_contract_version
```

缓存规则：

1. 首次读取、缓存失效或冲突后，从 durable store 恢复，不能把旧内存状态强行覆盖数据库 head。
2. 每次提交前，Store 在事务内再次比较 `expected_head_sequence_no` 和 `head_document_hash`。
3. 事务成功后才能向调用方确认保存。事务结果不确定时必须查询 `(draft_id, client_request_id)` 对账。
4. 进程崩溃可以丢缓存，但不能丢已确认命令。
5. 多进程下服务内锁只是减少冲突；顺序和幂等由 SQLite 唯一约束与事务保证。

## 6. 命令提交

一次 UI 操作产生一个领域批次：

- 拖拽过程中鼠标移动只改变前端临时状态；drop 后提交一个最终 `moveNode`。
- 页面排序 drop 后提交一个 `reorderPage`。
- 属性输入可以在 blur、Enter 或明确 debounce commit 点形成一个批次，不能把每次 keypress 都作为不可撤销业务动作。
- AI Apply 提交一个完整、原子的命令批次。

提交算法：

```text
1. Interface 严格校验请求和 client_request_id。
2. 创建 durable operation，冻结 request manifest hash。
3. 从 active state 取得 base document、head sequence 和 hash。
4. 纯函数应用 commands，计算 inverse、result document 和 hashes。
5. 完整 schema、语义、引用、scope 和安全校验。
6. BEGIN IMMEDIATE。
7. 查询既有 client_request_id；存在则返回原结果。
8. 重查 draft status、head sequence 和 base hash。
9. 插入 result_sequence_no=head+1 的不可变 batch。
10. 更新 draft head sequence/hash 和对象引用索引。
11. 追加 operation completion evidence，COMMIT。
12. 更新进程内 active state，并向前端返回权威 head。
```

步骤 3 至 5 不持有 SQLite 事务。步骤 8 冲突时整个操作返回 `draft_conflict`，调用方用服务端返回的最新 head snapshot 恢复。

## 7. Undo 与 Redo

Undo/Redo 不修改旧批次状态：

- Undo 找到当前线性历史中最近可撤销的 forward/redo batch，重新校验其 inverse commands，并追加一个 `operation_kind=undo`、`target_batch_id=<原批次>` 的补偿批次。
- Redo 只在当前 head 的最后一个用户历史动作是尚未被后续 forward 命令分叉的 undo 时可用；它追加一个 `operation_kind=redo` 的新批次。
- Undo 后提交普通 forward batch，会自然形成新分支，之前的 undo 仍是审计历史，但 Redo 不再合法。无需把旧行标成 `abandoned`。
- 每个补偿或 redo 批次都有自己的 sequence、hash、inverse 和结果文档 hash，因此可以和普通编辑一样恢复。
- 发布不会改写历史。发布后的新 active draft 从发布 revision checkpoint 的 sequence `0` 开始新的编辑时间线。

客户端可以请求 Undo/Redo，但不能指定任意 commands。服务端根据 head 计算目标，并在事务内重新确认目标仍然有效。

## 8. Checkpoint 策略

触发条件采用“任一满足即创建”：

- active draft 自上次 checkpoint 后 dirty 达 30 秒。
- checkpoint 后累计 50 个命令批次。
- 关闭文档或应用正常退出。
- Publish freeze 前。
- 首次 AI generation candidate 被接受时。
- AI proposal Apply 时，直接把已验证 candidate object 注册为该 result sequence 的 checkpoint。

硬约束：checkpoint 后的 replay tail 不得超过 200 个批次。准备追加第 201 个尾批次前必须先为当前 head 创建 checkpoint；checkpoint 失败则拒绝新命令，返回 `checkpoint_required_unavailable`。

Checkpoint 创建算法：

```text
1. 在 sequence H 取得已验证 active state。
2. canonicalize，计算 document hash，确认等于 active state hash。
3. 压缩并写入同目录临时文件。
4. fsync 文件，以不可覆盖方式安装到 content-addressed path，再 fsync 目录。
5. read-back、解压、校验 storage hash、content hash、schema 和完整文档。
6. BEGIN IMMEDIATE，确认 draft head 仍为 H/hash。
7. 注册 object descriptor、checkpoint 和 object reference，更新 latest_checkpoint_id。
8. 追加 checkpoint completion evidence，COMMIT。
```

如果步骤 6 发现 head 已推进，文件是安全 orphan；不能删除可能正被另一个事务引用的对象，由 GC 延迟处理。

## 9. 恢复与确定性重放

恢复算法：

```text
1. 读取 draft 元数据和 latest checkpoint。
2. 读取 object，校验 storage hash，解压并校验 content hash。
3. 按 checkpoint 固定的 schema/canonicalizer 版本校验文档。
4. 查询 (checkpoint_sequence_no, head_sequence_no] 内所有 batches。
5. 要求 sequence 严格连续，首条 base hash 等于 checkpoint hash。
6. 按 command_contract_version 顺序应用每个 batch。
7. 每步校验 command_batch_hash、base hash 和 result hash。
8. 最终 sequence/hash 必须等于 draft head。
9. 成功后建立 active state，并写入 replay evidence。
```

以下情况全部把 draft 标记为 `corrupt` 并拒绝编辑、发布和 AI 上下文构造：

- checkpoint object 缺失、无法解压或 hash 不匹配。
- schema、canonicalizer 或 command contract 版本不可用。
- sequence 缺失、重复、倒序或超过 200 条硬限制。
- 任一 batch hash、base hash 或 result hash 不匹配。
- 重放后完整文档校验失败。
- 最终结果与 draft head 不一致。

系统可以尝试只读诊断：寻找更早的合法 checkpoint 并重放到相同 head。诊断成功后也不能静默改指针；修复必须产生显式 repair operation、管理员确认和新的 checkpoint 证据。

## 10. 发布

Publish freeze 前先保证 head H 已有完全匹配的 checkpoint：

1. 若不存在则按第 8 节写 object 和 checkpoint。
2. 短事务内再次比较 expected head、checkpoint sequence/hash 和幂等请求。
3. 创建 immutable revision，revision 只引用 document object hash/checkpoint，不复制 JSON。
4. draft 进入 `publishing`，创建固定 renderer version 的 render run。
5. renderer 在事务外读取 revision object，产出 immutable artifact。
6. 完成事务写 artifact descriptor、推进 published pointer、关闭旧 draft，并创建以 revision object 为 sequence 0 checkpoint 的新 active draft。

渲染失败时公开指针不变，原 draft 回到 `active`。revision/object 可以保留用于诊断和按同一 renderer version 显式重试。

## 11. AI candidate 与大型 JSON

Claude staging 文件不是长期事实来源。接收大型输出时：

```text
staging file
  -> task/process/submission correlation
  -> strict schema + semantic validation
  -> canonical object write/read-back
  -> SQLite object descriptor + owner reference
  -> staging cleanup
```

- blueprint、foundation、page、assembled generation candidate、AI edit candidate 和冻结 context manifest 都保存为 object reference/hash。
- generation run item 和 AI edit run 不保存完整 `*_json` 列。
- AI edit command proposal可以在 SQLite 保存受限大小的 typed commands；完整 candidate document 只保存 object hash。
- Accept generation candidate 时，候选 object 同时成为新 draft sequence 0 checkpoint。
- Apply AI proposal 时，必须证明 proposed command batch 在 base hash 上得到的 result hash 与 previewed candidate object hash 一致；同一事务追加 batch并把该 object 注册为 result sequence checkpoint。

## 12. GC 与保留

GC 使用 mark-and-sweep，但不能在一次扫描中立即删除新 orphan：

1. 创建 `gc_run_id` 和扫描开始时间。
2. 从所有 object references、active/publishing draft checkpoint、revision、preview retention、运行中 job/run/item 建立 live set hash。
3. 列出 object store 中未进入 live set 且 `mtime < scan_started_at - grace_period` 的对象。
4. 将候选记录到 durable GC run/item，首轮只标记。
5. 第二轮重新计算引用；仍无引用且超过保留期才删除。
6. 删除后记录 content hash、storage key、byte size 和完成证据。

默认保留建议：

- 未引用 orphan grace period：24 小时。
- rejected/stale AI candidate：7 天。
- failed generation item：7 天。
- 普通 Studio/shared runtime session objects：7 天；recorded review：30 天；显式固定的 replay manifest 按项目保留。
- published revision 和其 render artifact：无限期，直到显式删除文档。
- Agent trajectory 按平台审计策略保留，不能作为 object live reference。

GC 失败不影响在线对象；它记录失败并重试。发现引用中的对象缺失时，GC 不继续清理该项目，并发出 `referenced_object_missing` 告警。

## 13. 错误码

```text
object_write_failed
object_readback_failed
object_hash_mismatch
object_hash_collision
object_missing
object_schema_unsupported
checkpoint_required_unavailable
checkpoint_head_conflict
replay_sequence_gap
replay_batch_hash_mismatch
replay_document_hash_mismatch
replay_contract_unsupported
draft_corrupt
gc_live_set_failed
referenced_object_missing
```

这些错误都失败闭合。尤其是 checkpoint、replay 或 live-set 构造异常时，不能继续写命令、发布或删除对象。

## 14. 最小测试矩阵

- 相同 canonical document 在不同键顺序和空白下得到相同 content hash。
- zstd 参数变化不改变 content hash，但 storage hash 可以不同；同一路径已有合法对象时复用其既有 codec/descriptor，不能用新压缩字节覆盖。
- object 写成功、DB 失败只留下可回收 orphan，不留下悬空数据库引用。
- DB 引用永远不会先于 object read-back 成功可见。
- 50 批次和 30 秒 dirty 触发 checkpoint；第 201 个 replay tail 在 checkpoint 失败时被拒绝。
- 100 次修改不会从 sequence 0 重放 100 次；恢复只重放最近 checkpoint 后的 tail。
- 拖拽过程只持久化一个最终 move command。
- Undo/Redo 追加补偿批次且不修改历史行；Undo 后 forward edit 禁止 Redo。
- sequence 缺失、batch hash 错误、object 损坏和不支持版本都将 draft 标为 corrupt。
- 相同 checkpoint 和 batches 在干净进程中重放出相同 final hash。
- AI Apply 的 result hash 与 preview candidate 不一致时整笔事务拒绝。
- Publish 的 revision 引用固定 object，renderer 失败不会推进 public pointer。
- GC 不删除有引用对象、新 orphan 或刚取消但仍在 retention 期内的 candidate。
