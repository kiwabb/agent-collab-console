from __future__ import annotations

from app.adapters.base import AgentResult


class FakeCodexAdapter:
    agent_id = "codex"
    role = "master"

    def execute(self, task_title: str) -> AgentResult:
        steps = [f"Design API for {task_title}", f"Implement {task_title}", f"Test {task_title}"]
        return {
            "agent_id": self.agent_id,
            "role": self.role,
            "status": "completed",
            "summary": f"Planned: {task_title}",
            "artifacts": [
                {
                    "kind": "plan",
                    "content": {
                        "summary": f"Plan for: {task_title}",
                        "next_steps": steps,
                        "task_title": task_title,
                    },
                    "steps": steps,
                }
            ],
        }
