import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from openai import AsyncOpenAI
from app.config import Settings
from app.content_updates import ContentUpdateService
from app.schemas import AnalysisResult


@dataclass(frozen=True)
class AnalysisOutcome:
    result: AnalysisResult
    raw_response: str


_OUTPUT_CONTRACT = """Return only one JSON object in this consolidated EGX report structure:
- analysis_period: string describing the covered dates.
- top_consolidated_recommendations: ranked array. Each item has stock_code, stock_name_en, stock_name_ar, mention_count, rank, status, analysis_summary_ar, and data_points.
- data_points: array for each stock. Each item has date, source, buy_price, target_1, target_2, stop_loss, support, resistance, expected_return_pct, and risk_pct.
- achieved_targets: array with stock_code, stock_name_en, status_ar, date, and source.
- text_based_categories: object with most_important_stocks, trading_stocks, and watchlist_stocks arrays. Each array item has stock_code, stock_name_en, and stock_name_ar.
- daily_breakdown: object keyed by date; each item has total_mentions and top_stock_of_day.
Use English EGX ticker codes in stock_code. Keep unavailable values as null. Do not invent price levels or targets."""


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

    async def analyze_consolidated(self, messages: list[dict[str, Any]], analysis_period: str) -> AnalysisOutcome:
        """Analyze one fresh, selected-chat window in a single model request."""
        if not messages:
            empty = {
                "analysis_period": analysis_period,
                "top_consolidated_recommendations": [],
                "achieved_targets": [],
                "text_based_categories": {
                    "most_important_stocks": [], "trading_stocks": [], "watchlist_stocks": [],
                },
                "daily_breakdown": {},
            }
            return AnalysisOutcome(result=_analysis_result_from_payload(empty), raw_response=json.dumps(empty))

        parts = [
            "Selected Telegram chat data follows. Analyze the complete set as one consolidated EGX window.",
            f"Analysis period: {analysis_period}",
            "Use each SOURCE exactly as written below in every data_points[].source value. "
            "Do not treat a source label as a stock recommendation by itself.",
        ]
        image_paths: list[str] = []
        for item in messages:
            source = str(item.get("source") or "Unknown chat")
            timestamp = str(item.get("published_at") or "")
            telegram_id = str(item.get("telegram_message_id") or "")
            text = str(item.get("text") or "[No text]")
            transcripts = item.get("transcripts") if isinstance(item.get("transcripts"), list) else []
            parts.extend([
                "", f"--- MESSAGE | SOURCE: {source} | DATE: {timestamp} | TELEGRAM_ID: {telegram_id} ---",
                text,
            ])
            if transcripts:
                parts.append("Audio transcript:\n" + "\n".join(str(value) for value in transcripts if value))
            for index, image_path in enumerate(item.get("image_paths") or [], start=1):
                parts.append(f"Image {index} for this message follows.")
                image_paths.append(str(image_path))
        return await self._analyze_prompt("\n".join(parts), image_paths)

    async def _analyze_prompt(self, source_data: str, image_paths: list[str]) -> AnalysisOutcome:
        if self.client is None:
            raise RuntimeError("An API key is required for the selected AI provider")
        analysis_prompt = self.settings.analysis_instructions.strip() or self.prompt
        prompt = f"{analysis_prompt}\n\n{_OUTPUT_CONTRACT}\n\n{source_data}"
        if self.settings.ai_provider != "openai":
            content: list[dict[str, object]] = [{"type": "text", "text": prompt}]
            for image_path in image_paths:
                encoded = base64.b64encode(Path(image_path).read_bytes()).decode()
                content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}})
            response_format: dict[str, object] = {"type": "json_object"}
            response = await self.client.chat.completions.create(
                model=self.settings.openai_model,
                messages=[{"role": "user", "content": content}],
                response_format=response_format,
            )
            output = response.choices[0].message.content or "{}"
            output = output.removeprefix("```json").removesuffix("```").strip()
            return AnalysisOutcome(result=_analysis_result_from_payload(json.loads(output)), raw_response=output)

        content = [{"type": "input_text", "text": prompt}]
        for image_path in image_paths:
            encoded = base64.b64encode(Path(image_path).read_bytes()).decode()
            content.append({"type": "input_image", "image_url": f"data:image/jpeg;base64,{encoded}", "detail": "high"})
        response = await self.client.responses.create(
            model=self.settings.openai_model,
            input=[{"role": "user", "content": content}],
            text={"format": {"type": "json_object"}},
        )
        return AnalysisOutcome(
            result=_analysis_result_from_payload(json.loads(response.output_text)), raw_response=response.output_text
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
