from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from subprocess import CompletedProcess
from typing import Protocol, cast

from pydantic import BaseModel, Field, ValidationError

from app.adapters.local_process import TimeoutExpired, run_trusted_local
from app.application.command_safety import parse_allowed_command

ACCEPTANCE_CONTEXT_MARKER = "AUTHORITATIVE ACCEPTANCE CRITERIA"
VERIFICATION_EVIDENCE_ROLES = frozenset(
    {
        "qa",
        "specialist:accessibility_reviewer",
        "specialist:api_contract_checker",
        "specialist:code_reviewer",
        "specialist:dependency_auditor",
        "specialist:i18n_checker",
        "specialist:performance_reviewer",
        "specialist:security_reviewer",
    }
)
_TRIVIAL_VERIFICATION_EXECUTABLES = frozenset({":", "echo", "printf", "true"})


class AcceptanceCriterionEvidence(BaseModel):
    criterion_index: int = Field(ge=0)
    criterion: str = Field(min_length=1)
    command: str = Field(min_length=1)
    # These fields are framework-owned. The QA model proposes only the
    # criterion/command mapping; the runner fills the actual result reference.
    execution_result_index: int | None = None
    evidence: str = ""


class VerificationStateError(RuntimeError):
    pass


class VerificationState(BaseModel):
    issue_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    role: str = Field(min_length=1)
    workspace_path: str = Field(min_length=1)
    git_head: str = Field(min_length=1)
    worktree_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    verified_at: datetime


class _Digest(Protocol):
    def update(self, value: bytes) -> None: ...


def _git_bytes(root: Path, args: list[str]) -> bytes:
    env = {
        "GIT_OPTIONAL_LOCKS": "0",
        "LANG": "C.UTF-8",
        "PATH": os.environ.get("PATH", os.defpath),
    }
    try:
        process = cast(
            "CompletedProcess[bytes]",
            run_trusted_local(
                ["git", *args],
                cwd=root,
                capture_output=True,
                text=False,
                timeout=30,
                env=env,
            ),
        )
    except (OSError, TimeoutExpired) as exc:
        raise VerificationStateError(
            "verification worktree state could not be inspected"
        ) from exc
    if process.returncode != 0 or not isinstance(process.stdout, bytes):
        raise VerificationStateError("verification worktree state could not be inspected")
    return process.stdout


def _dirty_paths(root: Path, issue_id: str) -> list[bytes]:
    tracked = _git_bytes(root, ["diff", "--name-only", "-z", "HEAD", "--", "."])
    untracked = _git_bytes(
        root,
        ["ls-files", "--others", "--exclude-standard", "-z", "--", "."],
    )
    qa_prefix = os.fsencode(f"issues/{issue_id}/qa/")
    paths = {
        path
        for path in (*tracked.split(b"\0"), *untracked.split(b"\0"))
        if path and path != qa_prefix[:-1] and not path.startswith(qa_prefix)
    }
    return sorted(paths)


def _hash_dirty_path(digest: _Digest, root: Path, relative_bytes: bytes) -> None:
    relative = Path(os.fsdecode(relative_bytes))
    if relative.is_absolute() or ".." in relative.parts:
        raise VerificationStateError("verification worktree contains an invalid path")
    path = root / relative
    if not path.parent.resolve().is_relative_to(root):
        raise VerificationStateError("verification worktree path escapes the worktree")

    digest.update(b"PATH\0")
    digest.update(relative_bytes)
    digest.update(b"\0")
    if path.is_symlink():
        if not path.resolve().is_relative_to(root):
            raise VerificationStateError("verification worktree symlink escapes the worktree")
        digest.update(b"SYMLINK\0")
        digest.update(os.fsencode(os.readlink(path)))
        digest.update(b"\0")
        return
    if not path.exists():
        digest.update(b"DELETED\0")
        return
    if not path.is_file():
        raise VerificationStateError(
            "verification worktree contains an unsupported dirty file type"
        )

    before = path.lstat()
    digest.update(f"MODE:{stat.S_IMODE(before.st_mode):o}\0".encode("ascii"))
    try:
        with path.open("rb") as file_obj:
            while chunk := file_obj.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise VerificationStateError("verification worktree file could not be read") from exc
    after = path.lstat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (
        after.st_size,
        after.st_mtime_ns,
        after.st_ino,
    ):
        raise VerificationStateError("verification worktree changed during inspection")
    digest.update(b"\0")


def capture_verification_state(
    *,
    workspace_path: str,
    issue_id: str,
    task_id: str,
    role: str,
) -> VerificationState:
    root = Path(workspace_path).resolve()
    if not root.is_dir():
        raise VerificationStateError("verification worktree does not exist")
    head = _git_bytes(root, ["rev-parse", "--verify", "HEAD"]).decode("ascii").strip()
    if not head:
        raise VerificationStateError("verification worktree has no Git HEAD")

    digest = hashlib.sha256()
    digest.update(b"HEAD\0")
    digest.update(head.encode("ascii"))
    digest.update(b"\0")
    for relative_bytes in _dirty_paths(root, issue_id):
        _hash_dirty_path(digest, root, relative_bytes)

    return VerificationState(
        issue_id=issue_id,
        task_id=task_id,
        role=role,
        workspace_path=str(root),
        git_head=head,
        worktree_state_sha256=digest.hexdigest(),
        verified_at=datetime.now(UTC),
    )


def append_acceptance_criteria_context(
    prompt: str,
    acceptance_criteria: Sequence[str],
    *,
    confirmed: bool,
) -> str:
    if ACCEPTANCE_CONTEXT_MARKER in prompt:
        return prompt

    criteria = [criterion.strip() for criterion in acceptance_criteria if criterion.strip()]
    if confirmed and criteria:
        lines = [
            ACCEPTANCE_CONTEXT_MARKER,
            "The user confirmed every criterion below. Treat this list as the completion contract:",
        ]
        lines.extend(f"{index}. {criterion}" for index, criterion in enumerate(criteria))
        lines.extend(
            [
                "For a passed verdict, criterion_evidence must contain exactly one entry for each "
                "index above.",
                "Each entry must repeat the exact criterion text and name one recommended command "
                "that directly verifies it.",
                "Use a distinct command string and result for every criterion; add criterion-specific "
                "test selectors instead of reusing one broad suite command.",
                "A general green command without this criterion-level mapping is unverified.",
            ]
        )
    else:
        lines = [
            ACCEPTANCE_CONTEXT_MARKER,
            "The issue has no user-confirmed acceptance criteria. You may inspect and test the work, "
            "but the verdict must be unverified rather than passed.",
        ]
    return f"{prompt.rstrip()}\n\n" + "\n".join(lines)


def sanitize_model_criterion_evidence(value: object) -> object:
    """Drop framework-owned proof fields before Pydantic validates model output."""
    if not isinstance(value, list):
        return value
    sanitized: list[object] = []
    for item in value:
        if not isinstance(item, dict):
            sanitized.append(item)
            continue
        clean = dict(item)
        clean.pop("execution_result_index", None)
        clean.pop("evidence", None)
        sanitized.append(clean)
    return sanitized


def _normalize_criterion(value: str) -> str:
    return " ".join(value.split()).casefold()


def _evidence_summary(result: Mapping[str, object]) -> str:
    stdout = result.get("stdout")
    stderr = result.get("stderr")
    output = stdout.strip() if isinstance(stdout, str) else ""
    if not output and isinstance(stderr, str):
        output = stderr.strip()
    return output[-1000:] if output else "command exited with code 0"


def build_verified_criterion_evidence(
    acceptance_criteria: Sequence[str],
    proposed_evidence: Sequence[AcceptanceCriterionEvidence],
    execution_results: Sequence[Mapping[str, object]],
) -> tuple[list[AcceptanceCriterionEvidence], str | None]:
    criteria = [criterion.strip() for criterion in acceptance_criteria if criterion.strip()]
    if not criteria:
        return [], "no confirmed acceptance criteria were available to verify"

    proposed_by_index: dict[int, AcceptanceCriterionEvidence] = {}
    for proposal in proposed_evidence:
        index = proposal.criterion_index
        if index in proposed_by_index:
            return [], f"criterion {index} has duplicate evidence entries"
        if index >= len(criteria):
            return [], f"criterion evidence index {index} is outside the confirmed criteria"
        proposed_by_index[index] = proposal

    missing = [index for index in range(len(criteria)) if index not in proposed_by_index]
    if missing:
        return [], f"confirmed criteria have no command evidence: {missing}"

    verified: list[AcceptanceCriterionEvidence] = []
    used_result_indexes: set[int] = set()
    used_commands: set[tuple[str, ...]] = set()
    for index, criterion in enumerate(criteria):
        proposal = proposed_by_index[index]
        if _normalize_criterion(proposal.criterion) != _normalize_criterion(criterion):
            return [], f"criterion {index} evidence does not match the confirmed criterion text"

        command = proposal.command.strip()
        executable = command.split(maxsplit=1)[0].casefold()
        if executable in _TRIVIAL_VERIFICATION_EXECUTABLES:
            return [], f"criterion {index} uses a trivial command that proves no behavior"
        argv, command_error = parse_allowed_command(command)
        if command_error is not None or argv is None:
            return [], f"criterion {index} uses a command outside the QA verification allowlist"
        command_signature = tuple(argv)
        if command_signature in used_commands:
            return [], f"criterion {index} reuses another criterion's verification command"
        result_index = next(
            (
                candidate_index
                for candidate_index, result in enumerate(execution_results)
                if candidate_index not in used_result_indexes
                and result.get("command") == command
                and result.get("refused") is None
                and result.get("exit_code") == 0
            ),
            None,
        )
        if result_index is None:
            return [], (
                f"criterion {index} is not linked to its own cleanly passing command result"
            )
        used_result_indexes.add(result_index)
        used_commands.add(command_signature)
        result = execution_results[result_index]
        verified.append(
            AcceptanceCriterionEvidence(
                criterion_index=index,
                criterion=criterion,
                command=command,
                execution_result_index=result_index,
                evidence=_evidence_summary(result),
            )
        )
    return verified, None


def persisted_criterion_evidence_error(
    acceptance_criteria: Sequence[str],
    raw_evidence: object,
    execution_results: Sequence[Mapping[str, object]],
) -> str | None:
    if not isinstance(raw_evidence, list) or not raw_evidence:
        return "verification report has no criterion-level acceptance evidence"
    try:
        persisted = [AcceptanceCriterionEvidence.model_validate(item) for item in raw_evidence]
    except ValidationError:
        return "verification report criterion evidence has an invalid structure"

    expected, error = build_verified_criterion_evidence(
        acceptance_criteria,
        persisted,
        execution_results,
    )
    if error is not None:
        return error
    if [item.model_dump() for item in persisted] != [item.model_dump() for item in expected]:
        return "verification report criterion evidence is not backed by framework execution results"
    return None
