"""Plugin permission levels and access control."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum


class PermissionLevel(IntEnum):
    READONLY = 10       # Can read data only
    STANDARD = 20       # Can read/write within sandbox
    ELEVATED = 30       # Can execute code, access network
    SYSTEM = 40         # Full system access (admin only)


@dataclass
class PluginPermissions:
    """Access control settings for a plugin."""
    level: PermissionLevel = PermissionLevel.STANDARD
    allowed_dirs: list[str] = field(default_factory=list)
    can_execute_code: bool = False
    can_access_network: bool = False
    max_execution_time: int = 30
    rate_limit: int | None = None

    @classmethod
    def for_level(cls, level: PermissionLevel) -> PluginPermissions:
        """Create permissions from a level with sensible defaults."""
        if level == PermissionLevel.READONLY:
            return cls(level=level, can_execute_code=False, can_access_network=False)
        elif level == PermissionLevel.STANDARD:
            return cls(level=level, can_execute_code=False, can_access_network=False)
        elif level == PermissionLevel.ELEVATED:
            return cls(level=level, can_execute_code=True, can_access_network=True)
        elif level == PermissionLevel.SYSTEM:
            return cls(
                level=level, can_execute_code=True, can_access_network=True,
                max_execution_time=120,
            )
        return cls(level=level)
