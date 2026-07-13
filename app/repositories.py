from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Channel, Stock
from app.config import get_settings
from app.content_updates import ContentUpdateService


class StockRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def resolve(self, ticker: str | None, company_name: str) -> Stock | None:
        if not ticker:
            ticker = ContentUpdateService(get_settings()).stock_aliases().get(company_name.strip().casefold())
        if not ticker:
            return None
        normalized = ticker.upper().strip()
        stock = await self.session.scalar(select(Stock).where(Stock.ticker == normalized))
        if stock:
            return stock
        stock = Stock(ticker=normalized, name_en=company_name, aliases=[company_name])
        self.session.add(stock)
        await self.session.flush()
        return stock


async def get_or_create_channel(session: AsyncSession, handle: str) -> Channel:
    normalized = handle.lower().lstrip("@")
    channel = await session.scalar(select(Channel).where(Channel.handle == normalized))
    if channel is None:
        channel = Channel(handle=normalized, title=normalized)
        session.add(channel)
        await session.flush()
    return channel
