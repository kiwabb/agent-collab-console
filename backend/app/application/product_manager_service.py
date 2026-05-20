from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from app.application.product_manager_documents import ProductManagerDocuments
from app.application.product_manager_router import ProductManagerRouter, RequirementRoute


class PRDRequirement(BaseModel):
    priority: str
    title: str
    description: str


class ProductRequirementDocument(BaseModel):
    language: str = "zh-CN"
    project_name: str
    issue_id: str
    issue_title: str
    original_requirements: str
    plan_summary: list[str] = Field(default_factory=list)
    product_goals: list[str] = Field(default_factory=list)
    user_stories: list[str] = Field(default_factory=list)
    requirement_analysis: str
    requirement_pool: list[PRDRequirement] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    # Set this when you cannot reasonably proceed without user input.
    # The framework will pause the pipeline and re-run you once answered.
    clarification_question: str | None = None
    # Phase 4: multi-instance engineer fan-out.
    # Populate when the issue naturally decomposes into independent parallel
    # workstreams that can each be assigned to a separate engineer agent.
    # Each dict: {"title": str, "scope": str, "role_suffix": str}
    # e.g. [{"title":"Frontend", "scope":"UI layer", "role_suffix":"frontend"},
    #        {"title":"Backend",  "scope":"API layer", "role_suffix":"backend"}]
    # Leave null (omit) for single-engineer issues.
    subtask_split: list[dict] | None = None


class BugfixRequirementDocument(BaseModel):
    language: str = "zh-CN"
    project_name: str
    issue_id: str
    issue_title: str
    original_requirements: str
    problem_statement: str
    suspected_impact: str
    reproduction_notes: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class ProductManagerArtifactError(ValueError):
    pass


class ProductManagerService:
    PRD_KEY_ALIASES = {
        "language": "language",
        "projectname": "project_name",
        "project_name": "project_name",
        "issueid": "issue_id",
        "issue_id": "issue_id",
        "issuetitle": "issue_title",
        "issue_title": "issue_title",
        "originalrequirements": "original_requirements",
        "original_requirements": "original_requirements",
        "plansummary": "plan_summary",
        "plan_summary": "plan_summary",
        "productgoals": "product_goals",
        "product_goals": "product_goals",
        "userstories": "user_stories",
        "user_stories": "user_stories",
        "requirementanalysis": "requirement_analysis",
        "requirement_analysis": "requirement_analysis",
        "requirementpool": "requirement_pool",
        "requirement_pool": "requirement_pool",
        "acceptancecriteria": "acceptance_criteria",
        "acceptance_criteria": "acceptance_criteria",
        "constraints": "constraints",
        "openquestions": "open_questions",
        "open_questions": "open_questions",
        "risks": "risks",
        "subtasksplit": "subtask_split",
        "subtask_split": "subtask_split",
    }
    BUGFIX_KEY_ALIASES = {
        "language": "language",
        "projectname": "project_name",
        "project_name": "project_name",
        "issueid": "issue_id",
        "issue_id": "issue_id",
        "issuetitle": "issue_title",
        "issue_title": "issue_title",
        "originalrequirements": "original_requirements",
        "original_requirements": "original_requirements",
        "problemstatement": "problem_statement",
        "problem_statement": "problem_statement",
        "suspectedimpact": "suspected_impact",
        "suspected_impact": "suspected_impact",
        "reproductionnotes": "reproduction_notes",
        "reproduction_notes": "reproduction_notes",
        "acceptancecriteria": "acceptance_criteria",
        "acceptance_criteria": "acceptance_criteria",
        "risks": "risks",
    }

    def __init__(self):
        self.documents = ProductManagerDocuments()
        self.router = ProductManagerRouter(self.documents)

    def build_prompt(self, task, workspace_title: str | None = None) -> str:
        project_name = workspace_title or "workspace-project"
        issue_id = task.issue_id or task.id
        self.prepare_documents(
            issue_id=issue_id,
            issue_title=task.title,
            issue_description=getattr(task, "description", None),
            workspace_path=task.workspace_path,
            prompt=task.prompt,
        )
        route = self.route_requirement(
            prompt=task.prompt,
            workspace_path=task.workspace_path,
            issue_id=issue_id,
        )
        requirement_document = ""
        if route.requirement_path.exists():
            requirement_document = route.requirement_path.read_text(encoding="utf-8")
        route_instructions = self._build_route_instructions(route)
        existing_prd_text = ""
        if route.existing_prd_path and route.existing_prd_path.exists():
            existing_prd_text = route.existing_prd_path.read_text(encoding="utf-8")
        return (
            "You are acting as ProductManager. Follow a MetaGPT-style flow: "
            "first use the prepared requirement document, then produce exactly one JSON object that matches the required schema. "
            "Do not wrap it in markdown. Use the same language as the user requirement when possible.\n\n"
            f"project_name: {project_name}\n"
            f"issue_id: {issue_id}\n"
            f"issue_title: {task.title}\n"
            f"requirement_route: {route.name}\n"
            f"requirement_document_path: {route.requirement_path}\n"
            f"existing_prd_path: {route.existing_prd_path or ''}\n"
            f"workflow_stage: PrepareDocuments -> {self._route_stage_name(route)}\n\n"
            f"{route_instructions}\n\n"
            "requirement_document:\n"
            f"{requirement_document}\n\n"
            "existing_prd:\n"
            f"{existing_prd_text}\n\n"
            f"user_requirement:\n{task.prompt}"
        )

    def prepare_documents(
        self,
        *,
        issue_id: str,
        issue_title: str,
        issue_description: str | None,
        workspace_path: str,
        prompt: str,
    ) -> Path:
        issue_root = self.documents.ensure_issue_root(workspace_path, issue_id)
        requirement_path = self.documents.requirement_path(workspace_path, issue_id)
        content = (
            "# Requirement\n\n"
            f"## Issue\n{issue_title}\n\n"
            f"## Description\n{issue_description or ''}\n\n"
            f"## Prompt\n{prompt}\n"
        )
        requirement_path.write_text(content, encoding="utf-8")
        return requirement_path

    def classify_requirement(
        self,
        prompt: str,
        *,
        workspace_path: str | None = None,
        issue_id: str | None = None,
    ) -> str:
        if not workspace_path or not issue_id:
            return "bugfix" if self._is_bugfix_prompt(prompt) else "new_requirement"
        return self.route_requirement(prompt=prompt, workspace_path=workspace_path, issue_id=issue_id).name

    def route_requirement(self, *, prompt: str, workspace_path: str, issue_id: str) -> RequirementRoute:
        return self.router.route_requirement(prompt=prompt, workspace_path=workspace_path, issue_id=issue_id)

    def merge_with_existing_prd(self, *, existing_prd_path: Path, new_payload: dict) -> dict:
        existing = json.loads(existing_prd_path.read_text(encoding="utf-8"))
        return {**existing, **new_payload}

    def persist_bugfix_artifact(self, task) -> Path:
        issue_id = task.issue_id or task.id
        self.documents.ensure_issue_root(task.workspace_path, issue_id)
        bugfix_path = self.documents.bugfix_path(task.workspace_path, issue_id)
        payload = self._parse_bugfix_payload(task)
        bugfix_path.write_text(self.render_bugfix_markdown(payload), encoding="utf-8")
        task.result = (
            f"Bugfix document generated for {payload.issue_title}. "
            f"File: {bugfix_path.name}. Acceptance Criteria: {len(payload.acceptance_criteria)}."
        )
        return bugfix_path

    def persist_prd_from_result(self, task, workspace_title: str | None = None) -> ProductRequirementDocument:
        if not task.workspace_path:
            raise ProductManagerArtifactError("Task workspace_path is required for ProductManager artifacts")
        if not task.result or not task.result.strip():
            raise ProductManagerArtifactError("ProductManager task result is empty")

        canonical_issue_id = task.issue_id or task.id
        self.prepare_documents(
            issue_id=canonical_issue_id,
            issue_title=task.title,
            issue_description=getattr(task, "description", None),
            workspace_path=task.workspace_path,
            prompt=task.prompt,
        )
        route = self.route_requirement(
            prompt=task.prompt,
            workspace_path=task.workspace_path,
            issue_id=canonical_issue_id,
        )
        if route.name == "bugfix":
            bugfix_md_path = self.persist_bugfix_artifact(task)
            bugfix_payload = ProductRequirementDocument(
                language="zh-CN",
                project_name=workspace_title or "workspace-project",
                issue_id=canonical_issue_id,
                issue_title=task.title,
                original_requirements=task.prompt,
                plan_summary=[],
                product_goals=[],
                user_stories=[],
                requirement_analysis="bugfix",
                requirement_pool=[],
                acceptance_criteria=[],
                constraints=[],
                open_questions=[],
                risks=[],
            )
            # Attach written_files to the payload using object.__setattr__ to bypass Pydantic validation
            object.__setattr__(bugfix_payload, "written_files", [
                {"name": "pm/bugfix.md", "path": str(bugfix_md_path), "kind": "product"}
            ])
            return bugfix_payload

        try:
            from app.application.tolerant_json import tolerant_json_loads
            payload = tolerant_json_loads(task.result)
            prd = ProductRequirementDocument.model_validate(payload)
            if not prd.plan_summary:
                fallback_plan = []
                if getattr(prd, "development_task_list", None):
                    fallback_plan = list(prd.development_task_list[:10])
                elif prd.product_goals:
                    fallback_plan = list(prd.product_goals[:10])
                if not fallback_plan:
                    fallback_plan = [task.title]
                prd.plan_summary = [
                    item if str(item).strip().startswith("-") else f"- {item}"
                    for item in fallback_plan
                ][:10]
            prd_json_path = self.documents.prd_json_path(task.workspace_path, canonical_issue_id)
            prd_md_path = self.documents.prd_md_path(task.workspace_path, canonical_issue_id)
            self.documents.ensure_issue_root(task.workspace_path, canonical_issue_id)

            if route.name == "requirement_update" and prd_json_path.exists():
                payload = self.merge_with_existing_prd(existing_prd_path=prd_json_path, new_payload=payload)
                prd = ProductRequirementDocument.model_validate(payload)

            prd_json_path.write_text(prd.model_dump_json(indent=2), encoding="utf-8")
            prd_md_path.write_text(self.render_markdown(prd), encoding="utf-8")
            task.result = self.build_summary(prd, prd_json_path, prd_md_path)
            # Attach written_files to the payload using object.__setattr__ to bypass Pydantic validation
            object.__setattr__(prd, "written_files", [
                {"name": "pm/prd.json", "path": str(prd_json_path), "kind": "product"},
                {"name": "pm/prd.md", "path": str(prd_md_path), "kind": "product"},
            ])
            return prd
        except (json.JSONDecodeError, ValidationError) as exc:
            # LLM returned invalid JSON or content that doesn't match the PRD schema
            import logging
            logger = logging.getLogger(__name__)

            self.documents.ensure_issue_root(task.workspace_path, canonical_issue_id)
            prd_md_path = self.documents.prd_md_path(task.workspace_path, canonical_issue_id)

            error_msg = f"Failed to parse PRD JSON for task {task.id}: {type(exc).__name__}: {exc}"
            logger.error(error_msg)

            # Save raw output for debugging (chat runs are guarded by EP.kind upstream
            # so they never reach this persist_result, see codex_task_runner / _mark_task_done).
            prd_md_path.write_text(task.result or "(empty response)", encoding="utf-8")

            error_details_parts = [
                f"ProductManager 返回了无效的 PRD 格式",
                f"",
                f"错误类型: {type(exc).__name__}",
                f"错误详情: {str(exc)}",
            ]

            if isinstance(exc, ValidationError):
                field_errors = []
                for err in exc.errors():
                    loc = ".".join(str(l) for l in err.get("loc", []))
                    msg = err.get("msg", "")
                    input_type = err.get("type", "")
                    field_errors.append(f"  - {loc}: {msg} (input_type={input_type})")
                if field_errors:
                    error_details_parts.extend([
                        "",
                        f"字段验证错误 ({len(field_errors)} 个):",
                        *field_errors,
                    ])
            elif isinstance(exc, json.JSONDecodeError):
                error_details_parts.extend([
                    "",
                    f"JSON 解析失败位置: 第 {exc.lineno} 行, 第 {exc.colno} 列 (字符位置 {exc.pos})",
                ])
                # Show context around the error position
                if task.result:
                    start = max(0, exc.pos - 50)
                    end = min(len(task.result), exc.pos + 50)
                    context = task.result[start:end]
                    error_details_parts.extend([
                        f"错误上下文 (字符 {start}-{end}):",
                        f"  {repr(context)}",
                    ])

            error_details_parts.extend([
                "",
                f"原始输出已保存到: {prd_md_path}",
                "",
                f"可能的原因：",
                f"1. LLM 返回了空响应（检查 API 配置和额度）",
                f"2. LLM 返回了非 JSON 格式的文本",
                f"3. LLM 返回的 JSON 格式不正确或缺少必需字段",
                f"4. Prompt 可能需要调整以确保返回正确的 JSON 格式",
            ])

            error_details = "\n".join(error_details_parts)

            raise ProductManagerArtifactError(error_details) from exc

    def _validate_prd_content(self, prd: ProductRequirementDocument) -> None:
        has_structured_content = any([
            bool(prd.plan_summary),
            bool(prd.product_goals),
            bool(prd.user_stories),
            bool(prd.requirement_pool),
            bool(prd.acceptance_criteria),
            bool(prd.requirement_analysis.strip()),
        ])
        if not has_structured_content:
            raise ProductManagerArtifactError(
                "ProductManager output is too sparse: PRD must include analysis, goals, stories, requirements, or acceptance criteria"
            )

    def build_summary(self, prd: ProductRequirementDocument, prd_json_path: Path, prd_md_path: Path) -> str:
        return (
            f"PRD generated for {prd.issue_title}. "
            f"Files: {prd_json_path.name}, {prd_md_path.name}. "
            f"Goals: {len(prd.product_goals)}. Requirements: {len(prd.requirement_pool)}."
        )

    def render_markdown(self, prd: ProductRequirementDocument) -> str:
        lines = [
            f"# PRD: {prd.issue_title}",
            "",
            f"- Project: {prd.project_name}",
            f"- Issue ID: {prd.issue_id}",
            f"- Language: {prd.language}",
            "",
            "## Original Requirements",
            prd.original_requirements,
            "",
            "## Plan Summary",
        ]
        lines.extend([f"- {item}" for item in prd.plan_summary] or ["- None"])
        lines.extend([
            "",
            "## Product Goals",
        ])
        lines.extend([f"- {item}" for item in prd.product_goals] or ["- None"])
        lines.extend(["", "## User Stories"])
        lines.extend([f"- {item}" for item in prd.user_stories] or ["- None"])
        lines.extend(["", "## Requirement Analysis", prd.requirement_analysis, "", "## Requirement Pool"])
        if prd.requirement_pool:
            lines.extend([f"- {item.priority} | {item.title}: {item.description}" for item in prd.requirement_pool])
        else:
            lines.append("- None")
        lines.extend(["", "## Acceptance Criteria"])
        lines.extend([f"- {item}" for item in prd.acceptance_criteria] or ["- None"])
        lines.extend(["", "## Constraints"])
        lines.extend([f"- {item}" for item in prd.constraints] or ["- None"])
        lines.extend(["", "## Open Questions"])
        lines.extend([f"- {item}" for item in prd.open_questions] or ["- None"])
        lines.extend(["", "## Risks"])
        lines.extend([f"- {item}" for item in prd.risks] or ["- None"])
        lines.append("")
        return "\n".join(lines)

    def render_bugfix_markdown(self, payload: BugfixRequirementDocument) -> str:
        lines = [
            f"# Bugfix: {payload.issue_title}",
            "",
            f"- Project: {payload.project_name}",
            f"- Issue ID: {payload.issue_id}",
            f"- Language: {payload.language}",
            "",
            "## Original Requirements",
            payload.original_requirements,
            "",
            "## Problem Statement",
            payload.problem_statement,
            "",
            "## Suspected Impact",
            payload.suspected_impact,
            "",
            "## Reproduction Notes",
        ]
        lines.extend([f"- {item}" for item in payload.reproduction_notes] or ["- None"])
        lines.extend(["", "## Acceptance Criteria"])
        lines.extend([f"- {item}" for item in payload.acceptance_criteria] or ["- None"])
        lines.extend(["", "## Risks"])
        lines.extend([f"- {item}" for item in payload.risks] or ["- None"])
        lines.append("")
        return "\n".join(lines)

    def _parse_bugfix_payload(self, task) -> BugfixRequirementDocument:
        try:
            payload = json.loads(task.result)
        except json.JSONDecodeError as exc:
            raise ProductManagerArtifactError(f"ProductManager output is not valid JSON: {exc}") from exc
        payload = self._normalize_payload_keys(payload, self.BUGFIX_KEY_ALIASES)

        payload.setdefault("project_name", "workspace-project")
        payload.setdefault("issue_id", task.issue_id or task.id)
        payload.setdefault("issue_title", task.title)
        payload.setdefault("original_requirements", task.prompt)

        try:
            return BugfixRequirementDocument.model_validate(payload)
        except ValidationError as exc:
            raise ProductManagerArtifactError(f"ProductManager bugfix output does not match schema: {exc}") from exc

    def _route_stage_name(self, route: RequirementRoute) -> str:
        if route.name == "bugfix":
            return "WriteBugfix"
        if route.name == "requirement_update":
            return "UpdatePRD"
        return "WritePRD"

    def _is_bugfix_prompt(self, prompt: str) -> bool:
        lowered = (prompt or "").lower()
        return any(token in lowered for token in self.router.BUGFIX_TOKENS)

    def _build_route_instructions(self, route: RequirementRoute) -> str:
        if route.name == "bugfix":
            return (
                "OUTPUT FORMAT RULES:\n"
                "- Output the JSON object directly. Do NOT wrap it in markdown code blocks (no ```json or ```).\n"
                "- The entire response must be a single raw JSON object starting with { and ending with }.\n"
                "- Do NOT write any analysis, summary, or explanation text before or after the JSON.\n"
                "- STOP immediately after outputting the closing }. No additional text or commands.\n\n"
                "required_schema: {"
                '"language": "string", '
                '"project_name": "string", '
                '"issue_id": "string", '
                '"issue_title": "string", '
                '"original_requirements": "string", '
                '"plan_summary": ["string"], '
                '"problem_statement": "string", '
                '"suspected_impact": "string", '
                '"reproduction_notes": ["string"], '
                '"acceptance_criteria": ["string"], '
                '"risks": ["string"]'
                "}\n"
                "Focus on root problem, impact, reproduction notes, and what success looks like after the fix."
            )
        return (
            "OUTPUT FORMAT RULES:\n"
            "- Output the JSON object directly. Do NOT wrap it in markdown code blocks (no ```json or ```).\n"
            "- The entire response must be a single raw JSON object starting with { and ending with }.\n"
            "- Do NOT write any analysis, summary, or explanation text before or after the JSON.\n"
            "- STOP immediately after outputting the closing }. No additional text or commands.\n\n"
            "required_schema: {"
            '"language": "string", '
            '"project_name": "string", '
            '"issue_id": "string", '
            '"issue_title": "string", '
            '"original_requirements": "string", '
            '"plan_summary": ["string"], '
            '"product_goals": ["string"], '
            '"user_stories": ["string"], '
            '"requirement_analysis": "string", '
            '"requirement_pool": [{"priority": "P0|P1|P2", "title": "string", "description": "string"}], '
            '"acceptance_criteria": ["string"], '
            '"constraints": ["string"], '
            '"open_questions": ["string"], '
            '"risks": ["string"], '
            '"subtask_split": [{"title": "string", "scope": "string", "role_suffix": "string"}] | null'
            "}\n"
            "The PRD must contain meaningful content. Do not return all-empty arrays and an empty requirement_analysis; "
            "include at least one concrete product goal, user story, requirement, acceptance criterion, or analysis sentence.\n"
            "SUBTASK SPLIT INSTRUCTIONS: Only populate subtask_split when the issue CLEARLY decomposes into 2-3 "
            "independent parallel workstreams (e.g. a full-stack feature with separable frontend and backend). "
            "Each entry needs: title (short human label), scope (one sentence on what this workstream covers), "
            "role_suffix (short lowercase identifier like 'frontend', 'backend', 'mobile'). "
            "For single-scope issues, bugs, refactors, and docs: set subtask_split to null.\n"
            + (
                "Update the existing PRD in-place. Preserve still-valid fields and only change what the new requirement affects."
                if route.name == "requirement_update"
                else "Create a new PRD from the prepared requirement document."
            )
        )

    def _normalize_payload_keys(self, payload: dict, aliases: dict[str, str]) -> dict:
        normalized = {}
        for key, value in payload.items():
            compact_key = "".join(ch for ch in str(key).lower() if ch.isalnum() or ch == "_")
            target_key = aliases.get(compact_key, aliases.get(str(key), key))
            normalized[target_key] = value
        return normalized
