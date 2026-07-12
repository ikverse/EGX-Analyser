from datetime import datetime, timezone
from html import escape
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import Settings
from app.models import Message, Recommendation, Report, Signal
from app.services import AnalyticsService


class ReportService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session, self.settings = session, settings

    async def generate_daily(self) -> Report:
        consensus = await AnalyticsService(self.session).consensus()
        generated_at = datetime.now(timezone.utc)
        stamp = generated_at.strftime("%Y-%m-%d")
        run_id = generated_at.strftime("%H%M%S")
        directory = self.settings.storage_root / "reports" / stamp
        directory.mkdir(parents=True, exist_ok=True)
        message_count = await self.session.scalar(select(func.count()).select_from(Message)) or 0
        recommendation_count = await self.session.scalar(
            select(func.count()).select_from(Recommendation)
        ) or 0
        signals = dict((await self.session.execute(
            select(Recommendation.signal, func.count()).group_by(Recommendation.signal)
        )).all())
        lines = [
            f"# EGX Market Intelligence Report - {stamp}", "", "## Overview",
            f"- Messages tracked: {message_count}",
            f"- Recommendations extracted: {recommendation_count}",
            f"- Buy / Sell / Hold: {signals.get(Signal.BUY.value, 0)} / "
            f"{signals.get(Signal.SELL.value, 0)} / {signals.get(Signal.HOLD.value, 0)}",
            "", "## Consensus",
        ]
        lines += [
            f"- **{item['company']}**: {item['sentiment']} ({item['confidence']:.0%} confidence)"
            for item in consensus
        ] or ["- No analyzed recommendations are available yet."]
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
            summary={"consensus": consensus, "message_count": message_count,
                     "recommendation_count": recommendation_count, "signals": signals},
        )
        self.session.add(report)
        await self.session.flush()
        return report
