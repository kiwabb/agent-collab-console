# Type Safety

> Type safety patterns in the vibe-kanban frontend package.

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
