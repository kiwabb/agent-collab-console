# pytest 提速：slow marker + addopts skip 默认

## Goal

把 backend 全量 pytest 从 10+ 分钟降到 30s-1min（默认）。慢测试加 `@pytest.mark.slow` marker，`pytest.ini` 配置 `addopts = -m "not slow"` 默认跳过；显式 `pytest --runslow` 才跑全量。CI 默认跑全量。

## What I already know

- backend/pytest.ini 现在只有 2 行配置（asyncio_mode + loop_scope），没有任何 marker / addopts
- 4 个 baseline-fail 文件 + 已知慢文件统计：
  - `test_projects_api.py` — 22 tests（含大量 worktree 操作）
  - `test_codex_tasks_ported.py` — 13 tests（git worktree + 真 SQLite migration）
  - `test_runtime_catalog.py` — 18 tests
  - `test_codex_api.py` — 2 tests
  - 合计 55 个 test，占据 90%+ 总耗时
- 这 4 个文件目前**已经有 baseline failure**（与本次提速任务无关），需要单独修，但提速本身不解决它们
- 其余 351 个 test 单独跑只需要 <2s（已验证：23 个 conductor 相关 test 跑了 0.63s）
- `pytest.ini` 加 `addopts = -m "not slow"` 默认排除带 marker 的；加自定义 `--runslow` 标记反向 enable 是 pytest 标准 pattern

## Assumptions (temporary)

- 4 个 "baseline fail" 文件就是"slow"的全集；如果有其他慢但目前 pass 的 test，本次不动
- CI 配置当前没有，所以"CI 跑全量"只是口头约定，不需要改 .github/workflows
- 不引入 pytest-xdist（并行）；先把"少跑"做掉，并行是下个迭代

## Open Questions

- Q1（slow marker 怎么打）：在每个慢测试 fixture / 文件顶部加 `pytestmark = pytest.mark.slow`（文件级，最快，60 个 test 共用一行）/ 在每个 test 函数上单独加（细粒度但要改 60 行）？
- Q2（–runslow 怎么实现）：在 backend 加一个 `conftest.py` 用 `pytest_addoption` 注册 `--runslow` flag + 改 `pytest_collection_modifyitems` 把 slow 自动 deselect / 直接靠 `pytest -m "not slow"` 在 ini 里写，--runslow 用户 alias `pytest -m ""` 跑全量？

## Requirements

- backend/pytest.ini 加 `markers = slow: long-running integration tests (db migration + worktree)` 注册 marker
- backend/pytest.ini 加 `addopts = -m "not slow"` 默认排除
- 4 个慢文件文件级 `pytestmark = pytest.mark.slow`
- 新增 `backend/conftest.py` 实现 `--runslow` flag：传入时 collection 包含 slow，否则按 addopts 跳过
- CLAUDE.md "Commands" 段：补充 `pytest` 默认快档说明 + `pytest --runslow` 跑全量

## Acceptance Criteria

- [ ] `cd backend && pytest` 跑出来不到 60s（vs 当前 10+ min），且 collected count 显示 ~351（不是 406）
- [ ] `cd backend && pytest --runslow` 跑全量 406 个 test，结果跟当前 `pytest` 等价
- [ ] `cd backend && pytest tests/test_projects_api.py` 直接指定慢文件也能跑（不会被 addopts 误拦）
- [ ] 现有 conductor / dispatcher / 其他快 test 全过

## Definition of Done

- backend/pytest.ini 改完
- backend/conftest.py 新建
- 4 个 slow 文件加 pytestmark
- CLAUDE.md 命令段更新
- 默认 `pytest` 一次 <60s 验证通过

## Out of Scope

- 不引入 pytest-xdist（并行执行）—— 下个迭代
- 不引入 pytest-testmon（变更影响分析）—— 下个迭代
- 不修 4 个 baseline-fail 文件本身的失败（那是另一回事）
- 不改 CI 配置（无现有 CI）
- 不改 frontend test workflow

## Technical Notes

- 关键文件：
  - `backend/pytest.ini` — 2 行配置，加 markers + addopts
  - `backend/conftest.py` — 不存在，要新建
  - `backend/tests/test_projects_api.py` / `test_codex_tasks_ported.py` / `test_runtime_catalog.py` / `test_codex_api.py` — 顶部加 pytestmark
  - `CLAUDE.md` — 命令段
- pytest 官方 pattern: https://docs.pytest.org/en/stable/example/simple.html#control-skipping-of-tests-according-to-command-line-option
