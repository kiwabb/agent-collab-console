# PR5 - 原型项目生成集成加固

## Goal

完成项目驱动原型生成的增量同步、过期语义、端到端验证、性能边界、可访问性和文档，使 VideoNote 主应用成为稳定的发布验收样例。

## Parent Design

- [`../07-11-project-driven-prototype-generation/prd.md`](../07-11-project-driven-prototype-generation/prd.md)
- [`../07-11-project-driven-prototype-generation/info.md`](../07-11-project-driven-prototype-generation/info.md)

## Dependencies

- 依赖 PR1 至 PR4 全部完成。

## Requirements

- 完整实现并验证 create/update/unchanged/missing 分类。
- source hash 未变的候选默认跳过；变化候选生成新版本；missing 只提示且不删除。
- 处理分析中途代码变化、生成前过期、dirty worktree、无 git HEAD 和重复候选冲突。
- 加入大仓库 package/file/evidence/prompt 上限测试和用户可见 diagnostics。
- 验证 analysis/generation runner 重启恢复、SSE 重连、重复 POST、乐观锁冲突和部分失败。
- 完成 VideoNote 最小 fixture 的端到端测试，固定 19 个逻辑页面族与 extension unsupported 结果。
- 完成原型工作台、计划审阅、生成队列、错误恢复和版本切换的浏览器 smoke。
- 检查桌面/移动视口、键盘操作、焦点、ARIA、文本溢出和控件稳定尺寸。
- 检查已有数据兼容：manual prototype、legacy code prototype、历史版本和 SQLite 行无需迁移。
- 更新 README/Trellis spec/用户可见文案，明确支持矩阵、restore 基线、unsupported 诊断和运行时证据非 MVP。
- 增加必要 observability：分析阶段耗时、候选数量、unsupported 数、生成成功/失败数；日志不得包含源码全文、模型密钥或用户秘密。
- 评估 feature flag/回滚路径并验证隐藏新入口不会影响旧原型功能。

## Acceptance Criteria

- [ ] VideoNote 首次分析产生 19 个逻辑页面族，第二次无改动分析全部为 unchanged。
- [ ] 修改一个 evidence 文件后只有对应页面族进入 update。
- [ ] 删除路由后旧 prototype 标记 missing，但数据和版本不删除。
- [ ] 计划过期时生成请求 fail-closed，重新分析后可继续。
- [ ] 大仓库超过上限时返回明确 diagnostics，不超时或静默空结果。
- [ ] runner 重启、断网重连和重复请求不会损坏计数或重复创建原型。
- [ ] 页面加载错误保留上一份计划/原型数据。
- [ ] 桌面与移动 smoke 无重叠、溢出、空白预览或不可操作控件。
- [ ] 旧原型全链路回归通过。
- [ ] 支持范围、限制、回滚和人工真实模型验收步骤已文档化。

## Definition Of Done

- 后端与前端相关测试全部通过；跨层风险需要时运行较完整测试集。
- 浏览器 smoke 记录关键状态截图或可复现证据。
- 不执行默认付费全量生成；真实 VideoNote 批量生成由用户显式触发。
- spec 更新完成，未留下宣称浏览器扩展或运行时截图已支持的错误文案。
- 父任务所有验收标准均可逐项追溯到测试或人工证据。

## Out Of Scope

- Vue/浏览器扩展 provider。
- 登录自动化、动态测试数据和运行时 DOM/截图采集。
- 像素级视觉回归平台。
- 批量优化设计。
- 自动修改 VideoNote 业务源码。

## Delivery Boundary

本任务只做发布级加固和证据闭环，不新增新的产品范围或框架支持。
