# Codex Runtime Feasibility Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Determine whether local Codex CLI is a viable backend for this MVP in the current environment before more product work continues.

**Architecture:** Stop treating PTY or non-PTY as already-settled implementation paths. First collect reliable runtime evidence, compare invocation modes, and then decide whether to continue with Codex CLI, constrain the MVP, or replace the runtime strategy.

**Tech Stack:** Python, FastAPI, subprocess, PTY, pytest, shell diagnostics

---

### Task 1: Establish a Reproducible Runtime Matrix

**Files:**
- Create or update: `agent-collab-console/backend/verify_happy_path.py`
- Create or update: `agent-collab-console/backend/tests/` diagnostics helpers as needed
- Update: `agent-collab-console/COMMUNICATION.md`

- [ ] **Step 1: Define the matrix**

Document and test these invocation modes:

```text
1. codex exec --json "<prompt>" + stdin=DEVNULL
2. codex exec --json "<prompt>" + stdin=PIPE
3. codex exec --json "<prompt>" + PTY
4. API path used by the current backend
```

- [ ] **Step 2: Capture the same facts for every mode**

For each mode, record:

```text
- did process start
- did thread.started appear
- did turn.started appear
- did item.completed appear
- did turn.completed appear
- total elapsed time
- final exit code
- final error message (if any)
```

- [ ] **Step 3: Save one factual summary**

Update `COMMUNICATION.md` with a short table or bullet list comparing the modes.

- [ ] **Step 4: Verify**

Run the chosen repro commands and make sure the matrix contains real measurements, not assumptions.

- [ ] **Step 5: Commit**

```bash
git add /Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/backend/verify_happy_path.py \
        /Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/COMMUNICATION.md
git commit -m "docs: record codex runtime feasibility matrix"
```

### Task 2: Decide the MVP Runtime Contract

**Files:**
- Update: `agent-collab-console/docs/specs/2026-04-12-local-codex-cli-web-console.md`
- Update: `agent-collab-console/docs/plans/2026-04-12-local-codex-cli-web-console.md`
- Update: `agent-collab-console/README.md`

- [ ] **Step 1: Choose one of three outcomes**

Write down one explicit decision:

```text
A. Codex CLI is viable enough for MVP
B. Codex CLI is usable only behind strict constraints
C. Codex CLI is not currently a viable MVP backend here
```

- [ ] **Step 2: Update docs to match that decision**

Examples:

```md
- If A: state the exact supported runtime path
- If B: state the supported path and the unsupported cases
- If C: say the MVP cannot currently promise reliable local Codex chat
```

- [ ] **Step 3: Remove contradictory statements**

Search and fix stale claims like:

```bash
rg -n "stable|reliable|20-30 seconds|PTY|non-PTY|works end to end|happy path verified" \
  /Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/docs/specs/2026-04-12-local-codex-cli-web-console.md \
  /Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/docs/plans/2026-04-12-local-codex-cli-web-console.md \
  /Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/README.md
```

- [ ] **Step 4: Commit**

```bash
git add /Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/docs/specs/2026-04-12-local-codex-cli-web-console.md \
        /Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/docs/plans/2026-04-12-local-codex-cli-web-console.md \
        /Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/README.md
git commit -m "docs: align codex mvp with runtime feasibility decision"
```

### Task 3: Create the Next Branching Plan Based on the Decision

**Files:**
- Create: follow-up plan file only after Task 2 decision is explicit

- [ ] **Step 1: If outcome A or B**

Write a follow-up plan focused on the supported runtime only.

- [ ] **Step 2: If outcome C**

Write a follow-up plan for one of:

```text
- alternative local runtime
- manual/operator-only Codex integration
- replacing Codex CLI with another backend path for MVP
```

- [ ] **Step 3: Keep the plan honest**

Do not write tasks that assume runtime behavior not demonstrated in Task 1.

- [ ] **Step 4: Commit**

```bash
git add /Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/docs/plans
git commit -m "docs: branch codex follow-up plan from feasibility decision"
```
