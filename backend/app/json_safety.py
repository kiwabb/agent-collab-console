from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

JsonObject = dict[str, object]
JsonList = list[object]


def object_dict(value: object) -> JsonObject:
    """Return a string-keyed dict for mapping-like JSON payloads."""
    if not isinstance(value, Mapping):
        return {}
    return {str(key): item for key, item in value.items()}


def object_dict_or_none(value: object) -> JsonObject | None:
    if not isinstance(value, Mapping):
        return None
    return object_dict(value)


def object_list(value: object) -> JsonList:
    return list(value) if isinstance(value, list) else []


def object_dict_list(value: object) -> list[JsonObject]:
    if not isinstance(value, list):
        return []
    return [object_dict(item) for item in value if isinstance(item, Mapping)]


def string_value(value: object, default: str = "") -> str:
    return value if isinstance(value, str) else default


def string_list_value(value: object, fallback: Sequence[str] | None = None) -> list[str]:
    if not isinstance(value, list):
        return list(fallback or ())
    return [str(item) for item in value]


def parse_json_object(raw: str | bytes | bytearray | None) -> JsonObject | None:
    if not raw:
        return None
    try:
        parsed: object = json.loads(raw)
    except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
        return None
    return object_dict_or_none(parsed)


def parse_json_value(raw: str | bytes | bytearray | None, *, default: object = None) -> object:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
        return default


def parse_json_list(raw: str | bytes | bytearray | None) -> JsonList:
    if not raw:
        return []
    try:
        parsed: object = json.loads(raw)
    except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
        return []
    return object_list(parsed)


def parse_json_object_list(raw: str | bytes | bytearray | None) -> list[JsonObject]:
    if not raw:
        return []
    try:
        parsed: object = json.loads(raw)
    except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
        return []
    return object_dict_list(parsed)
