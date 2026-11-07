"""Custom exchange adapter exceptions for normalized, fail-closed error handling."""


class ExchangeAdapterError(Exception):
    """Base exception for all exchange adapter operational errors."""


class ExchangeNetworkError(ExchangeAdapterError):
    """Raised when network connectivity fails or endpoint is unreachable."""


class ExchangeTimeoutError(ExchangeNetworkError):
    """Raised when an exchange API call times out."""


class ExchangeRateLimitError(ExchangeAdapterError):
    """Raised when exchange request rate limit is exceeded."""


class ExchangeDataError(ExchangeAdapterError):
    """Raised when exchange returns malformed, empty, or inconsistent data."""


class ExchangePermissionError(ExchangeAdapterError):
    """Raised when an operation is prohibited by safety policy or adapter read-only mode."""
