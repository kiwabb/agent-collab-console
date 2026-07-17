# Cross-Layer Thinking Guide

> **Purpose**: Think through data flow across layers before implementing.

---

## The Problem

**Most bugs happen at layer boundaries**, not within layers.

Common cross-layer bugs:
- API returns format A, frontend expects format B
- Database stores X, service transforms to Y, but loses data
- Multiple layers implement the same logic differently

---

## Before Implementing Cross-Layer Features

### Step 1: Map the Data Flow

Draw out how data moves:

```
Source → Transform → Store → Retrieve → Transform → Display
```

For each arrow, ask:
- What format is the data in?
- What could go wrong?
- Who is responsible for validation?

### Step 2: Identify Boundaries

| Boundary | Common Issues |
|----------|---------------|
| API ↔ Service | Type mismatches, missing fields |
| Service ↔ Database | Format conversions, null handling |
| Backend ↔ Frontend | Serialization, date formats |
| Component ↔ Component | Props shape changes |

### Step 3: Define Contracts

For each boundary:
- What is the exact input format?
- What is the exact output format?
- What errors can occur?

---

## Common Cross-Layer Mistakes

### Mistake 1: Implicit Format Assumptions

**Bad**: Assuming date format without checking

**Good**: Explicit format conversion at boundaries

### Mistake 2: Scattered Validation

**Bad**: Validating the same thing in multiple layers

**Good**: Validate once at the entry point

### Mistake 3: Leaky Abstractions

**Bad**: Component knows about database schema

**Good**: Each layer only knows its neighbors

---

## Checklist for Cross-Layer Features

Before implementation:
- [ ] Mapped the complete data flow
- [ ] Identified all layer boundaries
- [ ] Defined format at each boundary
- [ ] Decided where validation happens

After implementation:
- [ ] Tested with edge cases (null, empty, invalid)
- [ ] Verified error handling at each boundary
- [ ] Checked data survives round-trip

### Checklist: Continuous Editor Geometry to Persisted Fields

- [ ] Distinguish transient control/aggregate geometry from persisted entity fields. A selection
  union may legally exceed one field's limit even when every member is valid.
- [ ] Put explicit minimum and maximum constraints on the shared projection input; do not assume a
  container bound is also the persistence-format bound.
- [ ] Define the numeric handoff from continuous preview values to canonical storage precision,
  including a tolerance smaller than half the smallest persisted unit.
- [ ] Normalize machine-precision tails before preview and command construction, but reject any
      meaningful out-of-range value. Do not rely on serialization to repair editor state.
- [ ] When multiple snap systems compete, generate every candidate from the same continuous raw
      frame and define one deterministic priority. Never feed one snap result into another solver.
- [ ] For independent X/Y snapping, recheck any cross-axis lane/collision requirement against the
      combined final frame. A candidate that was valid only before the other axis moved must fall
      back without leaving a stale guide.
- [ ] If X/Y candidates invalidate each other only after combination, define a stable single-axis
      retry order (smaller correction, explicit tie-break, alternate, then raw/alignment) instead
      of dropping both opportunistically.
- [ ] Keep local spacing arithmetic separate from absolute canvas-coordinate tolerance. A logical
      zero gap must remain alignment, and the winning target, recorded gap, rendered segments, and
      committed correction must satisfy one executable invariant.
- [ ] Benchmark adversarial editor geometry, not only normal distributions. Repeated candidate
      queries inside RAF work need exact semantic cache keys or a spatial index; avoid a hidden
      pair-enumeration times full-scan path.
- [ ] Test every handle/modifier combination with no-op, constrained nonzero, overflow-recovery,
  aggregate-wider-than-field, and deterministic high-volume boundary cases.

**Real-world example**: Structured-prototype Resize initially limited the transient group union to
the document's per-node `4096` field cap. That rejected valid groups whose children were each
canonical but whose union was wider than one node field. After separating per-child size limits,
aspect/center arithmetic still produced values such as `4096.000000000001`, so preview succeeded
but command encoding failed. The stable contract derives group limits from every child, permits a
wider transient union, normalizes only relative-`1e-9` tails in Resize projection, and leaves
Move/Nudge measured geometry unchanged.

---

## Structured Model Output and Durable Live Workflows

Model streams and recoverable background work add two boundaries that ordinary
request/response checks do not cover: **proof of completion** and **durable
reconciliation**.

### Checklist: Before Repairing Model Output

- [ ] Decide what proves completion: an explicit provider terminal event, a
  complete single JSON envelope, or a validated staged artifact
- [ ] Keep large artifacts in files/object storage; keep final model text to a
  small typed manifest whenever the artifact can exceed one response budget
- [ ] Distinguish incomplete output from repairable syntax drift before calling
  a tolerant parser; repair must never invent missing terminal structure
- [ ] Run the strict domain schema, reference-integrity checks, and locale/content
  rules after any boundary repair
- [ ] Treat EOF without the required terminal event as failure, even when the
  accumulated text looks complete
- [ ] Test token-limit truncation, open strings/containers, prose/fences,
  concatenated objects, and provider-specific valid repair cases separately

### Checklist: Before Exposing Recursive Schemas as Agent Tools

- [ ] Run the exact schema through the configured Claude executor and provider;
  a local JSON Schema or Pydantic unit test does not prove the tool adapter
  preserves recursive arrays, discriminated unions, or referenced definitions
- [ ] Inspect the persisted wire input when a model repeats validation errors;
  distinguish model-authored invalid data from provider/tool-schema coercion
- [ ] If the adapter cannot preserve a recursive object, transport one complete
  JSON serialization in a bounded string and parse it once at the MCP boundary
- [ ] Hash the original tool arguments, retain the raw trajectory, and store the
  parsed canonical object separately so repair remains observable and replayable
- [ ] Normalize only allowlisted, lossless boundary drift and record exact field
  paths; refuse wrappers that discard elements, add fields, or require synthesis
- [ ] Add a real provider smoke test for context lookup, finalization, terminal
  process evidence, strict validation, and canonical object-store persistence

**Real-world example**: A recursive structured-prototype page schema passed
Pydantic and MCP descriptor tests, but one configured Claude provider encoded
`children` first as `{"item": [...]}` and later as `{"item": ["", ""]}`.
Unwrapping the first shape could be lossless; the second had already destroyed
node content and had to fail. Moving only page finalization to a bounded
`payloadJson` string prevented the tool adapter from interpreting the recursive
union, while the backend still parsed strict JSON and applied the same schema.

### Checklist: Before Adding Live Recovery

- [ ] Persist the complete user-visible snapshot and lifecycle counters; React
  state is a cache, not the workflow owner
- [ ] Put stable resource identity and contract version on snapshots and
  heartbeats, then reject cross-resource frames before state mutation
- [ ] Define one status/phase/counter matrix and validate it at the frontend
  transport boundary instead of reinterpreting status in each component
- [ ] Detect silence as well as socket errors; an open buffered SSE connection
  is not evidence of freshness
- [ ] Bound polling by attempts and elapsed time, reset the budget only after a
  valid heartbeat/snapshot or explicit user retry, and expose exhaustion
- [ ] Preserve the last valid snapshot and unsaved draft on transport failures
- [ ] Test partial terminal runs where failures count as processed, refresh,
  disconnect, silence, resource mismatch, polling failure, and exhaustion

### Checklist: Before Shipping a Persistence Change

- [ ] Separate SQL defaults from semantic defaults; non-null does not mean valid
- [ ] Backfill new required values from durable historical data in the same
  versioned migration
- [ ] Fail startup when a retryable/governed legacy row cannot be reconstructed;
  do not silently invent evidence, seeds, ownership, or budget state
- [ ] Move shared-state idempotence into the store transaction; service-local
  locks are only an optimization and do not protect multiple instances
- [ ] Test an old schema with meaningful rows, not only an empty database

**Real-world example**: Project-driven prototype generation initially returned
HTML and planning JSON through model text, used a service-local lock, and let
the UI derive progress. Token truncation, tolerant repair, a second SQLite
connection, legacy empty defaults, and buffered SSE exposed different symptoms
of the same missing completion/durability contracts. The stable design stages
HTML as an artifact, proves one complete planning envelope before repair,
freezes generation in SQLite, migrates semantic values, and reconciles typed
persisted snapshots through heartbeat plus bounded polling.

## Repository-Backed Agent Autonomy

Before building a prompt for an agent that already has an isolated repository
worktree:

- [ ] Pass the task identity, target resources, output contract, and safety
      boundary; let the agent search and follow the real dependency graph.
- [ ] Keep static scans, source paths, hashes, evidence, and large project
      context on the server as integrity guards or query tools instead of
      serializing them into the prompt.
- [ ] Make the prompt builder accept explicit agent-facing fields rather than a
      whole internal request object, so guard data cannot leak back in later.
- [ ] Fail closed when the repository-capable runtime is unavailable; do not
      fall back to a model path that cannot inspect the repository.
- [ ] Add negative prompt assertions for source paths, hashes, frozen briefs,
      unrelated routes, and arbitrary inspection-call limits.
- [ ] Capture the actual runtime wire input, not only the stored task prompt;
      managed prompt builders, project memory, team notes, and transport framing
      can otherwise inject context after the prompt unit test passes.
- [ ] Validate the final file and source tree, never the agent's Write/Edit/Bash
      sequence. Tool logs are an implementation trace, not artifact evidence.
- [ ] Persist the complete Agent trajectory: raw stream frames, thinking, tool
      inputs/outputs, commands, assistant messages, results/HTML, status, and
      audit traces. Preserve raw frames even when task identity is unresolved.
- [ ] Keep observability and artifact authority separate. Logs may contain the
      complete HTML but must never be replayed, reconstructed, or accepted as
      evidence that the staged artifact succeeded.

The executable prototype contract is in
`.trellis/spec/vibe-kanban/backend/database-guidelines.md`, under
"Project-Evidence Prototype Plans and Generation Runs".

---

## Cross-Platform Template Consistency

In Trellis, command templates (e.g., `record-session.md`) exist in **multiple platforms** with identical or near-identical content. This is a cross-layer boundary.

### Checklist: After Modifying Any Command Template

- [ ] Find all platforms with the same command: `find src/templates/*/commands/trellis/ -name "<command>.*"`
- [ ] Update all platform copies (Markdown `.md` and TOML `.toml`)
- [ ] For Gemini TOML: adapt line continuations (`\\` vs `\`) and triple-quoted strings
- [ ] Run `/trellis:check-cross-layer` to verify nothing was missed

**Real-world example**: Updated `record-session.md` in Claude to use `--mode record`, but forgot iFlow, Kilo, OpenCode, and Gemini — caught by cross-layer check.

---

## Generated Runtime Template Upgrade Consistency

Some generated files are both documentation and runtime input. In Trellis,
`.trellis/workflow.md` is parsed by `get_context.py`, `workflow_phase.py`,
SessionStart filters, and per-turn hooks. Template changes must be validated
against both fresh init and upgrade paths.

### Checklist: After Modifying A Runtime-Parsed Template

- [ ] Identify every runtime parser that reads the template, not just the file
  writer that installs it
- [ ] Check whether relevant syntax lives outside obvious managed regions
  such as tag blocks
- [ ] Verify fresh `init` output and a versioned `update` scenario that writes
  the older `.trellis/.version`
- [ ] Add an upgrade regression using an older pristine template fixture, then
  assert the installed file reaches the current packaged shape
- [ ] Update the backend spec that owns the runtime contract

**Real-world example**: Codex inline mode changed workflow platform markers from
`[Codex]` / `[Kilo, Antigravity, Windsurf]` to `[codex-sub-agent]` /
`[codex-inline, Kilo, Antigravity, Windsurf]`. Fresh init was correct, but
`trellis update` only merged `[workflow-state:*]` blocks and preserved stale
markers outside those blocks. Result: upgraded projects got new hook scripts
but old workflow routing, so `get_context.py --mode phase --platform codex`
could return empty Phase 2.1 detail.

---

## Mode-Detection Probe Checklist

When a CLI auto-detects a mode by probing a remote resource (e.g., checking if `index.json` exists to decide marketplace vs direct download):

### Before implementing:
- [ ] Probe runs in **ALL** code paths that use the result (interactive, `-y`, `--flag` combos)
- [ ] 404 vs transient error are distinguished — don't treat both as "not found"
- [ ] Transient errors **abort or retry**, never silently switch modes
- [ ] Shared state (caches, prefetched data) is **reset** when context changes (e.g., user switches source)
- [ ] **Shortcut paths** (e.g., `--template` skipping picker) must have the same error-handling quality as the probed path — check that downstream functions don't call catch-all wrappers

### After implementing:
- [ ] Trace every path from probe result to the mode-decision branch — no fallthrough
- [ ] External format contracts (giget URI, raw URLs) are tested or at least documented as comments
- [ ] Metadata reads consume a complete response or use a streaming parser — never parse a fixed-size prefix as full JSON
- [ ] When reconstructing a composite identifier from parsed parts, verify **all** fields are included and in the **correct position** (e.g., `provider:repo/path#ref` not `provider:repo#ref/path`)
- [ ] Verify that **action functions** called after a shortcut don't internally use the old catch-all fetch — they must use the probe-quality variant when error distinction matters

**Real-world example**: Custom registry flow had 8 bugs across 3 review rounds: (1) probe only ran in interactive mode, (2) transient errors fell through to wrong mode, (3) giget URI had `#ref` in wrong position, (4) prefetched templates leaked across source switches, (5) `--template` shortcut bypassed probe but `downloadTemplateById` internally used catch-all `fetchTemplateIndex`, turning timeouts into "Template not found".

**Real-world example**: Agent-session update hints fetched npm `latest` metadata with `response.read(4096)` and then parsed it as complete JSON. The `@mindfoldhq/trellis` package metadata exceeded 4 KB, so the JSON was truncated, parse failed silently, and the first session injection showed no update hint. Fix: read the complete response before parsing, and add a regression where `version` is followed by an 8 KB metadata tail.

---

## When to Create Flow Documentation

Create detailed flow docs when:
- Feature spans 3+ layers
- Multiple teams are involved
- Data format is complex
- Feature has caused bugs before
