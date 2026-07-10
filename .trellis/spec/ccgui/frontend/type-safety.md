# Type Safety

> Type safety patterns in the ccgui frontend package.

---

## Overview

The frontend is **TypeScript strict mode** with `noUncheckedIndexedAccess`,
`exactOptionalPropertyTypes`, `noImplicitReturns`,
`noUnusedLocals`, `noUnusedParameters`, `noUncheckedSideEffectImports`,
`noPropertyAccessFromIndexSignature`, `allowUnusedLabels: false`,
`allowUnreachableCode: false`, and `noImplicitOverride` enabled. Types are
colocated with their owner:

- **Cross-feature domain types** (a `CodexIssue`, a `RuntimeCatalog`, a
  `PipelineStage`) live in `frontend/src/lib/types.ts`. The shape is
  declared once and re-imported everywhere.
- **Feature-local types** (a panel's row shape, a hook's return tuple)
  live next to the file that owns them.
- **API response types** are declared at the call site in
  `frontend/src/lib/api.ts` and re-imported by consumers, not duplicated.
- **Dictionary keys** are inferred from the `dictionaries` object in
  `frontend/src/lib/i18n.ts`. New keys flow through TypeScript narrowing
  automatically — there is no separate "key type" to maintain.

---

## Type Organization

### Domain types → `lib/types.ts`

- One exported `interface` per record, snake_case fields to match the
  FastAPI response.
- Optional fields use `?` and a `| null` only when the backend actually
  sends `null` (not when it omits the field).
- Enums and literal unions (`"issue" | "default"`,
  `"product_manager" | "architect" | "engineer" | "qa"`) are spelled
  out — no `enum` keyword, the project uses string-literal unions.
- Comment headers explain non-obvious semantics (e.g.
  `remaining_usd: number | null` is `null` ONLY when the issue has no
  ceiling, never when spend is zero).

### API client → `lib/api.ts`

- One exported function per endpoint. Return type is the exact shape
  the backend serializes.
- Failure is encoded as `T | null` for endpoints that the UI wants to
  degrade silently (the budget endpoint is one example), or as a
  thrown error for endpoints that must surface failures.
- `dedupedFetch` (in `lib/api.ts`) handles in-flight deduplication; do
  not roll your own cache.
- When a monolithic API function is split into `lib/api/<domain>.ts`,
  preserve any existing `@/lib/api` import surface with a **narrow**
  explicit re-export. Do not use broad `export *` from every domain
  module inside `lib/api.ts`; it can collide with local monolithic
  definitions and create ambiguous build-time exports.

### Hook return types

- Hooks return **named tuples** (`{ data, loading, refresh }`), not
  positional arrays. Callers destructure by name.
- Async hooks that fetch on mount return `loading: true` until the
  first response lands; they do not return `undefined` for "not yet
  fetched". The discriminated state is intentional.

---

## Validation

**The backend is the source of truth for shape.** The frontend trusts
`frontend/src/lib/types.ts` and does not run a runtime schema check on
every fetch.

The exception is **user input** (form fields, query strings, command
palette input). Use a small Zod schema at the boundary if the input
flows into a typed call. Most inputs are short-lived UI state and do
not need schema validation.

`JSON.parse` of untrusted strings (e.g. log events) uses
`safeJsonParse` (in `lib/utils.ts`), not `JSON.parse` directly.
Unknown object payloads use `isRecord(...)` or a feature-local guard before
indexing. Do not assert runtime data with broad shapes such as
`as Record<string, unknown>`, `as { data?: unknown }`, or
`as { type?: string }`; add a narrow guard and keep the unsafe edge visible.

---

### Scenario: Runtime JSON Boundary Helpers

#### 1. Scope / Trigger

- Trigger: parsing runtime strings from logs, artifacts, skill imports,
  audit payloads, task results, browser storage, or streamed messages.
- These strings are user-editable, backend-generated, or transport-owned. A
  direct `JSON.parse(...)` in a component can throw during render or make a
  malformed payload look typed.

#### 2. Signatures

- `safeJsonParse(input: string) -> unknown | null`.
- `safeJsonRecord(input: string) -> Record<string, unknown> | null`.
- Feature-local parsers for domain payloads, such as
  `frontend/src/features/issues/issueResultParsing.ts` and
  `frontend/src/features/workbench/qaReportStatus.ts`.
- Source-hygiene test:
  `frontend/tests/sourceHygiene.test.ts`, test name
  `runtime JSON parsing goes through shared helpers`.

#### 3. Contracts

- Runtime `src/**/*.ts(x)` code does not call `JSON.parse(...)` directly,
  except the shared helper implementation and the inline app boot script that
  cannot import modules before hydration.
- Use `safeJsonParse(...)` when arrays, strings, numbers, or booleans are valid
  payloads; use `safeJsonRecord(...)` when the caller needs an object.
- Components do not cast parsed payloads into a domain type. Add a
  feature-local parser or literal guard, then return a narrowed value.
- Components and helpers do not cast parsed payloads to
  `Record<string, unknown>` just to index them. Use `isRecord(...)`,
  `safeJsonRecord(...)`, or a feature-local record guard first.
- Repeated parsing rules, such as issue result sections or QA report status,
  live next to the owning feature and have node tests.

#### 4. Validation & Error Matrix

- Malformed JSON -> helper returns `null`; caller falls back or drops the
  payload.
- Valid JSON of the wrong container type -> `safeJsonRecord(...)` returns
  `null`.
- Unknown literal status, role, action, or result variant -> feature guard
  returns `null` or a safe fallback.
- Direct `JSON.parse(...)` in runtime source outside the allowlist ->
  source-hygiene test fails.
- Broad object assertions such as `as Record<string, unknown>` or
  `as { data?: unknown }` in runtime source -> source-hygiene test fails.

#### 5. Good/Base/Bad Cases

- Good: `const parsed = safeJsonRecord(task.result);`.
- Base: `readQaReportStatus(artifacts)` hides corrupt or unknown QA statuses.
- Bad: `const parsed = JSON.parse(task.result) as QAReportDocument;`.

#### 6. Tests Required

- Add or update helper tests for malformed JSON, wrong container type, unknown
  literals, and the fallback behavior the UI depends on.
- Run `cd frontend && node --import tsx --test tests/sourceHygiene.test.ts`
  and `cd frontend && npm run typecheck`.

---

### Scenario: Budget Steering Event Payload Parsing

#### 1. Scope / Trigger

- Trigger: changing `useIssueBudget`, budget meter live updates, or backend
  `budget_warning` / `budget_exceeded` event payloads.
- Budget steering events are WS/event-bus payloads, not full REST endpoint
  responses. They must be parsed at the event boundary instead of cast into
  `IssueBudgetStatus`.

#### 2. Signatures

- Hook: `useIssueBudget(issueId: string, isActive: boolean) -> { budget, loading, refresh }`.
- Parser: `readBudgetSteeringEvent(event: unknown) -> IssueBudgetStatus | null`.
- Backend event type literals: `"budget_warning" | "budget_exceeded"`.
- Required event fields:
  - `type: "budget_warning" | "budget_exceeded"`
  - `issue_id: string`
  - `spent_usd: number`
  - `budget_usd: number`
  - `remaining_usd: number | null`
  - `used_ratio: number | null`
  - `budget_source: "issue" | "default"`
- Warning-only field: `soft_warn_ratio: number` is required for
  `budget_warning`.
- Exceeded events may omit `soft_warn_ratio`; the parser normalizes it to `1`.

#### 3. Contracts

- Do not cast event payloads with `event as IssueBudgetStatus`.
- Parse `unknown` payloads with field-level guards and return `null` for invalid
  shape or wrong primitive types.
- `budget_warning` normalizes to `soft_warn=true`, `over_budget=false`.
- `budget_exceeded` normalizes to `soft_warn=true`, `over_budget=true`.
- Extra backend fields such as `reserved_usd` and `effective_spend_usd` are
  allowed but ignored by the meter parser.
- The live-update path must preserve monotonic spend behavior: stale lower
  `spent_usd` events must not regress a newer polled snapshot.

#### 4. Validation & Error Matrix

- Unknown `type` -> parser returns `null`.
- Missing or non-string `issue_id` -> parser returns `null`.
- Non-number `spent_usd` / `budget_usd` -> parser returns `null`.
- `remaining_usd` / `used_ratio` not `number | null` -> parser returns `null`.
- `budget_warning` without numeric `soft_warn_ratio` -> parser returns `null`.
- `budget_exceeded` without `soft_warn_ratio` -> parser returns a valid
  `IssueBudgetStatus` with `soft_warn_ratio=1`.

#### 5. Good/Base/Bad Cases

- Good: `readBudgetSteeringEvent(event)` narrows and normalizes before calling
  `setBudget`.
- Base: polling `getIssueBudget(...)` still fetches full endpoint shape every
  30s while the issue is active.
- Bad: `const evt = event as IssueBudgetStatus & { type: string };` followed by
  `evt.soft_warn_ratio ?? 0.8`.

#### 6. Tests Required

- Node tests in `frontend/tests/defensiveProgrammingCleanup.test.ts` for:
  - representative `budget_warning` backend event;
  - representative `budget_exceeded` backend event without `soft_warn_ratio`;
  - malformed event rejection.
- Source-hygiene assertion that the hook calls `readBudgetSteeringEvent(event)`
  and does not cast the raw event to `IssueBudgetStatus`.
- Run `cd frontend && node --import tsx --test tests/defensiveProgrammingCleanup.test.ts`
  plus `npm run typecheck` and `npm run lint` for hook changes.

#### 7. Wrong vs Correct

Wrong:

```tsx
const evt = event as IssueBudgetStatus & { type: string };
setBudget({
  ...evt,
  soft_warn_ratio: evt.soft_warn_ratio ?? 0.8,
  has_ceiling: evt.has_ceiling ?? true,
});
```

Correct:

```tsx
const next = readBudgetSteeringEvent(event);
if (!next) return;
setBudget((prev) => (prev && next.spent_usd < prev.spent_usd ? prev : next));
```

---

### Scenario: Typed Stream Event Payload Parsing

#### 1. Scope / Trigger

- Trigger: adding or changing `EventSource` / SSE handlers or WebSocket
  `onmessage` handlers that read `event.data`, especially prototype generation
  streams or execution-process log/message streams.
- Stream payloads are untrusted strings at the UI boundary. Casting
  `JSON.parse(event.data) as SomeShape` makes malformed frames look typed and
  spreads duplicate parse/try/catch code across handlers.

#### 2. Signatures

- Generic JSON helper: `safeJsonParse(input: string) -> unknown | null` in
  `frontend/src/lib/utils.tsx`.
- Object guard: `isRecord(value: unknown) -> value is Record<string, unknown>`
  in `frontend/src/lib/utils.tsx`.
- Prototype SSE helper:
  `frontend/src/features/prototype/prototypeStreamEvents.ts`.
- Execution-process WebSocket frame helper:
  `frontend/src/hooks/executionProcessStreamFrames.ts`.
- Global/workspace execution-process stream frame helper:
  `frontend/src/hooks/executionProcessesStreamFrames.ts`.
- Prototype source-hygiene test:
  `frontend/tests/sourceHygiene.test.ts`, test name
  `prototype SSE UI parses event data through typed helpers`.
- Execution-process stream source-hygiene test:
  `frontend/tests/sourceHygiene.test.ts`, test name
  `execution process stream hooks parse frames through typed helpers`.

#### 3. Contracts

- Component SSE handlers do not call `JSON.parse(...)` directly.
- Parse `event.data` once with `parseSseRecord(event)` or an equivalent
  feature-local helper, then narrow each field with string/number/array guards.
- WebSocket stream hooks parse raw frames through pure frame parsers that
  returns a discriminated union (`finished`, `delta`, `heartbeat`, `log`,
  `message`, `control`, `unknown`, etc.) before mutating React state.
- Global event-bus envelopes preserve `event_id` / `resume_gap` semantics in
  the parser output; workspace patch streams validate `JsonPatch` operations
  and `Events` log rows before applying patches or invoking callbacks.
- Malformed optional progress frames are dropped without failing the whole
  stream; terminal frames still close the `EventSource` when the previous
  behavior did so.
- Feature-specific payload shapes that include domain types, such as
  regenerate-all `failed` prototype items, need a type guard that validates
  required fields before returning the domain type.
- Keep generated/transport constants and typed URL builders in
  `frontend/src/lib/api/<domain>.ts`; keep SSE event-shape narrowing next to
  the consuming feature unless a second feature imports it.

#### 4. Validation & Error Matrix

- Direct `JSON.parse(...)` in `frontend/src/features/prototype/**` outside the
  SSE helper -> source-hygiene test fails.
- Direct `JSON.parse(...)` in execution-process stream hooks ->
  source-hygiene test fails.
- Invalid JSON, array JSON, empty event data, or non-object JSON -> parse helper
  returns `null`; the handler drops the frame.
- Required field missing or wrong primitive type -> field reader returns
  `null` / `undefined`; the handler drops the frame.
- Unknown literal union members on feature-specific SSE frames, or malformed
  regenerate-all `failed` items -> the corresponding guard returns `null`.
- Terminal `all_done` malformed -> close the one-shot stream and mark progress
  done when that matches the previous lifecycle behavior.

#### 5. Good/Base/Bad Cases

- Good: `const data = parseSseRecord(ev); const count = data ? readSseNumber(data, "count") : null;`.
- Base: feature-local helper validates a domain-specific payload before a
  component updates state.
- Bad: `const data = JSON.parse((ev as MessageEvent).data) as { count: number };`.

#### 6. Tests Required

- Add or update node tests for the payload helper, including malformed JSON,
  wrong primitive types, literal-union rejection, and aggregate summaries.
- Add or update node tests for WebSocket frame parsers, including control
  frames, malformed message frames, deltas, heartbeats, and log/message rows.
- Add or update node tests for global/workspace stream parsers, including
  ping envelopes, resume gaps, event IDs, patch operations, log event rows, and
  malformed frames.
- Run `cd frontend && node --import tsx --test tests/sourceHygiene.test.ts`
  for prototype SSE changes.
- Run frontend `npm run typecheck`, `npm test`, `npm run lint`, and
  `npm run format:check` after changing SSE helpers or consumers.

#### 7. Wrong vs Correct

Wrong:

```tsx
source.addEventListener("done", (ev) => {
  const data = JSON.parse((ev as MessageEvent).data) as { version_no: number };
  setActiveVersion(data.version_no);
});
```

Correct:

```tsx
source.addEventListener("done", (ev) => {
  const data = parseSseRecord(ev);
  const versionNo = data ? readSseNumber(data, "version_no") : null;
  if (versionNo === null) return;
  setActiveVersion(versionNo);
});
```

---

### Scenario: Browser Storage JSON Narrowing

#### 1. Scope / Trigger

- Trigger: reading JSON from `localStorage`, `sessionStorage`, URL-migrated
  storage state, or other browser-owned persisted strings.
- Browser storage is user-editable and can contain stale data from older
  releases. A direct `JSON.parse(...)` can break hydration, sorting, or render
  paths before React has a chance to recover.

#### 2. Signatures

- `safeJsonParse(input: string) -> unknown | null`.
- `safeJsonRecord(input: string) -> Record<string, unknown> | null`.
- `safeJsonStringArray(input: string) -> string[] | null`.
- `safeJsonNumberRecord(input: string) -> Record<string, number> | null`.
- Storage source-hygiene tests live in `frontend/tests/sourceHygiene.test.ts`.

#### 3. Contracts

- Runtime components do not merge raw `JSON.parse(...)` output into typed state.
- Storage arrays such as recent searches or favorites use
  `safeJsonStringArray(...)`.
- Storage maps used for sorting or timestamps use `safeJsonNumberRecord(...)`;
  non-number values are ignored.
- Preference objects use `safeJsonRecord(...)` plus field-level guards for
  literal unions and booleans before applying DOM attributes or React state.
- Inline boot scripts that cannot import helpers keep preference parsing inside
  an inner `try/catch` so corrupt preferences do not prevent theme setup.

#### 4. Validation & Error Matrix

- Malformed storage JSON -> helper returns `null`; caller falls back to its
  default value.
- JSON of the wrong container type, such as an object where a string array is
  expected -> helper returns `null`.
- Mixed arrays, such as `["a", 1]` for recent searches -> helper returns
  `null`; caller falls back to `[]`.
- Number maps with extra bad values -> valid numeric entries are preserved and
  invalid values are dropped.
- Invalid preference literal, such as `fontSize: "huge"` -> default preference
  value is used for that field.

#### 5. Good/Base/Bad Cases

- Good: `safeJsonStringArray(stored) ?? []` for recent-search storage.
- Base: `safeJsonNumberRecord(stored) ?? {}` for project MRU ordering.
- Bad: `{ ...DEFAULT_PREFERENCES, ...JSON.parse(stored) }`.

#### 6. Tests Required

- Add or update `frontend/tests/utils.test.ts` for new storage helper behavior.
- Update source-hygiene tests when a storage reader must use a specific helper.
- Run `npm run typecheck`, `npm test`, `npm run lint`, `npm run build`, and
  `npm run format:check` for storage code that affects hydration or app chrome.

#### 7. Wrong vs Correct

Wrong:

```ts
const stored = window.localStorage.getItem("recent");
return stored ? JSON.parse(stored) : [];
```

Correct:

```ts
const stored = window.localStorage.getItem("recent");
return stored ? (safeJsonStringArray(stored) ?? []) : [];
```

---

## Common Patterns

### Narrow compatibility re-exports for split API modules

When moving a function from `frontend/src/lib/api.ts` to a domain
module, first search for existing imports from `@/lib/api`. If callers
still use the monolithic entrypoint, add an explicit compatibility
re-export for only the missing symbols:

```ts
export {
  getEmbeddingStatus,
  searchKnowledge,
} from "./api/knowledge";
export type { EmbeddingStatus } from "./api/knowledge";
```

Do not paper over missing exports with a catch-all barrel:

```ts
// Wrong: risks duplicate exports with functions still defined below.
export * from "./api/knowledge";
export * from "./api/tasks";
export * from "./api/projects";
```

**Why**: A broad barrel can introduce duplicate names such as
`getCodexTask` or `listProjects`, while missing compatibility exports
surface as runtime errors like `getEmbeddingStatus is not a function`.

**Check**: Search for the symbol and its import site:

```bash
rg -n "getEmbeddingStatus|from \"@/lib/api\"" frontend/src
```

Confirm the monolithic entrypoint exports the symbol exactly once.

### Exact optional properties

With `exactOptionalPropertyTypes` enabled, `field?: T` means the field can be
omitted; it does not mean callers may write `field: undefined`. Use this
distinction deliberately:

- Request payload builders should omit absent optional fields with conditional
  object construction, for example `...(value !== undefined ? { value } : {})`.
- Component or hook props that intentionally pass through an `undefined` value
  should declare that explicitly as `prop?: T | undefined`.
- API/domain response types should only include `| undefined` when the frontend
  really receives or propagates an explicit `undefined`. Backend-omitted fields
  stay as plain optional properties, and backend `null` stays `| null`.

### Static imports for split API modules

Runtime feature code imports split API modules statically:

```ts
import { submitCodexTask } from "@/lib/api/tasks";
```

Do not dynamically destructure split API modules from runtime code:

```ts
// Wrong: source-contract checks can miss missing exported names here.
const { submitCodexTask } = await import("@/lib/api/tasks");
```

**Why**: The project had runtime failures such as
`getEmbeddingStatus is not a function` after API functions moved between the
monolithic barrel and split modules. Static named imports are visible to the
split API export-contract test and fail earlier than a browser-only dynamic
chunk path.

**Check**: `frontend/tests/sourceHygiene.test.ts` rejects runtime dynamic
imports matching `import("@/lib/api/<domain>")`. If a split API call genuinely
needs lazy loading, add a documented exception and extend the contract test to
verify the destructured names.

### Scenario: Split API request helpers

#### 1. Scope / Trigger

- Trigger: adding or changing a function in `frontend/src/lib/api/*.ts` that
  performs a normal JSON request and should throw on non-OK responses.

#### 2. Signatures

- `apiRequest<T>(url, init?) -> Promise<T>` for ordinary requests.
- `apiDedupedRequest<T>(url, init?) -> Promise<T>` for GETs that should share
  the existing short-window dedupe behavior.
- `apiRequestOr<T>(url, fallback, { dedupe?, init?, errorMessage? }) ->
  Promise<T>` for read-only UI endpoints that intentionally degrade to
  `[]`, `null`, `{}`, or another typed fallback instead of throwing.
- `apiJsonRequest<T>(url, method, body) -> Promise<T>` for JSON request bodies.
- `jsonRequestInit(method, body) -> RequestInit` when a caller needs the init
  object separately.

#### 3. Contracts

- These helpers live in `frontend/src/lib/api/fetch.ts` and delegate error
  normalization to `handleResponse<T>()`.
- `apiJsonRequest()` always sends `Content-Type: application/json` and
  `JSON.stringify(body)`.
- `apiRequestOr()` preserves soft-failure contracts without duplicating
  `fetch` branches in domain modules. Use `dedupe: true` when the old code
  used `dedupedFetch`, and pass `errorMessage` when the old code logged a
  status-specific diagnostic.
- Split API modules may still build URLs locally; the helper owns the fetch
  plus response handling, not endpoint path construction.

#### 4. Validation & Error Matrix

- `response.ok === true` -> parse and return `response.json()` as `T`.
- FastAPI `{detail: [...]}` errors -> throw the formatted
  `loc: message` string from `formatApiErrorDetail()`.
- HTML/text fallback errors -> keep `handleResponse()` behavior.
- Empty `204` / `205` responses -> return `undefined as T` so
  `apiRequest<void>()` works for no-content endpoints.

#### 5. Good/Base/Bad Cases

- Good: `createProject()` uses `apiJsonRequest<Project>(url, "POST", body)`.
- Base: `getCodexIssue()` uses `apiDedupedRequest<CodexIssue>(url)` because
  issue detail can be requested by several panels at once.
- Bad: `deleteSkillCategory()` uses `apiRequest<void>()` and loses its raw
  response text error message on failed deletes.

#### 6. Tests Required

- Add or update API tests that mock `globalThis.fetch` and assert URL, method,
  headers, and body for new JSON helpers.
- Keep a direct helper test for `apiJsonRequest()`, FastAPI validation errors,
  soft-failure fallbacks, and GET dedupe behavior.
- When leaving raw `fetch`, cover or document the special response behavior
  (`[]`, `null`, text, CSV, or custom status handling).

#### 7. Wrong vs Correct

Wrong:

```ts
const response = await fetch(`${API_BASE}/projects`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});
return handleResponse<Project>(response);
```

Correct:

```ts
return apiJsonRequest<Project>(`${API_BASE}/projects`, "POST", body);
```

Keep raw `fetch` only when the raw `Response` is the contract, such as
CSV/text exports or a custom status-code protocol:

```ts
const response = await fetch(url);
if (response.status === 409) return unwrapRefusal(await response.json());
return handleResponse<ProjectRunStatus>(response);
```

For typed soft-failure reads, prefer the fallback helper:

```ts
return apiRequestOr<Item[]>(url, [], {
  dedupe: true,
  errorMessage: (status) => `loadItems failed: HTTP ${status}`,
});
```

### Narrowing with type guards

```ts
function isIssueBudgetStatus(value: unknown): value is IssueBudgetStatus {
  return (
    typeof value === "object" &&
    value !== null &&
    "issue_id" in value &&
    "spent_usd" in value
  );
}
```

### Discriminated unions for variant payloads

```ts
type BudgetEvent =
  | { type: "budget_warning"; payload: IssueBudgetStatus }
  | { type: "budget_exceeded"; payload: IssueBudgetStatus };
```

### `import("./types").Foo` for one-off imports in `lib/api.ts`

`lib/api.ts` is consumed by many features. Local type imports with the
inline `import("./types").Foo` form avoid a circular dependency with
`features/...` that also import from `lib/types.ts`.

### `as const` on API response enum fields

When the backend returns a string-literal field that the frontend
narrows on, the type uses the exact union — not `string`. The type
then drives exhaustive switches in the consumer.

---

## Forbidden Patterns

- **`any`.** The `no-explicit-any` ESLint rule is enforced. The only
  legitimate use is bridging a third-party type we cannot influence
  (none currently); in that case narrow as soon as possible.
- **`as` casts to silence a type error.** `as unknown as Foo` is a
  smell — figure out the real shape. `as const` is fine; `as Foo` on a
  fetch result is not.
- **`@ts-ignore` / `@ts-expect-error`** — only with a comment
  explaining why and a tracking TODO. The build will warn on either.
- **Optional chaining on already-non-null values.** `foo?.bar` when
  `foo` is `string` is a noise. Trim it.
- **Inferring `T` from a hook's `useState<T | null>`** and treating the
  `null` as "data missing" for unrelated reasons. Each hook defines
  what `null` means in its return type; do not invent a new meaning.
- **Loose `Record<string, any>` for API responses.** Use the typed
  shape from `lib/api.ts` (or `lib/types.ts` for shared domain types).
  A loose record disables the value of TypeScript entirely.

---

## Scenario: Project Script Task Response Typing

### 1. Scope / Trigger

- Trigger: changing `ProjectScriptTaskResponse`, `startProjectScriptTask`, or the Projects page Operations Engineer startup-script button.

### 2. Signatures

- API client: `startProjectScriptTask(projectId, body) -> Promise<ProjectScriptTaskResponse>`.
- Frontend type: `ProjectScriptTaskResponse`.
- Required response fields: `task_id`, `status`, `title`, `reused`.
- Optional nullable field: `execution_process_id?: string | null`.

### 3. Contracts

- `reused` is a required boolean. The backend always serializes it, using `false` for a fresh task and `true` for an active reused task.
- Frontend code must branch on `task.reused` directly, not treat absence as false.
- Terminal handling must still track the returned `task_id`; reused tasks do not relax task-id-specific matching.

### 4. Validation & Error Matrix

- `reused=true` -> show already-running copy and keep tracking returned `task_id`.
- `reused=false` -> show started copy and keep tracking returned `task_id`.
- Missing `reused` in mock fixtures -> update the fixture; do not make the type optional.

### 5. Good/Base/Bad Cases

- Good: Projects page receives `{ task_id, status: "running", title, reused: true }` and displays the already-running toast.
- Base: Fresh task response has `reused: false` and emits running status separately over websocket.
- Bad: `reused?: boolean` lets tests and components forget the reused branch.

### 6. Tests Required

- Source/API compatibility test: `ProjectScriptTaskResponse.reused` remains required.
- Projects source test: both `scriptSuggestionSuccess` and `scriptSuggestionAlreadyRunning` copy paths are wired.

### 7. Wrong vs Correct

Wrong:

```ts
export interface ProjectScriptTaskResponse {
  reused?: boolean;
}
```

Correct:

```ts
export interface ProjectScriptTaskResponse {
  reused: boolean;
}
```
