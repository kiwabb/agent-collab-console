from __future__ import annotations

import json

from app.adapters.base import (
    AgentArtifact,
    AgentResult,
    artifact_list,
    object_dict,
    string_field,
    string_list_field,
)
from app.adapters.local_process import CalledProcessError, run_trusted_local


class CodexCliAdapter:
    agent_id = "codex"
    role = "master"

    def __init__(self, command: list[str]):
        self.command = command

    def _fallback_artifact(self, task_title: str, summary: str, next_steps: list[str]) -> AgentArtifact:
        return {
            "kind": "plan",
            "content": {
                "summary": summary,
                "next_steps": next_steps,
                "task_title": task_title,
            },
            "steps": next_steps,
        }

    def _parse_output(self, stdout: str, task_title: str) -> AgentResult:
        """Parse CLI output. If JSON, extract structured fields; otherwise use as summary."""
        text = stdout.strip()
        try:
            data = object_dict(json.loads(text))
            summary = string_field(data, "summary", text or task_title)
            next_steps = string_list_field(data, "next_steps", [text or task_title])
            fallback_artifacts = [self._fallback_artifact(task_title, summary, next_steps)]
            return {
                "agent_id": self.agent_id,
                "role": self.role,
                "summary": summary,
                "artifacts": artifact_list(data.get("artifacts"), fallback_artifacts),
                "status": string_field(data, "status", "completed"),
            }
        except (json.JSONDecodeError, TypeError):
            summary = text or task_title
            next_steps = [summary]
            return {
                "agent_id": self.agent_id,
                "role": self.role,
                "summary": summary,
                "artifacts": [self._fallback_artifact(task_title, summary, next_steps)],
                "status": "completed",
            }

    def execute(self, task_title: str) -> AgentResult:
        try:
            completed = run_trusted_local(self.command, capture_output=True, text=True, check=True)
            parsed = self._parse_output(completed.stdout, task_title)
            return {
                "agent_id": self.agent_id,
                "role": self.role,
                "status": parsed["status"],
                "summary": parsed["summary"],
                "artifacts": parsed["artifacts"],
            }
        except CalledProcessError as e:
            return {
                "agent_id": self.agent_id,
                "role": self.role,
                "status": "failed",
                "summary": f"Planning failed: {e.stderr.strip() or str(e)}",
                "artifacts": [],
            }
