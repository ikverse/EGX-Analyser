from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from html import escape
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import Settings
from app.models import Channel, Message, Recommendation, Report, Signal
from app.services import AnalyticsService


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
        rows = (await self.session.execute(
            select(Recommendation, Message, Channel).join(Message, Recommendation.message_id == Message.id).join(Channel, Message.channel_id == Channel.id)
            .where(Message.published_at >= start.astimezone(timezone.utc), Message.published_at < end.astimezone(timezone.utc))
        )).all()
        grouped: dict[str, list] = {}
        for recommendation, message, channel in rows:
            key = (recommendation.ticker_raw or recommendation.company_name).upper()
            grouped.setdefault(key, []).append((recommendation, message, channel))
        consensus = []
        for ticker, items in grouped.items():
            signals: dict[str, int] = {}
            for recommendation, _, _ in items: signals[recommendation.signal] = signals.get(recommendation.signal, 0) + 1
            signal = max(signals, key=signals.get)
            selected = [item[0] for item in items if item[0].signal == signal]
            median = lambda values: sorted(values)[len(values) // 2] if values else None
            channels = {item[2].title or item[2].handle for item in items}
            consensus.append({"ticker": ticker, "company": items[0][0].company_name, "signal": signal,
                "priority": round(len(channels) * 100 + sum(item[0].confidence for item in selected) * 10, 1),
                "channel_count": len(channels), "entry": median([item.entry for item in selected if item.entry is not None]),
                "tp1": median([item.target for item in selected if item.target is not None]), "tp2": median([item.target_2 for item in selected if item.target_2 is not None]),
                "stop": median([item.stop_loss for item in selected if item.stop_loss is not None]),
                "confidence": round(sum(item.confidence for item in selected) / len(selected), 2),
                "evidence": [{"channel": channel.title or channel.handle, "signal": recommendation.signal, "entry": recommendation.entry, "tp1": recommendation.target, "tp2": recommendation.target_2, "stop": recommendation.stop_loss, "reason": recommendation.reason} for recommendation, _, channel in items]})
        consensus.sort(key=lambda item: item["priority"], reverse=True)
        stamp = generated_at.strftime("%Y-%m-%d")
        run_id = generated_at.strftime("%H%M%S")
        directory = self.settings.storage_root / "reports" / stamp
        directory.mkdir(parents=True, exist_ok=True)
        message_count = len({message.id for _, message, _ in rows})
        recommendation_count = len(rows)
        signals: dict[str, int] = {}
        for recommendation, _, _ in rows:
            signals[recommendation.signal] = signals.get(recommendation.signal, 0) + 1
        lines = [f"# EGX Daily Intelligence | تقرير EGX اليومي - {stamp}", "", f"## Overview | ملخص ({report_mode})", f"- Messages | الرسائل: {message_count}", f"- Recommendations | التوصيات: {recommendation_count}", "", "## Consolidated suggestions | الاقتراحات المجمعة"]
        for item in consensus:
            lines += [f"### {item['ticker']} — {item['company']} | {item['signal']} | Priority {item['priority']}", f"- AI suggestion | اقتراح الذكاء: Entry {item['entry'] or '—'} | TP1 {item['tp1'] or '—'} | TP2 {item['tp2'] or '—'} | Stop {item['stop'] or '—'}", f"- Agreement | التكرار: {item['channel_count']} channels | Confidence {item['confidence']:.0%}", "- Original channel levels | مستويات القنوات:"]
            lines += [f"  - {e['channel']}: {e['signal']} | Entry {e['entry'] or '—'} | TP1 {e['tp1'] or '—'} | TP2 {e['tp2'] or '—'} | Stop {e['stop'] or '—'} | {e['reason'] or ''}" for e in item['evidence']]
        if not consensus: lines += ["- No analyzed recommendations are available yet. | لا توجد توصيات محللة بعد."]
        markdown = "\n".join(lines)
        md_path = directory / f"report-{run_id}.md"
        html_path = directory / f"report-{run_id}.html"
        pdf_path = directory / f"report-{run_id}.pdf"
        md_path.write_text(markdown, encoding="utf-8")
        html_path.write_text("<html><body><pre>" + escape(markdown) + "</pre></body></html>", encoding="utf-8")
        canvas = Canvas(str(pdf_path), pagesize=A4)
        text = canvas.beginText(48, 800)
        for line in lines:
            text.textLine(line)
        canvas.drawText(text)
        canvas.save()
        report = Report(
            markdown_path=str(md_path), html_path=str(html_path), pdf_path=str(pdf_path),
            summary={"mode": report_mode, "consensus": consensus, "message_count": message_count, "recommendation_count": recommendation_count, "signals": signals},
        )
        self.session.add(report)
        await self.session.flush()
        return report
