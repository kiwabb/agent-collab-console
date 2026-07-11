# Trusted Execution Design Research

## Evidence From This Repository

1. The frontend dev server omits `--hostname`; the installed Next CLI reports `0.0.0.0` as the default. Next rewrites `/api/*` to the loopback backend, which makes the backend indirectly LAN-reachable.
2. REST routers and WebSockets have no common actor authentication. Global events accept before checking Host, Origin, or a token.
3. Project run persists a free-form string, applies an allow-by-default blocklist, passes the string to `create_subprocess_shell`, and inherits nearly the whole backend environment.
4. QA uses a safer argv allowlist, but execution is disabled by default and disabled execution does not invalidate an LLM `passed` claim.
5. Benchmark fixtures have pinned checks, but the real executor scores normal agent process exit codes instead of running those checks.
6. Secret env values are encrypted at the API boundary and returned unchanged by the store; `.env` serialization writes the returned ciphertext.

## Comparable Local-Control Patterns

### Loopback developer servers

Local control applications commonly combine explicit loopback binding with a high-entropy per-launch credential. Loopback limits network reachability; the credential and Origin validation address hostile webpages, DNS rebinding, browser extensions, and accidental proxy exposure. Neither control is sufficient alone.

### Capability-based process launchers

Safe launchers separate a requested command from its execution representation: executable argv, a scoped cwd, an explicit environment, resource limits, and an audit identity. Shell syntax is treated as a separate high-risk capability rather than the default string format.

### CI/evaluation systems

Trusted evaluators do not grade a worker using the worker's own status. They run pinned checks outside the worker response, record exact evidence, and distinguish infrastructure failure/unverified from test failure and pass.

### Secret stores

Encryption belongs at persistence boundaries, while decryption belongs at the last responsible execution boundary. API list/read surfaces expose only metadata such as `is_set`; materialization failures are atomic and fail closed.

## Feasible Approaches

### A. Strict local-only with ephemeral token (selected)

* Bind both services to loopback.
* Share an ephemeral token between Next server and FastAPI.
* Centralize REST/WS Host, Origin, and token checks.
* Launch only parsed argv with scoped cwd and minimal env.

This matches the current single-user architecture and has the smallest honest trust claim.

### B. Team service with identity and sandbox

* Add persistent sessions, OAuth/SSO, RBAC, CSRF, per-user budgets, remote workers, and container/VM isolation.

This is the correct future direction for network deployment, but it is a separate product architecture rather than a hardening patch.

### C. Keep unauthenticated localhost and document the risk

This does not address LAN exposure through Next/Docker, hostile-origin browser access, or actor attribution and was rejected.

## Convergence

Approach A is selected. It fixes the current product honestly without pretending loopback is a sandbox. The completion model must still fail closed: until a check runs in the trusted executor, the result is `unverified`, not `passed`.
