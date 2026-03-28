"""Database session factory and initialization."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_engine = None
_session_factory = None


async def init_db() -> None:
    """Initialize database engine from settings."""
    global _engine
    from etl_agent.core.config import get_settings

    settings = get_settings()
    db_url = getattr(settings, "database_url", "sqlite+aiosqlite:///./etl_agent.db")
    _engine = create_async_engine(db_url, echo=False)


def get_session_factory() -> async_sessionmaker:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
    return _session_factory


async def get_db():
    factory = get_session_factory()
    async with factory() as session:
        yield session


async def create_all_tables() -> None:
    """Create all tables (safe to call on every startup — uses IF NOT EXISTS)."""
    from etl_agent.database.models import Base

    if _engine is None:
        await init_db()
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_engine() -> None:
    if _engine:
        await _engine.dispose()
