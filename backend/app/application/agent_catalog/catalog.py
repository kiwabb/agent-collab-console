from __future__ import annotations  # noqa: I001

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SPECIALIST_PREFIX = "specialist:"
CUSTOM_PREFIX = "custom:"


@dataclass
class AgentDefinition:
    role_key: str
    display_name: str
    prompt_template: str
    output_schema: dict[str, Any]
    default_max_retries: int = 1
    agent_tier: str = "specialist"


class AgentCatalog:
    """In-process registry for predefined specialists and ad-hoc custom agents."""

    def __init__(self, specialists_dir: Path | None = None) -> None:
        self._specialists_dir = specialists_dir or Path(__file__).parent / "specialists"
        self._specialists = self._load_specialists()
        self._custom: dict[str, AgentDefinition] = {}

    def list_available_agents(self) -> list[AgentDefinition]:
        return [*self._specialists.values(), *self._custom.values()]

    def resolve_agent(self, role_key: str) -> AgentDefinition:
        normalized = self.normalize_role_key(role_key)
        if normalized in self._specialists:
            return self._specialists[normalized]
        custom_key = (
            normalized if normalized.startswith(CUSTOM_PREFIX) else f"{CUSTOM_PREFIX}{normalized}"
        )
        if custom_key in self._custom:
            return self._custom[custom_key]
        raise KeyError(f"Unknown agent role_key: {role_key}")

    def register_custom(
        self,
        *,
        name: str,
        prompt: str,
        schema: dict[str, Any] | None = None,
    ) -> AgentDefinition:
        slug = self._slug(name)
        role_key = f"{CUSTOM_PREFIX}{slug}"
        definition = AgentDefinition(
            role_key=role_key,
            display_name=name,
            prompt_template=prompt,
            output_schema=schema or {"type": "object"},
            default_max_retries=1,
            agent_tier="custom",
        )
        self._custom[role_key] = definition
        return definition

    @staticmethod
    def normalize_role_key(role_key: str) -> str:
        if role_key.startswith(SPECIALIST_PREFIX):
            return role_key[len(SPECIALIST_PREFIX) :]
        return role_key

    def _load_specialists(self) -> dict[str, AgentDefinition]:
        definitions: dict[str, AgentDefinition] = {}
        for path in sorted(self._specialists_dir.glob("*.yaml")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            definition = AgentDefinition(
                role_key=payload["role_key"],
                display_name=payload["display_name"],
                prompt_template=payload["prompt_template"],
                output_schema=payload.get("output_schema") or {"type": "object"},
                default_max_retries=int(payload.get("default_max_retries") or 1),
            )
            definitions[definition.role_key] = definition
        return definitions

    @staticmethod
    def _slug(value: str) -> str:
        return "_".join(value.strip().lower().replace("-", "_").split())
