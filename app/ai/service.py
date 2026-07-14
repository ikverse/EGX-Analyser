import base64
import hashlib
import io
import json
import mimetypes
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any
from openai import AsyncOpenAI
from app.config import Settings
from app.content_updates import ContentUpdateService
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


_OUTPUT_CONTRACT = """Return only one JSON object in this consolidated EGX report structure:
- analysis_period: string describing the covered dates.
- top_consolidated_recommendations: ranked array. Each item has stock_code, stock_name_en, stock_name_ar, mention_count, rank, status, analysis_summary_ar, and data_points.
- data_points: array for each stock. Each item has date, effective_date_basis, source, buy_price, target_1, target_2, stop_loss, support, resistance, expected_return_pct, and risk_pct. effective_date_basis is one of explicit_date, t_plus_1, next_session, or tomorrow.
- achieved_targets: array with stock_code, stock_name_en, status_ar, date, and source.
- client_inquiry_responses: array for stock-specific replies to customer/member questions. Each item has stock_code, stock_name_en, stock_name_ar, source, date, source_message_id, source_excerpt, question_summary_ar, reply_summary_ar, current_trend_ar, last_price, buy_price, target_1, target_2, stop_loss, support, resistance, advice_ar, and alternate_scenario_ar. Include source_message_id and source_excerpt when present in the source data.
- text_based_categories: object with most_important_stocks, trading_stocks, and watchlist_stocks arrays. Each array item has stock_code, stock_name_en, and stock_name_ar.
- daily_breakdown: object keyed by date; each item has total_mentions and top_stock_of_day.
Use English EGX ticker codes in stock_code. Keep unavailable values as null. Do not invent price levels or targets."""

_MAX_IMAGE_EDGE = 2_048
_OPTIMIZE_IMAGE_OVER_BYTES = 1_500_000
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
                                "entry": _number(item.get("entry")), "target": _number(item.get("target") or item.get("tp1")),
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
        summary = rank_item.get("analysis_summary_ar")
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
                "entry": _number(point.get("buy_price")), "target": _number(point.get("target_1")),
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
        }.get(settings.ai_provider)
        self.client = AsyncOpenAI(api_key=settings.ai_api_key, base_url=base_url) if settings.ai_api_key else None

    async def analyze(self, text: str, image_paths: list[str], transcripts: list[str] | None = None) -> AnalysisOutcome:
        transcript_text = "\n\n".join(transcripts or [])
        return await self._analyze_prompt(
            f"Post:\n{text}\n\nAudio transcript:\n{transcript_text}", image_paths
        )

    async def analyze_consolidated(self, messages: list[dict[str, Any]], analysis_period: str,
                                   target_trading_date: str) -> AnalysisOutcome:
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

        parts = [
            "Selected Telegram chat data follows. Analyze the complete set as one consolidated EGX window.",
            f"Analysis period: {analysis_period}",
            f"Target effective trading date: {target_trading_date}.",
            "Only include active, actionable EGX BUY recommendations intended for the target effective trading date. "
            "A candidate is valid only when the selected text, image, or audio contains a visible/explicit date that resolves "
            "to the target date, or explicitly says T+1, next session, or tomorrow relative to its Cairo message timestamp. "
            "A dated same-day buy signal without T+1/next-session/tomorrow wording is valid only for that same day and MUST be excluded. "
            "Undated stock tables, watchlists, charts, and price levels MUST be excluded; never infer their effective date from "
            "the Telegram posting time alone. data_points[].date must be the effective recommendation date, not the post date. "
            "Set data_points[].effective_date_basis to explicit_date when the effective date is written, or to t_plus_1, next_session, "
            "or tomorrow when that phrase determines the effective date. "
            "Exclude recommendations whose effective date is missing, ambiguous, already past, or different from the target date.",
            "OUTPUT PRIORITY: First extract every valid dated recommendation table, chart, image, text, or audio signal that is "
            "intended for the target effective date into top_consolidated_recommendations. For each source row, preserve entry, "
            "TP1, TP2, stop loss, support, and resistance whenever visible. If any qualifying dated source table exists, the main "
            "recommendations array must contain its stock rows; do this before creating client_inquiry_responses.",
            "Extract only explicit recommendations with a stock code and actionable price/risk levels such as buy/entry zone, "
            "TP1, TP2, stop loss, support, or resistance. Images may use different source layouts: identify headings rather than "
            "assuming column positions. For example, Arabic headings may include منطقة الشراء, هدف أول, هدف ثاني, إيقاف الخسارة, "
            "الدعم, المقاومة, or إشارة تداول - شراء. Keep each source's values separate.",
            "Strictly ignore advertisements, links, disclaimers, greetings, general market commentary, corporate/economic news, "
            "memes, and stock mentions without a dated actionable recommendation. Do not turn news into a trading signal.",
            "IMPORTANT — client/member inquiry replies are reference information, not main recommendations. Classify them from "
            "their own text, image, or audio context, including phrases such as 'ردًا على استفسارات عملائنا', 'ردا على استفسارات عملائنا', "
            "'رد على استفسار', or 'استفسارات العملاء'. Never classify a normal table, chart, photo, or signal as an inquiry because "
            "the same source/channel posted an inquiry elsewhere. A valid dated buy table remains a main recommendation. "
            "A marked message that clearly answers a member/customer question about a particular stock must NEVER appear in "
            "top_consolidated_recommendations, achieved_targets, or text_based_categories. Instead place one clean, "
            "stock-specific record in client_inquiry_responses. Preserve its source, date, entry, TP1, TP2, stop loss, levels, trend, advice, and "
            "alternative scenario when explicitly present. Include source_message_id equal to the supporting TELEGRAM_ID and an "
            "exact source_excerpt whenever available. Do not invent a buy recommendation from an inquiry reply.",
            "Use each SOURCE exactly as written below in every data_points[].source value. "
            "Do not treat a source label as a stock recommendation by itself.",
        ]
        image_paths: list[str] = []
        image_references: dict[str, int] = {}
        text_references: dict[str, str] = {}
        transcript_references: dict[str, str] = {}
        metrics = {
            "logical_message_count": len(messages),
            "logical_image_count": 0,
            "duplicate_image_count": 0,
            "reused_text_count": 0,
            "reused_transcript_count": 0,
        }
        for item in messages:
            source = str(item.get("source") or "Unknown chat")
            timestamp = str(item.get("published_at") or "")
            telegram_id = str(item.get("telegram_message_id") or "")
            original_text = str(item.get("text") or "")
            text, reused_text = _content_reference(original_text, text_references, "TEXT_REF", telegram_id)
            metrics["reused_text_count"] += int(reused_text)
            transcripts = item.get("transcripts") if isinstance(item.get("transcripts"), list) else []
            parts.extend([
                "", f"--- MESSAGE | SOURCE: {source} | DATE: {timestamp} | TELEGRAM_ID: {telegram_id} ---",
                text or "[No text]",
            ])
            if transcripts:
                original_transcript = "\n".join(str(value) for value in transcripts if value).strip()
                transcript, reused_transcript = _content_reference(
                    original_transcript, transcript_references, "AUDIO_REF", telegram_id,
                )
                metrics["reused_transcript_count"] += int(reused_transcript)
                if transcript:
                    parts.append("Audio transcript:\n" + transcript)
            for index, image_path in enumerate(item.get("image_paths") or [], start=1):
                metrics["logical_image_count"] += 1
                path = str(image_path)
                try:
                    digest = _image_digest(path)
                except OSError:
                    parts.append(f"Image {index} is unavailable and was not sent.")
                    continue
                reference = image_references.get(digest)
                if reference is not None:
                    metrics["duplicate_image_count"] += 1
                    parts.append(
                        f"Image {index} is an exact duplicate of IMAGE_REF {reference}. "
                        "Reuse its visible content while retaining this source/date occurrence."
                    )
                    continue
                reference = len(image_paths) + 1
                image_references[digest] = reference
                parts.append(f"Image {index} for this message is IMAGE_REF {reference}; it follows below.")
                image_paths.append(path)
        return await self._analyze_prompt("\n".join(parts), image_paths, metrics)

    async def _analyze_prompt(self, source_data: str, image_paths: list[str], input_metrics: dict[str, int] | None = None) -> AnalysisOutcome:
        if self.client is None:
            raise RuntimeError("An API key is required for the selected AI provider")
        analysis_prompt = self.settings.analysis_instructions.strip() or self.prompt
        prompt = f"{analysis_prompt}\n\n{_OUTPUT_CONTRACT}\n\n{source_data}"
        metrics = dict(input_metrics or {})
        prepared_images = [_prepared_image_data_url(path) for path in image_paths]
        metrics.update({
            "unique_image_count": len(prepared_images),
            "original_image_bytes": sum(item[1] for item in prepared_images),
            "sent_image_bytes": sum(item[2] for item in prepared_images),
            "optimized_image_count": sum(int(item[3]) for item in prepared_images),
            "prompt_characters": len(prompt),
        })
        request_started = perf_counter()
        if self.settings.ai_provider != "openai":
            content: list[dict[str, object]] = [{"type": "text", "text": prompt}]
            for data_url, _, _, _ in prepared_images:
                content.append({"type": "image_url", "image_url": {"url": data_url}})
            response_format: dict[str, object] = {"type": "json_object"}
            response = await self.client.chat.completions.create(
                model=self.settings.openai_model,
                messages=[{"role": "user", "content": content}],
                response_format=response_format,
            )
            metrics["model_request_ms"] = round((perf_counter() - request_started) * 1000)
            output = response.choices[0].message.content or "{}"
            output = output.removeprefix("```json").removesuffix("```").strip()
            return AnalysisOutcome(result=_analysis_result_from_payload(json.loads(output)), raw_response=output, input_metrics=metrics)

        content = [{"type": "input_text", "text": prompt}]
        for data_url, _, _, _ in prepared_images:
            content.append({"type": "input_image", "image_url": data_url, "detail": "high"})
        response = await self.client.responses.create(
            model=self.settings.openai_model,
            input=[{"role": "user", "content": content}],
            text={"format": {"type": "json_object"}},
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
