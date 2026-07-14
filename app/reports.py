from datetime import datetime, time, timedelta, timezone
from html import escape
import json
import os
from pathlib import Path
from statistics import median
from zoneinfo import ZoneInfo

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
                                             lookback_days: int, consolidated_source: dict | None = None,
                                             consolidated_raw_response: str | None = None,
                                             report_label: str | None = None) -> Report:
        return await self._generate(
            start, end, report_label or f"selected chats ({lookback_days} days)", channel_ids,
            consolidated_source=consolidated_source, consolidated_raw_response=consolidated_raw_response,
        )

    async def _generate(self, start: datetime, end: datetime, report_mode: str,
                        channel_ids: list[int] | None = None, consolidated_source: dict | None = None,
                        consolidated_raw_response: str | None = None) -> Report:
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
        consolidated_source = consolidated_source or _consolidated_source_output(message_rows)
        stock_source_table: list[dict] = []
        client_inquiry_responses: list[dict] = []
        if consolidated_source is not None:
            consensus, stock_code_summary, stock_code_details = _source_driven_tables(consolidated_source)
            stock_source_table = _consolidated_source_table(consolidated_source)
            valid_telegram_message_ids = {str(message.telegram_message_id) for message, _ in message_rows}
            client_inquiry_responses = _client_inquiry_rows(consolidated_source, valid_telegram_message_ids)
            source_counts = _consolidated_source_counts(consolidated_source)
            for channel in channels:
                label = channel.title or channel.handle
                if label not in source_counts:
                    continue
                recommendation_counts[channel.id] = source_counts[label]["recommendations"]
                mention_counts[channel.id] = source_counts[label]["stock_codes"]
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
        display_recommendation_count = sum(recommendation_counts.values())
        lines = [
            f"# EGX Intelligence Report - {generated_at:%Y-%m-%d}", "",
            f"## Overview ({report_mode})", f"- Messages: {len(message_rows)}",
            f"- Recommendations: {display_recommendation_count}", "", "## Chat relevance",
        ]
        lines += [f"- {item['channel']}: {item['status']} | Messages {item['messages']} | Recommendations {item['recommendations']}" for item in channel_results]
        if consolidated_source is not None:
            lines += ["", "## Qwen consolidated analysis", f"- Analysis period: {consolidated_source.get('analysis_period') or report_mode}"]
            lines += ["", "| Rank | Code | Company (EN) | Company (AR) | Source | Dates | Source entries | Entry | TP1 | TP2 | Stop | Support | Resistance | Return % | Risk % | Status |", "| ---: | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |"]
            for row in stock_source_table:
                lines.append(
                    f"| {row['rank'] or '-'} | {row['ticker']} | {row['company']} | {row['company_ar'] or '-'} | "
                    f"{row['source']} | {', '.join(row['source_dates']) or '-'} | {row['source_entries']} | "
                    f"{row['buy_price'] or '-'} | {row['target_1'] or '-'} | {row['target_2'] or '-'} | "
                    f"{row['stop_loss'] or '-'} | {row['support'] or '-'} | {row['resistance'] or '-'} | "
                    f"{row['expected_return_pct'] or '-'} | {row['risk_pct'] or '-'} | {row['status'] or '-'} |"
                )
                if row["analysis_summary_ar"]:
                    lines.append(f"- {row['ticker']} / {row['source']}: {row['analysis_summary_ar']}")
            lines += ["", "## Achieved targets"]
            for item in consolidated_source.get("achieved_targets", []):
                if isinstance(item, dict):
                    lines.append(f"- {item.get('stock_code') or '-'} | {item.get('stock_name_en') or '-'} | {item.get('status_ar') or '-'} | {item.get('date') or '-'} | {item.get('source') or '-'}")
            lines += ["", "## Client inquiry responses (reference only)", "| Code | Company | Source | Date | Customer inquiry | Reply / advice |", "| --- | --- | --- | --- | --- | --- |"]
            for item in client_inquiry_responses:
                lines.append(
                    f"| {item['ticker']} | {item['company']} | {item['source']} | {item['date'] or '-'} | "
                    f"{item['question_summary_ar'] or '-'} | {item['reply_summary_ar'] or item['advice_ar'] or '-'} |"
                )
            if not client_inquiry_responses:
                lines.append("| - | - | - | - | No stock-specific customer inquiry replies were found. | - |")
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
        raw_text_path = directory / f"original-ai-response-{run_id}.txt"
        markdown = "\n".join(lines)
        markdown_path.write_text(markdown, encoding="utf-8")
        html_path.write_text(
            _build_html_report(generated_at, report_mode, message_rows, recommendation_rows,
                               channel_results, consensus, stock_code_details,
                               consolidated_source, stock_source_table, client_inquiry_responses),
            encoding="utf-8",
        )
        raw_lines = [f"EGX Intelligence - Original AI Responses ({generated_at:%Y-%m-%d %H:%M UTC})", ""]
        if consolidated_raw_response:
            raw_lines += ["Consolidated selected-chat analysis", "", consolidated_raw_response, "", "=" * 90, ""]
        else:
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
        report = Report(markdown_path=str(markdown_path), html_path=str(html_path), pdf_path="", summary={
            "mode": report_mode, "consensus": consensus, "message_count": len(message_rows),
            "recommendation_count": display_recommendation_count, "channel_results": channel_results,
            "stock_code_summary": stock_code_summary, "stock_code_details": stock_code_details,
            "stock_source_table": stock_source_table,
            "client_inquiry_responses": client_inquiry_responses,
            "consolidated_source": consolidated_source,
            "analysis_mode": "consolidated_batch" if consolidated_raw_response else "per_message",
            "original_ai_response_text_path": str(raw_text_path),
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


def _consolidated_source_counts(payload: dict) -> dict[str, dict[str, int]]:
    """Count batch findings by the exact source labels supplied to the model."""
    counts: dict[str, dict[str, int]] = {}
    for item in payload.get("top_consolidated_recommendations", []):
        if not isinstance(item, dict):
            continue
        for point in item.get("data_points", []):
            if not isinstance(point, dict) or not point.get("source"):
                continue
            source = str(point["source"])
            values = counts.setdefault(source, {"recommendations": 0, "stock_codes": 0})
            values["recommendations"] += 1
            values["stock_codes"] += 1
    return counts


_SOURCE_VALUE_FIELDS = (
    "buy_price", "target_1", "target_2", "stop_loss", "support", "resistance",
    "expected_return_pct", "risk_pct",
)


def _consolidated_source_table(payload: dict) -> list[dict]:
    """Create one current, readable row for each EGX code and source.

    A source can publish several posts for a stock in the selected window. The row
    keeps the newest non-empty value for each price field and retains all dates so
    the report remains concise without discarding the audit history.
    """
    rows: list[dict] = []
    for item in payload.get("top_consolidated_recommendations", []):
        if not isinstance(item, dict) or not item.get("stock_code"):
            continue
        points_by_source: dict[str, list[dict]] = {}
        for point in item.get("data_points", []):
            if not isinstance(point, dict):
                continue
            source = str(point.get("source") or "Unspecified")
            points_by_source.setdefault(source, []).append(point)
        for source, points in points_by_source.items():
            ordered_points = sorted(points, key=lambda point: str(point.get("date") or ""))
            values: dict[str, object | None] = {field: None for field in _SOURCE_VALUE_FIELDS}
            for point in ordered_points:
                for field in _SOURCE_VALUE_FIELDS:
                    if point.get(field) not in (None, ""):
                        values[field] = point[field]
            dates = list(dict.fromkeys(
                str(point["date"])[:10] for point in ordered_points if point.get("date")
            ))
            rows.append({
                "rank": item.get("rank"),
                "ticker": str(item["stock_code"]).upper(),
                "company": str(item.get("stock_name_en") or item["stock_code"]),
                "company_ar": str(item.get("stock_name_ar") or ""),
                "source": source,
                "source_entries": len(ordered_points),
                "source_dates": dates,
                "latest_date": dates[-1] if dates else None,
                "mention_count": int(item.get("mention_count") or len(ordered_points)),
                "status": str(item.get("status") or ""),
                "analysis_summary_ar": str(item.get("analysis_summary_ar") or ""),
                **values,
            })
    return sorted(rows, key=lambda row: (int(row["rank"] or 999), row["ticker"], row["source"]))


def _client_inquiry_rows(payload: dict, valid_message_ids: set[str] | None = None) -> list[dict]:
    """Normalize model-extracted customer inquiry replies without promoting them to signals."""
    rows: list[dict] = []
    for item in payload.get("client_inquiry_responses", []):
        if not isinstance(item, dict):
            continue
        ticker = str(item.get("stock_code") or "").strip().upper()
        if not ticker:
            continue
        source_message_id = str(item.get("source_message_id") or item.get("telegram_message_id") or "").strip()
        source_excerpt = str(item.get("source_excerpt") or "").strip()
        if valid_message_ids is not None and (source_message_id not in valid_message_ids or not source_excerpt):
            continue
        rows.append({
            "ticker": ticker,
            "company": str(item.get("stock_name_en") or ticker),
            "company_ar": str(item.get("stock_name_ar") or ""),
            "source": str(item.get("source") or "Unspecified"),
            "date": str(item.get("date") or "")[:10] or None,
            "source_message_id": source_message_id or None,
            "source_excerpt": source_excerpt or None,
            "question_summary_ar": str(item.get("question_summary_ar") or ""),
            "reply_summary_ar": str(item.get("reply_summary_ar") or ""),
            "current_trend_ar": str(item.get("current_trend_ar") or ""),
            "last_price": item.get("last_price"),
            "support": item.get("support"),
            "resistance": item.get("resistance"),
            "advice_ar": str(item.get("advice_ar") or ""),
            "alternate_scenario_ar": str(item.get("alternate_scenario_ar") or ""),
        })
    return sorted(rows, key=lambda row: (row["ticker"], row["source"], row["date"] or ""))


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
    stock_source_table: list[dict],
    client_inquiry_responses: list[dict],
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

        if stock_source_table:
            sections.append(
                '<table><thead><tr>'
                '<th>Rank</th><th>Code</th><th>Company (EN)</th><th>Company (AR)</th>'
                '<th>Source</th><th>Dates</th><th class="num">Entries</th><th>Status</th>'
                '<th class="num">Entry</th><th class="num">TP1</th><th class="num">TP2</th>'
                '<th class="num">Stop loss</th><th class="num">Support</th><th class="num">Resistance</th>'
                '<th class="num">Return %</th><th class="num">Risk %</th>'
                '</tr></thead><tbody>'
            )
            for row in stock_source_table:
                sections.append(
                    f'<tr>'
                    f'<td class="num">{e(row["rank"] or "-")}</td>'
                    f'<td><strong>{e(row["ticker"])}</strong></td>'
                    f'<td>{e(row["company"])}</td>'
                    f'<td class="ar">{e(row["company_ar"])}</td>'
                    f'<td>{e(row["source"])}</td>'
                    f'<td>{e(", ".join(row["source_dates"]) or "-")}</td>'
                    f'<td class="num">{e(row["source_entries"])}</td>'
                    f'<td>{badge(row["status"] or "HOLD")}</td>'
                    f'<td class="num">{e(row["buy_price"] or "-")}</td>'
                    f'<td class="num">{e(row["target_1"] or "-")}</td>'
                    f'<td class="num">{e(row["target_2"] or "-")}</td>'
                    f'<td class="num">{e(row["stop_loss"] or "-")}</td>'
                    f'<td class="num">{e(row["support"] or "-")}</td>'
                    f'<td class="num">{e(row["resistance"] or "-")}</td>'
                    f'<td class="num">{e(row["expected_return_pct"] or "-")}</td>'
                    f'<td class="num">{e(row["risk_pct"] or "-")}</td>'
                    f'</tr>'
                )
            sections.append('</tbody></table>')

        if client_inquiry_responses:
            sections.append('<h3>Client inquiry responses (reference only)</h3>'
                            '<p>These replies are deliberately excluded from active recommendations.</p>'
                            '<table><thead><tr><th>Code</th><th>Company</th><th>Source</th><th>Date</th>'
                            '<th>Customer inquiry</th><th>Reply / advice</th></tr></thead><tbody>')
            for row in client_inquiry_responses:
                sections.append(
                    f'<tr><td><strong>{e(row["ticker"])}</strong></td><td>{e(row["company"])}</td>'
                    f'<td>{e(row["source"])}</td><td>{e(row["date"] or "-")}</td>'
                    f'<td class="ar">{e(row["question_summary_ar"] or "-")}</td>'
                    f'<td class="ar">{e(row["reply_summary_ar"] or row["advice_ar"] or "-")}</td></tr>'
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

