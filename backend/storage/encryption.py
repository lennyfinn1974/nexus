"""Encryption for sensitive settings (API keys, tokens).

Uses Fernet symmetric encryption. Key is auto-generated on first
boot and stored in .nexus_secret alongside the project root.
"""

import os
import logging
from cryptography.fernet import Fernet

logger = logging.getLogger("nexus.encryption")

_fernet = None


def _secret_path(base_dir: str) -> str:
    return os.path.join(base_dir, ".nexus_secret")


def init(base_dir: str):
    """Initialise (or load) the encryption key."""
    global _fernet
    path = _secret_path(base_dir)

    if os.path.exists(path):
        with open(path, "rb") as f:
            key = f.read().strip()
    else:
        key = Fernet.generate_key()
        with open(path, "wb") as f:
            f.write(key)
        os.chmod(path, 0o600)
        logger.info("Generated new encryption key")

    _fernet = Fernet(key)


def encrypt(value: str) -> str:
    """Encrypt a string → base64 token."""
    if not _fernet:
        raise RuntimeError("Encryption not initialised — call init() first")
    return _fernet.encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    """Decrypt a base64 token → string."""
    if not _fernet:
        raise RuntimeError("Encryption not initialised — call init() first")
    return _fernet.decrypt(token.encode()).decode()
