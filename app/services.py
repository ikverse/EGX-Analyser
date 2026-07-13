from collections import Counter
from datetime import datetime, timezone
import json
from math import sqrt
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.ai.service import AIAnalysisService, AnalysisOutcome
from app.models import Embedding, Image, Media, Message, Recommendation, Signal, StockMention
from app.repositories import StockRepository, get_or_create_channel
from app.schemas import ExtractedStockMention, MessageCreate


class MessageService:
    def __init__(self, session: AsyncSession, analyzer: AIAnalysisService | None = None) -> None:
        self.session, self.analyzer = session, analyzer

    async def ingest(self, payload: MessageCreate) -> Message:
        channel = await get_or_create_channel(self.session, payload.channel_handle)
        existing = await self.session.scalar(select(Message).where(
            Message.channel_id == channel.id, Message.telegram_message_id == payload.telegram_message_id))
        if existing:
            return existing
        message = Message(channel_id=channel.id, telegram_message_id=payload.telegram_message_id,
                          published_at=payload.published_at, text=payload.text, author=payload.author,
                          views=payload.views, forwarded_from=payload.forwarded_from)
        self.session.add(message)
        await self.session.flush()
        return message

    async def analyze(self, message: Message, force: bool = False) -> list[Recommendation]:
        if self.analyzer is None:
            raise RuntimeError("AI analysis service is unavailable")
        existing = (await self.session.scalars(
            select(Recommendation).where(Recommendation.message_id == message.id)
        )).all()
        existing_mentions = (await self.session.scalars(
            select(StockMention).where(StockMention.message_id == message.id)
        )).all()
        if not force and message.processed_at and (existing or existing_mentions):
            return list(existing)
        images = (await self.session.scalars(
            select(Image).where(Image.message_id == message.id)
        )).all()
        media = (await self.session.scalars(select(Media).where(Media.message_id == message.id))).all()
        transcripts = [item.transcript for item in media if item.transcript]
        analysis = await self.analyzer.analyze(message.text, [image.path for image in images], transcripts)
        if isinstance(analysis, AnalysisOutcome):
            result, message.ai_response_raw = analysis.result, analysis.raw_response
        else:
            result = analysis
            message.ai_response_raw = json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
        await self.session.execute(delete(Recommendation).where(Recommendation.message_id == message.id))
        await self.session.execute(delete(StockMention).where(StockMention.message_id == message.id))
        stocks = StockRepository(self.session)
        created: list[Recommendation] = []
        for item in result.recommendations:
            stock = await stocks.resolve(item.ticker, item.company_name)
            recommendation = Recommendation(message_id=message.id, stock_id=stock.id if stock else None,
                signal=item.signal.value, company_name=item.company_name, ticker_raw=item.ticker, entry=item.entry,
                target=item.target, target_2=item.target_2, stop_loss=item.stop_loss, reason=item.reason, risk_level=item.risk_level,
                time_horizon=item.time_horizon, indicators=item.indicators, confidence=item.confidence)
            self.session.add(recommendation)
            created.append(recommendation)
        mentions = {item.ticker.upper().strip(): item for item in result.stock_mentions if item.ticker.strip()}
        for recommendation in result.recommendations:
            if recommendation.ticker:
                ticker = recommendation.ticker.upper().strip()
                if ticker not in mentions:
                    mentions[ticker] = ExtractedStockMention(ticker=ticker, company_name=recommendation.company_name,
                                                             context=recommendation.reason, confidence=recommendation.confidence)
        for mention in mentions.values():
            stock = await stocks.resolve(mention.ticker, mention.company_name)
            self.session.add(StockMention(
                message_id=message.id, stock_id=stock.id if stock else None, ticker_raw=mention.ticker.upper().strip(),
                company_name_raw=mention.company_name, context=mention.context, table_data=mention.table_data,
                confidence=mention.confidence,
            ))
        message.processed_at = datetime.now(timezone.utc)
        content = "\n".join([message.text, *(image.ocr_text or "" for image in images)]).strip()
        if content:
            try:
                vector = await self.analyzer.embed(content)
            except RuntimeError:
                vector = []
            if vector:
                embedding = await self.session.scalar(
                    select(Embedding).where(Embedding.message_id == message.id)
                )
                if embedding is None:
                    self.session.add(Embedding(message_id=message.id, content=content, vector=vector))
                else:
                    embedding.content, embedding.vector = content, vector
        for image in images:
            image.vision_analysis = {"observations": result.image_observations,
                                     "stock_mentions": [item.model_dump() for item in result.stock_mentions]}
        await self.session.flush()
        return created


class AnalyticsService:
    def __init__(self, session: AsyncSession) -> None: self.session = session

    async def consensus(self) -> list[dict[str, object]]:
        rows = (await self.session.execute(select(
            Recommendation.company_name, Recommendation.signal, func.count(), func.avg(Recommendation.confidence),
            func.avg(Recommendation.entry), func.avg(Recommendation.target), func.avg(Recommendation.stop_loss)
        ).group_by(Recommendation.company_name, Recommendation.signal))).all()
        grouped: dict[str, list] = {}
        for row in rows: grouped.setdefault(row[0], []).append(row)
        results = []
        for company, values in grouped.items():
            counts = Counter({value[1]: value[2] for value in values})
            strongest = max(counts, key=counts.get)
            result = {"company": company, "sentiment": strongest, "buy_count": counts[Signal.BUY.value],
                      "sell_count": counts[Signal.SELL.value], "hold_count": counts[Signal.HOLD.value]}
            selected = next(row for row in values if row[1] == strongest)
            result.update({"confidence": round(float(selected[3] or 0), 3), "average_entry": selected[4],
                           "average_target": selected[5], "average_stop": selected[6]})
            results.append(result)
        return sorted(results, key=lambda item: item["confidence"], reverse=True)


class SearchService:
    def __init__(self, session: AsyncSession, analyzer: AIAnalysisService | None = None) -> None:
        self.session, self.analyzer = session, analyzer

    async def search(self, query: str, limit: int) -> list[dict[str, object]]:
        if self.analyzer is None:
            return await self._keyword_search(query, limit)
        try:
            query_vector = await self.analyzer.embed(query)
        except RuntimeError:
            return await self._keyword_search(query, limit)
        rows = (await self.session.execute(
            select(Embedding, Message).join(Message, Embedding.message_id == Message.id)
        )).all()
        ranked = sorted(
            ((self._cosine(query_vector, embedding.vector or []), message) for embedding, message in rows),
            key=lambda item: item[0], reverse=True,
        )[:limit]
        return [{"id": message.id, "text": message.text, "published_at": message.published_at,
                 "score": round(score, 4)} for score, message in ranked if score > 0]

    async def _keyword_search(self, query: str, limit: int) -> list[dict[str, object]]:
        term = f"%{query}%"
        messages = (await self.session.scalars(select(Message).where(
            Message.text.ilike(term)).order_by(Message.published_at.desc()).limit(limit))).all()
        return [{"id": message.id, "text": message.text, "published_at": message.published_at,
                 "score": None} for message in messages]

    @staticmethod
    def _cosine(left: list[float], right: list[float]) -> float:
        if not left or not right or len(left) != len(right):
            return 0.0
        denominator = sqrt(sum(value * value for value in left)) * sqrt(sum(value * value for value in right))
        return sum(a * b for a, b in zip(left, right)) / denominator if denominator else 0.0
