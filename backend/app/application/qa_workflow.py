from __future__ import annotations

import json

from pydantic import BaseModel, Field, ValidationError

from app.application.issue_artifact_documents import IssueArtifactDocuments


class QAWorkflowError(ValueError):
    pass


class QAReportDocument(BaseModel):
    language: str = "en"
    project_name: str
    issue_id: str
    issue_title: str
    status: str = Field(pattern="^(passed|failed|blocked|needs_follow_up)$")
    test_scope: str
    acceptance_coverage: list[str]
    commands_run: list[str]
    recommended_commands: list[str]
    manual_scenarios: list[str]
    bugs_found: list[str]
    risks: list[str]
    test_gaps: list[str]
    final_recommendation: str


class QAWorkflow:
    """Builds QA prompts and persists QA artifacts."""

    KEY_ALIASES = {
        "language": "language",
        "projectname": "project_name",
        "project_name": "project_name",
        "issueid": "issue_id",
        "issue_id": "issue_id",
        "issuetitle": "issue_title",
        "issue_title": "issue_title",
        "status": "status",
        "testscope": "test_scope",
        "test_scope": "test_scope",
        "acceptancecoverage": "acceptance_coverage",
        "acceptance_coverage": "acceptance_coverage",
        "commandsrun": "commands_run",
        "commands_run": "commands_run",
        "recommendedcommands": "recommended_commands",
        "recommended_commands": "recommended_commands",
        "manualscenarios": "manual_scenarios",
        "manual_scenarios": "manual_scenarios",
        "bugsfound": "bugs_found",
        "bugs_found": "bugs_found",
        "risks": "risks",
        "testgaps": "test_gaps",
        "test_gaps": "test_gaps",
        "finalrecommendation": "final_recommendation",
        "final_recommendation": "final_recommendation",
    }

    def __init__(self) -> None:
        self._docs = IssueArtifactDocuments()

    def build_prompt(self, task, workspace_title: str | None = None) -> str:
        project_name = workspace_title or "workspace-project"
        issue_id = task.issue_id or task.id

        pm_artifacts = self._read_pm_artifacts(task.workspace_path, issue_id)
        architect_artifacts = self._read_architect_artifacts(task.workspace_path, issue_id)
        engineer_artifacts = self._read_engineer_artifacts(task.workspace_path, issue_id)

        requirement_text = pm_artifacts.get("requirement", "")
        prd_text = pm_artifacts.get("prd", "")
        bugfix_text = pm_artifacts.get("bugfix", "")
        system_design_json = architect_artifacts.get("system_design_json", "")
        implementation_plan = architect_artifacts.get("implementation_plan", "")
        implementation_md = engineer_artifacts.get("implementation_md", "")

        upstream_context = self._build_upstream_context(
            requirement_text, prd_text, bugfix_text, system_design_json, implementation_plan, implementation_md
        )

        return (
            "You are acting as QA. Follow a QA workflow: "
            "analyze requirements, review design and implementation, verify coverage and risks, "
            "and produce exactly one JSON object that matches the required schema at the end. "
            "Do not auto-commit or auto-merge changes unless explicitly asked by the user. "
            "Use the same language as the user requirement when possible.\n\n"
            f"project_name: {project_name}\n"
            f"issue_id: {issue_id}\n"
            f"issue_title: {task.title}\n\n"
            f"{upstream_context}\n\n"
            "OUTPUT FORMAT RULES:\n"
            "- Output the JSON object directly. Do NOT wrap it in markdown code blocks (no ```json or ```).\n"
            "- The entire response must be a single raw JSON object starting with { and ending with }.\n"
            "- Do NOT write any analysis, summary, or explanation text before or after the JSON.\n"
            "- STOP immediately after outputting the closing }. No additional text or commands.\n\n"
            "required_schema: {\n"
            '"language": "string",\n'
            '"project_name": "string",\n'
            '"issue_id": "string",\n'
            '"issue_title": "string",\n'
            '"status": "passed|failed|blocked|needs_follow_up",\n'
            '"test_scope": "string",\n'
            '"acceptance_coverage": ["string"],\n'
            '"commands_run": ["string"],\n'
            '"recommended_commands": ["string"],\n'
            '"manual_scenarios": ["string"],\n'
            '"bugs_found": ["string"],\n'
            '"risks": ["string"],\n'
            '"test_gaps": ["string"],\n'
            '"final_recommendation": "string"\n'
            "}\n\n"
            f"user_requirement:\n{task.prompt}"
        )

    def persist_result(self, task, workspace_title: str | None = None) -> QAReportDocument:
        if not task.workspace_path:
            raise QAWorkflowError("Task workspace_path is required for QA artifacts")
        if not task.result or not task.result.strip():
            raise QAWorkflowError("QA task result is empty")

        canonical_issue_id = task.issue_id or task.id

        try:
            payload = json.loads(task.result)
        except json.JSONDecodeError as exc:
            raise QAWorkflowError(f"QA output is not valid JSON: {exc}") from exc

        payload = self._normalize_payload_keys(payload)

        payload.setdefault("project_name", workspace_title or "workspace-project")
        payload.setdefault("issue_id", canonical_issue_id)
        payload.setdefault("issue_title", task.title)

        try:
            report = QAReportDocument.model_validate(payload)
        except ValidationError as exc:
            raise QAWorkflowError(f"QA output does not match schema: {exc}") from exc

        self._docs.ensure_issue_root(task.workspace_path, canonical_issue_id)

        qa_plan_path = self._docs.qa_plan_json_path(task.workspace_path, canonical_issue_id)
        qa_report_path = self._docs.qa_report_md_path(task.workspace_path, canonical_issue_id)

        qa_plan_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        qa_report_path.write_text(self._render_qa_report_markdown(report), encoding="utf-8")

        task.result = (
            f"QA report generated for {report.issue_title}. "
            f"Status: {report.status}. Files: {qa_plan_path.name}, {qa_report_path.name}."
        )
        # Attach written_files to the payload using object.__setattr__ to bypass Pydantic validation
        object.__setattr__(report, "written_files", [
            {"name": "qa/qa_plan.json", "path": str(qa_plan_path), "kind": "testing"},
            {"name": "qa/qa_report.md", "path": str(qa_report_path), "kind": "testing"},
        ])
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

    def _read_engineer_artifacts(self, workspace_path: str, issue_id: str) -> dict[str, str]:
        artifacts: dict[str, str] = {}
        # Read all implementation files and combine them
        impl_files = self._docs.engineer_find_artifacts(workspace_path, issue_id)
        if impl_files:
            combined_content = []
            for impl_path in impl_files:
                content = impl_path.read_text(encoding="utf-8")
                combined_content.append(f"## {impl_path.name}\n\n{content}")
            artifacts["implementation_md"] = "\n\n---\n\n".join(combined_content)
        return artifacts

    def _build_upstream_context(
        self,
        requirement: str,
        prd: str,
        bugfix: str,
        system_design: str,
        implementation_plan: str,
        implementation_md: str,
    ) -> str:
        parts = []
        if requirement:
            parts.append(f"requirement_document:\n{requirement}\n")
        else:
            parts.append("NOTE: requirement.md is missing. Use test_scope and test_gaps for any underspecified requirement coverage.\n")

        if prd:
            parts.append(f"existing_prd:\n{prd}\n")
        else:
            parts.append("NOTE: prd.json is missing. Use acceptance_coverage for any missing requirement details.\n")

        if bugfix:
            parts.append(f"existing_bugfix:\n{bugfix}\n")
        else:
            parts.append("NOTE: bugfix.md is not present. Use bugs_found for any missing defect context.\n")

        if system_design:
            parts.append(f"existing_system_design:\n{system_design}\n")
        else:
            parts.append("NOTE: system_design.json is missing. Use test_gaps for any missing design context.\n")

        if implementation_plan:
            parts.append(f"implementation_plan:\n{implementation_plan}\n")
        else:
            parts.append("NOTE: implementation_plan.json is missing. Use test_gaps for any missing implementation breakdown.\n")

        if implementation_md:
            parts.append(f"existing_implementation_report:\n{implementation_md}\n")
        else:
            parts.append("NOTE: implementation.md is not present. Use test_gaps for any missing implementation context.\n")

        return "\n".join(parts)

    def _normalize_payload_keys(self, payload: dict) -> dict:
        normalized = {}
        for key, value in payload.items():
            compact_key = "".join(ch for ch in str(key).lower() if ch.isalnum() or ch == "_")
            target_key = self.KEY_ALIASES.get(compact_key, self.KEY_ALIASES.get(str(key), key))
            normalized[target_key] = value
        return normalized

    def _render_qa_report_markdown(self, report: QAReportDocument) -> str:
        lines = [
            f"# QA Report: {report.issue_title}",
            "",
            f"- Project: {report.project_name}",
            f"- Issue ID: {report.issue_id}",
            f"- Language: {report.language}",
            f"- Status: {report.status}",
            "",
            "## Test Scope",
            report.test_scope,
            "",
            "## Acceptance Coverage",
        ]
        lines.extend([f"- {c}" for c in report.acceptance_coverage] or ["- None"])
        lines.extend(["", "## Commands Run"])
        lines.extend([f"- `{c}`" for c in report.commands_run] or ["- None"])
        lines.extend(["", "## Recommended Commands"])
        lines.extend([f"- `{c}`" for c in report.recommended_commands] or ["- None"])
        lines.extend(["", "## Manual Scenarios"])
        lines.extend([f"- {s}" for s in report.manual_scenarios] or ["- None"])
        lines.extend(["", "## Bugs Found"])
        lines.extend([f"- {b}" for b in report.bugs_found] or ["- None"])
        lines.extend(["", "## Risks"])
        lines.extend([f"- {r}" for r in report.risks] or ["- None"])
        lines.extend(["", "## Test Gaps"])
        lines.extend([f"- {g}" for g in report.test_gaps] or ["- None"])
        lines.extend(["", "## Final Recommendation"])
        lines.append(report.final_recommendation)
        lines.append("")
        return "\n".join(lines)
