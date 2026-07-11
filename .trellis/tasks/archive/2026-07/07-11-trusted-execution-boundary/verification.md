# Verification Evidence

Verified on 2026-07-11 against the current worktree.

## Local trust boundary

- `bash scripts/security_smoke.sh`: 164 backend checks and 7 frontend checks passed; temporary FastAPI and Next listeners were both bound to `127.0.0.1`; bad Host and Origin returned 403; strict HttpOnly auth bootstrap and authenticated rewrite returned 200.
- `backend/tests/test_local_auth.py` covers anonymous/wrong/valid REST tokens and pre-accept WebSocket Host, Origin, and token refusal.
- `frontend/tests/localAuthBoundary.test.ts` covers raw Host rejection before token lookup, strict cookie injection, shared transport, and loopback rewrite target.
- `env -u CONSOLE_AUTH_TOKEN docker compose config` failed with the required-token error. The configured form passed and publishes only `127.0.0.1:4000/9000`.
- Both Docker images built successfully. Frontend build context is reduced by `frontend/.dockerignore`, and the image handles projects without a checked-in `public/` directory.

## Side-effect boundary

- `backend/tests/test_project_command.py`: 72 passed, including shell syntax, interpreter inline code, cwd/symlink escape, package-manager wrapper/download, Cargo install, remote Go module, Maven exec, Gradle init script, and Make injection refusals.
- `backend/tests/test_project_run.py -m slow`: 22 passed, including API refusal audit/no-spawn, structured argv launch/stop/log lifecycle, minimal child environment, and stdout/stderr secret redaction.
- `backend/tests/test_project_script_suggestions.py` covers the same structured launch and fail-closed redaction boundary for Operations verification.

## Verified completion

- `backend/tests/test_qa_workflow.py` covers disabled/no-command/refused/timeout/failure/pass reconciliation, criterion-level evidence, model-owned evidence stripping, secret redaction, and framework-owned worktree fingerprints.
- `backend/tests/test_conductor_main_loop.py` covers confirmed acceptance criteria, real QA evidence, role/worktree identity, missing fingerprints, QA-artifact stability, and tracked/untracked code-change staleness.
- Full backend suite passed: 1327 passed, 77 skipped, 172 deselected. Full Ruff and mypy over `app benchmark tests` passed.

## Benchmark and secrets

- Benchmark API/fixture/runner/scorer/store and worktree suites passed. Real runs require project/workspace, execute pinned structured commands in the issue worktree, require a failing precondition, persist command results, and reject synthetic baselines.
- Benchmark dependency validation accepts only a real worktree `frontend/node_modules` directory containing the exact trusted top-level symlinks prepared by `WorktreeManager`; a root symlink is rejected.
- Env crypto/materializer and project-run tests prove ciphertext-at-rest, plaintext-at-materialization, atomic failure, last-row deletion cleanup, start-time empty reconciliation, API masking, and process-output redaction.

## Frontend and release gates

- Full frontend suite passed: 412 passed. TypeScript typecheck, ESLint, Prettier check, production Next build, and npm audit (0 vulnerabilities) passed.
- Backend and frontend Docker images built successfully. A Compose runtime start was not forced because an existing user-owned Python process already occupied `127.0.0.1:9000`; the random-port runtime smoke independently proved the same listener/auth behavior without terminating that process.
