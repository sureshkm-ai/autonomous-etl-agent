"""Database session factory and initialization."""
<<<<<<< HEAD
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
=======
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

>>>>>>> main

_engine = None
_session_factory = None


<<<<<<< HEAD
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
        _session_factory = async_sessionmaker(
            _engine, class_=AsyncSession, expire_on_commit=False
        )
=======
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
>>>>>>> main
    return _session_factory


async def get_db():
<<<<<<< HEAD
=======
    """Dependency: get database session."""
>>>>>>> main
    factory = get_session_factory()
    async with factory() as session:
        yield session


<<<<<<< HEAD
async def create_all_tables() -> None:
    """Create all tables (safe to call on every startup — uses IF NOT EXISTS)."""
=======
async def create_all_tables():
    """Create all database tables."""
>>>>>>> main
    from etl_agent.database.models import Base
    if _engine is None:
        await init_db()
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


<<<<<<< HEAD
async def dispose_engine() -> None:
=======
async def dispose_engine():
    """Dispose database engine."""
>>>>>>> main
    if _engine:
        await _engine.dispose()
