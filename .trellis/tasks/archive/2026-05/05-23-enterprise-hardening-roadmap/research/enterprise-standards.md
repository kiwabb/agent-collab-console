# Enterprise Standards Research

## Sources Consulted

* [OWASP Application Security Verification Standard (ASVS)](https://owasp.org/www-project-application-security-verification-standard/) — security verification requirements for web applications.
* [OWASP Developer Guide: ASVS](https://devguide.owasp.org/en/03-requirements/05-asvs/) — ASVS sections and verification-level framing.
* [OpenSSF Scorecard](https://openssf.org/scorecard/) — automated security posture scoring for open source repositories.
* [WCAG 2 Overview](https://www.w3.org/WAI/standards-guidelines/wcag/) and [WCAG 2.2 Recommendation](https://www.w3.org/TR/WCAG22/) — accessibility principles and testable success criteria.
* [Google SRE Book: Monitoring Distributed Systems](https://sre.google/sre-book/monitoring-distributed-systems/) — four golden signals: latency, traffic, errors, saturation.

## Standards Mapped to This Project

### Security Baseline

OWASP ASVS is useful as a structured checklist for application security verification. For this local-first project, the first practical slice is not full ASVS compliance. The first slice should establish:

* documented trust boundaries between browser, FastAPI backend, local filesystem, local CLIs, and repositories;
* explicit handling of local secrets and environment variables;
* no accidental commit of runtime databases, logs, or session files;
* clear error behavior for user-triggered actions;
* dependency scanning and repeatable install commands.

### Supply Chain Baseline

OpenSSF Scorecard and SLSA emphasize repository hygiene, dependency pinning, CI, provenance, and tamper resistance. For this project, the immediate gaps are:

* no visible GitHub Actions workflow;
* broad Python dependency ranges;
* local generated/runtime files showing in `git status`;
* no documented release/package flow;
* no SBOM generation.

Recommended first milestone:

* add CI for backend tests and frontend typecheck/test/lint;
* add ignore rules for generated/runtime files;
* document dependency installation and vulnerability audit commands;
* plan SBOM and dependency review automation as the next milestone.

### Accessibility Baseline

WCAG 2.2 is the right reference point for enterprise UI accessibility. For a dense agent console, practical first checks are:

* keyboard navigation through command palette, dialogs, sidebar, and tabs;
* visible focus states;
* labels and `aria-label` for icon-only controls;
* color contrast for text and status states;
* reduced-motion behavior for live/animated surfaces.

The recent UI work started this direction; a later hardening slice should add automated or scripted accessibility checks.

### Operability Baseline

Google SRE's four golden signals map well to this system:

* Latency: task run duration, API response time, WebSocket lag.
* Traffic: active users, API calls, live event throughput.
* Errors: failed task runs, failed API calls, WebSocket disconnects.
* Saturation: active processes, queued tasks, SQLite contention, worker concurrency.

First milestone:

* document operational signals;
* add structured logs and health checks;
* expose a basic diagnostics endpoint or operator page in a future slice.

## Recommendation

Use a staged roadmap:

1. **Trust the repo**: docs, ignore rules, CI, current Docker/local run correctness.
2. **Trust the app**: health checks, structured errors, observability, recovery workflows.
3. **Trust the data**: backup/export, migration checks, retention, audit trails.
4. **Trust the supply chain**: pinned dependencies, Dependabot/dependency review, SBOM, release artifacts.
5. **Trust the UX**: accessibility checks, keyboard coverage, performance budgets.
