# Agent Collaboration Console

Enterprise-oriented, local-first multi-agent workbench for planning, running, observing, and recovering AI coding workflows.

The product model is a **local operations console**: the browser talks to a local FastAPI backend, and the backend can execute local CLI tools such as Codex and Claude against local repositories. This is powerful by design, so the repository treats local trust boundaries, runtime state, and recovery workflows as first-class concerns.

## Architecture

- **Backend**: Python, FastAPI, Pydantic, SQLite
- **Frontend**: Next.js, React, TypeScript, Tailwind
- **Live updates**: WebSocket event streams
- **Persistence**: SQLite for projects, issues, tasks, execution processes, logs, and artifacts
- **Execution**: Local process runtimes for Codex, Claude, and configured executors

## Ports

| Service | Default URL | Source |
| --- | --- | --- |
| Frontend | `http://localhost:4000` | `frontend/package.json`, `dev-local.sh` |
| Backend | `http://localhost:9000` | `backend/Dockerfile`, `dev-local.sh` |
| Backend API via frontend rewrites | `/api/*` -> `http://localhost:9000/api/*` | `frontend/next.config.ts` |

## Recommended Local Startup

From the repository root:

```bash
./dev-local.sh
```

The script:

- checks that `codex`, Node/npm, and a backend Python runtime are available;
- starts the backend on `http://localhost:9000`;
- starts the frontend on `http://localhost:4000`;
- frees those ports before startup;
- keeps both processes in the foreground;
- stops both services when you press `Ctrl+C`.

By default, `REAL_CLI=true`, so agent runs can call real local tools. For demo/offline mode:

```bash
REAL_CLI=false ./dev-local.sh
```

## Manual Local Startup

### Backend

```bash
cd backend
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 9000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:4000`.

## Quality Gates

Run these before committing user-facing changes:

```bash
cd frontend
npx tsc --noEmit --pretty false
npm run test
npm run lint
```

```bash
cd backend
pytest
```

Backend tests marked `slow` are skipped by default via `backend/pytest.ini`. To run slow tests too:

```bash
cd backend
pytest -m "slow"
```

## Docker

Docker is useful for smoke checks and isolated demos, but real local CLI execution usually works best on the host because containers do not automatically have access to your host Codex/Claude credentials, shell configuration, repositories, or SSH agent.

Build and run:

```bash
docker compose up --build
```

Compose exposes:

- frontend: `http://localhost:4000`
- backend: `http://localhost:9000`

The compose default uses `REAL_CLI=false` to avoid pretending the container can control host-local tools.

## Local-First Trust Boundaries

The backend may access:

- local repositories configured as projects;
- local worktrees created for issues/tasks;
- local Codex/Claude commands;
- local SQLite databases and logs;
- environment variables used by model providers and runtimes.

Do not commit local runtime data. The repository ignores generated caches, local SQLite databases, Trellis runtime sessions, and local agent configuration directories.

## Important Environment Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `REAL_CLI` | `true` in `dev-local.sh`, `false` in compose | Enables real local CLI execution instead of fake adapters |
| `CODEX_LAUNCH_ENABLED` | `true` | Allows Codex process runtime launch |
| `CODEX_SOURCE_ROOT` | repository root | Source root for local task execution |
| `CODEX_WORKSPACE_ROOT` | `/tmp/agent-collab-console-workspaces` | Local task worktree root |
| `CLAUDE_CMD` | runtime default | Override Claude command |
| `CODEX_CMD` | runtime default | Override Codex command |
| `BACKEND_API_BASE` | `http://localhost:9000` | Next.js server-side rewrite target; compose uses `http://backend:9000` |
| `NEXT_PUBLIC_WS_BASE` | `ws://localhost:9000` | Frontend WebSocket base URL |

## Troubleshooting

### Frontend cannot reach backend

Check the backend:

```bash
curl http://localhost:9000/api/health
```

If another service owns port 9000, stop it or change the backend/frontend rewrite configuration together.

### Codex or Claude unavailable

Check host commands:

```bash
which codex
which claude
```

If `REAL_CLI=true`, missing CLI tools will cause real executor runs to fail. Use `REAL_CLI=false` for demo mode.

### Local state appears in `git status`

Generated/runtime files should usually be ignored. If new runtime files appear, update `.gitignore` rather than committing local machine state.

Expected local-only examples:

- `backend/*.db`
- `frontend/tsconfig.tsbuildinfo`
- `.trellis/.runtime/`
- `.agents/`, `.claude/`, `.codex/`

## Enterprise Roadmap

See [`docs/enterprise/roadmap.md`](docs/enterprise/roadmap.md).

Current hardening priorities:

1. repository trust: current docs, CI, ignore policy, Docker metadata;
2. operational trust: structured logs, diagnostics, WebSocket health, golden signals;
3. data trust: backup/export/import, migration checks, retention, audit trail;
4. security trust: trust boundaries, dependency automation, SBOM, future permissions;
5. UX trust: accessibility, performance budgets, first-run guidance.
