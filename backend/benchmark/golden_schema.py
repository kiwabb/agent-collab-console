"""Golden fixture schema (Pydantic v2).

A "golden task" is a frozen, hand-validated issue spec that the runner
executes on the real Conductor and then scores. The schema mirrors the
SWE-bench-Verified shape (solvable from the description alone + pinned
expected commands) so a contributor can add a fixture without inventing
fields.

Layout on disk:

  backend/benchmark/golden/<id>.json

Each file is one ``GoldenIssue`` JSON. The loader (PR1) validates every
file at import time and the schema validation tests assert that every
checked-in fixture is well-formed.

Design choices:

  - ``pinned_qa_commands`` carries the FAIL_TO_PASS analog: the runner
    runs each command in the worktree, captures ``(exit_code, duration,
    stdout/stderr tail)``, and the execution scorer compares against
    ``expected_exit_code``. The hard "is the agent's code correct"
    signal lives here.
  - ``acceptance_criteria`` is the rubric layer: a separate scorer
    measures how many of the criteria the agent's completed work
    addresses. The matcher is intentionally simple (string keyword
    overlap) in PR1; LLM-as-judge is opt-in in PR3.
  - ``difficulty`` + ``tags`` are for filtering, not scoring — the
    runner uses them to pick a subset per epoch budget and the
    frontend groups the leaderboard by them.
  - ``source_issue_id`` is optional attribution when a golden task is
    derived from a real archived issue. The runner does not use it.
"""

from __future__ import annotations  # noqa: I001

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator


_DIFFICULTY = Literal["trivial", "small", "medium", "large"]


class PinnedCommand(BaseModel):
    """One command the runner will execute in the worktree.

    The expected exit code defaults to 0 (success) because most golden
    tasks are "make this command pass". A non-zero expected is allowed
    for tasks that assert a *failure* (e.g. "this command should now
    reject the bad input").
    """

    command: str = Field(min_length=1, max_length=2000)
    expected_exit_code: int = 0
    timeout_s: int = Field(default=60, ge=1, le=600)
    description: str | None = None

    @field_validator("command")
    @classmethod
    def _no_dangerous_shell(cls, v: str) -> str:
        """The runner runs these strings; reject anything that smells like
        a destructive shell pattern even in the test fixtures.

        This is belt-and-suspenders. The runner itself enforces a strict
        allowlist (no ``rm -rf``, no ``sudo``, no outbound network);
        validating at JSON-load time catches mistakes earlier.
        """
        forbidden = re.compile(
            r"(\brm\s+-rf\b|\bsudo\b|\bcurl\s+[^|]*\|\s*(ba)?sh\b|\bdd\s+if=)",
            re.IGNORECASE,
        )
        if forbidden.search(v):
            raise ValueError(f"pinned_qa_commands entry contains a forbidden shell pattern: {v!r}")
        return v


class GoldenIssue(BaseModel):
    """One frozen golden task. See module docstring for the full rationale."""

    id: str = Field(
        min_length=3,
        max_length=80,
        pattern=r"^[a-z0-9][a-z0-9._-]+$",
        description=(
            "Stable identifier; used as the file stem under "
            "backend/benchmark/golden/<id>.json and as the run record's "
            "issue_id column."
        ),
    )
    title: str = Field(min_length=5, max_length=200)
    description: str = Field(
        min_length=20,
        description=(
            "The full issue text the agent sees. Must be solvable from "
            "this text alone (SWE-bench-Verified rule)."
        ),
    )
    acceptance_criteria: list[str] = Field(
        min_length=1,
        max_length=20,
        description=(
            "The rubric the coverage scorer grades against. Each entry is "
            "a short statement (one sentence) that the agent's completed "
            "work should make true."
        ),
    )
    pinned_qa_commands: list[PinnedCommand] = Field(
        min_length=1,
        max_length=20,
        description=(
            "The FAIL_TO_PASS analog: one or more commands the runner "
            "executes in the worktree after the Conductor finalises."
        ),
    )
    expected_outcome: Literal["pass", "fail", "partial"] = "pass"
    tags: list[str] = Field(default_factory=list, max_length=10)
    difficulty: _DIFFICULTY = "small"
    source_issue_id: str | None = Field(
        default=None,
        description=(
            "Optional attribution when this fixture is derived from a real "
            "archived issue. The runner does not read this; it is for humans."
        ),
    )
    notes: str | None = None

    @field_validator("acceptance_criteria")
    @classmethod
    def _criteria_non_trivial(cls, v: list[str]) -> list[str]:
        for i, c in enumerate(v):
            if len(c.strip()) < 5:
                raise ValueError(f"acceptance_criteria[{i}] is too short (min 5 chars): {c!r}")
        return v

    @field_validator("tags")
    @classmethod
    def _tags_normalized(cls, v: list[str]) -> list[str]:
        # Lowercase, kebab-case, dedup. Keeps leaderboard grouping tidy.
        seen: set[str] = set()
        out: list[str] = []
        for t in v:
            t_norm = re.sub(r"\s+", "-", t.strip().lower())
            if not t_norm:
                continue
            if t_norm in seen:
                continue
            seen.add(t_norm)
            out.append(t_norm)
        return out
