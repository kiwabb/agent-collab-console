from __future__ import annotations

import json

from pydantic import BaseModel, Field, ValidationError

from app.application.issue_artifact_documents import IssueArtifactDocuments


class ArchitectWorkflowError(ValueError):
    pass


class ImplementationTask(BaseModel):
    title: str
    description: str
    priority: str = "P1"


class SystemDesignDocument(BaseModel):
    language: str = "zh-CN"
    project_name: str
    issue_id: str
    issue_title: str
    architecture_summary: str
    components: list[str]
    data_models: list[str]
    interfaces: list[str]
    data_flow: str
    implementation_tasks: list[ImplementationTask]
    development_task_list: list[str]
    risks: list[str]
    open_questions: list[str]


class ReviewReportDocument(BaseModel):
    language: str = "zh-CN"
    project_name: str
    issue_id: str
    issue_title: str
    decision: str = Field(pattern="^(approve|reject)$")
    reason: str
    suggestions: list[str]
    risks_identified: list[str]


class ArchitectWorkflow:
    """Builds Architect prompts and persists Architect artifacts."""

    KEY_ALIASES = {
        "language": "language",
        "projectname": "project_name",
        "project_name": "project_name",
        "issueid": "issue_id",
        "issue_id": "issue_id",
        "issuetitle": "issue_title",
        "issue_title": "issue_title",
        "architecturesummary": "architecture_summary",
        "architecture_summary": "architecture_summary",
        "components": "components",
        "datamodels": "data_models",
        "data_models": "data_models",
        "interfaces": "interfaces",
        "dataflow": "data_flow",
        "data_flow": "data_flow",
        "implementationtasks": "implementation_tasks",
        "implementation_tasks": "implementation_tasks",
        "developmenttasklist": "development_task_list",
        "development_task_list": "development_task_list",
        "risks": "risks",
        "openquestions": "open_questions",
        "open_questions": "open_questions",
    }

    def __init__(self) -> None:
        self._docs = IssueArtifactDocuments()

    def build_prompt(self, task, workspace_title: str | None = None) -> str:
        project_name = workspace_title or "workspace-project"
        issue_id = task.issue_id or task.id

        if getattr(task, "task_kind", "normal") == "review":
            return self._build_review_prompt(task, project_name, issue_id)

        pm_artifacts = self._read_pm_artifacts(task.workspace_path, issue_id)
        existing_design = self._read_existing_design_artifacts(task.workspace_path, issue_id)

        requirement_text = pm_artifacts.get("requirement", "")
        prd_text = pm_artifacts.get("prd", "")
        bugfix_text = pm_artifacts.get("bugfix", "")
        existing_design_json = existing_design.get("system_design_json", "")
        existing_impl_plan = existing_design.get("implementation_plan", "")

        upstream_context = self._build_upstream_context(
            requirement_text, prd_text, bugfix_text, existing_design_json, existing_impl_plan
        )

        is_update = bool(existing_design_json)

        return (
            "You are acting as Architect. Follow a MetaGPT-style architecture workflow: "
            "analyze requirements, design the system, and produce exactly one JSON object that matches the required schema. "
            "Do not wrap it in markdown. Use the same language as the user requirement when possible.\n\n"
            f"project_name: {project_name}\n"
            f"issue_id: {issue_id}\n"
            f"issue_title: {task.title}\n"
            f"is_design_update: {is_update}\n\n"
            f"{upstream_context}\n\n"
            "IMPORTANT - TASK GRANULARITY GUIDELINES:\n"
            "1. For SINGLE-FILE projects (e.g., standalone HTML page, single Python script, simple demo):\n"
            "   - Create 1-2 COARSE-GRAINED tasks that group related functionality\n"
            "   - Example: Task 1 'Implement complete HTML demo with sorting logic and visualization'\n"
            "   - Avoid splitting into many small tasks like 'build structure', 'add logic', 'add styling' separately\n"
            "2. For MULTI-FILE projects (e.g., web applications, APIs, microservices):\n"
            "   - Create FINE-GRAINED tasks organized by modules, components, or layers\n"
            "   - Example: Task 1 'Implement user authentication module', Task 2 'Implement data access layer'\n"
            "3. Task descriptions should be CLEAR about scope and boundaries:\n"
            "   - Good: 'Implement user login API endpoint with JWT authentication'\n"
            "   - Bad: 'Build authentication' (too vague, unclear boundary)\n"
            "4. Consider the natural cohesion of the work:\n"
            "   - If functionality naturally belongs together in one file, keep it in one task\n"
            "   - If functionality spans multiple modules/files, split into separate tasks\n\n"
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
            '"architecture_summary": "string",\n'
            '"components": ["string"],\n'
            '"data_models": ["string"],\n'
            '"interfaces": ["string"],\n'
            '"data_flow": "string",\n'
            '"implementation_tasks": [{"title": "string", "description": "string", "priority": "P0|P1|P2"}],\n'
            '"development_task_list": ["string"], // MUST exactly match the titles in implementation_tasks in the desired order of execution\n'
            '"risks": ["string"],\n'
            '"open_questions": ["string"]\n'
            "}\n\n"
            f"user_requirement:\n{task.prompt}"
        )

    def persist_result(self, task, workspace_title: str | None = None) -> SystemDesignDocument:
        if not task.workspace_path:
            raise ArchitectWorkflowError("Task workspace_path is required for Architect artifacts")
        if not task.result or not task.result.strip():
            raise ArchitectWorkflowError("Architect task result is empty")

        canonical_issue_id = task.issue_id or task.id

        try:
            payload = json.loads(task.result)
        except json.JSONDecodeError as exc:
            raise ArchitectWorkflowError(f"Architect output is not valid JSON: {exc}") from exc

        payload = self._normalize_payload_keys(payload)

        payload.setdefault("project_name", workspace_title or "workspace-project")
        payload.setdefault("issue_id", canonical_issue_id)
        payload.setdefault("issue_title", task.title)

        try:
            if getattr(task, "task_kind", "normal") == "review":
                report = ReviewReportDocument.model_validate(payload)
                task.result = f"Review completed: {report.decision}. Reason: {report.reason}"
                # For review tasks, there are no artifact files written, so written_files is empty
                object.__setattr__(report, "written_files", [])
                return report
            design = SystemDesignDocument.model_validate(payload)
        except ValidationError as exc:
            raise ArchitectWorkflowError(f"Architect output does not match schema: {exc}") from exc

        # Validate development_task_list
        self._validate_development_task_list(design)

        self._docs.ensure_issue_root(task.workspace_path, canonical_issue_id)

        design_json_path = self._docs.architect_system_design_json_path(task.workspace_path, canonical_issue_id)
        design_md_path = self._docs.architect_system_design_md_path(task.workspace_path, canonical_issue_id)
        impl_plan_path = self._docs.architect_implementation_plan_path(task.workspace_path, canonical_issue_id)
        dev_task_list_path = self._docs.architect_development_task_list_path(task.workspace_path, canonical_issue_id)

        design_json_path.write_text(design.model_dump_json(indent=2), encoding="utf-8")
        design_md_path.write_text(self._render_design_markdown(design), encoding="utf-8")
        impl_plan_path.write_text(self._render_implementation_plan(design), encoding="utf-8")
        dev_task_list_path.write_text(json.dumps(design.development_task_list, indent=2, ensure_ascii=False), encoding="utf-8")

        task.result = (
            f"System design generated for {design.issue_title}. "
            f"Files: {design_json_path.name}, {design_md_path.name}, {impl_plan_path.name}, {dev_task_list_path.name}."
        )
        # Attach written_files to the payload using object.__setattr__ to bypass Pydantic validation
        object.__setattr__(design, "written_files", [
            {"name": "architect/system_design.json", "path": str(design_json_path), "kind": "architecture"},
            {"name": "architect/system_design.md", "path": str(design_md_path), "kind": "architecture"},
            {"name": "architect/implementation_plan.json", "path": str(impl_plan_path), "kind": "architecture"},
            {"name": "architect/development_task_list.json", "path": str(dev_task_list_path), "kind": "architecture"},
        ])
        return design

    def _validate_development_task_list(self, design: SystemDesignDocument) -> None:
        """Validate development_task_list against implementation_tasks."""
        dev_list = design.development_task_list
        impl_tasks = design.implementation_tasks
        impl_titles = [task.title for task in impl_tasks]

        # Check non-empty
        if not dev_list:
            raise ArchitectWorkflowError("development_task_list 不能为空")

        # Check no duplicates in development_task_list
        if len(dev_list) != len(set(dev_list)):
            raise ArchitectWorkflowError("development_task_list 包含重复的 title")

        # Check no duplicates in implementation_tasks
        if len(impl_titles) != len(set(impl_titles)):
            raise ArchitectWorkflowError("implementation_tasks 包含重复的 title")

        # Check exact match with implementation_tasks
        dev_set = set(dev_list)
        impl_set = set(impl_titles)
        if dev_set != impl_set:
            # AUTO-REPAIR: If counts match, assume dev_list titles were just paraphrased and align them to impl_titles
            if len(dev_list) == len(impl_titles):
                print(f"DEBUG: Auto-aligning paraphrased development_task_list titles to match implementation_tasks for issue {design.issue_id}")
                design.development_task_list = impl_titles
                return

            missing_in_dev = impl_set - dev_set
            extra_in_dev = dev_set - impl_set
            msg_parts = []
            if missing_in_dev:
                msg_parts.append(f"缺少: {missing_in_dev}")
            if extra_in_dev:
                msg_parts.append(f"多余: {extra_in_dev}")
            raise ArchitectWorkflowError(f"development_task_list 与 implementation_tasks 不匹配。{'; '.join(msg_parts)}")


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

    def _read_existing_design_artifacts(self, workspace_path: str, issue_id: str) -> dict[str, str]:
        artifacts: dict[str, str] = {}
        design_json_path = self._docs.architect_system_design_json_path(workspace_path, issue_id)
        if design_json_path.exists():
            artifacts["system_design_json"] = design_json_path.read_text(encoding="utf-8")
        impl_plan_path = self._docs.architect_implementation_plan_path(workspace_path, issue_id)
        if impl_plan_path.exists():
            artifacts["implementation_plan"] = impl_plan_path.read_text(encoding="utf-8")
        return artifacts

    def _build_review_prompt(self, task, project_name: str, issue_id: str) -> str:
        pm_artifacts = self._read_pm_artifacts(task.workspace_path, issue_id)
        architect_artifacts = self._read_existing_design_artifacts(task.workspace_path, issue_id)
        engineer_artifacts = self._read_engineer_artifacts(task.workspace_path, issue_id)

        return (
            "You are acting as Architect performing a Code Review. "
            "Examine the requirements, the system design, and the engineer's implementation report. "
            "Verify if the implementation covers the required scope and follows the design. "
            "Provide exactly one JSON object with your decision (approve/reject) and detailed reasoning.\n\n"
            f"project_name: {project_name}\n"
            f"issue_id: {issue_id}\n"
            f"issue_title: {task.title}\n\n"
            "context_documents:\n"
            f"requirement: {pm_artifacts.get('requirement', 'N/A')}\n"
            f"system_design: {architect_artifacts.get('system_design_json', 'N/A')}\n"
            f"implementation_report: {engineer_artifacts.get('implementation_md', 'N/A')}\n\n"
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
            '"decision": "approve|reject",\n'
            '"reason": "string",\n'
            '"suggestions": ["string"],\n'
            '"risks_identified": ["string"]\n'
            "}\n\n"
            "Task: Review the changes and provide the decision JSON."
        )

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
        existing_design: str,
        existing_impl_plan: str,
    ) -> str:
        parts = []
        if requirement:
            parts.append(f"requirement_document:\n{requirement}\n")
        else:
            parts.append("NOTE: requirement.md is missing. Treat this as an underspecified requirement.\n")

        if prd:
            parts.append(f"existing_prd:\n{prd}\n")
        else:
            parts.append("NOTE: prd.json is missing. Include open_questions for any missing requirement details.\n")

        if bugfix:
            parts.append(f"existing_bugfix:\n{bugfix}\n")
        else:
            parts.append("NOTE: bugfix.md is not present. Include open_questions for any missing defect context.\n")

        if existing_design:
            parts.append(f"existing_system_design (update):\n{existing_design}\n")
        if existing_impl_plan:
            parts.append(f"existing_implementation_plan:\n{existing_impl_plan}\n")

        return "\n".join(parts)

    def _normalize_payload_keys(self, payload: dict) -> dict:
        normalized = {}
        for key, value in payload.items():
            compact_key = "".join(ch for ch in str(key).lower() if ch.isalnum() or ch == "_")
            target_key = self.KEY_ALIASES.get(compact_key, self.KEY_ALIASES.get(str(key), key))
            normalized[target_key] = value
        return normalized

    def _render_design_markdown(self, design: SystemDesignDocument) -> str:
        lines = [
            f"# System Design: {design.issue_title}",
            "",
            f"- Project: {design.project_name}",
            f"- Issue ID: {design.issue_id}",
            f"- Language: {design.language}",
            "",
            "## Architecture Summary",
            design.architecture_summary,
            "",
            "## Components",
        ]
        lines.extend([f"- {c}" for c in design.components] or ["- None"])
        lines.extend(["", "## Data Models"])
        lines.extend([f"- {m}" for m in design.data_models] or ["- None"])
        lines.extend(["", "## Interfaces"])
        lines.extend([f"- {i}" for i in design.interfaces] or ["- None"])
        lines.extend(["", "## Data Flow", design.data_flow or "Not specified", "", "## Risks"])
        lines.extend([f"- {r}" for r in design.risks] or ["- None"])
        lines.extend(["", "## Open Questions"])
        lines.extend([f"- {q}" for q in design.open_questions] or ["- None"])
        lines.append("")
        return "\n".join(lines)

    def _render_implementation_plan(self, design: SystemDesignDocument) -> str:
        tasks = design.implementation_tasks or []
        if not tasks:
            return "[]"
        return json.dumps(
            [{"title": t.title, "description": t.description, "priority": t.priority} for t in tasks],
            indent=2,
            ensure_ascii=False,
        )
