#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
LOCAL_AGENT_DIR = SKILL_DIR.parent.parent
REQUIRED_REFERENCES = {
    "command-contract.md",
    "design-principles.md",
    "mcp-tools.md",
    "security.md",
}


def fail(message: str) -> None:
    raise SystemExit(message)


def validate_skill() -> None:
    skill_body = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    if "TODO" in skill_body or "[TODO" in skill_body:
        fail("SKILL.md contains an unfinished placeholder")
    missing = [
        name for name in sorted(REQUIRED_REFERENCES) if not (SKILL_DIR / "references" / name).is_file()
    ]
    if missing:
        fail(f"missing Skill references: {', '.join(missing)}")
    if not (SKILL_DIR / "agents" / "openai.yaml").is_file():
        fail("agents/openai.yaml is missing")


def validate_manifest(name: str, agent_kind: str) -> None:
    path = LOCAL_AGENT_DIR / "manifests" / name
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("manifestVersion") != 1 or value.get("agentKind") != agent_kind:
        fail(f"{name} has an invalid identity or version")
    skill = value.get("skill")
    if not isinstance(skill, dict) or skill.get("version") != "1.0.0":
        fail(f"{name} does not bind Skill version 1.0.0")
    authority = value.get("authority")
    if not isinstance(authority, dict):
        fail(f"{name} has no authority declaration")
    if authority.get("allowed") != ["prototype:read", "prototype:propose"]:
        fail(f"{name} grants an unexpected permission")
    if authority.get("forbidden") != ["prototype:apply", "prototype:publish"]:
        fail(f"{name} omits a forbidden authority")


def main() -> None:
    validate_skill()
    validate_manifest("claude-code.json", "claude_code")
    validate_manifest("codex.json", "codex")
    print("prototype-designer package is valid")


if __name__ == "__main__":
    main()
