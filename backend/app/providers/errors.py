"""Errors shared by provider implementations."""


class ProviderError(Exception):
    """A provider call failed.

    `retryable` tells the caller whether the same call may succeed later
    (timeouts, rate limits, 5xx) or will keep failing (bad request, bad credentials).
    """

    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


class ProviderNotImplementedError(NotImplementedError):
    """Raised by provider stubs until the owning task implements them."""

    def __init__(self, provider: str) -> None:
        super().__init__(f"{provider} is not implemented yet.")
