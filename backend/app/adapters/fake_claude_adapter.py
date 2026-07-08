from __future__ import annotations

from app.adapters.base import AgentResult, WorkerTaskPayload


class FakeClaudeAdapter:
    agent_id = "claude"
    role = "worker"
    last_payload: WorkerTaskPayload | None = None

    def execute(self, payload: WorkerTaskPayload) -> AgentResult:
        FakeClaudeAdapter.last_payload = payload
        task_title = payload["task_title"]
        plan = payload.get("plan")
        plan_summary_raw = plan.get("summary") if plan else None
        plan_summary = plan_summary_raw if isinstance(plan_summary_raw, str) else None
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
