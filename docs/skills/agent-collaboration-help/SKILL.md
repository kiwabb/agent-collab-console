---
name: agent-collaboration-help
description: Use when a Codex task may need targeted help from Claude for review, validation, alternative implementation ideas, or higher-confidence analysis during task execution.
---

# Agent Collaboration Help

## Output Rule

When you need Claude's help in this project, output exactly one raw JSON object and nothing else.

Do not call `curl`.
Do not create sessions yourself.
Do not hit local APIs directly.
Do not wrap the JSON in a markdown code fence.
Do not add explanation text before or after the JSON.

## Required JSON

The JSON object must use these exact keys:

- `type`: must be exactly `request_help`
- `target`: must be `claude`
- `title`: short task label
- `prompt`: concrete request for Claude
- `blocking`: must be `true`
- `context_summary`: optional concise background

Canonical example:

```json
{
  "type": "request_help",
  "target": "claude",
  "title": "Review resume-state fix",
  "prompt": "Review this resume-state design. Focus on cross-executor state pollution, likely regressions, and missing tests. Recommend concrete fixes.",
  "blocking": true,
  "context_summary": "Codex and Claude tasks share one workspace session, and resume metadata may be crossing executor boundaries."
}
```

## When to Use

Use this only when Claude can materially improve correctness, reduce risk, or unblock a task faster than continuing alone.

Use it for:

- second opinions on risky implementation or refactor work
- uncertain bug root cause after meaningful investigation
- plan, edge case, or regression review
- alternative implementation comparison
- ambiguous behavior that needs focused external analysis

Do not use it when:

- the task is straightforward and you already know the next step
- you only want generic brainstorming with no clear decision to make
- the request would be vague, open-ended, or duplicate your own work
- you can answer from local code or recent logs directly

## Prompt Rules

Keep the prompt specific. Claude should know exactly what to do without guessing.

The prompt should:

- state exactly what Claude should do
- define the evaluation focus
- name the artifact or code path under review
- ask for concrete output, not vague advice

## Hard Rule

The only supported help request is the raw JSON protocol above.
