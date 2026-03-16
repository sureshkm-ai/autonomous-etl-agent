"""Database session factory and initialization."""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker


_engine = None
_session_factory = None


async def init_db():
    """Initialize database engine."""
    global _engine
    from etl_agent.core.config import get_settings
    settings = get_settings()
    _engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)


def get_session_factory() -> async_sessionmaker:
    """Get SQLAlchemy session factory."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
    return _session_factory


async def get_db():
    """Dependency: get database session."""
    factory = get_session_factory()
    async with factory() as session:
        yield session


async def create_all_tables():
    """Create all database tables."""
    from etl_agent.database.models import Base
    if _engine is None:
        await init_db()
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_engine():
    """Dispose database engine."""
    if _engine:
        await _engine.dispose()
