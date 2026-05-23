# brainstorm: enterprise hardening roadmap

## Goal

Turn Agent Collaboration Console from a powerful local-first prototype into an enterprise-grade, reliable, understandable, and operable multi-agent workbench. The project should be installable by a new engineer, safe to run locally, observable while agents work, resilient to failures, and governed by explicit quality gates.

## What I already know

* The product is a local-first multi-agent operations console with FastAPI backend, Next.js frontend, SQLite persistence, WebSocket live events, agent/task orchestration, Skills library, Projects, Issues, Approvals, Artifacts, Knowledge, Settings, and Help.
* Recent frontend work upgraded the UI toward a modern enterprise mission-control surface.
* The repository has many backend tests and frontend source tests, but no visible CI workflow in `.github/`.
* `README.md` is stale: it still describes Vite on port 5173, while `frontend/package.json` uses Next.js on port 4000.
* `docker-compose.yml` and `frontend/Dockerfile` are stale: compose exposes 5173 and frontend Docker copies `/app/dist`, which does not match Next.js output.
* `backend/Dockerfile` exposes/runs port 9000 while compose maps `8001:8000`, so container startup docs are inconsistent.
* `backend/requirements.txt` has broad unpinned lower bounds, which weakens reproducibility.
* There are local generated files and runtime state in the working tree (`frontend/tsconfig.tsbuildinfo`, `backend/codex.db`, `.trellis/.runtime/`, `.claude/`, `.codex/`, `.agents/`) that should not be committed without explicit policy.

## Assumptions

* Preserve the local-first product model: users run the backend on their machine so it can access local CLIs and repositories.
* Prefer incremental hardening over a ground-up rewrite.
* Enterprise-grade means operationally dependable and maintainable, not necessarily SaaS/multi-tenant in this task.
* Avoid backend API rewrites unless they remove a real reliability or security risk.
* First-pass hardening should prioritize high-confidence fixes that improve developer trust immediately.

## Research References

* [`research/enterprise-standards.md`](research/enterprise-standards.md) — External quality bars mapped to this repository.
* [`research/repo-audit.md`](research/repo-audit.md) — Local codebase audit and first-pass risk inventory.

## Requirements

* Create a prioritized enterprise hardening roadmap across documentation, dev environment, CI, security, observability, reliability, testing, and UX.
* Fix the most obvious trust-breaking drift in the first implementation slice: stale README/run instructions and stale Docker metadata.
* Establish a minimum CI quality gate for frontend and backend checks.
* Add or update ignore rules so local runtime/database/build artifacts stop polluting `git status`.
* Document environment variables, ports, startup modes, and known local-first constraints.
* Define next milestones for deeper work: auth/permissions, audit trails, structured logging, backup/export, error budgets, release packaging, and dependency/security automation.

## Acceptance Criteria

* [x] PRD and research files exist for the enterprise hardening effort.
* [x] README accurately describes current Next.js/FastAPI local startup, ports, and troubleshooting.
* [x] Docker and compose files either work for the current stack or clearly state local-first limitations.
* [x] Git ignore policy excludes local databases, build caches, runtime session files, and Python/Node caches.
* [x] A CI workflow exists for backend tests and frontend typecheck/test/lint.
* [x] The first slice runs `frontend` typecheck/tests/lint and backend tests, or documents any environment blocker precisely.
* [x] Remaining enterprise roadmap is captured in a durable doc under `docs/enterprise/`.

## Definition of Done

* New docs are written in clear, current, command-ready language.
* Code/config changes are verified with available local checks.
* No local runtime secrets/databases are committed.
* Changes are committed and pushed after verification.

## Out of Scope

* Full SaaS authentication, billing, or tenant isolation.
* Replacing SQLite with a production database.
* Replacing the orchestration engine.
* Building a cloud deployment platform.
* Completing every enterprise milestone in one pass.

## Technical Notes

* Inspected `README.md`, `frontend/package.json`, `backend/requirements.txt`, `backend/pytest.ini`, `docker-compose.yml`, `backend/Dockerfile`, and `frontend/Dockerfile`.
* Current frontend scripts: `dev` = `next dev --port 4000`, `test` = `node --import tsx --test tests/*.test.ts`, `lint` = `next lint`.
* Current backend test config defaults to skipping tests marked `slow`.
* `frontend/tsconfig.tsbuildinfo` is a generated cache and should not be committed.
* `backend/codex.db` is a local runtime database and should not be committed.
