"""The error raised by everything in io/ when FluentControl, the Fluent PC or a device refuses or fails."""


class BackendError(Exception):
    """Failure in the backend (FluentControl). The message is human-readable."""
