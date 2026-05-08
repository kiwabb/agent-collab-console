import json
import subprocess


class ClaudeCliAdapter:
    agent_id = "claude"
    role = "worker"

    def __init__(self, command: list[str]):
        self.command = command

    def _parse_output(self, stdout: str, fallback: str) -> dict:
        """Parse CLI output. If JSON, extract structured fields; otherwise use as summary."""
        text = stdout.strip()
        try:
            data = json.loads(text)
            return {
                "summary": data.get("summary", fallback),
                "artifacts": data.get("artifacts", [{"kind": "execution_result", "content": data.get("summary", fallback)}]),
                "status": data.get("status", "completed"),
            }
        except (json.JSONDecodeError, TypeError):
            return {
                "summary": text or fallback,
                "artifacts": [{"kind": "execution_result", "content": text or fallback}],
                "status": "completed",
            }

    def execute(self, payload: dict) -> dict:
        try:
            completed = subprocess.run(self.command, capture_output=True, text=True, check=True)
            plan = payload.get("plan")
            plan_summary = plan.get("summary") if plan else None
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
        except subprocess.CalledProcessError as e:
            return {
                "agent_id": self.agent_id,
                "role": self.role,
                "status": "failed",
                "summary": f"Task failed: {e.stderr.strip() or str(e)}",
                "artifacts": [],
            }
