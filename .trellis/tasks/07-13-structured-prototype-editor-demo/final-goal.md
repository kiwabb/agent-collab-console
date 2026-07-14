# 结构化原型 MVP 最终目标

## 最终结果

交付一个产品经理可实际使用的端到端结构化原型 MVP：

1. 通过项目绑定的 Claude Code `prototype_ui_engineer` 生成三页采购原型：采购申请列表、创建申请、申请详情。
2. 在 Studio 中拖拽和编辑 `Stack`、`Form`、`Text`、`Input`、`Button`、`Table` 六类语义组件。
3. 通过 AI 对话做受控修改，预览后 Apply 或 Reject；Claude 不直接修改 active draft。
4. 使用申请人和主管两个模拟角色，完整执行“创建采购申请 -> 提交 -> 主管审批通过 -> 列表与详情同步更新”。
5. 结构化文档、领域命令、checkpoint、runtime event、AI task/submission、render 和 publish 每一步都可观测、可恢复、可重放。
6. 发布一个可运行、可分享、由固定 renderer/runtime 版本生成的预览产物。

## MVP 边界

```text
1 个项目
1 个结构化原型文档
3 个页面
2 个模拟角色
1 个 Mock 实体：采购申请
6 类语义组件
1 条脚本化采购审批主场景
```

首版不包含真实 API/数据库、真实认证授权、生产数据、任意脚本/表达式、完整 BPMN、多人协作、Figma/Penpot 格式兼容或生产代码导出。

## 验收闭环

产品经理必须能够在不查看源码的情况下：

1. 生成采购原型首稿。
2. 拖动组件并保存。
3. 要求 AI 修改文案、布局或一条简单业务规则，并预览/应用。
4. 以申请人填写并提交采购申请。
5. 切换主管模拟角色并审批通过。
6. 在列表和详情中看到相同的“已通过”状态。
7. 刷新后恢复设计状态；重放 runtime session 得到相同 final state/view-model hashes。
8. 发布并打开可运行预览。

## 实施顺序

1. Contracts 与 runtime-core 风险验证。
2. Object store、command journal、checkpoint 与 draft API。
3. Studio runtime session、Flow rule projection 和拖拽编辑。
4. Deterministic renderer、publish 和分享。
5. Claude generation/conversation、证据链和完整端到端验收。

任何阶段都不能以扩大组件、流程或协作范围替代当前垂直切片的完成。

## 完成状态（2026-07-14）

- [x] 项目绑定 Claude UI Engineer 生成三页采购原型，并经蓝图确认后验收。
- [x] 六类语义组件支持结构化插入、选择、拖动和当前 MVP 属性编辑。
- [x] AI 对话生成受控命令提案，支持 Preview、Apply 和 Reject。
- [x] 申请人提交、主管审批、列表与详情状态同步的真实 runtime 闭环通过。
- [x] checkpoint、命令尾、runtime event 和最终 state/view-model hash 可确定性重放。
- [x] renderer、不可变 revision、分享路由和可运行发布预览通过。
- [x] Studio 按项目从服务端恢复当前草稿；无草稿项目进入需求生成，不依赖手工写入 localStorage。
- [x] Studio 业务交互从文档语义 key 和规则引用派生，不依赖 fixture UUID。

完整实现与浏览器证据见 `reports/generation-studio-integration.md`。
