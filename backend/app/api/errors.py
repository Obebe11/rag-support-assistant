"""One error format for the whole API: `{"error": {"code", "message", "details"}}`."""

import logging
from collections.abc import Mapping, Sequence
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.schemas.common import ErrorBody, ErrorCode, ErrorDetail, ErrorResponse

logger = logging.getLogger(__name__)

_STATUS_TO_CODE: dict[int, ErrorCode] = {
    401: ErrorCode.UNAUTHORIZED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    405: ErrorCode.METHOD_NOT_ALLOWED,
    409: ErrorCode.CONFLICT,
    413: ErrorCode.PAYLOAD_TOO_LARGE,
    415: ErrorCode.UNSUPPORTED_MEDIA_TYPE,
    422: ErrorCode.VALIDATION_ERROR,
    501: ErrorCode.NOT_IMPLEMENTED,
    503: ErrorCode.SERVICE_UNAVAILABLE,
}


class ApiError(Exception):
    """Raise from routes and services to return an error in the common format."""

    def __init__(
        self,
        status_code: int,
        code: ErrorCode,
        message: str,
        *,
        details: Sequence[ErrorDetail] = (),
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = list(details)
        self.headers = dict(headers) if headers else None


class NotImplementedApiError(ApiError):
    """Raised by endpoints that are declared in the contract but not built yet."""

    def __init__(self, feature: str) -> None:
        super().__init__(
            HTTPStatus.NOT_IMPLEMENTED,
            ErrorCode.NOT_IMPLEMENTED,
            f"{feature} is not implemented yet.",
        )


class NotFoundError(ApiError):
    def __init__(self, message: str) -> None:
        super().__init__(HTTPStatus.NOT_FOUND, ErrorCode.NOT_FOUND, message)


class ConflictError(ApiError):
    def __init__(self, message: str, *, details: Sequence[ErrorDetail] = ()) -> None:
        super().__init__(HTTPStatus.CONFLICT, ErrorCode.CONFLICT, message, details=details)


class ValidationApiError(ApiError):
    def __init__(self, message: str, *, details: Sequence[ErrorDetail] = ()) -> None:
        super().__init__(
            HTTPStatus.UNPROCESSABLE_ENTITY, ErrorCode.VALIDATION_ERROR, message, details=details
        )


def error_responses(*status_codes: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI `responses` entries that document errors in the common format."""
    return {
        status_code: {"model": ErrorResponse, "description": HTTPStatus(status_code).phrase}
        for status_code in status_codes
    }


def _error_response(
    status_code: int,
    code: ErrorCode,
    message: str,
    details: Sequence[ErrorDetail] = (),
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    body = ErrorResponse(error=ErrorBody(code=code, message=message, details=list(details)))
    return JSONResponse(body.model_dump(mode="json"), status_code=status_code, headers=headers)


async def _handle_api_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiError)
    return _error_response(exc.status_code, exc.code, exc.message, exc.details, exc.headers)


async def _handle_http_exception(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    default_code = (
        ErrorCode.INTERNAL_ERROR if exc.status_code >= 500 else ErrorCode.VALIDATION_ERROR
    )
    code = _STATUS_TO_CODE.get(exc.status_code, default_code)
    message = exc.detail if isinstance(exc.detail, str) else HTTPStatus(exc.status_code).phrase
    return _error_response(exc.status_code, code, message, headers=exc.headers)


async def _handle_validation_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    details = [
        ErrorDetail(
            field=".".join(str(part) for part in error.get("loc", ())) or None,
            message=str(error.get("msg", "Invalid value.")),
        )
        for error in exc.errors()
    ]
    return _error_response(
        HTTPStatus.UNPROCESSABLE_ENTITY,
        ErrorCode.VALIDATION_ERROR,
        "The request is not valid.",
        details,
    )


async def _handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path, exc_info=exc)
    return _error_response(
        HTTPStatus.INTERNAL_SERVER_ERROR,
        ErrorCode.INTERNAL_ERROR,
        "Internal server error.",
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _handle_api_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(Exception, _handle_unexpected_error)
