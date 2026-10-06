from typing import Any


class AppError(Exception):
    """Safe, stable application error that may be returned to an API client."""

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        retryable: bool = False,
        retry_after_seconds: int | None = None,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds
        self.details = details or {}
        self.headers = headers or {}


class AuthenticationError(AppError):
    def __init__(self, message: str = "Invalid or missing access token") -> None:
        super().__init__(
            status_code=401,
            code="unauthorized",
            message=message,
            headers={"WWW-Authenticate": "Bearer"},
        )


class NotFoundError(AppError):
    def __init__(self, message: str = "Resource not found") -> None:
        super().__init__(status_code=404, code="not_found", message=message)


class ConflictError(AppError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(status_code=409, code=code, message=message)


class ServiceUnavailableError(AppError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(
            status_code=503,
            code=code,
            message=message,
            retryable=True,
        )
