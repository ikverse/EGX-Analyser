from collections.abc import AsyncIterator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from app.config import get_settings

settings = get_settings()
engine = create_async_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def init_database() -> None:
    if not settings.database_url.startswith("sqlite"):
        return
    from app.models import Base
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        migrations = {"recommendations": {"target_2": "FLOAT"}, "channels": {"last_collected_message_id": "INTEGER", "last_collected_at": "DATETIME"}, "messages": {"processing_error": "TEXT", "ai_response_raw": "TEXT"}}
        for table, additions in migrations.items():
            columns = {column[1] for column in (await connection.exec_driver_sql(f"PRAGMA table_info({table})")).all()}
            for name, definition in additions.items():
                if name not in columns: await connection.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
