# 异步架构深度重构计划 (Async Runtime Refactoring Plan)

## 1. 核心目标
- **全异步化 (Pure Async)**：废弃所有针对日志读取和进程管理的 `threading.Thread`，改用 `asyncio` 原生并发。
- **非阻塞数据库 (Async DB)**：引入 `aiosqlite`，消除数据库操作对主线程的潜在阻塞。
- **执行进程中心化 (Execution-Process-Centric)**：所有日志和状态更新严格绑定到 `ExecutionProcess` 实体。

## 2. 重构路线图 (Roadmap)

### Phase 1: 基础设施异步化 (Infrastructure) [DONE]
- [x] **aiosqlite 集成**：创建 `AsyncSQLiteStore`，实现所有数据库方法的 `async` 版本。
- [x] **EventBus 升级**：废弃 `ThreadPoolExecutor`，改用 `asyncio.Queue` 处理后台写入任务。
- [x] **依赖注入更新**：在 `bootstrap.py` 中优先注入 `async_store`。

### Phase 2: 运行时核心重构 (Runtime Core) [DONE]
- [x] **BaseProcessRuntime 异步化**：将 `_reader_loop` 从线程改为 `asyncio.create_task`。
- [x] **JSON-RPC 客户端异步化**：重写 `AsyncJsonRpcPeer`，使用 `await stream.readline()`。
- [x] **Handshake 流程非阻塞化**：移除 `do_handshake` 专用线程，改用异步握手协程。

### Phase 3: 架构对齐 (Architectural Alignment) [DONE]
- [x] **统一 write_input_async**：废弃所有同步 `write_input` 入口，强制使用 `await write_input_async`。
- [x] **状态追踪优化**：确保 `turn/completed` 通知能准确触发 `ExecutionProcess` 的状态变更。
- [x] **清理冗余**：移除 `process_runtime_common.py` 中过时的线程管理逻辑。

## 3. 关键变更说明

### 3.1 进程管理 (Process Management)
以前：
```python
# 旧模式：阻塞读取 + 线程
def _reader_loop(self):
    line = self.proc.stdout.readline() # 阻塞！
```

现在：
```python
# 新模式：非阻塞读取 + 协程
async def _reader_loop(self):
    line = await self.proc.stdout.readline() # 非阻塞
```

### 3.2 握手与响应
- `CodexAppServerRuntime` 现在使用 `HANDSHAKE_ASYNC` 任务，不会阻塞主事件循环。
- 通过 `asyncio.Event` 实现跨协程的“等待响应”机制。

## 4. 预期收益
- **稳定性**：彻底解决 SQLite `database is locked` 报错。
- **性能**：单机可支撑 100+ 并发任务，且 CPU/内存消耗极低。
- **响应速度**：主事件循环延迟降至毫秒级，前端感知更加灵敏。

---

> [!IMPORTANT]
> **重构完成**：此重构涉及底层 IO 模型的彻底改变，旧的同步单元测试可能需要调整。
> **现状**：核心链路已通过 `doctor.py` 验证。
