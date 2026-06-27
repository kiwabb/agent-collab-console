from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.application.agent_catalog.catalog import AgentCatalog, AgentDefinition
from app.application.issue_artifact_documents import IssueArtifactDocuments


class GenericSpecialistWorkflowError(ValueError):
    pass


@dataclass
class SpecialistReportDocument:
    role_key: str
    artifact: dict[str, Any]
    written_files: list[dict]
    clarification_question: str | None = None


class GenericSpecialistWorkflow:
    """Common persistence path for catalog-driven specialists and custom agents."""

    def __init__(self, catalog: AgentCatalog | None = None) -> None:
        self._catalog = catalog or AgentCatalog()
        self._docs = IssueArtifactDocuments()

    def build_prompt(self, task, workspace_title: str | None = None) -> str:
        definition = self._resolve_definition(getattr(task, "role", ""))
        issue_id = getattr(task, "issue_id", None) or getattr(task, "id", "")
        return (
            f"You are {definition.display_name}, a specialist agent in an agent mesh.\n"
            "Produce exactly one JSON object matching this output_schema. Do not wrap it in markdown.\n\n"
            f"project_name: {workspace_title or 'workspace-project'}\n"
            f"issue_id: {issue_id}\n"
            f"issue_title: {getattr(task, 'title', '')}\n\n"
            f"output_schema:\n{json.dumps(definition.output_schema, ensure_ascii=False, indent=2)}\n\n"
            f"specialist_instructions:\n{definition.prompt_template}\n\n"
            f"user_requirement:\n{getattr(task, 'prompt', '')}"
        )

    def persist_result(self, task, workspace_title: str | None = None) -> SpecialistReportDocument:
        if not getattr(task, "workspace_path", None):
            raise GenericSpecialistWorkflowError(
                "Task workspace_path is required for specialist artifacts"
            )
        if not getattr(task, "result", None) or not str(task.result).strip():
            raise GenericSpecialistWorkflowError("Specialist task result is empty")

        definition = self._resolve_definition(getattr(task, "role", ""))
        try:
            from app.application.tolerant_json import tolerant_json_loads

            payload = tolerant_json_loads(task.result)
        except json.JSONDecodeError as exc:
            raise GenericSpecialistWorkflowError(
                f"Specialist output is not valid JSON: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise GenericSpecialistWorkflowError("Specialist output must be a JSON object")

        issue_id = getattr(task, "issue_id", None) or task.id
        artifact_path = self._docs.specialist_artifact_path(
            task.workspace_path,
            issue_id,
            definition.role_key,
            task.id,
        )
        artifact_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        rel_name = f"specialists/{definition.role_key}/{task.id}.json"
        task.result = (
            f"Specialist {definition.role_key} report generated. File: {artifact_path.name}."
        )
        return SpecialistReportDocument(
            role_key=definition.role_key,
            artifact=payload,
            written_files=[{"name": rel_name, "path": str(artifact_path), "kind": "specialist"}],
            clarification_question=payload.get("clarification_question"),
        )

    def _resolve_definition(self, role: str) -> AgentDefinition:
        try:
            return self._catalog.resolve_agent(role)
        except KeyError:
            if role.startswith("custom:"):
                return AgentDefinition(
                    role_key=role,
                    display_name=role.removeprefix("custom:").replace("_", " ").title(),
                    prompt_template="Run this custom specialist task and return structured JSON.",
                    output_schema={"type": "object"},
                    agent_tier="custom",
                )
            raise
