# Source-Informed Coordinator Patterns

## Current Project Findings

The ProjectConductor issue loop already has a substantial execution substrate:

* Anthropic-shaped tool-use loop with multiple tool calls per turn.
* `dispatch_subagent` for dependent serial work.
* `dispatch_batch` for independent concurrent work with per-agent worktree isolation and merge-back.
* Role concurrency limits, retry budget, activity-aware waits, heartbeat lease renewal, pause/resume, user inbox injection, and budget-aware concurrency downscaling.
* Structured tool results for `role_busy`, `retries_exhausted`, `artifact_invalid`, QA failure, and batch merge conflicts.

The main opportunity is coordinator cognition: the system prompt should make the conductor better at selecting the right workflow shape, delegating precisely, responding to failures, and finishing cleanly. There is also a concrete bug: `run_issue_conductor_loop` calls `ProjectConductor._load_state()`, but the class exposes `get_or_create_state()`. The broad exception handler hides this and prevents project context injection.

## Codex CLI Patterns

Relevant local files:

* `references/codex-cli/codex-rs/core/gpt_5_codex_prompt.md`
* `references/codex-cli/codex-rs/core/gpt_5_2_prompt.md`

Transferable ideas:

* Treat local repo instructions as scoped contracts.
* Persist through implementation and verification rather than stopping at analysis.
* Use a plan for non-trivial, multi-step work, but keep plans meaningful and updated.
* Prefer existing code patterns and root-cause fixes.
* Be careful with dirty worktrees and never silently revert unrelated work.
* Validate changes with focused tests before broad checks.
* Keep final user-facing output concise and outcome-oriented.

For ProjectConductor, these map to a stronger operating contract: inspect context first, decide whether work is simple or multi-agent, delegate with clear expected outputs, verify before finalizing, and summarize what changed plus residual risk.

## Claude Code Tool Surface Patterns

Relevant local file:

* `references/claude-code-sourcemap/package/sdk-tools.d.ts`

Transferable ideas from `AgentInput`:

* Delegation has a short description and a full prompt.
* The caller chooses a specialist/subagent type.
* The caller may choose isolation mode, background mode, permission mode, and model override.
* The prompt should encode execution intent, not just role name.

This project already has role selection, prompt override, worktree isolation for batch, and provider/model settings elsewhere. The prompt should therefore push the conductor to write better subagent prompts: goal, context, constraints, expected artifact/result, verification, and when not to edit.

## Recommended MVP

1. Extract prompt assembly into a small helper in `conductor_main_loop.py` so tests can assert behavior without running a full loop.
2. Fix project context loading by using `ProjectConductor.get_or_create_state()`.
3. Replace the prompt body with an explicit operating contract:
   * mission and available context
   * decision loop
   * role sequencing
   * delegation prompt quality
   * serial vs parallel rules
   * failure recovery rules
   * budget and language constraints
   * user interjection precedence
   * finalization criteria
4. Add focused tests for memory injection and contract text.

## Non-MVP Ideas

* Persist every conductor decision as a structured `ConductorDecision` row for later audit and benchmarking.
* Add a `plan_workflow` tool that records a conductor plan before dispatch.
* Add subagent model selection hints per role.
* Add frontend visualization for the conductor's chosen decision loop.
