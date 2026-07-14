# Research: Sandbox or Docker for Project Dev-Server Startup

- **Query**: Determine whether this repository's project dev-server launcher should use a sandbox or Docker to address port conflicts and service identity/readiness; inspect the trusted execution boundary, launcher/command/env handling, Docker support, `admin-demo`, and platform constraints; compare host processes, containers, and lightweight sandboxes.
- **Scope**: Mixed internal repository and external platform/runtime documentation
- **Date**: 2026-07-14

## Executive Finding

**Docker and sandboxing address different dimensions from application identity/readiness. Neither is the right primary fix for the current bug.**

The present defect is semantic: a generic loopback HTTP response is promoted from **address occupied/reachable** to **the expected application is ready**. A per-service declarative HTTP identity/readiness contract fixes that defect on host processes, in containers, and for correctly started external services. The current task PRD has already selected that architecture and explicitly keeps process liveness, address occupation, and application readiness separate.

Docker can provide a separate network namespace, stable orchestration identity, optional container health status, and dynamic host-port mapping. However:

1. two containers can reuse the same **container** port, but browser access still requires a published **host** port;
2. a fixed mapping such as `127.0.0.1:8080:8080` still conflicts when host port 8080 is occupied;
3. dynamic publication avoids that collision only if the console discovers the assigned host port and propagates/reconstructs access URLs and cross-service configuration;
4. container identity/health metadata does not, by itself, make an arbitrary HTTP response an application identity match;
5. this repository has no generic project image/build/mount/port/health lifecycle abstraction, and `admin-demo` intentionally has no Docker definition.

A lightweight sandbox that shares the host network does not isolate ports. Linux network namespaces can isolate port numbers, but require network plumbing and host forwarding before the browser can reach the service. The readily available low-level option, bubblewrap, is Linux-only and an isolated network contains only loopback by default. On macOS, `sandbox-exec` is deprecated and App Sandbox is an entitlement model for packaged applications, not a portable arbitrary-child network namespace. A cross-platform “lightweight sandbox” would therefore become a platform-specific runtime project without solving application identity.

## Recommendation

**Keep the hardened host-process launcher as the default and implement the selected per-service HTTP identity/readiness matcher now; treat Docker as a future opt-in runtime for projects with explicit container contracts and dynamic loopback port publication, not as the universal identity/readiness or port-conflict fix, and do not introduce a lightweight sandbox for this task.**

## Research Method and Five Angles

1. **Current trust and execution boundary** — inspected the archived trusted-execution task, README trust claims, command parser, child environment, process ownership, log redaction, and shutdown hook.
2. **Current status/identity semantics** — inspected the transport probe, startup-service schema/MCP/persistence, status/start APIs, frontend derivation, tests, and the active task PRD.
3. **Docker/container capability** — inspected repository Docker files and project-command support, then checked official Docker documentation for networking, port publication, Compose identity, health, lifecycle, security, rootless mode, and Docker Desktop.
4. **Lightweight sandbox capability** — checked Linux network namespaces, bubblewrap, macOS `sandbox-exec`, and App Sandbox constraints.
5. **Concrete `admin-demo` fit** — inspected its Spring/Vite bindings, proxy, stable identity surfaces, task scope, and absence of container configuration.

## Files Found

| File Path | Description |
|---|---|
| `README.md` | Defines the product as a trusted, loopback-only local console rather than a malicious-repository sandbox; documents host execution and limited Docker demo use. |
| `.trellis/tasks/archive/2026-07/07-11-trusted-execution-boundary/prd.md` | Selected strict local-only execution, structured argv/cwd/minimal env, and explicitly excluded a general malicious-code sandbox. |
| `.trellis/tasks/archive/2026-07/07-11-trusted-execution-boundary/research/trusted-execution-design.md` | Compares strict local execution with a separate team-service/container-isolation architecture. |
| `.trellis/tasks/archive/2026-07/07-11-trusted-execution-boundary/verification.md` | Records tests for loopback auth, command boundary, env/redaction, shutdown, and root repository Docker images. |
| `.trellis/tasks/07-12-startup-local-service-detection/prd.md` | Introduced transport reachability and duplicate-start prevention while separating console process ownership. |
| `.trellis/tasks/07-12-startup-local-service-detection/research/local-service-probe.md` | Documents why any HTTP status proves only address reachability. |
| `.trellis/tasks/07-14-fix-project-startup-service-identity-detection/prd.md` | Current decision: declarative application-specific HTTP identity/readiness; generic reachability remains address occupation. |
| `.trellis/tasks/07-14-fix-project-startup-service-identity-detection/research/readiness-identity-contract.md` | Detailed internal comparison of response matcher, health endpoint, launch token, and PID/socket ownership. |
| `backend/app/application/project_run_manager.py` | In-memory host process manager keyed by `(project_id, service_id)` with process-group ownership, logs, stop, and shutdown cleanup. |
| `backend/app/application/project_command.py` | Parses approved dev/setup commands into argv/cwd, allows `docker compose up`, and builds a minimal child environment. |
| `backend/app/application/command_safety.py` | Denylist guardrails; comments explicitly state callers must not treat these checks as a sandbox. |
| `backend/app/application/env_materializer.py` | Validates and atomically writes a console-managed project `.env` before launch. |
| `backend/app/application/env_crypto.py` | Encrypts project secret values at rest and decrypts only at materialization. |
| `backend/app/application/qa_output_redaction.py` | Supplies output redaction used before project logs enter the ring buffer. |
| `backend/app/application/local_service_probe.py` | Loopback-only, redirect/proxy-resistant transport probe that intentionally never reads bodies and treats any HTTP response as reachable. |
| `backend/app/application/project_startup_service.py` | Strict multi-service input validation, dependency validation, command parsing, evidence validation, and domain construction. |
| `backend/app/application/project_startup_mcp.py` | Authoritative Operations Engineer MCP schema; currently has no readiness matcher/runtime kind/container contract. |
| `backend/app/application/role_workflow_service.py` | Repository-aware Operations Engineer prompt and MCP-finalized startup configuration path. |
| `backend/app/domain/models.py` | `ProjectStartupService` currently stores command, working directory, access URL, dependencies, and evidence only. |
| `backend/app/adapters/async_sqlite_store.py` | Persists startup services by `(project_id, service_id)` with no runtime/container/readiness columns. |
| `backend/app/interfaces/api.py` | Combines managed process status with generic HTTP reachability; preflights address occupation before spawn. |
| `backend/app/main.py` | Calls `project_run_manager.shutdown_all()` during application shutdown. |
| `backend/tests/test_project_command.py` | Locks structured host commands, Docker Compose `up`, path scoping, shell rejection, and child env allowlisting. |
| `backend/tests/test_project_run.py` | Covers host process groups, per-service process isolation, stop, logs, and redaction. |
| `backend/tests/test_project_run_service_status.py` | Locks separation of managed-process liveness and generic service reachability. |
| `backend/tests/test_local_service_probe.py` | Locks any-status reachability and no-body-read behavior. |
| `frontend/src/lib/types/projects.ts` | Current process plus transport-reachability status types. |
| `frontend/src/lib/types.ts` | Current persisted startup-service frontend type; no readiness/runtime/container fields. |
| `frontend/src/features/projects/projectStartupConfig.ts` | Currently derives unmanaged `reachable` as external completion and disables Start. |
| `frontend/src/features/projects/ProjectStartupServicePanel.tsx` | Polls each service and currently renders generic reachability as a positive state. |
| `docker-compose.yml` | Packages the console itself for isolated demo/smoke use; publishes 4000/9000 on loopback and disables real CLI. |
| `backend/Dockerfile` | Console backend image, not a generic user-project runtime image. |
| `frontend/Dockerfile` | Console frontend production image, not a generic project dev-server image. |
| `examples/admin-demo/README.md` | Documents native Maven and npm startup, ports 8080/5173, and Vite proxy override. |
| `examples/admin-demo/backend/src/main/resources/application.properties` | Spring app binds specifically to host loopback `127.0.0.1:8080`. |
| `examples/admin-demo/backend/src/main/java/com/example/admindemo/AdminController.java` | Stable application-specific JSON at `GET /api/dashboard`. |
| `examples/admin-demo/frontend/package.json` | Vite dev command binds specifically to `127.0.0.1`. |
| `examples/admin-demo/frontend/vite.config.ts` | Fixed frontend port 5173 and default proxy target `http://127.0.0.1:8080`. |
| `examples/admin-demo/frontend/index.html` | Stable frontend title `Northstar 管理后台`. |
| `.trellis/tasks/07-12-vue3-springboot-admin-demo/prd.md` | Original demo scope explicitly excluded Docker/deployment configuration. |

## Current Repository Behavior

### 1. The supported product boundary is trusted host execution

The README calls the product a **trusted local operations console** and explicitly says it is “not a multi-user service or an isolation sandbox for malicious repositories” (`README.md:3-5`). The supported deployment is one trusted user, one machine, loopback networking, and trusted repositories; adversarial repositories require a different OS/container isolation architecture (`README.md:132-146`).

The archived trusted-execution decision selected:

- loopback plus an ephemeral token for the control plane;
- parsed argv and repository-scoped cwd;
- a minimal child environment;
- independent execution evidence;
- continued trust in the local repository rather than a claim of malicious-code isolation.

Sources: `.trellis/tasks/archive/2026-07/07-11-trusted-execution-boundary/prd.md:21-39`, `94-123`; `research/trusted-execution-design.md:32-53`.

This matters because adding Docker “for security” would change the product's trust claim and execution architecture, not merely fix a probe bug.

### 2. The host launcher already has a bounded capability boundary, but not an OS sandbox

`ProjectRunManager`:

- parses the command before launch (`project_run_manager.py:138-153`);
- launches with `asyncio.create_subprocess_exec`, not a shell (`:171-179`);
- uses the validated cwd and minimal environment (`:160-179`);
- creates a new session/process group (`:178`);
- keys ownership by `(project_id, service_id)` (`:133-158`);
- drains stdout/stderr into a 2,000-line bounded, redacted buffer (`:34-39`, `99-109`, `192-210`);
- stops with `SIGTERM`, then `SIGKILL`, and reaps the process group (`:223-298`);
- terminates all known entries when the FastAPI lifespan exits (`project_run_manager.py:327-334`; `backend/app/main.py:270-297`).

`project_command.py` rejects shell pipelines, redirects, substitution, inline interpreters, repository escapes, unsupported package-manager wrappers, remote Go modules, Maven exec, Gradle init scripts, and other command expansions. It emits structured argv/cwd (`project_command.py:167-220`, `224-329`, `515-566`, `696-705`). The child receives only an allowlist such as `HOME`, `PATH`, locale, temp, terminal, and selected XDG variables; console/model/cloud/SSH/database credentials are absent (`project_command.py:132-151`, `734-739`; `backend/tests/test_project_command.py:133-155`).

This is a **capability-reduction layer**, not filesystem/network/UID/syscall isolation. The launched repository program still runs as the console user's host process and can use the user's permissions and host network.

### 3. Environment handling is host-oriented and secret-aware

At start, the API reconciles the project's stored env rows into a repository-root `.env` and refuses invalid/missing values (`backend/app/interfaces/api.py:3287-3306`). `env_materializer.py`:

- lets stored user values override agent defaults (`:106-179`);
- rejects missing secret/empty values (`:182-213`);
- decrypts only a write-only materialization copy (`:240-276`);
- writes atomically (`:279-304`, `443-479`);
- removes stale files only when its ownership marker proves they are console-managed (`:306-345`).

Secret rows are Fernet-encrypted with a local `CONSOLE_ENCRYPTION_KEY` and fail closed if the key is missing/malformed (`env_crypto.py:1-21`, `58-121`).

A container runtime would need an explicit decision about whether this host-created `.env` is bind-mounted, copied into an image, passed through Compose, or translated into container environment/secrets. The repository currently has no such generic translation layer.

### 4. The current status bug is independent of process placement

`probe_local_service` permits only canonical loopback HTTP(S), disables redirects and environment proxies, uses a total deadline, and streams only response headers (`local_service_probe.py:78-110`, `205-270`). It intentionally returns `state="reachable"` for any HTTP response (`:229-246`). The code comment states that it proves loopback reachability, not server identity (`:234-236`).

The API combines that result with the independently owned process status (`local_service_probe.py:37-43`, `133-143`). It preflights the target before a per-service or all-service launch and blocks an unowned reachable address (`backend/app/interfaces/api.py:3396-3424`, `3434-3475`).

The frontend currently promotes generic reachability:

- unmanaged + reachable -> `external_reachable` (`projectStartupConfig.ts:82-102`);
- reachable disables Start and completes the Run step (`:177-228`);
- the service card labels it positively and suppresses Start (`ProjectStartupServicePanel.tsx:85-147`).

Moving the process into Docker or a network namespace would not change the logical error if readiness is still “some HTTP responder answered.” The current task correctly requires an application-specific matcher and keeps address occupation separate (`.trellis/tasks/07-14-fix-project-startup-service-identity-detection/prd.md:40-68`).

### 5. The startup configuration has no runtime or container contract

The persisted domain shape has:

```python
class ProjectStartupService(BaseModel):
    project_id: str
    service_id: str
    name: str
    working_directory: str
    setup_command: str
    run_command: str
    access_url: str | None = None
    depends_on: list[str]
    evidence: list[str]
```

Source: `backend/app/domain/models.py:112-123`.

The strict input and MCP schema mirror this shape and reject additional fields (`project_startup_service.py:22-69`; `project_startup_mcp.py:23-101`). SQLite stores only these fields plus timestamps (`async_sqlite_store.py:529-559`, `2033-2128`). The frontend mirrors them (`frontend/src/lib/types.ts:446-466`).

Not found in this contract or launcher:

- runtime kind such as `host` / `compose` / `container` / `sandbox`;
- image or build context;
- source/binary/cache mounts;
- container user/UID policy;
- internal and published ports;
- dynamic-port discovery;
- Compose project/container identity;
- healthcheck configuration or container-health state;
- resource limits;
- network egress policy;
- container inspect/down/remove lifecycle;
- sandbox profile or platform capability negotiation.

## Existing Docker Support: Present but Narrow

### 1. Root Docker files package the console, not user projects

The root `docker-compose.yml` builds the console backend and frontend, publishes only `127.0.0.1:9000` and `127.0.0.1:4000`, creates one bridge network, and uses a named data volume (`docker-compose.yml:1-40`). It sets `REAL_CLI=false` (`:8-13`). The README explains why: Docker is useful for smoke tests and isolated demos, but real local CLI execution usually works best on the host because containers do not automatically inherit host credentials, shell configuration, repositories, or SSH agents (`README.md:115-130`).

The backend/frontend Dockerfiles package only this application (`backend/Dockerfile:1-16`; `frontend/Dockerfile:1-32`). There is no generic dev-project base image or buildpack system.

### 2. The project command parser can launch project-authored Compose

`parse_project_command` accepts `docker compose ... up` and legacy `docker-compose ... up`, while rejecting other Docker commands (`project_command.py:523-531`). Path-bearing options such as `--file`, `--env-file`, and `--project-directory` must remain within the project (`:94-130`, `264-311`). Tests lock `docker compose up --watch` as valid and `docker ps`, external Compose files/directories, and `docker compose run` as invalid (`backend/tests/test_project_command.py:27-44`, `59-117`).

This means the current host manager can supervise the **Compose CLI command** as one process. It does not integrate with the Docker API or model the containers as first-class managed services.

Important lifecycle consequences of the existing support:

- With attached `docker compose up`, the manager owns the CLI process; Docker documents that interrupting attached `up` with `SIGINT` or `SIGTERM` stops the containers.
- `docker compose up --detach` is not explicitly rejected by the current parser. In detached mode, the CLI exits while daemon-owned containers remain. The manager then records a completed host process and has no `docker compose down`/label/inspect cleanup path.
- Container children are not members of the host CLI process group; they are daemon-managed resources. Host PID/process-group ownership is therefore not container ownership.
- No `docker compose ps`, `port`, `wait`, `inspect`, `stop`, `down`, label query, or Docker SDK usage was found in the project launcher.

The repository's current Compose acceptance is thus a trusted-project command compatibility path, not a Docker orchestration abstraction.

### 3. A checked-in Compose file is not automatically a security sandbox policy

The parser constrains the **Docker CLI argv and file path**, but it does not parse or restrict the contents of a repository's Compose file. A trusted Compose file can request bind mounts, capabilities, privileged mode, host networking, devices, or the Docker socket.

Docker's own security documentation warns that daemon control is powerful: a user able to direct the daemon can bind-mount host paths, including the host root, into a container. The daemon normally has root privileges unless rootless mode is explicitly used. Rootless mode moves both daemon and containers into a user namespace, but has host prerequisites and feature/resource caveats.

Therefore, running an adversarial repository's Compose file would not satisfy a malicious-code sandbox claim merely because the process is called a container. That use case remains outside the repository's declared trusted-repository boundary.

## `admin-demo` Constraints

### 1. Current native topology

| Service | Native command | Binding/access | Dependency behavior |
|---|---|---|---|
| Spring backend | `mvn spring-boot:run` in `backend/` | Explicit `127.0.0.1:8080` | No external services/database. |
| Vite frontend | `npm run dev` in `frontend/` | Script adds `--host 127.0.0.1`; Vite port 5173 | Proxies `/api` to backend URL. |

Sources: `examples/admin-demo/README.md:10-37`; `backend/src/main/resources/application.properties:1-3`; `frontend/package.json:6-9`; `frontend/vite.config.ts:4-15`.

The project task explicitly put Docker/deployment configuration out of scope (`.trellis/tasks/07-12-vue3-springboot-admin-demo/prd.md:28-31`). No Dockerfile, Compose file, devcontainer, healthcheck, `/health`, `/ready`, or Actuator route was found under `examples/admin-demo`.

### 2. Containerizing it is not a transparent wrapper

Both dev servers bind only to `127.0.0.1`. Inside a bridge-network container, that means loopback **inside that container**; ordinary Docker port forwarding targets the container interface, not the server's isolated loopback listener. A container profile would need to alter the bindings to `0.0.0.0` inside the container while still publishing only to host loopback.

The frontend's default proxy target is `http://127.0.0.1:8080`. In separate containers, that address refers to the frontend container itself, not the backend container. The proxy would need a container-network service name such as `http://backend:8080` (or an injected equivalent). The README's existing `VITE_API_PROXY_TARGET` override makes this possible, but the console currently has no generic container-network rewrite contract.

The Java and Node toolchains also require either:

- purpose-built images/Dockerfiles; or
- a generated generic development image with JDK 17, Maven, Node, npm, source mounts, caches, and UID/file-permission handling.

Neither exists for the demo.

### 3. It already has usable application identity without Docker

The backend's `GET /api/dashboard` returns a stable, application-specific JSON shape (`AdminController.java:9-24`), and its test locks HTTP 200 plus `totalUsers=2846`. The frontend root contains `<title>Northstar 管理后台</title>` (`frontend/index.html:1-13`). These can drive the selected declarative JSON-subset/text matcher today, independent of whether the process is host-native or containerized.

## Problem Decomposition

A launcher needs to avoid conflating at least five facts:

| Fact | Question answered | Current source | Docker contribution | Sandbox contribution |
|---|---|---|---|---|
| Process/resource ownership | “Can this console safely Stop what it started?” | In-memory host PID/process group | Container/Compose IDs and labels can provide stronger daemon-resource identity if integrated | Parent/PID namespace can help, but platform-specific lifecycle is required |
| Process/resource liveness | “Is the owned execution still alive/running?” | Child return code | Container running state | Sandboxed child/PID state |
| Address occupation | “Did anything answer/listen at this address?” | Loopback HTTP transport probe | Published host port or internal container port probe | Namespace-local or forwarded-port probe |
| Application identity | “Is the responder the expected application?” | Not implemented yet | Not supplied by network isolation; can use trusted app health/body contract | Not supplied |
| Application readiness | “Can this expected application serve its required function now?” | Not implemented yet | Optional Docker/Compose healthcheck can supply one signal; still project-defined | Not supplied |

Port isolation answers only where sockets live. Runtime labels answer which runtime resource exists. Healthchecks answer only what their project-defined command tests. An HTTP identity/readiness matcher answers what is actually responding at the user-facing endpoint. These signals are complementary, not substitutes.

## Option A: Hardened Host Process (Current Default)

### Security

**Existing:** structured argv, repository-scoped cwd, minimal inherited env, secret-at-rest/materialization boundary, output redaction, process-group ownership, loopback control plane, and trusted repositories.

**Not provided:** filesystem isolation, user/UID isolation, syscall filtering, network egress isolation, resource limits, or protection from malicious repository code running as the user.

This matches the documented threat model and was deliberately selected in the trusted-execution ADR.

### Port isolation

All host processes share the host network namespace. Two services cannot bind the same host address/port. Current behavior probes first and blocks rather than killing the owner or auto-reassigning ports. Framework-level dynamic/fallback ports are not a generic contract and can make analyzed URLs stale.

### Identity and readiness

The selected declarative HTTP matcher fits directly. It can recognize:

- the managed expected app;
- a correctly started external instance;
- an unrelated responder on the configured port;
- an identified app returning an unhealthy status;
- a live process whose endpoint is not ready.

No process-placement change is required.

### UX and portability

Advantages:

- no Docker daemon/Desktop dependency;
- uses the repository's native toolchain and caches;
- preserves IDE/terminal parity and native file watching;
- logs and process ownership already surface in the UI;
- works with the current Operations Engineer command/evidence model.

Constraints:

- the manager uses POSIX primitives (`killpg`, `getpgid`, `waitpid`) and POSIX command parsing; current behavior is not a portable Windows process supervisor without a separate implementation;
- user projects must have native dependencies installed;
- host port conflicts remain explicit conflicts unless the application itself has a configurable port contract.

### Cleanup

Strongest of the three **for the existing implementation**: the console knows the host PID/process group, escalates TERM to KILL, reaps it, cancels log readers, and shuts down all known entries. State remains intentionally in-memory, so it does not recover ownership across backend restarts.

### Implementation scope for the current bug

Contained: add the already-selected persisted readiness matcher, evaluator, API dimensions/state matrix, Operations Engineer schema/prompt, and frontend states. This fixes identity semantics without changing runtime, dependency setup, process control, or project filesystem behavior.

## Option B: Docker / Container Network Namespace

### Security

Docker provides separate filesystem, process, and network namespaces plus default capability reduction and seccomp. Rootless mode further runs daemon and containers without host root, subject to setup prerequisites and limitations.

Security depends heavily on policy:

- writable source bind mounts expose that source to the container;
- arbitrary host mounts, host networking, devices, privileged mode, extra capabilities, or Docker-socket mounts weaken/bypass isolation;
- daemon access is a powerful host capability;
- project-authored Compose must itself be trusted unless the platform parses and constrains its complete effective configuration.

Docker is a meaningful isolation improvement under a restrictive, platform-owned profile. Merely invoking a trusted repository's existing `docker compose up` is not equivalent to such a profile.

### Port isolation

Each bridge-network container has its own network stack and can bind the same internal port as containers in other namespaces. Compose service names provide stable internal discovery even when container IPs change.

For host/browser access:

- fixed publication (`127.0.0.1:8080:8080`) still consumes host port 8080 and still conflicts with an unrelated host listener;
- publication without a fixed host port can allocate an available dynamic port;
- `docker compose port <service> <container-port>` can discover that mapping;
- the console would then have to replace/derive the displayed access URL and propagate backend URLs to dependent frontends;
- publication must specify loopback because Docker defaults to all host interfaces when a host IP is omitted;
- `network_mode: host` removes the port-isolation benefit and is unsuitable for this goal.

Therefore Docker can solve collisions **only with dynamic or managed host publication**, not merely by putting the process in a container.

### Service identity

Docker/Compose supplies strong **orchestrator resource identity**:

- a Compose project name;
- canonical labels such as `com.docker.compose.project` and service labels;
- container IDs;
- service names stable across container recreation.

That identity can prove “this container belongs to this console launch” if the console chooses a unique project name/label and persists or reconstructs it. It does not prove that an arbitrary responder at a user-provided URL is the intended app. A misconfigured container, stale published port, reverse proxy, or incorrect route still needs an application-level check.

### Readiness

Docker distinguishes container running state from health only when a `HEALTHCHECK`/Compose `healthcheck` exists. Official Compose documentation states that normal startup waits only until a container is running, not ready. `depends_on.condition: service_healthy` and `docker compose up --wait` can wait on configured health.

This is useful when a project has a trustworthy healthcheck, but:

- no generic healthcheck exists in the current startup schema;
- `admin-demo` has none;
- a healthcheck command is project-specific and must still carry an identity/readiness contract;
- externally started correct applications remain outside this launch's container labels but should still be recognizable as expected applications under the current PRD.

A Docker runtime would therefore complement, not replace, the declarative HTTP matcher.

### UX and portability

Advantages:

- reproducible toolchain/images when definitions exist;
- internal service DNS and isolated port spaces;
- natural multi-service grouping;
- inspectable runtime IDs, state, logs, health, resource limits, and explicit teardown;
- dynamic host publication can avoid fixed host-port collisions.

Costs/constraints:

- Docker/compatible runtime must be installed, running, and authorized;
- images/builds add latency, downloads, disk use, and cleanup needs;
- on macOS and Windows, Docker Desktop runs Linux containers in a Linux VM and forwards ports/files between host and VM;
- bind-mounted development trees/file watching can behave differently and incur file-sharing overhead on Docker Desktop;
- UID/GID and generated-file ownership differ across native Linux, rootless mode, and Desktop VM sharing;
- host credentials, SSH agent, shell config, language caches, and native services are not automatically present;
- framework bindings and inter-service URLs often need container-specific overrides;
- the current Operations Engineer would need to discover or generate a much larger contract than command/cwd/access URL.

### Cleanup

Potentially strong if implemented as a first-class runtime:

- use a unique Compose project name and console-owned labels;
- inspect exact resources;
- stop/down containers and networks by identity;
- decide named-volume retention explicitly;
- recover daemon state after console restart.

Current repository behavior does not do this. It owns only the Compose CLI process. Detached containers can outlive that process and the backend, while attached Compose lifecycle depends on CLI signal handling.

### Implementation scope

A universal container launcher is a separate subsystem. At minimum it requires:

1. runtime capability detection and typed errors;
2. an explicit runtime selection policy, not hidden command rewriting;
3. image/Compose discovery or generation;
4. build contexts and cache policy;
5. source, dependency-cache, and generated-file mount policy;
6. container user/UID/GID and rootless policy;
7. loopback-only dynamic host-port allocation and mapping discovery;
8. service-to-service URL/environment translation;
9. container/Compose identity persistence or deterministic reconstruction;
10. health/HTTP readiness integration;
11. logs, stop/down, restart recovery, orphan cleanup, volume policy, and failure reconciliation;
12. restrictions on privileged mode, host mounts/network, devices, capabilities, and Docker socket if the threat model expands;
13. macOS/Linux/Windows and Docker Engine/Desktop/compatible-runtime testing.

That scope is disproportionate to the current identity bug and conflicts with the active PRD's out-of-scope automatic port rewriting (`prd.md:96-103`).

## Option C: Lightweight Sandbox / Direct OS Namespaces

### Security

On Linux, low-level tools can combine user, mount, PID, IPC, UTS, cgroup, network namespaces, seccomp, no-new-privileges, and a curated filesystem. Bubblewrap is one such unprivileged building block: it creates an empty mount namespace/root and allows explicit read-only/read-write bindings.

It is intentionally lower-level than an OCI development environment. The launcher must supply the filesystem tree, runtime binaries/libraries, DNS/network, devices, temp directories, UID mappings, seccomp policy, and process lifecycle.

On macOS, the installed `sandbox-exec` manual marks it deprecated and directs developers to App Sandbox. App Sandbox is configured with entitlements for an application target; it is not a supported generic profile system for arbitrarily launching Maven/npm child trees. It also does not create Linux-style independent port namespaces.

### Port isolation

- A filesystem/syscall sandbox that shares the host network provides **no port isolation**.
- A Linux network namespace isolates port numbers and network stacks.
- Bubblewrap's `--unshare-net` starts with only loopback, so the service is not browser-reachable from the host by default.
- To expose it, the console must create veth/slirp/pasta/proxy forwarding, allocate a host port, configure routes/DNS/firewall, discover the mapping, and clean up helpers.
- Once a host forwarding port is required, fixed host publication has the same conflict problem as Docker; dynamic forwarding requires the same URL propagation work.

### Identity and readiness

The namespace can prove that the console created a namespace/process, but it provides no application identity or readiness semantics. The same HTTP matcher is still required. A port-forward helper is another owned resource whose liveness must not be mistaken for application readiness.

### UX and portability

Advantages on Linux:

- lower runtime/image overhead than Docker;
- precise platform-owned filesystem/network policy;
- namespace cleanup follows process lifetime when all namespace references disappear.

Constraints:

- Linux-only mechanisms and distribution/kernel configuration differences;
- unprivileged user namespaces may be disabled or constrained;
- bubblewrap may not be installed (it is absent in the inspected macOS environment);
- constructing a usable Maven/Node/Python/Rust environment is manual;
- network forwarding and DNS substantially increase implementation scope;
- no supported equivalent abstraction spans macOS and Windows;
- macOS `sandbox-exec` is deprecated, while App Sandbox requires a packaged entitlement architecture.

### Cleanup

A namespace disappears when its last process/reference exits, and bubblewrap's temporary root is automatically cleaned when the last process exits. However, any host-side port forwarder, slirp process, caches, writable overlays, and bind-mounted outputs need explicit lifecycle ownership. Cross-process/backend-restart recovery remains a separate design.

### Implementation scope

For a Linux-only no-network command sandbox, scope can be modest. For an interactive, browser-reachable, multi-service dev-server runtime with dependency installation and live file watching, scope approaches a small container runtime and has worse cross-platform coverage than Docker.

It is therefore not a lightweight solution to this task's port or identity problem.

## Comparative Matrix

| Criterion | Hardened host process | Docker/container runtime | Lightweight sandbox/netns |
|---|---|---|---|
| Fits current trusted-local product boundary | **Yes; selected architecture** | Optional fit, but changes runtime assumptions | Only as a new platform-specific mode |
| Runs current project commands without new definitions | **Yes** | Only when image/Compose/toolchain policy exists | Requires constructing runtime filesystem/toolchain |
| Prevents malicious repo access to host | No; not claimed | Potentially better under restrictive owned policy; arbitrary Compose is not sufficient | Potentially strong on Linux with complete policy |
| Internal port isolation | No | **Yes** on bridge/container networks | **Yes** only with a network namespace |
| Avoids occupied fixed host port automatically | No | Only with dynamic/managed host publication | Only with dynamic/managed host forwarding |
| Browser reachability | Direct loopback | Requires published/forwarded host port | Requires forwarding out of isolated netns |
| Existing process/resource ownership | **PID/process group** | CLI only today; container IDs/labels require integration | Child/namespace ownership requires new integration |
| Application identity | Needs selected HTTP matcher | Still needs matcher/health identity | Still needs matcher |
| Readiness | Needs selected HTTP matcher | Can add container health; absent by default | Needs selected HTTP matcher |
| Correct external app recognition | **Yes with matcher** | Matcher can; launch labels alone cannot | Matcher can; namespace ownership alone cannot |
| Native file watching/caches/toolchains | **Best parity** | Mount/VM/runtime dependent | Policy/runtime dependent |
| macOS support | Current environment works | Docker Desktop VM; available in inspected environment | No portable low-level equivalent; `sandbox-exec` deprecated |
| Linux support | Current POSIX model | Native Engine/Desktop/rootless variants | Best platform for namespaces/bubblewrap |
| Windows support | Current `killpg` model does not provide it | Docker Desktop/WSL possible with separate testing | Different primitives required |
| Cleanup in current repo | **Implemented for host process groups** | Only Compose CLI process; no first-class container cleanup | Not implemented |
| Scope to fix current bug | **Contained** | Large separate subsystem | Large and platform-specific |

## Platform Evidence From the Current Environment

A read-only runtime check on 2026-07-14 found:

- host: `Darwin 25.0.0 arm64`;
- Docker CLI and server: 28.2.2;
- Docker server OS: Linux under Docker Desktop;
- active security options included built-in seccomp and cgroup namespaces, but did not report rootless mode;
- `podman` and `bwrap` were absent;
- `/usr/bin/sandbox-exec` existed, and its own manual labels it deprecated.

This confirms Docker is available on the developer machine used for this research, but repository code/README do not declare Docker as a mandatory user prerequisite. Environment availability must not be generalized into a product contract.

## External References

### Docker networking, ports, identity, and readiness

- [Docker: Port publishing and mapping](https://docs.docker.com/engine/network/port-publishing/) — Unpublished bridge ports are isolated; published ports map to host addresses; omitted host IP publishes broadly; explicit `127.0.0.1` restricts host publication.
- [Docker: Running containers](https://docs.docker.com/engine/containers/run/) — Containers have separate filesystems/network/process trees; host publication can map a container port to a different or random host port; healthcheck flags are separate from running state.
- [Docker Compose: Networking](https://docs.docker.com/compose/how-tos/networking/) — Compose creates a project network, provides stable service-name discovery, distinguishes host and container ports, and documents dynamic host-port discovery through `docker compose port`.
- [Docker Compose: Services reference](https://docs.docker.com/reference/compose-file/services/) — Defines `ports`, `healthcheck`, `depends_on` conditions, and canonical Compose labels.
- [Docker Compose: Startup order](https://docs.docker.com/compose/how-tos/startup-order/) — Explicitly states Compose normally waits for running, not readiness; `service_healthy` depends on a configured healthcheck.
- [Docker Compose: `up`](https://docs.docker.com/reference/cli/docker/compose/up/) — Attached `up` stops containers on interrupt; detached mode leaves them running; `--wait` waits for running/healthy services.
- [Docker Compose: Project names](https://docs.docker.com/compose/how-tos/project-name/) — Defines explicit project identity and precedence, useful for resource ownership rather than application identity.

### Docker platform and security

- [Docker Desktop: Networking](https://docs.docker.com/desktop/features/networking/) — Docker Desktop runs Engine in a Linux VM, routes host/VM traffic and file access through backend components, and forwards published host ports to container IPs.
- [Docker Desktop: Settings and resources](https://docs.docker.com/desktop/settings-and-maintenance/settings/) — Documents VM CPU/memory/disk controls and host file-sharing overhead/constraints.
- [Docker Engine security](https://docs.docker.com/engine/security/) — Documents namespace/capability isolation and warns that daemon control plus host mounts is a powerful host capability.
- [Docker rootless mode](https://docs.docker.com/engine/security/rootless/) — Runs daemon and containers in a user namespace without host root, with subordinate UID/GID prerequisites.
- [Docker user namespace remapping](https://docs.docker.com/engine/security/userns-remap/) — Documents UID remapping benefits and bind-mount/feature complexity.

### Lightweight sandbox and OS namespaces

- [Linux `network_namespaces(7)`](https://man7.org/linux/man-pages/man7/network_namespaces.7.html) — Network namespaces isolate devices, protocol stacks, routing/firewall tables, and port numbers; resources disappear/move when the namespace is freed.
- [bubblewrap](https://github.com/containers/bubblewrap) — Linux unprivileged sandbox building block using mount/user/PID/network namespaces; isolated networking has only loopback; temporary root is cleaned when the last process exits.
- [Linux seccomp filter documentation](https://docs.kernel.org/userspace-api/seccomp_filter.html) — Syscall filtering reduces exposed kernel surface and is separate from network/port identity.
- [Apple App Sandbox](https://developer.apple.com/documentation/security/app-sandbox) — Supported macOS containment model based on application entitlements and resource access.
- Local macOS `sandbox-exec(1)` manual — Marks `sandbox-exec` deprecated and directs application developers to App Sandbox.
- [Apple Developer Forums: custom sandbox guidance](https://developer.apple.com/forums/thread/661939) — Apple DTS explains that custom sandbox profile facilities are not a supported third-party product surface and that App Sandbox is a different entitlement-based model.

## Adversarial Claim Verification

The main decision claims were checked against independent repository evidence and external runtime documentation. No material claim was retained solely because one mechanism's marketing description implied it.

| Claim | Supporting evidence | Adversarial check | Result |
|---|---|---|---|
| Docker isolates internal ports but does not automatically solve a fixed occupied host port | Docker port-publishing docs; Compose host/container port distinction; Linux netns port isolation | Fixed `HOST_PORT:CONTAINER_PORT` still requires host listener; host networking removes isolation | **Retained, high confidence** |
| Dynamic Docker publication can avoid a collision | Docker run/Compose dynamic-port docs; `docker compose port` discovery | Access URL and dependent-service configuration become dynamic and must be propagated; omitted host IP may overexpose | **Retained with conditions, high confidence** |
| Docker running state is not readiness | Compose startup-order docs; healthcheck/service_healthy docs; current repo separates process and HTTP signals | A valid project-defined healthcheck can provide readiness, but none exists generically or in admin-demo | **Retained, high confidence** |
| Container identity is not application HTTP identity | Compose project/service labels and container IDs; current bug caused by responder ambiguity | If endpoint mapping is derived exclusively from an owned container and its trusted healthcheck, orchestration evidence is stronger, but externally started correct apps and HTTP content still need app semantics | **Retained, high confidence** |
| Arbitrary checked-in Compose is not a malicious-code sandbox policy | Current parser validates argv/path but not Compose contents; Docker security warns about daemon/mount power | Rootless/restrictive platform-owned profiles can reduce risk | **Retained with distinction, high confidence** |
| Lightweight network namespace is not a portable quick fix | Linux netns and bubblewrap docs; macOS deprecated `sandbox-exec`; App Sandbox entitlement model | Linux-only deployments could implement it, but still need forwarding and readiness | **Retained, high confidence** |
| The current host path is the smallest correct fix | Active PRD decision and out-of-scope list; existing schema/API/UI architecture; matcher research | Host path does not solve future adversarial-repo isolation or automatic port remapping | **Retained for current task, high confidence** |

## Decision Fit With Existing Specs and Tasks

### Current task

`.trellis/tasks/07-14-fix-project-startup-service-identity-detection/prd.md` already decides:

- generic reachable remains transport/address occupation;
- application identity/readiness is a declarative HTTP matcher;
- configs without a matcher become invalid and require regeneration;
- an occupied unknown responder blocks launch without being called ready;
- launch token and OS ownership are future/optional dimensions;
- automatic port selection/rewriting and universal framework health endpoints are out of scope.

Docker or sandbox adoption would not replace these requirements and would expand beyond this task.

### Trusted execution boundary

`.trellis/tasks/archive/2026-07/07-11-trusted-execution-boundary/prd.md:32-39`, `110-123` explicitly retains trusted local repositories and treats general sandboxing/container orchestration as a separate future product architecture. The README mirrors that boundary (`README.md:132-146`).

### Backend quality and persistence specs

- `.trellis/spec/vibe-kanban/backend/quality-guidelines.md:4004-4120` defines the current probe as SSRF-resistant loopback reachability, explicitly not identity.
- `.trellis/spec/vibe-kanban/backend/database-guidelines.md:550-660` defines repository-autonomous multi-service startup configuration, composite service identity, dependency order, and host process lifecycle.

A container runtime would require new spec contracts rather than an incidental change to the existing probe.

### Frontend state spec

`.trellis/spec/ccgui/frontend/state-management.md:321-430` distinguishes process ownership and HTTP reachability, but its current `reachable`-means-complete language is exactly the semantic layer the active task is replacing with expected-application readiness.

## If Docker Is Added Later: Boundary of a Coherent Opt-In Mode

This is not required for the current fix, but the comparison converges on the following minimum boundary for a future Docker mode:

1. **Explicit runtime type** in persisted service configuration; never silently wrap native commands.
2. **Project capability check**: existing trusted Compose/image contract or an intentionally generated platform-owned definition.
3. **Unique launch identity**: deterministic/recorded Compose project name plus console-owned labels; container IDs are runtime data, not application identity.
4. **Loopback-only dynamic host publication** when collision avoidance is desired; discover mappings and expose the resolved URL as runtime state.
5. **Separate internal and external URLs** so container-to-container DNS and browser access are not conflated.
6. **Container health plus HTTP identity/readiness**, with running, healthy, address reachable, expected app matched, and launch ownership represented separately.
7. **First-class teardown/recovery** using inspect/stop/down/remove by owned identity, including detached containers, networks, port forwarders, and explicit volume retention.
8. **Restrictive security profile** if stronger isolation is claimed: non-root user/rootless where available, no Docker socket, no privileged/host network, minimal capabilities, bounded mounts, and resource limits.
9. **Platform contract** for native Linux versus Docker Desktop VM file/network behavior and clear prerequisite/error UX.

Without these pieces, switching the command from host-native to Docker relocates the process but does not provide a reliable universal launcher.

## Caveats / Not Found

- No generic project-container runtime, Docker SDK integration, sandbox abstraction, runtime-kind schema, port mapping state, container health state, or container cleanup service was found.
- `admin-demo` has no Dockerfile, Compose file, health endpoint, readiness endpoint, or container binding configuration; Docker was explicitly out of scope when it was created.
- Current Docker command support does not appear to reject detached Compose `up`; no matching first-class `down`/inspect recovery path was found. This is a description of the present parser/lifecycle boundary, not evidence that detached mode is used by the demo.
- The exact Docker daemon policy varies by user installation. The inspected machine uses Docker Desktop and did not report rootless mode; this must not be assumed for all users.
- Bubblewrap availability and unprivileged-user-namespace policy vary by Linux distribution. It was not installed on the inspected macOS host.
- The proposed future Docker boundary above is architectural scope guidance, not an implemented design or current task requirement.
- Docker health is only as meaningful as the configured healthcheck; it must not be treated as universal application identity without a trusted contract.
