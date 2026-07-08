from __future__ import annotations

from typing import Protocol, TypedDict

from app.json_safety import object_dict, string_list_value, string_value


class AgentArtifact(TypedDict, total=False):
    kind: str
    content: object
    steps: list[str]


class AgentResult(TypedDict):
    agent_id: str
    role: str
    status: str
    summary: str
    artifacts: list[AgentArtifact]


class WorkerTaskPayload(TypedDict):
    task_id: str
    task_title: str
    plan: dict[str, object] | None
    session_id: str


def string_field(payload: dict[str, object], key: str, fallback: str) -> str:
    return string_value(payload.get(key), fallback)


def string_list_field(payload: dict[str, object], key: str, fallback: list[str]) -> list[str]:
    return string_list_value(payload.get(key), fallback)


def artifact_list(value: object, fallback: list[AgentArtifact]) -> list[AgentArtifact]:
    if not isinstance(value, list):
        return fallback

    artifacts: list[AgentArtifact] = []
    for raw_item in value:
        item = object_dict(raw_item)
        kind = item.get("kind")
        content = item.get("content")
        if not isinstance(kind, str) or content is None:
            continue
        artifact: AgentArtifact = {"kind": kind, "content": content}
        steps = item.get("steps")
        if isinstance(steps, list):
            artifact["steps"] = [str(step) for step in steps]
        artifacts.append(artifact)
    return artifacts or fallback


class AgentAdapter(Protocol):
    agent_id: str
    role: str

    def execute(self, task_title: str) -> AgentResult: ...
