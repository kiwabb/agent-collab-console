"""Tests for tolerant_json — covers the actual failure patterns captured
from MiniMax-M2.7 during the end-to-end walkthrough on 2026-05-15."""

import json

import pytest

from app.application.tolerant_json import tolerant_json_loads


def test_clean_json_fast_path():
    assert tolerant_json_loads('{"a": 1, "b": [1, 2, 3]}') == {"a": 1, "b": [1, 2, 3]}


def test_markdown_fence_stripped():
    fenced = '```json\n{"x": "hi"}\n```'
    assert tolerant_json_loads(fenced) == {"x": "hi"}


def test_markdown_fence_no_lang():
    fenced = '```\n{"x": "hi"}\n```'
    assert tolerant_json_loads(fenced) == {"x": "hi"}


def test_prose_before_json():
    s = 'Sure, here is the result:\n{"x": "hi"}\nLet me know if anything else.'
    assert tolerant_json_loads(s) == {"x": "hi"}


def test_trailing_comma_in_array():
    assert tolerant_json_loads('{"a": [1, 2, 3,]}') == {"a": [1, 2, 3]}


def test_trailing_comma_in_object():
    assert tolerant_json_loads('{"a": 1, "b": 2,}') == {"a": 1, "b": 2}


def test_minimax_failure_missing_open_quote_on_key():
    """First real failure observed: MiniMax dropped the opening quote on
    'priority' in the second array element."""
    s = (
        '{"requirement_pool":['
        '{"priority":"P0","title":"Executor"},'
        '{priority":"P0","title":"Provider"},'
        '{priority":"P1","title":"Config"}'
        "]}"
    )
    result = tolerant_json_loads(s)
    pool = result["requirement_pool"]
    assert len(pool) == 3
    assert pool[1] == {"priority": "P0", "title": "Provider"}
    assert pool[2] == {"priority": "P1", "title": "Config"}


def test_minimax_failure_missing_open_brace_in_array():
    """Second real failure: MiniMax dropped the opening '{' before a key,
    producing }, "priority":... instead of },{ "priority":..."""
    s = (
        '{"requirement_pool":['
        '{"priority":"P0","title":"first","description":"...支持codex和claude"},'
        '"priority":"P0","title":"Runtime Catalog"'
        "]}"
    )
    result = tolerant_json_loads(s)
    pool = result["requirement_pool"]
    assert len(pool) == 2
    assert pool[0]["title"] == "first"
    assert pool[1]["title"] == "Runtime Catalog"


def test_unicode_chinese_payload():
    s = '{"语言": "zh-CN", "需求": ["统一管理 Runtime Catalog", "支持热更新"]}'
    result = tolerant_json_loads(s)
    assert result["语言"] == "zh-CN"
    assert len(result["需求"]) == 2


def test_deeply_nested():
    s = '{"a": {"b": {"c": {"d": [1, 2, 3]}}}}'
    assert tolerant_json_loads(s) == {"a": {"b": {"c": {"d": [1, 2, 3]}}}}


def test_strings_with_braces():
    """Brace-extractor must not be confused by braces inside string literals."""
    s = '{"template": "use {x} as placeholder", "n": 1}'
    assert tolerant_json_loads(s) == {"template": "use {x} as placeholder", "n": 1}


def test_strings_with_escaped_quotes():
    s = '{"sentence": "He said \\"hi\\""}'
    assert tolerant_json_loads(s) == {"sentence": 'He said "hi"'}


def test_empty_string_raises():
    with pytest.raises(json.JSONDecodeError):
        tolerant_json_loads("")


def test_pure_garbage_raises():
    with pytest.raises(json.JSONDecodeError):
        tolerant_json_loads("absolutely not json")
