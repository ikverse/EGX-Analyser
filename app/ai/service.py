import base64
import json
from pathlib import Path
from typing import Any
from openai import AsyncOpenAI
from app.config import Settings
from app.content_updates import ContentUpdateService
from app.schemas import AnalysisResult


_OUTPUT_CONTRACT = """Return only one JSON object with exactly these top-level arrays:
- recommendations: each actionable trade must include company_name, ticker, signal (BUY, SELL, or HOLD), entry, target, target_2, stop_loss, reason, risk_level, time_horizon, indicators, and confidence from 0 to 1.
- stock_mentions: every detected EGX code must include ticker, company_name, context, table_data, and confidence from 0 to 1.
- image_observations: text observations from images.
Use ticker, never code. Use signal, never action. A ticker is an EGX trading code such as COMI, not an Arabic or English company name. Use null when an optional value is unavailable. Do not create a recommendation unless there is an explicit trade signal."""


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

    async def analyze(self, text: str, image_paths: list[str], transcripts: list[str] | None = None) -> AnalysisResult:
        if self.client is None:
            raise RuntimeError("An API key is required for the selected AI provider")
        transcript_text = "\n\n".join(transcripts or [])
        analysis_prompt = self.settings.analysis_instructions.strip() or self.prompt
        prompt = f"{analysis_prompt}\n\n{_OUTPUT_CONTRACT}\n\nPost:\n{text}\n\nAudio transcript:\n{transcript_text}"
        if self.settings.ai_provider != "openai":
            content: list[dict[str, object]] = [{"type": "text", "text": prompt}]
            for image_path in image_paths:
                encoded = base64.b64encode(Path(image_path).read_bytes()).decode()
                content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}})
            response_format: dict[str, object] = {"type": "json_schema", "json_schema": {
                "name": "analysis_result", "strict": True, "schema": analysis_output_schema(),
            }}
            if self.settings.ai_provider == "qwen":
                response_format = {"type": "json_object"}
            response = await self.client.chat.completions.create(
                model=self.settings.openai_model,
                messages=[{"role": "user", "content": content}],
                response_format=response_format,
            )
            output = response.choices[0].message.content or "{}"
            output = output.removeprefix("```json").removesuffix("```").strip()
            return _analysis_result_from_payload(json.loads(output))

        content = [{"type": "input_text", "text": prompt}]
        for image_path in image_paths:
            encoded = base64.b64encode(Path(image_path).read_bytes()).decode()
            content.append({"type": "input_image", "image_url": f"data:image/jpeg;base64,{encoded}", "detail": "high"})
        response = await self.client.responses.create(
            model=self.settings.openai_model,
            input=[{"role": "user", "content": content}],
            text={"format": {"type": "json_schema", "name": "analysis_result", "strict": True,
                "schema": analysis_output_schema()}},
        )
        return _analysis_result_from_payload(json.loads(response.output_text))

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
