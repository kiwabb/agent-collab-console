# Enterprise Hardening Roadmap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the first Repository Trust slice of the enterprise hardening roadmap.

**Architecture:** Keep product runtime behavior unchanged. Update documentation, repository hygiene, Docker metadata, and CI so the current FastAPI + Next.js stack is truthful and verifiable.

**Tech Stack:** FastAPI, pytest, Next.js, TypeScript, Node test runner, ESLint, Docker, GitHub Actions.

---

### Task 1: Fix Repository Hygiene

**Files:**
- Modify: `.gitignore`

- [x] **Step 1: Add ignore entries for generated and local-only files**

Add entries for frontend TypeScript build info, Next output, backend SQLite runtime DBs, Python caches, Trellis runtime state, and platform-local agent config.

- [x] **Step 2: Verify ignored files no longer pollute status**

Run: `git status --short --ignored`

Expected: local runtime files appear ignored or remain untracked only when intentionally not covered.

### Task 2: Update Current README

**Files:**
- Modify: `README.md`

- [x] **Step 1: Rewrite architecture and startup sections**

Update frontend from Vite/5173 to Next.js/4000 and backend from 8000 to 9000.

- [x] **Step 2: Add enterprise trust sections**

Document local-first trust boundaries, environment variables, quality commands, CI, Docker limitations, and troubleshooting.

### Task 3: Align Docker Metadata

**Files:**
- Modify: `docker-compose.yml`
- Modify: `frontend/Dockerfile`

- [x] **Step 1: Update compose ports**

Map backend `9000:9000` and frontend `4000:4000`.

- [x] **Step 2: Update frontend Dockerfile for Next.js**

Use a Node runtime image and `npm run build` + `npm run start`; do not copy `/app/dist`.

### Task 4: Add CI Workflow

**Files:**
- Create: `.github/workflows/ci.yml`

- [x] **Step 1: Add backend test job**

Install Python dependencies and run `pytest`.

- [x] **Step 2: Add frontend quality job**

Run `npm ci`, `npx tsc --noEmit --pretty false`, `npm run test`, and `npm run lint`.

### Task 5: Verify and Commit

**Files:**
- All files above

- [x] **Step 1: Run local checks**

Run frontend typecheck/test/lint and backend pytest.

- [ ] **Step 2: Commit and push**

Commit as `chore: establish enterprise repository trust baseline` and push `main`.
