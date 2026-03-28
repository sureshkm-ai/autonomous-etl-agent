"""FastAPI application factory with lifespan management."""
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

<<<<<<< HEAD
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
=======
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
>>>>>>> main
from fastapi.staticfiles import StaticFiles

from etl_agent.core.config import get_settings
from etl_agent.core.logging import configure_logging, get_logger
from etl_agent.database.session import create_all_tables, dispose_engine

logger = get_logger(__name__)


<<<<<<< HEAD
# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

=======
>>>>>>> main
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application startup and shutdown lifecycle."""
    settings = get_settings()
<<<<<<< HEAD
    configure_logging(
        log_level="DEBUG" if settings.debug else "INFO",
        json_logs=not settings.debug,
    )
=======
    configure_logging(log_level="DEBUG" if settings.debug else "INFO", json_logs=not settings.debug)
>>>>>>> main
    logger.info("etl_agent_starting", version="0.1.0", debug=settings.debug)
    await create_all_tables()
    yield
    await dispose_engine()
    logger.info("etl_agent_stopped")


<<<<<<< HEAD
# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

=======
>>>>>>> main
def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Autonomous ETL Agent",
        description="AI-powered ETL pipeline generation from DevOps user stories.",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

<<<<<<< HEAD
    # ------------------------------------------------------------------
    # CORS — driven by settings.cors_origins (comma-separated list or "*")
    # ------------------------------------------------------------------
    cors_origins = settings.cors_origin_list  # property on Settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-API-Key", "Authorization"],
    )

    # ------------------------------------------------------------------
    # Rate limiting via slowapi
    # ------------------------------------------------------------------
    try:
        from slowapi import Limiter, _rate_limit_exceeded_handler
        from slowapi.errors import RateLimitExceeded
        from slowapi.util import get_remote_address

        limiter = Limiter(key_func=get_remote_address, default_limits=["120/minute"])
        app.state.limiter = limiter
        app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
        logger.info("rate_limiting_enabled", default_limit="120/minute")
    except ImportError:
        logger.warning("slowapi_not_installed", detail="Rate limiting disabled")

    # ------------------------------------------------------------------
    # Custom security middleware (order matters: outermost runs first)
    # ------------------------------------------------------------------
    from etl_agent.api.middleware import APIKeyMiddleware, BodySizeLimitMiddleware

    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(APIKeyMiddleware)

    # ------------------------------------------------------------------
    # API routers
    # ------------------------------------------------------------------
    from etl_agent.api.v1 import health, runs, stories

=======
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register API routers
    from etl_agent.api.v1 import health, runs, stories
    from etl_agent.api.middleware import APIKeyMiddleware

    app.add_middleware(APIKeyMiddleware)
>>>>>>> main
    app.include_router(health.router, prefix="/api/v1", tags=["health"])
    app.include_router(stories.router, prefix="/api/v1", tags=["stories"])
    app.include_router(runs.router, prefix="/api/v1", tags=["runs"])

<<<<<<< HEAD
    # ------------------------------------------------------------------
    # Static UI
    # ------------------------------------------------------------------
=======
    # Serve the single-page UI from src/etl_agent/static/
>>>>>>> main
    static_dir = Path(__file__).parent.parent / "static"
    if static_dir.exists():
        app.mount("/ui", StaticFiles(directory=str(static_dir), html=True), name="ui")

    # Redirect root to UI
    @app.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:
        return RedirectResponse(url="/ui")

    return app


app = create_app()
