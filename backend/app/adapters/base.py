from typing import Protocol


class AgentAdapter(Protocol):
    agent_id: str
    role: str

    def execute(self, task_title: str) -> dict: ...
