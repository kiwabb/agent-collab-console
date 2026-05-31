from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time

from pydantic import BaseModel, Field, ValidationError

from app.application.issue_artifact_documents import IssueArtifactDocuments
from app.application.qa_failure_summary import format_qa_failure_narrative


logger = logging.getLogger(__name__)


class QAWorkflowError(ValueError):
    pass


# Per-command timeout when executing QA verification commands. Keep short —
# a stuck pytest run shouldn't hold the whole pipeline.
QA_COMMAND_TIMEOUT_S = int(os.getenv("QA_COMMAND_TIMEOUT_S", "120"))
# Total time budget across ALL verification commands for one QA pass.
QA_TOTAL_BUDGET_S = int(os.getenv("QA_TOTAL_BUDGET_S", "300"))
# Whether to actually execute verification commands. Default ON in real-CLI
# mode. Disable for offline tests / quick demos.
QA_EXECUTE_COMMANDS = os.getenv("QA_EXECUTE_COMMANDS", os.getenv("REAL_CLI", "true")).lower() == "true"

# Patterns we refuse to run even if the LLM proposes them. These are the
# obvious foot-guns; the worktree is sandboxed-ish (per-issue branch) but
# never bet the farm on the LLM picking safe commands.
_REFUSED_COMMAND_PATTERNS = [
    re.compile(r"\brm\s+-[rRf]"),
    re.compile(r"\bsudo\b"),
    re.compile(r"\b(curl|wget)\b[^|;]*\|\s*(sh|bash|zsh|python|node)\b"),
    re.compile(r":\(\)\s*\{"),  # fork bomb prefix
    re.compile(r"\bdd\s+if=.*\bof="),
    re.compile(r"\bmkfs\b|\bfdisk\b|\bformat\b"),
    re.compile(r"\bshutdown\b|\breboot\b|\bhalt\b|\bpoweroff\b"),
    re.compile(r"\bgit\s+push\b"),  # the agent should NOT push; user merges.
    re.compile(r"\bgit\s+reset\s+--hard\b"),
    re.compile(r"\b(npm|yarn|pnpm)\s+publish\b"),
    re.compile(r"\bpip\s+install\b.*--user"),  # force into the system env
]


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
    # Set this when you cannot reasonably proceed without user input.
    # The framework will pause the pipeline and re-run you once answered.
    clarification_question: str | None = None
    # Phase 4: Request specialist assistance (e.g., security review) without waiting for Conductor.
    # Set this field to call a specialist agent directly. The specialist will complete,
    # and the QA will resume with the specialist's findings in review_comment.
    call_specialist: dict | None = None  # {"role_key": "security_reviewer", "prompt": "...", "why": "..."}


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
        "callspecialist": "call_specialist",
        "call_specialist": "call_specialist",
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
            from app.application.tolerant_json import tolerant_json_loads
            payload = tolerant_json_loads(task.result)
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

        # Real test execution. The LLM proposed `recommended_commands` based
        # on what it inspected; we now actually run them and let the exit
        # codes drive the final QA verdict instead of trusting the LLM's
        # self-reported status.
        execution_results = self._execute_verification_commands(
            report.recommended_commands, task.workspace_path
        )
        if execution_results is not None:
            real_status, framework_notes = self._reconcile_status_with_execution(
                report.status, execution_results
            )
            if real_status != report.status:
                report.status = real_status
            # Replace commands_run with what we ACTUALLY ran so downstream
            # reviewers see the truth. The LLM's claim is preserved in the
            # raw qa_plan.json above this — we override only the UX copy.
            report.commands_run = [
                f"{r['command']} → exit {r['exit_code']}" for r in execution_results
            ]
            existing_notes = list(report.test_gaps or [])
            report.test_gaps = framework_notes + existing_notes

        # D1 — independent git cross-check (soft, additive). Even when the
        # Engineer recommended no commands (so the reconcile above is a no-op),
        # an implementation that claims it landed code but shows a ZERO real git
        # diff is suspicious. Bump to `needs_follow_up` (soft, sticky over a
        # `passed` claim) so a human looks — never harder than the command
        # reconcile (a real command FAILURE keeps `failed`).
        git_status, git_note = self._git_cross_check(report.status, task.workspace_path, canonical_issue_id)
        if git_note:
            if git_status != report.status:
                report.status = git_status
            report.test_gaps = [git_note, *list(report.test_gaps or [])]

        self._docs.ensure_issue_root(task.workspace_path, canonical_issue_id)

        qa_plan_path = self._docs.qa_plan_json_path(task.workspace_path, canonical_issue_id)
        qa_report_path = self._docs.qa_report_md_path(task.workspace_path, canonical_issue_id)

        qa_plan_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        qa_report_path.write_text(
            self._render_qa_report_markdown(report, execution_results), encoding="utf-8"
        )

        # Store the full structured JSON so AgentDecisionDrawer.case "qa" can render
        # bugs_found / risks / test_gaps / final_recommendation without reading disk.
        task.result = report.model_dump_json()

        qa_relpath = str(qa_report_path.relative_to(task.workspace_path))
        if report.status == "failed":
            # Mark the task failed so the scheduler's rework gate fires.
            task.status = "failed"
            task.review_comment = format_qa_failure_narrative(
                report.model_dump(), qa_report_relpath=qa_relpath
            )
        elif report.status in ("blocked", "needs_follow_up"):
            # Keep status="done" (no rework loop), but surface the verdict.
            task.review_comment = (
                f"[{report.status.upper()}] "
                + format_qa_failure_narrative(report.model_dump(), qa_report_relpath=qa_relpath)
            )
        # Attach written_files to the payload using object.__setattr__ to bypass Pydantic validation
        object.__setattr__(report, "written_files", [
            {"name": "qa/qa_plan.json", "path": str(qa_plan_path), "kind": "testing"},
            {"name": "qa/qa_report.md", "path": str(qa_report_path), "kind": "testing"},
        ])
        # Surface execution results so the scheduler / replanner can reason
        # about whether to dispatch an Engineer rework.
        object.__setattr__(report, "execution_results", execution_results or [])
        return report

    def _execute_verification_commands(
        self, commands: list[str], workspace_path: str
    ) -> list[dict] | None:
        """Run each verification command in the worktree and capture results.

        Returns:
            List of {command, exit_code, stdout, stderr, duration_s, refused?}
            dicts, or None if execution is disabled (mock mode / offline).

        Safety:
            - Per-command timeout (QA_COMMAND_TIMEOUT_S).
            - Total budget (QA_TOTAL_BUDGET_S) — remaining commands are
              recorded as `refused: budget_exhausted`.
            - Pattern-based refuse list for obvious foot-guns.
        """
        if not QA_EXECUTE_COMMANDS:
            return None
        if not commands:
            return []

        results: list[dict] = []
        start = time.monotonic()
        for cmd in commands:
            cmd = (cmd or "").strip()
            if not cmd:
                continue
            elapsed = time.monotonic() - start
            if elapsed >= QA_TOTAL_BUDGET_S:
                results.append({
                    "command": cmd,
                    "exit_code": -1,
                    "stdout": "",
                    "stderr": "",
                    "duration_s": 0.0,
                    "refused": "budget_exhausted",
                })
                continue
            refusal = self._refuse_reason(cmd)
            if refusal:
                results.append({
                    "command": cmd,
                    "exit_code": -1,
                    "stdout": "",
                    "stderr": f"refused by framework: {refusal}",
                    "duration_s": 0.0,
                    "refused": refusal,
                })
                continue
            t0 = time.monotonic()
            try:
                proc = subprocess.run(
                    cmd,
                    shell=True,
                    cwd=workspace_path,
                    capture_output=True,
                    text=True,
                    timeout=QA_COMMAND_TIMEOUT_S,
                )
                results.append({
                    "command": cmd,
                    "exit_code": proc.returncode,
                    "stdout": (proc.stdout or "")[-4000:],
                    "stderr": (proc.stderr or "")[-4000:],
                    "duration_s": round(time.monotonic() - t0, 2),
                })
            except subprocess.TimeoutExpired as exc:
                results.append({
                    "command": cmd,
                    "exit_code": -1,
                    "stdout": (exc.stdout or "")[-4000:] if isinstance(exc.stdout, str) else "",
                    "stderr": f"timed out after {QA_COMMAND_TIMEOUT_S}s",
                    "duration_s": round(time.monotonic() - t0, 2),
                    "refused": "timeout",
                })
            except Exception as exc:  # noqa: BLE001
                logger.warning("QA command %r raised: %s", cmd, exc)
                results.append({
                    "command": cmd,
                    "exit_code": -1,
                    "stdout": "",
                    "stderr": f"command runner error: {exc}",
                    "duration_s": round(time.monotonic() - t0, 2),
                    "refused": "runner_error",
                })
        return results

    @staticmethod
    def _refuse_reason(cmd: str) -> str | None:
        for pat in _REFUSED_COMMAND_PATTERNS:
            if pat.search(cmd):
                return pat.pattern
        return None

    @staticmethod
    def _reconcile_status_with_execution(
        claimed_status: str, results: list[dict]
    ) -> tuple[str, list[str]]:
        """Override the LLM's claimed status with what actually happened.

        - If any executed command exited non-zero (and wasn't refused for
          safety reasons), the QA verdict is `failed` regardless of what the
          LLM said.
        - If every command was refused / timed out / errored, surface as
          `needs_follow_up` so a human can adjudicate.
        - Otherwise, trust the LLM's claim but bound it: a `passed` claim is
          downgraded to `needs_follow_up` when zero commands actually ran.
        """
        notes: list[str] = []
        if not results:
            return claimed_status, notes

        ran = [r for r in results if not r.get("refused")]
        refused = [r for r in results if r.get("refused")]
        failed = [r for r in ran if r["exit_code"] != 0]

        if refused:
            notes.append(
                f"[framework] {len(refused)} command(s) skipped by safety filter "
                f"or timed out: {[r['command'] for r in refused]!r}"
            )

        if failed:
            failed_summary = ", ".join(
                f"{r['command']!r} → exit {r['exit_code']}" for r in failed
            )
            notes.insert(
                0,
                f"[framework] Verification failed on {len(failed)} command(s): {failed_summary}. "
                f"Status overridden to 'failed' regardless of LLM self-report ('{claimed_status}').",
            )
            return "failed", notes

        if not ran:
            notes.insert(
                0,
                "[framework] No verification command ran cleanly (all refused or timed out). "
                "Marking 'needs_follow_up' for human review.",
            )
            return "needs_follow_up", notes

        if claimed_status == "passed":
            return "passed", notes

        # Anything else (LLM said failed/blocked/needs_follow_up) — trust it,
        # since the model knows context the executed commands don't.
        return claimed_status, notes

    @staticmethod
    def _git_cross_check(
        current_status: str, workspace_path: str, issue_id: str
    ) -> tuple[str, str | None]:
        """Independent worktree git diff vs the Engineer report (D1).

        Soft signal layered ON TOP of the command reconcile: if the Engineer
        report implies it implemented something (status is not `blocked` and/or
        it lists completed_tasks) but the worktree shows ZERO changes against the
        base branch, the QA verdict is bumped to `needs_follow_up` so the empty
        implementation is surfaced — even when the Engineer recommended no
        verification commands (the path the command reconcile can't see).

        Returns (status, note). ``note`` is None when nothing fired. This NEVER
        downgrades a `failed` verdict (a real command failure is a stronger fact)
        and NEVER hard-kills — it follows the repo's soft-signal philosophy.
        """
        # A real command failure is the stronger, more certain fact: don't
        # weaken it. Also nothing to add to an already-needs_follow_up verdict.
        if current_status in ("failed", "needs_follow_up"):
            return current_status, None
        try:
            from app.application.engineer_workflow import git_changed_files
            from app.application.review_guard import _read_engineer_report
        except Exception:  # noqa: BLE001
            return current_status, None

        try:
            eng_status, _claimed, has_completed_tasks = _read_engineer_report(
                workspace_path, issue_id
            )
        except Exception:  # noqa: BLE001
            return current_status, None

        # Engineer report implies it did implementation work.
        implies_implementation = (
            (eng_status is not None and eng_status != "blocked") or has_completed_tasks
        )
        if not implies_implementation:
            return current_status, None

        actual_changed = git_changed_files(workspace_path)
        if actual_changed:
            return current_status, None

        note = (
            "[framework] Independent git cross-check: the Engineer report implies "
            f"implementation (status={eng_status!r}) but the worktree shows ZERO file "
            "changes against the base branch. Marking 'needs_follow_up' for human review."
        )
        return "needs_follow_up", note

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

    def _render_qa_report_markdown(
        self, report: QAReportDocument, execution_results: list[dict] | None = None
    ) -> str:
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

        if execution_results:
            lines.extend(["", "## Verification Execution"])
            for r in execution_results:
                marker = "✓" if r["exit_code"] == 0 else "✗"
                refused = r.get("refused")
                tag = f" _(skipped: {refused})_" if refused else ""
                lines.append(
                    f"- {marker} `{r['command']}` → exit {r['exit_code']} ({r['duration_s']}s){tag}"
                )
                if r.get("stderr"):
                    stderr = r["stderr"].rstrip()
                    if stderr:
                        lines.extend(["  ```", *stderr.splitlines()[-12:], "  ```"])

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
