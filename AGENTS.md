Use the local `agent-collaboration-help` skill at `.codex/skills/agent-collaboration-help/SKILL.md` when a Codex task needs focused help from Claude for review, validation, alternative approaches, or higher-confidence analysis.

When you need that help, output exactly one raw JSON object using the project help protocol and nothing else.

Do not use `curl`, do not create sessions yourself, and do not call local APIs directly as a substitute for help.

Keep help requests specific. Provide a short title, a concrete prompt, and use blocking help so the parent task can continue with the returned result.
Use the canonical JSON keys `type`, `target`, `title`, `prompt`, `blocking`, and optional `context_summary`.
The `type` value must be exactly `request_help`.
