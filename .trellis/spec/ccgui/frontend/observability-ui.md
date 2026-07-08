# Observability UI

> Frontend contracts for rendering raw audit evidence, semantic Agent Timeline
> operations, and trace details.

---

## Scenario: Audit Log vs Agent Timeline UI Contract

### 1. Scope / Trigger

- Trigger: changing `frontend/src/features/audit/**`,
  `frontend/src/lib/api/audit.ts`, or any UI that presents audit rows, Agent
  Timeline operations, or trace details.
- The UI must keep two concepts separate:
  - **Audit log** is the raw evidence table/list.
- **Agent Timeline** is the human-readable execution view built from backend
    `/api/codex/agent-timeline`.
- Do not make the timeline by regrouping flat audit rows in the component. The
  backend owns semantic projection and status merging.

### 2. Signatures

- API client:
  - `getAuditLog(params) -> Promise<AuditLogPage>`
  - `getAuditLogChains(params) -> Promise<AuditLogChainPage>` legacy only.
  - `getAgentTimeline(params) -> Promise<AgentTimelinePage>`
  - `getBestAuditTrace(entry) -> Promise<AuditTraceDetail | AuditTraceCollection>`
- Timeline response type:
  - `AgentTimelineOperation`
  - `AgentTimelinePage`
- Required timeline fields:
  - `id`
  - `timeline_kind`
  - `event_type`
  - `title`
  - `summary`
  - `result`
  - `status`
  - `status_source`
  - `execution_process_id`
  - `trace_id`
  - `span_id`
  - `parent_span_id`
  - `entries`

### 3. Contracts

- The view switch must describe the two surfaces as separate concepts:
  - `auditLog.view.flat` -> Audit log / 审计日志.
  - `auditLog.view.chain` -> Agent Timeline.
- Local state and new code should use timeline naming
  (`timelineOperations`, `timelineNextCursor`, `AgentTimelineOperation`) rather
  than `chain*` names. Historical `AuditLogChainOperation` aliases may remain
  for compatibility but should not drive new feature names.
- Top-level Agent Timeline cards represent one agent execution, not one raw
  semantic event. `cli_spawn` and `project_script_updated` from the same
  execution should appear as entries/steps inside one card.
- `task_status` rows are not rendered as top-level Agent Timeline operations.
  If present in `entries`, they are evidence only.
- Timeline cards should prioritize human business meaning:
  - `project_script_updated` shows `result.run_command` /
    `result.setup_script`.
  - `cli_spawn` shows executor/model/cwd/pid rather than raw argv JSON.
  - Raw payload is hidden by default for known semantic rows and only appears as
    fallback detail.
- Status display must use semantic labels:
  - success -> `auditLog.roleChain.summary.success`
  - failure -> `auditLog.roleChain.summary.failed`
  - active -> `auditLog.roleChain.summary.running`
  - unknown -> neutral text
- Status color cannot be the only signal. Keep text labels visible while using
  `status-done`, `status-failed`, or `status-awaiting` tokens.
- Operation details should show business `result` first, then supporting
  evidence rows and Trace.
- Trace controls for known semantic steps should live on the step row. In
  particular, `cli_spawn` should expose an expandable runtime process showing
  persisted Claude Code messages and log events.
- `getBestAuditTrace(entry)` should prefer row-level trace detail before falling
  back to trace-wide collections. This prevents every operation button from
  showing the same full runtime transcript.
- User-visible strings for audit/timeline must exist in:
  - `frontend/src/lib/i18n.ts`
  - `frontend/src/lib/i18n/zh-CN.ts`
  - `frontend/src/lib/i18n/en-US.ts`

### 4. Validation & Error Matrix

- `/agent-timeline` request fails -> show existing audit-log error banner with
  the thrown message.
- Empty timeline response -> show the shared empty state, not a raw JSON dump.
- Trace detail unavailable -> show trace unavailable copy with the reason.
- Unknown `timeline_kind` -> render title/summary/status neutrally and keep raw
  evidence available in the expanded details.
- Missing `result` -> use `summary`; do not crash or show `undefined`.
- Missing `execution_process_id` -> omit execution meta; do not infer it from
  task id in the UI.

### 5. Good/Base/Bad Cases

- Good: an Operations Engineer timeline card reads "Generate Startup Scripts"
  or the localized task label, and shows "启动命令：docker compose up" before
  evidence rows containing "启动 Claude CLI" and "项目启动脚本已更新".
- Good: expanding a card shows audit evidence rows and a Trace button, but raw
  payload is folded/hidden for known semantic events.
- Base: an older audit row without structured `result` still shows a usable
  backend-provided summary.
- Bad: separate top-level cards for "启动 Claude CLI" and "项目启动脚本已更新"
  when both rows belong to the same execution.
- Bad: a top-level timeline card titled `task_status`.
- Bad: rendering `MiniMax-M3` twice because model is used as both title and
  metadata.
- Bad: deriving timeline groups in React from `getAuditLog()` items.

### 6. Tests Required

- Frontend typecheck must cover `AgentTimelinePage` and
  `AgentTimelineOperation` response fields.
- Component/source tests should assert the page calls `getAgentTimeline()` for
  timeline mode, not `getAuditLogChains()` or `getAuditLog()`.
- i18n parity/source tests must include all audit/timeline keys in zh-CN and
  en-US dictionaries.
- Pure helper tests should cover status label/class mapping for success,
  failure, active, and unknown statuses when the mapping is extracted.
- Browser/manual check: an Operations Engineer script generation timeline shows
  `CLI 启动` and `项目启动脚本已更新`, while `task_status` stays out of the top-level
  list.

### 7. Wrong vs Correct

#### Wrong

```tsx
const page = await getAuditLog({ ...filters });
setTimelineOperations(groupAuditRowsInReact(page.items));
```

#### Correct

```tsx
const page = await getAgentTimeline({ ...filters });
setTimelineOperations(page.items);
```

#### Wrong

```tsx
<span>{operation.status}</span>
```

Raw status values such as `ok`, `done`, and `responding` are backend evidence,
not user-facing product copy.

#### Correct

```tsx
const label = operationStatusLabel(operation.status, t);
return label ? <span>{label}</span> : null;
```

#### Wrong

```tsx
<DetailBlock label="raw" value={entry.payload_json} />
```

Showing raw payload first makes semantic events unreadable.

#### Correct

```tsx
const result = operationResultMeta(operation, t);
return result ? <BusinessResultBanner>{result}</BusinessResultBanner> : null;
```
