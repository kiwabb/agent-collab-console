from __future__ import annotations

from pathlib import Path


def pytest_addoption(parser) -> None:
    parser.addoption(
        "--runslow",
        action="store_true",
        default=False,
        help="run tests marked as slow",
    )


def pytest_configure(config) -> None:
    """Default to the fast lane unless the user explicitly asks for slow tests.

    `pytest.ini` sets `-m "not slow"` so plain `pytest` stays fast. We clear the
    mark expression in two cases:
    - the caller passed `--runslow`
    - the caller explicitly targeted files/directories on the command line
      (e.g. `pytest tests/test_projects_api.py`)
    """
    raw_args = list(getattr(config.invocation_params, "args", ()) or ())
    if config.getoption("--runslow") or _has_explicit_selection(raw_args):
        config.option.markexpr = ""


def _has_explicit_selection(args: list[str]) -> bool:
    for arg in args:
        if not arg or arg.startswith("-"):
            continue
        if "::" in arg:
            return True
        path_part = arg.split("::", 1)[0]
        if Path(path_part).suffix in {".py", ".txt"}:
            return True
        if Path(path_part).exists():
            return True
    return False
