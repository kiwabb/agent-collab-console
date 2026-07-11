"""Tests for env_materializer: merge, validate, materialize, is_secret_name."""

from __future__ import annotations

import logging

from app.application.env_crypto import encrypt, generate_key
from app.application.env_materializer import (
    MANAGED_ENV_FORMAT_MARKER,
    MANAGED_ENV_SECRET_MARKER_PREFIX,
    EnvValidationError,
    build_env_file_content,
    is_secret_name,
    materialize_env_file,
    merge_env_vars,
    validate_merged_vars,
)
from app.domain.models import ProjectEnvVar

# ---- is_secret_name ----------------------------------------------------


def test_is_secret_name_detects_secret():
    assert is_secret_name("OPENAI_API_KEY") is True
    assert is_secret_name("SECRET_TOKEN") is True
    assert is_secret_name("DB_PASSWORD") is True
    assert is_secret_name("AWS_ACCESS_KEY_ID") is True
    assert is_secret_name("JWT_SIGNING_KEY") is True
    assert is_secret_name("CREDENTIAL") is True
    assert is_secret_name("AUTH_TOKEN") is True


def test_is_secret_name_ignores_non_secret():
    assert is_secret_name("APP_PORT") is False
    assert is_secret_name("BACKEND_HOST") is False
    assert is_secret_name("NODE_ENV") is False
    assert is_secret_name("BASE_REGISTRY") is False
    assert is_secret_name("KEYCLOAK_URL") is False  # KEY is prefix, not standalone
    assert is_secret_name("WHISPER_MODEL_SIZE") is False


# ---- merge_env_vars ----------------------------------------------------


def test_merge_agent_vars_only():
    agent = [
        {"name": "APP_PORT", "value": "3000", "secret": False, "source": "agent"},
        {"name": "BACKEND_PORT", "value": "8483", "secret": False, "source": "agent"},
    ]
    merged = merge_env_vars(agent_env_vars=agent, stored_vars=[])
    assert len(merged) == 2
    app = next(v for v in merged if v["name"] == "APP_PORT")
    assert app["value"] == "3000"
    assert app["secret"] is False


def test_merge_stored_wins_over_agent():
    agent = [{"name": "APP_PORT", "value": "3000", "secret": False, "source": "agent"}]
    stored = [
        ProjectEnvVar(
            project_id="p1", name="APP_PORT", value="8080", secret=False, source="user"
        ),
    ]
    merged = merge_env_vars(agent_env_vars=agent, stored_vars=stored)
    app = next(v for v in merged if v["name"] == "APP_PORT")
    assert app["value"] == "8080"  # user wins
    assert app["source"] == "user"


def test_merge_stored_not_in_agent_still_included():
    agent: list[dict[str, object]] = []
    stored = [
        ProjectEnvVar(
            project_id="p1", name="CUSTOM_VAR", value="hello", secret=False, source="user"
        ),
    ]
    merged = merge_env_vars(agent_env_vars=agent, stored_vars=stored)
    assert len(merged) == 1
    assert merged[0]["name"] == "CUSTOM_VAR"


def test_agent_secret_value_discarded():
    """Security: agent MUST NOT supply a secret value — discard it."""
    agent = [
        {"name": "OPENAI_API_KEY", "value": "sk-fake-from-agent", "secret": True, "source": "agent"},
    ]
    merged = merge_env_vars(agent_env_vars=agent, stored_vars=[])
    assert merged[0]["value"] is None
    assert merged[0]["secret"] is True


def test_name_based_secret_override():
    """When agent forgets secret=True, name heuristic catches it."""
    agent = [
        {"name": "DB_PASSWORD", "value": "agent-guessed", "secret": False, "source": "agent"},
    ]
    merged = merge_env_vars(agent_env_vars=agent, stored_vars=[])
    assert merged[0]["secret"] is True
    assert merged[0]["value"] is None  # discarded


def test_stored_secret_wins_and_agent_value_ignored():
    agent = [
        {"name": "OPENAI_API_KEY", "value": "sk-agent-wrong", "secret": True, "source": "agent"},
    ]
    stored = [
        ProjectEnvVar(
            project_id="p1",
            name="OPENAI_API_KEY",
            value="encrypted-user-key",
            secret=True,
            source="user",
        ),
    ]
    merged = merge_env_vars(agent_env_vars=agent, stored_vars=stored)
    key_var = next(v for v in merged if v["name"] == "OPENAI_API_KEY")
    assert key_var["value"] == "encrypted-user-key"  # user wins


# ---- validate_merged_vars ----------------------------------------------------


def test_validate_secret_missing():
    merged: list[dict[str, object]] = [
        {"name": "APP_PORT", "value": "3000", "secret": False},
        {"name": "OPENAI_API_KEY", "value": None, "secret": True},
    ]
    errors = validate_merged_vars(merged)
    assert len(errors) == 1
    assert errors[0].name == "OPENAI_API_KEY"
    assert errors[0].reason == "missing_secret"


def test_validate_empty_secret_value():
    merged = [
        {"name": "API_TOKEN", "value": "", "secret": True},
    ]
    errors = validate_merged_vars(merged)
    assert len(errors) == 1
    assert errors[0].reason == "missing_secret"


def test_validate_empty_non_secret_value():
    merged = [
        {"name": "SOME_VAR", "value": "", "secret": False},
    ]
    errors = validate_merged_vars(merged)
    assert len(errors) == 1
    assert errors[0].reason == "empty_value"


def test_validate_all_good():
    merged = [
        {"name": "APP_PORT", "value": "3000", "secret": False},
        {"name": "BACKEND_HOST", "value": "0.0.0.0", "secret": False},
    ]
    errors = validate_merged_vars(merged)
    assert len(errors) == 0


def test_validate_mixed():
    merged: list[dict[str, object]] = [
        {"name": "APP_PORT", "value": "3000", "secret": False},
        {"name": "OPENAI_API_KEY", "value": None, "secret": True},
        {"name": "EMPTY_VAR", "value": "", "secret": False},
    ]
    errors = validate_merged_vars(merged)
    assert len(errors) == 2
    names = {e.name for e in errors}
    assert names == {"OPENAI_API_KEY", "EMPTY_VAR"}


# ---- build_env_file_content ----------------------------------------------------


def test_build_env_file_content():
    merged = [
        {"name": "APP_PORT", "value": "3000", "secret": False},
        {"name": "BACKEND_PORT", "value": "8483", "secret": False},
    ]
    content = build_env_file_content(merged)
    assert "APP_PORT=3000" in content
    assert "BACKEND_PORT=8483" in content
    assert content.startswith("# Generated by Agent Collab Console")
    assert MANAGED_ENV_FORMAT_MARKER in content
    assert content.endswith("\n")


def test_build_env_file_null_value():
    """Non-secret null values are written as KEY= (empty)."""
    merged: list[dict[str, object]] = [
        {"name": "OPTIONAL_VAR", "value": None, "secret": False},
    ]
    content = build_env_file_content(merged)
    assert "OPTIONAL_VAR=" in content


# ---- EnvValidationError ----------------------------------------------------


def test_validation_error_to_dict():
    err = EnvValidationError(name="API_KEY", reason="missing_secret", description="敏感凭据")
    d = err.to_dict()
    assert d == {"name": "API_KEY", "reason": "missing_secret", "description": "敏感凭据"}


# ---- materialize_env_file ----------------------------------------------------


async def test_materialize_decrypts_secret_only_for_env_file(tmp_path, monkeypatch):
    monkeypatch.setenv("CONSOLE_ENCRYPTION_KEY", generate_key())
    plaintext = "secret-value-only-for-env"
    ciphertext = encrypt(plaintext)
    stored = [
        ProjectEnvVar(
            project_id="p1",
            name="SERVICE_TOKEN",
            value=ciphertext,
            secret=True,
            source="user",
        ),
        ProjectEnvVar(
            project_id="p1",
            name="APP_PORT",
            value="3000",
            secret=False,
            source="user",
        ),
    ]

    result = await materialize_env_file(
        project_id="p1",
        repo_path=str(tmp_path),
        agent_env_vars=[],
        stored_vars=stored,
    )

    content = (tmp_path / ".env").read_text(encoding="utf-8")
    assert result.valid is True
    assert result.written is True
    assert f"SERVICE_TOKEN={plaintext}" in content
    assert f"{MANAGED_ENV_SECRET_MARKER_PREFIX}SERVICE_TOKEN" in content
    assert ciphertext not in content
    assert stored[0].value == ciphertext
    assert result.vars_written[0]["value"] == ciphertext


async def test_materialize_missing_key_leaves_existing_env_unchanged(tmp_path, monkeypatch):
    monkeypatch.setenv("CONSOLE_ENCRYPTION_KEY", generate_key())
    plaintext = "must-not-leak"
    ciphertext = encrypt(plaintext)
    monkeypatch.delenv("CONSOLE_ENCRYPTION_KEY")
    env_path = tmp_path / ".env"
    env_path.write_text("EXISTING=preserved\n", encoding="utf-8")

    result = await materialize_env_file(
        project_id="p1",
        repo_path=str(tmp_path),
        agent_env_vars=[],
        stored_vars=[
            ProjectEnvVar(
                project_id="p1",
                name="SERVICE_TOKEN",
                value=ciphertext,
                secret=True,
                source="user",
            )
        ],
    )

    assert result.valid is False
    assert result.errors[0].reason == "encryption_key_unavailable"
    assert env_path.read_text(encoding="utf-8") == "EXISTING=preserved\n"
    serialized_error = str(result.errors[0].to_dict())
    assert plaintext not in serialized_error
    assert ciphertext not in serialized_error


async def test_materialize_invalid_ciphertext_fails_before_any_write(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("CONSOLE_ENCRYPTION_KEY", generate_key())
    invalid_ciphertext = "invalid-ciphertext-must-not-leak"
    env_path = tmp_path / ".env"
    caplog.set_level(logging.DEBUG)

    result = await materialize_env_file(
        project_id="p1",
        repo_path=str(tmp_path),
        agent_env_vars=[],
        stored_vars=[
            ProjectEnvVar(
                project_id="p1",
                name="SERVICE_TOKEN",
                value=invalid_ciphertext,
                secret=True,
                source="user",
            )
        ],
    )

    assert result.valid is False
    assert result.errors[0].reason == "secret_decryption_failed"
    assert env_path.exists() is False
    assert invalid_ciphertext not in str(result.errors[0].to_dict())
    assert invalid_ciphertext not in caplog.text


async def test_materialize_one_bad_secret_prevents_all_writes(tmp_path, monkeypatch):
    monkeypatch.setenv("CONSOLE_ENCRYPTION_KEY", generate_key())
    first_plaintext = "first-secret-must-not-be-written"
    env_path = tmp_path / ".env"
    env_path.write_text("EXISTING=preserved\n", encoding="utf-8")

    result = await materialize_env_file(
        project_id="p1",
        repo_path=str(tmp_path),
        agent_env_vars=[],
        stored_vars=[
            ProjectEnvVar(
                project_id="p1",
                name="FIRST_TOKEN",
                value=encrypt(first_plaintext),
                secret=True,
                source="user",
            ),
            ProjectEnvVar(
                project_id="p1",
                name="SECOND_TOKEN",
                value="invalid-ciphertext",
                secret=True,
                source="user",
            ),
        ],
    )

    assert result.valid is False
    assert env_path.read_text(encoding="utf-8") == "EXISTING=preserved\n"
    assert first_plaintext not in env_path.read_text(encoding="utf-8")


async def test_invalid_secret_removes_previous_console_managed_env(tmp_path, monkeypatch):
    monkeypatch.setenv("CONSOLE_ENCRYPTION_KEY", generate_key())
    stale_plaintext = "stale-plaintext-must-be-removed"
    env_path = tmp_path / ".env"
    env_path.write_text(
        build_env_file_content(
            [
                {
                    "name": "SERVICE_TOKEN",
                    "value": stale_plaintext,
                    "secret": True,
                }
            ]
        ),
        encoding="utf-8",
    )

    result = await materialize_env_file(
        project_id="p1",
        repo_path=str(tmp_path),
        agent_env_vars=[],
        stored_vars=[
            ProjectEnvVar(
                project_id="p1",
                name="SERVICE_TOKEN",
                value="invalid-ciphertext",
                secret=True,
                source="user",
            )
        ],
    )

    assert result.valid is False
    assert result.removed is True
    assert result.errors[0].reason == "secret_decryption_failed"
    assert env_path.exists() is False


async def test_empty_reconciliation_removes_only_console_managed_env(tmp_path):
    plaintext = "obsolete-secret-plaintext"
    env_path = tmp_path / ".env"
    env_path.write_text(
        "# locally added note\n"
        + build_env_file_content(
            [
                {
                    "name": "SERVICE_TOKEN",
                    "value": plaintext,
                    "secret": True,
                }
            ]
        ),
        encoding="utf-8",
    )

    result = await materialize_env_file(
        project_id="p1",
        repo_path=str(tmp_path),
        agent_env_vars=[],
        stored_vars=[],
    )

    assert result.valid is True
    assert result.removed is True
    assert result.skipped is False
    assert env_path.exists() is False
    assert plaintext not in "\n".join(path.read_text() for path in tmp_path.iterdir())


async def test_empty_reconciliation_preserves_manual_env(tmp_path):
    env_path = tmp_path / ".env"
    manual_content = "SERVICE_TOKEN=manual-owner-value\n"
    env_path.write_text(manual_content, encoding="utf-8")

    result = await materialize_env_file(
        project_id="p1",
        repo_path=str(tmp_path),
        agent_env_vars=[],
        stored_vars=[],
    )

    assert result.valid is True
    assert result.removed is False
    assert result.skipped is True
    assert env_path.read_text(encoding="utf-8") == manual_content


def test_agent_secret_warning_does_not_log_supplied_value(caplog):
    supplied_value = "agent-secret-must-not-leak"
    caplog.set_level(logging.WARNING)

    merge_env_vars(
        agent_env_vars=[
            {
                "name": "SERVICE_TOKEN",
                "value": supplied_value,
                "secret": True,
                "source": "agent",
            }
        ],
        stored_vars=[],
    )

    assert supplied_value not in caplog.text
