class IBSngError(Exception):
    """Base exception for all IBSng API errors."""


class IBSngUserExistsError(IBSngError):
    """Raised when attempting to create a user that already exists."""


class IBSngUserNotFoundError(IBSngError):
    """Raised when an operation targets a username that doesn't exist in IBSng."""
