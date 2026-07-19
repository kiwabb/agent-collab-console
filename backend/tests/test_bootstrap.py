from __future__ import annotations

import ast
from pathlib import Path


def _timeout_accessor_name(call: ast.Call, keyword_name: str) -> str:
    for keyword in call.keywords:
        if keyword.arg != keyword_name:
            continue
        value = keyword.value
        assert isinstance(value, ast.Call)
        assert not value.args
        assert not value.keywords
        function = value.func
        assert isinstance(function, ast.Attribute)
        assert isinstance(function.value, ast.Name)
        assert function.value.id == "timeouts"
        return function.attr
    raise AssertionError(f"missing PrototypeSnapWorker keyword: {keyword_name}")


def test_bootstrap_injects_snap_worker_timeout_policy() -> None:
    bootstrap_path = Path(__file__).parents[1] / "app" / "bootstrap.py"
    module = ast.parse(bootstrap_path.read_text(encoding="utf-8"))
    snap_worker_calls = [
        node
        for node in ast.walk(module)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "PrototypeSnapWorker"
    ]

    assert len(snap_worker_calls) == 1
    call = snap_worker_calls[0]
    assert (
        _timeout_accessor_name(call, "attest_timeout_s")
        == "prototype_snap_worker_attest_timeout_s"
    )
    assert (
        _timeout_accessor_name(call, "attest_many_timeout_s")
        == "prototype_snap_worker_attest_many_timeout_s"
    )


def test_bootstrap_injects_runtime_worker_timeout_policy() -> None:
    bootstrap_path = Path(__file__).parents[1] / "app" / "bootstrap.py"
    module = ast.parse(bootstrap_path.read_text(encoding="utf-8"))
    runtime_worker_calls = [
        node
        for node in ast.walk(module)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "PrototypeRuntimeWorker"
    ]

    assert len(runtime_worker_calls) == 1
    assert (
        _timeout_accessor_name(runtime_worker_calls[0], "timeout_s")
        == "prototype_runtime_worker_timeout_s"
    )
