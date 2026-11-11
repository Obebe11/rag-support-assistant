"""Guard for knowledge base uploads, applied before the request body is read.

FastAPI parses a multipart body before it runs route dependencies, so without
this guard an anonymous client could make the API read a large upload and only
then get `401`. For `POST` requests under the upload prefix this middleware

1. checks the administrator token first, with the same rules and the same
   error bodies as `app.api.deps.require_admin`, and
2. rejects a body over the upload limit with `413`: at once when
   `Content-Length` says so, otherwise as soon as the limit is passed while
   the body streams in.

The route still checks the exact size of the file itself.
"""

import contextlib
from http import HTTPStatus

from fastapi.security import HTTPAuthorizationCredentials
from fastapi.security.utils import get_authorization_scheme_param
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.deps import require_admin
from app.api.errors import ApiError
from app.core.config import Settings
from app.schemas.common import ErrorBody, ErrorCode, ErrorResponse

UPLOAD_PATH_PREFIX = "/api/admin/documents"
MULTIPART_OVERHEAD_BYTES = 64 * 1024
"""Room for multipart boundaries and the form fields sent next to the file."""


class _BodyTooLargeError(Exception):
    pass


def _error_response(error: ApiError) -> JSONResponse:
    body = ErrorResponse(error=ErrorBody(code=error.code, message=error.message, details=[]))
    return JSONResponse(
        body.model_dump(mode="json"), status_code=error.status_code, headers=error.headers
    )


class UploadGuardMiddleware:
    def __init__(self, app: ASGIApp, *, settings: Settings) -> None:
        self._app = app
        self._settings = settings

    @property
    def _max_body_bytes(self) -> int:
        return self._settings.max_upload_bytes + MULTIPART_OVERHEAD_BYTES

    def _too_large(self) -> ApiError:
        return ApiError(
            HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            ErrorCode.PAYLOAD_TOO_LARGE,
            f"The upload is larger than the limit of {self._settings.max_upload_bytes} bytes.",
        )

    def _authorization_error(self, headers: Headers) -> ApiError | None:
        scheme, token = get_authorization_scheme_param(headers.get("authorization"))
        credentials = (
            HTTPAuthorizationCredentials(scheme=scheme, credentials=token)
            if scheme.lower() == "bearer" and token
            else None
        )
        try:
            require_admin(credentials, self._settings)
        except ApiError as error:
            return error
        return None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] != "POST"
            or not scope["path"].startswith(UPLOAD_PATH_PREFIX)
        ):
            await self._app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        error = self._authorization_error(headers)
        if error is None:
            declared = headers.get("content-length", "")
            # A value that is not a plain number is left to the streaming limit below.
            if declared.isascii() and declared.isdigit() and int(declared) > self._max_body_bytes:
                error = self._too_large()
        if error is not None:
            await _error_response(error)(scope, receive, send)
            return

        received = 0
        exceeded = False

        async def limited_receive() -> Message:
            nonlocal received, exceeded
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self._max_body_bytes:
                    exceeded = True
                    raise _BodyTooLargeError
            return message

        async def guarded_send(message: Message) -> None:
            # Once the limit is passed, this middleware answers instead of the app.
            if not exceeded:
                await send(message)

        with contextlib.suppress(_BodyTooLargeError):
            await self._app(scope, limited_receive, guarded_send)
        if exceeded:
            await _error_response(self._too_large())(scope, receive, send)
