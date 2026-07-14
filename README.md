# Agent Collaboration Console

Strict local-only multi-agent workbench for planning, running, observing, and recovering AI coding workflows.

The product model is a **trusted local operations console**: the browser talks to a loopback-only FastAPI backend, and the backend can execute local CLI tools such as Codex and Claude against trusted local repositories. It is not a multi-user service or an isolation sandbox for malicious repositories.

## Architecture

- **Backend**: Python, FastAPI, Pydantic, SQLite
- **Frontend**: Next.js, React, TypeScript, Tailwind
- **Live updates**: WebSocket event streams
- **Persistence**: SQLite for projects, issues, tasks, execution processes, logs, and artifacts
- **Execution**: Local process runtimes for Codex, Claude, and configured executors

## Ports

| Service | Default URL | Source |
| --- | --- | --- |
| Frontend | `http://127.0.0.1:4000` | `frontend/package.json`, `dev-local.sh` |
| Backend | `http://127.0.0.1:9000` | `dev-local.sh` |
| Backend API via frontend rewrites | `/api/*` -> `http://127.0.0.1:9000/api/*` | `frontend/next.config.ts` |

## Recommended Local Startup

From the repository root:

```bash
./dev-local.sh
```

The script:

- checks that `codex`, Node/npm, and a backend Python runtime are available;
- generates a high-entropy `CONSOLE_AUTH_TOKEN` when one is not provided;
- starts the backend on `http://127.0.0.1:9000`;
- starts the frontend on `http://127.0.0.1:4000`;
- frees those ports before startup;
- keeps both processes in the foreground;
- stops both services when you press `Ctrl+C`.

The browser receives the token as an HttpOnly, `SameSite=Strict` session cookie; frontend JavaScript cannot read it. When the script generates a token, it prints the path of a mode-`0600` temporary token file for local CLI calls and removes that file on shutdown:

```bash
export CONSOLE_AUTH_TOKEN="$(< /tmp/agent-collab-console-token.XXXXXX)"
curl -H "X-Console-Token: $CONSOLE_AUTH_TOKEN" http://127.0.0.1:9000/api/codex/status
```

By default, `REAL_CLI=true`, so agent runs can call real local tools. For demo/offline mode:

```bash
REAL_CLI=false ./dev-local.sh
```

## Manual Local Startup

### Backend

```bash
export CONSOLE_AUTH_TOKEN="$(openssl rand -hex 32)"
cd backend
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 9000
```

### Frontend

```bash
cd frontend
npm install
CONSOLE_AUTH_TOKEN="$CONSOLE_AUTH_TOKEN" npm run dev
```

Both processes must receive the same token. Open `http://127.0.0.1:4000`.

## Quality Gates

Run these before committing user-facing changes:

```bash
cd frontend
npm audit --registry=https://registry.npmjs.org
npm run typecheck
npm test
npm run lint
npm run build
npm run format:check
```

```bash
cd backend
.venv/bin/python -m ruff check .
.venv/bin/python -m mypy app benchmark tests --show-error-codes --no-pretty
.venv/bin/python -c "from app.main import app"
.venv/bin/python -m pytest -q --tb=short --disable-warnings
```

Backend tests marked `slow` are skipped by default via `backend/pyproject.toml`.
To run slow tests too:

```bash
cd backend
pytest -m "slow"
```

Run the lightweight release/security smoke for the local auth boundary, WebSocket Origin gate, command parser, QA evidence semantics, and secret materialization:

```bash
./scripts/security_smoke.sh
```

Real paid Benchmark epochs are an explicit manual release gate. They are not run by ordinary CI because they launch real agents and consume model budget.

## Docker

Docker is useful for smoke checks and isolated demos, but real local CLI execution usually works best on the host because containers do not automatically have access to your host Codex/Claude credentials, shell configuration, repositories, or SSH agent.

Build and run:

```bash
CONSOLE_AUTH_TOKEN="$(openssl rand -hex 32)" docker compose up --build
```

Compose exposes:

- frontend: `http://localhost:4000`
- backend: `http://localhost:9000`

Compose publishes both ports only on `127.0.0.1`, requires a shared token, and uses `REAL_CLI=false` to avoid pretending the container can control host-local tools.

## Strict Local Trust Boundaries

The backend may access:

- local repositories configured as projects;
- local worktrees created for issues/tasks;
- local Codex/Claude commands;
- local SQLite databases and logs;
- environment variables used by model providers and runtimes.

Do not commit local runtime data. The repository ignores generated caches, local SQLite databases, Trellis runtime sessions, and local agent configuration directories.

The supported deployment boundary is one trusted user, one machine, loopback networking, and trusted repositories. LAN/public binding, reverse-proxy exposure, shared team access, and running adversarial repositories are unsupported. Those modes require a separate identity/RBAC layer and OS/container isolation.

Project launch commands are parsed into an allowlisted executable argv plus a repository-scoped cwd. Shell pipelines, redirects, command substitution, interpreter inline code, and cwd escape are rejected before process creation. Child processes receive a minimal environment; console/model/cloud/database credentials are not inherited.

## Project-Driven Prototype Generation

The prototype workspace can analyze a project before generating HTML. Analysis and generation are separate actions: opening or editing a plan never starts paid HTML generation. The first generated version is always a restore baseline; design optimization remains an explicit later iteration so the baseline is preserved in version history.

Supported deterministic discovery:

| Surface | Support |
| --- | --- |
| Next.js App Router / Pages Router | Supported |
| Vite/React with React Router JSX routes | Supported |
| React page directories without routes | Partial, low confidence |
| Browser extensions, Vue, and unknown frameworks | Reported as unsupported; not silently ignored |

Static evidence includes bounded route, page, layout, navigation, style, design-token, and UI-text source. Runtime DOM, screenshots, authentication, and dynamic route fixture generation are not collected automatically.

Page generation uses the built-in `prototype_ui_engineer` role. It runs through the existing Claude Code executor and inherits the active endpoint, credential, and model from Runtime Catalog, including a MiniMax-backed Claude configuration. Each page gets an ephemeral full-project worktree. The task prompt contains only the page title, current target routes, locale, and artifact protocol; Claude locates router entries and follows component, layout, navigation, style, token, and asset imports itself. Scanned source paths, hashes, evidence, project context, restore briefs, and other project routes stay server-side as integrity guards and are never injected into the generation prompt.

The engineer may write only `.agent-collab/prototype-staging/<run-item-id>/index.html`. Its final response is a small checksum manifest rather than the HTML itself, so complete pages are not constrained by one assistant-message token ceiling. The artifact is accepted only after path, symlink, UTF-8, size, complete-document, external-URL, checksum, and source-edit validation. An accepted version is written before database completion to `<project>/prototypes/<prototype-id>/<version-id>/index.html`; preview reads that project file and treats a missing, escaped, or mismatched file as an explicit integrity failure.

Analysis and generation snapshots are persisted and streamed as strict versioned contracts. The review page reconnects through SSE and falls back to bounded REST polling when the stream is unavailable. Generation progress uses `processed / total`; processed includes successful, failed, interrupted, and skipped items. A terminal run with 8 successful and 5 failed pages therefore displays `13/13`, while success and failure remain separate counters.

Operational limits and rollback:

- `PROTOTYPE_GENERATION_ENABLED=false` hides the project-generation entry and rejects new analysis/generation with `503`. Existing plans, prototypes, versions, manual creation, iteration, preview, and regenerate-all remain readable and usable.
- Candidate count, estimated cost, and shared generation concurrency are fail-closed gates. An unavailable or rejected gate does not start model work.
- Plans and generation runs are persisted. Backend restart marks in-flight analysis/generation interrupted so the UI can reanalyze or retry.
- Project-driven generation never falls back to a model request that cannot read the repository. If the Claude UI engineer is unavailable, the request fails before a run or prototype is frozen. Manual one-off HTML streaming remains a separate capability.

Manual real-model acceptance is intentionally explicit:

1. Configure and enable the Claude executor in Runtime Catalog. Select the intended MiniMax provider/model there, then open a trusted test project.
2. Create a zero-input plan and confirm the candidate list/evidence before generating.
3. Generate a small selected subset first; verify task/process correlation, staging cleanup, the restore baseline, progress reconnect, version history, and failure retry.
4. Trigger a full paid batch only after reviewing the estimated count and budget. Automated tests use fake runtimes and never perform this step.

## Important Environment Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `REAL_CLI` | `true` in `dev-local.sh`, `false` in compose | Enables real local CLI execution instead of fake adapters |
| `CONSOLE_AUTH_TOKEN` | required; generated by `dev-local.sh` | Shared URL-safe local control-plane credential, minimum 32 characters |
| `CONSOLE_ALLOWED_HOSTS` | loopback hosts | Allowed HTTP/WebSocket Host names |
| `CONSOLE_ALLOWED_ORIGINS` | local frontend origins | Exact browser origins accepted by REST/WebSocket gates |
| `CODEX_LAUNCH_ENABLED` | `true` | Allows Codex process runtime launch |
| `CODEX_SOURCE_ROOT` | repository root | Source root for local task execution |
| `CODEX_WORKSPACE_ROOT` | `/tmp/agent-collab-console-workspaces` | Local task worktree root |
| `CLAUDE_CMD` | runtime default | Override Claude command |
| `CODEX_CMD` | runtime default | Override Codex command |
| `QA_EXECUTE_COMMANDS` | follows `REAL_CLI` | Enables narrow argv-based QA checks; disabled/no evidence stays `unverified` |
| `BACKEND_API_BASE` | `http://127.0.0.1:9000` | Next.js server-side rewrite target; compose uses `http://backend:9000` |
| `NEXT_PUBLIC_WS_BASE` | derived from the browser host | Optional explicit WebSocket base override |
| `PROTOTYPE_GENERATION_ENABLED` | `true` | Enables project analysis and batch prototype generation; set `false` for rollback |
| `PROTOTYPE_PLANNING_TIMEOUT_S` | `120` | Timeout for repository-scale prototype planning; independent from the shorter workflow Auto-plan timeout |
| `PROTOTYPE_PLANNING_MAX_TOKENS` | `16384` | Independent planning response ceiling; max-token batches are recursively split before the plan is accepted |
| `PROTOTYPE_GENERATION_MAX_CANDIDATES` | `100` | Maximum selected pages allowed in one generation run |
| `PROTOTYPE_GENERATION_ESTIMATED_USD_PER_PAGE` | `0.25` | Conservative estimated cost used by the generation budget gate |
| `PROTOTYPE_GENERATION_MAX_ESTIMATED_USD` | `25` | Maximum estimated cost allowed for one run |
| `PROTOTYPE_GENERATION_GLOBAL_CONCURRENCY` | `2` | Shared model-generation concurrency across all prototype runs |
| `PROTOTYPE_GENERATION_MAX_TOKENS` | `16384` | Independent token ceiling for manual HTML streaming; project-driven generation always uses the Claude UI engineer artifact workflow |
| `PROTOTYPE_ARTIFACT_MAX_BYTES` | `1000000` | Maximum accepted size for one staged HTML artifact |

## Troubleshooting

### Frontend cannot reach backend

Check the backend:

```bash
curl http://127.0.0.1:9000/api/health
```

For an operational snapshot that is safe to share in support/debugging notes:

```bash
curl -H "X-Console-Token: $CONSOLE_AUTH_TOKEN" http://127.0.0.1:9000/api/diagnostics
```

The diagnostics response includes database counts, runtime catalog status,
executor binary availability, WebSocket subscriber counts, and key configuration
flags. It reports whether model API keys are configured, but never returns the
secret values.

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
