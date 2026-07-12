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
        columns = (await connection.exec_driver_sql("PRAGMA table_info(recommendations)")).all()
        if "target_2" not in {column[1] for column in columns}:
            await connection.exec_driver_sql("ALTER TABLE recommendations ADD COLUMN target_2 FLOAT")
