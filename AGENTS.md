<!-- TRELLIS:START -->
# Trellis Instructions

These instructions are for AI assistants working in this project.

This project is managed by Trellis. The working knowledge you need lives under `.trellis/`:

- `.trellis/workflow.md` — development phases, when to create tasks, skill routing
- `.trellis/spec/` — package- and layer-scoped coding guidelines (read before writing code in a given layer)
- `.trellis/workspace/` — per-developer journals and session traces
- `.trellis/tasks/` — active and archived tasks (PRDs, research, jsonl context)

If a Trellis command is available on your platform (e.g. `/trellis:finish-work`, `/trellis:continue`), prefer it over manual steps. Not every platform exposes every command.

If you're using Codex or another agent-capable tool, additional project-scoped helpers may live in:
- `.agents/skills/` — reusable Trellis skills
- `.codex/agents/` — optional custom subagents

Managed by Trellis. Edits outside this block are preserved; edits inside may be overwritten by a future `trellis update`.

<!-- TRELLIS:END -->

## Error Handling & Defensive Programming Rules

This project has a history of over-defensive code written by AI agents. The patterns below are **banned** unless explicitly justified with a comment explaining why.

### 1. Fail-Closed, Not Fail-Open

When a governance gate (budget check, concurrency limit, rework cap) encounters an error, it MUST **refuse the action**, not silently allow it.

```python
# WRONG — bug in gate silently disables all limits
try:
    budget_ok = await check_budget(issue)
except Exception:
    return None  # "no problem" → dispatch proceeds unchecked

# RIGHT — gate failure = action denied
try:
    budget_ok = await check_budget(issue)
except Exception:
    logger.error("budget gate failed, refusing dispatch", exc_info=True)
    return {"error": "budget_check_unavailable"}
```

### 2. No `getattr` on Typed Model Fields

Never use `getattr(obj, "field", default)` on Pydantic BaseModel / dataclass / TypedDict fields that are declared in the schema. Access them directly. If the field doesn't exist, you WANT the AttributeError — the default hides the bug.

```python
# WRONG
role = getattr(task, "role", None)  # task.role is declared with default "general"

# RIGHT
role = task.role
```

### 3. Distinguish System Boundaries from Internal Code

**Only validate at boundaries:**
- User input (HTTP request bodies, query params)
- External API responses
- File/DB reads of untyped data (raw JSON, legacy rows)

**Trust internal contracts:**
- Function-to-function calls with typed signatures
- Pydantic-validated model fields
- Context values from typed React contexts (they throw if missing)

### 4. No Broad `except Exception` in Internal Logic

If code is pure computation (arithmetic, dict access, string ops), it doesn't need try/except. If you wrap a single fallible call, catch only what it can raise.

```python
# WRONG — wraps 15 lines of infallible code to protect one .record() call
try:
    duration_ms = int((time.monotonic() - started) * 1000)
    status = "error" if error else "ok"
    sink.record(category, actor="git", duration_ms=duration_ms, status=status)
except Exception:
    logger.debug("recording failed")

# RIGHT — only wrap what can fail
duration_ms = int((time.monotonic() - started) * 1000)
status = "error" if error else "ok"
try:
    sink.record(category, actor="git", duration_ms=duration_ms, status=status)
except Exception:
    logger.warning("audit record failed", exc_info=True)
```

### 5. No Silent `.catch(() => {})` in Frontend

Every caught error must either:
- Show a user-visible error state (toast, error banner, fallback UI)
- Re-throw to a boundary that handles it
- Log AND set an error state variable

```typescript
// WRONG — user sees empty page, no indication of failure
getIssueData(id).then(setData).catch(() => {});

// RIGHT — error state drives UI feedback
getIssueData(id).then(setData).catch((e) => {
  console.error("Failed to load issue", e);
  setError("Failed to load issue data");
});
```

### 6. No Destructive Error Recovery

On transient errors (network blip, timeout), NEVER clear previously loaded data. Stale data > empty screen.

```typescript
// WRONG — error wipes user's view
.catch(() => { setLogs([]); setMessages([]); })

// RIGHT — keep stale data, show error indicator
.catch((e) => { setLoadError(e.message); })
```

### 7. No Redundant Nullish Guards on Non-Optional Types

If TypeScript says `items: Thing[]` (not `Thing[] | undefined`), do not add `?? []` or `|| []`. If you feel the need, fix the type declaration instead.

```typescript
// WRONG — items is required in the prop type
const list = props.items ?? [];

// RIGHT — trust the type, access directly
const list = props.items;
```

### 8. No Double Validation Across Layers

If the route validates a precondition, the service layer should trust it (or vice versa). Pick one owner. Don't load the same entity from DB twice in one call chain.

### 9. No `Object.values()` on Arrays

`Object.values(arr)` on an array is a no-op identity transform that allocates a new array for nothing. If you see it, the type is probably wrong upstream — fix the type, not the callsite.

### Why These Rules Exist

AI agents writing code in this project tend toward "never crash" over "fail fast." This creates invisible degradation: governance gates silently disable, context silently drops, errors silently vanish. The user sees "it works" while budget limits aren't enforced, agents run without memory, and pages show stale/empty data with no error. **A loud crash you can debug is better than a silent failure you discover in production costs.**
