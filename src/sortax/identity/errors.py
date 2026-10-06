from sortax.api.errors import NotFoundError


class InvalidAccessTokenError(Exception):
    """Raised when an access token cannot be trusted."""


class ResourceNotFoundError(NotFoundError):
    """Raised for missing or unauthorized resources to prevent enumeration."""
