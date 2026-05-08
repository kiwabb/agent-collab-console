# System Design: 架构 - 冒泡排序算法html演示

- Project: ces
- Issue ID: a2b2953e-da83-4c3b-96d4-a2a6ff96d0db
- Language: zh-CN

## Architecture Summary
采用单页纯前端静态架构实现冒泡排序演示：HTML负责页面结构，CSS负责数组条形图、状态高亮和动画表现，原生JavaScript负责数据生成、冒泡排序步骤生成、播放控制和DOM渲染。整体以「状态驱动 + 步骤队列 + 动画调度器」为核心，保证排序逻辑与可视化解耦，便于后续扩展降序、手动输入或更多教学信息。

## Components
- 页面骨架与控制区：包含数组展示容器、开始/暂停、重置、速度调节与状态文案区域
- 数组生成器：初始化随机数组，支持重置时重新生成
- 冒泡排序步骤引擎：根据当前数组预生成比较、交换、轮次结束等步骤
- 动画调度器：按速度播放步骤队列，控制单步高亮、交换和节流
- 可视化渲染器：将数组数值映射为条形高度、颜色状态与位置变化
- 状态管理模块：维护原始数组、当前数组、执行进度、播放状态和速度
- 提示与说明模块：展示当前比较对象、交换结果、完成状态与教学说明

## Data Models
- ArrayItem：{ value, index, state }，用于表示单个数组元素及其视觉状态
- SortStep：{ type, i, j, arraySnapshot, round, message }，用于描述一次比较、交换或轮次结束
- SortSession：{ originalArray, workingArray, steps, currentStepIndex, speed, isRunning, isPaused }，用于管理一次演示会话
- UIState：{ statusText, highlightedIndices, completed, disabledControls }，用于驱动页面展示
- SpeedConfig：{ label, delayMs }，用于将用户选择映射为动画延迟

## Interfaces
- initDemo(options) -> 初始化随机数组并渲染初始视图
- generateRandomArray(size, min, max) -> 生成待排序数据
- buildBubbleSortSteps(array) -> 产出完整步骤队列
- playSteps(steps, speed) -> 按节奏执行动画并更新视图
- pauseDemo() / resumeDemo() / resetDemo() -> 控制演示流程
- renderArray(items, highlightState) -> 更新条形图和高亮样式
- renderStatus(message) -> 更新步骤说明文本

## Data Flow
页面加载后，数组生成器创建默认随机数组并交给可视化渲染器展示。用户点击开始后，步骤引擎基于当前数组预生成冒泡排序步骤队列，动画调度器按当前速度逐步消费队列；每一步都会同时更新工作数组、比较/交换高亮、轮次状态和说明文本。排序完成后，状态管理模块将会话置为结束态，控制区按钮切换为可重置状态，页面保持最终升序结果供用户复盘。

## Risks
- 纯前端动画在数组规模增大时可能出现掉帧或交互延迟，需要控制默认规模
- 如果步骤预生成与实时渲染不同步，可能出现展示状态与数组真实状态不一致
- 不同浏览器对CSS过渡和布局抖动的表现略有差异，需要进行基本兼容验证
- 如果速度控制粒度过细，可能增加实现复杂度并影响演示稳定性

## Open Questions
- 默认演示数组规模应该设为多少个元素，5个、8个还是10个更合适？
- 是否允许用户手动输入数组，还是仅使用随机生成？
- 是否需要支持降序排序，还是当前版本只做升序演示？
- 动画速度的档位和范围是否需要固定为慢/中/快，还是允许自由滑块调节？
- 是否需要展示时间复杂度、空间复杂度或每轮比较次数等教学信息？
