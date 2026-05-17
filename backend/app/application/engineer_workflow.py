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
    # Set this when you cannot reasonably proceed without user input.
    # The framework will pause the pipeline and re-run you once answered.
    clarification_question: str | None = None


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
            "EFFICIENCY RULES - FOLLOW STRICTLY TO AVOID CONTEXT OVERFLOW:\n"
            "1. NEVER read a file that exceeds 200 lines in full. Use Bash grep/find to locate the specific section you need, then read only that range with offset+limit.\n"
            "2. Before reading any file, check its line count with `wc -l`. If it exceeds 200 lines, use grep to find relevant symbols instead.\n"
            "3. Prefer targeted lookups: grep for function/component names, read only the lines you need.\n"
            "4. Do not explore files out of curiosity — only read what you must modify or directly depend on.\n\n"
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
            + (
                "REWORK REQUIRED - ARCHITECT REVIEW FEEDBACK:\n"
                f"{task.review_comment}\n\n"
                "You MUST address ALL points in the above feedback before producing the final JSON.\n\n"
                if getattr(task, "review_comment", None) else ""
            )
            + "TOOL USE REQUIREMENT (NEW — strictly enforced):\n"
            "- When status will be 'completed' or 'partial', you MUST actually call Write/Edit/Bash tools to modify files in the workspace. A description of what you would do is NOT acceptable.\n"
            "- Before deciding 'changed_files' and the final status, run `git diff --name-only` to confirm which files actually changed under your edits. Use that list verbatim as 'changed_files'.\n"
            "- The system runs a post-execution git-diff cross-check. If you claim 'status=completed' but git diff is empty, the framework will downgrade the status to 'partial' and the Architect Review will see the discrepancy.\n"
            "- 'changed_files=[]' is only acceptable when status='blocked' or when the requirement was already implemented and nothing needed to change (state this explicitly in summary).\n"
            "- DO NOT claim status='blocked' just because pm/requirement.md looks empty — that's a stub file, not the real requirements. The real requirements live in the `existing_prd` section of this prompt (which is read from pm/prd.json). If the existing_prd section above contains a PRD, you have requirements; you must NOT use 'requirements are missing' as a reason to block.\n\n"
            + "OUTPUT FORMAT RULES:\n"
            "- Output the JSON object directly. Do NOT wrap it in markdown code blocks (no ```json or ```).\n"
            "- The entire response must be a single raw JSON object starting with { and ending with }.\n"
            "- STOP immediately after outputting the JSON. Do NOT run any shell commands, read files, or perform any operations after the JSON. The JSON is your complete and final response for this turn.\n\n"
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
            from app.application.tolerant_json import tolerant_json_loads
            payload = tolerant_json_loads(task.result)
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

        # Post-execution cross-check: an Engineer claiming `completed` MUST
        # have produced an actual git diff. If not, downgrade to `partial`
        # and prepend a qa_note flagging the discrepancy. This stops models
        # from declaring victory while only writing a markdown report.
        if report.status == "completed":
            actually_changed = self._git_changed_files(task.workspace_path)
            if not actually_changed:
                report.status = "partial"
                claim_note = (
                    "[framework] Engineer claimed status=completed but git diff against the base "
                    "branch shows no file changes. Downgraded to partial pending real implementation. "
                    f"Claimed changed_files: {report.changed_files!r}"
                )
                # Pydantic models are frozen-ish in v2; mutate via __setattr__.
                report.qa_notes = [claim_note, *list(report.qa_notes or [])]
                report.changed_files = []

        self._docs.ensure_issue_root(task.workspace_path, canonical_issue_id)

        impl_md_path = self._docs.engineer_implementation_md_path(task.workspace_path, canonical_issue_id, task.id)
        impl_md_path.write_text(self._render_implementation_markdown(report), encoding="utf-8")

        task.result = (
            f"Implementation report generated for {report.issue_title}. "
            f"Status: {report.status}. File: {impl_md_path.name}."
        )
        # Attach written_files to the payload using object.__setattr__ to bypass Pydantic validation
        object.__setattr__(report, "written_files", [
            {"name": f"engineer/{impl_md_path.name}", "path": str(impl_md_path), "kind": "development"},
        ])
        return report

    def _git_changed_files(self, workspace_path: str | None) -> list[str]:
        """Return files that differ from the base branch in this worktree.

        Compares against `git merge-base origin/main HEAD` first (most
        common base reference), then `main`, then `HEAD~1`. Returns an
        empty list if no git diff machinery is reachable, which makes the
        post-execution check fail-open rather than fail-closed.
        """
        if not workspace_path:
            return []
        import subprocess
        # Try a few bases in order of preference.
        for base in ("origin/main", "main", "HEAD~1"):
            try:
                result = subprocess.run(
                    ["git", "diff", "--name-only", f"{base}..HEAD"],
                    cwd=workspace_path,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
            except (FileNotFoundError, subprocess.TimeoutExpired):
                return []
            if result.returncode == 0:
                committed = [line.strip() for line in result.stdout.splitlines() if line.strip()]
                # Also include uncommitted working-tree changes the model
                # may not have committed yet.
                try:
                    wt = subprocess.run(
                        ["git", "status", "--porcelain"],
                        cwd=workspace_path,
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    if wt.returncode == 0:
                        wt_files = [
                            line[3:].strip()
                            for line in wt.stdout.splitlines()
                            if line.strip() and not line[3:].startswith("issues/")
                        ]
                        return list({*committed, *wt_files})
                except (FileNotFoundError, subprocess.TimeoutExpired):
                    pass
                return committed
        return []

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
        # `pm/requirement.md` is just a stub template auto-generated when the
        # issue is created — only contains the title + an empty Description
        # field. It's the seed PM reads to *write* the PRD; it is not itself
        # the requirements. When the real PRD is present, suppress the stub
        # so the engineer agent doesn't get tricked into "spec is empty".
        if prd:
            parts.append(f"existing_prd:\n{prd}\n")
            parts.append(
                "IMPORTANT: The PRD above (existing_prd) IS the authoritative "
                "requirements for this task. DO NOT read pm/requirement.md — "
                "that file is just a stub template containing only the issue "
                "title. If you must read upstream files, read pm/prd.json or "
                "pm/prd.md, NOT pm/requirement.md.\n"
            )
        elif requirement:
            parts.append(f"requirement_document:\n{requirement}\n")
        else:
            parts.append(
                "NOTE: Neither pm/prd.json nor pm/requirement.md is present. "
                "Treat this as an underspecified requirement and surface it in qa_notes.\n"
            )

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
