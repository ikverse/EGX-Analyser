from collections.abc import AsyncIterator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from app.config import get_settings


_engine = None
_session_factory = None


def _engine_and_factory():
    global _engine, _session_factory
    if _engine is None:
        _engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine, _session_factory


def SessionLocal():
    _, factory = _engine_and_factory()
    return factory()


async def get_session() -> AsyncIterator[AsyncSession]:
    _, factory = _engine_and_factory()
    async with factory() as session:
        yield session


async def init_database() -> None:
    engine, _ = _engine_and_factory()
    if not get_settings().database_url.startswith("sqlite"):
        return
    from app.models import Base
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        migrations = {"recommendations": {"target_2": "FLOAT"}, "channels": {"last_collected_message_id": "INTEGER", "last_collected_at": "DATETIME"}, "messages": {"processing_error": "TEXT", "ai_response_raw": "TEXT"}}
        for table, additions in migrations.items():
            columns = {column[1] for column in (await connection.exec_driver_sql(f"PRAGMA table_info({table})")).all()}
            for name, definition in additions.items():
                if name not in columns: await connection.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
