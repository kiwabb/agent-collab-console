class FakeClaudeAdapter:
    agent_id = "claude"
    role = "worker"
    last_payload: dict | None = None

    def execute(self, payload: dict) -> dict:
        FakeClaudeAdapter.last_payload = payload
        task_title = payload["task_title"]
        plan = payload.get("plan")
        plan_summary = plan.get("summary") if plan else None
        if plan_summary:
            summary = f"Implemented {task_title} following plan: {plan_summary}"
        else:
            summary = f"Implemented: {task_title}"
        return {
            "agent_id": self.agent_id,
            "role": self.role,
            "status": "completed",
            "summary": summary,
            "artifacts": [{"kind": "execution_result", "content": summary}],
        }
