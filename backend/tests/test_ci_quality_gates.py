from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
README = REPO_ROOT / "README.md"
BACKEND_SPEC_INDEX = REPO_ROOT / ".trellis" / "spec" / "vibe-kanban" / "backend" / "index.md"
BACKEND_GATE_COMMANDS = [
    "ruff check .",
    "mypy app benchmark tests --show-error-codes --no-pretty",
    'python -c "from app.main import app"',
    "pytest -q --tb=short --disable-warnings",
]
FRONTEND_GATE_COMMANDS = [
    "npm audit --registry=https://registry.npmjs.org",
    "npm run typecheck",
    "npm test",
    "npm run lint",
    "npm run build",
    "npm run format:check",
]


def _backend_pyproject() -> dict[str, object]:
    return tomllib.loads((BACKEND_ROOT / "pyproject.toml").read_text())


def _table(value: object, name: str) -> dict[str, object]:
    assert isinstance(value, Mapping), f"expected {name} to be a TOML table"
    return {str(key): item for key, item in value.items()}


def _ci_workflow() -> str:
    return CI_WORKFLOW.read_text()


def test_ci_quality_gates_do_not_soft_fail() -> None:
    workflow = _ci_workflow()

    assert "|| true" not in workflow
    assert "continue-on-error: true" not in workflow


def test_backend_ci_runs_documented_quality_gates() -> None:
    workflow = _ci_workflow()

    missing = [command for command in BACKEND_GATE_COMMANDS if command not in workflow]

    assert missing == []


def test_frontend_ci_runs_documented_quality_gates() -> None:
    workflow = _ci_workflow()

    missing = [command for command in FRONTEND_GATE_COMMANDS if command not in workflow]

    assert missing == []


def test_readme_documents_ci_quality_gates() -> None:
    readme = README.read_text()
    expected_commands = [*BACKEND_GATE_COMMANDS, *FRONTEND_GATE_COMMANDS]

    missing = [command for command in expected_commands if command not in readme]

    assert missing == []


def test_backend_python_version_contract_stays_aligned() -> None:
    pyproject = _backend_pyproject()
    project = _table(pyproject["project"], "project")
    tool = _table(pyproject["tool"], "tool")
    mypy = _table(tool["mypy"], "tool.mypy")
    ruff = _table(tool["ruff"], "tool.ruff")
    workflow = _ci_workflow()
    spec_index = BACKEND_SPEC_INDEX.read_text()

    assert project["requires-python"] == ">=3.12"
    assert mypy["python_version"] == "3.12"
    assert ruff["target-version"] == "py312"
    assert re.search(r'python-version:\s*"3\.12"', workflow)
    assert "Python 3.12+" in spec_index
