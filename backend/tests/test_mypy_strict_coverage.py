from __future__ import annotations

import tomllib
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
STRICT_ROOTS = ("app", "benchmark")
ALLOWED_TEST_MYPY_IGNORE_ERRORS = {
    BACKEND_ROOT / "tests" / "test_codex_tasks.py",
}
MYPY_IGNORE_ERRORS_DIRECTIVE = "# mypy:" + " ignore-errors"


def _module_name(path: Path) -> str:
    relative = path.relative_to(BACKEND_ROOT).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _strict_override_modules() -> set[str]:
    pyproject = tomllib.loads((BACKEND_ROOT / "pyproject.toml").read_text())
    modules: set[str] = set()
    for override in pyproject["tool"]["mypy"].get("overrides", []):
        if override.get("disallow_untyped_defs") is not True:
            continue
        value = override["module"]
        if isinstance(value, str):
            modules.add(value)
        else:
            modules.update(value)
    return modules


def test_app_and_benchmark_modules_are_strict() -> None:
    expected = {
        _module_name(path)
        for root in STRICT_ROOTS
        for path in (BACKEND_ROOT / root).rglob("*.py")
    }

    strict_modules = _strict_override_modules()
    missing = sorted(expected - strict_modules)

    assert missing == []


def test_no_loose_app_or_benchmark_mypy_override_remains() -> None:
    pyproject = tomllib.loads((BACKEND_ROOT / "pyproject.toml").read_text())
    loose_overrides: list[str] = []
    for override in pyproject["tool"]["mypy"].get("overrides", []):
        if override.get("disallow_untyped_defs") is True:
            continue
        value = override["module"]
        modules = [value] if isinstance(value, str) else value
        loose_overrides.extend(
            module for module in modules if module in {"app.*", "benchmark.*"}
        )

    assert loose_overrides == []


def test_test_mypy_ignore_errors_are_explicitly_allowlisted() -> None:
    offenders = sorted(
        path.relative_to(BACKEND_ROOT).as_posix()
        for path in (BACKEND_ROOT / "tests").rglob("*.py")
        if MYPY_IGNORE_ERRORS_DIRECTIVE in path.read_text()
        and path not in ALLOWED_TEST_MYPY_IGNORE_ERRORS
    )

    assert offenders == []


def test_legacy_codex_tasks_mypy_optout_stays_runtime_skipped() -> None:
    source = (BACKEND_ROOT / "tests" / "test_codex_tasks.py").read_text()

    assert MYPY_IGNORE_ERRORS_DIRECTIVE in source
    assert "pytestmark = pytest.mark.skip" in source
    assert "tests/test_codex_tasks_ported.py" in source
