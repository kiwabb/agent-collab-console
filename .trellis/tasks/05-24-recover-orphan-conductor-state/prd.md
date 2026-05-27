# fix: recover orphan conductor state

## Goal

Make Conductor status management truthful and recoverable when the backend process reloads, crashes, or loses the in-memory conductor coroutine. A task must not remain indefinitely in `running / awaiting_llm` after its runner has disappeared.

## What I Already Know

* Observed issue `12b81f91-7465-421a-9816-db7c7683b6e7` stayed at `running / awaiting_llm`.
* The last persisted turn was a second-round `llm_request`; there was no later `llm_response`, `error`, or `finalize`.
* Backend logs showed `StatReload detected changes in 'app/interfaces/api.py'. Reloading...` immediately after that turn.
* After reload, the active worker process had no outbound LLM socket, so the database was stale rather than actively waiting on MiniMax.
* Existing code already has startup orphan recovery for execution processes and a task stall watchdog, but no equivalent durable Conductor runner lease.

## Requirements

* Add a durable Conductor runner lease/heartbeat contract so a `running` conductor task can be distinguished from an orphaned database row.
* Use a precise terminal/system status for lost runners. Prefer `stalled` over `failed`, because losing the backend coroutine is an operational failure, not a failed product task.
* On backend startup, recover any orphaned running conductor tasks whose lease is expired or whose runner owner cannot exist in the new process.
* Add a periodic watchdog scan while the backend is running, so stalled conductor tasks are detected without waiting for another restart.
* Preserve normal running conductors that have a fresh heartbeat.
* Preserve paused/done/failed tasks.
* Persist a useful reason in the conductor payload/result so UI/API can explain what happened.
* Emit the existing conductor status event when a task is marked stalled.
* Do not auto-replay or auto-dispatch agents in this task. Manual restart/resume can be a later feature.

## Acceptance Criteria

* [ ] Regression tests prove an expired/orphaned `running / awaiting_llm` conductor task becomes `stalled`.
* [ ] Regression tests prove a fresh lease is not marked stalled.
* [ ] Regression tests prove paused and terminal tasks are not touched.
* [ ] `run_issue_conductor_loop` updates the heartbeat while a live loop progresses.
* [ ] Startup runs the conductor orphan recovery.
* [ ] A periodic conductor watchdog runs alongside the existing task stall watchdog.
* [ ] Relevant backend tests pass.

## Definition of Done

* Tests added before implementation and observed failing.
* Backend unit tests pass for conductor state management.
* No unrelated frontend files are modified.
* Existing uncommitted work is preserved.

## Out of Scope

* Auto-resuming a lost conductor loop.
* Retrying the LLM request automatically.
* Re-dispatching agents automatically.
* Changing the frontend visual design beyond consuming clearer backend status already returned by the API.

## Technical Notes

* Likely files:
  * `backend/app/domain/models.py`
  * `backend/app/adapters/async_sqlite_store.py`
  * `backend/app/adapters/sqlite_store.py`
  * `backend/app/application/conductor_main_loop.py`
  * new or existing watchdog module under `backend/app/application/`
  * `backend/app/main.py`
  * tests under `backend/tests/`
* Prefer a small service module for recovery logic so startup, watchdog, and tests share the same implementation.
