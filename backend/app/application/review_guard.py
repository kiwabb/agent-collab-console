from __future__ import annotations

"""Deterministic diff-vs-claim / diff-vs-plan guard for Architect Review.

This module computes a deterministic, side-effect-free assessment of an
Engineer implementation against the actual git diff in the workspace, so that
the Architect Review step (and the review-dispatch path) can:

  * hard-reject (skipping the LLM) when an Engineer claims it landed code but
    the worktree shows zero file changes (``hard_mismatch``);
  * still let an honest "nothing to change / already implemented" report
    through to the normal LLM review (legal empty diff is NOT a mismatch);
  * inject a structured ``expected_files`` vs actual-diff delta plus a real
    diff summary into the review prompt as a SOFT signal (``plan_drift``).

The hard/soft split follows the existing repo philosophy: facts that are
certain are enforced hard (claim-vs-reality contradiction), fuzzy judgements
(Architect's pre-code file predictions) are surfaced as soft signals for the
LLM to weigh.

Nothing here mutates state, performs merges, or touches the primary repo.
It only *reads* the worktree diff.
"""
import logging  # noqa: E402
import re  # noqa: E402
from collections.abc import Iterable  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402

logger = logging.getLogger(__name__)

from app.adapters.local_process import TimeoutExpired, run_trusted_local  # noqa: E402
from app.application.engineer_workflow import git_changed_files  # noqa: E402
from app.application.issue_artifact_documents import IssueArtifactDocuments  # noqa: E402
from app.json_safety import parse_json_object_list  # noqa: E402

# Cap the diff text injected into the review prompt so a large change set does
# not blow the prompt budget. The review LLM only needs a representative
# ground-truth sample, not the entire patch.
_DIFF_SUMMARY_MAX_CHARS = 8000

_CLAIMED_IMPL_STATUSES = {"completed", "partial"}


def _normalize_path(path: str) -> str:
    """repo-relative, no leading ``./``; collapse backslashes for comparison."""
    p = (path or "").strip().replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p.strip("/")


def _normalize_set(paths: Iterable[object] | None) -> set[str]:
    out: set[str] = set()
    for p in paths or []:
        norm = _normalize_path(str(p))
        if norm:
            out.add(norm)
    return out


@dataclass
class GuardResult:
    """Deterministic guard verdict.

    verdict:
      * ``hard_mismatch`` — claimed implementation but zero real diff (hard reject).
      * ``plan_drift``    — real changes exist but diverge from ``expected_files`` (soft).
      * ``ok``            — consistent / no actionable divergence.
    """

    verdict: str
    claimed_files: list[str] = field(default_factory=list)
    actual_files: list[str] = field(default_factory=list)
    expected_files: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    extra: list[str] = field(default_factory=list)
    diff_summary: str = ""
    claimed_status: str | None = None
    claims_implementation: bool = False

    @property
    def is_hard_mismatch(self) -> bool:
        return self.verdict == "hard_mismatch"

    def to_artifact(self) -> dict[str, object]:
        """Compact, JSON-serializable form for embedding in the review artifact."""
        return {
            "verdict": self.verdict,
            "claimed_files": self.claimed_files,
            "actual_files": self.actual_files,
            "expected_files": self.expected_files,
            "missing": self.missing,
            "extra": self.extra,
            "claimed_status": self.claimed_status,
        }


def _parse_md_bullet_list(text: str, header: str) -> list[str]:
    """Return non-'None' bullet items under a ``## <header>`` section."""
    out: list[str] = []
    section = re.search(
        rf"^##\s+{re.escape(header)}\s*$\n(.*?)(?=^##\s|\Z)",
        text,
        re.MULTILINE | re.DOTALL | re.IGNORECASE,
    )
    if not section:
        return out
    for line in section.group(1).splitlines():
        line = line.strip()
        if not line.startswith("- "):
            continue
        value = line[2:].strip().strip("`").strip()
        if not value or value.lower() == "none":
            continue
        out.append(value)
    return out


def _parse_engineer_report_md(text: str) -> tuple[str | None, list[str], bool]:
    """Parse (status, claimed changed_files, has_completed_tasks) from the report markdown.

    The persisted Engineer artifact (``implementation-<task>.md``) is the only
    structured trace the review task can reach on disk (the parent task's
    ``result`` is rewritten to a one-line summary). We parse the well-known
    ``- Status:`` line plus the ``## Changed Files`` and ``## Completed Tasks``
    bullet lists rendered by ``EngineerWorkflow._render_implementation_markdown``.
    """
    status: str | None = None
    status_match = re.search(r"^-\s*Status:\s*(\w+)\s*$", text, re.MULTILINE | re.IGNORECASE)
    if status_match:
        status = status_match.group(1).strip().lower()

    changed = _parse_md_bullet_list(text, "Changed Files")
    completed = _parse_md_bullet_list(text, "Completed Tasks")
    return status, changed, bool(completed)


def _read_expected_files(workspace_path: str, issue_id: str) -> list[str]:
    """Union of ``expected_files`` across all implementation tasks in the plan.

    Tolerant of missing file / malformed JSON / pre-PR1 payloads that lack the
    ``expected_files`` field (degrade to []).
    """
    docs = IssueArtifactDocuments()
    try:
        plan_path = docs.architect_implementation_plan_path(workspace_path, issue_id)
    except Exception:  # noqa: BLE001, RUF100
        return []
    if not plan_path.exists():
        return []
    try:
        tasks = parse_json_object_list(plan_path.read_text(encoding="utf-8"))
    except OSError:
        return []
    union: list[str] = []
    for task in tasks:
        expected_files = task.get("expected_files")
        if not isinstance(expected_files, list):
            continue
        for f in expected_files:
            if isinstance(f, str):
                union.append(f)
    return union


def git_diff_summary(workspace_path: str | None) -> str:
    """Best-effort truncated unified diff against the base branch (sync, read-only).

    Mirrors the base-fallback order used by ``git_changed_files``
    (origin/main -> main -> HEAD~1). Returns "" when no diff machinery is
    reachable so callers degrade gracefully. Pure read; never mutates the repo.
    """
    if not workspace_path:
        return ""

    for base in ("origin/main", "main", "HEAD~1"):
        try:
            result = run_trusted_local(
                ["git", "diff", f"{base}..HEAD"],
                cwd=workspace_path,
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (FileNotFoundError, TimeoutExpired):
            return ""
        if result.returncode == 0:
            diff_text = result.stdout
            # Append uncommitted working-tree diff so an uncommitted impl is visible.
            try:
                wt = run_trusted_local(
                    ["git", "diff"],
                    cwd=workspace_path,
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                if wt.returncode == 0 and wt.stdout.strip():
                    diff_text = f"{diff_text}\n{wt.stdout}" if diff_text else wt.stdout
            except (FileNotFoundError, TimeoutExpired):
                pass
            if not diff_text:
                continue
            if len(diff_text) > _DIFF_SUMMARY_MAX_CHARS:
                return diff_text[:_DIFF_SUMMARY_MAX_CHARS] + "\n... [diff truncated] ..."
            return diff_text
    return ""


def _read_engineer_report(workspace_path: str, issue_id: str) -> tuple[str | None, list[str], bool]:
    """Read the Engineer report markdown; return (status, claimed_files, has_completed_tasks).

    Combines all engineer artifacts (parallel specialist engineers may produce
    several) so claimed_files is a union, status reflects any report claiming
    implementation, and has_completed_tasks is True if any report lists one.
    """
    docs = IssueArtifactDocuments()
    try:
        impl_files = docs.engineer_find_artifacts(workspace_path, issue_id)
    except Exception:  # noqa: BLE001, RUF100
        return None, [], False
    status: str | None = None
    claimed: list[str] = []
    has_completed = False
    for path in impl_files or []:
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001, RUF100
            logger.debug("engineer report read failed: path=%s", path, exc_info=True)
            continue
        s, files, completed = _parse_engineer_report_md(text)
        # Prefer a status that claims implementation if any report does.
        if s and (
            status is None or (status not in _CLAIMED_IMPL_STATUSES and s in _CLAIMED_IMPL_STATUSES)
        ):
            status = s
        claimed.extend(files)
        has_completed = has_completed or completed
    return status, claimed, has_completed


def compute_review_guard(
    workspace_path: str | None,
    issue_id: str,
    *,
    include_diff_summary: bool = True,
) -> GuardResult:
    """Compute the deterministic review guard for one engineer→review handoff.

    Pure read-only, fully synchronous (subprocess git reads + artifact file
    reads). The authoritative changed-file *list* comes from
    ``git_changed_files`` (the same base-fallback logic the Engineer
    post-execution cross-check uses); the human-readable diff summary comes from
    ``git_diff_summary``.

    ``include_diff_summary=False`` skips the (heavier) diff read — used on the
    hard-short-circuit path where only the verdict matters.
    """
    if not workspace_path:
        return GuardResult(verdict="ok")

    claimed_status, claimed_raw, has_completed_tasks = _read_engineer_report(
        workspace_path, issue_id
    )
    expected_raw = _read_expected_files(workspace_path, issue_id)

    actual_set = _normalize_set(git_changed_files(workspace_path))
    claimed_set = _normalize_set(claimed_raw)
    expected_set = _normalize_set(expected_raw)

    # Does the report assert that it LANDED CODE? The only unambiguous signal is
    # an explicit, non-empty `changed_files` list: the Engineer named files it
    # claims it modified. If that list contradicts a zero git diff, it is a hard
    # fact (claim-vs-reality), so a deterministic reject is warranted.
    #
    # We deliberately do NOT treat (status in {completed,partial} AND
    # completed_tasks) as a code-landing claim: the Engineer prompt explicitly
    # allows `changed_files=[]` with status=completed when "the requirement was
    # already implemented and nothing needed to change", and such an honest
    # report still legitimately lists completed_tasks (the task WAS addressed,
    # just without new code). Using completed_tasks as the hard trigger would
    # false-positive that legal already-implemented case (AC4 violation), so the
    # already-implemented / blocked empty-diff path is left for the LLM to judge.
    # `claimed_status`/`has_completed_tasks` are still surfaced for observability.
    claims_implementation = bool(claimed_set)
    _ = has_completed_tasks  # retained for the artifact / future soft signals

    # --- HARD layer: claim-vs-reality contradiction -------------------------
    # Claimed implementation but the worktree shows zero file changes. This is
    # the only certain fact -> deterministic reject. An honest changed_files=[]
    # with a non-implementation status (blocked / already-implemented) is a
    # LEGAL empty diff and must NOT be hard-rejected.
    if claims_implementation and not actual_set:
        return GuardResult(
            verdict="hard_mismatch",
            claimed_files=sorted(claimed_set),
            actual_files=[],
            expected_files=sorted(expected_set),
            claimed_status=claimed_status,
            claims_implementation=True,
        )

    # --- diff summary (best-effort) for the soft layer ----------------------
    diff_summary = ""
    if actual_set and include_diff_summary:
        diff_summary = git_diff_summary(workspace_path)

    # --- SOFT layer: expected_files vs actual divergence --------------------
    # Only meaningful when the Architect predicted files AND real changes exist.
    missing: list[str] = []
    extra: list[str] = []
    verdict = "ok"
    if expected_set and actual_set:
        missing = sorted(expected_set - actual_set)
        extra = sorted(actual_set - expected_set)
        if missing or extra:
            verdict = "plan_drift"

    return GuardResult(
        verdict=verdict,
        claimed_files=sorted(claimed_set),
        actual_files=sorted(actual_set),
        expected_files=sorted(expected_set),
        missing=missing,
        extra=extra,
        diff_summary=diff_summary,
        claimed_status=claimed_status,
        claims_implementation=claims_implementation,
    )


def render_guard_context(guard: GuardResult) -> str:
    """Render the guard's soft signal as a context block for the review prompt.

    The block is explicit that ``missing``/``extra`` are SOFT signals (the
    Architect's pre-code predictions are not authoritative) and that the diff
    is the ground truth the reviewer should weigh.
    """
    lines = [
        "framework_diff_guard (deterministic, computed from real git diff):",
        f"- actual_changed_files: {guard.actual_files or 'NONE'}",
        f"- engineer_claimed_files: {guard.claimed_files or 'NONE'}",
        f"- architect_expected_files: {guard.expected_files or 'NONE (not predicted)'}",
    ]
    if guard.expected_files:
        lines.append(f"- missing_vs_expected (SOFT signal): {guard.missing or 'NONE'}")
        lines.append(f"- extra_vs_expected (SOFT signal): {guard.extra or 'NONE'}")
        lines.append(
            "  NOTE: expected_files is the Architect's BEST-EFFORT prediction made "
            "before any code was written. missing/extra are SOFT signals only — weigh "
            "them against the real diff below, do NOT treat them as hard pass/fail criteria."
        )
    if guard.diff_summary:
        lines.append("")
        lines.append("actual_git_diff (ground truth — review against THIS, not just the report):")
        lines.append(guard.diff_summary)
    return "\n".join(lines)
