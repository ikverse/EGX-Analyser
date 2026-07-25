import base64
import hashlib
import io
import json
import mimetypes
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from time import perf_counter
from typing import Any

from openai import AsyncOpenAI

from app.analysis_validation import normalize_consolidated_output
from app.channel_names import clean_channel_name
from app.config import Settings
from app.content_updates import ContentUpdateService
from app.entry_points import normalize_entry_point
from app.prompt_customization import prompt_customization_block
from app.recommendation_notes import remove_unsupported_targets
from app.schemas import AnalysisResult

try:
    from PIL import Image as PillowImage
    from PIL import ImageOps
except ImportError:  # The desktop sidecar retains the original image when Pillow is unavailable.
    PillowImage = None
    ImageOps = None


@dataclass(frozen=True)
class AnalysisOutcome:
    result: AnalysisResult
    raw_response: str
    input_metrics: dict[str, int] = field(default_factory=dict)
    validation_warnings: list[str] = field(default_factory=list)
    correction_attempted: bool = False
    retry_audit: dict[str, Any] = field(default_factory=dict)
    source_image_references: dict[int, dict[str, str]] = field(default_factory=dict)


_OUTPUT_CONTRACT = """Return only one JSON object in this consolidated EGX report structure:
- analysis_period: string describing the covered dates.
- top_consolidated_recommendations: ranked array. Each item has stock_code, stock_name_en, stock_name_ar, mention_count, rank, status, notes_summary, analysis_summary_ar, and data_points. notes_summary must be written in concise Arabic and generated only after grouping every occurrence of that exact stock. Merge duplicate literal T+1 occurrences and semantically equivalent سهم مراقبة / stock-to-watch wording, preserve genuinely different insights, and never copy full source messages or image text. Never treat translated, paraphrased, or inferred next-day wording as T+1. Keep ticker codes and standard market abbreviations such as T+1 as written. analysis_summary_ar remains optional for backward compatibility.
- data_points: array for each stock. Each item has date, effective_date_basis, source_message_id, source_image_ref, recommendation_evidence, recommendation_type, buy_price, buy_price_low, buy_price_high, target_1, target_2, stop_loss, support, resistance, expected_return_pct, risk_pct, and notes_ar. recommendation_evidence is a short exact phrase visibly present in that same source message/image which includes the stock identity and explicit recommendation context such as توصية شراء, منطقة الشراء, إشارة تداول - شراء, سهم تحت المراقبة, or a stock-to-watch heading. Never invent or paraphrase this evidence. Extract only the first two take-profit levels. Ignore TP3, target 3, third target, مستهدف ثالث, الهدف الثالث, and every later target; never return them in any field or summary. source_message_id must exactly equal the supporting TELEGRAM_ID. Do not return a source or channel name; the application restores it locally from source_message_id. recommendation_type is buy or sell. notes_ar is a concise Arabic note for narrative/chart recommendations that do not use a table; otherwise it is null. effective_date_basis is explicit_date, t_plus_1, or watching. For watching, timing_evidence must quote the exact same-stock Arabic or English watch wording. For a single entry, use buy_price only. For an explicit entry range, set buy_price to null and preserve the exact left and right values in buy_price_low and buy_price_high; never average, round, infer, or swap them.
- achieved_targets: array with stock_code, stock_name_en, status_ar, date, and source_message_id.
- client_inquiry_responses: array for stock-specific replies to customer/member questions. Each item has stock_code, stock_name_en, stock_name_ar, date, source_message_id, source_image_ref, source_excerpt, question_summary_ar, reply_summary_ar, current_trend_ar, last_price, buy_price, buy_price_low, buy_price_high, target_1, target_2, stop_loss, support, resistance, advice_ar, and alternate_scenario_ar. Do not return a source or channel name. Include the supporting source_message_id and source_excerpt when present in the source data. Use the same exact single-entry/range rules as data_points.
- text_based_categories: object with most_important_stocks, trading_stocks, and watchlist_stocks arrays. Each array item has stock_code, stock_name_en, and stock_name_ar.
- daily_breakdown: object keyed by date; each item has total_mentions and top_stock_of_day.
Use English EGX ticker codes in stock_code. Keep unavailable values as null. Do not invent price levels or targets."""

_CORE_ANALYSIS_PROTOCOL = """You are the EGX Intelligence consolidation engine. The mandatory two-list contract and JSON structure in the user request are non-negotiable. Managed include/exclude phrase guidance extends recommendation recognition only; it must never override list separation, date eligibility, source message IDs, or the JSON structure. Client inquiry replies must only appear in client_inquiry_responses, never in top_consolidated_recommendations. Return JSON only."""

_IMAGE_REFERENCE_CONTRACT = """IMAGE TRACEABILITY: Every image is placed directly after its immutable IMAGE_REF metadata block. For every data point whose evidence comes from an image, return source_image_ref as that exact IMAGE_REF integer. For text-only or audio-only evidence, return source_image_ref as null. Never copy an IMAGE_REF, stock identity, recommendation, date, or values from a neighboring image. A source_image_ref is supporting traceability only; an image must still satisfy every recommendation-context and date rule before it can be included."""

_DATE_EVIDENCE_CONTRACT = """DATE TRACEABILITY: Every returned image, text, or audio data point must contain visible_source_date, date_evidence, and timing_evidence. For image-derived data, visible_source_date is the date visibly written in that same image, normalized as YYYY-MM-DD, and date_evidence is a short exact visible date phrase copied from it. For explicit_date, timing_evidence must be null. For t_plus_1, timing_evidence must be the exact contiguous literal token T+1 copied from that same stock recommendation context; matching is case-insensitive, so t+1 also qualifies. No translation, synonym, paraphrase, or inferred next-day meaning qualifies. جلسة الغد, تداول الغد, الجلسة القادمة, الجلسة التالية, next session, next trading day, tomorrow, and similar wording are not T+1. For watching, timing_evidence must be the exact same-stock phrase meaning سهم تحت المراقبة, تحت المراقبة, سهم للمراقبة, watching, under watch, stock to watch, or a clear semantic equivalent. A watching result may use the supplied MESSAGE DATE as its source date only for text or voice-note transcripts that have explicit same-stock watch wording but no internal date; in that case normalize MESSAGE DATE into visible_source_date and copy the supplied MESSAGE DATE timestamp into date_evidence. Never use MESSAGE DATE to date an image. The phrase `يسمح بالتداول على سعر الشراء المحدد` and wording that only permits trading within a percentage around the specified entry price describe entry-price execution tolerance, not T+1, tomorrow, the next trading day, the next session, or Watching. Never use such wording as timing_evidence, never label the recommendation t_plus_1 or watching because of it, and never move its visible date to the following day. Never infer, manufacture, translate, or borrow date/timing evidence from another image, another stock, or merely from the fact that a source date precedes the target date."""

_MAX_IMAGE_EDGE = 2_048
_OPTIMIZE_IMAGE_OVER_BYTES = 1_500_000


def _build_analysis_prompt(base_prompt: str, source_data: str) -> str:
    phrase_guidance = prompt_customization_block()
    managed_guidance = f"\n\n{phrase_guidance}" if phrase_guidance else ""
    return (
        f"{base_prompt}{managed_guidance}\n\n{_OUTPUT_CONTRACT}\n\n"
        f"{_IMAGE_REFERENCE_CONTRACT}\n\n{_DATE_EVIDENCE_CONTRACT}\n\n{source_data}"
    )


def _content_reference(value: str, references: dict[str, str], label: str, telegram_id: str) -> tuple[str, bool]:
    """Reuse only byte-identical text/transcripts while retaining the message occurrence."""
    text = value.strip()
    if not text:
        return "", False
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    original_id = references.get(digest)
    if original_id:
        return (
            f"[{label} is byte-for-byte identical to TELEGRAM_ID {original_id}. "
            "Keep this message as a separate source/date occurrence.]",
            True,
        )
    references[digest] = telegram_id
    return text, False


def _image_digest(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _image_visual_signature(path: str) -> bytes | None:
    """Return normalized pixels for conservative near-duplicate repost detection."""
    if PillowImage is None or ImageOps is None:
        return None
    try:
        with PillowImage.open(path) as image:
            return ImageOps.exif_transpose(image).convert("RGB").resize((64, 64)).tobytes()
    except (OSError, ValueError):
        return None


def _visually_same_image(first: bytes | None, second: bytes | None) -> bool:
    if first is None or second is None or len(first) != len(second) or not first:
        return False
    total_difference = sum(abs(left - right) for left, right in zip(first, second, strict=True))
    return total_difference / len(first) <= 1.5


def _prepared_image_data_url(path: str) -> tuple[str, int, int, bool]:
    """Optimize only oversized images and retain the original bytes when optimization is not beneficial."""
    image_path = Path(path)
    raw = image_path.read_bytes()
    original_size = len(raw)
    content = raw
    mime_type = mimetypes.guess_type(image_path.name)[0] or "image/jpeg"
    optimized = False
    if PillowImage is not None and ImageOps is not None:
        try:
            with PillowImage.open(io.BytesIO(raw)) as image:
                normalized = ImageOps.exif_transpose(image)
                oversized = max(normalized.size) > _MAX_IMAGE_EDGE or original_size > _OPTIMIZE_IMAGE_OVER_BYTES
                if oversized:
                    normalized = normalized.convert("RGB")
                    normalized.thumbnail((_MAX_IMAGE_EDGE, _MAX_IMAGE_EDGE))
                    candidate = io.BytesIO()
                    normalized.save(candidate, format="JPEG", quality=92, optimize=True, progressive=True)
                    compressed = candidate.getvalue()
                    if len(compressed) < original_size:
                        content = compressed
                        mime_type = "image/jpeg"
                        optimized = True
        except (OSError, ValueError):
            pass
    encoded = base64.b64encode(content).decode()
    return f"data:{mime_type};base64,{encoded}", original_size, len(content), optimized


def _write_provider_request_trace(directory: Path, prompt: str,
                                  prepared_images: list[tuple[str, int, int, bool]]) -> None:
    """Save the final text and optimized image bytes supplied to a provider."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "provider-prompt.txt").write_text(prompt, encoding="utf-8")
    image_directory = directory / "sent-images"
    image_directory.mkdir(exist_ok=True)
    manifest: list[dict[str, object]] = []
    for index, (data_url, original_bytes, sent_bytes, optimized) in enumerate(prepared_images, start=1):
        header, encoded = data_url.split(",", 1)
        mime_type = header.removeprefix("data:").split(";", 1)[0]
        extension = mimetypes.guess_extension(mime_type) or ".bin"
        filename = f"image-{index}{extension}"
        (image_directory / filename).write_bytes(base64.b64decode(encoded))
        manifest.append({
            "reference": index, "file": (Path("sent-images") / filename).as_posix(), "mime_type": mime_type,
            "original_bytes": original_bytes, "sent_bytes": sent_bytes, "optimized": optimized,
        })
    (directory / "sent-images.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def analysis_output_schema() -> dict[str, Any]:
    schema = AnalysisResult.model_json_schema()

    def make_strict(value: Any) -> None:
        if isinstance(value, dict):
            if value.get("type") == "object":
                value["additionalProperties"] = False
                if isinstance(value.get("properties"), dict):
                    value["required"] = list(value["properties"])
            for child in value.values():
                make_strict(child)
        elif isinstance(value, list):
            for child in value:
                make_strict(child)

    make_strict(schema)
    return schema


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None


def _confidence(value: Any) -> float:
    number = _number(value)
    return min(1.0, max(0.0, number if number is not None else 0.5))


def _signal(value: Any) -> str | None:
    normalized = str(value or "").strip().upper()
    aliases = {"BUY": "BUY", "PURCHASE": "BUY", "شراء": "BUY", "SELL": "SELL", "بيع": "SELL", "HOLD": "HOLD", "احتفاظ": "HOLD"}
    return aliases.get(normalized)


def _analysis_result_from_payload(payload: Any) -> AnalysisResult:
    if not isinstance(payload, dict):
        raise ValueError("The AI provider did not return a JSON object")
    if isinstance(payload.get("top_consolidated_recommendations"), list):
        return _analysis_result_from_consolidated_payload(payload)
    mentions: list[dict[str, Any]] = []
    for item in payload.get("stock_mentions", []):
        if not isinstance(item, dict):
            continue
        ticker = str(item.get("ticker") or item.get("code") or "").strip()
        if not ticker:
            continue
        table_data = item.get("table_data") if isinstance(item.get("table_data"), dict) else {}
        mentions.append({"ticker": ticker, "company_name": item.get("company_name") or item.get("company") or item.get("name"),
                         "context": item.get("context") or item.get("reason"),
                         "table_data": {str(key): str(value) for key, value in table_data.items()},
                         "confidence": _confidence(item.get("confidence"))})
    recommendations: list[dict[str, Any]] = []
    for item in payload.get("recommendations", []):
        if not isinstance(item, dict):
            continue
        ticker = str(item.get("ticker") or item.get("code") or "").strip() or None
        signal = _signal(item.get("signal") or item.get("action"))
        company_name = str(item.get("company_name") or item.get("company") or item.get("name") or ticker or "").strip()
        if not signal or not company_name:
            continue
        recommendations.append({"company_name": company_name, "ticker": ticker, "signal": signal,
                                "entry": normalize_entry_point(item.get("entry"), item.get("entry_low"), item.get("entry_high"))[0],
                                "entry_low": normalize_entry_point(item.get("entry"), item.get("entry_low"), item.get("entry_high"))[1],
                                "entry_high": normalize_entry_point(item.get("entry"), item.get("entry_low"), item.get("entry_high"))[2],
                                "target": _number(item.get("target") or item.get("tp1")),
                                "target_2": _number(item.get("target_2") or item.get("tp2")), "stop_loss": _number(item.get("stop_loss") or item.get("stop")),
                                "reason": item.get("reason"), "risk_level": item.get("risk_level"),
                                "time_horizon": item.get("time_horizon"),
                                "indicators": [str(value) for value in item.get("indicators", [])] if isinstance(item.get("indicators"), list) else [],
                                "confidence": _confidence(item.get("confidence"))})
    observations = [str(value) for value in payload.get("image_observations", []) if isinstance(value, (str, int, float))]
    return AnalysisResult.model_validate({"recommendations": recommendations, "stock_mentions": mentions,
                                          "image_observations": observations})


def _analysis_result_from_consolidated_payload(payload: dict[str, Any]) -> AnalysisResult:
    recommendations: list[dict[str, Any]] = []
    mentions: list[dict[str, Any]] = []
    for rank_item in payload.get("top_consolidated_recommendations", []):
        if not isinstance(rank_item, dict):
            continue
        ticker = str(rank_item.get("stock_code") or "").strip().upper()
        if not ticker:
            continue
        company_name = str(rank_item.get("stock_name_en") or ticker).strip()
        mention_count = rank_item.get("mention_count")
        summary = remove_unsupported_targets(rank_item.get("notes_summary") or rank_item.get("analysis_summary_ar"))
        data_points = rank_item.get("data_points") if isinstance(rank_item.get("data_points"), list) else []
        mentions.append({
            "ticker": ticker, "company_name": company_name, "context": summary,
            "table_data": {
                "rank": str(rank_item.get("rank") or ""), "status": str(rank_item.get("status") or ""),
                "mention_count": str(mention_count or ""), "stock_name_ar": str(rank_item.get("stock_name_ar") or ""),
                "data_points": json.dumps(data_points, ensure_ascii=False),
            },
            "confidence": _confidence(min(1.0, 0.5 + _number(mention_count or 0) / 10)),
        })
        signal = "BUY" if str(rank_item.get("status") or "").lower() == "active" else "HOLD"
        for point in data_points or [{}]:
            if not isinstance(point, dict):
                continue
            recommendations.append({
                "company_name": company_name, "ticker": ticker, "signal": signal,
                "entry": normalize_entry_point(point.get("buy_price"), point.get("buy_price_low"), point.get("buy_price_high"))[0],
                "entry_low": normalize_entry_point(point.get("buy_price"), point.get("buy_price_low"), point.get("buy_price_high"))[1],
                "entry_high": normalize_entry_point(point.get("buy_price"), point.get("buy_price_low"), point.get("buy_price_high"))[2],
                "target": _number(point.get("target_1")),
                "target_2": _number(point.get("target_2")), "stop_loss": _number(point.get("stop_loss")),
                "reason": summary, "risk_level": f"{point.get('risk_pct')}%" if point.get("risk_pct") is not None else None,
                "time_horizon": point.get("date"), "indicators": [],
                "confidence": _confidence(min(1.0, 0.5 + _number(mention_count or 0) / 10)),
            })
    return AnalysisResult.model_validate({"recommendations": recommendations, "stock_mentions": mentions,
                                          "image_observations": []})


class AIAnalysisService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        prompt_path = ContentUpdateService(settings).file_path("recommendation.md")
        self.prompt = (prompt_path or Path(__file__).parent / "prompts" / "recommendation.md").read_text(encoding="utf-8")
        base_url = {
            "qwen": settings.qwen_base_url,
            "openrouter": "https://openrouter.ai/api/v1",
            "huggingface": "https://router.huggingface.co/v1",
            "ollama": f"{settings.ollama_base_url.rstrip('/').removesuffix('/v1')}/v1",
        }.get(settings.ai_provider)
        self.client = AsyncOpenAI(api_key=settings.ai_api_key, base_url=base_url) if settings.ai_api_key else None

    async def analyze(self, text: str, image_paths: list[str], transcripts: list[str] | None = None) -> AnalysisOutcome:
        transcript_text = "\n\n".join(transcripts or [])
        return await self._analyze_prompt(
            f"Post:\n{text}\n\nAudio transcript:\n{transcript_text}", image_paths
        )

    async def analyze_consolidated(self, messages: list[dict[str, Any]], analysis_period: str,
                                   target_trading_date: str, trace_directory: Path | None = None) -> AnalysisOutcome:
        """Analyze one fresh, selected-chat window in a single model request."""
        if not messages:
            empty = {
                "analysis_period": analysis_period,
                "top_consolidated_recommendations": [],
                "achieved_targets": [],
                "client_inquiry_responses": [],
                "text_based_categories": {
                    "most_important_stocks": [], "trading_stocks": [], "watchlist_stocks": [],
                },
                "daily_breakdown": {},
            }
            return AnalysisOutcome(result=_analysis_result_from_payload(empty), raw_response=json.dumps(empty))

        prompt_assembly_started = perf_counter()
        previous_target_date = (date.fromisoformat(target_trading_date) - timedelta(days=1)).isoformat()
        parts = [
            "Selected Telegram chat data follows. Analyze the complete set as one consolidated EGX window.",
            f"Analysis period: {analysis_period}",
            f"Target effective trading date: {target_trading_date}.",
            "FIRST perform an internal two-list classification. LIST 1 contains only stock-specific client/customer inquiry replies, "
            "such as replies headed or contextualized as 'ردًا على استفسارات عملائنا', 'ردا على استفسارات عملائنا', 'رد على استفسار', "
            "or 'استفسارات العملاء'. LIST 2 contains every other cleaned, valid EGX recommendation. Do not return either internal list; "
            "use LIST 1 only for client_inquiry_responses and LIST 2 only for top_consolidated_recommendations. "
            "Discard all irrelevant material before this classification: advertisements, links, disclaimers, greetings, news, memes, "
            "general commentary, non-EGX material, and stock discussion without an explicit actionable recommendation or explicit "
            "same-stock Watching classification and an eligible source date. Only include active, actionable EGX BUY or SELL "
            "recommendations, plus explicit same-stock Watching recommendations, from LIST 2 intended for the target effective trading date. "
            "A candidate is valid only when its selected text, image, or audio has a visible/explicit effective date equal to the target date. "
            f"The T+1 prior-date exception is a visible date of {previous_target_date} together with the exact contiguous literal token "
            "T+1 in the same stock recommendation context. Match case-insensitively, so t+1 also qualifies. No translation, synonym, "
            "paraphrase, or inferred next-day meaning qualifies. جلسة الغد, تداول الغد, الجلسة القادمة, الجلسة التالية, next session, "
            "next trading day, tomorrow, and similar wording are not T+1. The literal token must explicitly apply to that exact "
            "recommendation; a generic caption, disclaimer, neighboring image, Telegram posting date, or merely being one day earlier "
            "does not qualify. For that exception, output "
            "data_points[].date as the target date and data_points[].effective_date_basis as t_plus_1. "
            "WATCHING TIMING CATEGORY: A source explicitly classifying the exact stock as سهم تحت المراقبة, تحت المراقبة, "
            "سهم للمراقبة, watching, under watch, stock to watch, or a clear semantic equivalent is a valid Watching recommendation. "
            "This applies equally to image text, ordinary text messages, and voice-note transcripts. Set data_points[].date to the target "
            "date, data_points[].effective_date_basis to watching, and timing_evidence to the exact same-stock watch phrase. Preserve "
            "conditional actions such as الشراء باختراق / buy on breakout and every explicit entry, TP1, TP2, stop loss, return, and risk value. "
            "In an image, a watch heading may govern the ticker or stock name visibly placed directly beneath it in the same recommendation "
            "card even when they are not on one text line; never transfer that heading to a neighboring image or unrelated stock. "
            "For an image, require a visible image date inside the supplied analysis period and never substitute the Telegram timestamp. "
            "For a text message or voice-note transcript with no internal date, the supplied MESSAGE DATE may establish the source date "
            "only for this explicit Watching classification; normalize it into visible_source_date and copy that supplied timestamp "
            "into date_evidence. Watching never means T+1 and must never be returned as t_plus_1. "
            "The phrase 'يسمح بالتداول على سعر الشراء المحدد' and any wording that merely allows a percentage deviation around the "
            "specified entry price are execution-tolerance instructions, not timing instructions. They never qualify as T+1 or "
            "Watching or timing_evidence and must not shift the visible recommendation date forward. "
            "Undated stock tables, generic watchlists, charts, and price levels without explicit same-stock Watching wording MUST be "
            "excluded; never infer their effective date from the Telegram posting time alone. data_points[].date must be the effective "
            "recommendation date, not the post date. "
            "Set data_points[].effective_date_basis to explicit_date only when the visible source date equals the target date, or "
            "to t_plus_1 only for the exact same-context literal T+1 exception, or to watching only for explicit same-stock watch wording. "
            "Exclude recommendations whose effective date is missing, ambiguous, already past, or different from the target date.",
            "OUTPUT PRIORITY: First extract every valid dated recommendation table, chart, image, text, or audio signal from LIST 2 that is "
            "intended for the target effective date into top_consolidated_recommendations. For each source row, preserve entry, "
            "TP1, TP2, stop loss, support, and resistance whenever visible. If any qualifying dated source table exists, the main "
            "recommendations array must contain its stock rows; do this before creating client_inquiry_responses.",
            "TAKE-PROFIT LIMIT: Extract and return only TP1 and TP2 (target_1 and target_2). Completely ignore TP3, target 3, "
            "third target, take profit 3, مستهدف ثالث, الهدف الثالث, and any fourth or later target. Do not mention ignored "
            "targets in notes_summary, analysis_summary_ar, notes_ar, or any other output field.",
            "Entry values require special care. A single entry is buy_price only. If a source explicitly shows an entry range in "
            "Arabic or English (for example 24.50-25.20, 24.50–25.20, 'from 24.50 to 25.20', or 'من 24.50 إلى 25.20'), "
            "return buy_price=null, buy_price_low=the exact left value, and buy_price_high=the exact right value. Never average, "
            "round, infer, reverse, or confuse entry values with stop loss, targets, support, resistance, or current price.",
            "Extract only explicit recommendations with a stock code and a visible recommendation cue such as توصية, شراء, بيع, "
            "منطقة الشراء, إشارة تداول, سهم تحت المراقبة, تحت المراقبة, سهم للمراقبة, recommendation, buy, sell, "
            "watching, under watch, stock to watch, or entry zone. Explicit same-stock watch wording is sufficient context for the "
            "Watching category even when the action is conditional rather than immediate. Support, "
            "resistance, stop loss, current price, targets, liquidity ranking, sector ranking, or an important-stocks list alone NEVER "
            "makes a recommendation and must be excluded. Images may use different source layouts: identify headings rather than "
            "assuming column positions. For example, Arabic headings may include منطقة الشراء, هدف أول, هدف ثاني, إيقاف الخسارة, "
            "الدعم, المقاومة, or إشارة تداول - شراء. For every included point, copy a short exact visible phrase containing both the "
            "stock identity and explicit recommendation context into recommendation_evidence. Keep each source's values separate and "
            "never copy values or evidence from one image/message into another source_message_id.",
            "A dated chart/photo with narrative stock guidance but no table is still a data point: extract every visible level and put "
            "a concise Arabic explanation of its guidance into data_points[].notes_ar. Keep each source's values separate. "
            "Strictly ignore advertisements, links, disclaimers, greetings, general market commentary, corporate/economic news, "
            "memes, and stock mentions without a dated actionable recommendation. Do not turn news into a trading signal.",
            "Image-only messages are intentionally included for visual review. If an image itself identifies a recommendation as previous, "
            "past, achieved, target-hit, or no longer actionable, exclude it completely: do not include it in "
            "top_consolidated_recommendations, achieved_targets, client_inquiry_responses, or text_based_categories.",
            "IMPORTANT — client/member inquiry replies are reference information, not main recommendations. Classify them from "
            "their own text, image, or audio context, including phrases such as 'ردًا على استفسارات عملائنا', 'ردا على استفسارات عملائنا', "
            "'رد على استفسار', or 'استفسارات العملاء'. Never classify a normal table, chart, photo, or signal as an inquiry because "
            "the same source/channel posted an inquiry elsewhere. A valid dated buy table remains a main recommendation. "
            "A marked message that clearly answers a member/customer question about a particular stock must NEVER appear in "
            "top_consolidated_recommendations, achieved_targets, or text_based_categories. Instead place one clean, "
            "stock-specific record in client_inquiry_responses. Preserve its date, entry, TP1, TP2, stop loss, levels, trend, advice, and "
            "alternative scenario when explicitly present. Include source_message_id equal to the supporting TELEGRAM_ID and an "
            "exact source_excerpt whenever available. Do not invent a buy recommendation from an inquiry reply.",
            "Client/member inquiry replies belong to LIST 1 only; they are reference information, never main recommendations. "
            "Return only the exact supporting TELEGRAM_ID as data_points[].source_message_id and in every client_inquiry_responses item. "
            "Do not return channel names or source labels; the application restores them locally. Before returning JSON, internally assign every "
            "supporting TELEGRAM_ID to exactly one destination: LIST 1 IDs only in client_inquiry_responses, LIST 2 IDs only "
            "in top_consolidated_recommendations, or excluded. Never use one TELEGRAM_ID in both arrays, and never place a "
            "LIST 1 TELEGRAM_ID in a recommendation data point.",
            "NOTES SUMMARY: Group all LIST 2 findings by exact stock_code before writing notes_summary. Produce exactly one concise, "
            "factual Arabic notes_summary per stock from all of that stock's occurrences, regardless of source. The prose must be Arabic; "
            "keep only ticker codes, numbers, and standard market abbreviations such as T+1 in their normal form. Merge duplicate literal "
            "T+1 findings, but never treat next-session translations, synonyms, paraphrases, or inferred next-day meanings as T+1. Treat "
            "سهم تحت المراقبة/سهم للمراقبة/stock-to-watch wording as one Watching insight after date eligibility is established. Watching "
            "remains a distinct Timing category and never broadens or substitutes for the literal T+1 date exception. "
            "Mention each meaning once. Preserve distinct insights such as T+1, watchlist status, entry range, targets, stop loss, and "
            "risk warnings. Do not paste, enumerate, or paraphrase whole source messages, captions, tables, or image text. Keep "
            "source_message_id and per-message values only in data_points for traceability. Keep notes_summary under 60 Arabic words.",
            "MANDATORY DATE ELIGIBILITY SELF-AUDIT BEFORE RETURNING JSON: Re-read every proposed data point against its own source image "
            "or message. Keep explicit_date only when visible_source_date equals the target date and date_evidence exactly supports it; "
            "timing_evidence must then be null. Keep t_plus_1 only when visible_source_date equals the stated prior date and non-empty "
            "timing_evidence exactly copies the contiguous literal token T+1, case-insensitively, from that same stock recommendation "
            "context. Reject every translation, synonym, paraphrase, or inferred next-day meaning. "
            "Keep watching only when non-empty timing_evidence exactly quotes same-stock watch wording from that image, text, or voice-note "
            "transcript. For image-based Watching require the visible image date to fall inside the supplied analysis period. For text or "
            "voice-note Watching with no internal date, normalize the supplied MESSAGE DATE into visible_source_date and copy its timestamp "
            "into date_evidence. Return the effective "
            "data point date as the target date and never relabel Watching as t_plus_1. "
            "Explicitly reject 'يسمح بالتداول على سعر الشراء المحدد' and entry-price percentage-tolerance wording as timing_evidence. "
            "If any required evidence is absent, belongs to another image/stock, or conflicts with the selected basis, remove the data "
            "point completely before ranking, categorizing, counting mentions, or writing notes_summary.",
        ]
        image_paths: list[str] = []
        image_references: dict[str, int] = {}
        source_image_references: dict[int, dict[str, str]] = {}
        image_visual_signatures: list[tuple[bytes, int]] = []
        text_references: dict[str, str] = {}
        transcript_references: dict[str, str] = {}
        interleaved_parts: list[tuple[str, str | None]] = []
        source_prelude = "\n".join(parts)
        metrics = {
            "logical_message_count": len(messages),
            "logical_image_count": 0,
            "duplicate_image_count": 0,
            "near_duplicate_image_count": 0,
            "reused_text_count": 0,
            "reused_transcript_count": 0,
        }
        for item in messages:
            source = clean_channel_name(item.get("source"))
            timestamp = str(item.get("published_at") or "")
            telegram_id = str(item.get("telegram_message_id") or "")
            original_text = str(item.get("text") or "")
            text, reused_text = _content_reference(original_text, text_references, "TEXT_REF", telegram_id)
            metrics["reused_text_count"] += int(reused_text)
            transcripts = item.get("transcripts") if isinstance(item.get("transcripts"), list) else []
            message_parts = [
                f"--- MESSAGE | CHANNEL: {source} | DATE: {timestamp} | TELEGRAM_ID: {telegram_id} ---",
                text or "[No text]",
            ]
            if transcripts:
                original_transcript = "\n".join(str(value) for value in transcripts if value).strip()
                transcript, reused_transcript = _content_reference(
                    original_transcript, transcript_references, "AUDIO_REF", telegram_id,
                )
                metrics["reused_transcript_count"] += int(reused_transcript)
                if transcript:
                    message_parts.append("Audio transcript:\n" + transcript)
            interleaved_parts.append(("\n".join(message_parts), None))
            for index, image_path in enumerate(item.get("image_paths") or [], start=1):
                metrics["logical_image_count"] += 1
                path = str(image_path)
                try:
                    digest = _image_digest(path)
                except OSError:
                    interleaved_parts.append((f"Image {index} is unavailable and was not sent.", None))
                    continue
                reference = image_references.get(digest)
                visual_signature = _image_visual_signature(path)
                similar_reference = None
                if reference is None and visual_signature is not None:
                    similar_reference = next((
                        existing_reference for signature, existing_reference in image_visual_signatures
                        if _visually_same_image(visual_signature, signature)
                    ), None)
                if reference is not None:
                    metrics["duplicate_image_count"] += 1
                    interleaved_parts.append((
                        f"Image {index} is an exact byte-for-byte duplicate of IMAGE_REF {reference}. "
                        "Do not create another data point for this repost; the raw input trace preserves its source occurrence.",
                        None,
                    ))
                    continue
                reference = len(image_paths) + 1
                image_references[digest] = reference
                source_image_references[reference] = {
                    "path": path,
                    "source": source,
                    "source_message_id": telegram_id,
                    "image_index": str(index),
                }
                if visual_signature is not None:
                    image_visual_signatures.append((visual_signature, reference))
                if similar_reference is not None:
                    metrics["near_duplicate_image_count"] += 1
                    image_label = (
                        f"IMAGE_REF {reference} | CHANNEL: {source} | TELEGRAM_ID: {telegram_id} | "
                        f"MESSAGE_IMAGE_INDEX: {index}. The referenced image is immediately below. "
                        f"It visually resembles IMAGE_REF {similar_reference} and may share the same template, but it can contain "
                        "a different ticker, date, recommendation, or trade values. Read it independently and merge the two only "
                        "when their visible stock identity and recommendation details actually match."
                    )
                else:
                    image_label = (
                        f"IMAGE_REF {reference} | CHANNEL: {source} | TELEGRAM_ID: {telegram_id} | "
                        f"MESSAGE_IMAGE_INDEX: {index}. The referenced image is immediately below."
                    )
                interleaved_parts.append((image_label, path))
                image_paths.append(path)
        initial = await self._analyze_prompt(
            source_prelude,
            image_paths,
            metrics,
            trace_directory,
            _CORE_ANALYSIS_PROTOCOL,
            interleaved_parts=interleaved_parts,
        )
        initial_metrics = dict(initial.input_metrics)
        initial_payload = json.loads(initial.raw_response)
        if trace_directory is not None:
            (trace_directory / "provider-ai-response.json").write_text(
                initial.raw_response, encoding="utf-8",
            )
        warnings = normalize_consolidated_output(
            initial_payload, messages, source_image_references,
        )
        normalized_response = json.dumps(initial_payload, ensure_ascii=False)
        initial_metrics["prompt_assembly_ms"] = round((perf_counter() - prompt_assembly_started) * 1000)
        initial_metrics["model_request_count"] = 1
        initial_metrics["model_requests_total_ms"] = initial_metrics.get("model_request_ms", 0)
        return AnalysisOutcome(
            result=_analysis_result_from_payload(initial_payload),
            raw_response=normalized_response,
            input_metrics=initial_metrics,
            validation_warnings=warnings,
            correction_attempted=False,
            retry_audit={
                "attempted": False,
                "status": "not_required",
                "excluded_rows": warnings,
                "final_validation_warnings": warnings,
                "final_response_path": "consolidated-ai-response.json",
            },
            source_image_references=source_image_references,
        )

    async def _analyze_prompt(self, source_data: str, image_paths: list[str], input_metrics: dict[str, int] | None = None,
                              trace_directory: Path | None = None, system_instruction: str | None = None,
                              interleaved_parts: list[tuple[str, str | None]] | None = None) -> AnalysisOutcome:
        if self.client is None:
            raise RuntimeError("An API key is required for the selected AI provider")
        prompt = _build_analysis_prompt(self.prompt, source_data)
        metrics = dict(input_metrics or {})
        image_preparation_started = perf_counter()
        prepared_images = [_prepared_image_data_url(path) for path in image_paths]
        prepared_by_path = dict(zip(image_paths, prepared_images, strict=True))
        trace_prompt = prompt
        if interleaved_parts:
            trace_prompt = "\n\n".join([prompt, *[text for text, _ in interleaved_parts if text]])
        metrics.update({
            "unique_image_count": len(prepared_images),
            "original_image_bytes": sum(item[1] for item in prepared_images),
            "sent_image_bytes": sum(item[2] for item in prepared_images),
            "optimized_image_count": sum(int(item[3]) for item in prepared_images),
            "prompt_characters": len(prompt),
            "image_preparation_ms": round((perf_counter() - image_preparation_started) * 1000),
        })
        if trace_directory is not None:
            trace_write_started = perf_counter()
            _write_provider_request_trace(trace_directory, trace_prompt, prepared_images)
            metrics["provider_trace_write_ms"] = round((perf_counter() - trace_write_started) * 1000)
        request_started = perf_counter()
        if self.settings.ai_provider != "openai":
            content: list[dict[str, object]] = [{"type": "text", "text": prompt}]
            if interleaved_parts:
                for text, image_path in interleaved_parts:
                    if text:
                        content.append({"type": "text", "text": text})
                    if image_path:
                        data_url = prepared_by_path[image_path][0]
                        content.append({"type": "image_url", "image_url": {"url": data_url}})
            else:
                for data_url, _, _, _ in prepared_images:
                    content.append({"type": "image_url", "image_url": {"url": data_url}})
            response_format: dict[str, object] = {"type": "json_object"}
            request_messages: list[dict[str, object]] = []
            if system_instruction:
                request_messages.append({"role": "system", "content": system_instruction})
            request_messages.append({"role": "user", "content": content})
            response = await self.client.chat.completions.create(
                model=self.settings.ai_model,
                messages=request_messages,
                response_format=response_format,
            )
            metrics["model_request_ms"] = round((perf_counter() - request_started) * 1000)
            output = response.choices[0].message.content or "{}"
            output = output.removeprefix("```json").removesuffix("```").strip()
            return AnalysisOutcome(result=_analysis_result_from_payload(json.loads(output)), raw_response=output, input_metrics=metrics)

        content = [{"type": "input_text", "text": prompt}]
        if interleaved_parts:
            for text, image_path in interleaved_parts:
                if text:
                    content.append({"type": "input_text", "text": text})
                if image_path:
                    data_url = prepared_by_path[image_path][0]
                    content.append({"type": "input_image", "image_url": data_url, "detail": "high"})
        else:
            for data_url, _, _, _ in prepared_images:
                content.append({"type": "input_image", "image_url": data_url, "detail": "high"})
        response = await self.client.responses.create(
            model=self.settings.ai_model,
            input=[{"role": "user", "content": content}],
            text={"format": {"type": "json_object"}},
            instructions=system_instruction,
        )
        metrics["model_request_ms"] = round((perf_counter() - request_started) * 1000)
        return AnalysisOutcome(
            result=_analysis_result_from_payload(json.loads(response.output_text)), raw_response=response.output_text,
            input_metrics=metrics,
        )

    async def transcribe(self, audio_path: str) -> str:
        if self.client is None or self.settings.ai_provider != "openai":
            raise RuntimeError("Audio transcription currently requires the OpenAI provider")
        with Path(audio_path).open("rb") as audio:
            response = await self.client.audio.transcriptions.create(model="gpt-4o-mini-transcribe", file=audio)
        return response.text

    async def embed(self, content: str) -> list[float]:
        if self.client is None or self.settings.ai_provider != "openai":
            raise RuntimeError("Semantic search embeddings currently require the OpenAI provider")
        response = await self.client.embeddings.create(
            model="text-embedding-3-small", input=content[:24_000]
        )
        return response.data[0].embedding
