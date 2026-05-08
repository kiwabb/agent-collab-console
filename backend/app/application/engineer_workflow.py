from __future__ import annotations

import json

from pydantic import BaseModel, Field, ValidationError

from app.application.issue_artifact_documents import IssueArtifactDocuments


class EngineerWorkflowError(ValueError):
    pass


class ImplementationTaskItem(BaseModel):
    title: str
    description: str
    priority: str = "P1"


class EngineerReportDocument(BaseModel):
    language: str = "en"
    project_name: str
    issue_id: str
    issue_title: str
    status: str = Field(pattern="^(completed|partial|blocked|failed)$")
    summary: str
    changed_files: list[str]
    completed_tasks: list[ImplementationTaskItem]
    deferred_tasks: list[ImplementationTaskItem]
    risks: list[str]
    verification_commands: list[str]
    qa_notes: list[str]


class EngineerWorkflow:
    """Builds Engineer prompts and persists Engineer artifacts."""

    KEY_ALIASES = {
        "language": "language",
        "projectname": "project_name",
        "project_name": "project_name",
        "issueid": "issue_id",
        "issue_id": "issue_id",
        "issuetitle": "issue_title",
        "issue_title": "issue_title",
        "status": "status",
        "summary": "summary",
        "changedfiles": "changed_files",
        "changed_files": "changed_files",
        "completedtasks": "completed_tasks",
        "completed_tasks": "completed_tasks",
        "deferredtasks": "deferred_tasks",
        "deferred_tasks": "deferred_tasks",
        "risks": "risks",
        "verificationcommands": "verification_commands",
        "verification_commands": "verification_commands",
        "qanotes": "qa_notes",
        "qa_notes": "qa_notes",
    }

    def __init__(self) -> None:
        self._docs = IssueArtifactDocuments()

    def build_prompt(self, task, workspace_title: str | None = None) -> str:
        project_name = workspace_title or "workspace-project"
        issue_id = task.issue_id or task.id

        pm_artifacts = self._read_pm_artifacts(task.workspace_path, issue_id)
        architect_artifacts = self._read_architect_artifacts(task.workspace_path, issue_id)

        requirement_text = pm_artifacts.get("requirement", "")
        prd_text = pm_artifacts.get("prd", "")
        bugfix_text = pm_artifacts.get("bugfix", "")
        system_design_json = architect_artifacts.get("system_design_json", "")
        implementation_plan = architect_artifacts.get("implementation_plan", "")

        upstream_context = self._build_upstream_context(
            requirement_text, prd_text, bugfix_text, system_design_json, implementation_plan
        )

        return (
            "You are acting as Engineer. Follow an implementation workflow: "
            "understand the requirements and design, modify code in the current task workspace, "
            "and produce exactly one JSON object that matches the required schema at the end. "
            "Do not auto-commit or auto-merge changes unless explicitly asked by the user. "
            "Use the same language as the user requirement when possible.\n\n"
            "CRITICAL - TASK BOUNDARY RULES:\n"
            "1. ONLY implement what THIS SPECIFIC TASK requires - DO NOT implement future tasks:\n"
            "   - Read the task title and description carefully to understand the exact scope\n"
            "   - If task says '搭建静态页面结构' (build static page structure), implement ONLY HTML/CSS structure, NO JavaScript logic\n"
            "   - If task says '实现排序引擎' (implement sorting engine), implement ONLY the sorting logic, NOT the UI\n"
            "   - If task says '实现可视化渲染' (implement visualization), implement ONLY the rendering, NOT the control logic\n"
            "   - List unimplemented functionality in 'deferred_tasks' for future tasks to handle\n"
            "2. If the required functionality already exists in the codebase:\n"
            "   - Verify it meets the requirements\n"
            "   - Set status to 'completed'\n"
            "   - Set changed_files to [] (empty array) since no files were modified\n"
            "   - Clearly state in summary that the functionality already exists\n"
            "3. The 'changed_files' array must ONLY contain files you actually modified:\n"
            "   - If you only read files without modifying them, do NOT include them\n"
            "   - If no files were modified, use an empty array: []\n"
            "4. Be honest and precise about what you did and did not do.\n\n"
            "TASK SCOPE INTERPRETATION EXAMPLES:\n"
            "- '搭建页面结构' = HTML markup + CSS styling ONLY, no JavaScript\n"
            "- '实现数据模型' = Data structures/classes ONLY, no business logic\n"
            "- '实现API接口' = API endpoints ONLY, no frontend integration\n"
            "- '实现单元测试' = Test code ONLY, no production code changes\n"
            "When in doubt, implement LESS rather than MORE. Let subsequent tasks handle their own scope.\n\n"
            f"project_name: {project_name}\n"
            f"issue_id: {issue_id}\n"
            f"issue_title: {task.title}\n\n"
            f"{upstream_context}\n\n"
            "required_schema: {\n"
            '"language": "string",\n'
            '"project_name": "string",\n'
            '"issue_id": "string",\n'
            '"issue_title": "string",\n'
            '"status": "completed|partial|blocked|failed",\n'
            '"summary": "string",\n'
            '"changed_files": ["string"],  // ONLY files you actually modified, empty array [] if none\n'
            '"completed_tasks": [{"title": "string", "description": "string", "priority": "P0|P1|P2"}],\n'
            '"deferred_tasks": [{"title": "string", "description": "string", "priority": "P0|P1|P2"}],\n'
            '"risks": ["string"],\n'
            '"verification_commands": ["string"],\n'
            '"qa_notes": ["string"]\n'
            "}\n\n"
            f"user_requirement:\n{task.prompt}"
        )

    def persist_result(self, task, workspace_title: str | None = None) -> EngineerReportDocument:
        if not task.workspace_path:
            raise EngineerWorkflowError("Task workspace_path is required for Engineer artifacts")
        if not task.result or not task.result.strip():
            raise EngineerWorkflowError("Engineer task result is empty")

        canonical_issue_id = task.issue_id or task.id

        try:
            payload = json.loads(task.result)
        except json.JSONDecodeError as exc:
            raise EngineerWorkflowError(f"Engineer output is not valid JSON: {exc}") from exc

        payload = self._normalize_payload_keys(payload)

        payload.setdefault("project_name", workspace_title or "workspace-project")
        payload.setdefault("issue_id", canonical_issue_id)
        payload.setdefault("issue_title", task.title)

        try:
            report = EngineerReportDocument.model_validate(payload)
        except ValidationError as exc:
            raise EngineerWorkflowError(f"Engineer output does not match schema: {exc}") from exc

        self._docs.ensure_issue_root(task.workspace_path, canonical_issue_id)

        impl_md_path = self._docs.engineer_implementation_md_path(task.workspace_path, canonical_issue_id, task.id)
        impl_md_path.write_text(self._render_implementation_markdown(report), encoding="utf-8")

        task.result = (
            f"Implementation report generated for {report.issue_title}. "
            f"Status: {report.status}. File: {impl_md_path.name}."
        )
        return report

    def _read_pm_artifacts(self, workspace_path: str, issue_id: str) -> dict[str, str]:
        artifacts: dict[str, str] = {}
        requirement_path = self._docs.pm_requirement_path(workspace_path, issue_id)
        if requirement_path.exists():
            artifacts["requirement"] = requirement_path.read_text(encoding="utf-8")
        prd_json_path = self._docs.pm_prd_json_path(workspace_path, issue_id)
        if prd_json_path.exists():
            artifacts["prd"] = prd_json_path.read_text(encoding="utf-8")
        bugfix_path = self._docs.pm_bugfix_path(workspace_path, issue_id)
        if bugfix_path.exists():
            artifacts["bugfix"] = bugfix_path.read_text(encoding="utf-8")
        return artifacts

    def _read_architect_artifacts(self, workspace_path: str, issue_id: str) -> dict[str, str]:
        artifacts: dict[str, str] = {}
        design_json_path = self._docs.architect_system_design_json_path(workspace_path, issue_id)
        if design_json_path.exists():
            artifacts["system_design_json"] = design_json_path.read_text(encoding="utf-8")
        impl_plan_path = self._docs.architect_implementation_plan_path(workspace_path, issue_id)
        if impl_plan_path.exists():
            artifacts["implementation_plan"] = impl_plan_path.read_text(encoding="utf-8")
        return artifacts

    def _build_upstream_context(
        self,
        requirement: str,
        prd: str,
        bugfix: str,
        system_design: str,
        implementation_plan: str,
    ) -> str:
        parts = []
        if requirement:
            parts.append(f"requirement_document:\n{requirement}\n")
        else:
            parts.append("NOTE: requirement.md is missing. Treat this as an underspecified requirement.\n")

        if prd:
            parts.append(f"existing_prd:\n{prd}\n")
        else:
            parts.append("NOTE: prd.json is missing. Use qa_notes or deferred_tasks for any missing requirement details.\n")

        if bugfix:
            parts.append(f"existing_bugfix:\n{bugfix}\n")
        else:
            parts.append("NOTE: bugfix.md is not present. Use qa_notes for any missing defect context.\n")

        if system_design:
            parts.append(f"existing_system_design:\n{system_design}\n")
        else:
            parts.append("NOTE: system_design.json is missing. Use qa_notes for any missing design context.\n")

        if implementation_plan:
            parts.append(f"implementation_plan:\n{implementation_plan}\n")
        else:
            parts.append("NOTE: implementation_plan.json is missing. Use deferred_tasks for any missing implementation breakdown.\n")

        return "\n".join(parts)

    def _normalize_payload_keys(self, payload: dict) -> dict:
        normalized = {}
        for key, value in payload.items():
            compact_key = "".join(ch for ch in str(key).lower() if ch.isalnum() or ch == "_")
            target_key = self.KEY_ALIASES.get(compact_key, self.KEY_ALIASES.get(str(key), key))
            normalized[target_key] = value
        return normalized

    def _render_implementation_markdown(self, report: EngineerReportDocument) -> str:
        lines = [
            f"# Implementation Report: {report.issue_title}",
            "",
            f"- Project: {report.project_name}",
            f"- Issue ID: {report.issue_id}",
            f"- Language: {report.language}",
            f"- Status: {report.status}",
            "",
            "## Summary",
            report.summary,
            "",
            "## Changed Files",
        ]
        lines.extend([f"- {f}" for f in report.changed_files] or ["- None"])
        lines.extend(["", "## Completed Tasks"])
        lines.extend([f"- **{t.title}** ({t.priority}): {t.description}" for t in report.completed_tasks] or ["- None"])
        lines.extend(["", "## Deferred Tasks"])
        lines.extend([f"- **{t.title}** ({t.priority}): {t.description}" for t in report.deferred_tasks] or ["- None"])
        lines.extend(["", "## Risks"])
        lines.extend([f"- {r}" for r in report.risks] or ["- None"])
        lines.extend(["", "## Verification Commands"])
        lines.extend([f"- `{c}`" for c in report.verification_commands] or ["- None"])
        lines.extend(["", "## QA Notes"])
        lines.extend([f"- {n}" for n in report.qa_notes] or ["- None"])
        lines.append("")
        return "\n".join(lines)
