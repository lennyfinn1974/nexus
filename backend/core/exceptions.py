"""Custom exception hierarchy for Nexus."""


class NexusError(Exception):
    """Base exception for all Nexus errors."""


class ToolExecutionError(NexusError):
    """A tool call failed to execute."""


class PluginNotFoundError(NexusError):
    """Requested plugin does not exist or is not loaded."""


class SkillNotConfiguredError(NexusError):
    """A skill is missing required configuration."""


class ModelUnavailableError(NexusError):
    """No AI model is currently available to handle the request."""


class PathAccessDeniedError(NexusError):
    """File path is outside allowed directories."""


class RateLimitExceededError(NexusError):
    """Client has exceeded the rate limit."""
