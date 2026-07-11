from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from app.application.env_detection import parse_dotenv
from app.application.env_materializer import (
    MANAGED_ENV_FORMAT_MARKER,
    MANAGED_ENV_MARKER,
    MANAGED_ENV_SECRET_MARKER_PREFIX,
    is_secret_name,
)

REDACTION_MARKER = "[REDACTED]"
_SKIPPED_DIRECTORIES = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".next",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "build",
        "coverage",
        "dist",
        "node_modules",
        "target",
        "venv",
    }
)
_DOTENV_TEMPLATE_SUFFIXES = (".example", ".sample", ".template", ".dist", ".defaults")
_FERNET_CIPHERTEXT_RE = re.compile(r"gAAAA[A-Za-z0-9_-]{60,}={0,2}")


class SecretOutputRedactionError(RuntimeError):
    pass


def _is_runtime_dotenv_file(name: str) -> bool:
    if name == ".env":
        return True
    return name.startswith(".env.") and not name.endswith(_DOTENV_TEMPLATE_SUFFIXES)


def _project_dotenv_values(project_root: Path) -> set[str]:
    values: set[str] = set()

    def _raise_walk_error(error: OSError) -> None:
        raise SecretOutputRedactionError(
            "project environment files could not be inspected"
        ) from error

    for current_root, directories, files in os.walk(
        project_root,
        topdown=True,
        followlinks=False,
        onerror=_raise_walk_error,
    ):
        directories[:] = [name for name in directories if name not in _SKIPPED_DIRECTORIES]
        for filename in files:
            if not _is_runtime_dotenv_file(filename):
                continue
            path = Path(current_root) / filename
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                raise SecretOutputRedactionError(
                    "a project environment file could not be read for output redaction"
                ) from exc
            parsed = parse_dotenv(text)
            stripped_lines = [line.strip() for line in text.splitlines()]
            declared_secret_names = {
                line.removeprefix(MANAGED_ENV_SECRET_MARKER_PREFIX).strip()
                for line in stripped_lines
                if line.startswith(MANAGED_ENV_SECRET_MARKER_PREFIX)
            }
            legacy_managed_file = (
                MANAGED_ENV_MARKER in stripped_lines
                and MANAGED_ENV_FORMAT_MARKER not in stripped_lines
            )
            for name, value in parsed.items():
                if not value:
                    continue
                if (
                    legacy_managed_file
                    or name in declared_secret_names
                    or is_secret_name(name)
                    or len(value) >= 4
                ):
                    values.add(value)
    return values


@dataclass(frozen=True)
class SecretOutputRedactor:
    values: tuple[str, ...]

    @classmethod
    def from_workspace(
        cls,
        workspace_path: str,
        child_env: Mapping[str, str],
    ) -> SecretOutputRedactor:
        try:
            project_root = Path(workspace_path).resolve()
        except (OSError, RuntimeError) as exc:
            raise SecretOutputRedactionError(
                "project root could not be resolved for output redaction"
            ) from exc
        values = _project_dotenv_values(project_root)
        values.update(
            value
            for name, value in child_env.items()
            if value and is_secret_name(name)
        )
        return cls(values=tuple(sorted(values, key=len, reverse=True)))

    def redact(self, text: str) -> str:
        redacted = text
        for value in self.values:
            redacted = redacted.replace(value, REDACTION_MARKER)
        return _FERNET_CIPHERTEXT_RE.sub(REDACTION_MARKER, redacted)


# Compatibility names retained for the QA workflow while the implementation is
# shared by every project subprocess boundary.
QAOutputRedactionError = SecretOutputRedactionError
QAOutputRedactor = SecretOutputRedactor
