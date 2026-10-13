from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import __version__
from app.api.router import router
from app.core.config import AppSettings, normalize_base_url
from app.core.errors import ConnectMapError
from app.core.logging import configure_logging
from app.core.security import sanitize_text
from app.services.runtime import AppRuntime

logger = logging.getLogger(__name__)


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; connect-src 'self'; object-src 'none'; "
        "base-uri 'self'; frame-ancestors 'none'"
    ),
}


def _secure_response(response):
    for header, value in SECURITY_HEADERS.items():
        response.headers[header] = value
    return response


def _error_response(
    status_code: int,
    code: str,
    message: str,
    details: Any = None,
) -> JSONResponse:
    error: dict[str, Any] = {"code": code, "message": sanitize_text(message)}
    if details is not None:
        error["details"] = details
    return _secure_response(JSONResponse(status_code=status_code, content={"error": error}))


def _find_static_dir(settings: AppSettings) -> Path | None:
    candidates = [
        settings.static_dir,
        Path(__file__).resolve().parents[2] / "frontend" / "dist",
        Path.cwd() / "frontend" / "dist",
        Path("/app/frontend/dist"),
        Path("/app/static"),
    ]
    for candidate in candidates:
        if candidate and candidate.is_dir() and (candidate / "index.html").is_file():
            return candidate
    return None


def create_app(settings: AppSettings | None = None) -> FastAPI:
    resolved_settings = settings or AppSettings.from_env()
    configure_logging(resolved_settings.log_level)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        runtime = AppRuntime(resolved_settings)
        application.state.runtime = runtime
        await runtime.start()
        try:
            yield
        finally:
            await runtime.stop()

    docs_url = None if resolved_settings.disable_docs else "/api/docs"
    openapi_url = None if resolved_settings.disable_docs else "/api/openapi.json"
    application = FastAPI(
        title="SDEX ConnectMap",
        version=__version__,
        docs_url=docs_url,
        redoc_url=None,
        openapi_url=openapi_url,
        lifespan=lifespan,
    )

    @application.middleware("http")
    async def security_and_body_middleware(request: Request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            if request.url.path.startswith("/api/"):
                origin = request.headers.get("origin")
                cross_origin = request.headers.get("sec-fetch-site") == "cross-site"
                if origin is not None:
                    try:
                        expected_origin = normalize_base_url(
                            f"{request.url.scheme}://{request.headers.get('host', '')}"
                        )
                        cross_origin = cross_origin or (
                            normalize_base_url(origin) != expected_origin
                        )
                    except ValueError:
                        cross_origin = True
                if cross_origin:
                    return _error_response(
                        403,
                        "cross_origin_request",
                        "Cross-origin changes are not allowed.",
                    )
            content_length = request.headers.get("content-length")
            if content_length:
                try:
                    too_large = int(content_length) > resolved_settings.max_body_bytes
                except ValueError:
                    return _error_response(400, "invalid_content_length", "Invalid body length.")
                if too_large:
                    return _error_response(
                        413,
                        "body_too_large",
                        "Request body exceeds the configured size limit.",
                    )
            received = 0
            chunks: list[bytes] = []
            more_body = True
            while more_body:
                message = await request.receive()
                if message["type"] == "http.disconnect":
                    break
                chunk = message.get("body", b"")
                received += len(chunk)
                if received > resolved_settings.max_body_bytes:
                    return _error_response(
                        413,
                        "body_too_large",
                        "Request body exceeds the configured size limit.",
                    )
                chunks.append(chunk)
                more_body = bool(message.get("more_body", False))
            # Starlette's cached request replays this bounded body to Pydantic.
            request._body = b"".join(chunks)  # type: ignore[attr-defined]
        response = await call_next(request)
        return _secure_response(response)

    @application.exception_handler(ConnectMapError)
    async def connectmap_error_handler(
        _request: Request,
        exc: ConnectMapError,
    ) -> JSONResponse:
        return _error_response(
            exc.status_code,
            exc.code,
            str(exc),
            exc.details,
        )

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        details = [
            {
                "location": list(error.get("loc", ())),
                "message": sanitize_text(error.get("msg", "Invalid value.")),
                "type": error.get("type", "validation_error"),
            }
            for error in exc.errors()
        ]
        return _error_response(
            422,
            "validation_error",
            "Request validation failed.",
            details,
        )

    @application.exception_handler(StarletteHTTPException)
    async def http_error_handler(
        request: Request,
        exc: StarletteHTTPException,
    ):
        if request.url.path.startswith("/api/"):
            return _error_response(
                exc.status_code,
                "http_error",
                str(exc.detail),
            )
        return _error_response(exc.status_code, "not_found", "Resource not found.")

    @application.exception_handler(Exception)
    async def unexpected_error_handler(
        _request: Request,
        exc: Exception,
    ) -> JSONResponse:
        logger.error(
            "Unhandled API error: %s",
            sanitize_text(exc),
            extra={"event": "api_error"},
        )
        return _error_response(
            500,
            "internal_error",
            "An unexpected internal error occurred.",
        )

    application.include_router(router)

    static_dir = _find_static_dir(resolved_settings)
    if static_dir:
        assets_dir = static_dir / "assets"
        if assets_dir.is_dir():
            application.mount(
                "/assets",
                StaticFiles(directory=assets_dir),
                name="assets",
            )
        icons_dir = static_dir / "icons"
        if icons_dir.is_dir():
            application.mount(
                "/icons",
                StaticFiles(directory=icons_dir),
                name="icons",
            )

        @application.get("/", include_in_schema=False)
        async def index() -> FileResponse:
            return FileResponse(static_dir / "index.html")

        @application.get("/{path:path}", include_in_schema=False)
        async def spa_fallback(path: str):
            candidate = (static_dir / path).resolve()
            try:
                candidate.relative_to(static_dir.resolve())
            except ValueError:
                return _error_response(404, "not_found", "Resource not found.")
            if candidate.is_file():
                return FileResponse(candidate)
            if path == "api" or path.startswith("api/"):
                return _error_response(404, "not_found", "API route not found.")
            return FileResponse(static_dir / "index.html")
    else:

        @application.get("/", include_in_schema=False)
        async def backend_only_index() -> JSONResponse:
            return JSONResponse(
                {
                    "name": "SDEX ConnectMap",
                    "version": __version__,
                    "api": "/api/health",
                }
            )

    return application


app = create_app()
