from __future__ import annotations

import json

from app.adapters.base import (
    AgentArtifact,
    AgentResult,
    WorkerTaskPayload,
    artifact_list,
    object_dict,
    string_field,
)
from app.adapters.local_process import CalledProcessError, run_trusted_local


class ClaudeCliAdapter:
    agent_id = "claude"
    role = "worker"

    def __init__(self, command: list[str]):
        self.command = command

    def _fallback_artifact(self, summary: str) -> AgentArtifact:
        return {"kind": "execution_result", "content": summary}

    def _parse_output(self, stdout: str, fallback: str) -> AgentResult:
        """Parse CLI output. If JSON, extract structured fields; otherwise use as summary."""
        text = stdout.strip()
        try:
            data = object_dict(json.loads(text))
            summary = string_field(data, "summary", fallback)
            fallback_artifacts = [self._fallback_artifact(summary)]
            return {
                "agent_id": self.agent_id,
                "role": self.role,
                "summary": summary,
                "artifacts": artifact_list(data.get("artifacts"), fallback_artifacts),
                "status": string_field(data, "status", "completed"),
            }
        except (json.JSONDecodeError, TypeError):
            summary = text or fallback
            return {
                "agent_id": self.agent_id,
                "role": self.role,
                "summary": summary,
                "artifacts": [self._fallback_artifact(summary)],
                "status": "completed",
            }

    def execute(self, payload: WorkerTaskPayload) -> AgentResult:
        try:
            completed = run_trusted_local(self.command, capture_output=True, text=True, check=True)
            plan = payload.get("plan")
            plan_summary_raw = plan.get("summary") if plan else None
            plan_summary = plan_summary_raw if isinstance(plan_summary_raw, str) else None
            parsed = self._parse_output(completed.stdout, payload["task_title"])
            if plan_summary and "plan:" not in parsed["summary"]:
                summary = f"{parsed['summary']} [plan: {plan_summary}]"
            else:
                summary = parsed["summary"]
            return {
                "agent_id": self.agent_id,
                "role": self.role,
                "status": parsed["status"],
                "summary": summary,
                "artifacts": parsed["artifacts"],
            }
        except CalledProcessError as e:
            return {
                "agent_id": self.agent_id,
                "role": self.role,
                "status": "failed",
                "summary": f"Task failed: {e.stderr.strip() or str(e)}",
                "artifacts": [],
            }
