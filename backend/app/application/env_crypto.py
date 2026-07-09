"""Symmetric encryption for project environment-variable values.

Project env vars (see ``project_env_vars`` table) can hold secrets — API keys,
DB passwords, tokens. We never want those sitting in plaintext in the console
DB, so secret values are encrypted at rest with a symmetric key.

Key management (deliberately simple for a local single-machine tool):

- The key comes from the ``CONSOLE_ENCRYPTION_KEY`` environment variable. It is
  a urlsafe-base64 32-byte Fernet key (generate one with
  ``Fernet.generate_key().decode()`` or ``python -m app.application.env_crypto``).
- If the variable is missing or malformed, encryption/decryption raise
  ``EnvCryptoKeyError`` loudly rather than silently degrading. Callers surface
  this to the user as "configure CONSOLE_ENCRYPTION_KEY" instead of writing a
  broken secret or crashing deep in the DB layer.
- There is intentionally NO key rotation / multi-key support in the MVP. If the
  key is lost or changed, previously-encrypted values can no longer be decrypted
  and must be re-entered — this trade-off is documented for the user.

Non-secret values (ports, hosts) are stored in plaintext columns; only the
secret column goes through this module.
"""
from __future__ import annotations

import logging
import os

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

ENV_KEY_NAME = "CONSOLE_ENCRYPTION_KEY"


class EnvCryptoError(RuntimeError):
    """Base class for env-crypto failures."""


class EnvCryptoKeyError(EnvCryptoError):
    """The encryption key is missing or malformed.

    Surfaced to the user as an actionable "configure CONSOLE_ENCRYPTION_KEY"
    error, never swallowed.
    """


class EnvCryptoDecryptError(EnvCryptoError):
    """A stored ciphertext could not be decrypted with the current key.

    Usually means the key changed since the value was written (see module
    docstring: no rotation, values must be re-entered).
    """


def generate_key() -> str:
    """Return a fresh urlsafe-base64 Fernet key suitable for CONSOLE_ENCRYPTION_KEY."""
    return Fernet.generate_key().decode("ascii")


def _load_fernet() -> Fernet:
    raw = os.getenv(ENV_KEY_NAME)
    if not raw or not raw.strip():
        raise EnvCryptoKeyError(
            f"{ENV_KEY_NAME} is not set. Generate one with "
            f"`python -m app.application.env_crypto` and export it before "
            f"storing project secrets."
        )
    try:
        return Fernet(raw.strip().encode("ascii"))
    except (ValueError, TypeError) as exc:
        raise EnvCryptoKeyError(
            f"{ENV_KEY_NAME} is malformed (expected a urlsafe-base64 32-byte "
            f"Fernet key): {exc}"
        ) from exc


def is_configured() -> bool:
    """Return True if a usable encryption key is currently configured.

    Never raises — safe for a UI/health probe to call. Use this to decide
    whether to show a "configure CONSOLE_ENCRYPTION_KEY" banner before the user
    tries to save a secret.
    """
    try:
        _load_fernet()
        return True
    except EnvCryptoKeyError:
        return False


def encrypt(plaintext: str) -> str:
    """Encrypt a secret value. Returns urlsafe-base64 ciphertext (str).

    Raises EnvCryptoKeyError if the key is missing/malformed.
    """
    fernet = _load_fernet()
    return fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(ciphertext: str) -> str:
    """Decrypt a stored secret value.

    Raises EnvCryptoKeyError if the key is missing/malformed, or
    EnvCryptoDecryptError if the ciphertext cannot be decrypted with the
    current key (e.g. the key was rotated).
    """
    fernet = _load_fernet()
    try:
        return fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise EnvCryptoDecryptError(
            "Failed to decrypt a stored value with the current "
            f"{ENV_KEY_NAME}. The key may have changed since it was saved; "
            "the value must be re-entered."
        ) from exc


if __name__ == "__main__":  # pragma: no cover - developer convenience
    print(generate_key())  # noqa: T201
