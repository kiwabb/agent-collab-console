# Conductor — design + deferred items

## What Conductor is

A "5th agent" alongside PM / Architect / Engineer / QA. Runs after every task
completes inside `WorkflowScheduler.on_task_completed`. Sees the team state
end-to-end and produces ONE of three decisions per round:

| action | meaning | side effect |
|---|---|---|
| `proceed` | nothing to say, normal round | event emit only (UI dock glow) |
| `note` | team learning worth keeping | appends a line to `<repo>/.agent-collab/team_notes.md` so every agent's next-run prompt picks it up |
| `escalate` | workflow looks stuck or wrong | **pauses the workflow**: skips auto-rework and finalize; user must resume manually |

Backend: `backend/app/application/conductor_supervisor.py`
Wired in: `backend/app/application/workflow_scheduler.py` (`on_task_completed`)
Frontend banner: `frontend/src/features/issues/IssueDetailPage.tsx`
Event type: `conductor_decision` (broadcast on the workspace WS bus)

Disable at runtime with `CONDUCTOR_ENABLED=false`.

---

## Current state (v0 — "minimal + flow control")

### Done
- LLM-driven decision every task completion (~500 token input, ~150 token output)
- Heuristic fallback when no LLM configured (uses retry counts)
- `note` action: deduped append to team_notes.md
- `escalate` action: scheduler bails out before `_maybe_trigger_qa_rework` and
  `_maybe_finalize`. Issue stays `in_progress`, failed node stays failed. User
  must take manual action via DAG retry / steer / abandon.
- `conductor_decision` event on every round (dock UI feedback)
- Frontend banner on `IssueDetailPage`: shows for 60s when action ∈
  {note, escalate}, with manual dismiss
- Toast on note / escalate

### Deferred (next iterations)

| # | Deferred item | Why deferred | Sketch of full version |
|---|---|---|---|
| 1 | **Trigger gating** — don't burn LLM on every round | Each round = 1 LLM call (~$0.003 Sonnet, ~$0.0003 Haiku). Cheap but wasteful. | Deterministic prefilters: skip when `retries==0 && terminal==done`; only fire when (a) same exit-code pattern repeats, (b) engineer diff between rounds is empty, (c) retry approaching max, (d) total runtime > threshold |
| 2 | **Per-agent prompt nudge** | Conductor can write team-wide notes but can't say "next time QA runs, inject this hint" | Add `agent_hint: {role, inject}` to decision; scheduler stitches the hint into that specific task's review_comment / prompt before dispatch |
| 3 | **Historical context in snapshot** | Sees only current round; can't tell "engineer changed nothing this rework cycle" | Snapshot adds `recent_rounds: [{role, status, exit_codes, diff_summary}]` for last 2-3 cycles |
| 4 | **DAG awareness** | Knows node statuses but not "X more tasks until done" | Pass `dag_pending: [node_keys]` + edge topology summary |
| 5 | **Model tiering** | Uses same Auto-plan LLM (Sonnet-class) for trivial proceed decisions | Haiku 4.5 for the 90% `proceed` cases; promote to Sonnet only when heuristic flags trouble |
| 6 | **Prompt caching** | Each call sends full system prompt | Anthropic cache_control on the persistent guidance block; 80% discount when triggered within 5min TTL |
| 7 | **Retry on transient LLM failure** | Single attempt, falls through to heuristic on first error | Retry once with exponential backoff; only fall through after 2 attempts |
| 8 | **AgentDock conductor tile binding** | Dock's conductor visual still uses old `conductorPhase` from plan-time agentBus; doesn't react to runtime `conductor_decision` events | Wire `useAgentStatus.ts` to also consume `lastEvent.conductor_decision` and show "thinking…/noted/⚠ paused" states |
| 9 | **Pause UI affordance** | When escalated, only the banner shows. User has to figure out they should go to DAG tab and retry manually. | Add an "Acknowledge & resume" action on the banner that calls scheduler.settle, or a "Force engineer rework anyway" button that overrides the escalation |
| 10 | **Auto-distill team_notes** | Conductor notes accumulate forever; team_notes.md grows. We have `project_memory.maybe_distill` for issue summaries but it doesn't touch Conductor-authored lines | Distill Conductor notes separately (or together with issue summaries) after every N additions, dedupe overlapping conventions |
| 11 | **Multi-issue learning** | Notes are per-project repo. No cross-project memory. | Optional global notes file or workspace-shared store |
| 12 | **Sample efficiency** | We send a fresh snapshot every call. If `proceed → proceed → proceed` for 3 rounds, the LLM has no idea | Either keep a short rolling memory buffer (last 3 decisions) injected into the prompt, or use the Memory Tool API |
| 13 | **Conductor for plan-time** | Plan-first PM gate currently has no Conductor involvement (it's just a hard pause) | Conductor could review the PM PRD itself and decide if it's good enough to auto-approve, or call out specific gaps to the user |
| 14 | **Conductor for clarification triage** | When an agent emits `clarification_question`, Conductor could pre-answer from team_notes / issue context instead of always escalating to the user | Adds an "auto-answer if confident" path before surfacing to the approvals inbox |

### Open questions

- Should `escalate` carry an explicit `next_actions` list (e.g. "try `cd frontend && npm test`")? Right now the user reads the reason text.
- Should there be a separate Conductor LLM identity that the user can configure (different model than Auto-plan)?
- When Conductor writes a note, should it auto-tag with the issue id so we can later filter "notes derived from issue X"?

---

## Operating notes

- Every task completion triggers one LLM call. For an issue running PM→Architect→Engineer→QA cleanly, that's 4 calls. With one QA-rework cycle, ~6 calls. ~$0.02 per issue on Sonnet, ~$0.002 on Haiku.
- The supervisor is fully isolated behind try/except — any failure inside the supervisor is logged at DEBUG and the scheduler continues. The workflow does not have a hard dependency on Conductor being healthy.
- Set `CONDUCTOR_ENABLED=false` in the backend env to disable entirely while keeping the rest of the system unchanged.
