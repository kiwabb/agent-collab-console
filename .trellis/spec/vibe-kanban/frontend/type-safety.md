# Type Safety

> Type safety patterns in this project.

---

## Overview

<!--
Document your project's type safety conventions here.

Questions to answer:
- What type system do you use?
- How are types organized?
- What validation library do you use?
- How do you handle type inference?
-->

(To be filled by the team)

---

## Type Organization

<!-- Where types are defined, shared types vs local types -->

(To be filled by the team)

---

## Validation

<!-- Runtime validation patterns (Zod, Yup, io-ts, etc.) -->

(To be filled by the team)

---

## Common Patterns

<!-- Type utilities, generics, type guards -->

### Scenario: API Error Detail Parsing

#### Scope / Trigger

- Trigger: changing `frontend/src/lib/api.ts` response handling or adding frontend wrappers around FastAPI endpoints.
- FastAPI may return `detail` as a string, array of validation errors, object, or omit it.

#### Required Pattern

- Treat parsed error JSON as `unknown` until narrowed.
- Preserve string `detail` values directly.
- For validation arrays, render each item with `loc` and `msg` when present, joined with `; `.
- Fall back to `HTTP <status>` when the detail shape is unknown or empty.

#### Forbidden Pattern

- Do not cast `detail` to `string` without runtime narrowing. FastAPI 422 arrays stringify to `[object Object]`, hiding the actual validation error.

---

## Forbidden Patterns

<!-- any, type assertions, etc. -->

(To be filled by the team)
