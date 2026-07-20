# remove duplicate workspace navigation

## Goal

Remove the duplicate frontend workspace and issue navigation implemented by the
legacy root `WorkbenchPage`. Keep one canonical project workspace list at
`/projects/:projectId`, one canonical workspace console at
`/workspaces/:workspaceId`, and make `/` the global Inbox entry point.

## What I already know

* `frontend/src/app/page.tsx` currently mounts the legacy `WorkbenchPage`.
* `WorkbenchPage` resolves `?project=<projectId>`, renders `WorkspaceGrid`,
  and switches to an in-memory `IssueGrid` without changing the URL.
* `frontend/src/app/projects/[id]/page.tsx` mounts `ProjectWorkspacesPage`,
  which already owns project-scoped workspace CRUD, search, project run
  controls, and navigation to `/workspaces/:workspaceId`.
* `frontend/src/app/workspaces/[wsId]/page.tsx` mounts `WorkspaceConsole`,
  which owns one-workspace issue/task operations and uses the shared
  `WorkbenchShell`.
* `frontend/src/features/inbox/InboxDashboard.tsx` is an existing global
  summary page but is currently not mounted by an App Router page.
* The root route is outside `WorkbenchShell`; the rest of the current route
  tree uses `WorkbenchShell` and the newer route-oriented architecture.
* Existing unrelated backend/spec changes are present in the working tree and
  must remain untouched.

## Assumptions

* `/projects/:projectId` is the canonical project workspace-management route.
* `/workspaces/:workspaceId` is the canonical single-workspace route.
* A legacy root URL carrying `?project=<projectId>` should redirect to the
  canonical project route, preserving the project selection in the path.
* A root URL without a project query should render the existing Inbox dashboard,
  not a second workspace list.
* The backend API contracts and workspace/issue behavior do not change.

## Requirements

* Replace the root route's `WorkbenchPage` mount with `WorkbenchShell` plus
  `InboxDashboard`.
* Handle the legacy `project` query at the server route boundary and redirect
  to `/projects/<encoded project id>`.
* Remove the root route's runtime dependency on the legacy `WorkbenchPage` and
  its duplicate workspace-list rendering.
* Keep project-page workspace creation, editing, deletion, search, project run
  controls, and navigation behavior unchanged.
* Keep workspace-console issue/task behavior unchanged.
* Project-scoped routes must pass their path `projectId` into
  `WorkbenchShell`, so the global project selector cannot display stale
  local-storage state after a legacy redirect or deep link.
* Update source-contract tests and route tests so they assert the canonical
  route map rather than requiring the removed root workbench implementation.
* Do not remove shared shell, websocket, task, or issue modules that are still
  imported by canonical routes.

## Acceptance Criteria

* [x] `frontend/src/app/page.tsx` no longer imports or renders `WorkbenchPage`.
* [x] `/` renders `InboxDashboard` inside `WorkbenchShell`.
* [x] `/?project=<id>` redirects to `/projects/<encoded id>`.
* [x] `/projects/<id>` remains the only project-scoped workspace list entry
      point and still type-checks successfully.
* [x] `/workspaces/<workspaceId>` remains a single-workspace detail route.
* [x] Project workspace, conductor, environment, and prototype routes keep
      the global shell selection synchronized with the path project ID.
* [x] No canonical route imports `WorkspaceGrid` through the root workbench.
* [x] Frontend tests, type-check, lint, and formatting checks pass (or any
      pre-existing unrelated failures are documented).

## Definition of Done

* Tests updated for the route and source-contract change.
* Frontend typecheck/lint/targeted tests pass.
* No unrelated dirty files are modified.
* The final response documents the canonical route map and verification.

## Out of Scope

* Backend/API/database changes.
* Redesigning `ProjectWorkspacesPage` or `WorkspaceConsole` UI.
* Removing shared task/execution stores used by `WorkbenchShell` providers.
* Changing external links beyond the root legacy compatibility redirect.

## Technical Notes

* Relevant package spec: `.trellis/spec/ccgui/frontend/index.md`.
* The existing route-shell convention is `WorkbenchShell` wrapping feature
  pages; `InboxDashboard` already follows the feature-page pattern and uses
  project/workspace APIs directly.
* The old root workbench remains a large source file with source-contract tests;
  tests should be changed narrowly to reflect the new route ownership instead
  of deleting unrelated shared components.

## Route Ownership Decision

| Route | Owner | Responsibility |
| --- | --- | --- |
| `/` | `InboxDashboard` inside `WorkbenchShell` | Cross-project activity summary and global entry navigation |
| `/?project=<projectId>` | Route boundary redirect | Legacy compatibility only; redirects to `/projects/<projectId>` |
| `/projects/<projectId>` | `ProjectWorkspacesPage` | Project metadata, workspace CRUD/search, project run/sync controls |
| `/workspaces/<workspaceId>` | `WorkspaceConsole` | One workspace's issue/task queue and issue creation/opening |
| `/issues/<issueId>` | `IssueDetailPage` | Issue workflow, tasks, execution, artifacts, diff, and agent activity |

The legacy `WorkbenchPage` combines the second, third, and fourth rows in one
in-memory state machine. It is therefore removed from the mounted route path;
the canonical feature pages remain the owners of their respective behavior.
