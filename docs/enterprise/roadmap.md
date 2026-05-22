# Enterprise Hardening Roadmap

## Objective

Make Agent Collaboration Console dependable enough for serious team use: easy to run, clear to operate, safe by default, observable during agent work, and protected by repeatable quality gates.

## Milestone 1: Repository Trust

Goal: a new engineer can clone the repo, follow current docs, run checks, and understand what is intentionally local-only.

Deliverables:

* Current README with accurate ports and startup commands.
* Working or explicitly scoped Docker/compose files.
* `.gitignore` coverage for local databases, runtime sessions, caches, and machine-local config.
* CI workflow for backend tests and frontend typecheck/test/lint.
* Enterprise roadmap committed under `docs/enterprise/`.

## Milestone 2: Operational Trust

Goal: users can tell what the app is doing and operators can diagnose failures.

Deliverables:

* Structured backend logging with request IDs and task/process IDs.
* Health and diagnostics endpoints for backend, database, runtime catalog, and WebSocket status.
* Frontend diagnostics panel showing backend connectivity, event stream health, and executor availability.
* Golden-signal metrics plan: latency, traffic, errors, saturation.

## Milestone 3: Data Trust

Goal: local data is durable, explainable, and recoverable.

Deliverables:

* SQLite backup/export/import commands.
* Migration verification tests.
* Data retention policy for logs and artifacts.
* Audit trail for destructive actions and task lifecycle transitions.

## Milestone 4: Security Trust

Goal: local-first power remains explicit and safe.

Deliverables:

* Trust boundary documentation.
* Environment variable reference with secret-handling rules.
* Dependency review and audit automation.
* SBOM generation.
* Permission model roadmap for any future multi-user mode.

## Milestone 5: UX Trust

Goal: dense multi-agent workflows remain understandable under stress.

Deliverables:

* Accessibility checks for keyboard, focus, labels, and contrast.
* Performance budgets for main routes and live streams.
* Empty/error/loading state audit.
* Guided first-run/onboarding flow.

## Milestone 6: Release Trust

Goal: releases are repeatable and rollback-friendly.

Deliverables:

* Versioning and changelog policy.
* Release checklist.
* Container images or packaged local app artifacts.
* Smoke test script for release candidates.
