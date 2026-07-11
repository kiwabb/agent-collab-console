"""Tests for the golden fixture schema + loader (PR1).

These tests pin the contract that:

  1. Every checked-in fixture in ``backend/benchmark/golden/`` loads
     cleanly (catches a typo at PR time, not at runner time).
  2. The Pydantic schema rejects malformed shapes (missing required
     fields, bad id patterns, dangerous shell patterns).
  3. The loader is stable (ids in sorted order), the whitelist filter
     works, and missing directories fail loudly.
"""

from __future__ import annotations  # noqa: I001

import json
from pathlib import Path

import pytest

from benchmark import golden_loader
from benchmark.golden_loader import GoldenFixtureError, ids, load_all
from benchmark.golden_schema import GoldenIssue, PinnedCommand


REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Loader — every checked-in fixture is well-formed
# ---------------------------------------------------------------------------


def test_every_checked_in_fixture_loads():
    """The repo's benchmark/golden/ directory is the source of truth.

    A typo in any fixture (missing field, bad id, etc.) fails here
    instead of silently dropping a task from the leaderboard.
    """
    fixtures = load_all()
    assert len(fixtures) >= 10, (
        f"expected at least 10 golden fixtures, found {len(fixtures)}; "
        "the methodology recommends ~10-20 hand-validated tasks to start"
    )


def test_backend_container_includes_and_persists_benchmark_package():
    dockerfile = (REPO_ROOT / "backend" / "Dockerfile").read_text()
    compose = (REPO_ROOT / "docker-compose.yml").read_text()

    assert "COPY benchmark/ ./benchmark/" in dockerfile
    assert "ln -s /var/lib/agent-collab/benchmark.db /app/benchmark.db" in dockerfile
    assert "benchmark-data:/var/lib/agent-collab" in compose
    assert "benchmark-data:" in compose


def test_fixture_ids_are_unique():
    fixtures = load_all()
    seen = [f.id for f in fixtures]
    dupes = [x for x in set(seen) if seen.count(x) > 1]
    assert not dupes, f"duplicate fixture ids: {dupes}"


def test_fixture_ids_match_file_stems():
    """File stem must equal the id field (loader assumption)."""
    root = golden_loader.DEFAULT_GOLDEN_DIR
    for path in root.glob("*.json"):
        fixture = golden_loader.load_golden(path)
        assert path.stem == fixture.id, (
            f"file {path.name!r} has id {fixture.id!r}; the loader keys fixtures by file stem"
        )


def test_ids_returns_stable_order():
    """ids() must be deterministic for test snapshots + leaderboard rows."""
    all_ids = ids()
    assert all_ids == sorted(all_ids), "ids() must return sorted list"
    # Round-trip: same result across calls.
    assert ids() == all_ids


# ---------------------------------------------------------------------------
# Schema — required fields + format constraints
# ---------------------------------------------------------------------------


def test_minimal_valid_fixture_parses():
    fixture = GoldenIssue(
        id="abc.test",
        title="A valid test fixture",
        description="Long enough description to clear the 20-char minimum.",
        acceptance_criteria=["One criterion that is long enough"],
        pinned_qa_commands=[
            PinnedCommand(argv=["echo", "ok"]),
        ],
    )
    assert fixture.id == "abc.test"
    assert fixture.expected_outcome == "pass"  # default
    assert fixture.difficulty == "small"  # default
    assert fixture.tags == []  # default


def test_id_pattern_rejects_uppercase_and_spaces():
    with pytest.raises(Exception):  # noqa: B017
        GoldenIssue(
            id="Has Spaces",
            title="title",
            description="description long enough for the field",
            acceptance_criteria=["one criterion"],
            pinned_qa_commands=[PinnedCommand(argv=["echo", "ok"])],
        )


def test_empty_acceptance_criteria_rejected():
    with pytest.raises(Exception):  # noqa: B017
        GoldenIssue(
            id="empty.criteria",
            title="title",
            description="description long enough for the field",
            acceptance_criteria=[],
            pinned_qa_commands=[PinnedCommand(argv=["echo", "ok"])],
        )


def test_short_criterion_rejected():
    with pytest.raises(Exception):  # noqa: B017
        GoldenIssue(
            id="short.crit",
            title="title",
            description="description long enough for the field",
            acceptance_criteria=["ok"],  # too short
            pinned_qa_commands=[PinnedCommand(argv=["echo", "ok"])],
        )


def test_pinned_command_zero_is_allowed():
    """Zero pinned commands is a degenerate fixture; schema should reject."""
    with pytest.raises(Exception):  # noqa: B017
        GoldenIssue(
            id="zero.cmd",
            title="title",
            description="description long enough for the field",
            acceptance_criteria=["one criterion that is long enough"],
            pinned_qa_commands=[],
        )


# ---------------------------------------------------------------------------
# Schema — structured command boundary
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["bash", "-lc", "echo unsafe"],
        ["/bin/echo", "unsafe"],
        ["../bin/tool"],
        ["echo", ""],
    ],
)
def test_pinned_command_rejects_unsafe_argv(argv: list[str]):
    with pytest.raises(Exception):  # noqa: B017
        PinnedCommand(argv=argv)


@pytest.mark.parametrize("cwd", ["/tmp", "../outside", "nested/../../outside"])
def test_pinned_command_rejects_cwd_outside_worktree(cwd: str):
    with pytest.raises(Exception):  # noqa: B017
        PinnedCommand(argv=["echo", "ok"], cwd=cwd)


def test_pinned_command_rejects_legacy_shell_string():
    with pytest.raises(Exception):  # noqa: B017
        PinnedCommand.model_validate({"command": "npm test"})


def test_pinned_command_accepts_structured_argv_and_relative_cwd():
    command = PinnedCommand(
        argv=["{python}", "-c", "print(1)"],
        cwd="backend",
    )
    assert command.argv == ["{python}", "-c", "print(1)"]
    assert command.cwd == "backend"


# ---------------------------------------------------------------------------
# Loader — error paths + whitelist
# ---------------------------------------------------------------------------


def test_load_all_missing_dir_raises(tmp_path: Path):
    with pytest.raises(GoldenFixtureError):
        load_all(root=tmp_path / "does-not-exist")


def test_load_all_whitelist_filters(tmp_path: Path):
    # Author two fixtures in a temp dir, load only one.
    a = tmp_path / "alpha.json"
    b = tmp_path / "beta.json"
    a.write_text(
        json.dumps(
            {
                "id": "alpha",
                "title": "Alpha fixture title here",
                "description": "Description long enough to clear the minimum.",
                "acceptance_criteria": ["alpha criterion long enough"],
                "pinned_qa_commands": [{"argv": ["echo", "alpha"]}],
            }
        )
    )
    b.write_text(
        json.dumps(
            {
                "id": "beta",
                "title": "Beta fixture title here",
                "description": "Description long enough to clear the minimum.",
                "acceptance_criteria": ["beta criterion long enough"],
                "pinned_qa_commands": [{"argv": ["echo", "beta"]}],
            }
        )
    )
    only_alpha = load_all(root=tmp_path, ids=["alpha"])
    assert [f.id for f in only_alpha] == ["alpha"]
    # Whitelist with a non-existent id: returns an empty list (the
    # other files are still validated, which surfaces typos).
    only_missing = load_all(root=tmp_path, ids=["nope"])
    assert only_missing == []


def test_load_all_malformed_file_raises(tmp_path: Path):
    bad = tmp_path / "broken.json"
    bad.write_text('{"id": "broken", "title": "too short"}')  # missing fields
    with pytest.raises(GoldenFixtureError):
        load_all(root=tmp_path)


# ---------------------------------------------------------------------------
# Tags normalization
# ---------------------------------------------------------------------------


def test_tags_are_normalized_deduped():
    fixture = GoldenIssue(
        id="tag.test",
        title="title here long enough",
        description="description long enough for the field",
        acceptance_criteria=["one criterion"],
        pinned_qa_commands=[PinnedCommand(argv=["echo", "ok"])],
        tags=["Backend", "BACKEND", "api endpoint", "api endpoint"],
    )
    assert fixture.tags == ["backend", "api-endpoint"]
