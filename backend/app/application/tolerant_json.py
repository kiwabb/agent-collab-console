"""Tolerant JSON loader for role-agent outputs.

Models like MiniMax-M2.7 sometimes drift on strict-JSON prompts and emit:
  - markdown code fences (```json … ```)
  - prose before/after the actual JSON
  - missing opening quotes on object keys: `{key": "v"}` → should be `{"key": "v"}`
  - missing closing quotes on values
  - trailing commas before `]` or `}`

`tolerant_json_loads(s)` first extracts the first complete JSON object via
brace-balancing (string-literal aware), then runs a small set of regex-based
repairs, then attempts json.loads. If everything fails it raises the original
JSONDecodeError so callers can surface the parse error.
"""

from __future__ import annotations

import json
import re
from typing import Any


def _extract_first_json_object(text: str) -> str | None:
    """Find the first complete top-level `{...}` by depth-aware brace
    balancing. Skips braces inside string literals and handles backslash
    escapes inside strings."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


# Matches: an opening `{` or `,` followed by an identifier and `":`
# where the opening quote of the key was dropped. Example match:
#   `{priority":"P0"` or `,priority":"P0"`
# We capture the bare identifier and rewrite it as `"<identifier>":`.
_MISSING_OPEN_QUOTE_KEY_RE = re.compile(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)(\":)")

# Matches trailing commas inside arrays/objects: `,]` or `,}` with optional ws.
_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")


def _strip_markdown_fence(text: str) -> str:
    # ```json ... ``` or ``` ... ```
    fenced = re.match(r"^\s*```(?:json)?\s*\n?(.*?)\n?```\s*$", text, re.DOTALL)
    if fenced:
        return fenced.group(1)
    return text


def _repair(text: str) -> str:
    repaired = text
    # 1. Missing opening quote before key:  `{key":` → `{"key":`
    repaired = _MISSING_OPEN_QUOTE_KEY_RE.sub(r'\1"\2\3', repaired)
    # 2. Trailing commas inside arrays/objects.
    repaired = _TRAILING_COMMA_RE.sub(r"\1", repaired)
    return repaired


def tolerant_json_loads(s: str) -> Any:
    """Best-effort json.loads tolerant to common LLM JSON-output mistakes.

    Pipeline:
      1. Strip optional markdown fences.
      2. Strict json.loads — fast path for clean output.
      3. Depth-aware brace extraction to drop prose before/after.
      4. Local regex repairs (missing key-open-quote, trailing commas).
      5. json-repair library (handles missing braces, missing closing quotes,
         comma/brace mix-ups, lots of model-specific drift).

    Raises the original JSONDecodeError if every stage fails.
    """
    # First, strip optional markdown fences around the whole thing.
    stripped = _strip_markdown_fence(s.strip())

    # Try fast path — already clean JSON.
    try:
        return json.loads(stripped)
    except json.JSONDecodeError as exc_strict:
        first_exc = exc_strict

    # Extract the largest top-level {...} via depth-aware brace balancing.
    extracted = _extract_first_json_object(stripped)
    candidate = extracted if extracted else stripped

    # Try the extracted slice as-is.
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    # Apply local regex repairs.
    repaired = _repair(candidate)
    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        pass

    # json-repair handles a wider class of drift (missing braces, missing
    # quotes on values, comma/brace mix-ups, etc.) than my regex set.
    try:
        from json_repair import repair_json
        # repair_json returns a JSON string with `return_objects=False` (default);
        # easier to just round-trip via json.loads on it.
        repaired_str = repair_json(candidate, return_objects=False)
        if repaired_str:
            return json.loads(repaired_str)
    except Exception:  # noqa: BLE001
        pass

    # Last resort: json-repair on the full (un-extracted) stripped text.
    try:
        from json_repair import repair_json
        repaired_str = repair_json(stripped, return_objects=False)
        if repaired_str:
            return json.loads(repaired_str)
    except Exception:  # noqa: BLE001
        pass

    # Surface the *original* strict error for the most informative location info.
    raise first_exc
