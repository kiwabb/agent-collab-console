"""Focused security tests for project environment-variable encryption."""

from __future__ import annotations

import pytest

from app.application.env_crypto import (
    EnvCryptoDecryptError,
    EnvCryptoKeyError,
    decrypt,
    generate_key,
)


def test_malformed_key_error_does_not_contain_key(monkeypatch):
    malformed_key = "malformed-key-must-not-leak"
    monkeypatch.setenv("CONSOLE_ENCRYPTION_KEY", malformed_key)

    with pytest.raises(EnvCryptoKeyError) as exc_info:
        decrypt("ciphertext")

    assert malformed_key not in str(exc_info.value)
    assert exc_info.value.__cause__ is None


def test_invalid_ciphertext_error_does_not_contain_ciphertext(monkeypatch):
    invalid_ciphertext = "ciphertext-must-not-leak"
    monkeypatch.setenv("CONSOLE_ENCRYPTION_KEY", generate_key())

    with pytest.raises(EnvCryptoDecryptError) as exc_info:
        decrypt(invalid_ciphertext)

    assert invalid_ciphertext not in str(exc_info.value)
    assert exc_info.value.__cause__ is None


def test_non_ascii_ciphertext_uses_sanitized_error(monkeypatch):
    invalid_ciphertext = "密文不得出现在异常中"
    monkeypatch.setenv("CONSOLE_ENCRYPTION_KEY", generate_key())

    with pytest.raises(EnvCryptoDecryptError) as exc_info:
        decrypt(invalid_ciphertext)

    assert invalid_ciphertext not in str(exc_info.value)
    assert exc_info.value.__cause__ is None
