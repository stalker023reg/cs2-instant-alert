"""
CS2 Instant Alert — Credential Encryption.

Uses Fernet symmetric encryption to protect stored credentials
(Pushover tokens, Discord webhooks, etc.) at rest in the database.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.exceptions import EncryptionError


class CredentialEncryptor:
    """
    Encrypts and decrypts sensitive credential strings using Fernet.

    If no encryption key is provided, operates in passthrough mode
    (returns values as-is). This is only acceptable in development.
    """

    def __init__(self, encryption_key: str | None = None) -> None:
        self._fernet: Fernet | None = None

        if encryption_key:
            # Ensure the key is valid Fernet format (44 url-safe base64 chars)
            try:
                self._fernet = Fernet(encryption_key.encode())
            except (ValueError, Exception):
                # If it's not a valid Fernet key, derive one from it
                derived = base64.urlsafe_b64encode(
                    hashlib.sha256(encryption_key.encode()).digest()
                )
                self._fernet = Fernet(derived)

    @property
    def is_enabled(self) -> bool:
        """Whether encryption is active (key was provided)."""
        return self._fernet is not None

    def encrypt(self, plaintext: str) -> str:
        """
        Encrypt a plaintext string.

        Args:
            plaintext: The string to encrypt.

        Returns:
            Base64-encoded ciphertext string.

        Raises:
            EncryptionError: If encryption fails.
        """
        if not self._fernet:
            return plaintext

        try:
            return self._fernet.encrypt(plaintext.encode()).decode()
        except Exception as exc:
            raise EncryptionError(f"Failed to encrypt value: {exc}") from exc

    def decrypt(self, ciphertext: str) -> str:
        """
        Decrypt a ciphertext string.

        Args:
            ciphertext: The base64-encoded ciphertext.

        Returns:
            Decrypted plaintext string.

        Raises:
            EncryptionError: If decryption fails (wrong key, corrupted data).
        """
        if not self._fernet:
            return ciphertext

        try:
            return self._fernet.decrypt(ciphertext.encode()).decode()
        except InvalidToken as exc:
            raise EncryptionError(
                "Failed to decrypt value — invalid key or corrupted data"
            ) from exc
        except Exception as exc:
            raise EncryptionError(f"Failed to decrypt value: {exc}") from exc
