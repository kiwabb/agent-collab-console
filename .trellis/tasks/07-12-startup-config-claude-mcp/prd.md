# Claude MCP Multi-Service Startup Configuration

## Goal

Replace the fixed startup-evidence whitelist and free-text JSON result parsing with a Claude-driven repository inspection workflow. Claude must inspect the real project workspace and persist a structured multi-service startup configuration through a project-scoped MCP tool.

## What I Already Know

- The current collector reads a fixed list of files and omits important evidence such as Maven `pom.xml`, Gradle files, Vite config, application properties, Dockerfiles, and `.env.example` files.
- The current project model stores only one `setup_script` and one `run_command`.
- `examples/admin-demo` contains a Spring Boot backend and a Vue/Vite frontend. The current analysis recognizes both but persists only the frontend command and relegates the backend command to notes.
- Prototype planning already provides the desired architectural pattern: Claude inspects the isolated workspace and submits structured output through a session-scoped MCP service.
- Startup analysis currently runs as an `operations_engineer` task and the frontend polls that task until completion.

## Requirements (Evolving)

- Claude runs with the project repository as its workspace and autonomously uses its filesystem inspection tools to discover startup evidence.
- Remove the fixed evidence excerpt as the primary analysis path.
- Provide a project- and task-scoped MCP tool that persists the startup analysis.
- The MCP payload represents multiple independently identifiable services.
- Each service records its working directory, setup command, run command, access URL, dependencies, and evidence paths.
- Environment variable discoveries remain structured and preserve user-entered values.
- MCP input is validated at the service boundary before persistence.
- Analysis only discovers and saves commands; it does not execute model-proposed commands.
- A task is successful only after the MCP save/finalize tool has accepted a result.
- Keep deterministic inference only as an explicit degraded path when Claude/MCP execution is unavailable.
- Existing projects with legacy `setup_script` and `run_command` remain readable during migration.
- Each discovered service can be started and stopped independently.
- Each service exposes its own process state, reachability state, and logs.
- The page also provides a project-level start-all and stop-all flow that respects declared service dependencies.
- Starting multiple services is fail-closed: a validation or environment-materialization failure refuses that service start and is shown explicitly.
- A failure in one service does not erase logs, state, or previously persisted configuration for the other services.

## Acceptance Criteria (Evolving)

- [ ] An Operations Engineer can inspect files outside the old whitelist, including `backend/pom.xml`.
- [ ] `admin-demo` analysis persists both backend and frontend as first-class services.
- [ ] The backend service uses `backend` plus `mvn spring-boot:run` and the frontend service uses `frontend` plus `npm run dev`.
- [ ] The analysis result is persisted through MCP rather than parsed from Claude's final free-text response.
- [ ] MCP sessions cannot save configuration for another project or task.
- [ ] Invalid working directories or malformed commands are rejected without overwriting the previous valid configuration.
- [ ] Existing user-provided environment variable values are not overwritten by inferred values.
- [ ] The startup configuration page displays all discovered services and their evidence.
- [ ] Users can independently start and stop the backend and frontend services and inspect separate logs.
- [ ] Start-all follows dependency order; for `admin-demo`, backend starts before frontend.
- [ ] Stop-all uses reverse dependency order.
- [ ] A service failure is visible without clearing another service's stale status or logs.
- [ ] Existing legacy startup configuration remains readable after migration.

## Definition of Done

- Focused backend and frontend tests cover the new workflow and migration compatibility.
- Relevant lint/type checks pass where justified by the touched layers.
- API, persistence, event, and UI contracts are consistent.
- New durable conventions are captured in Trellis specs when warranted.

## Technical Approach

- Reuse the prototype-planning MCP lifecycle pattern: issue a scoped session token, expose an MCP endpoint during the Claude task, require discovery/finalization tool calls, and close the session on completion.
- Introduce a normalized startup-service persistence model rather than encoding multiple commands in shell concatenation or notes.
- Make the MCP service call an application service; the MCP layer never writes SQLite directly.
- Treat Claude's final text as diagnostics only. The persisted MCP result is authoritative.
- Preserve legacy project fields as a compatibility projection during rollout, then route new UI reads through the service collection.
- Replace the project-singleton run manager state with service-keyed process state while preserving the existing command safety, environment materialization, output redaction, and local reachability checks.

## Decision (ADR-lite)

**Context**: A backend-owned evidence whitelist cannot cover heterogeneous repositories, and a single `run_command` cannot model full-stack projects.

**Decision**: Let Claude inspect the actual workspace and save a validated multi-service configuration through scoped MCP tools, following the existing prototype-planning architecture.

**Consequences**: Analysis becomes more capable and extensible, but persistence, execution state, API contracts, migration compatibility, and process lifecycle management must explicitly model service identity and dependency ordering.

## Out of Scope (Temporary)

- Modifying files inside analyzed projects to generate `dev-local.sh`.
- Automatically executing commands during analysis.
- Remote deployment or production orchestration.

## Technical Notes

- Current collector: `backend/app/application/project_script_suggestions.py`
- Current task creation: `backend/app/interfaces/api.py`
- Current result persistence: `backend/app/application/role_workflow_service.py`
- Existing MCP reference: `backend/app/application/prototype_planning_mcp.py`
- Existing UI: `frontend/src/features/projects/ProjectStartupConfigPage.tsx`
- Existing hook: `frontend/src/features/projects/useProjectStartupConfig.ts`
