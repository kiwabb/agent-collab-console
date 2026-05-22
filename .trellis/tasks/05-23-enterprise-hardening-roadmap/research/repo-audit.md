# Repository Audit

## Current Stack

* Backend: FastAPI, Pydantic, SQLite via async/sync stores, pytest.
* Frontend: Next.js, React, Tailwind, node test runner, TypeScript.
* Runtime model: local-first backend controls local CLIs and repositories.
* Deployment files: backend Dockerfile, frontend Dockerfile, docker-compose.

## High-Confidence Gaps

### Documentation Drift

`README.md` describes a Vite frontend on port 5173. Current `frontend/package.json` uses Next on port 4000. This makes onboarding unreliable and undermines trust.

### Docker Drift

`frontend/Dockerfile` copies `/app/dist`, which is Vite-style output, while the frontend is now Next.js. `docker-compose.yml` exposes 5173. `backend/Dockerfile` runs port 9000, while compose maps `8001:8000`. These files need to be updated or clearly marked unsupported.

### Dirty Runtime Files

The working tree contains generated and local files:

* `frontend/tsconfig.tsbuildinfo`
* `backend/codex.db`
* `.trellis/.runtime/`
* Python `__pycache__` under backend
* local agent/platform directories

The repository needs a sharper ignore policy.

### CI Missing

No `.github/workflows` files were found. A first enterprise milestone should add CI for:

* backend pytest;
* frontend typecheck;
* frontend source tests;
* frontend lint.

### Dependency Hygiene

Python dependencies are specified with broad lower bounds. This is convenient for prototype work but weak for reproducibility. Node has a package lock. Future work should pin or compile Python dependencies and introduce dependency audit automation.

## First Slice Recommendation

Implement a "repo trust" slice:

1. Update README to match current architecture and ports.
2. Fix or modernize Docker/compose metadata for Next + FastAPI.
3. Add `.gitignore` entries for local DBs, runtime files, build caches, and agent-local config.
4. Add GitHub Actions CI.
5. Write `docs/enterprise/roadmap.md` with follow-on milestones.

## Risks

* Full Docker support for real CLI execution is inherently limited because containers do not automatically have host `codex`/`claude` credentials or shell access.
* CI may need to skip tests that require real local CLIs or long-running worktree behavior.
* Some local Trellis files may be intended to be tracked, but the current root repository has only a subset committed. Avoid committing platform-local files until policy is clear.
