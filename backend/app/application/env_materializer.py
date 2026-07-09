"""Materialize .env file and validate required vars before project startup.

Agent-driven architecture (see PRD): the Operations Engineer Agent produces
``env_vars`` inside ``ProjectScriptSuggestion``. This module merges agent-inferred
defaults with user-supplied values from ``project_env_vars``, writes ``.env`` to
the project root, and validates that every secret variable has been filled.

Key rules:
- User-stored values (from ``project_env_vars`` table) ALWAYS win over agent defaults.
- Secret variables NEVER get an auto-filled value — value must come from the user.
- .env materialization is idempotent: if the file exists with identical content, skip.
- Missing required secret → structured ``EnvValidationError``, startup blocked.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.domain.models import ProjectEnvVar

logger = logging.getLogger(__name__)


@dataclass
class EnvValidationError:
    """A single missing or invalid env var that blocks startup."""

    name: str
    reason: str  # "missing_secret" | "missing_required" | "empty_value"
    description: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "reason": self.reason,
            "description": self.description,
        }


@dataclass
class EnvMaterializeResult:
    """Outcome of an .env materialization attempt."""

    written: bool  # True if we wrote or would have written .env
    skipped: bool  # True if .env already exists with identical content
    env_path: str
    errors: list[EnvValidationError] = field(default_factory=list)
    # The merged vars that were written (or would have been)
    vars_written: list[dict[str, object]] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return len(self.errors) == 0

    def to_dict(self) -> dict[str, object]:
        return {
            "written": self.written,
            "skipped": self.skipped,
            "env_path": self.env_path,
            "valid": self.valid,
            "errors": [e.to_dict() for e in self.errors],
        }


# Secret name hints (same heuristic as the deprecated env_detection.py, kept as
# a lightweight guardrail — not a rules engine).
_SECRET_HINTS = (
    "SECRET",
    "PASSWORD",
    "PASSWD",
    "TOKEN",
    "APIKEY",
    "API_KEY",
    "ACCESS_KEY",
    "PRIVATE_KEY",
    "CREDENTIAL",
    "AUTH",
    "SALT",
    "SIGNING",
)


def is_secret_name(name: str) -> bool:
    """Lightweight name-based secret heuristic. Only used as a double-check
    against agent misclassification, not as primary detection."""
    upper = name.upper()
    if any(hint in upper for hint in _SECRET_HINTS):
        return True
    # Bare "KEY" as a word segment: API_KEY, OPENAI_KEY → secret.
    # KEYCLOAK_URL → NOT secret (KEY is prefix of KEYCLOAK, not standalone).
    segments = upper.split("_")
    return "KEY" in segments


def merge_env_vars(
    *,
    agent_env_vars: list[dict[str, object]],
    stored_vars: list[ProjectEnvVar],
) -> list[dict[str, object]]:
    """Merge agent-inferred env vars with user-stored values.

    Priority: user-stored > agent-inferred.
    For secret vars: agent MUST have value=null; user-stored value wins.
    """
    # Build index of stored vars by name
    stored_by_name: dict[str, ProjectEnvVar] = {v.name: v for v in stored_vars}

    merged: list[dict[str, object]] = []
    seen: set[str] = set()

    # Start with agent vars
    for av in agent_env_vars:
        name = str(av.get("name", ""))
        if not name or name in seen:
            continue
        seen.add(name)

        agent_value = av.get("value")
        agent_secret = bool(av.get("secret", False))
        agent_source = str(av.get("source", "agent"))

        # Secret safety: if agent provided a value for a secret, discard it (log warning)
        if agent_secret and agent_value is not None:
            logger.warning(
                "Agent supplied value %r for secret var %s — discarding (security policy)",
                agent_value,
                name,
            )
            agent_value = None

        # Double-check: name-based secret detection catches agent misclassification
        if is_secret_name(name):
            agent_secret = True
            if agent_value is not None:
                logger.warning(
                    "Agent supplied value for name-matched secret %s — discarding",
                    name,
                )
                agent_value = None

        stored = stored_by_name.get(name)
        if stored is not None:
            # User-stored value wins
            merged.append({
                "name": name,
                "value": stored.value,
                "secret": stored.secret or agent_secret,
                "source": stored.source or agent_source,
            })
        else:
            merged.append({
                "name": name,
                "value": agent_value,
                "secret": agent_secret,
                "source": agent_source,
            })

    # Add stored vars not in agent list
    for sv in stored_vars:
        if sv.name not in seen:
            seen.add(sv.name)
            merged.append({
                "name": sv.name,
                "value": sv.value,
                "secret": sv.secret,
                "source": sv.source or "user",
            })

    return merged


def validate_merged_vars(
    merged: list[dict[str, object]],
) -> list[EnvValidationError]:
    """Validate merged env vars: every secret/required var must have a value.

    Returns a list of errors. Empty list = valid, safe to start.
    """
    errors: list[EnvValidationError] = []

    for mv in merged:
        name = str(mv.get("name", ""))
        secret = bool(mv.get("secret", False))
        value = mv.get("value")

        if secret and (value is None or str(value).strip() == ""):
            errors.append(
                EnvValidationError(
                    name=name,
                    reason="missing_secret",
                    description="敏感凭据，必须手动填写",
                )
            )
        elif value is None or str(value).strip() == "":
            errors.append(
                EnvValidationError(
                    name=name,
                    reason="empty_value",
                    description="变量值为空",
                )
            )

    return errors


def build_env_file_content(merged: list[dict[str, object]]) -> str:
    """Serialize merged env vars to .env file content (KEY=VALUE lines).

    Secret values with None/empty are written as KEY= (empty) — the validation
    step should have already caught these. Non-secret None values are written as
    KEY= (empty) since compose treats missing var as blank anyway.
    """
    lines: list[str] = [
        "# Generated by Agent Collab Console — Operations Engineer",
        "# Do not edit manually; changes will be overwritten on next startup.",
        "",
    ]
    for mv in merged:
        name = str(mv.get("name", ""))
        value = mv.get("value")
        value_str = str(value) if value is not None else ""
        lines.append(f"{name}={value_str}")

    return "\n".join(lines) + "\n"


async def materialize_env_file(
    *,
    project_id: str,
    repo_path: str,
    agent_env_vars: list[dict[str, object]],
    stored_vars: list[ProjectEnvVar],
    env_file_name: str = ".env",
) -> EnvMaterializeResult:
    """Merge, validate, and write a project's .env file.

    This is the main entry point called by ``project_run_manager.start()`` before
    spawning the dev server process.

    1. Merge agent vars with user-stored vars (user wins).
    2. Validate: secret vars must have values.
    3. If invalid, return errors WITHOUT writing.
    4. Write .env (idempotent: skip if identical content exists).
    """
    from pathlib import Path

    merged = merge_env_vars(
        agent_env_vars=agent_env_vars,
        stored_vars=stored_vars,
    )
    errors = validate_merged_vars(merged)
    if errors:
        return EnvMaterializeResult(
            written=False,
            skipped=False,
            env_path=str(Path(repo_path) / env_file_name),
            errors=errors,
            vars_written=merged,
        )

    content = build_env_file_content(merged)
    env_path = Path(repo_path) / env_file_name

    # Idempotent: skip if file already exists with identical content
    if env_path.is_file():
        try:
            existing = env_path.read_text(encoding="utf-8")
        except OSError:
            existing = ""
        if existing == content:
            logger.info(
                ".env already exists with identical content, skipping write. project=%s path=%s",
                project_id,
                env_path,
            )
            return EnvMaterializeResult(
                written=False,
                skipped=True,
                env_path=str(env_path),
                vars_written=merged,
            )

    try:
        env_path.write_text(content, encoding="utf-8")
    except OSError as exc:
        logger.error("Failed to write .env for project %s: %s", project_id, exc)
        return EnvMaterializeResult(
            written=False,
            skipped=False,
            env_path=str(env_path),
            errors=[
                EnvValidationError(
                    name="(filesystem)",
                    reason="write_failed",
                    description=f"无法写入 .env 文件: {exc}",
                )
            ],
            vars_written=merged,
        )

    logger.info(
        "Materialized .env for project %s: %d vars written to %s",
        project_id,
        len(merged),
        env_path,
    )
    return EnvMaterializeResult(
        written=True,
        skipped=False,
        env_path=str(env_path),
        vars_written=merged,
    )