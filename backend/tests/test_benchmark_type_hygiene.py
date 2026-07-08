from __future__ import annotations

import re
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_ROOT = BACKEND_ROOT / "benchmark"
EXPLICIT_ANY_PATTERN = re.compile(
    r"\bAny\b|dict\[str,\s*Any\]|Awaitable\[Any\]|Callable\[[^\n]*Any"
)


def test_benchmark_package_avoids_explicit_any() -> None:
    matches: list[str] = []
    for path in sorted(BENCHMARK_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        source = path.read_text()
        for line_number, line in enumerate(source.splitlines(), start=1):
            if EXPLICIT_ANY_PATTERN.search(line):
                rel = path.relative_to(BACKEND_ROOT)
                matches.append(f"{rel}:{line_number}: {line.strip()}")

    assert matches == []
