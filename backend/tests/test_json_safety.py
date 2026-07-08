from __future__ import annotations

from app.json_safety import (
    object_dict,
    object_dict_list,
    object_dict_or_none,
    object_list,
    parse_json_list,
    parse_json_object,
    parse_json_object_list,
    parse_json_value,
    string_list_value,
    string_value,
)


def test_object_dict_coerces_mapping_keys_to_strings() -> None:
    assert object_dict({1: "one", "two": 2}) == {"1": "one", "two": 2}
    assert object_dict(["not", "a", "mapping"]) == {}
    assert object_dict_or_none({"ok": True}) == {"ok": True}
    assert object_dict_or_none("nope") is None


def test_object_list_and_object_dict_list_keep_only_expected_shapes() -> None:
    assert object_list(("not", "json", "list")) == []
    assert object_list(["a", 1]) == ["a", 1]
    assert object_dict_list([{"x": 1}, ["bad"], {2: "two"}]) == [
        {"x": 1},
        {"2": "two"},
    ]


def test_string_helpers_preserve_existing_fallback_semantics() -> None:
    assert string_value("ok") == "ok"
    assert string_value(3, default="fallback") == "fallback"
    assert string_list_value(["a", 2]) == ["a", "2"]
    assert string_list_value("bad", fallback=("x", "y")) == ["x", "y"]


def test_parse_json_object_returns_none_for_invalid_or_non_object_payloads() -> None:
    assert parse_json_object('{"a": 1}') == {"a": 1}
    assert parse_json_object(b'{"a": 1}') == {"a": 1}
    assert parse_json_object("[1, 2]") is None
    assert parse_json_object("{bad") is None
    assert parse_json_object(None) is None


def test_parse_json_value_preserves_scalar_shapes_and_default() -> None:
    sentinel = object()

    assert parse_json_value('"hello"') == "hello"
    assert parse_json_value("42") == 42
    assert parse_json_value("null", default=sentinel) is None
    assert parse_json_value("{bad", default=sentinel) is sentinel
    assert parse_json_value(None, default=sentinel) is sentinel


def test_parse_json_list_and_object_list_are_safe() -> None:
    assert parse_json_list('["a", 2]') == ["a", 2]
    assert parse_json_list('{"a": 1}') == []
    assert parse_json_list("{bad") == []
    assert parse_json_object_list('[{"a": 1}, "bad", {"b": 2}]') == [
        {"a": 1},
        {"b": 2},
    ]
