# Research: Application-Specific Startup Readiness and Identity

- **Query**: Research the generic architecture for application-specific startup readiness and identity checks in this repository; inspect startup suggestion schemas, startup config types/UI, APIs, tests, and `admin-demo`; compare health endpoint, expected response matcher, launch token, and process/port ownership patterns.
- **Scope**: Internal repository and stack patterns
- **Date**: 2026-07-14

## Executive Finding

The repository already separates **console-managed process liveness** from **loopback HTTP reachability**, but it does not yet carry an application-specific readiness or identity contract. The most direct fit is an optional, strict, per-service HTTP readiness contract that keeps the existing transport probe intact and adds an expected status plus a bounded body identity matcher. A received response continues to mean “address occupied”; only a matcher pass means “expected application ready.”

A dedicated health endpoint is the cleanest producer-side form of that contract, while a declarative matcher also works with existing repositories such as `admin-demo` without requiring a new endpoint. Launch nonces and OS socket ownership answer the narrower question “did this console launch this instance?” and are useful later, but neither is a replacement for application readiness.

## Files Found

| File Path | Description |
|---|---|
| `backend/app/application/local_service_probe.py` | Loopback-only transport reachability probe and status payload composition. |
| `backend/app/application/project_run_manager.py` | In-memory process ownership, PID/process-group lifecycle, and service-keyed logs. |
| `backend/app/application/project_startup_service.py` | Strict Pydantic input validation for persisted multi-service startup configuration. |
| `backend/app/application/project_startup_mcp.py` | JSON Schema for the authoritative `save_startup_config` MCP tool and scoped token pattern. |
| `backend/app/application/role_workflow_service.py` | Operations Engineer repository-analysis prompt and MCP-finalization authority. |
| `backend/app/application/project_script_suggestions.py` | Legacy/single-service suggestion schema and launch verification based on generic reachability. |
| `backend/app/domain/models.py` | `ProjectStartupService` persisted domain shape. |
| `backend/app/adapters/async_sqlite_store.py` | `project_startup_services` schema and transactional round trip. |
| `backend/app/interfaces/api.py` | Startup config, per-service, batch, and legacy run endpoints; health endpoint pattern. |
| `backend/app/application/project_command.py` | Child environment allowlist relevant to launch-token injection. |
| `backend/app/application/timeouts.py` | Existing configurable service probe deadline. |
| `backend/tests/test_local_service_probe.py` | Tests locking transport reachability for every HTTP status without reading bodies. |
| `backend/tests/test_project_run_service_status.py` | Tests separating process ownership and reachability and blocking an occupied address. |
| `backend/tests/test_project_startup_mcp.py` | Multi-service schema, validation, token, and persistence tests using admin-demo-like services. |
| `backend/tests/test_project_script_suggestions.py` | Legacy suggestion parsing and launch verification tests. |
| `backend/tests/test_project_run.py` | Real process/process-group and per-service manager tests. |
| `frontend/src/lib/types/projects.ts` | Process and generic service-reachability status types. |
| `frontend/src/lib/types.ts` | Multi-service startup configuration types. |
| `frontend/src/lib/api/projects.ts` | Startup config and run endpoint clients. |
| `frontend/src/lib/api/health.ts` | Existing status/body identity check for the console backend. |
| `frontend/src/features/projects/projectStartupConfig.ts` | Pure derivation that currently promotes `reachable` into complete/external-service presentation. |
| `frontend/src/features/projects/useProjectStartupConfig.ts` | Startup config loading, polling, and run actions. |
| `frontend/src/features/projects/ProjectStartupConfigPage.tsx` | Aggregate startup progress and multi-service UI. |
| `frontend/src/features/projects/ProjectStartupServicePanel.tsx` | Per-service polling, start/stop controls, and generic reachable display. |
| `frontend/src/features/projects/ProjectRunStatusPanel.tsx` | Legacy process/reachability presentation. |
| `frontend/tests/projectStartupConfig.test.ts` | Pure-state tests, including a reachable HTTP 404 treated as external completion. |
| `frontend/tests/projectRunControls.test.ts` | Source contracts for run polling, controls, types, and localized feedback. |
| `examples/admin-demo/README.md` | Documented backend/frontend ports and stable application routes. |
| `examples/admin-demo/backend/src/main/resources/application.properties` | Spring application name and loopback port 8080. |
| `examples/admin-demo/backend/src/main/java/com/example/admindemo/AdminController.java` | Stable application-specific JSON surface at `GET /api/dashboard`. |
| `examples/admin-demo/backend/src/test/java/com/example/admindemo/AdminControllerTest.java` | Locks a dashboard response field and status 200. |
| `examples/admin-demo/frontend/index.html` | Stable `Northstar 管理后台` HTML title. |
| `examples/admin-demo/frontend/vite.config.ts` | Frontend port 5173 and `/api` proxy to backend 8080. |
| `scripts/security_smoke.sh` | Existing `lsof` listener inspection pattern used by a shell smoke test. |
| `dev-local.sh` | Existing port-to-PID lookup and port-freeing shell behavior. |

## Current Architecture

### 1. The persisted startup service has an address but no readiness contract

`ProjectStartupService` contains service identity inside the console (`project_id`, `service_id`), commands, `access_url`, dependencies, and evidence, but no probe endpoint, expected status, expected body, launch token, or socket owner:

```python
class ProjectStartupService(BaseModel):
    project_id: str
    service_id: str
    name: str
    working_directory: str
    setup_command: str
    run_command: str
    access_url: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
```

Source: `backend/app/domain/models.py:112-123`.

The strict analysis input mirrors this shape and rejects unknown fields with `ConfigDict(extra="forbid", strict=True)` (`backend/app/application/project_startup_service.py:22-45`). The MCP JSON Schema requires the same service properties and sets `additionalProperties: false` (`backend/app/application/project_startup_mcp.py:23-43`, `61-101`). Therefore a readiness field must be introduced at all three contract boundaries together: MCP schema, Pydantic input/domain, and persistence.

SQLite stores exactly the current fields in a composite-key row `(project_id, service_id)` (`backend/app/adapters/async_sqlite_store.py:530-559`). Replacement of all service rows and config metadata is transactional (`backend/app/adapters/async_sqlite_store.py:2033-2093`). This makes readiness naturally a **per-service persisted attribute**, not a project-global flag.

The frontend contract likewise has only `access_url` and no readiness information (`frontend/src/lib/types.ts:446-466`).

### 2. Operations Engineer is the repository-aware source of startup configuration

The current Operations Engineer prompt tells the agent to inspect the repository directly, discover every service, and save one complete dependency graph through MCP (`backend/app/application/role_workflow_service.py:439-468`). The MCP finalization is authoritative; if no finalized result exists, persistence fails (`backend/app/application/role_workflow_service.py:518-539`).

This is the existing place where an application-specific readiness contract can be discovered from repository evidence without hard-coding frameworks or `admin-demo` values in platform code. The prompt currently asks for access URL, dependencies, and evidence, but not a health/readiness endpoint or matcher (`backend/app/application/role_workflow_service.py:459-465`).

There is also a legacy/single-service schema:

```python
class ProjectScriptSuggestion(BaseModel):
    setup_script: str
    run_command: str
    agent_name: str = "Operations Engineer"
    access_url: str | None = None
    notes: list[str] = Field(default_factory=list)
    verification: ProjectScriptVerification | None = None
    env_vars: list[EnvVarEntry] = Field(default_factory=list)
```

Source: `backend/app/application/project_script_suggestions.py:55-62`.

Its older JSON prompt asks only for `setup_script`, `run_command`, `access_url`, notes, and environment variables (`backend/app/application/project_script_suggestions.py:125-180`). Its parser accepts aliases for setup/run/access fields but no readiness matcher (`backend/app/application/project_script_suggestions.py:247-263`). The current MCP-backed multi-service path and this compatibility path both therefore need an explicit compatibility policy if the status model changes.

### 3. Generic reachability deliberately proves only transport/address occupation

`LocalServiceStatus` has these states:

- `reachable`
- `unreachable`
- `not_configured`
- `invalid_url`
- `unknown`

and records `url`, `http_status`, `checked_at`, and `error` (`backend/app/application/local_service_probe.py:20-35`).

`probe_local_service`:

- accepts only `http`/`https` loopback targets;
- normalizes wildcard hosts to loopback;
- rejects userinfo, invalid ports, unsafe hosts, and non-printable URLs;
- disables redirects and environment proxies;
- does not read the response body;
- treats any received HTTP response headers as `reachable`, including 3xx/4xx/5xx;
- wraps the complete request/header phase in a total timeout.

Sources: `backend/app/application/local_service_probe.py:78-110`, `205-270`. The default deadline is 0.75 seconds and is controlled by `PROJECT_SERVICE_PROBE_TIMEOUT_S` (`backend/app/application/timeouts.py:620-622`).

The behavior is intentional and test-locked: 200, 302, 404, and 500 all return `state="reachable"` (`backend/tests/test_local_service_probe.py:86-106`), and a custom stream proves the body is never consumed (`backend/tests/test_local_service_probe.py:109-135`). The related backend spec explicitly says this check proves reachability, not server identity (`.trellis/spec/vibe-kanban/backend/quality-guidelines.md:4004-4068`).

This transport probe is already the right primitive for the first question: **is the configured address occupied/responding?** It should not silently be redefined as readiness.

### 4. Process ownership is already independent from reachability

`ProjectRunManager` stores entries by `(project_id, service_id)`, launches each command with `start_new_session=True`, records the root PID, and considers it running while the owned child has not exited (`backend/app/application/project_run_manager.py:80-130`, `133-198`). Stop targets the owned process group with `killpg`, then reaps it (`backend/app/application/project_run_manager.py:223-298`).

`ProjectRunStatusPayload` combines—but does not conflate—the process status and service probe (`backend/app/application/local_service_probe.py:37-43`, `133-143`). A backend test explicitly locks `running=True` together with `service.state="unreachable"` (`backend/tests/test_project_run_service_status.py:114-140`).

This proves **the console owns a still-live launched process**, not that the process owns the configured socket and not that the expected application is ready.

### 5. API consumers currently promote generic reachability

For a persisted startup service, status is `probe_local_service(service.access_url)` plus the service-keyed process status (`backend/app/interfaces/api.py:3341-3348`).

Per-service start and start-all preflight generic reachability. If an address responds and no managed process is running, they return HTTP 409 `service_already_reachable` before spawning (`backend/app/interfaces/api.py:3396-3424`, `3434-3475`). The legacy project endpoint has the same behavior and adds an audit event (`backend/app/interfaces/api.py:3491-3532`). This safely prevents a blind bind collision but names generic occupation as if the expected service were present.

The frontend derives:

- unmanaged + `reachable` -> `external_reachable`;
- managed + `unreachable` -> `managed_starting`;
- any managed + other state -> `managed_running`;
- Run step complete when the process is running **or** service is reachable;
- Start disabled whenever service state is `reachable`.

Source: `frontend/src/features/projects/projectStartupConfig.ts:63-102`, `177-228`.

The per-service panel similarly shows “reachable,” suppresses Start, and displays no Stop when an unmanaged address responds (`frontend/src/features/projects/ProjectStartupServicePanel.tsx:85-147`). The legacy status panel presents the generic responder as an external running service (`frontend/src/features/projects/ProjectRunStatusPanel.tsx:35-68`, `117-149`).

The frontend test makes the current semantics explicit: an unmanaged responder returning HTTP 404 yields `run="complete"`, `canStart=false`, and presentation `external_reachable` (`frontend/tests/projectStartupConfig.test.ts:317-340`).

### 6. Legacy launch verification has the same identity gap

`verify_project_launch` starts a temporary process, waits for exit/timeout, gathers candidate local URLs, and calls the same generic transport probe (`backend/app/application/project_script_suggestions.py:424-525`, `528-642`). Any `reachable` response produces verification status `verified` (`backend/app/application/project_script_suggestions.py:609-618`).

The test uses `python3 -m http.server` and asserts `verified` based only on reachability (`backend/tests/test_project_script_suggestions.py:171-190`). Thus the identity contract must be reusable by both steady-state run status and launch verification; otherwise the two paths can disagree about “verified.”

## `admin-demo` Evidence

### Existing startup topology

The repository documents two services:

| Service | Command | Access URL | Evidence |
|---|---|---|---|
| Backend | `mvn spring-boot:run` in `backend/` | `http://127.0.0.1:8080` | `examples/admin-demo/README.md:10-25`; `backend/src/main/resources/application.properties:1-3` |
| Frontend | `npm run dev` in `frontend/` | `http://127.0.0.1:5173` | `examples/admin-demo/README.md:27-37`; `frontend/vite.config.ts:4-15` |

A read-only query of the active `backend/console.db` confirms that the persisted startup services are `backend` and `frontend`, with frontend depending on backend, and that they currently store only the root `access_url` values above. No readiness matcher is persisted.

### Stable backend identity surface

`GET /api/dashboard` returns a fixed application-specific JSON object containing, among other fields:

```json
{
  "totalUsers": 2846,
  "activeOrders": 128,
  "monthlyRevenue": 368420,
  "conversionRate": 26.8
}
```

Source: `examples/admin-demo/backend/src/main/java/com/example/admindemo/AdminController.java:9-24`. Its Spring test locks status 200 and `$.totalUsers == 2846` (`examples/admin-demo/backend/src/test/java/com/example/admindemo/AdminControllerTest.java:13-20`). The README also documents this route (`examples/admin-demo/README.md:39-45`).

This is sufficient for a declarative status + JSON-subset identity check without hard-coding the values in console code. It is not a dedicated health endpoint, so its product data is a less explicit identity contract than a stable `{service, status}` response.

### Stable frontend identity surface

The Vite root HTML contains `<title>Northstar 管理后台</title>` (`examples/admin-demo/frontend/index.html:1-13`). A bounded text-contains matcher at the frontend root can distinguish this UI from an arbitrary service on port 5173. The frontend also proxies `/api` to backend 8080 (`examples/admin-demo/frontend/vite.config.ts:7-14`), so a frontend check should deliberately target either the HTML root (frontend identity) or a proxied backend endpoint (end-to-end dependency readiness); those answer different questions.

### No dedicated admin-demo health endpoint found

No `/health`, `/ready`, `/actuator/health`, launch-token echo, or socket-owner contract exists in `examples/admin-demo`. The usable existing fingerprints are `/api/dashboard` JSON and the Northstar HTML title.

## Established Pattern Comparison

### Pattern 1: Dedicated application health endpoint contract

**Existing repository precedent**

The console backend exposes:

```python
@router.get("/health")
async def health_check() -> object:
    return {"service": "agent-collab-console", "version": "1.0"}
```

Source: `backend/app/interfaces/api.py:2709-2712`.

The frontend does not accept HTTP 200 alone. It parses JSON and requires `data.service === "agent-collab-console"`, otherwise throwing `Wrong backend` (`frontend/src/lib/api/health.ts:6-15`). This is already an application identity matcher in the stack. The TypeScript response type permits additive fields (`service` required, `status` optional), while the backend also returns version (`frontend/src/lib/types/common.ts:13-17`). The diagnostics endpoint uses the same stable `service` marker and adds operational status (`backend/app/interfaces/api.py:2267-2284`).

**What it proves**

- Address responds.
- Response belongs to an application implementing the agreed identity marker.
- A separate status field can express readiness/degradation.
- It can recognize a correct instance launched externally as well as one launched by the console.

**Fit and limits**

- Best semantic contract when the target repository already has, or can intentionally add, a health endpoint.
- Stable and cheap to probe; avoids matching incidental page/product data.
- Does not prove current-launch ownership.
- Cannot be universally required because arbitrary imported projects may not expose such an endpoint, and adding one to every project is outside current scope.

**Admin-demo applicability**

- No dedicated endpoint currently exists.
- `/api/dashboard` can act as an existing application-specific response contract for the MVP; a dedicated health route would be a cleaner producer contract if the demo itself is intentionally changed later.

### Pattern 2: Declarative expected status + body identity matcher

**Existing repository precedent**

- The generic probe already captures exact HTTP status while preserving safe loopback URL validation (`backend/app/application/local_service_probe.py:205-270`).
- The console frontend health check performs a simple JSON field match (`frontend/src/lib/api/health.ts:6-15`).
- Strict discriminated unions are an established Pydantic style elsewhere, using literal `kind` fields and `Field(discriminator="kind")` (`backend/app/application/structured_prototype_ai_contracts.py:26-70`; `backend/app/interfaces/structured_prototype_api.py:124-155`).
- Strict startup input models already fail on unknown fields (`backend/app/application/project_startup_service.py:22-69`).
- Bounded JSON handling is an established safety pattern (`backend/app/application/external_prototype_agent_contracts.py:242-259`).

**What it proves**

- Address occupation remains independently observable.
- Expected status determines readiness.
- A configured body predicate identifies the expected application.
- Correct externally launched applications can pass.
- A wrong service returning HTTP 200 fails identity; 302/404/500 remain observable transport responses but fail the expected-ready status.

**Fit and limits**

- Works with existing repositories and existing endpoints; no framework-specific platform code.
- Fits the Operations Engineer evidence-discovery/MCP pipeline.
- JSON subset matching is resilient to additive response fields and aligns with the existing console health check.
- Text contains is useful for HTML UIs such as admin-demo but is weaker than a dedicated JSON marker.
- Response bodies must be bounded and parse failures must fail closed; current generic probe intentionally never reads bodies, so the readiness evaluator should be a separate layer rather than changing transport semantics.
- A static matcher proves application identity, not which launch created the instance.

**Admin-demo applicability**

A repository-derived backend check can use:

```json
{
  "kind": "http",
  "url": "http://127.0.0.1:8080/api/dashboard",
  "expected_status": 200,
  "identity": {
    "kind": "json_subset",
    "expected": {"totalUsers": 2846, "activeOrders": 128}
  }
}
```

A frontend check can use the root URL, status 200, and a bounded text marker `Northstar 管理后台`. These are configuration examples inferred from repository evidence, not platform hard-coding.

### Pattern 3: Per-launch nonce/token echoed by the application

**Existing repository precedent**

Task-scoped internal MCP services already generate opaque tokens with `secrets.token_urlsafe(32)`, send them in a dedicated header, keep session state in memory, compare tokens with `hmac.compare_digest`, and close the session after completion (`backend/app/application/project_startup_mcp.py:107-170`, `175-190`). Equivalent patterns exist for prototype MCP services.

**What it proves**

If a fresh nonce is injected into the launched process and the application returns it at a probe endpoint, the response belongs to the specific launch initiated by this console. It therefore proves **instance ownership**, not merely static application identity.

**Fit and limits in the current startup stack**

- Requires application cooperation: the application must read and echo the nonce.
- Current project child environments are allowlisted and do not pass arbitrary variables (`backend/app/application/project_command.py:132-150`, `734-739`), so a new token cannot currently be injected as an ordinary process env variable through `ProjectRunManager`.
- `.env` materialization exists, but a launch nonce has different lifecycle and secrecy requirements from persisted project configuration; no current startup schema or run-manager entry stores one.
- It intentionally rejects externally launched correct instances because they do not know the current console nonce. That conflicts with the accepted scenario where externally started correct applications may be considered ready but must not be attributed to the console.
- Token echo alone says little about dependency/database readiness unless the echo endpoint also enforces readiness.

**Best role**

An optional later ownership proof layered alongside a static readiness/identity matcher, not the initial universal readiness mechanism.

### Pattern 4: Process/port ownership correlation

**Existing repository precedent**

- `ProjectRunManager` owns a root PID/process group and status is keyed by `(project_id, service_id)` (`backend/app/application/project_run_manager.py:80-198`).
- `stop` uses `os.getpgid`, `killpg`, and `waitpid` to control the owned process tree (`backend/app/application/project_run_manager.py:237-298`).
- `dev-local.sh` uses `lsof -ti :<port>` to find and kill listeners (`dev-local.sh:79-104`).
- `scripts/security_smoke.sh` uses `lsof -nP -iTCP:<port> -sTCP:LISTEN` to assert loopback binding (`scripts/security_smoke.sh:53-67`).

No application-layer startup code was found that maps the configured URL/port listener back to the managed PID/process group.

**What it proves**

When reliable, socket/PID correlation can show whether a listener belongs to a process in the console-owned process group. It can distinguish a foreign occupied port from a console-launched listener without target-application code changes.

**Fit and limits**

- Does not prove the listener is the expected application or that dependencies are ready.
- Platform/tool dependent (`lsof` shell patterns are currently macOS/Unix-oriented).
- Framework dev servers may fork/re-exec; Docker/Compose can expose a host proxy owned by a daemon outside the launched process group; wrapper processes and container networking weaken direct PID correlation.
- Cannot grant readiness to an externally launched correct service because external ownership is intentionally absent.
- The current manager’s process-group ownership remains valuable for Stop authority even without socket correlation.

**Best role**

Optional diagnostic/ownership evidence, not the application identity predicate and not the basis for readiness.

## Comparative Summary

| Pattern | Expected app identity | Readiness | Current-launch ownership | Recognizes correct external instance | Repository support now | Primary limitation |
|---|---:|---:|---:|---:|---|---|
| Dedicated health endpoint | Yes | Yes, if endpoint reports it | No | Yes | Console `/api/health` pattern; absent in admin-demo | Requires target app contract |
| Expected status + body matcher | Yes | Yes | No | Yes | Loopback probe, status capture, health body match, strict schemas | Must bound/parse body safely; matcher quality depends on evidence |
| Launch nonce/token echo | Yes for cooperating launch | Only if echo endpoint is readiness-aware | Yes | No | Scoped token generation/validation patterns exist | Requires app/env integration and per-launch state |
| Process/port ownership | No | No | Often, with platform caveats | No | PID/process group plus shell `lsof` patterns | Forks, containers, portability; no app semantics |

## Contract Shape That Fits Existing Boundaries

The following is a synthesized architecture based on existing repository patterns; it is **not currently implemented**.

### Persisted per-service readiness specification

Keep `access_url` as the user-facing/open target and add a separate optional readiness target because the best check may be `/api/dashboard` or `/health`, not the root page:

```json
{
  "service_id": "backend",
  "access_url": "http://127.0.0.1:8080",
  "readiness_probe": {
    "kind": "http",
    "url": "http://127.0.0.1:8080/api/dashboard",
    "expected_status": 200,
    "identity": {
      "kind": "json_subset",
      "expected": {"totalUsers": 2846, "activeOrders": 128}
    }
  }
}
```

A minimal body union consistent with existing strict discriminated models is:

- `json_subset`: all configured key/value pairs must be present and equal; additive response fields are allowed.
- `text_contains`: a bounded literal marker for HTML/non-JSON services.

A dedicated health endpoint is represented by the same generic contract, for example expected status 200 and JSON subset `{ "service": "agent-collab-console" }`. Platform code remains application-agnostic.

### Separate result dimensions

The response should preserve three independent facts:

1. **Process ownership/liveness** — current `running`, PID, start time, exit code.
2. **Transport/address state** — current generic loopback probe: configured/invalid/unreachable/reachable and HTTP status.
3. **Application readiness/identity** — unconfigured, matched-ready, identity-mismatch, identified-but-unready, invalid-check, or probe-error.

A practical evaluation order is:

1. Validate/canonicalize the configured readiness URL with the current loopback-only rules.
2. Make one request with redirects/proxies disabled and the existing total deadline.
3. If no response arrives, address is unreachable.
4. If any response arrives, address is occupied/reachable regardless of status.
5. Evaluate the bounded body identity matcher.
6. Evaluate expected status for readiness.
7. Combine those facts with managed process state for presentation and Start/Stop authority.

Separating identity-body match from expected readiness status allows a correct application returning, for example, 503 with its stable service marker to be described as **identified but unhealthy**, rather than as either offline or a foreign responder.

### State matrix

| Managed process | Address response | Identity configured/matched | Expected status | Meaning | Start behavior |
|---:|---:|---|---:|---|---|
| No | No | Any | N/A | Offline/unreachable | May start |
| Yes | No | Any | N/A | Managed process starting | No duplicate start; Stop allowed |
| No | Yes | No matcher | N/A | Occupied, identity unverified | Block collision; do not call ready |
| Yes | Yes | No matcher | N/A | Managed and reachable, identity unverified | Stop allowed; do not claim identity/readiness |
| No | Yes | Match | Yes | Correct external application ready | No Start; Open allowed; no Stop |
| Yes | Yes | Match | Yes | Managed application ready | Stop/Open allowed |
| No | Yes | Mismatch | Any | Address occupied by unknown responder | Block collision with occupied/conflict semantics |
| Yes | Yes | Mismatch | Any | Managed process alive but expected app not established | Starting/unhealthy; Stop allowed |
| Any | Yes | Match | No | Expected application identified but not ready | Unhealthy/not ready; keep occupation visible |
| No | Yes | Invalid matcher/config | Any | Address occupied; readiness indeterminate | Fail closed and block collision |

This preserves the existing safety behavior—do not start into an occupied configured address—without promoting occupation into successful startup.

### Legacy compatibility

Existing configurations with no matcher should retain:

- loopback reachability/occupation reporting;
- process lifecycle and Stop ownership;
- collision prevention.

They should explicitly report readiness/identity as **not configured/unverified**, rather than inheriting a false readiness guarantee. The current `not_configured` transport state is insufficient for this distinction because an address can be reachable while the application matcher is unconfigured.

### Shared evaluator requirement

The same application readiness evaluator should be used by:

- per-service `GET .../run/status`;
- per-service and start-all preflight;
- legacy project status/start where a compatible matcher exists;
- Operations Engineer launch verification.

This follows the existing design choice to reuse `probe_local_service` for launch verification (`backend/app/application/project_script_suggestions.py:513-525`) and avoids separate meanings of “verified” and “ready.”

## API and UI Impact Map

### Backend boundaries

- `StartupServiceInput` strict model: `backend/app/application/project_startup_service.py:22-45`.
- MCP schema `_SERVICE_PROPERTIES` and required fields: `backend/app/application/project_startup_mcp.py:23-43`, `61-101`.
- Domain model: `backend/app/domain/models.py:112-123`.
- SQLite table, insert, select: `backend/app/adapters/async_sqlite_store.py:541-555`, `2033-2128`.
- Status payload: `backend/app/application/local_service_probe.py:20-43`, `133-143`.
- Per-service and batch endpoints: `backend/app/interfaces/api.py:3331-3488`.
- Legacy endpoints: `backend/app/interfaces/api.py:3309-3328`, `3491-3551`.
- Operations prompt/MCP finalization: `backend/app/application/role_workflow_service.py:439-468`, `518-539`.
- Legacy launch verification: `backend/app/application/project_script_suggestions.py:513-642`.

### Frontend boundaries

- Additive run status types: `frontend/src/lib/types/projects.ts:15-34`.
- Startup service config type: `frontend/src/lib/types.ts:446-466`.
- API clients: `frontend/src/lib/api/projects.ts:117-228`.
- State derivation currently keyed only to `reachable`: `frontend/src/features/projects/projectStartupConfig.ts:71-102`, `177-228`.
- Page summary and Run-step completion: `frontend/src/features/projects/ProjectStartupConfigPage.tsx:82-130`, `227-323`.
- Per-service card controls: `frontend/src/features/projects/ProjectStartupServicePanel.tsx:23-90`, `121-147`.
- Legacy status presentation: `frontend/src/features/projects/ProjectRunStatusPanel.tsx:35-96`, `117-149`.
- Current user-facing wording says any responder is a local service already running (`frontend/src/lib/i18n/en-US.ts:205-248`).

The existing UI architecture already has separate process and service data, so it can derive managed-ready, managed-starting/unhealthy, external-ready, occupied-unknown, and offline without granting Stop for unowned processes.

## Test Coverage and Required Scenario Locations

### Existing coverage

- Loopback URL validation and SSRF boundary: `backend/tests/test_local_service_probe.py:22-69`.
- Every HTTP status is transport reachable: `backend/tests/test_local_service_probe.py:86-106`.
- Body is not consumed by generic transport probe: `backend/tests/test_local_service_probe.py:109-135`.
- Timeout and connection errors: `backend/tests/test_local_service_probe.py:137-204`.
- Access URL freshness/current-command selection: `backend/tests/test_local_service_probe.py:207-348`.
- Occupied external service blocks before environment materialization/spawn: `backend/tests/test_project_run_service_status.py:61-111`.
- Managed process and reachability remain independent: `backend/tests/test_project_run_service_status.py:114-140`.
- MCP two-service config, bad evidence, cycle, bad token, SQLite round trip: `backend/tests/test_project_startup_mcp.py:63-255`.
- Real process ownership, incremental logs, idempotent stop, and per-service isolation: `backend/tests/test_project_run.py:73-157`.
- Frontend external reachable and managed starting derivations: `frontend/tests/projectStartupConfig.test.ts:230-296`, `317-366`.
- Frontend source contracts for startup polling/control/type boundaries: `frontend/tests/projectRunControls.test.ts:79-174`.

### Not found

- No test where an unrelated HTTP 200 body fails application identity.
- No readiness test for expected 200 vs 302/404/500 while preserving transport reachability.
- No malformed/oversized body readiness test because no readiness body reader exists.
- No test for “identified application but unhealthy status.”
- No persisted readiness matcher round-trip test.
- No frontend state for occupied/unknown responder distinct from correct external-ready.
- No application-layer process-to-listener ownership test.
- No dedicated admin-demo health/ready endpoint or launch-token echo test.
- No backend API tests were found for the current per-service/start-all endpoint functions; current multi-service tests cover MCP persistence and manager isolation, while the legacy occupied preflight has direct API-function coverage.

The acceptance scenarios map naturally to:

- `backend/tests/test_local_service_probe.py` or a new readiness-evaluator test for transport + matcher outcomes;
- `backend/tests/test_project_startup_mcp.py` for strict schema/persistence and invalid matcher failure;
- `backend/tests/test_project_run_service_status.py` for occupied unknown vs external ready vs managed unhealthy;
- `backend/tests/test_project_script_suggestions.py` for launch verification reuse;
- `frontend/tests/projectStartupConfig.test.ts` for the expanded pure state matrix;
- admin-demo Spring/controller tests for any dedicated producer-side health contract, if one is added.

## Related Specs

- `.trellis/spec/vibe-kanban/backend/quality-guidelines.md:4004-4120` — Defines the current local-only reachability probe, SSRF constraints, any-status reachability, and explicit statement that it does not prove server identity.
- `.trellis/spec/vibe-kanban/backend/database-guidelines.md:550-639` — Defines authoritative repository-driven multi-service startup configuration, composite service identity, transactional persistence, and process lifecycle API contracts.
- `.trellis/spec/ccgui/frontend/state-management.md:321-430` — Defines process ownership and HTTP reachability as separate UI dimensions, but currently treats unmanaged `reachable` as an external service and completes the Run step.
- `.trellis/spec/ccgui/frontend/type-safety.md:553-583` — Covers typed Operations Engineer startup-task responses and reused-task recovery.
- `.trellis/tasks/07-14-fix-project-startup-service-identity-detection/prd.md` — Requires separate process liveness, address occupation, and application-specific readiness/identity while preserving collision prevention.

## External References

None required for this report. The repository already contains concrete implementations of all four compared patterns or their enabling primitives: health response identity matching, strict declarative schemas, scoped opaque tokens, and PID/port inspection.

## Recommendation

Adopt the declarative per-service HTTP contract as the MVP: a separate loopback readiness URL, exact expected status, and bounded JSON-subset or literal-text identity matcher discovered by Operations Engineer and persisted through the existing strict MCP path. Keep `probe_local_service` as transport-only occupation evidence; derive readiness by combining matcher results with process ownership. Use a dedicated health endpoint when a repository exposes one, and reserve launch nonces or socket/PID correlation for optional ownership evidence rather than readiness.

## Caveats / Not Found

- The proposed schema and state names above are a synthesis for implementation planning; they do not exist in current code.
- A `/api/dashboard` product-data fingerprint is adequate for the admin-demo regression but is less stable/explicit than a dedicated `{service, status}` health response.
- A body matcher needs a strict response-size limit and fail-closed parsing; the current transport probe intentionally avoids body reads.
- A launch nonce cannot be passed through the current child environment without a deliberate change because arbitrary environment variables are filtered.
- OS socket ownership is not portable or semantically sufficient for application readiness, especially for Docker/Compose and for externally launched correct applications.
