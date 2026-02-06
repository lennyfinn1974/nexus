"""Path validation and sandboxing utilities."""

from __future__ import annotations

import os
from collections.abc import Sequence

from core.exceptions import PathAccessDeniedError

# Populated at startup from app factory
ALLOWED_DIRS: list[str] = []


def init_allowed_dirs(base_dir: str) -> list[str]:
    """Initialize and return the default allowed directories."""
    global ALLOWED_DIRS
    ALLOWED_DIRS = [
        os.path.join(base_dir, "data"),
        os.path.join(base_dir, "docs"),
        os.path.join(base_dir, "skills"),
    ]
    return ALLOWED_DIRS


def validate_path(file_path: str, allowed_dirs: Sequence[str] | None = None) -> str:
    """Resolve *file_path* and ensure it lives inside an allowed directory.

    Returns the resolved absolute path on success.
    Raises PathAccessDeniedError on disallowed locations.
    """
    dirs = allowed_dirs or ALLOWED_DIRS
    resolved = os.path.realpath(file_path)
    for allowed in dirs:
        allowed_resolved = os.path.realpath(allowed)
        if resolved == allowed_resolved or resolved.startswith(allowed_resolved + os.sep):
            return resolved
    raise PathAccessDeniedError(f"Path outside allowed directories: {file_path}")
