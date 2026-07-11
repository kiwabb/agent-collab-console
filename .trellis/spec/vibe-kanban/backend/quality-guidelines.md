# Quality Guidelines

> Code quality standards for backend development.

---

## Overview

The bar is **"a senior engineer can read the diff in one pass and
trust it."** A change that touches a service is reviewable in
under 15 minutes; a change that touches the conductor or the
store is reviewable in under 30. The toolchain enforces most of
the mechanical rules (lint, typecheck, tests), so the reviewer's
job is mostly about shape, naming, race conditions, and the
things the tools cannot see.

Every change must pass, locally, in this order:

```bash
cd backend
.venv/bin/python -m ruff check .                  # lint, 0 findings
.venv/bin/python -m mypy app benchmark tests --show-error-codes --no-pretty
.venv/bin/python -c "from app.main import app"    # import smoke
.venv/bin/python -m pytest -q --tb=short --disable-warnings
.venv/bin/python -m pytest tests/test_foo.py -v   # pointed test, never skipped
```

A PR that hasn't run the relevant checks is not ready for
review. A change that touches a public Pydantic model gets a
serializer round-trip test; a change that touches the
conductor gets a state-machine test; a change that touches the
store gets a real-async-store migration test.

### Scenario: CI Workflow Quality Gate Contract

#### 1. Scope / Trigger

- Trigger: changing `.github/workflows/ci.yml`, README quality gates, or the
  local backend/frontend gate commands.
- CI is a release boundary. A workflow that soft-fails lint/type/test/build can
  let regressions merge even when local specs say the gate is mandatory.

#### 2. Signatures

- Workflow: `.github/workflows/ci.yml`.
- Documentation: `README.md` quality gates section.
- Regression test: `backend/tests/test_ci_quality_gates.py`.
- Backend CI commands:
  `ruff check .`,
  `mypy app benchmark tests --show-error-codes --no-pretty`,
  `python -c "from app.main import app"`,
  `pytest -q --tb=short --disable-warnings`.
- Python version contract: backend `requires-python >=3.12`, mypy
  `python_version = "3.12"`, Ruff `target-version = "py312"`, CI
  `python-version: "3.12"`, and backend spec `Python 3.12+`.
- Frontend CI commands:
  `npm audit --registry=https://registry.npmjs.org`, `npm run typecheck`,
  `npm test`, `npm run lint`, `npm run build`, `npm run format:check`.

#### 3. Contracts

- CI quality gates must be hard gates. Do not use `|| true` or
  `continue-on-error: true` on lint/type/test/build checks.
- README quality gates and CI gate commands stay aligned.
- Backend CI mypy covers `app`, `benchmark`, and backend `tests`.
- Backend Python runtime metadata, static-analysis target, CI version, and spec
  version stay aligned on Python 3.12.
- Frontend CI runs the production build, not just typecheck/test/lint.
- CI should use project scripts (`npm run ...`) for frontend gates so package
  script changes stay centralized.
- Frontend dependency audit uses the official npm registry because alternate
  mirrors may not implement the audit endpoint.

#### 4. Validation & Error Matrix

- Missing documented command -> `test_ci_quality_gates.py` fails with the
  missing command list.
- Missing README gate command -> `test_ci_quality_gates.py` fails with the
  missing command list.
- `|| true` or `continue-on-error: true` in the workflow -> test fails.
- Workflow YAML syntax still needs an external parser/actionlint when available;
  the regression test only enforces gate presence and hard-fail semantics.
- Python version drift between CI, `pyproject.toml`, and backend spec ->
  `test_ci_quality_gates.py` fails.
- Missing frontend npm audit gate -> `test_ci_quality_gates.py` fails with the
  missing command list.

#### 5. Good/Base/Bad Cases

- Good: hard backend and frontend gates, including dependency audit, match
  README/spec commands.
- Base: adding an extra hard gate is allowed when it is documented.
- Bad: `mypy app || true`, `npx prettier ... || true`, or omitting
  `npm run build`.

#### 6. Tests Required

- `cd backend && .venv/bin/python -m pytest tests/test_ci_quality_gates.py -q`.
- Backend full pytest after changing the test or workflow source contract.
- YAML/actionlint validation when the tool is available locally or in CI.

#### 7. Wrong vs Correct

Wrong:

```yaml
- name: Mypy (baseline)
  run: mypy app || true
```

Correct:

```yaml
- name: Mypy
  run: mypy app benchmark tests --show-error-codes --no-pretty
```

---

### Scenario: Backend App Logging Source Hygiene

#### 1. Scope / Trigger

- Trigger: changing code under `backend/app/` that emits diagnostics, handles
  best-effort cleanup, mirrors audit/event data, or bridges external processes.
- The backend logging contract is executable: application code uses stdlib
  `logger`, not `print(...)`, so output routes through the configured app log
  instead of ad hoc stdout/stderr writes.

#### 2. Signatures

- Source boundary: `backend/app/**/*.py`.
- Regression test: `backend/tests/test_backend_source_hygiene.py`.
- Logging API: module-level `logger = logging.getLogger(__name__)`.
- Bare `except/pass` allowlist:
  `EXPECTED_BARE_EXCEPT_PASS` in `test_backend_source_hygiene.py`.

#### 3. Contracts

- No real AST `print(...)` call is allowed under `backend/app`.
- Generated script text may contain `print(...)` when it is written as data for
  an external hook; the AST test intentionally does not inspect string bodies.
- Existing bare `except ...: pass` sites are frozen in the source-hygiene
  allowlist. New silent exception swallowing under `backend/app` or
  `backend/benchmark` must either log with context, use a clearer
  `contextlib.suppress(...)` for intentionally ignored control flow, or update
  the allowlist with a reason in review.
- Best-effort cleanup / audit / event mirroring paths may swallow exceptions
  only after logging at `DEBUG` or higher with useful identifiers and
  `exc_info=True` / `logger.exception(...)` when a traceback is needed.
- User-facing process logs still go through the existing `LogEvent` /
  EventBus paths, not direct terminal writes.

#### 4. Validation & Error Matrix

- `print(...)` call under `backend/app` -> `test_backend_source_hygiene.py`
  fails with `<path>:<line>: print(...)`.
- New bare `except/pass` site or a changed allowlisted scope ->
  `test_backend_source_hygiene.py` fails with the actual site list.
- Cleanup path uses `except Exception: pass` with no logging -> Bandit reports
  low `B110` / `B112`; either add debug logging or document why a
  `contextlib.suppress(...)` block is more precise.
- Logging without an identifier on cross-process / cross-task boundaries ->
  review failure; include `task_id`, `workspace_id`, `issue_id`, or the nearest
  equivalent.

#### 5. Good/Base/Bad Cases

- Good: `logger.exception("event bus broadcast failed: event_type=%s", event_type)`.
- Base: `logger.debug("process cleanup failed: workspace_id=%s", workspace_id, exc_info=True)`.
- Bad: `print(f"[EventBus] Error: {exc}", file=sys.stderr)` or bare
  `except Exception: pass`.

#### 6. Tests Required

- `cd backend && .venv/bin/python -m pytest -q tests/test_backend_source_hygiene.py`.
- For touched runtime boundaries, run the relevant unit/integration tests
  (`test_event_bus_ws.py`, `test_audit_logger.py`, process runtime tests, etc.).
- When replacing `except/pass`, run targeted Bandit for the touched files to
  confirm `B110`/`B112` noise does not increase.

#### 7. Wrong vs Correct

Wrong:

```python
try:
    await event_bus.append(payload)
except Exception:
    pass
```

Correct:

```python
try:
    await event_bus.append(payload)
except Exception:
    logger.debug("event append failed: task_id=%s", task_id, exc_info=True)
```

---

### Scenario: Trusted Local Subprocess Boundary

#### 1. Scope / Trigger

- Trigger: adding or changing synchronous local CLI calls for trusted developer
  tools such as `git`, `osascript`, `codex`, `claude`, benchmark helpers, or QA
  command execution.
- Static security scanners cannot tell local-first CLI integration from unsafe
  command execution when `subprocess.run(...)` is scattered through services.
  Keep suppressions at a small I/O boundary so application code stays
  reviewable.

#### 2. Signatures

- Boundary module: `backend/app/adapters/local_process.py`.
- Regression test: `backend/tests/test_backend_source_hygiene.py`.
- Runner:
  `run_trusted_local(args: Sequence[str], *, cwd=None, capture_output=True, text=True, check=False, timeout=None, env=None) -> subprocess.CompletedProcess[str]`.
- Re-exported exceptions/types:
  `CalledProcessError`, `CompletedProcess`, `TimeoutExpired`.
- Static analyzer suppressions live only at the boundary import/call sites:
  `# nosec B404` and `# nosec B603`.

#### 3. Contracts

- Callers pass an argv sequence; the helper converts it to `list(args)`.
- `shell=False` is mandatory inside the helper and is not caller-configurable.
- User content may appear only as an argv value. It must not be interpolated into
  a shell string.
- Feature/application/interface code that needs a one-shot trusted local CLI
  call imports `run_trusted_local(...)` instead of calling `subprocess.run(...)`
  directly.
- Long-lived async runtimes may still use `asyncio.create_subprocess_exec(...)`
  or existing command-safety reviewed async process boundaries when they need
  streaming stdio, cancellation, and process-group cleanup.
- New modules under `backend/app/` or `backend/benchmark/` remain covered by the
  strict mypy override list in `backend/pyproject.toml`.

#### 4. Validation & Error Matrix

- Direct `subprocess.run(...)` outside `local_process.py` -> review failure and
  `test_backend_source_hygiene.py` failure; move the call behind
  `run_trusted_local(...)`.
- Direct synchronous `subprocess.Popen(...)`, `subprocess.call(...)`,
  `subprocess.check_call(...)`, or `subprocess.check_output(...)` under
  `app` / `benchmark` outside `local_process.py` -> source-hygiene failure.
- Adding a `shell` parameter to `run_trusted_local(...)` -> review failure; the
  boundary loses its security contract.
- Building a command as a string from user input -> review failure; pass argv
  values separately or use an existing command-safety parser.
- Adding a new backend module without strict mypy coverage ->
  `tests/test_mypy_strict_coverage.py` fails.
- Bandit reports high/medium findings in `app` or `benchmark` -> the batch is
  not green until fixed or documented with a narrow suppression.

#### 5. Good/Base/Bad Cases

- Good: `run_trusted_local(["git", "status", "--short"], cwd=repo)`.
- Base: `run_trusted_local(["osascript", "-e", script], timeout=5)`, where
  `script` is fixed application text plus normal argv-safe values.
- Bad: `subprocess.run(f"git -C {repo} status", shell=True)`.

#### 6. Tests Required

- `cd backend && .venv/bin/python -m ruff check .`.
- `cd backend && .venv/bin/python -m mypy app benchmark tests --show-error-codes --no-pretty`.
- `cd backend && .venv/bin/python -m pytest -q tests/test_backend_source_hygiene.py`.
- `cd backend && .venv/bin/python -m pytest -q tests/test_mypy_strict_coverage.py`.
- Run the targeted tests for the changed caller, especially process runtime,
  QA workflow, benchmark, API, or git/status tests.
- `cd backend && pipx run bandit -r app benchmark -f json -q` must report an
  empty `results` list for high/medium/low findings introduced by the change.

#### 7. Wrong vs Correct

Wrong:

```python
import subprocess

result = subprocess.run(["git", "diff", "--name-only"], capture_output=True, text=True)
```

Correct:

```python
from app.adapters.local_process import run_trusted_local

result = run_trusted_local(["git", "diff", "--name-only"])
```

---

## Forbidden Patterns

- **`any` in production types.** The `no-any` rule is enforced
  at review time. Use `object` + a type guard, or define a
  narrow union. The exception is bridging a third-party type
  we cannot change — narrow as soon as you cross the bridge.
- **`os.getenv` / `os.environ.get` from feature code.** Config parsing belongs
  in `application/timeouts.py` accessors, including defaults, bool parsing,
  numeric coercion, and invalid-value fallback. Feature/application/interface
  code consumes typed accessors only. Copying environment values into a child
  process environment, such as preserving `PATH`, is allowed because it is not
  configuration parsing.
- **Hand-rolled CodexTask status sets.** Task lifecycle checks go through
  `application/task_statuses.py`: pending, active (`running` / `responding`),
  waiting-for-help, waiting-for-specialist, success, failure, and terminal. Do
  not write local `{ "done", "failed", ... }` or `{ "running", "responding" }`
  sets in feature code; otherwise aliases like `success`, `error`, `timeout`,
  or whitespace/case variants drift.
- **Catching `Exception` to "always return a value".** Let
  unexpected exceptions propagate to the loop boundary or the
  transport layer, where they can be logged with a traceback.
  Catch the typed errors the use case actually anticipates.
- **Polling a value the WS already streams.** A background
  task that polls a value the conductor already emits is a
  duplicate of the event stream. The conductor emits at
  semantic boundaries; polling is for silent growth below a
  threshold.
- **Service code that imports from `interfaces/`.** The
  transport layer imports the application layer; never the
  other way. A service that knows the HTTP shape leaks.
- **`raise HTTPException(...)` from a service.** Same leak in
  the other direction. The service raises a typed error; the
  transport maps it to a status.
- **Long-running coroutines that hold a transaction across an
  `await`.** A conductor iteration that opens a write
  transaction and then awaits a dispatch holds the SQLite
  write lock for the duration. Release before the await,
  re-acquire on the next call.
- **Re-using the same conductor issue worktree across parallel
  dispatches.** The `dispatch_batch` path forks an
  isolation worktree per agent (`worktree_manager.prepare_agent_worktree`).
  Running two agents on the same worktree is a race; the
  `in-flow join` cannot merge two agents that wrote to the
  same files at the same time.
- **Untested inline Conductor prompt rewrites.** The issue
  Conductor prompt is behavior, not copy. Keep prompt assembly in
  a pure helper that tests can assert directly, and add an
  integration-style loop test when the prompt depends on project
  memory, budget, language, or user steering context.
- **Calling private or nonexistent memory helpers from the
  Conductor loop.** The issue loop must load project memory
  through `ProjectConductor.get_or_create_state()`. A broad
  background-loop `except Exception` can otherwise hide missing
  method calls and silently remove team notes / warm summaries
  from the model prompt.

---

## Required Patterns

<!-- Patterns that must always be used -->

### Convention: Type Singleton Instance Attributes At Class Scope

**What**: When a process-singleton initializes mutable instance attributes in
`__new__`, declare those instance attributes on the class before assigning them
on the newly-created object.

**Why**: The runtime pattern is safe, but mypy cannot infer attributes that are
introduced only through annotated assignments on a temporary `obj` inside
`__new__`. Class-scope annotations keep the singleton pattern explicit and avoid
large false-positive `attr-defined` cascades.

Wrong:

```python
class Registry:
    _instance: Registry | None = None

    def __new__(cls) -> Registry:
        if cls._instance is None:
            obj = super().__new__(cls)
            obj._events: dict[str, asyncio.Event] = {}
            cls._instance = obj
        return cls._instance
```

Correct:

```python
class Registry:
    _instance: Registry | None = None
    _events: dict[str, asyncio.Event]

    def __new__(cls) -> Registry:
        if cls._instance is None:
            obj = super().__new__(cls)
            obj._events = {}
            cls._instance = obj
        return cls._instance
```

### Convention: Declare Runtime Entry Scratch State On The Dataclass

**What**: When a process runtime stores per-process scratch state on
`AsyncProcessEntry`, add the field to the dataclass in
`application/process_runtime_common.py`. Do not attach ad hoc attributes from a
specific runtime such as `CodexAppServerRuntime`.

**Why**: Codex and Claude runtimes share the same process-entry object. Hidden
runtime-only attributes make timeout/watchdog behavior hard to audit and create
false `attr-defined` workarounds during type tightening.

Wrong:

```python
entry._timeout_reason = "idle_timeout"
entry.turn_watchdog_task = asyncio.create_task(watchdog())
```

Correct:

```python
@dataclass
class AsyncProcessEntry:
    timeout_reason: str | None = None
    turn_watchdog_task: asyncio.Task[None] | None = None
```

### Convention: Preserve Optional Store Capabilities In API Tests

**What**: When tightening `interfaces/api.py` store typing with a structural
Protocol, keep any existing endpoint fallback for narrower test stores or
optional store capabilities. If a method is intentionally optional for a
specific endpoint, check it with `getattr(..., None)` / `callable(...)`, then
cast to a narrow callable Protocol at the call boundary.

**Why**: Some endpoint tests monkeypatch `api.codex_store` with a focused stub
that only implements the methods the scenario needs. Replacing a documented
fallback with a direct Protocol method call can make production typing cleaner
while breaking those executable transport contracts.

Wrong:

```python
store = _require_codex_store()
existing_workspace = await store.load_codex_workspace(project.id)
```

Correct:

```python
load_workspace_raw = getattr(store, "load_codex_workspace", None)
save_workspace_raw = getattr(store, "save_codex_workspace", None)
if not callable(load_workspace_raw) or not callable(save_workspace_raw):
    return project.id
load_workspace = cast(LoadCodexWorkspaceFn, load_workspace_raw)
existing_workspace = await load_workspace(project.id)
```

### Convention: Type-Narrow Test Fixtures Instead Of Ignoring Mypy

**What**: Backend tests that prove fixture state should narrow the value with a
real assertion before indexing, comparing, or passing it into a typed helper.
Focused test doubles should either match the production Protocol signature or be
cast at the call site where the test intentionally supplies a partial stub.

**Why**: Test code is executable documentation for edge cases. A broad
`# type: ignore`, an unannotated async fixture, or indexing a `Row | None` hides
whether the fixture actually established the state the test depends on.
Assertions make both the runtime failure and the mypy contract point at the
missing setup.

Wrong:

```python
row = await cursor.fetchone()
assert row[0] == 1

assert classify_intent(None) == "chat"  # type: ignore[arg-type]

class Store:
    async def update_execution_process_status(self, process_id: str, status: str, **kwargs):
        ...
```

Correct:

```python
row = await cursor.fetchone()
assert row is not None
assert row[0] == 1

assert classify_intent(None) == "chat"

class Store:
    async def update_execution_process_status(
        self,
        process_id: str,
        status: str,
        completed_at: datetime | None = None,
    ) -> None:
        ...
```

### Convention: Type Service Constructor Dependencies By Capability

**What**: When an application service only needs a subset of another service's
methods or attributes, define a small structural `Protocol` for that dependency
instead of typing the constructor parameter as the concrete implementation.

**Why**: Concrete service annotations make tests reach for broad casts even
when the production code only needs two methods. A capability Protocol keeps the
boundary honest, lets focused fakes type-check, and documents hidden
requirements such as an in-memory `sessions` index.

Wrong:

```python
class OrchestrationService:
    def __init__(self, session_service: SessionService) -> None:
        self.session_service = session_service
```

Correct:

```python
class OrchestrationSessionService(Protocol):
    sessions: dict[str, Session]

    async def get_session(self, session_id: str) -> Session: ...

    async def update_session(self, session: Session) -> None: ...


class OrchestrationService:
    def __init__(self, session_service: OrchestrationSessionService) -> None:
        self.session_service = session_service
```

### Convention: Type Transport/Runtime Fakes By Capability

**What**: When a backend transport helper or process-runtime helper only uses a
small capability surface, expose that surface as a structural `Protocol` and
make tests implement the Protocol directly. Keep casts at the deliberate fake
boundary, such as a fake subprocess standing in for `asyncio.subprocess.Process`.

**Why**: Tests should not need to inherit concrete framework classes such as
FastAPI `WebSocket`, nor pass `None` into runtime entries, just to exercise a
small sender or lifecycle behavior. Capability Protocols document what the
production code really needs and keep focused fakes type-checkable without
pulling in framework internals.

Wrong:

```python
class WsSubscriber:
    def __init__(self, ws: WebSocket, maxsize: int) -> None:
        self.ws = ws


sub = WsSubscriber(FakeWebSocket(), maxsize=16)  # fake is not a WebSocket
```

Correct:

```python
class WsSendChannel(Protocol):
    async def send_json(self, data: object) -> None: ...
    async def send_text(self, data: str) -> None: ...
    async def close(self, code: int = 1000, reason: str = "") -> None: ...


class WsSubscriber:
    def __init__(self, ws: WsSendChannel, maxsize: int) -> None:
        self.ws = ws
```

### Convention: Keep Protocol Signatures Domain-Typed

**What**: A structural `Protocol` should name the actual domain types it loads,
saves, or emits. Do not widen method parameters to `object` to make a Protocol
feel more permissive when every real implementation expects a concrete model.

**Why**: Method parameters are checked contravariantly. A Protocol method such
as `save_codex_task(task: object)` is stricter for implementers than
`save_codex_task(task: CodexTask)`: a real store that only accepts `CodexTask`
will not satisfy the `object` signature. This creates false test-mypy failures
and tempts broad casts around otherwise correct stores.

Wrong:

```python
class FollowupStore(Protocol):
    async def load_codex_task(self, task_id: str) -> object | None: ...

    async def save_codex_task(self, task: object) -> None: ...
```

Correct:

```python
class FollowupStore(Protocol):
    async def load_codex_task(self, task_id: str) -> CodexTask | None: ...

    async def save_codex_task(self, task: CodexTask) -> None: ...
```

### Convention: Narrow External JSON Before Typed Payloads

**What**: Values parsed from CLI, LLM, JSON-RPC, or other external JSON
boundaries start as `object`. Convert them through a small guard/coercion helper
before returning a `TypedDict` or domain model. Do not annotate raw parsed JSON
as a trusted `dict[str, object]` without checking that it is actually a mapping.

**Why**: `json.loads()` and third-party protocol payloads can be lists, scalars,
or dicts with wrong field types. Treating those values as typed dicts makes
mypy quiet while moving the failure to a later consumer. Guarding at the boundary
keeps adapter/service return shapes honest and lets modules graduate to strict
mypy without hiding runtime drift.

Wrong:

```python
data = json.loads(stdout)
return {
    "summary": data.get("summary", fallback),
    "artifacts": data.get("artifacts", []),
}
```

Correct:

```python
from app.json_safety import object_dict

data = object_dict(json.loads(stdout))
summary = data.get("summary")
return {
    "summary": summary if isinstance(summary, str) else fallback,
    "artifacts": artifact_list(data.get("artifacts"), fallback_artifacts),
}
```

### Scenario: Shared JSON Shape Guard Boundary

#### 1. Scope / Trigger

- Trigger: parsing JSON or mapping-like payloads from CLI stdout, LLM/tool
  results, JSON-RPC frames, HTTP provider responses, persisted JSON blobs, or
  project/worktree config files.
- Shape guards are a backend-wide primitive. Duplicating small
  `_object_dict(...)` helpers across services makes fallback behavior drift
  and hides raw `json.loads()` trust-boundary mistakes from review.

#### 2. Signatures

- Boundary module: `backend/app/json_safety.py`.
- Type aliases: `JsonObject = dict[str, object]`,
  `JsonList = list[object]`.
- Guard helpers:
  `object_dict(value: object) -> JsonObject`,
  `object_dict_or_none(value: object) -> JsonObject | None`,
  `object_list(value: object) -> JsonList`,
  `object_dict_list(value: object) -> list[JsonObject]`,
  `string_value(value: object, default: str = "") -> str`,
  `string_list_value(value: object, fallback: Sequence[str] | None = None) -> list[str]`.
- Safe JSON text helpers:
  `parse_json_object(raw) -> JsonObject | None`,
  `parse_json_value(raw, *, default: object = None) -> object`,
  `parse_json_list(raw) -> JsonList`,
  `parse_json_object_list(raw) -> list[JsonObject]`.
- Regression tests:
  `backend/tests/test_json_safety.py` and
  `backend/tests/test_backend_source_hygiene.py`.
  The source-hygiene test also rejects direct `json.loads(...)` calls in
  LLM/prototype streaming boundary modules; those parse untrusted SSE frames
  through `parse_json_object(...)`. Tolerant safe-read boundaries such as
  conductor turn policy, review-plan expected files, and knowledge-index JSON
  artifact flattening are also source-hygiene protected so they keep using the
  shared `parse_json_*` helpers.

#### 3. Contracts

- Application, adapter, and interface code uses `app.json_safety` for generic
  mapping/list/string shape coercion instead of defining local `_object_dict`,
  `_object_mapping`, or `object_dict` helpers.
- Choose the helper by branch semantics: use `object_dict(...)` when invalid
  payloads should degrade to `{}`, and `object_dict_or_none(...)` when
  downstream code distinguishes "missing/non-object" from an empty object.
- SQLite store wrappers may keep private `_json_object(...)` helpers when they
  intentionally preserve `json.loads()` exceptions for malformed persisted DB
  data, but the shape coercion inside those wrappers still delegates to
  `json_safety`.
- `parse_json_*` helpers are for tolerant "safe read" boundaries that should
  degrade on malformed text. Do not use them where malformed stored JSON should
  fail loudly.
- Use `parse_json_value(..., default=sentinel)` when the boundary accepts any
  JSON shape and must distinguish malformed text from a valid JSON `null`.

#### 4. Validation & Error Matrix

- New `_object_dict`, `_object_mapping`, or `object_dict` function under
  `backend/app` outside `app/json_safety.py` ->
  `test_backend_source_hygiene.py` fails with the file and line.
- Direct `json.loads(...)` in the LLM/prototype streaming boundary files ->
  `test_backend_source_hygiene.py` fails with the file and line.
- A new backend module under `backend/app` that imports `app.json_safety` but is
  missing from the strict mypy override list ->
  `tests/test_mypy_strict_coverage.py` fails.
- Raw `json.loads()` value indexed as a dict/list without a guard -> mypy should
  force `object` narrowing; review should require a `json_safety` helper.
- Using `parse_json_object(...) or {}` where `None` has business meaning ->
  review failure; keep `object_dict_or_none(...)` / explicit `None` handling.

#### 5. Good/Base/Bad Cases

- Good: JSON-RPC `params` and Codex app-server `item` payloads use
  `object_dict(...)` before `.get(...)`.
- Base: SQLite store `_json_object(raw)` uses `json.loads(raw)` and then
  `object_dict_or_none(parsed)` so malformed DB JSON still raises.
- Bad: a service adds a new local `_object_mapping(value)` that copies the same
  `isinstance(value, Mapping)` logic.

#### 6. Tests Required

- `cd backend && .venv/bin/python -m pytest -q tests/test_json_safety.py`.
- `cd backend && .venv/bin/python -m pytest -q tests/test_backend_source_hygiene.py`.
- For touched runtime or protocol boundaries, run the relevant tests
  (`test_json_rpc_client.py`, process runtime tests, API tests, or provider
  streaming tests).
- Run `ruff check .`, strict mypy, and import smoke when the helper signature or
  a broad call surface changes.

#### 7. Wrong vs Correct

Wrong:

```python
def _object_mapping(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): item for key, item in value.items()}
```

Correct:

```python
from app.json_safety import object_dict

payload = object_dict(raw_payload)
```

### Scenario: FastAPI No-Content Route Type Annotations

#### 1. Scope / Trigger

- Trigger: adding return annotations to FastAPI routes, especially during strict
  mypy graduation of `interfaces/api.py`.
- No-content routes are a transport contract: FastAPI rejects `204` route
  declarations that imply a response body.

#### 2. Signatures

- Route decorator: `@router.delete(..., status_code=204)`.
- Implementation return annotation: `-> Response`.
- Return value: `Response(status_code=204)`.

#### 3. Contracts

- A `204` endpoint must not declare or infer a response body model.
- Do not annotate a `204` route as `-> object`, `-> dict[str, object]`, or a
  Pydantic model. FastAPI treats those annotations as response body shapes.
- If the route returns JSON, it is not a `204`; use a `200`/`202` status instead.

#### 4. Validation & Error Matrix

- `status_code=204` plus `-> object` / dict / model annotation -> FastAPI raises
  at import/route registration: status code 204 must not have a response body.
- `status_code=204` plus `-> Response` and `return Response(status_code=204)` ->
  import succeeds and the client receives an empty body.

#### 5. Good/Base/Bad Cases

- Good: `DELETE /api/agents/{id}` returns `Response(status_code=204)` after a
  successful delete.
- Base: failed deletes still raise `HTTPException` with `404`/`400` and a normal
  FastAPI error body.
- Bad: mechanically adding `-> object` to every route during strict typing; this
  can make a previously valid `204` endpoint fail at app import time.

#### 6. Tests Required

- Import smoke: `from app.main import app` must succeed after route annotation
  changes.
- Endpoint test: successful `204` route has status `204` and no response body.
- Regression test or targeted route test for the affected endpoint, not just
  static mypy.

#### 7. Wrong vs Correct

Wrong:

```python
@router.delete("/agents/{agent_id}", status_code=204)
async def delete_agent(agent_id: str) -> object:
    return Response(status_code=204)
```

Correct:

```python
@router.delete("/agents/{agent_id}", status_code=204)
async def delete_agent(agent_id: str) -> Response:
    return Response(status_code=204)
```

### Scenario: Benchmark Handler Typed JSON Responses

#### 1. Scope / Trigger

- Trigger: adding or changing handlers in `backend/benchmark/api.py`, or the
  `/codex/benchmark/*` forwarding routes in `app/interfaces/api.py`.
- Benchmark handlers are HTTP JSON contracts even though the route decorators
  live in `interfaces/api.py`; do not hide those payloads behind
  `dict[str, Any]` or `-> object`.

#### 2. Signatures

- Request body: `TriggerRunRequest` validates the FastAPI body.
- Handler payload: `TriggerRunPayload` is the internal `TypedDict` passed from
  the route to `trigger_run()`.
- Handler responses: `TriggerRunResponse`, `SerializedRun`,
  `ListRunsResponse`, `BaselineResponse`, `SetBaselineResponse`,
  `RunDiffResponse`, `CalibrationReportResponse`, and `JobResponse`.
- Router annotations mirror handler responses, for example
  `def get_benchmark_run(...) -> benchmark_handlers.SerializedRun`.
- Job registry callback: `start_job[ResultT](..., coro:
  Callable[[], Awaitable[ResultT]], on_complete:
  CompletionCallback[ResultT] | None = None)`.
- Real benchmark executor store boundary: `BenchmarkRuntimeStore` Protocol with
  async `list_codex_tasks(...) -> list[dict[str, object]]` and
  `list_execution_processes(...) -> list[ExecutionProcess]`.

#### 3. Contracts

- Response `TypedDict`s list every JSON field returned by the handler.
- Optional JSON fields are represented with `| None` when the key is always
  present, or `NotRequired[...]` when the key is conditionally omitted.
- The FastAPI forwarding route builds a `TriggerRunPayload` explicitly from the
  Pydantic request fields instead of passing raw `request.model_dump()`.
- `Job.meta` is `dict[str, object]`. Code that reads from metadata must narrow
  the value before assigning it to a typed field such as `result_ref`.
- `RealConductorExecutor` must verify it received an async runtime store before
  awaiting store methods. Use a `TypeGuard` such as
  `_is_benchmark_runtime_store()` instead of annotating the store as `Any`.
- `Score.metadata` is `dict[str, object]`; scorer debug payloads must remain
  JSON-ish and cannot use `Any` as an escape hatch.
- `Any` is reserved for true third-party or callback bridges; benchmark handler
  request/response/job shapes use `object`, `TypedDict`, generics, or
  dataclasses.

#### 4. Validation & Error Matrix

- Invalid trigger body -> Pydantic validation raises `HTTPException(422)` before
  touching the store or job registry.
- Unknown run/job -> `HTTPException(404)`.
- No baseline -> `RunDiffResponse` includes `baseline=None`, `diff=None`, and a
  `note`.
- Candidate is the baseline -> same response shape with an explanatory `note`.

#### 5. Good/Base/Bad Cases

- Good: `get_run()` returns `SerializedRun` and `_serialize_run()` is the only
  place that constructs the run payload.
- Base: `get_run_diff()` returns the same top-level shape whether a diff exists
  or a note explains why it does not.
- Bad: `async def trigger_run(body: dict[str, Any]) -> dict[str, Any]` plus a
  router that forwards `request.model_dump()` directly.
- Bad: `on_complete: Callable[[Job, Any | None, BaseException | None], Any]`
  because it loses the coroutine result type at the callback boundary.
- Bad: `codex_store: Any` in `RealConductorExecutor` because a sync store or
  `None` can be awaited accidentally.
- Bad: `Score.metadata: dict[str, Any]` because tests can still assert runtime
  metadata without letting scorer code smuggle untyped values through the
  benchmark package.

#### 6. Tests Required

- Targeted API tests for benchmark trigger/list/get/diff/baseline/job routes.
- Strict mypy over `benchmark/api.py` and `app/interfaces/api.py`.
- Strict mypy over `benchmark/job.py` when changing job lifecycle callbacks or
  metadata.
- Benchmark runner tests when changing `RealConductorExecutor` store contracts,
  plus full `mypy app benchmark tests`.
- Source scan for benchmark type escapes:
  `rg -n "\bAny\b|dict\[str, Any\]|Awaitable\[Any\]|Callable\[.*Any" backend/benchmark`
  should return no matches unless a new documented external bridge is added.
- Regression test:
  `cd backend && .venv/bin/python -m pytest tests/test_benchmark_type_hygiene.py -q`.
- Full backend mypy command:
  `.venv/bin/python -m mypy app benchmark tests --show-error-codes --no-pretty`.
- Project-wide source-hygiene regression:
  `cd backend && .venv/bin/python -m pytest tests/test_backend_source_hygiene.py -q`
  rejects explicit type escape hatches in `backend/app`, `backend/benchmark`,
  and backend tests. Do not add `type: ignore`, `from typing import Any`,
  `dict[str, Any]`, `list[dict[str, Any]]`, `Awaitable[Any]`, or `cast(Any...)`
  unless the source-hygiene contract is intentionally changed with a documented
  boundary reason.

#### 7. Wrong vs Correct

Wrong:

```python
async def trigger_benchmark_run(request: TriggerRunRequest) -> object:
    return await benchmark_handlers.trigger_run(request.model_dump())
```

Correct:

```python
async def trigger_benchmark_run(
    request: TriggerRunRequest,
) -> benchmark_handlers.TriggerRunResponse:
    payload: benchmark_handlers.TriggerRunPayload = {
        "label": request.label,
        "epochs": request.epochs,
        "fixture_ids": request.fixture_ids,
        "is_baseline": request.is_baseline,
        "max_budget_usd": request.max_budget_usd,
        "project_id": request.project_id,
        "workspace_id": request.workspace_id,
        "dry_run": request.dry_run,
    }
    return await benchmark_handlers.trigger_run(payload)
```

### Convention: Keep Conductor Turn Kinds In The Domain Literal

**What**: When adding or discovering a persisted `conductor_turns.kind` value,
update `ConductorTurnKind` in `domain/models.py` instead of loosening conductor
call sites back to plain `str`.

**Why**: The Conductor loop, recovery tools, audit mirroring, and tests all
share the same persisted timeline. If a kind such as `policy_decision` is saved
but missing from the domain literal, later type tightening creates false local
workarounds and can hide real persistence/audit drift.

Wrong:

```python
async def persist_turn(*, kind: str, payload: dict[str, Any]) -> None:
    turn = ConductorTurn(kind=kind, payload_json=json.dumps(payload))
```

Correct:

```python
ConductorTurnKind = Literal["llm_request", "policy_decision", "tool_result", ...]

async def persist_turn(*, kind: ConductorTurnKind, payload: dict[str, Any]) -> None:
    turn = ConductorTurn(kind=kind, payload_json=json.dumps(payload))
```

### Scenario: Unified Audit Log Role-Chain Read Contract

#### 1. Scope / Trigger

- Trigger: changing `GET /api/codex/audit-log`, `audit_log` serialization,
  Conductor turn audit writes, or frontend audit-log role-chain rendering.
- The audit page is a cross-layer observability contract: `audit_log` rows stay
  generic, while API serialization derives role and turn metadata for the UI.

#### 2. Signatures

- Writer helper: `_audit_conductor_turn(..., kind, payload, turn_index=None, sub_index=None)`.
- LLM runner helper: `build_llm_runner(..., audit_actor="auto_plan", audit_role="system_planner")`.
- Store helper: `list_codex_task_roles(task_ids: list[str]) -> dict[str, str]`.
- API: `GET /api/codex/audit-log` returns each item with the original audit row
  fields plus derived optional fields:
  `role`, `role_label`, `turn_index`, `sub_index`, `call_name`,
  `call_input`, `call_output`, `call_summary`.

#### 3. Contracts

- Existing audit fields and filters remain backwards compatible.
- Rows with `task_id` derive `role` from `codex_tasks.role`.
- Conductor `tool_use` rows derive target role from `payload.input.role`.
- Conductor `tool_result` rows derive target role from `payload.result.role` or
  `payload.result.task_id -> codex_tasks.role`.
- Conductor audit payloads must include `turn_index` and `sub_index` when the
  turn recorder knows them.
- Rows without a target role but with `conductor_task_id` group under
  `role="conductor"`.
- Taskless LLM rows must still have an intelligible role. `auto_plan` derives
  `role="system_planner"`, while project script suggestion / operations agent
  calls use `actor="operations_engineer"` and `role="operations"`.
- Successful `llm_return` payloads must include the final assistant text in
  `content` when available; the API exposes that text as `call_output`.
- Taskless `git_command` / `command_exec` rows group under `role="system"`,
  never the generic Agent fallback. If a command row has `task_id`, the task
  role wins.
- Command audit rows split command/cwd into `call_input` and
  `exit_code`/`stdout`/`stderr`/duration/refusal into `call_output`; stdout and
  stderr are outputs, not inputs.

#### 4. Validation & Error Matrix

- Missing or malformed `payload_json` -> derived fields are `null`/fallbacks;
  the row still returns.
- Unknown task id -> no task-derived role; conductor rows fall back to
  `conductor` only when appropriate.
- Unknown role key -> `role_label` is a title-cased fallback, not an error.
- Legacy taskless `auto_plan` row with no payload role -> API derives
  `role="system_planner"`; legacy rows cannot synthesize missing response
  text that was never persisted.
- LLM 200 response with no text content -> record `llm_return` with
  `status="error"` and `error="empty_content"`.
- Taskless command row -> `role="system"` and `role_label="System"` so the UI
  does not present operational git noise as an Agent call chain.
- Store unavailable -> existing audit endpoint `503` behavior remains.

#### 5. Good/Base/Bad Cases

- Good: `dispatch_subagent` tool use/result in turn 3 both render under the
  Architect role with input/output visible.
- Good: clicking project "AI fill commands" records operations LLM rows under
  Operations Engineer, and the LLM response text appears in output details.
- Base: a raw `git_command` audit row with no task still appears in the raw
  list, groups under System, and exposes stdout/stderr in `call_output`.
- Base: legacy `auto_plan` LLM rows without task or role group as System
  Planner rather than Unassigned.
- Bad: auditing only `usage` / `stop_reason` for `llm_return` and dropping the
  assistant text operators need to inspect.
- Bad: putting `stdout`, `stderr`, or `exit_code` inside `call_input`, which
  makes the details drawer look like commands have no output.
- Bad: adding audit table role columns when the value can be derived from task
  and conductor payloads.
- Bad: frontend re-parsing raw `payload_json` to infer role differently from
  the backend.

#### 6. Tests Required

- Backend endpoint test: task-linked row returns `role` / `role_label` and
  input details.
- Backend endpoint test: taskless `git_command` returns `role="system"`,
  command/cwd as `call_input`, and stdout/stderr/exit code as `call_output`.
- Backend endpoint test: task-linked `command_exec` preserves the task role and
  splits input/output fields.
- Backend endpoint test: operations `llm_return` returns
  `role="operations"`, `role_label="Operations Engineer"`, and model text as
  `call_output`.
- LLM runner test: successful Anthropic-compatible response records
  `llm_return.payload.content` after the prefilled `{` normalization.
- Backend endpoint test: conductor dispatch `tool_use` / `tool_result` returns
  role, turn index, input, output, and summary.
- Writer test: `_audit_conductor_turn` preserves `turn_index` and `sub_index`
  in the audit payload.
- Frontend pure helper test: audit records group by role and turn in call
  order, and taskless rows group as System / derived role rather than Agent or
  Unassigned.
- Frontend source or component test: audit page mounts the role-chain view while
  preserving raw rows.

#### 7. Wrong vs Correct

Wrong:

```python
return {"items": [entry.__dict__ for entry in page]}
```

Correct:

```python
payloads = {entry.id: _audit_payload_object(entry.payload_json) for entry in page}
task_roles = await _load_audit_task_roles(page, payloads)
return {"items": [{**serialize_row(entry), **_derive_audit_call_metadata(entry, payloads[entry.id], task_roles)} for entry in page]}
```

### Scenario: Safe Operational Diagnostics API

#### 1. Scope / Trigger

- Trigger: adding or changing machine-readable operational endpoints such as `GET /api/diagnostics`.
- These endpoints are cross-cutting support contracts: they inspect storage, runtime catalog, executors, websockets, and environment flags, so they must be safe to paste into support tickets and CI logs.

#### 2. Signatures

- API: `GET /api/diagnostics`
- Implementation location: `backend/app/interfaces/api.py`
- Success status: `200`
- Store unavailable status: `503` with detail `"SQLite store not available"`

#### 3. Contracts

- Top-level response fields: `service`, `status`, `generated_at`, `database`,
  `runtime_catalog`, `github_pr_followup`, `project_review_scheduler`,
  `executors`, `websockets`, `config`, `checks`.
- `status` is `"ok"` only when all checks are ok; use `"degraded"` when any check is degraded or errored but the endpoint can still return a snapshot.
- Supervisor snapshots such as `github_pr_followup` and
  `project_review_scheduler` produce degraded checks when `last_error` is set
  or when `running` is `true`; running-state details must be short generic
  messages, not project/issue/task content.
- Scheduler-style snapshots with `interval_s` and `last_completed_at` may also
  produce degraded stale checks when the last completion is older than twice the
  configured interval. Missing `last_completed_at` alone is not stale.
- Runtime catalog entries may expose booleans such as `api_endpoint_configured` and `api_key_configured`.
- Runtime catalog entries must not expose raw secret values, raw API keys, bearer tokens, auth headers, or provider credentials.
- Config fields should expose booleans for whether sensitive paths or env values are configured, not their raw values.

#### 4. Validation & Error Matrix

- `codex_store is None` -> HTTP `503`, detail `"SQLite store not available"`.
- Database query raises -> keep HTTP `200`, set `database.status = "error"`, append a database error check, and set top-level `status = "degraded"`.
- Runtime catalog load raises -> keep HTTP `200`, set `runtime_catalog.status = "error"`, append a runtime catalog error check, and set top-level `status = "degraded"`.
- Runtime catalog has no enabled executor -> keep HTTP `200`, append a degraded runtime catalog check, and set top-level `status = "degraded"`.
- Supervisor snapshot has `last_error` -> keep HTTP `200`, append a degraded
  supervisor check using that safe error text, and set top-level `status =
  "degraded"`.
- Supervisor snapshot has `running=true` and no error -> keep HTTP `200`,
  append a degraded supervisor check with a generic running-state detail, and
  set top-level `status = "degraded"`.
- Scheduler snapshot has `last_completed_at` older than `interval_s * 2` and
  no error/running state -> keep HTTP `200`, append a degraded stale check with
  a generic detail, and set top-level `status = "degraded"`.

#### 5. Good/Base/Bad Cases

- Good: report executor availability and `api_key_configured: true` without returning the key.
- Base: return zero counts and empty subscriber counts when no sessions, processes, or websocket subscribers exist.
- Bad: returning `api_key`, `OPENAI_API_KEY`, token strings, workspace root paths, or SQLite paths in the diagnostics payload.

#### 6. Tests Required

- Test that `GET /api/diagnostics` returns all top-level sections.
- Test that a configured runtime API key is represented only by `api_key_configured: true`.
- Test that the raw API key string is absent from the full serialized response body.
- Test the `503` behavior when `codex_store` is unavailable.

#### 7. Wrong vs Correct

Wrong:

```python
{"api_key": executor.api_key, "sqlite_db_path": os.getenv("SQLITE_DB_PATH")}
```

Correct:

```python
from app.application import timeouts

{
    "api_key_configured": bool(executor.api_key),
    "sqlite_enabled": timeouts.use_sqlite(),
}
```

### Scenario: Runtime Catalog Secret Redaction

#### 1. Scope / Trigger

- Trigger: adding or changing runtime catalog APIs, settings UI payloads, executor credentials, or provider secret storage.
- Runtime catalog secrets are needed by backend execution paths, but read responses are consumed by multiple browser surfaces and must be treated as public data.

#### 2. Signatures

- API: `GET /api/runtime-catalog`
- API: `PUT /api/runtime-catalog`
- Storage model: `RuntimeExecutorConfig.api_key`
- Public response field: `api_key_configured: boolean`

#### 3. Contracts

- Stored catalogs may contain `api_key`.
- Browser-facing read/update responses must not include raw `api_key`.
- Browser-facing responses must expose `api_key_configured` so UI can show that a key exists.
- `PUT /api/runtime-catalog` must preserve an existing stored key when the request omits the `api_key` field for an executor.
- `PUT /api/runtime-catalog` may replace/clear a key only when the request explicitly includes `api_key`.

#### 4. Validation & Error Matrix

- `codex_store is None` -> HTTP `503`, detail `"SQLite store not available"`.
- Invalid catalog references -> HTTP `400`, validation detail.
- Request omits `api_key` for an existing executor -> save non-secret changes and preserve existing key.
- Request includes `api_key` -> save the supplied value, but return only `api_key_configured`.

#### 5. Good/Base/Bad Cases

- Good: settings UI changes a model name without deleting the stored key.
- Base: new executor without a key returns `api_key_configured: false`.
- Bad: returning raw API keys from `GET /api/runtime-catalog` or keeping raw keys in frontend app state after save.

#### 6. Tests Required

- Test that `GET /api/runtime-catalog` and `PUT /api/runtime-catalog` responses never contain the raw key string.
- Test that public responses omit `api_key` and include `api_key_configured`.
- Test that an update payload omitting `api_key` preserves the previously stored key.

#### 7. Wrong vs Correct

Wrong:

```python
return await service.load_catalog()
```

Correct:

```python
catalog = await service.load_catalog()
return {
    "executors": [
        {"id": executor.id, "api_key_configured": bool(executor.api_key)}
        for executor in catalog.executors
    ]
}
```

### Scenario: Runtime Catalog Test Timeout Contract

#### 1. Scope / Trigger

- Trigger: changing `POST /api/runtime-catalog/test`, executor test
  requests, runtime catalog timeout fields, or OpenAI/Anthropic provider
  probe behavior.
- Runtime test is a real provider call from the backend. It must reflect the
  configured runtime tolerance while still capping request duration for UI
  responsiveness.

#### 2. Signatures

- API: `POST /api/runtime-catalog/test`
- Request model: `TestExecutorRequest(executor_id, provider_id?, model_id?, api_endpoint?, api_key?)`
- Timeout source: `RuntimeCatalog.conductor_llm.timeout_s`
- Timeout helper: `_runtime_test_timeout_s(catalog: RuntimeCatalog) -> float`
- OpenAI probe URL: `llm_api_url(endpoint, "/v1/chat/completions")`
- Anthropic probe URL: `llm_api_url(endpoint, "/v1/messages")`

#### 3. Contracts

- Effective executor/provider/model resolution follows the saved runtime
  catalog, with request overrides for endpoint/key/model when supplied.
- OpenAI protocol probes send `{"model": model_id, "max_tokens": 1,
  "messages": [{"role": "user", "content": "ping"}]}` to
  `/v1/chat/completions`.
- Anthropic protocol probes send the same logical ping body to `/v1/messages`
  with `x-api-key` and `anthropic-version`.
- Timeout must derive from `catalog.conductor_llm.timeout_s` and clamp to the
  inclusive range `10.0..120.0`.
- Missing or falsey timeout defaults to `10.0`.
- Timeout error text must report the effective timeout value, for example
  `Request timed out after 120s`.
- Runtime test responses must never expose raw API keys or bearer tokens.

#### 4. Validation & Error Matrix

- Unknown executor id -> HTTP `404`.
- Unknown provider id for that executor -> HTTP `400`.
- No resolved model -> HTTP `400`.
- Provider model id not present in provider model list -> HTTP `400`.
- Missing resolved endpoint or key -> HTTP `400`.
- Provider returns HTTP error -> `{"success": false, "error": "HTTP <status>: <sanitized prefix>"}`.
- Provider request times out -> `{"success": false, "error": "Request timed out after <effective>s"}`.
- Successful provider HTTP `200` -> `{"success": true, "latency_ms": <float>}`.

#### 5. Good/Base/Bad Cases

- Good: a catalog with `conductor_llm.timeout_s=120` lets a slow
  OpenAI-compatible local proxy finish instead of failing at a hard-coded 10s.
- Base: omitted conductor timeout uses 10s and keeps quick UI feedback.
- Base: a request supplies `api_endpoint`/`api_key` overrides to test an
  unsaved form draft without persisting the key.
- Bad: hard-coding `httpx.AsyncClient(timeout=10)` in the endpoint.
- Bad: returning raw provider response headers or auth data in the failure
  payload.

#### 6. Tests Required

- API contract test: OpenAI protocol uses `/v1/chat/completions`, bearer auth,
  the selected model, and the clamped catalog timeout.
- API contract test: saved API keys are preserved/masked when the UI omits
  `api_key`, so test requests can still use the stored key.
- API contract test: timeout errors include the effective timeout rather than a
  stale hard-coded value.
- API contract test: provider/executor/model validation returns the expected
  HTTP status without making an outbound request.

#### 7. Wrong vs Correct

Wrong:

```python
async with httpx.AsyncClient(timeout=10) as client:
    response = await client.post(...)
```

Correct:

```python
timeout_s = _runtime_test_timeout_s(catalog)
async with httpx.AsyncClient(timeout=timeout_s) as client:
    response = await client.post(...)
```

### Scenario: Safe Knowledge Search Snippets

#### 1. Scope / Trigger

- Trigger: adding/changing FTS snippets, knowledge search responses, artifact previews, or frontend `dangerouslySetInnerHTML` rendering.
- FTS snippets include indexed issue/artifact text, which can contain user-authored HTML.

#### 2. Signatures

- Backend helper: `_sanitize_fts_snippet(snippet: str | None) -> str`
- Search response fields: `issues[].snippet`, `artifacts[].snippet`
- Frontend render target: knowledge search result snippets

#### 3. Contracts

- Snippets may preserve backend-generated `<mark>` and `</mark>` tags only.
- All indexed text from issues/artifacts must be HTML-escaped before reaching a browser HTML sink.
- Frontend components must not render raw issue/artifact text through `dangerouslySetInnerHTML` unless the backend contract guarantees sanitization.

#### 4. Validation & Error Matrix

- Empty snippet -> empty string.
- Snippet contains user HTML such as `<img onerror=...>` -> escaped text such as `&lt;img ...&gt;`.
- Snippet contains FTS-generated `<mark>` tags -> preserve those exact tags.
- Snippet contains non-mark tags from indexed content -> escape them.

#### 5. Good/Base/Bad Cases

- Good: `&lt;img src=x onerror=alert(1)&gt; <mark>token</mark>`.
- Base: plain text snippets render unchanged except for escaped HTML characters.
- Bad: `<img src=x onerror=alert(1)> <mark>token</mark>` reaches `dangerouslySetInnerHTML`.

#### 6. Tests Required

- Test that malicious indexed HTML is escaped in artifact snippets.
- Test that `<mark>` highlighting remains available after sanitization.
- Test both issue and artifact snippet paths when modifying shared snippet logic.

#### 7. Wrong vs Correct

Wrong:

```python
{"snippet": row["snippet"]}
```

Correct:

```python
{"snippet": _sanitize_fts_snippet(row["snippet"])}
```

### Scenario: Safe Skill Proxy Fetching

#### 1. Scope / Trigger

- Trigger: adding or changing remote skill preview fetching, URL rewriting, or CORS proxy behavior.
- The proxy runs server-side with local network access, so it must not become a generic URL fetcher.

#### 2. Signatures

- API: `GET /api/skills/proxy?url=<absolute http(s) URL>`
- Helpers: `_rewrite_to_raw(url: str) -> str`, `_validate_skill_proxy_url(url: str) -> str`
- Allowed upstream hosts: `raw.githubusercontent.com`, `gist.githubusercontent.com`

#### 3. Contracts

- Browser-facing callers may pass common GitHub/Gist view URLs; the backend may rewrite them to raw URLs.
- After rewriting, the final target host must be in the allowlist before any network request is made.
- The proxy must not follow redirects, because redirects can leave the allowlisted host after validation.
- The proxy returns markdown text only; HTML content types are rejected.

#### 4. Validation & Error Matrix

- Missing or non-http(s) URL -> HTTP `400`.
- Host outside allowlist, including loopback/private/local hosts -> HTTP `400`, detail contains `"not allowed"`.
- Upstream redirect -> HTTP `400`.
- Upstream HTTP error -> matching upstream status.
- Upstream HTML content type -> HTTP `415`.

#### 5. Good/Base/Bad Cases

- Good: `https://github.com/owner/repo/blob/main/SKILL.md` rewrites to `https://raw.githubusercontent.com/...` and fetches markdown.
- Base: `https://gist.github.com/user/<id>` rewrites to `https://gist.githubusercontent.com/.../raw`.
- Bad: `http://127.0.0.1:8000/secret.md`, cloud metadata IPs, or arbitrary intranet URLs are fetched.

#### 6. Tests Required

- Test that loopback/private URLs are rejected before fetch.
- Test GitHub/Gist view URL rewriting still produces an allowed raw host.
- Test redirects are rejected when proxy behavior changes.

#### 7. Wrong vs Correct

Wrong:

```python
async with httpx.AsyncClient(follow_redirects=True) as client:
    return await client.get(url)
```

Correct:

```python
target = _validate_skill_proxy_url(_rewrite_to_raw(url))
async with httpx.AsyncClient(follow_redirects=False) as client:
    return await client.get(target)
```

### Scenario: Issue Orchestration Policy Contract

#### 1. Scope / Trigger

- Trigger: adding or changing deterministic Conductor scheduling policy, the issue policy endpoint, or frontend policy display surfaces.
- The policy is a cross-layer contract: backend classification steers the Conductor prompt and the browser displays the same policy without reimplementing heuristics.

#### 2. Signatures

- Classifier: `classify_issue_orchestration(title: str | None, description: str | None) -> OrchestrationPolicy`
- Prompt helper: `render_issue_orchestration_policy_block(title: str | None, description: str | None) -> str`
- API: `GET /api/codex/issues/{issue_id}/orchestration-policy`

#### 3. Contracts

- Response fields: `issue_id: string`, `recommendation: string`, `batch_allowed: boolean`, `signals: string[]`, `guidance: string[]`.
- Known recommendation values: `pm_first`, `architect_first`, `batch_allowed`, `single_engineer`.
- Known signal values: `explicit_parallel`, `independent_slices`, `trivial`, `ambiguous_scope`, `risk_or_cross_layer`, `default_serial`.
- The backend classifier is the source of truth. Frontend code may derive display tone/copy from the response, but must not duplicate scheduling heuristics.
- `batch_allowed=true` is only valid when the issue explicitly asks for parallel work and the classifier detects independent slices.

#### 4. Validation & Error Matrix

- `codex_store is None` -> HTTP `503`, detail `"SQLite store not available"`.
- Issue id does not exist -> HTTP `404`, detail contains the issue id.
- Empty or underspecified issue text -> `pm_first`, `batch_allowed=false`, includes `ambiguous_scope`.
- Risky/cross-layer issue text -> `architect_first`, `batch_allowed=false`, includes `risk_or_cross_layer`.
- Explicit parallel independent issue text -> `batch_allowed`, `batch_allowed=true`, includes `explicit_parallel` and `independent_slices`.
- Small/trivial issue text -> `single_engineer`, `batch_allowed=false`, includes `trivial`.

#### 5. Good/Base/Bad Cases

- Good: Conductor prompt and UI panel both reflect the same classifier result for the same issue title/description.
- Base: A normal clear issue returns `single_engineer` and `batch_allowed=false`.
- Bad: frontend infers `batch_allowed=true` from keywords without calling the backend endpoint.

#### 6. Tests Required

- Unit-test classifier branches for trivial, ambiguous, risky/cross-layer, and explicit independent parallel issues.
- Test prompt rendering includes recommendation, batch allowance, signals, and guidance.
- Test the endpoint returns the stable response shape, `404` for missing issues, and `503` when the store is unavailable.
- Frontend tests must assert the typed client URL-encodes issue ids and display derivation consumes the response shape without adding scheduling heuristics.

#### 7. Wrong vs Correct

Wrong:

```typescript
const batchAllowed = issue.description.includes("parallel");
```

Correct:

```typescript
const policy = await getIssueOrchestrationPolicy(issue.id);
const batchAllowed = policy?.batch_allowed ?? false;
```

### Scenario: LLM HTTP Client Environment Isolation

#### 1. Scope / Trigger

- Trigger: creating or changing outbound HTTP clients used for LLM provider calls.
- LLM calls run from the local desktop environment, where `NO_PROXY` / proxy variables may contain OS- or shell-specific values such as bare IPv6 loopback entries.

#### 2. Signatures

- Helper: `_llm_http_client(timeout_s: float) -> httpx.AsyncClient`
- Call sites: Anthropic-compatible and OpenAI-compatible requests in `application/llm_runner.py`.

#### 3. Contracts

- LLM provider clients must pass `trust_env=False`.
- Timeout is still supplied explicitly by the caller.
- This rule applies to LLM provider traffic only; generic API clients keep their own security and redirect rules.

#### 4. Validation & Error Matrix

- `NO_PROXY` contains bare IPv6 entries such as `::1` -> client construction must not raise.
- Provider request times out -> existing timeout handling logs and returns the fallback result.
- Provider returns non-JSON or HTTP error -> existing sanitized error handling applies.

#### 5. Good/Base/Bad Cases

- Good: LLM call succeeds or fails based on provider behavior, not local proxy parsing.
- Base: unset proxy environment behaves the same as before.
- Bad: `httpx.AsyncClient(...)` inherits a local `NO_PROXY` value and crashes before the provider request is sent.

#### 6. Tests Required

- Test that constructing the LLM HTTP client ignores invalid local proxy bypass entries.
- Test streaming/non-streaming call behavior through the shared helper when adding new LLM request paths.

#### 7. Wrong vs Correct

Wrong:

```python
async with httpx.AsyncClient(timeout=timeout_s) as client:
    ...
```

Correct:

```python
async with _llm_http_client(timeout_s) as client:
    ...
```

### Scenario: WebSocket Initial Send Disconnects

#### 1. Scope / Trigger

- Trigger: sending initial WebSocket snapshot/replay frames before the endpoint enters a shared subscriber loop.
- Browser navigation can close the socket immediately after `accept()`, before subscriber cleanup code has been installed.

#### 2. Signatures

- Endpoint shape: `async def <stream>(websocket: WebSocket, ...)`
- Guard helper shape: `_send_*_initial_*(websocket, state) -> bool`

#### 3. Contracts

- Initial snapshot/replay sends must catch `WebSocketDisconnect` and return without registering a subscriber.
- Subscriber loops may still catch `WebSocketDisconnect` at their own boundary.
- A normal browser disconnect must not become an ASGI application exception.

#### 4. Validation & Error Matrix

- Client disconnects during initial snapshot send -> endpoint returns quietly.
- Client remains connected -> endpoint registers subscriber and enters the normal sender/receiver loop.
- Store/resource is missing before accept -> existing close code and reason still apply.

#### 5. Good/Base/Bad Cases

- Good: fast route changes produce normal `connection closed` logs only.
- Base: initial snapshot and `Ready` frame are sent before subscribing.
- Bad: `await websocket.send_json(...)` before the subscriber loop lets `WebSocketDisconnect` escape to uvicorn.

#### 6. Tests Required

- Unit-test the initial-send helper with a fake WebSocket that raises `WebSocketDisconnect`.
- Keep backpressure/subscriber tests covering queue overflow and clean terminal closes.

#### 7. Wrong vs Correct

Wrong:

```python
await websocket.send_json(snapshot)
sub = WsSubscriber(websocket, maxsize=WORKSPACE_QUEUE_MAXSIZE)
```

Correct:

```python
if not await _send_workspace_initial_snapshot(websocket, state):
    return
sub = WsSubscriber(websocket, maxsize=WORKSPACE_QUEUE_MAXSIZE)
```

### Scenario: Artifact File Boundary Safety

#### 1. Scope / Trigger

- Trigger: scanning issue artifact folders, backfilling artifact rows, reading artifact preview content, or building artifact zip downloads.
- Artifact paths can come from disk scans or persisted rows, so every file read/archive path needs a filesystem boundary check.

#### 2. Signatures

- Scanner: `_scan_and_backfill_artifacts(issue_id: str, session_id: str, store) -> list[dict]`
- Roots helper: `_artifact_issue_roots(issue_id: str, session_id: str, store) -> list[Path]`
- Guard helper: `_is_safe_artifact_file(path: Path, roots: list[Path]) -> bool`
- Preview API: `GET /api/codex/issues/{issue_id}/artifacts`
- Download API: `GET /api/codex/issues/{issue_id}/artifacts/download`

#### 3. Contracts

- An artifact file is safe only when it is a regular file, not a symlink, and its resolved path remains under one of the issue artifact roots.
- Directory traversal must not follow symlinked directories.
- Artifact preview must re-check persisted artifact paths before returning a row or reading content.
- Zip download must re-check persisted artifact paths instead of trusting database rows.
- Stores used in tests may omit task-list methods; root discovery must still fall back to the workspace issue root.

#### 4. Validation & Error Matrix

- Symlink file -> skip.
- Symlink directory -> skip.
- Regular file resolving outside issue roots -> skip.
- Missing file or unreadable file -> skip.
- No artifacts after filtering -> return an empty zip when rows existed but no safe files remained.

#### 5. Good/Base/Bad Cases

- Good: `issues/<issue_id>/pm/prd.md` is scanned and zipped.
- Base: stale DB row pointing to a deleted file is ignored.
- Bad: `issues/<issue_id>/pm/leak.md -> /tmp/secret.md` is scanned, indexed, previewed, or zipped.

#### 6. Tests Required

- Test scan skips symlinks that point outside the issue root.
- Test preview skips symlink artifact rows.
- Test zip skips symlink artifact rows.
- Test regular artifacts under the issue root still zip correctly.

#### 7. Wrong vs Correct

Wrong:

```python
if path.exists() and path.is_file():
    zf.write(path, arcname)
```

Correct:

```python
if _is_safe_artifact_file(path, safe_roots):
    zf.write(path, arcname)
```

---

### Scenario: Worktree-Scoped Branch Merge (Swarm-Safe)

#### 1. Scope / Trigger

- Trigger: merging a source branch into a target branch when the target branch is **NOT checked out in the primary repo** but lives in a separate `git worktree` (the parallel-swarm case: agent branches merge back into the issue integration branch, which is checked out in the issue worktree while the primary repo sits on `main`).
- Why code-spec depth: this is a destructive git operation that, done naively, **silently advances the primary repo's checked-out branch (`main`)** onto unreviewed changes — bypassing the human review gate. Discovered empirically during PR3 of `05-29-parallel-swarm-scheduler` (real-git repro: `main` fast-forwarded onto agent changes).

#### 2. Signatures

```python
# git_service.py
async def squash_merge(repo, source_branch, base_branch, message) -> str
#   ^ fast-forwards the PRIMARY repo (assumes base_branch is checked out there).
#     Safe ONLY for the issue→default merge (merge_issue, base=main checked out in primary repo).

async def squash_merge_into_branch(
    repo, source_branch, target_branch, message, target_worktree_path=None
) -> str
#   ^ swarm-safe: squash-merges in a throwaway DETACHED temp worktree,
#     advances ONLY refs/heads/<target_branch> via update-ref,
#     resets the target worktree's index/tree ONLY if it has target_branch checked out.
#     NEVER touches the primary repo's checked-out branch.
```

#### 3. Contracts

- `squash_merge_into_branch` advances exactly one ref: `refs/heads/<target_branch>`. The primary repo's `HEAD`/working tree is invariant.
- Conflict → `reset --hard` in the temp worktree + raise `GitError`; no half-state, no partial ref move.
- `target_worktree_path` index sync happens **iff** that worktree actually has `target_branch` checked out (else a bare `update-ref` leaves the worktree index stale → phantom deletions on next `commit_all`).

#### 4. Validation & Error Matrix

- target branch checked out in primary repo (issue→default) → use `squash_merge` (fast-forward is correct there).
- target branch checked out in a worktree, primary on another branch → use `squash_merge_into_branch` (plain `squash_merge` would pollute the primary branch).
- merge conflict → `GitError` raised; caller collects `conflicted_files` + `worktree_diff` and surfaces for reconcile; already-merged refs are NOT rolled back.

#### 5. Good/Base/Bad Cases

- Good: agent branch → issue branch via `squash_merge_into_branch`; `main` byte-for-byte unchanged, issue branch accumulates, issue worktree clean.
- Base: issue branch → `main` via `squash_merge` (primary repo on `main`).
- Bad: agent branch → issue branch via plain `squash_merge`; `main` silently fast-forwards onto unreviewed agent changes.

#### 6. Tests Required

- Regression: after merging ≥2 agent branches into the issue branch, assert the default branch ref **and tree** are unchanged and contain none of the agent files (`test_merge_agent_worktrees_does_not_pollute_default_branch`).
- Conflict: stop-on-first-conflict, conflicting worktree kept, earlier merges not rolled back, structured `conflicted_files`+diff returned.
- No temp/probe worktree leaks across success/conflict/cleanup paths.

#### 7. Wrong vs Correct

Wrong:

```python
# target (issue branch) lives in a worktree, primary repo is on main:
await git.squash_merge(repo, agent_branch, issue_branch, msg)  # ff's main onto agent work
```

Correct:

```python
await git.squash_merge_into_branch(
    repo, agent_branch, issue_branch, msg,
    target_worktree_path=issue.git_worktree_path,
)
```

#### 8. Terminal-state swarm cleanup (resource hygiene)

- `dispatch_batch` retains per-agent `swarm/<issue.id[:8]>-*` branches + `swarm-<issue.id>-*` worktrees on the conflict / non-merged path (intentional — for reconcile). Their cleanup owner is the conductor terminal seal: `worktree_manager.cleanup_issue_swarm_worktrees(project, issue)`, called best-effort at the end of `_seal_graph_and_issue_status` (`conductor_main_loop.py`).
- Contract: enumerate residuals from **real git state** (`git worktree list` + `git branch --list 'swarm/<prefix>*'`), NOT in-memory lineage (not persisted; gone at terminal time). Discovery prefixes MUST byte-match creation (`_worktree_path` / `_agent_branch_name`): dir uses full `issue.id`, branch uses `issue.id[:8]`.
- HARD: only removes worktrees + force-deletes `swarm/*` refs (`git branch -D`, regex-gated). NEVER merge/checkout/advance `main` or the issue branch. Idempotent + best-effort: missing residuals skip silently; a cleanup failure logs a warning and never blocks the terminal seal.
- Tests: real-git integration asserting residual worktree+branch removed, `git rev-parse main` byte-identical before/after, sibling-issue swarm branches survive (issue-scoped discovery).

---

### Scenario: Isolated Worktree Upstream Visibility

#### 1. Scope / Trigger

- Trigger: forking a per-agent worktree (`prepare_agent_worktree`, base = issue branch) for parallel fan-out where the agent must see upstream artifacts (PM/architect output) produced earlier in the same issue.
- Why: a worktree forked from a branch sees **only what is committed to that branch**. Upstream roles write artifacts into the shared issue worktree but do not auto-commit, so a freshly forked agent worktree would see a stale tree.

#### 2. Signatures

```python
# worktree_manager.py
async def commit_issue_worktree(issue, message=None) -> str | None
#   flush the shared issue worktree's uncommitted changes onto the issue branch.
async def prepare_agent_worktree(project, issue, agent_key) -> (branch, path, base)
```

#### 3. Contracts

- `commit_issue_worktree` MUST run **before** `prepare_agent_worktree` in any fan-out path.
- Idempotent: returns `None` when there is nothing to commit.

#### 4. Validation & Error Matrix

- uncommitted upstream artifacts present → commit them, then fork → agent sees them.
- nothing to commit → `None`, fork proceeds.
- issue has no `git_branch` yet → `prepare_agent_worktree` raises `WorktreeError` (prepare the issue worktree first).

#### 5. Good/Base/Bad Cases

- Good: `dispatch_batch` flushes once, then forks N agent worktrees that all see upstream output.
- Bad: fork first, then agent reads `task.workspace_path` and misses uncommitted upstream artifacts.

#### 6. Tests Required

- Assert a forked agent worktree contains an upstream artifact that was uncommitted in the issue worktree before the batch (flush-then-fork).
- Assert `commit_issue_worktree` is idempotent (`None` on clean tree).

#### 7. Wrong vs Correct

Wrong:

```python
wt = await wm.prepare_agent_worktree(project, issue, key)  # forks stale tree
```

Correct:

```python
await wm.commit_issue_worktree(issue)                      # flush upstream first
wt = await wm.prepare_agent_worktree(project, issue, key)
```

---

### Scenario: Cost / Budget Is Soft, Not a Hard Gate

#### 1. Scope / Trigger

- Trigger: anything touching issue cost aggregation, per-model pricing, or budget-driven Conductor behavior (`budget_service.py`, `usage_utils.price_tokens`, `dispatch_batch` concurrency).
- Why code-spec depth: budget is **advisory** — it steers via prompt + concurrency, it must NEVER hard-kill the loop. A future dev "tightening" this into a hard stop would break the design contract. Also, naive cost aggregation double-counts.

#### 2. Signatures

```python
# usage_utils.py
def price_tokens(input_tokens, output_tokens, cache_read_tokens, pricing=None) -> float
#   pricing: RuntimeModelConfig|dict|None. Per-rate: model price if set, else global env rate.
def price_tokens_for_model(model, ...) -> float

# budget_service.py
def aggregate_issue_spend_usd(store, issue_id) -> float   # COMPLETED runs only
def budget_steering_event(status) -> dict | None          # None when no ceiling / healthy

# timeouts.py
def resolve_issue_budget_usd(issue_budget) -> float       # None -> global default; 0 -> unlimited
def budget_supported_concurrency(remaining, configured_cap, over_budget) -> int
```

#### 3. Contracts

- `price_tokens(pricing=None)` is byte-identical to the legacy global-rate path (backward compat). Per-rate fallback: a model with only `input_usd_per_m` set uses env rates for output/cache.
- Spend aggregation counts only `ExecutionProcess.status in {Completed, Failed, Killed}` — never `Running` (its `total_cost_usd` is not final).
- `budget_usd`: `None` → global default; `0` → unlimited (no warnings, no wind-down, no concurrency squeeze).
- `budget_supported_concurrency` only ever **lowers** the cap: `min(cap, floor(remaining / EST_COST_PER_AGENT_USD))`, clamped ≥ 1; `remaining is None` (unlimited) → cap unchanged; `over_budget` → 1.

#### 4. Validation & Error Matrix

- spend ≥ `BUDGET_SOFT_WARN_RATIO * budget` → `budget_warning` event + WARNING-tone block (no kill).
- spend ≥ budget (over) → `budget_exceeded` event + wind-down steer toward `finalize_task` (no kill).
- aggregation / price collection / concurrency calc raises → best-effort: omit budget block / fall back to configured cap; loop and batch proceed.
- budget = 0 (unlimited) → no events, no squeeze, no false "over".

#### 5. Good/Base/Bad Cases

- Good: over budget → loop keeps running, gets a strong wind-down steer, batch concurrency drops to 1.
- Base: healthy budget → neutral block, configured cap, no events.
- Bad: over budget hard-kills the loop or forces batch concurrency to 0 — violates the soft-semantics contract.

#### 6. Tests Required

- price: per-rate model pricing + env fallback (priced + partial + unpriced regression).
- aggregation: a `Running` process is excluded from the sum.
- soft semantics: over-budget loop still returns `status="done"` (asserted no hard kill).
- concurrency: tight budget downscales effective `dispatch_batch` peak (≥1); unlimited does not.

#### 7. Wrong vs Correct

Wrong:

```python
if status.over_budget:
    raise BudgetExceeded()        # hard-kills the loop — violates the contract
spent = sum(p.total_cost_usd for p in all_processes)   # counts Running → double-count
```

Correct:

```python
if (ev := budget_steering_event(status)):
    emit(ev)                      # soft: event + prompt steer, loop continues
spent = aggregate_issue_spend_usd(store, issue_id)     # completed runs only
```

---

### Scenario: Engineer/QA Real-Codegen Reconciliation (Claim vs Git Ground Truth)

#### 1. Scope / Trigger

- Trigger: changing how the Engineer persists its report (`EngineerWorkflow.persist_result`) or how QA reconciles its verdict (`QAWorkflow.persist_result`) against the real worktree git diff.
- Why code-spec depth: an Engineer (LLM) can declare victory while only writing a markdown report, or misname the files it touched. The framework treats the git diff as ground truth and reconciles deterministically. The hard/soft split must follow the repo philosophy: claim-vs-reality contradiction is a HARD fact; everything else is a SOFT signal that never hard-kills.

#### 2. Signatures

```python
# engineer_workflow.py
def git_changed_files(workspace_path: str | None) -> list[str]   # module-level, single source of truth
class EngineerWorkflow:
    def _apply_diff_cross_check(self, report, actually_changed: list[str]) -> None  # in-place C1 + C2
    @staticmethod
    def _claims_implementation(report) -> bool

# qa_workflow.py
class QAWorkflow:
    @staticmethod
    def _git_cross_check(current_status, workspace_path, issue_id) -> tuple[str, str | None]  # D1
```

#### 3. Contracts

- **C1 (downgrade, HARD):** a report that *claims it landed code* — status ∈ {completed, partial} AND a non-empty `changed_files` (it named files it claims to have modified) — but produces a ZERO real git diff is downgraded to `partial`, `changed_files` cleared, and a `[framework]` qa_note prepended. Covers BOTH `completed` and `partial`.
- **`completed_tasks` is NOT a C1 hard trigger:** the only unambiguous code-landing signal is a non-empty `changed_files`. An honest `changed_files=[]` already-implemented report legitimately lists the task it addressed in `completed_tasks` (the task WAS handled, just without new code), so treating `completed_tasks` as a landing claim would downgrade an honest "already implemented" report (AC4 violation). This is the identical definition of a code-landing claim used by the Architect-Review guard (`review_guard.compute_review_guard` uses `bool(claimed_set)` only) — one consistent notion across the chain.
- **Legal empty diff is NOT a claim:** status=blocked, or `changed_files=[]` (already-implemented / nothing-to-change, with or without `completed_tasks`), is honest and left untouched by C1. The hard trigger is the claim-vs-reality contradiction (named changed files vs zero diff), never "diff is empty". The already-implemented empty-diff case is surfaced only by the SOFT D1 / LLM layers, never by a C1 status downgrade.
- **C2 (reconcile, ground truth):** when real changes DO exist, the report's `changed_files` is overwritten with the actual git-diff set whenever it diverges (after `./`-stripping path normalization), plus a `[framework]` qa_note recording claimed-vs-actual. No divergence → list left verbatim, no note (no noise).
- **D1 (QA soft signal):** layered ON TOP of the command reconcile. If the Engineer report implies implementation (status != blocked, or has completed_tasks) but the worktree shows zero diff, QA bumps to `needs_follow_up` — even when the Engineer recommended no commands. NEVER weakens a `failed` (real non-zero command exit is the stronger fact) and never hard-kills.
- `git_changed_files` is the one base-fallback implementation (origin/main → main → HEAD~1); Engineer cross-check, review guard, and QA D1 all reuse it.

#### 4. Validation & Error Matrix

- claims implementation + zero diff → C1 downgrade to partial + note.
- partial + real (matching) diff → untouched.
- completed/partial + honest `changed_files=[]` + zero diff → NOT flagged by C1 (legal already-implemented / blocked), whether or not `completed_tasks` is listed.
- claimed files ≠ actual files (real changes exist) → C2 rewrite to actual + note; claimed == actual → no note.
- QA: engineer implies impl + zero diff + no commands → `needs_follow_up`. Engineer blocked / real changes → no bump. Command non-zero exit → stays `failed` regardless of D1.

#### 5. Good/Base/Bad Cases

- Good: Engineer claims `[a.py]`, git shows `[b.py]` → report rewritten to `[b.py]` with a reconcile note; review/QA see the truth.
- Base: honest "already implemented, nothing to change" (status=completed, `changed_files=[]`) survives untouched by C1 — even when it lists the addressed task in `completed_tasks`.
- Bad: hard-rejecting / downgrading the legal empty-diff already-implemented case, or letting D1 override a real command failure.

#### 6. Tests Required

- C1: completed+zero-diff downgrade; partial+zero-diff(claiming files) downgrade; legal empty `changed_files` (completed & partial, incl. with completed_tasks) NOT flagged; partial+real-diff untouched.
- C2: claimed≠actual rewrite + note; claimed==actual no note.
- D1: implies-impl + zero diff + no commands → needs_follow_up; real changes → no bump; blocked engineer → no bump; non-zero command exit stays failed (reconcile not regressed).

#### 7. Wrong vs Correct

Wrong:

```python
if report.status == "completed" and not git_changed_files(ws):  # misses partial; ignores claimed files
    report.status = "partial"
```

Correct:

```python
actually_changed = git_changed_files(ws)
self._apply_diff_cross_check(report, actually_changed)  # C1 (completed+partial) + C2 reconcile
```

---

### Scenario: Architect-Review Deterministic Tiered Guard (diff-vs-plan)

> The Architect-Review-side counterpart of *Engineer/QA Real-Codegen Reconciliation* above.
> Same one notion of a code-landing claim (`bool(claimed_changed_files)`), same single
> `git_changed_files` base-fallback. This scenario covers the **review decision**, not the report.

#### 1. Scope / Trigger

- Trigger: an engineer→architect review task (`task_kind="review"`, has `parent_task_id`) is about to be dispatched, OR an architect review prompt is being built. Before this guard the review LLM saw only requirement / system_design / implementation_report markdown — **zero git ground truth** — so "report claims work, code is empty" survived on luck. This guard makes the claim-vs-reality check deterministic and feeds the real diff to the LLM.
- Cross-layer: reads git (worktree), `implementation_plan.json` (architect artifact), the engineer report, and short-circuits an API dispatch path → code-spec depth mandatory.

#### 2. Signatures

```python
# review_guard.py  (pure, synchronous, read-only — safe to call inside sync prompt-build)
def compute_review_guard(workspace_path: str | None, issue_id: str,
                         *, include_diff_summary: bool = True) -> ReviewGuardResult
#   ReviewGuardResult: {verdict: "hard_mismatch"|"plan_drift"|"ok",
#                       claimed_files, actual_files, expected_files,
#                       missing, extra, diff_summary}

# architect_workflow.py
class ReviewReportDocument(BaseModel):
    ...
    framework_guard: dict | None = None   # B5; default None = backward compatible

# api.py
async def submit_codex_task_for_review(task_id): ...   # B2 short-circuit lives here, BEFORE run_codex_task
def _apply_automated_review_to_parent(parent_task, artifact) -> None   # shared by LLM + synthetic-reject paths
```

#### 3. Contracts

- **Ground truth (deterministic):** actual changed files come from the single `git_changed_files` (origin/main → main → HEAD~1 fallback, includes untracked via `git status --porcelain`). `diff_summary` is a truncated real-diff text. `expected_files` is the union of `ImplementationTask.expected_files` from `implementation_plan.json` (tolerant of legacy artifacts → `[]`). All paths normalized repo-relative, leading `./` stripped, before comparison.
- **HARD (`hard_mismatch`) — claim-vs-reality contradiction:** report claims it landed code (non-empty `claimed_changed_files`, same `bool(claimed_set)` definition as Engineer C1 — `completed_tasks` is NOT a signal) but actual git diff is empty. → In `submit_codex_task_for_review`, **before** `run_codex_task`, write a synthetic `ReviewReportDocument(decision="reject", reason="[FRAMEWORK] report-claim mismatch…", framework_guard=…)`, apply it to parent (`status="rework"` + `[FRAMEWORK]` `review_comment`) via `_apply_automated_review_to_parent`, mark the review task done, and `return`. **The LLM is never invoked.**
- **Legal empty diff (AC4):** honest `changed_files=[]` (already-implemented / blocked) with zero diff is NOT `hard_mismatch` — the LLM review IS dispatched (it still sees the empty diff via injected context). The hard trigger is the contradiction, never "diff is empty".
- **SOFT (`plan_drift`):** real changes exist but diverge from `expected_files` (missing and/or extra). → NOT a short-circuit. `{expected, actual, missing, extra}` + `diff_summary` are injected into `_build_review_prompt` as an explicitly-labelled SOFT signal; the LLM weighs it (architect's pre-code file prediction is best-effort, not a contract). Empty `expected_files` → soft layer skipped, only the hard layer applies.
- **Artifact (B5):** the guard verdict/missing/extra is recorded on `ReviewReportDocument.framework_guard` (default `None` keeps old artifacts valid).

#### 4. Validation & Error Matrix

- claimed non-empty + zero diff → `hard_mismatch` → deterministic reject, `run_codex_task` NOT called, parent `rework`.
- honest `changed_files=[]` + zero diff (already-implemented/blocked) → NOT hard; LLM dispatched, parent stays `awaiting_review`.
- real changes + `expected_files` has missing/extra → `plan_drift` → soft inject, no short-circuit.
- real changes == expected (or expected empty) → `ok` → normal LLM review with real diff in context.
- legacy `implementation_plan.json` without `expected_files` → treated as `[]`, soft layer skipped, no error.

#### 5. Good/Base/Bad Cases

- Good: engineer report claims `[api.py]`, worktree diff empty → review auto-rejected with `[FRAMEWORK]` reason, no model tokens spent, engineer goes back to `rework`.
- Base: honest "already implemented" review (claimed `[]`, empty diff) → dispatched to the LLM with the empty diff visible; the model, not the framework, decides.
- Bad: short-circuiting the legal empty-diff case (AC4 regression), or building the review prompt without the real diff so the LLM judges blind again.

#### 6. Tests Required

- `hard_mismatch`: end-to-end `submit_codex_task_for_review` with `run_codex_task` monkeypatched → assert `call_count == 0`, `verdict == "hard_mismatch"`, parent `rework` + `[FRAMEWORK]` comment.
- legal-empty (AC4 lock): honest `changed_files=[]` + completed_tasks + zero diff → assert `run_codex_task` `call_count == 1`, `verdict != "hard_mismatch"`.
- `plan_drift`: real change vs `expected_files` missing → `verdict == "plan_drift"`, prompt context contains the missing entry + real diff, no short-circuit.
- untracked new file counted (no false `hard_mismatch`); path normalization `./a.py == a.py`; swarm per-agent worktree base-fallback computes the real change without touching `main`.

#### 7. Wrong vs Correct

Wrong:

```python
# guard only in prompt text → LLM already invoked; cannot save the tokens, and a blind
# reject depends on the model noticing "changed files: None" in prose.
prompt = _build_review_prompt(task)          # LLM runs regardless
```

Correct:

```python
guard = compute_review_guard(task.workspace_path, issue_id)
if guard.verdict == "hard_mismatch":         # BEFORE run_codex_task
    artifact = ReviewReportDocument(decision="reject", reason="[FRAMEWORK] …", framework_guard=guard.as_dict())
    _apply_automated_review_to_parent(parent_task, artifact)
    return                                   # LLM never invoked (AC3)
await run_codex_task(review_task_id)         # ok / plan_drift → LLM sees real diff via injected context
```

---

### Scenario: Unified Audit Log (single-writer, additive, best-effort)

#### 1. Scope / Trigger
- Trigger: recording any LLM call / agent return / tool call / command execution / git op / CLI spawn / generic event for after-the-fact auditing. New DB table + cross-cutting choke-point instrumentation + read API → code-spec depth mandatory.
- Additive: existing rich records (`conductor_turns`, `log_events`, QA `commands_run`) are NOT removed; `audit_log` is one uniform, queryable view layered on top. It deliberately accepts duplication with those tables (a product decision) in exchange for one place to query.

#### 2. Signatures
```python
# audit_logger.py  (singleton, single write entry-point — NEVER write audit_log directly elsewhere)
audit_logger.record(category, *, actor=None, issue_id=None, task_id=None,
    conductor_task_id=None, execution_process_id=None, correlation_id=None,
    status=None, duration_ms=None, payload=None, error=None) -> None  # fire-and-forget, never raises
# categories: llm_call|llm_return|tool_use|tool_result|command_exec|git_command|cli_spawn|event|agent_finalize

# adapters/audit_log_query.py  (shared by both stores — keeps SQL byte-identical)
build_audit_log_query(*, categories, issue_id, task_id, since, until, q, cursor_*, limit) -> (sql, params)
# api.py
GET /api/codex/audit-log?category=&issue_id=&task_id=&since=&until=&q=&cursor=&limit=  -> {items, next_cursor}
```

#### 3. Contracts
- **Single writer**: every choke point routes through `audit_logger.record`. No scattered `save_audit_log` calls (prevents the double-write drift the unified-table choice risks).
- **Async, non-blocking, best-effort**: `record` is pure enqueue onto a bounded `asyncio.Queue` drained by a background worker (mirrors `EventBus._db_worker`). Enqueue is loop-aware — `call_soon_threadsafe` when called off the worker's loop thread (asyncio.Queue is NOT thread-safe; a plain cross-thread `put_nowait` silently stalls the row). Failures log a warning and are swallowed — NEVER raised into the audited hot path. Shutdown flushes (sentinel) BEFORE the store closes.
- **Bounded + drop**: queue has `maxsize` (drop-newest on saturation) + a `dropped` counter; audit is best-effort, so dropping under load beats OOM. Required because `event_bus.append` is high-frequency.
- **Call-level granularity (NOT line-level)**: one row per call/command/event. Per-line stdout/stderr stays in `log_events`, linked via `execution_process_id`; git/QA stdout/stderr stored only as truncated tail. Large payloads truncated (`{__truncated__, preview, original_length}`).
- **No double-write storm**: `event_bus` instrumentation skips event types already captured richer elsewhere or purely streaming (`conductor_turn`, `conductor_turn_delta`, `log`, `message_delta`, `heartbeat`).
- **Secret hygiene**: `cli_spawn` redacts the trailing prompt arg (`<prompt redacted>`); never log raw prompts/secrets into argv payloads.
- **Read API**: all filters fully parameterized (`?` binds, incl. `q` LIKE term — never string-interpolate); keyset cursor `(created_at, id) < (?, ?)` DESC (offset-drift-immune); `limit` clamped; `limit+1` probe for `next_cursor`; garbage cursor → graceful page-1.

#### 4. Validation & Error Matrix
- store/worker not ready, store raises, non-serializable payload → `record` swallows, no propagation.
- queue full → drop-newest, `dropped++`, no raise.
- off-loop-thread enqueue → routed via `call_soon_threadsafe` (row not lost).
- malformed cursor → `(None, None)` → page 1.
- injection in `q`/filters → bound as values, table intact.

#### 5. Good/Base/Bad Cases
- Good: a git merge, a conductor LLM turn, and a QA command each leave one queryable `audit_log` row, filterable by issue + category, without slowing the operation.
- Base: under an event burst, newest rows drop with a counted warning — the operation never blocks.
- Bad: writing `audit_log` directly from a choke point (drift); awaiting the DB on the hot path; re-copying per-line stdout into `audit_log`; string-interpolating a filter into SQL.

#### 6. Tests Required
- each category lands via its real instrumented function (mutation-verify non-vacuous); best-effort no-raise on store failure; bounded-queue drop counts without raising; cross-thread enqueue drains; event skip-set blocks double-write; cursor paging over tied timestamps has no dupes/gaps; `q` injection (tautology / DROP) returns literal/empty + table intact.

#### 7. Wrong vs Correct
Wrong:
```python
await store.save_audit_log(...)        # direct write at a choke point → drift; await blocks hot path
```
Correct:
```python
audit_logger.record("git_command", issue_id=..., payload={...}, status="ok")  # enqueue, best-effort, non-blocking
```

---

### Scenario: GitHub PR Follow-Up Sweep (review / CI / merge state)

#### 1. Scope / Trigger

- Trigger: changing GitHub PR refresh, project-level PR sweeps, or any
  conductor/scheduled-review path that follows an opened PR through review,
  status checks, and remote merge.
- Why code-spec depth: this is the autonomy bridge after "open PR". If it
  falls back to a manual Refresh PR button, issues stall outside the conductor.
  If one PR refresh failure aborts the sweep, unattended project operation drops
  work.

#### 2. Signatures

```python
# github_pr_followup.py
async def refresh_issue_github_pr(issue_id, *, store, event_bus, run_subprocess) -> GitHubPRFollowupResult
async def sweep_project_github_prs(project_id, *, store, event_bus, run_subprocess, auto_merge=False) -> GitHubPRFollowupSummary
def get_github_pr_followup_status() -> dict[str, object]
def reset_github_pr_followup_status() -> None

# api.py
POST /api/codex/issues/{issue_id}/pr/refresh -> CodexIssue
POST /api/codex/projects/{project_id}/pr/follow-up {"auto_merge": false} -> {
    project_id, counts, results: [{issue_id, status, github_pr_state, message, error}]
}
GET /api/diagnostics -> {"github_pr_followup": {...}, ...}

# project_conductor.py
ProjectConductor.handle_task(ConductorTask(task_kind="scheduled_review")) -> {
    status, answer, task_id, github_pr_followup
}
```

#### 3. Contracts

- The single-issue manual endpoint and project sweep MUST share the same
  application-layer refresh implementation.
- `gh pr view` MUST request
  `state,reviewDecision,reviews,mergeStateStatus,statusCheckRollup` so review,
  CI, and merge state are visible in one call.
- Stable result statuses are:
  - `updated`: PR open, no requested changes or failed completed checks.
  - `changes_requested`: `reviewDecision == "CHANGES_REQUESTED"`; latest
    engineer task is set to `pending` with review feedback.
  - `checks_failed`: at least one completed status check conclusion is not
    success/skipped/neutral; result message names failed checks.
  - `checks_pending`: at least one status check is not completed; auto-merge
    MUST NOT run while this is true.
  - `checks_missing`: auto-merge was requested but GitHub returned no status
    checks; missing checks are not treated as green.
  - `review_required`: auto-merge was requested but the PR is not approved.
  - `merge_blocked`: auto-merge was requested but `mergeStateStatus` is not a
    known mergeable value.
  - `merge_failed`: `gh pr merge` returned non-zero; audit/event recorded and
    the sweep continues.
  - `merged`: `state == "MERGED"`; issue becomes
    `git_merge_status="merged"` and lifecycle `status="completed"`.
  - `failed`: `gh` non-zero, bad JSON, or subprocess exception.
- Auto-merge is opt-in only (`auto_merge=True`). Default project follow-up MUST
  never merge.
- Auto-merge may call
  `gh pr merge <github_pr_url> --merge --delete-branch` only when:
  `state == "OPEN"`, `reviewDecision == "APPROVED"`,
  `mergeStateStatus in {"CLEAN", "HAS_HOOKS", "UNSTABLE"}`, at least one
  status check exists, every status check is completed, and no completed status
  check failed.
- Every result writes `project_audit` event
  `github_pr_followup_<status>` and emits an `issue_pr_followup` event.
- The project sweep skips issues with no `github_pr_url` or already merged
  `git_merge_status`.
- The project sweep MUST maintain an in-memory operational status snapshot with
  only safe fields: `configured`, `running`, `sweep_count`, `last_started_at`,
  `last_completed_at`, `last_error`, `last_summary_counts`, and
  `auto_merge_enabled`.
- `GET /api/diagnostics` MUST expose that snapshot as top-level
  `github_pr_followup`. It must not expose GitHub tokens, project names, repo
  paths, prompts, issue titles/descriptions, or full tracebacks.
- A successful project sweep records completion time, increments
  `sweep_count`, clears `last_error`, and stores summary counts. A sweep-level
  exception records safe error text, increments `sweep_count`, clears
  `running`, and re-raises so callers keep their existing supervisor behavior.
- Manual single-issue PR refresh MUST NOT update the project sweep status
  snapshot.
- A `ProjectConductor` scheduled review MUST run the project sweep with
  `auto_merge=True`, then include the sweep summary under
  `github_pr_followup` in the returned result, persisted task `result_json`,
  and project hot-thread answer event.
- Scheduled-review PR follow-up is best-effort supervisor work. A sweep
  exception is logged and reported as `{"status": "failed", "error": ...}`,
  but the conductor task still completes so the project review loop survives.

#### 4. Validation & Error Matrix

- Missing issue -> service raises `not_found`; manual endpoint maps 404.
- Issue without PR -> service raises `no_pr`; manual endpoint maps 409.
- `gh` unavailable -> endpoint maps 412 before service call.
- `gh pr view` non-zero / bad JSON / subprocess exception -> result
  `failed`, audit/event recorded, sweep continues.
- `auto_merge=False` -> never call `gh pr merge`, even if the PR is approved
  and green.
- `auto_merge=True` + pending checks -> `checks_pending`, no merge.
- `auto_merge=True` + no checks -> `checks_missing`, no merge.
- `auto_merge=True` + not approved -> `review_required`, no merge.
- `auto_merge=True` + unmergeable status -> `merge_blocked`, no merge.
- `auto_merge=True` + merge command non-zero or subprocess exception ->
  `merge_failed`, issue remains open, sweep continues.
- One failed issue in a sweep -> included as `failed`; following issues still
  refresh.
- Sweep-level exception before/after issue iteration -> status snapshot records
  `last_error` and clears `running`; exception propagates to the conductor or
  endpoint boundary.
- Scheduled-review sweep raises unexpectedly -> conductor result includes a
  failed `github_pr_followup` payload and the conductor task status remains
  `done`.

#### 5. Good/Base/Bad Cases

- Good: one project sweep refreshes ten open PRs, requeues one engineer for
  requested changes, auto-merges one approved green PR, marks one remotely
  merged issue completed, records one failed CI status, and reports two `gh`
  failures without aborting the sweep.
- Base: manual refresh of a single issue returns the updated `CodexIssue`, as
  before, but now uses the shared service.
- Bad: duplicating PR parsing in `api.py`; treating a bad JSON response as an
  unhandled exception; only polling review state and ignoring status checks.

#### 6. Tests Required

- Single refresh: remote merged PR updates `git_merge_status`, lifecycle status,
  audit, and event.
- Single refresh: changes requested writes review feedback into latest engineer
  task and emits `task_status`.
- Single refresh: failed completed status check returns `checks_failed` and
  names the failed check.
- Single refresh: bad JSON / non-zero `gh` returns `failed` with audit/event.
- Project sweep: skips no-PR / already-merged issues and isolates failures.
- Project sweep status records success counts, failure error text, running
  transitions, and the `auto_merge_enabled` flag.
- Endpoint: project follow-up returns best-effort summary instead of HTTP
  failing for one broken PR.
- Diagnostics includes top-level `github_pr_followup` and degrades when its
  `last_error` is present or `running` is `true`.
- ProjectConductor scheduled review: calls project sweep with `auto_merge=True`
  and records the summary in return payload, `result_json`, and hot memory.
- ProjectConductor scheduled review: sweep exception is reported without
  raising or failing the conductor task.
- Auto-merge: approved + all-green + mergeable -> calls `gh pr merge`, marks
  merged/completed, records `github_pr_followup_merged`.
- Auto-merge: missing checks / pending checks / review required / merge command
  failure -> no unsafe merge; stable status returned.

#### 7. Wrong vs Correct

Wrong:
```python
# API-only parsing means background/conductor paths cannot reuse the logic.
data = json.loads(await gh_pr_view(...))
issue.github_pr_state = f"{data['state']}:{data['reviewDecision']}"
```

Correct:
```python
summary = await sweep_project_github_prs(
    project_id,
    store=codex_store,
    event_bus=event_bus,
    run_subprocess=_run_subprocess,
)
```

---

### Scenario: Workflow Failed Node Auto Retry

#### 1. Scope / Trigger

- Trigger: changing `WorkflowScheduler.on_task_completed`, workflow node
  terminal status handling, task runner completion events, or automatic recovery
  for DAG-backed tasks.
- Why code-spec depth: this hook is the bridge between executor failures and
  unattended issue progress. A single transient failed task must not strand the
  workflow, but deterministic failures must still surface as failed once the
  node retry budget is exhausted.

#### 2. Signatures

```python
# workflow_scheduler.py
class WorkflowScheduler:
    async def on_task_completed(self, task: CodexTask) -> None
```

Relevant storage calls:

```python
await store.save_codex_task(retry_task)
await store.update_workflow_node(
    node.id,
    status="running",
    task_id=retry_task.id,
    retries=node.retries + 1,
    started_at=retry_task.created_at,
    completed_at=None,
)
```

Relevant events:

```json
{"type": "workflow_node_diff_guard_failed", "task_id": "...", "reason": "..."}
{"type": "workflow_node_retrying", "previous_task_id": "...", "retry_task_id": "..."}
{"type": "workflow_node_retry_failed", "retry_task_id": "...", "status": "failed"}
{"type": "task_status", "task_id": "...", "status": "pending|failed"}
```

#### 3. Contracts

- Auto-retry applies only to tasks with `workflow_node_id` whose terminal task
  status maps to workflow node `failed`.
- Before a workflow-backed Engineer task (`engineer`, `engineer_frontend`, or
  `engineer_backend`) is allowed to mark its node `done`, the scheduler MUST
  honor the Engineer diff cross-check's hard failure note. If the persisted
  Engineer document says the Engineer claimed changed files but git diff
  against the base branch showed no file changes, the scheduler converts the
  completion to `failed`, persists that task status, emits
  `workflow_node_diff_guard_failed`, and then lets the normal auto-retry logic
  handle the failed node. This keeps deterministic "report-only implementation"
  failures self-healing before Architect Review / QA.
- The diff completion guard MUST NOT fire for honest empty-diff Engineer
  reports (`changed_files=[]`, no hard cross-check note), non-Engineer roles,
  or arbitrary prose that happens to mention git diff outside the managed
  Engineer report document.
- A node is eligible only when `node.retries < node.max_retries` and the
  scheduler has both an issue row and a `task_dispatcher`.
- The retry creates a fresh `CodexTask` for the same workflow node:
  `parent_task_id` points to the failed task, `workflow_node_id` is unchanged,
  project/session/issue/role/prompt/executor/provider/model/git fields are
  inherited, and status starts as `pending`.
- The retry task `review_comment` MUST include a short `[AUTO RETRY X/Y]`
  framework note and may include truncated previous result/review context.
- The workflow node MUST be moved back to `running`, `completed_at` cleared to
  `NULL`, `task_id` set to the retry task, and `retries` incremented before the
  retry dispatcher is started.
- While a retry is launched, the Conductor completion registry MUST NOT receive
  the original failed result. It should observe the retry task's eventual
  terminal result instead.
- If retry dispatch itself raises, mark the retry task `failed`, emit
  `workflow_node_retry_failed`, restore normal failed-node handling for the
  original task, and keep the original failed task id on the final node status.
- Once retry budget is exhausted, keep existing failed-node behavior: mark the
  node failed, signal Conductor with the failed result, and do not advance the
  issue phase as if the node succeeded.

#### 4. Validation & Error Matrix

- Task has no `workflow_node_id` -> no scheduler action.
- Task status is non-terminal or maps to no node status -> no scheduler action.
- Failed node with retries remaining and dispatcher available -> create retry
  task, update node to running, emit retry events, start dispatcher, return.
- Done Engineer node with persisted diff-guard failure note and retries
  remaining -> persist the original task as failed, emit
  `workflow_node_diff_guard_failed`, create retry task, update node to running,
  emit retry events, start dispatcher, return.
- Done Engineer node with no diff-guard failure note -> mark node done normally.
- Done non-Engineer node with similar text -> mark node done normally.
- Failed node with retries exhausted -> mark node failed and continue existing
  Conductor signaling.
- Failed node with no issue row or no dispatcher -> mark node failed and
  continue existing Conductor signaling.
- Retry dispatcher raises -> retry task becomes failed, retry-failed event is
  emitted, original node becomes failed, and the exception does not escape the
  scheduler hook.
- Event emission failure -> log/debug and continue; observability must not
  break the recovery path.

#### 5. Good/Base/Bad Cases

- Good: a transient executor startup failure on `engineer` creates
  `task-retry`, moves `engineer` back to running with `retries=1`, and the
  Conductor only sees the retry's eventual result.
- Base: a deterministic QA command failure with `retries == max_retries` marks
  the QA node failed and gives Conductor the failed result.
- Bad: signaling the first failed task to Conductor and also starting a retry,
  leaving two supervisors racing over the same node.

#### 6. Tests Required

- First failed workflow task creates and dispatches a retry task, increments
  node retries, clears node completion time, and emits retry/task events.
- Retry budget exhausted preserves existing failed-node behavior and does not
  create a retry task.
- Retry dispatch failure marks the retry task failed, emits
  `workflow_node_retry_failed`, and falls back to final failed-node handling.
- Diff completion guard converts a `done` Engineer task with the hard
  diff-cross-check note into a failed original task, emits
  `workflow_node_diff_guard_failed`, and then uses the same retry behavior as a
  regular failed node.
- Guard boundaries: a `done` Engineer task without that note marks the node
  done; a `done` non-Engineer task with similar text also marks the node done.
- Existing artifact-validation signaling tests still pass, proving completion
  registry behavior stays compatible.

#### 7. Wrong vs Correct

Wrong:
```python
await store.update_workflow_node(node.id, status="failed")
reg.signal(task.id, {"status": "failed"})
await dispatch_retry_later(task)
```

Correct:
```python
if task.status == "failed" and node.retries < node.max_retries:
    retry_task = build_retry_task(task, node)
    await store.save_codex_task(retry_task)
    await store.update_workflow_node(
        node.id,
        status="running",
        task_id=retry_task.id,
        retries=node.retries + 1,
        completed_at=None,
    )
    await task_dispatcher(retry_task)
    return
```

---

### Scenario: Project Review Scheduler Tick

#### 1. Scope / Trigger

- Trigger: adding or changing backend automation that periodically runs
  project-level reviews across projects.
- The scheduler tick is the bridge between an operator-triggered scheduled
  review endpoint and unattended project operation.

#### 2. Signatures

```python
async def run_project_review_tick(
    store,
    *,
    event_bus=None,
    conductor_factory=_default_conductor_factory,
    limit=None,
) -> ProjectReviewTickSummary
```

#### 3. Contracts

- The scheduler MUST list projects through the typed store API
  (`list_projects`); it does not query SQL directly.
- Each selected project gets a `ConductorTask` with
  `task_kind="scheduled_review"` and the standard scheduled health-review
  question.
- The scheduler MUST call `ProjectConductor.handle_task(...)` instead of
  duplicating GitHub PR follow-up, auto-merge, or memory logic.
- A per-project failure is isolated and returned as a `failed` result with
  safe error text. Later projects in the same tick still run.
- The tick supports a `limit` parameter so future background loops can bound
  work per scan.

#### 4. Tests Required

- Project list with two projects -> two scheduled-review conductor tasks.
- First project raises -> first result `failed`, second project still runs.
- `limit=2` with three projects -> only first two projects are reviewed.

#### 5. Wrong vs Correct

Wrong:
```python
# Re-implements scheduled review internals and silently diverges from
# ProjectConductor / PR follow-up behavior.
await sweep_project_github_prs(project.id, auto_merge=True, ...)
```

Correct:
```python
conductor = ProjectConductor(project_id=project.id, store=store, event_bus=event_bus)
await conductor.handle_task(scheduled_review_task)
```

### Scenario: Project Review Scheduler Background Loop

#### 1. Scope / Trigger

- Trigger: wiring project review scheduling into long-running backend
  process startup, shutdown, or cadence controls.
- The background loop is the unattended supervisor around
  `run_project_review_tick`; it does not change scheduled-review semantics.

#### 2. Signatures

```python
async def run_project_review_scheduler_loop(
    store,
    *,
    event_bus=None,
    interval_s=None,
    limit=None,
    tick_fn=run_project_review_tick,
    sleep_fn=asyncio.sleep,
) -> None

def get_project_review_scheduler_status() -> dict[str, object]
```

#### 3. Contracts

- The loop MUST delegate actual work to `run_project_review_tick(...)`.
- Cadence and default work bounds MUST be read through
  `app.application.timeouts` accessors. Feature code must not call
  `os.getenv` directly.
- A tick-level unexpected exception is a loop-boundary failure: log it with
  `logger.exception(...)`, then continue to the next sleep/cycle.
- `asyncio.CancelledError` MUST propagate so FastAPI lifespan shutdown can
  stop the task promptly.
- Tests SHOULD inject `tick_fn` and `sleep_fn` so loop cadence, exception
  survival, and cancellation are deterministic.
- FastAPI lifespan starts the loop only when `async_store` is available, names
  the task `project-review-scheduler`, and cancels/awaits it during shutdown.
- The loop MUST maintain an in-memory operational status snapshot with only
  safe fields: `configured`, `interval_s`, `limit`, `running`, `tick_count`,
  `last_started_at`, `last_completed_at`, `last_error`, and
  `last_summary_counts`.
- `GET /api/diagnostics` MUST expose that snapshot as top-level
  `project_review_scheduler`. It must not expose project names, repo paths,
  prompts, task payloads, credentials, or full tracebacks.
- A successful tick records completion time, increments `tick_count`, clears
  `last_error`, and stores summary counts. A regular tick exception records
  safe error text, increments `tick_count`, and keeps the loop alive.
- Cancellation sets `running=False` and propagates `asyncio.CancelledError`; it
  must not be counted as a successful completed tick.
- Diagnostics treats a scheduler status as stale when `last_completed_at` is
  present and older than `interval_s * 2`. Error and running states take
  precedence over stale; a scheduler that has never completed a tick is not
  stale from the missing completion timestamp alone.

#### 4. Tests Required

- Loop calls the tick, sleeps the configured interval, and repeats.
- Tick raises a regular exception -> loop logs/survives and runs another tick.
- Tick or sleep raises `CancelledError` -> cancellation propagates.
- Lifespan creates and later cancels the named `project-review-scheduler`
  task.
- Scheduler status records success, failure, and cancellation transitions.
- Diagnostics includes `project_review_scheduler` with configured interval and
  limit, degrades when `last_error` is present, `running` is `true`, or the last
  completion is stale, and does not leak runtime catalog API keys.

#### 5. Wrong vs Correct

Wrong:
```python
while True:
    await run_project_review_tick(store)
    await asyncio.sleep(float(os.getenv("PROJECT_REVIEW_INTERVAL_S", "3600")))
```

Correct:
```python
await run_project_review_scheduler_loop(
    store,
    event_bus=event_bus,
    interval_s=timeouts.project_review_interval_s(),
)
```

Correct:
```python
return {
    "project_review_scheduler": get_project_review_scheduler_status(),
    ...
}
```

---

### Scenario: Project Operations Engineer Startup Script Task

#### 1. Scope / Trigger

- Trigger: adding or changing project startup-script generation, Operations
  Engineer task creation, project script persistence, or project update events.
- This is a cross-layer contract: a Projects UI action creates a backend
  `CodexTask`, the task runner executes `operations_engineer`, the role
  workflow persists `Project.setup_script` / `Project.run_command`, and the UI
  refreshes from task/project events.

#### 2. Signatures

- API: `POST /api/projects/{project_id}/script-task`
- Request model: `ScriptTaskRequest(setup_script?: str, run_command?: str,
  verify?: bool, executor?: str, provider?: str, model?: str)`
- Response model: `ScriptTaskResponse(task_id: str, status: str, title: str,
  execution_process_id?: str, reused: bool = False)`
- Created task fields: `role="operations_engineer"`,
  `task_kind="project_script_suggestion"`, `project_id`, `session_id`,
  `workspace_path`, `git_branch`, `git_base_branch`, `executor`, `provider`,
  `model`.
- Events: `task_created`, runner-owned `task_status`, role-owned
  `project_updated` and `project_script_updated`.

#### 3. Contracts

- The endpoint must create a real `CodexTask` and start it via the task
  runner. It must not perform the role work synchronously in the request path.
- Pending/running/responding `project_script_suggestion` tasks for the same
  project are idempotent: duplicate calls return the existing task with
  `reused=true`.
- The task prompt must preserve the current request's setup/run command
  context, including explicit empty strings. Do not fall back to stale project
  values merely because the request value is `""`.
- `RoleWorkflowService` builds the Operations Engineer prompt from repository
  evidence and request/project script context. New JSON prompt context must
  remain compatible with legacy `Existing setup_script/run_command` prompt
  lines for already-created tasks.
- Operations persistence parses structured model output first. If parsing fails
  or the output is empty, it may fall back to repository inference before
  failing the task.
- Project script persistence updates `Project.setup_script`,
  `Project.run_command`, and `Project.updated_at`, then emits
  `project_updated` and `project_script_updated`.
- `task_status` event ownership stays in the task runner. Role persistence
  should not emit duplicate terminal `task_status` events.
- Store methods must round-trip `CodexTask.project_id`, `provider`, and `model`
  in both async and sync stores so duplicate detection and UI task lookups stay
  project-aware.

#### 4. Validation & Error Matrix

- Unknown project id -> HTTP `404`.
- Store unavailable -> HTTP `503`, detail `"SQLite store not available"`.
- Invalid runtime catalog selection -> HTTP `400` from runtime config
  validation.
- Duplicate active operations task -> HTTP `200`, existing task response with
  `reused=true`.
- Task runner startup raises -> mark task `failed`, persist the error in
  `task.result`, emit failed `task_status`, and return HTTP `500`.
- Operations output unparsable and repository inference unavailable -> task
  persistence raises, runner marks the task failed.
- Project update event emission fails -> script persistence still succeeds;
  events are best-effort observability.

#### 5. Good/Base/Bad Cases

- Good: clicking "Call operations engineer" creates one durable operations
  task, starts a process, and later updates the project scripts plus emits
  project update events.
- Good: a second click while the first task is running returns the first task
  id and does not start a second process.
- Base: legacy synchronous `/script-suggestion` remains available for
  compatibility, but the one-click role path uses `/script-task`.
- Bad: a direct LLM suggestion endpoint updates scripts without a durable
  `operations_engineer` task.
- Bad: storing a task without `project_id`, causing duplicate detection and
  `/projects` polling to lose the project association.
- Bad: role persistence emits its own terminal `task_status` while the runner
  also emits one, creating duplicate terminal notifications.

#### 6. Tests Required

- Endpoint test: creating a script task persists the expected role,
  `task_kind`, project id, workspace path, runtime config, and emits
  `task_created`.
- Endpoint test: duplicate active task returns `reused=true` and does not start
  another task runner process.
- Role workflow test: JSON request context preserves explicit empty strings and
  falls back to legacy prompt lines for older tasks.
- Role workflow test: unparsable/empty result attempts repository inference
  before failing.
- Store parity test: async and sync stores save/list/load script tasks with
  `project_id`, `provider`, and `model`.
- Event test: Operations persistence emits project update/script update events
  and relies on the runner for terminal `task_status`.

#### 7. Wrong vs Correct

Wrong:

```python
# Direct suggestion path: no durable task, no project-aware process state.
suggestion = await suggest_project_scripts(project=project, runner=llm)
project.setup_script = suggestion.setup_script
await store.save_project(project)
```

Correct:

```python
task = CodexTask(
    project_id=project.id,
    session_id=project.id,
    role="operations_engineer",
    task_kind="project_script_suggestion",
    workspace_path=project.repo_path,
    status="pending",
)
await store.save_codex_task(task)
await task_runner.start_task_run(task)
```


---

### Scenario: Conductor Task Status and Dispatch Terminal Contracts

#### 1. Scope / Trigger

- Trigger: changing Conductor dispatch, `CodexTaskRunner`, process runtime termination, specialist orchestration, budget gating, or any code that emits `task_status`.
- This is a backend-to-frontend and scheduler contract: a task terminal event must carry enough correlation fields for UI, retry logic, and waiting registries to agree on what changed.

#### 2. Signatures

- Event helper: `build_task_status_event(task, status=None, execution_process_id=None, **extra) -> dict`.
- Required event fields: `type`, `task_id`, `project_id`, `issue_id`, `workspace_id`, `session_id`, `role`, `task_kind`, `status`, `execution_process_id`.
- Conductor success aliases: `done`, `success`, `completed`, `passed`, `ok` normalize to `done`.
- Non-success statuses: `failed`, `blocked`, `cancelled`, `canceled`, `error`, `needs_user`, `max_wall`, `max_turns`, `protocol_error`.
- Budget gate result: `{"status": "budget_exceeded", "error": str, "budget": {...}}`.

#### 3. Contracts

- All `task_status` emitters must use `build_task_status_event` unless they can prove they emit the exact same field set.
- Missing optional values are explicit `None`, not omitted, so consumers can rely on a stable schema.
- Runner-start failure, result-persist failure, process kill, retry, specialist wait, and timeout paths must emit the same correlation fields as the happy path.
- `dispatch_role(register_completion=True)` must signal `TaskCompletionRegistry` if runner startup fails; Conductor must not wait until idle/hard timeout for a task that never started.
- Subagent timeout must best-effort terminate the real task, mark task and workflow node failed, and emit terminal events.
- Specialist child startup failure must mark the child failed and the parent `ready_to_resume`; the parent must not remain `waiting_for_specialist`.
- Specialist request failure from an Engineer/QA artifact is a task failure, not a warning-only side effect.
- Over-budget issues must not dispatch new subagents or create batch worktrees. The Conductor receives `budget_exceeded` and should finalize, request user input, or choose a no-cost recovery path.
- `dispatch_batch` must serialize the short pre-run gate for each agent:
  budget check, per-role redispatch check, worktree preparation, and task/node
  creation. The long subagent wait may still run concurrently, but agents must
  not simultaneously pass the same stale budget snapshot and both create
  worktrees/tasks.
- Conductor completion requires a `finalize_task` tool call. Plain text without tool use is a protocol error after correction attempts.

#### 4. Validation & Error Matrix

- `task_status` missing `role` / `task_kind` -> invalid emitter; replace with `build_task_status_event`.
- Runner startup raises after completion registration -> save task failed, mark node failed, emit events, signal registry failed result.
- `wait_for_active` times out -> terminate task when possible, mark task/node failed, emit terminal state, return structured timeout.
- Specialist child runner raises -> child failed + parent `ready_to_resume` + both task status events.
- Unknown `finalize_task.status` -> normalize to `failed`, never success.
- LLM response has no tool use -> append correction message; if still no tool use by the final turn, return `protocol_error`.
- Budget status is over ceiling -> return `budget_exceeded`; do not create task, workflow node, execution process, or worktree.
- Batch budget changes after the first agent starts -> later agents re-check
  under the dispatch gate and stop before worktree preparation when over
  budget.
- Budget status cannot be computed -> degrade open, because store errors must not hide unrelated dispatch behavior.

#### 5. Good/Base/Bad Cases

- Good: Operations Engineer `/script-task` startup failure emits `task_status` with `project_id`, `workspace_id`, `role="operations_engineer"`, and `task_kind="project_script_suggestion"`.
- Good: a killed QA task emits the same correlation fields as a normally failed QA task.
- Good: over-budget `dispatch_batch` returns `budget_exceeded` before `prepare_agent_worktree`.
- Good: batch cap is 2, first agent starts, second per-agent budget gate now
  sees over-budget and returns `budget_exceeded` with no second worktree.
- Base: unlimited budget (`budget_usd <= 0`) does not block dispatch.
- Bad: emitting `{"type": "task_status", "task_id": id, "status": "failed"}` directly from a side path.
- Bad: swallowing specialist request failure and allowing the parent Engineer task to look successful.
- Bad: running all per-agent budget checks concurrently, letting multiple
  agents pass before any dispatch-side effect can be observed.
- Bad: treating `blocked`, `needs_user`, `maybe`, or free-form text as a completed Conductor issue.

#### 6. Tests Required

- Unit test: `build_task_status_event` includes all shared correlation fields and preserves extra fields.
- Loop test: a plain-text Conductor response without tool use becomes `protocol_error` unless corrected with `finalize_task`.
- Loop test: unknown `finalize_task.status` fails closed.
- Tool test: over-budget `dispatch_batch` returns `budget_exceeded` and does not create worktrees.
- Tool test: with batch concurrency >1 and a budget that changes after the
  first per-agent gate, only the first agent prepares a worktree; later agents
  return `budget_exceeded`.
- Dispatcher test: runner-start failure signals `TaskCompletionRegistry` and marks task/node failed.
- Runtime test: `terminate_task` and workspace termination emit complete task-status payloads.
- Specialist test: child startup failure marks parent and child failed.

#### 7. Wrong vs Correct

Wrong:

```python
await event_bus.append({
    "type": "task_status",
    "task_id": task.id,
    "status": "failed",
})
```

Correct:

```python
await event_bus.append(
    build_task_status_event(
        task,
        "failed",
        result=task.result,
        execution_process_id=task.last_execution_process_id,
    )
)
```

### Scenario: Non-Security Deterministic Hashes

#### 1. Scope / Trigger

- Trigger: adding or changing a hash used for deterministic IDs, cache keys,
  dedupe keys, prompt/content fingerprints, or audit references.
- Hashes that are not protecting secrets still look security-sensitive to
  scanners; the code must make the non-security intent executable.

#### 2. Signatures

- Python hash call: `hashlib.sha1(data, usedforsecurity=False)`.
- Targeted static scan:
  `pipx run bandit backend/app/application/team_notes_service.py -f json`
  (substitute the touched file).

#### 3. Contracts

- If a weak digest such as SHA-1 is used only for deterministic identity, pass
  `usedforsecurity=False` and add a nearby comment or docstring phrase such as
  "non-security digest".
- Do not use weak digests for authentication, signatures, secret comparison,
  permission decisions, or integrity checks across trust boundaries.
- Preserve existing deterministic ID formats when migrating a legacy key
  unless a migration/backfill plan exists.

#### 4. Validation & Error Matrix

- Weak digest without `usedforsecurity=False` -> Bandit `B324` high finding.
- Weak digest used for a security decision -> replace with an appropriate
  modern primitive; do not suppress the scanner.
- Changing the output prefix/length of an existing persisted ID -> requires a
  compatibility test or migration plan.

#### 5. Good/Base/Bad Cases

- Good: `hashlib.sha1(heading.encode("utf-8"), usedforsecurity=False)` for a
  legacy team-note block ID whose prefix and length stay unchanged.
- Base: `hashlib.sha256(...)` for a non-secret content fingerprint when output
  compatibility is not constrained.
- Bad: `hashlib.sha1(token.encode()).hexdigest()` for auth, signatures, or any
  user trust decision.

#### 6. Tests Required

- Run the focused unit tests for the owner of the ID/fingerprint behavior.
- Run a targeted Bandit scan for the touched file.
- If the digest output is persisted or user-visible, test that the previous ID
  shape is preserved.

#### 7. Wrong vs Correct

Wrong:

```python
block_id = "h:" + hashlib.sha1(heading.encode("utf-8")).hexdigest()[:16]
```

Correct:

```python
block_id = (
    "h:" + hashlib.sha1(heading.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
)
```

### Scenario: Dynamic SQL Identifier Boundaries

#### 1. Scope / Trigger

- Trigger: building SQL that contains dynamic table names, column names,
  `ORDER BY` directions, optional `WHERE` fragments, or `SET` clauses.
- SQLite parameter binding only protects values. Identifiers and SQL keywords
  must be constrained separately.

#### 2. Signatures

- Identifier validator:
  `SQLITE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")`.
- Identifier quote helper: `_quote_sqlite_identifier(name: object) -> str`.
- Static scan: `pipx run bandit backend/app/adapters/sqlite_store.py -f json`
  or the touched store file.

#### 3. Contracts

- User-provided values always use `?` parameters.
- Dynamic identifiers must come from a hard-coded allowlist or pass a strict
  identifier validator before being quoted.
- Dynamic SQL fragments such as `ASC`/`DESC`, `WHERE`, or `SET` clauses must be
  built from internal enums/booleans/known field lists, not request strings.
- A `# nosec B608` suppression is allowed only on the exact execute line after
  the dynamic identifier/fragment has been validated nearby.

#### 4. Validation & Error Matrix

- Raw user value interpolated into SQL -> reject; use a bound parameter.
- Table/column name from sqlite metadata or config -> validate with the helper
  before interpolation.
- `ORDER BY {request.query}` -> reject; map request values to hard-coded
  literals first.
- `# nosec B608` without a nearby validation comment/helper -> review failure.

#### 5. Good/Base/Bad Cases

- Good: reset code validates a sqlite table name with `_quote_sqlite_identifier`
  before `DELETE FROM "<table>"`.
- Base: optional filters append fixed strings such as `"project_id = ?"` while
  user values remain in the parameter tuple.
- Bad: `f"DELETE FROM {name}"` where `name` has not been validated and quoted.

#### 6. Tests Required

- Run the store tests that exercise the touched query path.
- Run Ruff, mypy for the touched store file, and a targeted Bandit scan.
- Add a unit test for new public query-shaping helpers or any request-driven
  sort/filter mapping.

#### 7. Wrong vs Correct

Wrong:

```python
conn.execute(f"DELETE FROM {name}")
```

Correct:

```python
quoted_name = _quote_sqlite_identifier(name)
# Identifier is validated by _quote_sqlite_identifier.
conn.execute(f"DELETE FROM {quoted_name}")  # nosec B608
```

---

## Testing Requirements

- **All new code is covered by tests.** Service logic,
  endpoint logic, and pure helper functions all get tests.
  The `pytest` mark `slow` opts into long integration tests;
  the default lane skips them, so a focused run
  (`pytest tests/test_foo.py -v`) is the right shape.
- **Pure functions are unit-tested in isolation.** A function
  in `application/` that takes a `CodexIssue` and returns
  an `IssueBudgetStatus` should be tested with a tiny
  stub store — no need for the real async store in most
  cases.
- **Endpoints are tested with the real async store where
  practical**, and with a focused store stub for the
  endpoint's own logic. The pattern is in
  `test_pipeline_stages.py` and `test_issue_budget_endpoint.py`.
- **Migration tests cover legacy rows.** A new column needs a
  test that exercises a row written before the migration,
  not just a fresh row. See
  `test_issue_budget.py::test_sync_store_migrates_legacy_issue_without_budget_column`
  for the canonical pattern.
- **State-machine tests for the conductor.** The conductor's
  legal/illegal phase transitions are enforced by
  `LEGAL_TRANSITIONS`; a change to the table needs a test
  in `test_conductor_state_machine.py`.
- **Cost / budget behavior is tested with the real
  `timeouts.X()` accessors.** A test that monkey-patches
  `os.getenv` skips the boot-time validation, which is the
  whole point of the accessor pattern.
- **No snapshot tests.** They drift; the per-feature
  derivation tests and the unit tests of the budget
  computation do the work snapshots would.

---

## Code Review Checklist

A reviewer should be able to answer YES to **all** of the
following before approving:

- [ ] The change is **scope-limited**: no incidental refactors,
      no drive-by reformatting, no opportunistic dependency
      bump.
- [ ] Every new service / endpoint is **typed end-to-end**
      (no `any`, no bare `dict` for shape-bearing data).
- [ ] Every new env-driven knob goes through
      `application/timeouts.py`, not a `os.getenv` call from
      feature code.
- [ ] Every new endpoint has a **focused test** (ceiling /
      unlimited / missing branches where applicable).
- [ ] Every new state-derivation rule has a **unit test**
      that covers below / at / above the threshold.
- [ ] Every new long-running coroutine **catches at the
      boundary** and persists a `failed` row with the
      traceback in `result_json` — the loop survives.
- [ ] Every new background poll has an **active-state guard**
      and stops once the issue is done / idle. No polling
      after the user's gone.
- [ ] Every new migration is **idempotent** and bumps
      `schema_version` in the same block.
- [ ] The diff is **readable in one pass** (no nested
      ternaries, no 9-prop god functions, no copy-paste
      boilerplate that should be a helper).
- [ ] `pytest -v` and any pointed test commands are green
      locally, with the actual output attached to the PR
      or task handoff.
- [ ] The change does not introduce a new external dependency
      without a sentence explaining why.

### Scenario: Conductor Orchestration Safety Gates

#### 1. Scope / Trigger

- Trigger: changing Conductor loop termination, `finalize_task`, `dispatch_subagent`, `dispatch_batch`, help/specialist parent-child flows, retry scheduling, relaunch recovery, or `task_status` event payloads.
- These paths are a cross-layer state-machine contract. A task can be persisted correctly and still appear stuck if the event payload is incomplete, or appear complete when the graph still has unresolved nodes.

#### 2. Signatures

- Tool: `finalize_task({ status, answer?, summary? }) -> { status, answer, summary }`.
- Tool: `request_user_clarification({ question }) -> { status: "waiting_for_user", terminal_status: "needs_user", question }`.
- Helper: `build_task_status_event(task, status=None, execution_process_id=None, **extra) -> dict`.
- Runtime config: `timeouts.conductor_max_dispatches_per_role() -> int` reads `CONDUCTOR_MAX_DISPATCHES_PER_ROLE`.
- Relaunch entry: `run_issue_conductor_loop(..., recovery_context="")` injects persisted graph and turn context into the prompt.
- Retry signal: `TaskCompletionRegistry.signal(retry_task.id, failed_payload)` must fire when an auto-retry runner fails to start after `transfer(old_task, retry_task)`.

#### 3. Contracts

- Successful `finalize_task(status="done")` is not model-owned. The backend must reject success when the persisted workflow graph is empty, has no completed work, or contains unresolved `pending`, `running`, `waiting_*`, `awaiting_*`, `failed`, `rework`, `conflict`, `artifact_invalid`, `retries_exhausted`, or timeout nodes. `skipped` is allowed as a non-blocking node status, but a graph with only skipped nodes still has no completed work.
- `finalize_task` must not be accepted in the same Conductor turn as another tool. If a turn dispatches work and finalizes at the same time, the finalize result is a tool error and the loop feeds all tool results back to the model; non-finalize tools in that turn still execute through the normal concurrent multi-tool path.
- `skip_llm` and missing Conductor LLM configuration must never synthesize `done`. They finalize as `blocked` or another non-success terminal status.
- `request_user_clarification` is terminal for the current loop turn. It returns `needs_user` and must not be followed by speculative dispatch.
- Every `task_status` event emitted to the event bus or websocket must use `build_task_status_event` or an exactly equivalent complete payload including `task_id`, `project_id`, `issue_id`, `workspace_id`, `session_id`, `role`, `task_kind`, `status`, and `execution_process_id`.
- Websocket `task_status` events must be independently published. They must not depend on execution-process JsonPatch generation or `buffer_pending` flushes.
- Raw log/message websocket endpoints must share the same execution-process
  terminal status set, including `done`, `completed`, `failed`, `killed`,
  `cancelled`, and `canceled`, so reconnecting to a cancelled process returns
  the initial history plus `{finished: true}` instead of hanging.
- Role aliases must be canonicalized before concurrency slots, redispatch budgets, batch requested-role counts, and per-agent worktree keys are computed.
- `dispatch_batch` must run its per-agent budget gate after acquiring a
  per-agent semaphore and inside a short serialized dispatch gate that also
  covers redispatch-budget check, worktree preparation, and task/node creation.
  The batch-level preflight is not enough, and concurrent per-agent gates must
  not all pass against the same stale budget snapshot.
- Help and specialist parent-child flows must validate non-empty title/prompt inputs before mutating parent state, and must leave parent, child, and request records in explicit terminal or resumable states when child launch or parent resume fails.
- Relaunch recovery must reuse the existing workflow graph when present and inject recovery context that names previous phase/detail, node statuses, task ids, retry counts, and recent turns.
- Relaunch recovery's production contract is scheduling/registering a new
  conductor session through `ConductorSessionRegistry.try_start`, not proving the
  runner has executed its first line. Tests that need to observe runner entry
  must use an explicit `asyncio.Event` or equivalent signal from the fake runner,
  not rely on `await asyncio.sleep(0)`.

#### 4. Validation & Error Matrix

- Graph has unresolved nodes + `finalize_task(done)` -> return `status="failed"` with a rejection reason. A `skipped` node may be non-blocking, but it does not count as completed work evidence.
- Same turn contains `dispatch_subagent` and `finalize_task` -> mark finalize tool result as `protocol_error`; do not end the loop from that finalize.
- Same turn contains multiple non-finalize tools plus `finalize_task` -> mark only
  `finalize_task` as `protocol_error`; execute the non-finalize tools
  concurrently and preserve original tool-result order.
- Clarification tool succeeds -> return loop status `needs_user` with the question text.
- `skip_llm` policy action -> return `blocked`, not `done`.
- Websocket cannot load an execution process view -> still publish complete `task_status` independently.
- Raw log/message websocket opens for a cancelled process -> send initial
  history, send `{finished: true}`, close cleanly.
- Batch per-agent budget gate sees over-budget after an earlier agent started
  -> return `budget_exceeded` for that agent and do not prepare its worktree.
- Auto-retry runner start raises after registry transfer -> save retry task failed, emit retry failure events, and signal the registry using the retry task id.
- Help title/prompt or specialist prompt is empty -> reject before saving child tasks or mutating parent state.
- Help child start raises -> child `failed`, help request `failed`, parent `ready_to_resume`, and complete task status events emitted.
- Help parent auto-resume raises -> help request `resume_failed`, parent `ready_to_resume`, assistant continuation message persisted.
- Specialist child is not `done` or parent is not `waiting_for_specialist` -> raise `SpecialistOrchestratorError` and do not mutate parent review comment or status.
- Issue is `awaiting_review` and graph seals failed -> issue status becomes `failed`; awaiting states are protected only on successful seals.
- Recovery relaunch scheduled -> `_try_relaunch` may return once the new session
  task is registered; immediate runner-side effects require an explicit runner
  entry signal.

#### 5. Good/Base/Bad Cases

- Good: a script-generation task emits `task_status` with task and project ids, and the project page clears loading by matching the tracked task id.
- Good: recovery relaunch prompt tells the model that `engineer` is already done and `qa` failed, so the next action is QA recovery rather than repeating engineer.
- Good: recovery relaunch test awaits a fake runner `entered` event before
  asserting captured `recovery_context`.
- Good: a batch with `eng` and `dev` counts both as `engineer` for redispatch caps.
- Good: batch fan-out keeps long subagent waits concurrent but serializes the
  short gate/create section so budget and dispatch-count checks observe earlier
  starts.
- Good: a same-turn `dispatch_subagent + dispatch_reviewer + finalize_task`
  runs the two dispatch tools concurrently, returns a protocol error only for
  finalize, and waits for a later standalone finalize.
- Base: project-memory recording fails after a successful seal; the issue remains completed and only a warning is logged.
- Base: a route without an execution-process provider polls the tracked task id and handles duplicate WS/poll terminal notifications once.
- Bad: `finalize_task(done)` seals an issue while QA is pending or a merge conflict is unresolved.
- Bad: `task_status` is manually emitted with only `task_id` and `status`.
- Bad: help or specialist child launch failure leaves the parent stuck in `waiting_for_help` or `waiting_for_specialist`.

#### 6. Tests Required

- Loop test: mixed dispatch plus finalize in one turn does not finish until a later standalone finalize.
- Loop test: mixed finalize with multiple non-finalize tools keeps the
  non-finalize tools concurrent and preserves result order.
- Tool test: `finalize_task(done)` rejects unresolved graph nodes.
- Loop test: `request_user_clarification` returns `needs_user` immediately.
- Issue-loop test: `skip_llm` returns `blocked` and does not call the LLM.
- Event test: representative terminal task paths emit full `task_status` fields.
- Websocket test/source check: raw log and message streams use one shared
  terminal status set that includes `cancelled` and `canceled`.
- Websocket/source test: terminal script-task handling matches tracked `task_id` before falling back to `project_id`.
- Help tests: empty title/prompt rejects before mutation; child start failure and parent auto-resume failure produce explicit states.
- Specialist tests: empty prompt rejects before mutation; failed child and non-waiting parent are rejected without parent mutation.
- Scheduler test: auto-retry dispatch failure signals `TaskCompletionRegistry`.
- Recovery test: relaunch context includes stalled task id, previous phase/detail, node statuses, task ids, and recent turns.
- Recovery test: relaunch runner entry is observed through an explicit event,
  not through one event-loop yield.
- Budget test: batch per-agent budget gate rejects before worktree preparation when budget changes after preflight.
- Budget test: with `MAX_PARALLEL_DISPATCH_PER_BATCH > 1`, a second agent that
  becomes over-budget after the first agent starts does not prepare a worktree.
- Worktree lineage test: a `dispatch_batch` result keeps the user-facing
  `agent_key`, but failed/no-op/merged cleanup uses `worktree_key` when the
  physical swarm worktree key includes the batch suffix.
- Alias test: `eng` and `dev` share the canonical `engineer` dispatch budget.

#### 7. Wrong vs Correct

Wrong:

```python
await event_bus.append({"type": "task_status", "task_id": task.id, "status": task.status})
```

Correct:

```python
await event_bus.append(
    build_task_status_event(
        task,
        task.status,
        result=task.result,
        execution_process_id=task.last_execution_process_id,
    )
)
```

Wrong:

```python
if policy_decision.action == "skip_llm":
    return {"name": "finalize_task", "input": {"status": "done"}}
```

Correct:

```python
if policy_decision.action == "skip_llm":
    return {"name": "finalize_task", "input": {"status": "blocked", "answer": reason}}
```

Wrong:

```python
stream_manager.buffer_pending(task.session_id, {"type": "task_status", "task_id": task.id})
await stream_manager.publish_execution_process(task.session_id, task_id=task.id)
```

Correct:

```python
await stream_manager.publish_event(task.session_id, build_task_status_event(task, task.status))
await stream_manager.publish_execution_process(task.session_id, task_id=task.id)
```

---

## Scenario: Conductor Tool-Turn Side-Effect Safety

### 1. Scope / Trigger

- Trigger: changing `run_conductor_loop`, `finalize_task`, `request_user_clarification`, or any Conductor tool that can dispatch tasks, resume work, mutate workflow graph state, or terminate an issue.
- The Conductor may receive multiple tool calls in one model turn, but some tools are terminal or pausing boundaries and must not be mixed with side-effecting work.

### 2. Signatures

- Loop helper: `run_conductor_loop(..., tools: Mapping[str, ToolCallable], tool_definitions: list[JsonObject]) -> ConductorLoopResult`.
- Tool executor: `_execute_tool_uses(tool_uses: list[JsonObject], tools: Mapping[str, ToolCallable]) -> list[JsonObject]`.
- Protocol-error helper: `_tool_protocol_error(tool_use: JsonObject, error: str) -> JsonObject`.
- Terminal tool: `finalize_task({ status, answer })`.
- Pause tool: `request_user_clarification({ question })`.

### 3. Contracts

- `finalize_task` must be the only tool in its turn when it is used. If it appears with other tools, the loop may execute the non-finalize tools, but `finalize_task` itself must be converted to a protocol error before execution.
- `request_user_clarification` must be the only tool in its turn. If it appears with any other tool, every tool in that turn must be converted to protocol errors before execution, because asking the user is a pause point and dispatching work before the answer is a side effect.
- `finalize_task(status="done")` must fail closed when `issue_id` exists but the workflow graph is missing or cannot be loaded.
- `finalize_task(status="done")` must require at least one completed non-skipped work node and no unresolved/failed/conflicted/timeout nodes.
- `skipped` nodes may be non-blocking, but they are not evidence that work completed.

### 4. Validation & Error Matrix

- `finalize_task + dispatch_subagent` in one turn -> dispatch may run; finalize result is `protocol_error`; loop continues.
- `request_user_clarification + dispatch_subagent` in one turn -> both results are `protocol_error`; no dispatch side effect occurs; loop continues.
- `finalize_task(done)` with missing graph -> result status `failed`; answer explains graph is missing.
- `finalize_task(done)` with graph load exception -> result status `failed`; answer explains graph could not be loaded.
- `finalize_task(done)` with only `skipped` nodes -> result status `failed`; answer explains no completed work node exists.
- `request_user_clarification` alone -> loop terminates with `needs_user` and the user-facing question.

### 5. Good/Base/Bad Cases

- Good: model asks one clarification question, the loop returns `needs_user`, and no subagent is started until the next user answer.
- Good: model dispatches `qa`, receives the result in a later turn, then calls `finalize_task` by itself.
- Base: model emits plain text without a tool; loop prompts it to call a tool and eventually fails as `protocol_error` if it never does.
- Bad: graph storage is unavailable and `finalize_task(done)` succeeds because the backend treats graph verification as best-effort.
- Bad: model asks the user a question and dispatches `engineer` in the same turn, causing code changes before the requested user decision exists.

### 6. Tests Required

- Loop test: mixed `finalize_task + dispatch_subagent` does not execute finalize and does not terminate the loop in that turn.
- Loop test: mixed `request_user_clarification + dispatch_subagent` executes neither tool and records protocol errors.
- Tool test: `finalize_task(done)` rejects a missing graph.
- Tool test: `finalize_task(done)` rejects graph load exceptions.
- Tool test: `finalize_task(done)` rejects graphs with unresolved nodes.
- Tool test: `finalize_task(done)` rejects graphs where every node is `skipped`.

### 7. Wrong vs Correct

Wrong:

```python
events = await _execute_tool_uses(tool_uses, tools)
# Later mutate finalize/clarification results after side effects already ran.
```

Correct:

```python
if clarification_mixed_with_work:
    events = [_tool_protocol_error(tool_use, error) for tool_use in tool_uses]
elif finalize_mixed_with_work:
    events = []
    for tool_use in tool_uses:
        if tool_use["name"] == "finalize_task":
            events.append(_tool_protocol_error(tool_use, error))
        else:
            events.append(await _execute_tool_use(tool_use, tools))
else:
    events = await _execute_tool_uses(tool_uses, tools)
```

---

## Scenario: Help and Specialist Child Completion Safety

### 1. Scope / Trigger

- Trigger: changing `HelpOrchestrator`, `SpecialistOrchestrator`, workflow scheduler child-completion handling, or parent/child task status transitions.
- Help and specialist children are recovery/continuation flows. A child startup or completion problem must not silently mutate the wrong parent or permanently strand a parent in a waiting state.

### 2. Signatures

- Help create: `HelpOrchestrator.request_help(parent_task_id, target_executor, title, prompt, context_summary=None)`.
- Help complete: `HelpOrchestrator.complete_help_request(help_request_id, *, child_status, child_result)`.
- Specialist create: `SpecialistOrchestrator.request_specialist(parent_task, specialist_role_key, specialist_prompt, why="")`.
- Specialist complete: `SpecialistOrchestrator.complete_specialist_request(specialist_child_task_id, specialist_result_summary)`.
- Parent recoverable status: `ready_to_resume`.
- Specialist wait lock: while `parent.status == "waiting_for_specialist"`,
  `parent.blocked_by_help_id` stores `specialist:<child_task_id>`. The field
  name is legacy, but the status namespace distinguishes it from
  `waiting_for_help` help request ids.

### 3. Contracts

- Help completion must reload the persisted child task and validate `task_kind == "help_child"`, `parent_task_id`, and real terminal status before mutating the parent.
- Help completion must reject already-terminal help requests such as `completed`, `failed`, `consumed`, or `resume_failed`.
- Help completion must reject a parent that is not currently `waiting_for_help` for that exact `help_request.id`.
- Help auto-resume must set the parent to a runnable state before calling the task runner; if resume fails, the parent falls back to `ready_to_resume`.
- Specialist child startup failure must mark the child `failed` and the parent `ready_to_resume`, not `failed`, unless product policy explicitly decides that specialist startup failure is terminal for the parent.
- Specialist completion must only inject results from a persisted child with `task_kind == "specialist_child"`, `status == "done"`, and a parent currently `waiting_for_specialist`.
- Specialist completion must also verify the parent is waiting for the exact
  child id via `blocked_by_help_id == f"specialist:{child.id}"`. A stale
  completed specialist child from an older request must not resume or mutate a
  parent now waiting on a newer specialist child.
- Specialist duplicate protection must block only the current specialist wait
  lock or active specialist children (`pending`, `running`, `responding`).
  Historical terminal specialist children (`done`, `failed`, `cancelled`) are
  not unresolved and must not prevent a resumed parent from making a later,
  legitimate specialist request.
- Specialist completion must prefer the persisted `child.result` over the
  caller-provided `specialist_result_summary`; scheduler callbacks can be
  stale, but the stored child is authoritative.
- Specialist startup failure and specialist terminal failure handling must clear
  the specialist wait lock when moving the parent to `ready_to_resume`.

### 4. Validation & Error Matrix

- Missing help request -> `KeyError(help_request_id)`.
- Help request already terminal -> `ValueError` and no parent mutation.
- Help child not terminal -> `ValueError` and no parent mutation.
- Help child belongs to a different parent -> `ValueError` and no parent mutation.
- Help auto-resume runner raises -> help request `resume_failed`; parent `ready_to_resume`; assistant continuation message persisted.
- Specialist child startup runner raises -> child `failed`; parent `ready_to_resume`; emit `specialist_failed`; raise `SpecialistOrchestratorError`.
- Specialist failed child completion for the currently locked child -> emit
  child task status, move parent to `ready_to_resume`, clear the wait lock,
  emit `specialist_failed`, raise `SpecialistOrchestratorError`, and leave
  parent review comment unchanged.
- Specialist completion for a child that belongs to the parent but does not
  match the current `specialist:<child_task_id>` lock -> raise
  `SpecialistOrchestratorError` and do not mutate parent status, lock, or review
  comment.
- Parent has only terminal historical specialist children and is otherwise
  runnable -> a new `request_specialist()` call may create a new child and set a
  new `specialist:<child_task_id>` wait lock.

### 5. Good/Base/Bad Cases

- Good: help child finishes `done`, parent is waiting for that help id, auto-resume starts from the parent's own resume session.
- Good: specialist runner cannot start, parent shows a recoverable state instead of being marked failed.
- Good: parent waits on `specialist:child-b`; stale `child-a` finishes later and
  is rejected without resuming the parent.
- Good: parent resumes after `child-a` completed, runs again, and then creates
  `child-b` for a fresh specialist pass.
- Base: completed specialist child injects a concise continuation into `parent.review_comment` and resets parent to `pending`.
- Bad: trusting a scheduler-provided `child_status="done"` while the stored child is still `running`.
- Bad: completing the same help request twice and starting the parent twice.
- Bad: specialist start failure marks the parent `failed`, making an infrastructure problem look like task failure.

### 6. Tests Required

- Help test: non-terminal stored child is rejected even if caller passes `child_status="done"`.
- Help test: already-terminal help request cannot be completed again.
- Help test: parent not waiting for that help id is rejected without mutation.
- Help test: auto-resume failure falls back to `ready_to_resume` and records `resume_error`.
- Specialist test: child startup failure marks parent `ready_to_resume`, child `failed`, and emits `specialist_failed`.
- Specialist test: failed child completion does not mutate parent review comment.
- Specialist test: parent not waiting for specialist rejects completion without mutation.
- Specialist test: stale child whose id does not match the parent's current
  specialist wait lock is rejected without mutation.
- Specialist test: done child completion injects persisted `child.result`, not a
  stale caller-provided summary.
- Specialist test: terminal historical children do not block a new specialist
  request after the parent is runnable again.

### 7. Wrong vs Correct

Wrong:

```python
help_request.status = "completed" if child_status == "done" else "failed"
parent.blocked_by_help_id = None
await store.save_codex_task(parent)
```

Correct:

```python
child = await store.load_codex_task(help_request.child_task_id)
if child.task_kind != "help_child" or child.parent_task_id != parent.id:
    raise ValueError("invalid help child")
if child.status not in TERMINAL_CHILD_STATUSES:
    raise ValueError("Help child task is not terminal")
```

---

## Scenario: Workspace WebSocket Task-Status Event Delivery

### 1. Scope / Trigger

- Trigger: changing `ExecutionProcessWorkspaceStreamManager`, `EventBus._broadcast_to_ws`, process runtime task completion/failure paths, or frontend consumers of workspace `task_status` events.
- `task_status` is a semantic event contract, not merely an execution-process JsonPatch side effect. It must reach existing subscribers immediately and reconnecting subscribers through the initial snapshot path.

### 2. Signatures

- Event builder: `build_task_status_event(task, status, ..., execution_process_id=None) -> dict`.
- Workspace manager methods:
  - `publish_event(workspace_id, event)`.
  - `buffer_pending(workspace_id, event)`.
  - `consume_pending_events(workspace_id) -> list[dict]`.
  - `get_state(workspace_id) -> dict`.
- Initial snapshot helper: `_send_workspace_initial_snapshot(websocket, state, pending_events=None) -> bool`.

### 3. Contracts

- Existing workspace subscribers receive `task_status` via an immediate `{"Events": [...]}` frame.
- If no subscriber is connected, `task_status` is buffered as pending for that workspace.
- A reconnecting workspace websocket must receive pending events in the initial snapshot frame along with the JsonPatch state, then the pending buffer is consumed exactly once.
- Process runtime terminal paths must choose one fanout source. If an `EventBus` is present, append the event to it and let `EventBus._broadcast_to_ws` publish to workspace streams. Only direct-publish to `stream_manager` when there is no `EventBus`.
- Frontend consumers must still de-duplicate terminal handling by `task_id`, because websocket and polling can race.

### 4. Validation & Error Matrix

- No subscribers when event occurs -> event stored under `_pending_events[workspace_id]`.
- Subscriber connects after pending event -> first snapshot frame includes both `JsonPatch` and `Events`, then `Ready` follows.
- `EventBus` present on process completion -> exactly one event path feeds workspace WS.
- `EventBus` absent on process completion -> direct `stream_manager.publish_event` keeps UI feedback working.
- Pending event has no matching execution-process row -> still sent; event delivery does not depend on JsonPatch process state.

### 5. Good/Base/Bad Cases

- Good: project script task completes while `/projects` is disconnected; on reconnect the pending `task_status` is delivered in the initial frame and the button clears.
- Base: active workbench subscriber receives `task_status` immediately and then a process JsonPatch refresh.
- Bad: buffering a pure event and waiting for a future `publish_patch()` that may never happen.
- Bad: appending to `EventBus` and also direct-publishing the same terminal event to `stream_manager`, causing duplicate toasts in consumers without task-id dedupe.

### 6. Tests Required

- Workspace stream test: initial snapshot includes pending `task_status` events and then sends `Ready`.
- Workspace stream test: `update_task_status` buffers full builder-shaped events when no subscriber exists.
- Runtime test: terminal success path with `EventBus` appends one `task_status` and does not directly publish a duplicate.
- Frontend test: duplicate websocket/poll terminal notifications for one `task_id` are handled once.

### 7. Wrong vs Correct

Wrong:

```python
await event_bus.append(status_event)
await stream_manager.publish_event(task.session_id, status_event)
```

Correct:

```python
if event_bus is not None:
    await event_bus.append(status_event)
else:
    await stream_manager.publish_event(task.session_id, status_event)
```

---

## Scenario: Conductor Terminal Seal Fault Isolation

### 1. Scope / Trigger

- Trigger: changing `_seal_graph_and_issue_status`, Conductor recovery relaunch, terminal issue status updates, project-memory recording, self-improvement extraction, or swarm worktree cleanup.
- Terminal sealing crosses several best-effort subsystems. A failure in graph persistence, memory extraction, proposal extraction, or cleanup must not hide the issue's terminal status.

### 2. Signatures

- Seal helper: `_seal_graph_and_issue_status(store, issue, event_bus, result_status)`.
- Recovery relaunch: `_try_relaunch(store, conductor_task, event_bus=None, task_dispatcher_fn=None)`.
- Best-effort post-success hooks:
  - `record_project_memory(graph.id, store)`.
  - `record_issue_self_improvement(issue, store)`.
  - `worktree_manager.cleanup_issue_swarm_worktrees(project, issue)`.

### 3. Contracts

- `result_status in {"done", "success", "completed"}` maps to graph status `done`; every other status maps to `failed`.
- Workflow graph load/save is best-effort for terminal issue sealing. It may warn, but issue terminal status must still be attempted.
- Project memory and self-improvement extraction are best-effort post-success hooks. They must never turn a successful issue into a failed issue or prevent status persistence.
- Issue status persistence and `issue_updated` emission are their own fault boundary.
- Recovery relaunch should yield once after scheduling the new Conductor task so immediate observers/tests can see the scheduled relaunch begin without relying on a later watchdog tick.

### 4. Validation & Error Matrix

- Graph load raises -> warn; still set issue status based on `result_status` and emit `issue_updated` if save succeeds.
- Graph save raises -> warn; still attempt project-memory/self-improvement when graph object exists and still attempt issue status.
- `record_project_memory` raises -> warn; keep terminal status behavior.
- `record_issue_self_improvement` raises -> warn; keep terminal status behavior.
- Issue status save raises -> warn; cleanup may still run best-effort.
- Swarm cleanup raises -> warn only.

### 5. Good/Base/Bad Cases

- Good: graph store is temporarily unavailable, but a failed Conductor still marks the issue `failed` so the UI does not show it as running forever.
- Good: self-improvement proposal extraction crashes after a done issue; the issue remains completed and the failure is only logged.
- Base: awaiting-review/awaiting-merge statuses are preserved only for successful seals.
- Bad: wrapping graph save, memory recording, self-improvement extraction, and issue status save in one broad `try` so an early failure skips issue terminal status.

### 6. Tests Required

- Seal test: graph load failure still saves issue terminal status and emits `issue_updated`.
- Seal test: self-improvement failure does not prevent successful issue completion.
- Recovery test: relaunch context includes persisted graph nodes and recent turns.
- Recovery test: relaunch circuit breaker seals issue failed and emits `conductor_relaunch_exhausted`.

### 7. Wrong vs Correct

Wrong:

```python
try:
    graph = await store.load_workflow_graph_for_issue(issue.id)
    await store.save_workflow_graph(graph)
    await record_project_memory(graph.id, store)
    await record_issue_self_improvement(issue, store)
    await store.save_codex_issue(issue)
except Exception:
    logger.warning("terminal seal failed")
```

Correct:

```python
try:
    graph = await store.load_workflow_graph_for_issue(issue.id)
except Exception:
    graph = None

if graph is not None:
    try:
        await store.save_workflow_graph(graph)
    except Exception:
        logger.warning("workflow graph status seal failed")

try:
    await store.save_codex_issue(issue)
    await _append_event(event_bus, {"type": "issue_updated", "status": issue.status})
except Exception:
    logger.warning("issue terminal status seal failed")
```

> Specialist parent freshness addendum: `request_specialist()` must reload the parent task from the store before validating status or mutating it. The caller's `parent_task` object may be stale because result persistence, scheduler callbacks, and recovery can interleave. A stale `running` object must not create a child when the stored parent is already `failed`, `waiting_for_specialist`, or otherwise non-runnable.

> Runtime task-status fanout addendum: process runtimes should route terminal task status through a single helper (for example `_emit_task_status`). The helper appends to `EventBus` when available, because `EventBus._broadcast_to_ws` owns workspace fanout and scheduler notifications. Only when no `EventBus` exists should it direct-publish to `stream_manager`. Avoid call sites that do both.

---

## Scenario: Project Git Lifecycle API Contract

### 1. Scope / Trigger

- Trigger: changing project git sync endpoints, issue abandon/reset endpoints,
  issue diff behavior, `ProjectService.remote_status()`,
  `ProjectService.fast_forward_pull()`, or issue worktree cleanup in
  `WorktreeManager`.
- These APIs are recovery and trust-boundary operations. They touch the primary
  repo, issue worktrees, task rows, and frontend sync controls, so they must be
  deterministic and non-destructive on failure.

### 2. Signatures

- `GET /api/projects/{project_id}/remote-status?fetch=true|false`.
- `POST /api/projects/{project_id}/pull`.
- `GET /api/codex/issues/{issue_id}/diff?stat_only=false`.
- `POST /api/codex/issues/{issue_id}/abandon`.
- `POST /api/codex/issues/{issue_id}/abandon/finalize`.
- `POST /api/codex/issues/{issue_id}/reset`.
- `POST /api/codex/issues/{issue_id}/conductor/restart`.

### 3. Contracts

- Remote status is read-only except for optional `git fetch`; it returns
  `branch`, `current_branch`, `has_origin`, `dirty`, `behind`, `ahead`,
  `can_fast_forward`, `fetched`, and `error`.
- Pull is fast-forward only. It returns success only after the primary repo has
  advanced with `behind_before` and `new_sha`; refusal returns HTTP `409` with
  a machine-readable detail dict containing `success=false`, `reason`, and
  `branch`.
- Issue diff must detect a missing `git_worktree_path` before invoking git,
  clear stale issue git fields, save the issue, and return an empty diff payload
  with `worktree_missing=true`.
- Abandon is soft by default: it marks `git_merge_status="abandoned"` but keeps
  `git_worktree_path` and the on-disk worktree so the user can inspect or undo.
- Abandon finalize is the destructive cleanup step: it removes the issue
  worktree best-effort and then clears `git_worktree_path`.
- Issue reset must check that the project repo path exists before deleting
  tasks, branches, or worktrees. On success it deletes issue tasks, removes the
  old issue worktree/branch via `cleanup_issue_worktree_for_reset()`, recreates
  the deterministic issue worktree, and resets the issue to open requirements
  state.
- Conductor restart must perform the same missing-repo guard before creating a
  workflow graph or starting the loop.

### 4. Validation & Error Matrix

- Store unavailable -> HTTP `503`, detail `SQLite store not available`.
- Unknown project or issue -> HTTP `404`.
- Project repo path missing during issue reset/restart -> HTTP `409`, no DB
  mutation and no workflow graph creation.
- Pull with no origin, fetch failure, no remote branch, not on default branch,
  dirty worktree, diverged history, or already up to date -> HTTP `409` with
  `detail.reason`.
- Pull fast-forward command failure after preflight -> HTTP `500`.
- Abandoning an already merged issue -> HTTP `409`.
- Finalizing an issue that is not abandoned -> HTTP `409`.

### 5. Good/Base/Bad Cases

- Good: a behind, clean default branch reports `can_fast_forward=true`; pull
  fast-forwards and then remote status reports `behind=0`.
- Good: a deleted issue worktree makes diff return empty data and marks the
  issue stale git fields as `null` instead of crashing with `FileNotFoundError`.
- Base: soft abandon keeps the worktree path and directory; finalize removes
  them.
- Bad: reset deletes tasks before confirming the project repo exists.
- Bad: pull stashes or merges dirty/diverged local work instead of refusing.

### 6. Tests Required

- API tests for remote status: up to date, behind/can fast-forward, no origin,
  and unknown project.
- API tests for pull: success, already up to date, dirty repo, and diverged
  repo.
- API test: missing issue worktree diff returns `worktree_missing=true` and
  clears stale issue git fields.
- API test: soft abandon keeps `git_worktree_path` and the directory; finalize
  clears the path and removes the directory.
- API test: reset with missing project repo returns `409` and leaves issue/task
  state unchanged.
- API test: reset recreates the issue worktree from the deterministic branch and
  removes old generated files.
- API test: conductor restart with missing project repo returns `409` and does
  not create a graph.

### 7. Wrong vs Correct

Wrong:

```python
await worktree_manager.cleanup_issue_worktree(project, issue)
issue.git_merge_status = "abandoned"
issue.git_worktree_path = None
```

Correct:

```python
issue.git_merge_status = "abandoned"
await store.save_codex_issue(issue)
# Later, only on explicit finalize:
await worktree_manager.cleanup_issue_worktree(project, issue)
issue.git_worktree_path = None
```

---

## Scenario: Operations Engineer Startup-Script Task Contract

### 1. Scope / Trigger

- Trigger: changing `POST /api/projects/{project_id}/script-task`, Operations Engineer task creation, project startup-script generation, or the `/projects` frontend button that starts script generation.
- The Projects page button is user-facing orchestration: it must create or reuse exactly one Operations Engineer task and emit enough task-status metadata for standalone pages to track it.

### 2. Signatures

- API: `POST /api/projects/{project_id}/script-task`.
- Request model: `ScriptTaskRequest` / frontend `ProjectScriptTaskRequest`.
- Response model: `ScriptTaskResponse` / frontend `ProjectScriptTaskResponse` with `task_id`, `status`, `title`, `execution_process_id`, and `reused`.
- Task fields:
  - `role="operations_engineer"`.
  - `phase="operations"`.
  - `task_kind="project_script_suggestion"`.
  - `session_id == project.id`.
  - `project_id == project.id`.

### 3. Contracts

- If an active `project_script_suggestion` task exists in `pending`, `running`, or `responding`, the API returns it with `reused=true` and does not start another runner.
- New tasks must preserve request context as JSON in the prompt, including explicit empty strings for `setup_script` and `run_command`.
- New tasks must resolve executor/provider/model through the runtime catalog and persist those fields on the task.
- After runner startup succeeds, the API must emit a builder-shaped `task_status` event with `status="running"`, `role="operations_engineer"`, `task_kind="project_script_suggestion"`, `project_id`, `workspace_id/session_id`, and `execution_process_id`.
- If runner startup fails, the API must mark the task `failed`, persist `task.result`, and emit a builder-shaped `task_status` event with the same role/task_kind/project/workspace fields.

### 4. Validation & Error Matrix

- Store unavailable -> HTTP `503`, detail `SQLite store not available`.
- Unknown project -> HTTP `404`.
- Active script task exists -> HTTP `200`, `reused=true`, no new task, no runner start.
- Runtime config invalid/start conflict -> HTTP `409` from runner/config error.
- Runner raises unexpectedly -> HTTP `500`, task `failed`, `task_status(status="failed")` emitted.

### 5. Good/Base/Bad Cases

- Good: `/projects` button starts task `abc`, receives `task_status(task_id=abc, status=running)`, then tracks only that task id until terminal.
- Good: explicit empty setup/run command inputs stay empty in the prompt and are not replaced by stale project values.
- Base: active task reuse returns `reused=true` and the frontend keeps the same loading flow.
- Bad: creating a generic task with no `role`, causing audit and status bar to render it as an unassigned agent.
- Bad: runner starts successfully but no `task_status=running` event is emitted, leaving standalone pages dependent on polling only.

### 6. Tests Required

- API test: new script task has `role="operations_engineer"`, `task_kind="project_script_suggestion"`, project/session fields, runtime fields, and prompt JSON context.
- API test: startup success emits `task_created` then `task_status=running` with `execution_process_id`.
- API test: active script task is reused without runner start.
- API test: runner startup failure marks task failed and emits builder-shaped `task_status=failed`.
- Frontend test: Projects page button calls `startProjectScriptTask`, stores returned `task_id`, and ignores terminal events for other task ids.

### 7. Wrong vs Correct

Wrong:

```python
await event_bus.append({"type": "task_status", "task_id": task.id, "status": "running"})
```

Correct:

```python
await event_bus.append(
    build_task_status_event(
        task,
        "running",
        execution_process_id=exec_process.id,
    )
)
```

> Operations script task reuse addendum: when `POST /projects/{project_id}/script-task` reuses an active `project_script_suggestion` task, it must still emit a full `task_status` event for the reused task. Reuse must not start a second runner, but it must give standalone project pages the same tracking signal as a fresh start.

> API task-status fanout addendum: HTTP handlers that already have the global `event_bus` must append builder-shaped `task_status` events to `event_bus` only. They must not also direct-publish the same event through `stream_manager`; EventBus owns websocket fanout and scheduler notification.

> Operations script task row-fallback addendum: if the active reused task cannot be loaded as a full `CodexTask`, the API must still emit a `task_status` fallback payload with `role="operations_engineer"`, `task_kind="project_script_suggestion"`, `project_id`, `workspace_id/session_id`, `result`, `review_comment`, and `execution_process_id`. Do not emit a minimal `{task_id, status}` payload.

> Operations script task reuse consistency addendum: the reused response and the reused `task_status` event must use the same normalized `status`, `title`, and `execution_process_id` values. If the full task loads, prefer its fields; otherwise fall back to the list row. Do not let the response say `running` while the event says `responding`, or vice versa.

> Operations script task stale-row addendum: if the active-task list row says a script task is active but loading the full `CodexTask` shows a terminal status, the API must ignore that row and create/start a new task. Full task state wins over list-row state.

> Operations script task zombie-process addendum: active `project_script_suggestion`
> task reuse must be backed by an active `ExecutionProcess`. If
> `last_execution_process_id` is missing, cannot be found, or points at a
> non-running process, the API must mark the old full task `failed`, emit a
> builder-shaped `task_status=failed`, and create/start a fresh Operations
> Engineer task. A stale `pending`/`running`/`responding` task without a live
> process must not permanently block the Projects page button.

> Operations script persistence addendum: an Operations Engineer suggestion
> with an empty `setup_script` or `run_command` must not erase an existing
> project field. Persist an effective suggestion where each empty field falls
> back to the current project value, and use that effective value consistently
> for `project_updated`, `project_script_updated`, `task.result`, and
> `review_comment`.

> Conductor finalize evidence addendum: `finalize_task(done)` must not accept planning-only graphs. Completed `product_manager`/`architect` nodes prove requirements/design, not delivery. If a completed implementation role such as `engineer` or `operations_engineer` exists, a completed verification role such as `qa` must also exist before success can seal. This is a backend safety gate, not just prompt guidance.

> Operations Engineer finalize note: `operations_engineer` counts as an implementation/delivery role for Conductor graph sealing. A startup-script generation issue may be small, but if it is represented in the workflow graph and sealed by Conductor, success still needs verification evidence (`qa` or another future verification role) rather than treating generated scripts as self-verifying.

> Finalize role-set maintenance addendum: backend finalize evidence roles live in `PLANNING_ONLY_FINALIZE_ROLES`, `IMPLEMENTATION_FINALIZE_ROLES`, and `VERIFICATION_FINALIZE_ROLES`. Adding a delivery or verification role requires updating these constants and the success-gate tests; changing only the Conductor prompt is insufficient.

> Verification-only finalize addendum: completed verification roles such as `qa` are not delivery evidence by themselves. `finalize_task(done)` must reject QA-only graphs just as it rejects planning-only graphs; verification only completes the success proof when paired with implementation/delivery evidence.

> Specialist finalize classification addendum: built-in implementation roles include `engineer_frontend`, `engineer_backend`, `operations_engineer`, and `specialist:doc_writer`. Built-in verification roles include reviewer/checker/auditor specialists such as `specialist:security_reviewer`, `specialist:performance_reviewer`, `specialist:accessibility_reviewer`, `specialist:api_contract_checker`, `specialist:dependency_auditor`, `specialist:i18n_checker`, and `specialist:code_reviewer`. Unclassified specialist-only graphs must not finalize as done; classify the role first and add success-gate tests.

> Recognized finalize evidence addendum: any completed-role set with no recognized implementation role and no recognized verification role must be rejected, even if it mixes planning roles with unclassified specialists. Unknown or unclassified roles may provide context, but they are not success evidence until explicitly classified in the backend role sets.

> Delivery-first finalize addendum: recognized verification evidence is never sufficient without recognized implementation/delivery evidence. Graphs such as `architect + qa` or `qa + unclassified specialist` must be rejected because they prove review/planning activity, not delivered work. The success proof is delivery first, then verification.

> Delivery specialist positive-case addendum: success-gate tests must include at least one classified delivery specialist positive path, currently `specialist:doc_writer + qa`, so the backend role classification is not only constrained by negative unknown-specialist cases.

> Finalize unclassified-role diagnostics addendum: when `finalize_task(done)` rejects a graph because it has completed roles but no recognized implementation/delivery role, the result should include `unclassified_roles` for completed roles that are outside the planning, implementation, and verification role sets. This makes catalog drift visible without silently accepting unknown specialists as success evidence.

> Operations script task running-state addendum: after `start_task_run()` succeeds, the script-task API must persist the task as `status="running"` and set `last_execution_process_id` before emitting `task_status=running` or returning the response. The database task, websocket event, and HTTP response must agree on running state and execution process id.

> Operations script task workspace addendum: project-level `operations_engineer`
> startup-script tasks must ensure a backing Codex workspace exists before
> calling `start_task_run()`. Runtimes load a workspace by `task.session_id`, so
> using `project.id` as `session_id` is only valid when a lightweight workspace
> with `id=project.id`, `project_id=project.id`, and `cwd=project.repo_path` has
> been created or already exists. This preserves project-scoped event identity
> while preventing runtime failures such as `Workspace {project_id} not found`.

> Task runner startup failure addendum: when an API starts a task runner and startup raises unexpectedly, persist `task.status="failed"` and `task.result=str(exc)` before emitting `task_status=failed`. The database task and event payload must agree; do not only put the error in the event.

> Dispatch batch start-lock addendum: `dispatch_batch` may serialize the per-agent start gate to keep budget checks, redispatch checks, worktree preparation, and `dispatch_role()` task/node creation consistent. That lock must not cover the long subagent wait (`TaskCompletionRegistry.wait_for_active`) or the batch silently becomes serial. Tests for dispatch batch budget/concurrency should prove healthy batches still overlap while budget-blocked agents stop before worktree preparation.

> Dispatch start-lock scope addendum: `dispatch_subagent` and `dispatch_batch`
> must share an issue-scoped dispatch-start lock for the same issue. The lock
> covers budget gate re-checks, redispatch budget re-checks, per-agent worktree
> preparation, and `dispatch_role()` node/task creation so concurrent tool calls
> cannot all pass against the same stale workflow graph. The lock must still be
> released before `TaskCompletionRegistry.wait_for_active()`.

> Issue budget reservation addendum: `compute_issue_budget_status()` must
> distinguish actual terminal spend from in-flight reservation. Terminal
> execution processes contribute their recorded `total_cost_usd` to
> `spent_usd`; `Running` execution processes must not contribute their partial
> recorded cost to `spent_usd`, but each one must reserve
> `timeouts.estimated_agent_cost_usd()` in `reserved_usd`. Hard gates and
> remaining budget calculations use `effective_spend_usd = spent_usd +
> reserved_usd`.

> Dispatch batch isolation addendum: user-facing `agent_key` values only need to
> be unique inside a batch, but worktree/branch keys must also include the
> `batch_key` so concurrent `dispatch_batch` calls for the same issue and role
> never share a swarm worktree. Subagent completion results must not override
> backend-recorded lineage fields (`agent_key`, `branch`, `worktree_path`) used
> for merge candidates. Cleanup is physical, not display-oriented: failed
> dispatches, no-op merges, and successful merges must call
> `cleanup_agent_worktree()` with `worktree_key` when present, while returned
> tool payloads and conflict reports keep the user-facing `agent_key`. If
> `merge_agent_worktrees()` raises, the tool result must report
> `merge_status="error"` and include `merge_error`; never collapse a merge
> infrastructure failure into `noop` or copy that claims merge success. If a
> batch coroutine is cancelled after preparing a per-agent worktree, it must
> preserve cancellation semantics while still cleaning that prepared worktree in
> `finally` using the physical worktree key.

> Specialist child completion addendum: `workflow_scheduler.on_task_completed()` must route every terminal `specialist_child` status through `SpecialistOrchestrator.complete_specialist_request()`. Scheduler-local specialist resume logic is forbidden because it bypasses the parent `blocked_by_help_id == specialist:<child_id>` stale-child guard. Failed, error, cancelled/canceled, and killed specialist children must clear the current parent lock and move the parent to `ready_to_resume` rather than auto-retrying the specialist node.

> Help request API state addendum: `POST /api/codex/tasks/{task_id}/request-help`
> must not mutate a parent task into `running` to satisfy
> `HelpOrchestrator.request_help()` preconditions. Only tasks that are already
> `running` or `responding` may enter the help wait-lock flow; pending, done,
> failed, ready-to-resume, and terminal tasks must receive `409` without a task
> save.

> Help completion ready-state addendum: whenever `HelpOrchestrator` moves a
> parent task to `ready_to_resume`, it must also clear `blocked_by_help_id`.
> The system must not persist `waiting_for_help` or `ready_to_resume` states
> that point at an already completed/failed/consumed help request.

> Help completion save-order addendum: without a store-level transaction,
> `HelpOrchestrator.complete_help_request()` must first save the parent as
> `ready_to_resume` with `blocked_by_help_id=None`, then save the help request
> terminal payload, and only then attempt auto-resume. This ordering minimizes
> crash windows that would otherwise leave a parent waiting on a help request
> that has already become terminal.
> The same parent-ready-before-terminal-request ordering applies when
> `request_help()` fails to start the help child task.

> Help request reconcile addendum: before creating a new help request,
> `HelpOrchestrator.request_help()` must reconcile unresolved help requests for
> the parent. If a running help request exists but the parent is not locked on
> it, restore `parent.status="waiting_for_help"` and
> `blocked_by_help_id=<help_request_id>`. If that child is already terminal,
> complete the existing help request first, then re-load and re-check the parent
> preconditions; do not immediately create a second help request for a parent
> that was moved to `ready_to_resume`.

> Help child context addendum: help child tasks must inherit the parent
> `project_id`, `issue_id`, and `phase`, and must carry a non-empty role such
> as `help:<target_executor>`. Task status events, audit rows, and task lists
> should be able to attribute help children to the same project/issue as the
> parent.

> Help child running-state addendum: after `request_help()` successfully starts
> the help child runner, it must persist the child as `status="running"`, record
> `last_execution_process_id` when the runner returns one, and emit a
> builder-shaped `task_status=running` event. The child task row, websocket
> event, and execution process id must agree before the API returns.

> Task terminal status addendum: backend application code must use
> `app.application.task_statuses` for shared task terminal/success/failure
> checks. The terminal set includes success spellings (`done`, `completed`,
> `success`, `passed`, `ok`) and failure spellings (`failed`, `error`,
> `cancelled`, `canceled`, `killed`, `timeout`, `timed_out`,
> `protocol_error`). Do not hand-roll partial sets such as
> `{done, failed, cancelled}` in runtime, websocket, help, or specialist
> orchestration paths.

---

### Scenario: Trusted Project Command Execution Boundary

#### 1. Scope / Trigger

- Trigger: changing project start commands, command suggestions, or the process
  launch path. A command that is syntactically shell-free is not automatically
  safe: many package/build tools expose their own execution escape hatches.

#### 2. Signatures

- Parser: `parse_project_command(command: str, project_root: str | Path) -> ParsedProjectCommand`.
- Result: structured `argv: tuple[str, ...]` and project-relative `cwd`.
- Refusal: `ProjectCommandError` with a stable user-facing reason.

#### 3. Contracts

- Parse once, then launch only the returned argv and cwd with `shell=False`.
- Resolve cwd and reject symlink traversal outside `project_root`.
- Apply per-tool subcommand/goal/flag allowlists; a generic executable allowlist
  is insufficient.
- `npx` must use `--no-install` and a locally available package. Downloading or
  installing code during project launch is forbidden.
- Reject nested runtimes, eval/init-script/plugin injection, remote package
  execution, and shell separator/redirection syntax.

#### 4. Validation & Error Matrix

- Shell syntax or cwd escape -> reject before process creation.
- `npm explore ... -- <command>`, `yarn node`, `bun --eval`, Maven exec,
  Gradle init scripts, or Make eval/include injection -> reject.
- `npx` without `--no-install`, `cargo install`, or remote `go run ...@version`
  -> reject.
- Parser/internal gate failure -> fail closed and emit a refusal audit record;
  never fall back to the original command string.

#### 5. Good/Base/Bad Cases

- Good: `npx --no-install vite` in `.` when Vite exists locally.
- Base: an allowlisted package-manager script with ordinary argv-safe flags.
- Bad: `npm explore foo -- sh -c id` or `go run example.com/tool@latest`.

#### 6. Tests Required

- Parser tests assert exact argv/cwd for accepted commands and stable refusal
  reasons for every tool-specific bypass class.
- API/process tests assert a refused command creates no subprocess and records
  the audit refusal.
- Symlinked-cwd tests assert the resolved path cannot leave the project root.

#### 7. Wrong vs Correct

Wrong: allow every command whose first token is `npm`, `go`, or `make`.

Correct: parse to structured argv/cwd, then enforce the selected tool's
subcommand, goal, and flag policy before any spawn.

---

### Scenario: Framework-Owned Verification Fingerprint

#### 1. Scope / Trigger

- Trigger: changing QA evidence, task finalization, worktree state, or model
  payload handling. The model must not be able to attest that its own evidence
  is current.

#### 2. Signatures

- Boundary module: `backend/app/application/verification_evidence.py`.
- Fingerprint inputs: issue/task/role/worktree identity, Git HEAD, and current
  tracked plus untracked code state.
- Finalization consumes stored framework-generated evidence, not a fingerprint
  supplied in model output.

#### 3. Contracts

- Strip/ignore model-supplied fingerprint fields and compute the fingerprint in
  framework code after verification.
- Exclude the framework-owned QA artifact subtree from dirty-state identity so
  writing the evidence does not immediately stale itself.
- Any other tracked or untracked code change changes the fingerprint.
- Missing or stale verification evidence blocks finalization.

#### 4. Validation & Error Matrix

- Missing fingerprint/evidence -> reject finalization.
- Current fingerprint differs from stored fingerprint -> reject as stale.
- Only QA artifact files changed -> evidence remains current.
- Model provides a matching-looking fingerprint -> ignore it and use the
  framework value.

#### 5. Good/Base/Bad Cases

- Good: verification runs, framework stores the computed identity, unchanged
  code finalizes.
- Base: writing the QA report after verification does not invalidate evidence.
- Bad: edit an untracked source file after verification and still finalize.

#### 6. Tests Required

- Assert model fingerprints are discarded.
- Assert tracked and untracked code changes stale evidence.
- Assert QA artifact-only changes do not stale evidence.
- Assert missing/stale evidence refuses finalization.

#### 7. Wrong vs Correct

Wrong: trust `verification_fingerprint` from an agent response.

Correct: derive and compare the fingerprint inside the application boundary at
verification and finalization time.

---

### Scenario: Trusted Frontend Dependency Reuse

#### 1. Scope / Trigger

- Trigger: changing Git worktree preparation or benchmark setup for frontend
  projects whose ignored dependencies are absent from new worktrees.

#### 2. Signatures

- Owner: `WorktreeManager` creates `frontend/node_modules` in a worktree.
- Source: primary checkout's real `frontend/node_modules` directory.
- Benchmark runner validates the resulting layout; it does not invent a second
  dependency-linking scheme.

#### 3. Contracts

- `frontend/node_modules` must be ignored and must be a real directory in the
  worktree.
- Reuse only trusted top-level entries through controlled symlinks to the
  primary checkout; never link the entire directory or repository root.
- Reject an unexpected existing symlink or a non-directory source.
- The repository-root `node_modules` symlink is forbidden.

#### 4. Validation & Error Matrix

- Primary dependency source missing/not a directory -> explicit setup error.
- Worktree `frontend/node_modules` is a symlink -> reject.
- Dependency path is not Git-ignored -> skip/refuse reuse according to the
  manager contract; do not create tracked artifacts.
- Benchmark sees extra, missing, or wrong-target links -> fail validation.

#### 5. Good/Base/Bad Cases

- Good: real ignored directory containing only expected top-level symlinks.
- Base: no reuse when the primary checkout has no installed dependencies.
- Bad: `worktree/node_modules -> primary/node_modules`.

#### 6. Tests Required

- Worktree tests assert directory type, exact link names/targets, ignore state,
  and rejection of pre-existing unexpected symlinks.
- Benchmark tests assert the exact `WorktreeManager` layout and prove the
  benchmark does not create a competing layout.

#### 7. Wrong vs Correct

Wrong: let each benchmark/runtime create whichever `node_modules` symlink it
needs.

Correct: keep creation in `WorktreeManager` and make all consumers validate the
same explicit layout.

---

### Scenario: Reproducible Frontend Docker Context

#### 1. Scope / Trigger

- Trigger: changing the frontend Dockerfile, build context, or generated Next.js
  inputs.

#### 2. Signatures

- Image recipe: `frontend/Dockerfile`.
- Context exclusions: `frontend/.dockerignore`.
- Build input permits projects with no checked-in `public/` directory.

#### 3. Contracts

- The builder creates an empty `public/` before the runner-stage copy.
- Exclude local `node_modules`, `.next`, `.env*`, logs, and package/build caches
  from the Docker context.
- Dependencies inside the image come from the lockfile install stage, never the
  developer machine.

#### 4. Validation & Error Matrix

- Missing repository `public/` -> image still builds with an empty directory.
- Local dependency/build cache enters context -> contract failure; add the
  precise `.dockerignore` entry.
- Lockfile install or production build fails -> image build fails closed.

#### 5. Good/Base/Bad Cases

- Good: small context and reproducible lockfile-installed dependencies.
- Base: repository has no public assets.
- Bad: copy host `node_modules` or require `COPY public` to exist.

#### 6. Tests Required

- Run `docker build -f frontend/Dockerfile frontend`.
- Inspect build output/context size and confirm local `.env*`, `.next`, and
  `node_modules` are excluded.

#### 7. Wrong vs Correct

Wrong: rely on a host `public/` directory and send local caches in the context.

Correct: create the optional directory in the builder and define a narrow
`.dockerignore` contract.
