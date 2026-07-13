from datetime import datetime, time, timedelta, timezone
from html import escape
from statistics import median
from zoneinfo import ZoneInfo

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import Channel, Message, Recommendation, Report, Stock, StockMention


def is_stock_related(text: str) -> bool:
    normalized = text.lower()
    keywords = (
        "egx", "stock", "shares", "buy", "sell", "target", "entry", "support", "resistance",
        "البورصة", "سهم", "أسهم", "شراء", "بيع", "هدف", "دخول", "دعم", "مقاومة",
    )
    return any(keyword in normalized for keyword in keywords)


class ReportService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session, self.settings = session, settings

    async def generate_daily(self, report_mode: str = "calendar", report_date: datetime | None = None) -> Report:
        generated_at = report_date or datetime.now(timezone.utc)
        cairo = ZoneInfo("Africa/Cairo")
        local_day = generated_at.astimezone(cairo).date()
        start = datetime.combine(local_day, time(0, 0), tzinfo=cairo)
        end = start + timedelta(days=1)
        if report_mode == "session":
            start = datetime.combine(local_day, time.fromisoformat(self.settings.egx_session_start), tzinfo=cairo)
            end = datetime.combine(local_day, time.fromisoformat(self.settings.egx_session_end), tzinfo=cairo)
        return await self._generate(start.astimezone(timezone.utc), end.astimezone(timezone.utc), report_mode)

    async def generate_selected_chat_report(self, channel_ids: list[int], start: datetime, end: datetime,
                                             lookback_days: int) -> Report:
        return await self._generate(start, end, f"selected chats ({lookback_days} days)", channel_ids)

    async def _generate(self, start: datetime, end: datetime, report_mode: str,
                        channel_ids: list[int] | None = None) -> Report:
        filters = [Message.published_at >= start, Message.published_at < end]
        if channel_ids is not None:
            filters.append(Message.channel_id.in_(channel_ids))
        recommendation_rows = (await self.session.execute(
            select(Recommendation, Message, Channel)
            .join(Message, Recommendation.message_id == Message.id)
            .join(Channel, Message.channel_id == Channel.id)
            .where(*filters)
        )).all()
        message_rows = (await self.session.execute(
            select(Message, Channel).join(Channel, Message.channel_id == Channel.id).where(*filters)
        )).all()
        mention_rows = (await self.session.execute(
            select(StockMention, Message, Channel, Stock)
            .join(Message, StockMention.message_id == Message.id)
            .join(Channel, Message.channel_id == Channel.id)
            .outerjoin(Stock, StockMention.stock_id == Stock.id)
            .where(*filters)
        )).all()
        ids = channel_ids or sorted({channel.id for _, channel in message_rows})
        channels = (await self.session.scalars(select(Channel).where(Channel.id.in_(ids)))).all() if ids else []

        grouped: dict[str, list[tuple[Recommendation, Message, Channel]]] = {}
        for recommendation, message, channel in recommendation_rows:
            grouped.setdefault((recommendation.ticker_raw or recommendation.company_name).upper(), []).append(
                (recommendation, message, channel)
            )
        consensus = []
        for ticker, items in grouped.items():
            signals: dict[str, int] = {}
            for recommendation, _, _ in items:
                signals[recommendation.signal] = signals.get(recommendation.signal, 0) + 1
            signal = max(signals, key=signals.get)
            selected = [recommendation for recommendation, _, _ in items if recommendation.signal == signal]
            source_channels = {channel.title or channel.handle for _, _, channel in items}
            consensus.append({
                "ticker": ticker, "company": items[0][0].company_name, "signal": signal,
                "priority": round(len(source_channels) * 100 + sum(item.confidence for item in selected) * 10, 1),
                "channel_count": len(source_channels),
                "entry": _median([item.entry for item in selected if item.entry is not None]),
                "tp1": _median([item.target for item in selected if item.target is not None]),
                "tp2": _median([item.target_2 for item in selected if item.target_2 is not None]),
                "stop": _median([item.stop_loss for item in selected if item.stop_loss is not None]),
                "confidence": round(sum(item.confidence for item in selected) / len(selected), 2),
                "evidence": [{"channel": channel.title or channel.handle, "signal": recommendation.signal,
                              "entry": recommendation.entry, "tp1": recommendation.target,
                              "tp2": recommendation.target_2, "stop": recommendation.stop_loss,
                              "reason": recommendation.reason} for recommendation, _, channel in items],
            })
        consensus.sort(key=lambda item: item["priority"], reverse=True)

        texts_by_channel: dict[int, list[str]] = {}
        for message, channel in message_rows:
            texts_by_channel.setdefault(channel.id, []).append(message.text)
        recommendation_counts: dict[int, int] = {}
        for _, message, _ in recommendation_rows:
            recommendation_counts[message.channel_id] = recommendation_counts.get(message.channel_id, 0) + 1
        mention_counts: dict[int, int] = {}
        ticker_groups: dict[str, list[tuple[StockMention, Message, Channel, Stock | None]]] = {}
        for mention, message, channel, stock in mention_rows:
            mention_counts[message.channel_id] = mention_counts.get(message.channel_id, 0) + 1
            ticker_groups.setdefault(mention.ticker_raw.upper(), []).append((mention, message, channel, stock))
        stock_code_summary = []
        for ticker, items in ticker_groups.items():
            names = [stock.name_en for _, _, _, stock in items if stock and stock.name_en]
            names += [mention.company_name_raw for mention, _, _, _ in items if mention.company_name_raw]
            channel_counts: dict[str, int] = {}
            data_samples = []
            for mention, _, channel, _ in items:
                channel_name = channel.title or channel.handle
                channel_counts[channel_name] = channel_counts.get(channel_name, 0) + 1
                if mention.table_data and len(data_samples) < 3:
                    data_samples.append({"channel": channel_name, "data": mention.table_data, "context": mention.context})
            stock_code_summary.append({"ticker": ticker, "company": names[0] if names else ticker,
                                       "occurrences": len(items), "by_chat": channel_counts,
                                       "data_samples": data_samples})
        stock_code_summary.sort(key=lambda item: (-item["occurrences"], item["ticker"]))
        channel_results = []
        for channel in channels:
            texts = texts_by_channel.get(channel.id, [])
            recommendations = recommendation_counts.get(channel.id, 0)
            mentions = mention_counts.get(channel.id, 0)
            status = "recommendations_found" if recommendations else "stock_codes_found" if mentions else (
                "stock_related_no_recommendations" if any(is_stock_related(text) for text in texts)
                else "not_stock_related" if texts else "no_recent_messages"
            )
            channel_results.append({"channel": channel.title or channel.handle, "status": status,
                                    "messages": len(texts), "recommendations": recommendations, "stock_codes": mentions})

        generated_at = datetime.now(timezone.utc)
        directory = self.settings.storage_root / "reports" / generated_at.strftime("%Y-%m-%d")
        directory.mkdir(parents=True, exist_ok=True)
        lines = [
            f"# EGX Intelligence Report - {generated_at:%Y-%m-%d}", "",
            f"## Overview ({report_mode})", f"- Messages: {len(message_rows)}",
            f"- Recommendations: {len(recommendation_rows)}", "", "## Chat relevance",
        ]
        lines += [f"- {item['channel']}: {item['status']} | Messages {item['messages']} | Recommendations {item['recommendations']}" for item in channel_results]
        lines += ["", "## EGX codes found", "| Code | Company | Occurrences | Per chat | Table/chat data |", "| --- | --- | ---: | --- | --- |"]
        for item in stock_code_summary:
            per_chat = ", ".join(f"{name}: {count}" for name, count in item["by_chat"].items())
            samples = "; ".join(
                f"{sample['channel']}: " + ", ".join(f"{key}={value}" for key, value in sample["data"].items())
                for sample in item["data_samples"]
            ) or "-"
            lines.append(f"| {item['ticker']} | {item['company']} | {item['occurrences']} | {per_chat} | {samples} |")
        lines += ["", "## Consolidated suggestions"]
        for item in consensus:
            lines += [
                f"### {item['ticker']} - {item['company']} | {item['signal']} | Priority {item['priority']}",
                f"- AI suggestion: Entry {item['entry'] or '-'} | TP1 {item['tp1'] or '-'} | TP2 {item['tp2'] or '-'} | Stop {item['stop'] or '-'}",
                f"- Agreement: {item['channel_count']} channels | Confidence {item['confidence']:.0%}",
            ]
            lines += [f"  - {e['channel']}: {e['signal']} | Entry {e['entry'] or '-'} | TP1 {e['tp1'] or '-'} | TP2 {e['tp2'] or '-'} | Stop {e['stop'] or '-'} | {e['reason'] or ''}" for e in item["evidence"]]
        if not consensus:
            lines.append("- No stock recommendations were detected in this analysis window.")
        run_id = generated_at.strftime("%H%M%S")
        markdown_path = directory / f"report-{run_id}.md"
        html_path = directory / f"report-{run_id}.html"
        pdf_path = directory / f"report-{run_id}.pdf"
        markdown = "\n".join(lines)
        markdown_path.write_text(markdown, encoding="utf-8")
        html_path.write_text(f"<html><body><pre>{escape(markdown)}</pre></body></html>", encoding="utf-8")
        canvas = Canvas(str(pdf_path), pagesize=A4)
        text = canvas.beginText(48, 800)
        for line in lines:
            text.textLine(line)
        canvas.drawText(text)
        canvas.save()
        report = Report(markdown_path=str(markdown_path), html_path=str(html_path), pdf_path=str(pdf_path), summary={
            "mode": report_mode, "consensus": consensus, "message_count": len(message_rows),
            "recommendation_count": len(recommendation_rows), "channel_results": channel_results,
            "stock_code_summary": stock_code_summary,
        })
        self.session.add(report)
        await self.session.flush()
        return report


def _median(values: list[float]) -> float | None:
    return median(values) if values else None
