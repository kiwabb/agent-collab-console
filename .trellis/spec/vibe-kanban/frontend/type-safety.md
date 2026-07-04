# Type Safety

> Type safety patterns in the ccgui frontend package.

---

## Overview

The frontend is **TypeScript strict mode** with `noUncheckedIndexedAccess`
and `noImplicitOverride` enabled. Types are colocated with their owner:

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
