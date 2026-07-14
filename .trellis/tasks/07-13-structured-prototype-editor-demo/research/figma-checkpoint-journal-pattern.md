# Figma Checkpoint and Journal Pattern

## Scope

This note records the parts of Figma's published architecture that support the structured prototype storage decision. It does not claim access to Figma's current private schema, file format, or complete implementation.

## Official Evidence

Figma's engineering articles describe a broad three-part persistence pattern:

- A live file is held in the Multiplayer service's memory while it is active.
- Full file checkpoints are serialized in a compact binary representation, compressed, and stored in S3 roughly every 30 to 60 seconds.
- Incremental edits are batched into a sequence-numbered journal stored in DynamoDB.
- Recovery loads the latest checkpoint and applies journal entries after the checkpoint's sequence number.
- Product metadata such as users, projects, and comments is stored separately in relational storage.

The articles also make clear that durable journal records are not individual browser mouse events. Clients communicate frequently, while server persistence batches incremental changes.

## Sources

- [Making multiplayer more reliable](https://www.figma.com/blog/making-multiplayer-more-reliable/)
- [How Figma's multiplayer technology works](https://www.figma.com/blog/how-figmas-multiplayer-technology-works/)
- [Inside Figma: a case study on solving the deep search problem](https://www.figma.com/blog/deep-search/)

Sources were reviewed on 2026-07-13.

## Design Consequences

1. Use in-memory active state for editing latency, but treat it as reconstructible cache.
2. Keep a gap-free monotonic command journal in SQLite rather than rewriting a complete SQLite JSON value for every edit.
3. Store complete compressed checkpoints as immutable managed objects and recover from checkpoint plus bounded journal tail.
4. Persist one final semantic move command for a drag gesture, not every mousemove.
5. Keep workflow metadata, sequence allocation, idempotency, object references, and errors in SQLite.
6. Do not copy Figma's multiplayer/CRDT assumptions into the MVP; this product remains single-active-draft and uses optimistic concurrency.
