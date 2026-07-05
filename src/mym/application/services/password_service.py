"""Ledger password protection using hashed passwords."""

import hashlib
import os
import secrets


class PasswordService:
    """Handles ledger password setting and verification.

    Uses PBKDF2-like hashing via hashlib with salt.
    NOTE: The password hash is stored in the ledger database's app_settings table.
    """

    SALT_LENGTH = 32
    HASH_ITERATIONS = 100000

    @staticmethod
    def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
        """Hash a password with a salt. Returns (hash_hex, salt_hex)."""
        if salt is None:
            salt = secrets.token_bytes(PasswordService.SALT_LENGTH)

        key = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            PasswordService.HASH_ITERATIONS,
        )
        return key.hex(), salt.hex()

    @staticmethod
    def verify(password: str, stored_hash: str, stored_salt: str) -> bool:
        """Verify a password against stored hash and salt."""
        try:
            salt = bytes.fromhex(stored_salt)
            computed, _ = PasswordService.hash_password(password, salt)
            return secrets.compare_digest(computed, stored_hash)
        except (ValueError, TypeError):
            return False

    @staticmethod
    def has_password(stored_hash: str | None) -> bool:
        """Check if a password is set."""
        return bool(stored_hash)
