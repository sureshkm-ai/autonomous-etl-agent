"""FastAPI application factory with lifespan management."""
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from etl_agent.core.config import get_settings
from etl_agent.core.logging import configure_logging, get_logger
from etl_agent.database.session import create_all_tables, dispose_engine

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application startup and shutdown lifecycle."""
    settings = get_settings()
    configure_logging(log_level="DEBUG" if settings.debug else "INFO", json_logs=not settings.debug)
    logger.info("etl_agent_starting", version="0.1.0", debug=settings.debug)
    await create_all_tables()
    yield
    await dispose_engine()
    logger.info("etl_agent_stopped")


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
    app.include_router(health.router, prefix="/api/v1", tags=["health"])
    app.include_router(stories.router, prefix="/api/v1", tags=["stories"])
    app.include_router(runs.router, prefix="/api/v1", tags=["runs"])

    return app


app = create_app()
