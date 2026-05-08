import json
import subprocess


class CodexCliAdapter:
    agent_id = "codex"
    role = "master"

    def __init__(self, command: list[str]):
        self.command = command

    def _parse_output(self, stdout: str, task_title: str) -> dict:
        """Parse CLI output. If JSON, extract structured fields; otherwise use as summary."""
        text = stdout.strip()
        try:
            data = json.loads(text)
            return {
                "summary": data.get("summary", text or task_title),
                "artifacts": data.get("artifacts", [{
                    "kind": "plan",
                    "content": {
                        "summary": data.get("summary", text or task_title),
                        "next_steps": data.get("next_steps", [text or task_title]),
                        "task_title": data.get("task_title", task_title),
                    },
                    "steps": data.get("next_steps", [text or task_title]),
                }]),
                "status": data.get("status", "completed"),
            }
        except (json.JSONDecodeError, TypeError):
            return {
                "summary": text or task_title,
                "artifacts": [{
                    "kind": "plan",
                    "content": {
                        "summary": text or task_title,
                        "next_steps": [text or task_title],
                        "task_title": task_title,
                    },
                    "steps": [text or task_title],
                }],
                "status": "completed",
            }

    def execute(self, task_title: str) -> dict:
        try:
            completed = subprocess.run(self.command, capture_output=True, text=True, check=True)
            parsed = self._parse_output(completed.stdout, task_title)
            return {
                "agent_id": self.agent_id,
                "role": self.role,
                "status": parsed["status"],
                "summary": parsed["summary"],
                "artifacts": parsed["artifacts"],
            }
        except subprocess.CalledProcessError as e:
            return {
                "agent_id": self.agent_id,
                "role": self.role,
                "status": "failed",
                "summary": f"Planning failed: {e.stderr.strip() or str(e)}",
                "artifacts": [],
            }
