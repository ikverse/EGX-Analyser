import base64
import json
from pathlib import Path
from typing import Any
from openai import AsyncOpenAI
from app.config import Settings
from app.schemas import AnalysisResult


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


class AIAnalysisService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.prompt = (Path(__file__).parent / "prompts" / "recommendation.md").read_text(encoding="utf-8")
        base_url = {
            "openrouter": "https://openrouter.ai/api/v1",
            "huggingface": "https://router.huggingface.co/v1",
        }.get(settings.ai_provider)
        self.client = AsyncOpenAI(api_key=settings.ai_api_key, base_url=base_url) if settings.ai_api_key else None

    async def analyze(self, text: str, image_paths: list[str], transcripts: list[str] | None = None) -> AnalysisResult:
        if self.client is None:
            raise RuntimeError("An API key is required for the selected AI provider")
        transcript_text = "\n\n".join(transcripts or [])
        prompt = f"{self.prompt}\n\nPost:\n{text}\n\nAudio transcript:\n{transcript_text}"
        if self.settings.ai_provider != "openai":
            content: list[dict[str, object]] = [{"type": "text", "text": prompt}]
            for image_path in image_paths:
                encoded = base64.b64encode(Path(image_path).read_bytes()).decode()
                content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}})
            response = await self.client.chat.completions.create(
                model=self.settings.openai_model,
                messages=[{"role": "user", "content": content}],
                response_format={"type": "json_schema", "json_schema": {
                    "name": "analysis_result", "strict": True, "schema": analysis_output_schema(),
                }},
            )
            output = response.choices[0].message.content or "{}"
            output = output.removeprefix("```json").removesuffix("```").strip()
            return AnalysisResult.model_validate(json.loads(output))

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
        return AnalysisResult.model_validate(json.loads(response.output_text))

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
