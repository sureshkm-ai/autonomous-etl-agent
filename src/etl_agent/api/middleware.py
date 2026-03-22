"""Security middleware: API key auth, body size enforcement."""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from etl_agent.core.config import get_settings
from etl_agent.core.logging import get_logger

logger = get_logger(__name__)

EXCLUDED_PATHS = {"/api/v1/health", "/docs", "/redoc", "/openapi.json"}

# Path prefixes served without API key authentication.
# The UI itself is public; it sends the API key on individual API calls.
EXCLUDED_PREFIXES = ("/ui", "/static", "/docs", "/redoc")

# Root path is also public (redirects to /ui)
EXCLUDED_EXACT = {"/", "/favicon.ico"}


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Validates X-API-Key header on all non-excluded routes."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        path = request.url.path

        if (
            path in EXCLUDED_PATHS
            or path in EXCLUDED_EXACT
            or any(path.startswith(p) for p in EXCLUDED_PREFIXES)
        ):
            return await call_next(request)

        settings = get_settings()
        api_key = request.headers.get("X-API-Key")

        if not api_key or api_key != settings.api_key:
            logger.warning(
                "unauthorized_request",
                path=request.url.path,
                ip=request.client.host if request.client else "unknown",
            )
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API key"},
            )

        return await call_next(request)


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject request bodies that exceed max_request_body_bytes."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        settings = get_settings()
        limit = settings.max_request_body_bytes  # default 32 KiB

        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > limit:
                    logger.warning(
                        "request_body_too_large",
                        content_length=content_length,
                        limit=limit,
                        path=request.url.path,
                    )
                    return JSONResponse(
                        status_code=413,
                        content={"detail": f"Request body exceeds {limit:,} byte limit"},
                    )
            except ValueError:
                pass

        return await call_next(request)
