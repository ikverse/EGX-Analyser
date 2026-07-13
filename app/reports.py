from datetime import datetime, time, timedelta, timezone
from html import escape
import json
import os
from pathlib import Path
from statistics import median
from zoneinfo import ZoneInfo

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import Channel, Image, Media, Message, Recommendation, Report, Stock, StockMention

try:
    import arabic_reshaper
    from bidi.algorithm import get_display
except ImportError:
    arabic_reshaper = None
    get_display = None


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
        message_ids = [msg.id for msg, _ in message_rows]
        image_rows: list[tuple] = []
        if message_ids:
            image_rows = (await self.session.execute(
                select(Image, Message)
                .join(Message, Image.message_id == Message.id)
                .where(Image.message_id.in_(message_ids))
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
        stock_code_details = []
        for ticker, items in ticker_groups.items():
            names = [stock.name_en for _, _, _, stock in items if stock and stock.name_en]
            names += [mention.company_name_raw for mention, _, _, _ in items if mention.company_name_raw]
            company = names[0] if names else ticker
            channel_counts: dict[str, int] = {}
            data_samples = []
            details_by_channel: dict[str, list[StockMention]] = {}
            for mention, _, channel, _ in items:
                channel_name = channel.title or channel.handle
                channel_counts[channel_name] = channel_counts.get(channel_name, 0) + 1
                details_by_channel.setdefault(channel_name, []).append(mention)
                if mention.table_data and len(data_samples) < 3:
                    data_samples.append({"channel": channel_name, "data": mention.table_data, "context": mention.context})
            stock_code_summary.append({"ticker": ticker, "company": company,
                                       "occurrences": len(items), "by_chat": channel_counts,
                                       "data_samples": data_samples})
            ticker_notes = _collect_ticker_notes(ticker, items, recommendation_rows, image_rows)
            for channel_name, mentions in details_by_channel.items():
                details = []
                for mention in mentions:
                    detail = {str(key): str(value) for key, value in (mention.table_data or {}).items()}
                    if mention.context:
                        detail["context"] = mention.context
                    if detail:
                        details.append(detail)
                stock_code_details.append({"ticker": ticker, "company": company, "channel": channel_name,
                                           "occurrences": len(mentions), "details": details,
                                           "notes": ticker_notes})
        stock_code_summary.sort(key=lambda item: (-item["occurrences"], item["ticker"]))
        stock_code_details.sort(key=lambda item: (item["ticker"], item["channel"]))
        consolidated_source = _consolidated_source_output(message_rows)
        if consolidated_source is not None:
            consensus, stock_code_summary, stock_code_details = _source_driven_tables(consolidated_source)
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
        if consolidated_source is not None:
            lines += ["", "## Qwen consolidated analysis", f"- Analysis period: {consolidated_source.get('analysis_period') or report_mode}"]
            lines += ["", "| Rank | Code | Company (EN) | Company (AR) | Mentions | Status | Source | Buy | Target 1 | Target 2 | Stop loss |", "| ---: | --- | --- | --- | ---: | --- | --- | ---: | ---: | ---: | ---: |"]
            for item in consolidated_source.get("top_consolidated_recommendations", []):
                if not isinstance(item, dict):
                    continue
                points = item.get("data_points") if isinstance(item.get("data_points"), list) else []
                for point in points or [{}]:
                    point = point if isinstance(point, dict) else {}
                    lines.append(
                        f"| {item.get('rank') or '-'} | {item.get('stock_code') or '-'} | {item.get('stock_name_en') or '-'} | {item.get('stock_name_ar') or '-'} | "
                        f"{item.get('mention_count') or 0} | {item.get('status') or '-'} | {point.get('source') or '-'} | "
                        f"{point.get('buy_price') or '-'} | {point.get('target_1') or '-'} | {point.get('target_2') or '-'} | {point.get('stop_loss') or '-'} |"
                    )
                if item.get("analysis_summary_ar"):
                    lines.append(f"- {item.get('stock_code')}: {item['analysis_summary_ar']}")
            lines += ["", "## Achieved targets"]
            for item in consolidated_source.get("achieved_targets", []):
                if isinstance(item, dict):
                    lines.append(f"- {item.get('stock_code') or '-'} | {item.get('stock_name_en') or '-'} | {item.get('status_ar') or '-'} | {item.get('date') or '-'} | {item.get('source') or '-'}")
            lines += ["", "## Text-based categories"]
            categories = consolidated_source.get("text_based_categories")
            if isinstance(categories, dict):
                for name, stocks in categories.items():
                    lines.append(f"- {name}: {_category_labels(stocks)}")
            lines += ["", "## Daily breakdown"]
            daily = consolidated_source.get("daily_breakdown")
            if isinstance(daily, dict):
                for day, values in sorted(daily.items()):
                    values = values if isinstance(values, dict) else {}
                    lines.append(f"- {day}: mentions {values.get('total_mentions') or 0} | top stock {values.get('top_stock_of_day') or '-'}")
        lines += ["", "## EGX code details by channel", "| Code | Company | Channel | Occurrences | Extracted chat/table details |", "| --- | --- | --- | ---: | --- |"]
        for item in stock_code_details:
            details = "; ".join(
                ", ".join(f"{key}={value}" for key, value in detail.items()) for detail in item["details"]
            ) or "-"
            lines.append(f"| {item['ticker']} | {item['company']} | {item['channel']} | {item['occurrences']} | {details} |")
        if not stock_code_details:
            lines.append("| - | - | - | 0 | No EGX codes were found in this analysis window. |")
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
        raw_text_path = directory / f"original-ai-response-{run_id}.txt"
        raw_pdf_path = directory / f"original-ai-response-{run_id}.pdf"
        markdown = "\n".join(lines)
        markdown_path.write_text(markdown, encoding="utf-8")
        html_path.write_text(
            _build_html_report(generated_at, report_mode, message_rows, recommendation_rows,
                               channel_results, consensus, stock_code_details,
                               consolidated_source),
            encoding="utf-8",
        )
        canvas = Canvas(str(pdf_path), pagesize=A4)
        text = canvas.beginText(48, 800)
        for line in lines:
            text.textLine(line)
        canvas.drawText(text)
        canvas.save()
        raw_lines = [f"EGX Intelligence - Original AI Responses ({generated_at:%Y-%m-%d %H:%M UTC})", ""]
        for message, channel in message_rows:
            if not message.ai_response_raw:
                continue
            raw_lines += [
                f"Channel: {channel.title or channel.handle}",
                f"Telegram message: {message.telegram_message_id}",
                f"Published: {message.published_at.isoformat()}",
                "", message.ai_response_raw, "", "=" * 90, "",
            ]
        if len(raw_lines) == 2:
            raw_lines.append("No original AI responses were recorded for this analysis window.")
        raw_text_path.write_text("\n".join(raw_lines), encoding="utf-8")
        raw_canvas = Canvas(str(raw_pdf_path), pagesize=A4)
        raw_text = raw_canvas.beginText(36, 806)
        raw_font = _raw_pdf_font()
        raw_text.setFont(raw_font, 7)
        for line in raw_lines:
            for wrapped in _wrap_pdf_line(_format_pdf_text(line), 125):
                if raw_text.getY() < 36:
                    raw_canvas.drawText(raw_text)
                    raw_canvas.showPage()
                    raw_text = raw_canvas.beginText(36, 806)
                    raw_text.setFont(raw_font, 7)
                raw_text.textLine(wrapped)
        raw_canvas.drawText(raw_text)
        raw_canvas.save()
        report = Report(markdown_path=str(markdown_path), html_path=str(html_path), pdf_path=str(pdf_path), summary={
            "mode": report_mode, "consensus": consensus, "message_count": len(message_rows),
            "recommendation_count": len(recommendation_rows), "channel_results": channel_results,
            "stock_code_summary": stock_code_summary, "stock_code_details": stock_code_details,
            "consolidated_source": consolidated_source,
            "original_ai_response_text_path": str(raw_text_path),
            "original_ai_response_pdf_path": str(raw_pdf_path),
        })
        self.session.add(report)
        await self.session.flush()
        return report


def _median(values: list[float | None]) -> float | None:
    numeric = [value for value in values if value is not None]
    return median(numeric) if numeric else None


def _wrap_pdf_line(value: str, width: int) -> list[str]:
    return [value[index:index + width] for index in range(0, max(len(value), 1), width)]


def _format_pdf_text(value: str) -> str:
    if arabic_reshaper is not None and get_display is not None:
        return get_display(arabic_reshaper.reshape(value))
    return value


def _raw_pdf_font() -> str:
    font_name = "EGXUnicode"
    if font_name in pdfmetrics.getRegisteredFontNames():
        return font_name
    font_path = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "arial.ttf"
    if font_path.exists():
        pdfmetrics.registerFont(TTFont(font_name, str(font_path)))
        return font_name
    return "Courier"


def _consolidated_source_output(message_rows: list[tuple[Message, Channel]]) -> dict | None:
    candidates: list[dict] = []
    for message, _ in message_rows:
        if not message.ai_response_raw:
            continue
        try:
            payload = json.loads(message.ai_response_raw)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("top_consolidated_recommendations"), list):
            candidates.append(payload)
    return max(candidates, key=lambda item: len(item["top_consolidated_recommendations"]), default=None)


def _source_driven_tables(payload: dict) -> tuple[list[dict], list[dict], list[dict]]:
    consensus: list[dict] = []
    summaries: list[dict] = []
    details: list[dict] = []
    for item in payload.get("top_consolidated_recommendations", []):
        if not isinstance(item, dict) or not item.get("stock_code"):
            continue
        ticker = str(item["stock_code"]).upper()
        company = str(item.get("stock_name_en") or ticker)
        company_ar = str(item.get("stock_name_ar") or "")
        points = [point for point in item.get("data_points", []) if isinstance(point, dict)]
        by_source: dict[str, int] = {}
        per_source: dict[str, list[dict[str, str]]] = {}
        for point in points:
            source = str(point.get("source") or "Unspecified")
            by_source[source] = by_source.get(source, 0) + 1
            detail = {str(key): str(value) for key, value in point.items() if value is not None}
            per_source.setdefault(source, []).append(detail)
        summary = item.get("analysis_summary_ar")
        if summary:
            for source_details in per_source.values():
                for detail in source_details:
                    detail["analysis_summary_ar"] = str(summary)
        # Build a combined notes string for this ticker from all available text
        note_parts: list[str] = []
        if summary:
            note_parts.append(str(summary))
        for point in points:
            for key in ("context", "reason", "notes", "comment", "ملاحظات", "تعليق"):
                val = point.get(key)
                if val and str(val).strip() and str(val).strip() not in note_parts:
                    note_parts.append(str(val).strip())
        ticker_notes = " · ".join(note_parts)
        summaries.append({"ticker": ticker, "company": company, "company_ar": company_ar, "occurrences": int(item.get("mention_count") or len(points)),
                          "by_chat": by_source, "data_samples": [{"channel": source, "data": values[0]} for source, values in per_source.items() if values]})
        for source, source_details in per_source.items():
            details.append({"ticker": ticker, "company": company, "company_ar": company_ar, "channel": source,
                            "occurrences": len(source_details), "details": source_details, "notes": ticker_notes})
        signal = "BUY" if str(item.get("status") or "").lower() == "active" else "HOLD"
        consensus.append({"ticker": ticker, "company": company, "signal": signal, "priority": float(item.get("rank") or 999),
                          "channel_count": len(by_source), "entry": _median([_as_number(point.get("buy_price")) for point in points]),
                          "tp1": _median([_as_number(point.get("target_1")) for point in points]),
                          "tp2": _median([_as_number(point.get("target_2")) for point in points]),
                          "stop": _median([_as_number(point.get("stop_loss")) for point in points]),
                          "confidence": min(1.0, 0.5 + min(float(item.get("mention_count") or 0), 5) / 10), "evidence": []})
    return sorted(consensus, key=lambda item: item["priority"]), summaries, details


def _as_number(value: object) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _collect_ticker_notes(
    ticker: str,
    mention_items: list[tuple],  # (StockMention, Message, Channel, Stock|None)
    rec_items: list[tuple],      # (Recommendation, Message, Channel)
    image_rows: list[tuple],     # (Image, Message) for messages in window
) -> str:
    """Combine all human-readable notes about a ticker into one clean string."""
    seen: set[str] = set()
    parts: list[str] = []

    def add(text: str | None) -> None:
        if not text:
            return
        text = text.strip()
        if text and text not in seen and text.lower() not in ("none", "null", "-"):
            seen.add(text)
            parts.append(text)

    # 1. Mention context (surrounding text where ticker appeared)
    for mention, _, channel, _ in mention_items:
        add(mention.context)

    # 2. Recommendation reason / AI reasoning
    for rec, _, _ in rec_items:
        if (rec.ticker_raw or "").upper() == ticker or (rec.company_name or "").upper() == ticker:
            add(rec.reason)

    # 3. Image observations and OCR for messages that mention this ticker
    mention_message_ids = {msg.id for _, msg, _, _ in mention_items}
    for image, message in image_rows:
        if message.id not in mention_message_ids:
            continue
        if image.vision_analysis:
            for obs in image.vision_analysis.get("observations") or []:
                add(str(obs))
        add(image.ocr_text)

    return " · ".join(parts)


def _category_labels(stocks: object) -> str:
    if not isinstance(stocks, list):
        return "-"
    labels = []
    for item in stocks:
        if isinstance(item, dict):
            code = item.get("stock_code") or "-"
            name_en = item.get("stock_name_en") or ""
            name_ar = item.get("stock_name_ar") or ""
            labels.append(f"{code} ({name_en} {name_ar})".strip())
        else:
            labels.append(str(item))
    return ", ".join(labels) or "-"


def _build_html_report(
    generated_at: datetime,
    report_mode: str,
    message_rows: list,
    recommendation_rows: list,
    channel_results: list[dict],
    consensus: list[dict],
    stock_code_details: list[dict],
    consolidated_source: dict | None,
) -> str:
    css = """
    <style>
      :root{--bg:#0b1120;--surface:#111c2e;--border:#26364d;--text:#e5e7eb;--muted:#94a3b8;
            --green:#70c96a;--red:#f87171;--yellow:#fbbf24}
      *{box-sizing:border-box}
      body{margin:0;padding:2rem;font-family:Inter,system-ui,sans-serif;background:var(--bg);color:var(--text);line-height:1.6;direction:ltr}
      h1{font-size:1.5rem;color:var(--green);margin:0 0 .5rem}
      h2{font-size:1.1rem;color:var(--green);margin:2rem 0 .75rem;border-bottom:1px solid var(--border);padding-bottom:.35rem}
      h3{font-size:.95rem;color:var(--text);margin:1.5rem 0 .5rem}
      .meta{color:var(--muted);font-size:.85rem;margin-bottom:2rem}
      table{width:100%;border-collapse:collapse;background:var(--surface);border:1px solid var(--border);border-radius:8px;overflow:hidden;margin:.5rem 0 1.5rem;font-size:.85rem}
      th{background:#172033;color:var(--muted);padding:.65rem .8rem;text-align:left;font-weight:600}
      td{padding:.6rem .8rem;border-top:1px solid var(--border);vertical-align:top}
      .badge{display:inline-block;padding:.2rem .55rem;border-radius:4px;font-size:.75rem;font-weight:700}
      .buy{background:#1a3d24;color:#86efac}.sell{background:#3d1a1a;color:#fca5a5}.hold{background:#2e2a14;color:#fde68a}
      .ok{background:#1a3d24;color:#86efac}.warn{background:#2e2a14;color:#fde68a}.neutral{background:#172033;color:var(--muted)}
      .ar{direction:rtl;unicode-bidi:embed;text-align:right;font-size:.9rem}
      .num{text-align:right;font-variant-numeric:tabular-nums}
      .section{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:1.25rem;margin-bottom:1.5rem}
      p{margin:.3rem 0;color:var(--muted);font-size:.88rem}
      .empty{color:var(--muted);font-style:italic;font-size:.85rem}
    </style>"""

    def e(text: object) -> str:
        return escape(str(text) if text is not None else "")

    def badge(signal: str) -> str:
        cls = {"BUY": "buy", "SELL": "sell", "HOLD": "hold"}.get(str(signal).upper(), "neutral")
        return f'<span class="badge {cls}">{e(signal)}</span>'

    def status_badge(status: str) -> str:
        cls = {"recommendations_found": "ok", "stock_codes_found": "ok",
               "stock_related_no_recommendations": "warn", "not_stock_related": "neutral",
               "no_recent_messages": "neutral"}.get(status, "neutral")
        return f'<span class="badge {cls}">{e(status.replace("_", " "))}</span>'

    sections: list[str] = []

    # ── header ────────────────────────────────────────────────────────────────
    sections.append(
        f'<h1>EGX Intelligence Report</h1>'
        f'<p class="meta">Generated {generated_at:%Y-%m-%d %H:%M UTC} &nbsp;·&nbsp; '
        f'Mode: {e(report_mode)} &nbsp;·&nbsp; '
        f'Messages: {len(message_rows)} &nbsp;·&nbsp; '
        f'Recommendations: {len(recommendation_rows)}</p>'
    )

    # ── channel relevance ─────────────────────────────────────────────────────
    sections.append('<h2>Channel relevance</h2><table><thead><tr>'
                    '<th>Channel</th><th>Status</th><th>Messages</th>'
                    '<th>Recommendations</th><th>Stock codes</th></tr></thead><tbody>')
    for item in channel_results:
        sections.append(
            f'<tr><td>{e(item["channel"])}</td>'
            f'<td>{status_badge(item["status"])}</td>'
            f'<td class="num">{e(item["messages"])}</td>'
            f'<td class="num">{e(item["recommendations"])}</td>'
            f'<td class="num">{e(item["stock_codes"])}</td></tr>'
        )
    sections.append('</tbody></table>')

    # ── Qwen consolidated analysis ────────────────────────────────────────────
    if consolidated_source is not None:
        period = consolidated_source.get("analysis_period") or report_mode
        sections.append(f'<h2>Qwen consolidated analysis</h2>'
                        f'<p>Analysis period: <strong>{e(period)}</strong></p>')

        recs = consolidated_source.get("top_consolidated_recommendations", [])
        if recs:
            sections.append(
                '<table><thead><tr>'
                '<th>Rank</th><th>Code</th><th>Company (EN)</th><th>Company (AR)</th>'
                '<th class="num">Mentions</th><th>Status</th><th>Source</th>'
                '<th class="num">Buy</th><th class="num">Target 1</th>'
                '<th class="num">Target 2</th><th class="num">Stop loss</th>'
                '<th class="num">Return %</th><th class="num">Risk %</th>'
                '</tr></thead><tbody>'
            )
            for item in recs:
                if not isinstance(item, dict):
                    continue
                points = item.get("data_points") if isinstance(item.get("data_points"), list) else [{}]
                row_status = str(item.get("status") or "")
                for point in (points or [{}]):
                    point = point if isinstance(point, dict) else {}
                    sections.append(
                        f'<tr>'
                        f'<td class="num">{e(item.get("rank", "-"))}</td>'
                        f'<td><strong>{e(item.get("stock_code", "-"))}</strong></td>'
                        f'<td>{e(item.get("stock_name_en", "-"))}</td>'
                        f'<td class="ar">{e(item.get("stock_name_ar", ""))}</td>'
                        f'<td class="num">{e(item.get("mention_count", 0))}</td>'
                        f'<td>{badge(row_status if row_status else "HOLD")}</td>'
                        f'<td>{e(point.get("source", "-"))}</td>'
                        f'<td class="num">{e(point.get("buy_price", "-"))}</td>'
                        f'<td class="num">{e(point.get("target_1", "-"))}</td>'
                        f'<td class="num">{e(point.get("target_2", "-"))}</td>'
                        f'<td class="num">{e(point.get("stop_loss", "-"))}</td>'
                        f'<td class="num">{e(point.get("expected_return_pct", "-"))}</td>'
                        f'<td class="num">{e(point.get("risk_pct", "-"))}</td>'
                        f'</tr>'
                    )
                summary_ar = item.get("analysis_summary_ar")
                if summary_ar:
                    sections.append(
                        f'<tr><td colspan="13" class="ar" style="color:#94a3b8;font-size:.82rem">'
                        f'{e(summary_ar)}</td></tr>'
                    )
            sections.append('</tbody></table>')

        achieved = consolidated_source.get("achieved_targets", [])
        if achieved:
            sections.append('<h3>Achieved targets</h3>'
                            '<table><thead><tr><th>Code</th><th>Company (EN)</th>'
                            '<th>Status (AR)</th><th>Date</th><th>Source</th></tr></thead><tbody>')
            for item in achieved:
                if not isinstance(item, dict):
                    continue
                sections.append(
                    f'<tr>'
                    f'<td><strong>{e(item.get("stock_code", "-"))}</strong></td>'
                    f'<td>{e(item.get("stock_name_en", "-"))}</td>'
                    f'<td class="ar">{e(item.get("status_ar", ""))}</td>'
                    f'<td>{e(item.get("date", "-"))}</td>'
                    f'<td>{e(item.get("source", "-"))}</td>'
                    f'</tr>'
                )
            sections.append('</tbody></table>')

        categories = consolidated_source.get("text_based_categories")
        if isinstance(categories, dict):
            sections.append('<h3>Text-based categories</h3><div class="section">')
            for cat_name, cat_stocks in categories.items():
                label = cat_name.replace("_", " ").title()
                sections.append(f'<p><strong>{e(label)}:</strong> {e(_category_labels(cat_stocks))}</p>')
            sections.append('</div>')

        daily = consolidated_source.get("daily_breakdown")
        if isinstance(daily, dict):
            sections.append('<h3>Daily breakdown</h3>'
                            '<table><thead><tr><th>Date</th><th class="num">Total mentions</th>'
                            '<th>Top stock</th></tr></thead><tbody>')
            for day, vals in sorted(daily.items()):
                vals = vals if isinstance(vals, dict) else {}
                sections.append(
                    f'<tr><td>{e(day)}</td>'
                    f'<td class="num">{e(vals.get("total_mentions", 0))}</td>'
                    f'<td>{e(vals.get("top_stock_of_day", "-"))}</td></tr>'
                )
            sections.append('</tbody></table>')

    # ── EGX code details ──────────────────────────────────────────────────────
    sections.append('<h2>EGX code details by channel</h2>')
    if stock_code_details:
        sections.append(
            '<table><thead><tr>'
            '<th>Code</th><th>Company</th><th>Channel</th>'
            '<th class="num">Occurrences</th><th>Extracted details</th>'
            '</tr></thead><tbody>'
        )
        for item in stock_code_details:
            detail_text = "; ".join(
                ", ".join(f"{k}={v}" for k, v in d.items()) for d in item["details"]
            ) or "—"
            sections.append(
                f'<tr>'
                f'<td><strong>{e(item["ticker"])}</strong></td>'
                f'<td>{e(item["company"])}</td>'
                f'<td>{e(item["channel"])}</td>'
                f'<td class="num">{e(item["occurrences"])}</td>'
                f'<td style="font-size:.78rem;color:#94a3b8">{e(detail_text)}</td>'
                f'</tr>'
            )
        sections.append('</tbody></table>')
    else:
        sections.append('<p class="empty">No EGX codes were found in this analysis window.</p>')

    # ── consensus suggestions ─────────────────────────────────────────────────
    sections.append('<h2>Consolidated suggestions</h2>')
    if consensus:
        sections.append(
            '<table><thead><tr>'
            '<th>Code</th><th>Company</th><th>Signal</th>'
            '<th class="num">Channels</th><th class="num">Confidence</th>'
            '<th class="num">Entry</th><th class="num">TP1</th>'
            '<th class="num">TP2</th><th class="num">Stop</th>'
            '</tr></thead><tbody>'
        )
        for item in consensus:
            sections.append(
                f'<tr>'
                f'<td><strong>{e(item["ticker"])}</strong></td>'
                f'<td>{e(item["company"])}</td>'
                f'<td>{badge(item["signal"])}</td>'
                f'<td class="num">{e(item["channel_count"])}</td>'
                f'<td class="num">{item["confidence"]:.0%}</td>'
                f'<td class="num">{e(item["entry"] or "-")}</td>'
                f'<td class="num">{e(item["tp1"] or "-")}</td>'
                f'<td class="num">{e(item["tp2"] or "-")}</td>'
                f'<td class="num">{e(item["stop"] or "-")}</td>'
                f'</tr>'
            )
        sections.append('</tbody></table>')
    else:
        sections.append('<p class="empty">No stock recommendations were detected in this analysis window.</p>')

    body = "\n".join(sections)
    return (
        f'<!doctype html><html lang="en"><head>'
        f'<meta charset="UTF-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>EGX Intelligence Report {generated_at:%Y-%m-%d}</title>'
        f'{css}</head><body>{body}</body></html>'
    )

