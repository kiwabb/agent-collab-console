# Real-time Artifact Architecture

**Date**: 2026-04-27
**Status**: COMPLETED

## 1. Background
Currently, the system relies on synchronous database writes for streaming output, and reconstructs large artifacts (like PRDs) from SQLite logs at the end of a task. This causes IO bottlenecks during typing and massive latency when fetching artifacts.

## 2. Objective
Adopt a "MetaGPT-like" architecture:
- Send streaming fragments to the frontend with zero DB latency (Async Persistence).
- Intercept the final JSON result in memory and write directly to the workspace file system (In-Memory Artifact Capture).

## 3. Plan Phases

### Phase 1: Asynchronous Persistence for Streaming
- **Component**: `EventBus`
- **Action**: Modify `EventBus` to push events to WebSocket immediately, while queuing DB inserts (`log_store.save_log_event`) in a background asyncio task/worker.
- **Goal**: Zero-latency UI response during typing.

### Phase 2: In-Memory Artifact Capture
- **Component**: `CodexAppServerRuntime` & `ProductManagerService`
- **Action**: Intercept `item/completed` (with `final_answer`) directly from `stdout`.
- **Action**: Extract the JSON content in memory and write directly to `workspace/issues/<id>/prd.md` synchronously.
- **Goal**: Instant artifact availability without SQLite query overhead.

### Phase 3: API & Frontend Cleanup
- **Component**: `api.py`
- **Action**: Remove `_refresh_task_result()` fallback logic from the GET endpoints.
- **Goal**: Serve files natively; remove legacy DB reconstruction logic.

## 4. Current Task
Start with Phase 1: Asynchronous Persistence for Streaming.
