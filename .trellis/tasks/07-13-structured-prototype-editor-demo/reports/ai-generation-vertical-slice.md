# AI Generation Vertical Slice

Date: 2026-07-14

## Completed

- Requirements generation invokes the project-bound Claude Code
  `prototype_ui_engineer`; there is no generic LLM fallback.
- The user-confirmed blueprint gates foundation and page generation.
- Blueprint, foundation, and page runs use isolated worktrees, fresh durable
  task/process identities, frozen context hashes, strict MCP finalization, and
  managed content-addressed object storage.
- Recursive page artifacts use bounded `payloadJson` transport so the provider
  tool adapter cannot reinterpret the page node union. The backend parses JSON,
  performs allowlisted observable normalization, and then applies strict
  Pydantic and procurement assembly constraints.
- The service deterministically assembles the three procurement pages, replays
  the scripted applicant/manager approval scenario, renders a preview, writes a
  replay manifest, and exposes a candidate only after all checks pass.
- Accept atomically creates the document, active sequence-0 draft, immutable
  generation checkpoint, object references, and operation completion evidence.

## Real Acceptance Evidence

- Successful generation job: `96161aec-5e3c-5e71-ba93-08a03d22f2ad`
- Pages: `purchase-list`, `purchase-create`, `purchase-detail`; all `done`
- Page MCP validation retries: zero for all three successful page tasks
- Candidate/document hash:
  `sha256:52a084f7f7adc657c6aa62f5b2ee36a66662a255879afb65d2da8ece07a5b0ed`
- Preview output hash:
  `sha256:2492a5f373c67059b2fa1b14566d7e0dd86fb1a907b1cdb8820709c0dab8a467`
- Generation replay manifest:
  `sha256:b0c5881ce80f4d432ba28ab1f67d91be089377796fcfb09888b880ad0f3038d4`
- Preview `index.html`: HTTP 200, 5,274 bytes
- Document: `47941524-bbc1-5856-a9e3-b77d6c9f496e`
- Draft: `b334a5f6-0350-53c9-82e7-10db6d577d80`, head sequence 0
- Checkpoint: `6c453fd7-f90e-5863-b74c-46f1efbac68e`
- Checkpoint object hash equals candidate/document hash.
- Root generation operation completed as `succeeded` with a terminal result
  manifest hash.

## Failure Comparison Evidence

- Job `72b5fe3b-d7f2-59fe-a325-51606465e188` proved direct recursive object
  submission could repeatedly wrap `children` as `{item: [...]}`.
- Job `3d07576f-f49f-56bf-a1cc-97a6acc6d6f4` proved the adapter could further
  reduce child objects to empty strings. The backend refused to synthesize the
  lost nodes and the job remained failed.
- The successful job used page prompt/protocol
  `structured-prototype-generation/v2` and completed each page with one accepted
  finalization call.

## Verification

- Full structured-prototype backend suite: 98 passed.
- Targeted Ruff: passed.
- Backend import smoke: passed.
- Real browser-facing preview read: HTTP 200.

## Follow-on Completion

- Claude conversational edit proposal, isolated preview, Apply, and Reject are
  implemented and verified with real Claude execution.
- Immutable publication, share route, and runnable published preview are
  implemented.
- Project-current recovery and the generation review UI now connect this
  backend pipeline to Studio without manually seeded browser IDs. See
  `reports/generation-studio-integration.md`.
