"""User-facing error types."""


class PrecError(Exception):
    """Base class for expected errors."""


class ConfigError(PrecError):
    """The project configuration is missing or invalid."""


class RepositoryError(PrecError):
    """Git repository inspection failed."""


class HookError(PrecError):
    """A Git hook could not be installed or uninstalled safely."""


class UsageError(PrecError):
    """A CLI selection is invalid."""
