import logging
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from sortax.api.errors import AppError
from sortax.api.models import ErrorEnvelope, ErrorPayload

logger = logging.getLogger(__name__)


def request_id_for(request: Request) -> str:
    return str(getattr(request.state, "request_id", uuid4()))


def error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    retryable: bool = False,
    retry_after_seconds: int | None = None,
    details: dict[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    request_id = request_id_for(request)
    response_headers = {"X-Request-ID": request_id, **dict(headers or {})}
    if retry_after_seconds is not None:
        response_headers["Retry-After"] = str(retry_after_seconds)
    envelope = ErrorEnvelope(
        error=ErrorPayload(
            code=code,
            message=message,
            request_id=request_id,
            retryable=retryable,
            retry_after_seconds=retry_after_seconds,
            details=details or {},
        )
    )
    return JSONResponse(
        status_code=status_code,
        content=envelope.model_dump(mode="json", exclude_none=True),
        headers=response_headers,
    )


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return error_response(
        request,
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        retryable=exc.retryable,
        retry_after_seconds=exc.retry_after_seconds,
        details=exc.details,
        headers=exc.headers,
    )


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    fields = [
        {"field": ".".join(str(part) for part in error["loc"]), "type": error["type"]}
        for error in exc.errors()
    ]
    return error_response(
        request,
        status_code=422,
        code="validation_error",
        message="Request validation failed",
        details={"fields": fields},
    )


async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
    code_by_status = {401: "unauthorized", 404: "not_found"}
    code = code_by_status.get(exc.status_code, "invalid_request")
    message = exc.detail if isinstance(exc.detail, str) else "Request failed"
    return error_response(
        request,
        status_code=exc.status_code,
        code=code,
        message=message,
        headers=exc.headers,
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "unhandled_exception",
        extra={"exception_type": type(exc).__name__},
    )
    return error_response(
        request,
        status_code=500,
        code="internal_error",
        message="An unexpected error occurred",
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(HTTPException, http_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_error_handler)
