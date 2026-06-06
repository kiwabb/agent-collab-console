# brainstorm: coordinator source-informed upgrade

## Goal

Upgrade this project's ProjectConductor so it behaves like a stronger coding-work coordinator: it should preserve project context, choose the right serial vs parallel workflow shape, delegate with focused prompts, recover from common subagent failure states, and finish with a useful summary. The work should be informed by the local Claude Code sourcemap and Codex CLI source references without copying their product-specific implementation.

## What I already know

* User asked to study `references/claude-code-sourcemap` and `references/codex-cli`.
* The coordinator implementation is primarily in `backend/app/application/conductor_main_loop.py` and `backend/app/application/conductor_tools.py`.
* The current system already supports tool-use orchestration, `dispatch_subagent`, `dispatch_batch`, role concurrency limits, budget-aware fan-out downscaling, conductor pause/resume, user interjections, heartbeat leases, and per-agent worktree isolation.
* `run_issue_conductor_loop` tries to load project memory with `ProjectConductor._load_state()`, but `ProjectConductor` exposes `get_or_create_state()` instead. Because the call is wrapped in a broad exception handler, project context is silently omitted from the issue coordinator prompt.
* Codex CLI's model prompts emphasize scoped repository instructions, autonomy/persistence, concise user updates, high-quality planning only when warranted, safe editing, dirty-worktree awareness, and validation.
* Claude Code's SDK tool surface exposes explicit task spawning fields: description, prompt, specialized subagent type, optional model, background execution, named teammates, permission mode, and worktree isolation. The useful transferable idea is making delegation intent and execution constraints explicit.

## Assumptions

* "协调者" refers to the backend ProjectConductor issue loop, not only the project-level ask endpoint or frontend conductor monitor.
* The first implementation should be a focused backend behavior upgrade, not a wholesale orchestration rewrite.
* The project should keep the existing tool protocol and database model unless the research uncovers a blocker.

## Requirements

* Fix project memory injection so the issue coordinator actually receives pinned team notes and recent warm summaries.
* Replace the monolithic conductor prompt with a clearer, source-informed operating contract.
* Preserve existing tool names and schemas so current API/UI behavior remains compatible.
* Make the prompt explicitly teach the coordinator when to use `dispatch_batch` versus serial `dispatch_subagent`.
* Make delegation prompts more disciplined: include goal, constraints, expected artifact/result, prior context, and verification expectation when relevant.
* Make failure handling explicit for `artifact_invalid`, `role_busy`, `retries_exhausted`, QA failure, and merge conflict results.
* Keep budget guidance, language guidance, user interjection handling, and `finalize_task` requirement.
* Add or update focused backend tests that verify prompt construction behavior and project memory injection.

## Acceptance Criteria

* [x] A test proves pinned project context and recent warm summaries are injected into the issue conductor prompt.
* [x] A test proves the conductor prompt contains the new operating contract for planning, delegation, parallelism, failure recovery, and finalization.
* [x] Existing conductor loop/tool tests still pass for the changed area.
* [x] No tool schema compatibility break is introduced.
* [x] The implementation avoids unrelated refactors.

## Definition of Done

* Tests added/updated for the coordinator prompt behavior.
* Relevant backend tests pass.
* Trellis check is run before completion.
* Spec update decision is made before wrap-up.

## Out of Scope

* No new database tables for conductor decisions.
* No new frontend conductor UI in this task.
* No new external LLM/provider integration.
* No copying Claude Code or Codex CLI source into this project.
* No redesign of subagent runtime execution or worktree merge mechanics unless required by tests.

## Technical Notes

* Current prompt is assembled inline in `backend/app/application/conductor_main_loop.py`.
* Tool definitions live in `backend/app/application/conductor_tools.py`.
* Relevant tests include `backend/tests/test_conductor_main_loop.py`, `backend/tests/test_run_issue_conductor_loop.py`, `backend/tests/test_conductor_budget_injection.py`, and `backend/tests/test_conductor_budget_steering_injection.py`.
* Research notes live in `research/source-informed-coordinator-patterns.md`.
* Verification run: `PYTHONPATH=backend backend/.venv/bin/python -m pytest backend/tests/test_run_issue_conductor_loop.py backend/tests/test_conductor_budget_injection.py backend/tests/test_conductor_budget_steering_injection.py backend/tests/test_conductor_main_loop.py backend/tests/test_conductor_dispatch_batch.py backend/tests/test_dispatch_batch_budget_concurrency.py -q` -> 41 passed.
* Verification run: `PYTHONPATH=backend backend/.venv/bin/python -c "from app.main import app; print('import ok')"` -> import ok.
* Verification run: `git diff --check` -> passed.

## Research References

* `research/source-informed-coordinator-patterns.md` - transferable coordination patterns from Codex CLI prompts and Claude Code task tool schemas.
