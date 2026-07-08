# Logging Guidelines

> How logging is done in the vibe-kanban backend package.

---

## Overview

The backend uses the **stdlib `logging` module** (no loguru,
no structlog). Loggers are module-level
(`logger = logging.getLogger(__name__)`), configured by a single
root-level setup that runs at app startup. There is exactly one
log destination: stdout / a rotating file (configured by the
deployment harness, not the application).

The project's logging philosophy is:

- **Log the boundary, not the body.** Service-internal happy paths
  are quiet; cross-process, cross-network, or cross-conductor
  events are loud.
- **Structured enough to grep, prose enough to read.** A log line
  is a human sentence with the structured fields appended. JSON
  is reserved for the audit log (see `app/audit/`).
- **One log line per boundary crossing.** A conductor iteration
  that calls 5 services emits at most 5 log lines, one per
  external effect (LLM call, dispatch, merge, event emission).
  Internal state changes do not log.

---

## Log Levels

| Level | When to use |
|-------|------------|
| `DEBUG` | Per-iteration conductor state, every dispatched subagent prompt, every persisted row. **Off by default** in production. The `LOG_LEVEL=DEBUG` env flag turns it on. |
| `INFO` | One line per external effect: a task started, a task completed, a budget steering event fired, an issue was pinned. This is the default level. |
| `WARNING` | A recoverable problem the operator should know about: a stale lease recovered, a soft-warn threshold hit, a transient Git failure that retried successfully. The system continues. |
| `ERROR` | An operation failed and the failure is meaningful to the user: a dispatch failed and the task is in `failed`, a merge conflict, an audit-log sink write failed. The exception is logged with `logger.exception(...)`. |
| `CRITICAL` | Reserved for the rare case the supervisor itself cannot continue: the conductor loop crashed, the store is unrecoverable. |

A new log statement should fit one of those five. "I want to
print a variable" → `logger.debug(...)`. "I want to know the
request was accepted" → `logger.info(...)`. "Something is
wrong" → `logger.warning(...)` if recoverable,
`logger.error(...)` if not.

---

## Structured Logging

Stdlib logging only. The project does not require a JSON log
sink in production (the deployment harness is free to add one
without changing the application code). When a log line needs
to be machine-parseable, **the message string includes the
fields inline**:

```python
logger.info(
    "conductor iteration: issue_id=%s turn=%d phase=%s",
    issue.id, turn, phase,
)
```

This is a single line, machine-parseable, and readable in a
terminal. The audit log (`app/audit/`) is a separate concern
and IS structured — it persists JSON rows to the `audit_log`
table.

Do not use f-strings in `logger.debug/info/warning/error/exception`
calls under `backend/app`. Keep interpolation lazy by passing
`%s` / `%d` placeholders plus arguments; the source-hygiene test
rejects logger calls whose first argument is an f-string.

### Required fields per log line

- An **identifier** (issue id, task id, run id, agent name) is
  always present in the message. The first arg to `logger.info`
  is always `f"... issue_id=%s ..." % (issue_id,)` or the
  `%`-formatting equivalent.
- The **exception** is logged via `logger.exception(...)` (not
  `logger.error(..., exc_info=True)`). It is reserved for
  `ERROR` / `CRITICAL` lines, never `INFO`.

---

## What to Log

- **Issue / task / run lifecycle transitions** at `INFO`.
- **Budget steering events** (`budget_warning`, `budget_exceeded`)
  at `WARNING` (the operator should see the soft-warn even on a
  happy path).
- **Conductor loop turn boundaries** at `DEBUG` (off in
  production).
- **External CLI invocations** (codex / claude) at `INFO` with
  the executor name and the issue id.
- **WS event emissions** at `DEBUG`.
- **Audit log sink failures** at `ERROR` with `exc_info`.

---

## What NOT to Log

- **API keys, OAuth tokens, or any credential material.** Never
  log a request body that includes an `Authorization` header,
  and never log the contents of an env var whose name ends in
  `_KEY`, `_TOKEN`, `_SECRET`, or `_PASSWORD`.
- **Full LLM prompts in production.** The prompt body is logged
  at `DEBUG` and gated behind the `LOG_LLM_PROMPTS=1` env flag.
  The audit log captures the prompt hash, not the body, for the
  regular case.
- **User PII from issue / task content.** The console is an
  internal product and we control the data, but defensively: do
  not log full issue titles or descriptions at `INFO`. A short
  slug or id is fine.
- **File contents read from disk.** A `git diff` is logged at
  `DEBUG` only; a `git log` is logged at `INFO` as a SHA list,
  not a full message body.
- **Stdlib `print(...)`.** All console output goes through
  `logger`. A `print` in a service module is a CI failure
  waiting to happen.

---

## Gotchas

- **Stdout, not stderr, by default.** The deployment harness
  reads stdout for the application log and stderr for crash
  traces. The application does not pick which stream to write
  to; the harness does. `logger.info` writes to stdout, the
  unhandled exception handler writes to stderr.
- **`uvicorn --reload` noise.** When the dev server is in
  reload mode, the import log can be loud. Filter `uvicorn.*`
  to `WARNING` in `dev-local.sh` if it's drowning out real
  output.
- **Async context + logging.** The stdlib logger is
  thread-safe; the call sites in async coroutines are safe to
  use as-is. There is no project-specific `AsyncLogger`.
- **Correlation across boundaries.** There is no built-in
  correlation id. The convention is to include `issue_id` in
  every line emitted while servicing a single request — the
  reviewer can grep for it and reconstruct the flow.
