from __future__ import annotations

"""Cross-issue project memory.

Each project gets a single team-notes file at
`<project.repo_path>/.agent-collab/team_notes.md`. That file:

  1. is read at every role-prompt build time and injected as a TEAM CONTEXT
     header, so each new issue starts with the lessons learned from prior
     issues (Devin's "self-improving" behaviour, minus the magic);

  2. is appended to whenever an issue lands in a terminal `done` state,
     summarising the issue's outcome — what was changed, what tests ran,
     what bugs QA flagged. The summary is built deterministically from the
     PM/Engineer/QA artifacts on disk (no extra LLM call → no cost).

The file is plaintext markdown, capped at 16 KB. When it grows past the cap
the oldest dated block is dropped before the new one is appended. This keeps
prompt-injection cost bounded.

It lives **inside the project repo**, so:
  - Humans can read and edit it (it's just markdown).
  - It travels with the repo on clone/branch.
  - It survives `console.db` resets.

Two failure modes are explicitly tolerated:
  - Missing project repo path → no memory injection, no append.
  - Filesystem write error → log and continue (memory is best-effort, never
    a reason to fail an issue).
"""
import logging  # noqa: E402
from collections.abc import Awaitable, Callable, Mapping, Sequence  # noqa: E402
from datetime import datetime  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Protocol  # noqa: E402

from app.json_safety import object_list, parse_json_object  # noqa: E402

logger = logging.getLogger(__name__)

MEMORY_DIR_NAME = ".agent-collab"
MEMORY_FILE_NAME = "team_notes.md"
# Hard cap on the memory file. Past this size we drop oldest entries so the
# prompt injection budget stays bounded. 16 KB ≈ ~4k tokens, low enough not
# to crowd out the per-issue context.
MEMORY_BYTES_CAP = 16_000
# S3c: above this many per-issue blocks the deterministic append stops
# scaling — kick off an LLM distillation that compresses the accumulated
# blocks into ≤5 long-lived lessons. The 2 most recent raw blocks are
# always kept untouched so the LLM doesn't erase facts it never saw.
DISTILL_TRIGGER_BLOCKS = 5
KEEP_RECENT_BLOCKS = 2
DISTILLED_HEADER = "## ⚙️ Distilled lessons (auto-curated)"


class ProjectMemoryDbCursor(Protocol):
    async def fetchone(self) -> Sequence[object] | None: ...

    async def fetchall(self) -> list[Sequence[object]]: ...


class ProjectMemoryDbConnection(Protocol):
    async def execute(
        self, sql: str, parameters: Sequence[object] = ()
    ) -> ProjectMemoryDbCursor: ...

    async def commit(self) -> None: ...


class ProjectMemoryGraph(Protocol):
    issue_id: str
    status: str


class ProjectMemoryIssue(Protocol):
    id: str
    title: str
    project_id: str | None
    git_worktree_path: str | None


class ProjectMemoryProject(Protocol):
    repo_path: str


class ProjectMemoryStore(Protocol):
    async def load_workflow_graph(self, graph_id: str) -> ProjectMemoryGraph | None: ...

    async def load_codex_issue(self, issue_id: str) -> ProjectMemoryIssue | None: ...

    async def load_project(self, project_id: str) -> ProjectMemoryProject | None: ...

    async def _get_conn(self) -> ProjectMemoryDbConnection: ...


ProjectMemoryLlmRunner = Callable[[str], Awaitable[object]]


class ProjectMemoryService:
    """Read/write the per-project team_notes.md file."""

    def __init__(self) -> None:
        pass

    # ------------------------------------------------------------------
    # Read path: prompt injection
    # ------------------------------------------------------------------

    def read_for_prompt(self, project_repo_path: str | None) -> str | None:
        """Return memory content suitable for injection into a role prompt.

        Returns None when no memory exists or the project repo isn't
        accessible — caller should skip the TEAM CONTEXT block entirely.
        """
        path = self._memory_path(project_repo_path)
        if path is None or not path.exists():
            return None
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.debug("project_memory read failed for %s: %s", path, exc)
            return None
        content = content.strip()
        return content or None

    @staticmethod
    def format_for_prompt(memory_text: str) -> str:
        """Wrap the raw memory in the canonical TEAM CONTEXT header used by
        all role prompts."""
        return (
            "TEAM CONTEXT (lessons captured from prior issues on this project):\n"
            "---\n"
            f"{memory_text}\n"
            "---\n"
            "Apply these conventions when relevant. If a convention here conflicts "
            "with the user's current request, defer to the user but flag the conflict "
            "in your output (qa_notes / risks / open_questions, depending on your role).\n"
        )

    # ------------------------------------------------------------------
    # Write path: per-issue summary append
    # ------------------------------------------------------------------

    def record_issue_completion(
        self,
        project_repo_path: str | None,
        *,
        issue_id: str,
        issue_title: str,
        worktree_path: str | None,
        graph_status: str,
    ) -> Path | None:
        """Append a short summary of an issue's outcome to team_notes.md.

        Pulls structured data from the issue's worktree artifacts:
          - issues/<id>/pm/prd.json
          - issues/<id>/architect/system_design.json
          - issues/<id>/engineer/implementation-*.md (via engineer report)
          - issues/<id>/qa/qa_plan.json

        Returns the path written to, or None when nothing was written.
        """
        path = self._memory_path(project_repo_path)
        if path is None:
            return None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.debug("project_memory mkdir failed for %s: %s", path.parent, exc)
            return None

        summary = self._build_summary_block(
            issue_id=issue_id,
            issue_title=issue_title,
            worktree_path=worktree_path,
            graph_status=graph_status,
        )
        if summary is None:
            return None
        try:
            existing = path.read_text(encoding="utf-8") if path.exists() else ""
        except OSError:
            existing = ""

        # Guard against re-appending the same issue summary (re-runs).
        marker = f"<!-- issue:{issue_id} -->"
        if marker in existing:
            # Replace the old block with the new one to keep state fresh.
            blocks = self._split_into_blocks(existing)
            blocks = [b for b in blocks if marker not in b]
            existing = "\n\n".join(blocks).strip()

        combined = (existing + "\n\n" + summary).strip() + "\n"
        combined = self._trim_to_cap(combined)
        try:
            path.write_text(combined, encoding="utf-8")
        except OSError as exc:
            logger.warning("project_memory write failed for %s: %s", path, exc)
            return None
        return path

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _memory_path(self, project_repo_path: str | None) -> Path | None:
        if not project_repo_path:
            return None
        try:
            base = Path(project_repo_path)
        except (TypeError, ValueError):
            return None
        if not base.exists():
            return None
        return base / MEMORY_DIR_NAME / MEMORY_FILE_NAME

    def _build_summary_block(
        self,
        *,
        issue_id: str,
        issue_title: str,
        worktree_path: str | None,
        graph_status: str,
    ) -> str | None:
        # Pull whichever artifacts exist on disk. None of these are
        # required — we record whatever is available.
        prd = self._read_json(worktree_path, issue_id, "pm/prd.json")
        bugfix = self._read_json(worktree_path, issue_id, "pm/bugfix.json")
        design = self._read_json(worktree_path, issue_id, "architect/system_design.json")
        impl_plan = self._read_json(worktree_path, issue_id, "architect/implementation_plan.json")
        qa = self._read_json(worktree_path, issue_id, "qa/qa_plan.json")

        # An engineer report's file name embeds the task id so we glob.
        engineer_changed_files: list[str] = []
        if worktree_path:
            engineer_dir = Path(worktree_path) / "issues" / issue_id / "engineer"
            if engineer_dir.exists():
                for impl_md in sorted(engineer_dir.glob("implementation-*.md")):
                    text = self._safe_read_text(impl_md)
                    if text:
                        engineer_changed_files.extend(_parse_changed_files_section(text))

        intent = "feature"
        if bugfix:
            intent = "bugfix"
        elif prd and (prd.get("requirement_pool") or prd.get("product_goals")):
            intent = "feature"

        lines = [
            f"<!-- issue:{issue_id} -->",
            f"## {datetime.now().strftime('%Y-%m-%d %H:%M')} — {issue_title}",
            f"_intent: {intent} · graph status: {graph_status}_",
            "",
        ]

        if prd:
            goals = _text_list(prd.get("product_goals"))
            if goals:
                lines.append("**Product goals:**")
                lines.extend([f"- {g}" for g in goals[:3]])
                lines.append("")

        if design:
            constraints = _text_list(design.get("constraints"))
            chosen = _text_list(design.get("design_choices") or design.get("decisions"))
            if constraints or chosen:
                lines.append("**Architecture notes (carry forward):**")
                for c in constraints[:3]:
                    lines.append(f"- constraint: {c}")
                for c in chosen[:3]:
                    lines.append(f"- decision: {c}")
                lines.append("")

        if impl_plan:
            tasks = object_list(impl_plan.get("tasks") or impl_plan.get("subtasks"))
            if tasks:
                lines.append("**Implementation tasks pursued:**")
                for t in tasks[:5]:
                    title = _text(t.get("title")) if isinstance(t, Mapping) else str(t)
                    if title:
                        lines.append(f"- {title}")
                lines.append("")

        if engineer_changed_files:
            unique_files = list(dict.fromkeys(engineer_changed_files))[:10]
            lines.append("**Files touched:**")
            lines.extend([f"- `{f}`" for f in unique_files])
            lines.append("")

        if qa:
            verdict = _text(qa.get("status"), default="unknown")
            commands = _text_list(qa.get("commands_run"))
            recommended = _text_list(qa.get("recommended_commands"))
            bugs = _text_list(qa.get("bugs_found"))
            lines.append(f"**QA verdict:** `{verdict}`")
            if recommended:
                lines.append("**Verification commands worth keeping:**")
                lines.extend([f"- `{c}`" for c in recommended[:6]])
            if commands:
                lines.append("**Actually run by QA:**")
                lines.extend([f"- `{c}`" for c in commands[:6]])
            if bugs:
                lines.append("**Bugs / lessons:**")
                lines.extend([f"- {b}" for b in bugs[:5]])

        # Drop trailing empty section if nothing useful was found.
        meaningful = any(
            line
            and not line.startswith("##")
            and not line.startswith("<!--")
            and not line.startswith("_intent:")
            for line in lines
        )
        if not meaningful:
            return None
        return "\n".join(lines).rstrip() + "\n"

    def _read_json(
        self, worktree_path: str | None, issue_id: str, relpath: str
    ) -> dict[str, object] | None:
        if not worktree_path:
            return None
        p = Path(worktree_path) / "issues" / issue_id / relpath
        if not p.exists():
            return None
        text = self._safe_read_text(p)
        if not text:
            return None
        return parse_json_object(text)

    @staticmethod
    def _safe_read_text(p: Path) -> str | None:
        try:
            return p.read_text(encoding="utf-8")
        except OSError:
            return None

    @staticmethod
    def _split_into_blocks(content: str) -> list[str]:
        """Split team_notes.md into per-issue blocks separated by blank lines.

        Each block starts at an `<!-- issue:... -->` marker line (or, for
        legacy content without markers, at the closest `## ` heading).
        """
        if not content.strip():
            return []
        chunks: list[str] = []
        current: list[str] = []
        for line in content.splitlines():
            if line.startswith("<!-- issue:") or (line.startswith("## ") and not current):  # noqa: SIM102
                if current:
                    chunks.append("\n".join(current).strip())
                    current = []
            current.append(line)
        if current:
            chunks.append("\n".join(current).strip())
        return [c for c in chunks if c]

    def _trim_to_cap(self, content: str) -> str:
        """Drop oldest blocks until we're under MEMORY_BYTES_CAP."""
        if len(content.encode("utf-8")) <= MEMORY_BYTES_CAP:
            return content
        blocks = self._split_into_blocks(content)
        while blocks and len("\n\n".join(blocks).encode("utf-8")) > MEMORY_BYTES_CAP:
            blocks.pop(0)
        return "\n\n".join(blocks).strip() + "\n" if blocks else ""

    def trim_to_cap(self, content: str) -> str:
        """Return project-memory content trimmed to the prompt budget cap."""
        return self._trim_to_cap(content)

    def needs_distillation(self, content: str) -> bool:
        """Heuristic: kick off an LLM distillation once we've accumulated
        more than DISTILL_TRIGGER_BLOCKS raw issue blocks (excluding the
        Distilled-lessons header)."""
        blocks = [b for b in self._split_into_blocks(content) if not b.startswith(DISTILLED_HEADER)]
        return len(blocks) > DISTILL_TRIGGER_BLOCKS

    async def maybe_distill(
        self, project_repo_path: str | None, llm_runner: ProjectMemoryLlmRunner
    ) -> Path | None:
        """If team_notes.md has grown past the threshold and an llm_runner
        is supplied, distill the older blocks into ≤5 evergreen lessons
        and rewrite the file. Returns the path on success, None otherwise.
        Tolerant — any failure leaves the file untouched.
        """
        path = self._memory_path(project_repo_path)
        if path is None or not path.exists():
            return None
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            return None
        if not self.needs_distillation(content):
            return None

        all_blocks = self._split_into_blocks(content)
        # Carve out the existing distilled header (will be regenerated).
        raw_blocks = [b for b in all_blocks if not b.startswith(DISTILLED_HEADER)]
        if len(raw_blocks) <= KEEP_RECENT_BLOCKS:
            return None
        to_distill = raw_blocks[:-KEEP_RECENT_BLOCKS]
        keep_recent = raw_blocks[-KEEP_RECENT_BLOCKS:]

        prompt = (
            "You are curating a project's long-term engineering memory. Read these "
            f"{len(to_distill)} per-issue notes and distill them into AT MOST 5 evergreen "
            "lessons that should permanently guide future issues on this project.\n\n"
            "Rules:\n"
            "- Drop time-bound facts (build versions, sprint names, specific dates).\n"
            "- Drop trivial / one-off / duplicate observations.\n"
            "- Keep conventions, architectural decisions, gotchas, repeated bug classes, anti-patterns.\n"
            "- Each lesson: a single sentence in present tense imperative ('Use X', 'Prefer Y over Z', 'Always validate W').\n"
            "- Reply with ONLY a markdown bullet list, no preamble.\n\n"
            "Notes to distill:\n\n" + "\n\n".join(to_distill)
        )
        try:
            response = await llm_runner(prompt)
        except Exception as exc:  # noqa: BLE001, RUF100
            logger.debug("project_memory distillation LLM call failed: %s", exc)
            return None
        if not isinstance(response, str) or not response.strip():
            return None

        # Clean up the LLM response — strip code fences and any stray header.
        body = response.strip()
        if body.startswith("```"):
            lines = body.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            body = "\n".join(lines).strip()

        rebuilt = (
            "\n\n".join(
                [
                    f"{DISTILLED_HEADER}\n{body}",
                    *keep_recent,
                ]
            ).strip()
            + "\n"
        )
        try:
            path.write_text(self._trim_to_cap(rebuilt), encoding="utf-8")
        except OSError as exc:
            logger.warning("project_memory distill write failed: %s", exc)
            return None
        return path


def _parse_changed_files_section(impl_md_text: str) -> list[str]:
    """Pull file paths out of the engineer report's `## Changed Files` block."""
    files: list[str] = []
    in_section = False
    for line in impl_md_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## Changed Files"):
            in_section = True
            continue
        if in_section and stripped.startswith("## "):
            break
        if in_section and stripped.startswith("- "):
            entry = stripped[2:].strip()
            if entry and entry != "None":
                files.append(entry)
    return files


def _text(value: object, *, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _text_list(value: object) -> list[str]:
    return [str(item) for item in object_list(value) if item is not None]


# Module-level singleton for convenience; the service is stateless.
project_memory = ProjectMemoryService()


async def record_project_memory(graph_id: str, store: ProjectMemoryStore) -> None:
    """Standalone async function for recording project memory after a graph completes.

    Extracts from WorkflowScheduler._record_project_memory for use by the
    Conductor-driven issue loop (run_issue_conductor_loop).
    """
    try:
        graph = await store.load_workflow_graph(graph_id)
        if graph is None:
            return
        issue = await store.load_codex_issue(graph.issue_id)
        if issue is None:
            return
        project_repo_path = None
        if issue.project_id:
            proj = await store.load_project(issue.project_id)
            if proj is not None:
                project_repo_path = proj.repo_path
        project_memory.record_issue_completion(
            project_repo_path,
            issue_id=issue.id,
            issue_title=issue.title or issue.id,
            worktree_path=issue.git_worktree_path,
            graph_status=graph.status,
        )
        # Reconcile team_notes_state
        try:
            from app.application.team_notes_service import team_notes

            if issue.project_id and project_repo_path:
                md = team_notes.read_markdown(project_repo_path)
                parsed = team_notes.parse_blocks(md)
                state = await team_notes._load_state(store, issue.project_id)
                parsed_ids = {b.block_id for b in parsed}
                for b in parsed:
                    if b.block_id not in state:
                        await team_notes._upsert_state(store, issue.project_id, b.block_id)
                for stale_id in set(state.keys()) - parsed_ids:
                    try:
                        conn = await store._get_conn()
                        await conn.execute(
                            "DELETE FROM team_notes_state WHERE project_id = ? AND block_id = ?",
                            (issue.project_id, stale_id),
                        )
                        await conn.commit()
                    except Exception:  # noqa: BLE001, RUF100
                        logger.debug(
                            "team notes stale block cleanup failed: project_id=%s block_id=%s",
                            issue.project_id,
                            stale_id,
                            exc_info=True,
                        )
        except Exception as exc:  # noqa: BLE001, RUF100
            logger.debug("team_notes_state reconcile skipped: %s", exc)
    except Exception as exc:  # noqa: BLE001, RUF100
        logger.warning("record_project_memory failed for graph %s: %s", graph_id, exc)
