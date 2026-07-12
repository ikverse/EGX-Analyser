import base64
import json
from pathlib import Path
from openai import AsyncOpenAI
from app.config import Settings
from app.schemas import AnalysisResult


class AIAnalysisService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.prompt = (Path(__file__).parent / "prompts" / "recommendation.md").read_text(encoding="utf-8")
        self.client = AsyncOpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None

    async def analyze(self, text: str, image_paths: list[str], transcripts: list[str] | None = None) -> AnalysisResult:
        if self.client is None:
            raise RuntimeError("OPENAI_API_KEY is required to analyze messages")
        transcript_text = "\n\n".join(transcripts or [])
        content: list[dict[str, object]] = [{"type": "input_text", "text": f"{self.prompt}\n\nPost:\n{text}\n\nAudio transcript:\n{transcript_text}"}]
        for image_path in image_paths:
            encoded = base64.b64encode(Path(image_path).read_bytes()).decode()
            content.append({"type": "input_image", "image_url": f"data:image/jpeg;base64,{encoded}", "detail": "high"})
        response = await self.client.responses.create(
            model=self.settings.openai_model,
            input=[{"role": "user", "content": content}],
            text={"format": {"type": "json_schema", "name": "analysis_result", "strict": True,
                "schema": AnalysisResult.model_json_schema()}},
        )
        return AnalysisResult.model_validate(json.loads(response.output_text))

    async def transcribe(self, audio_path: str) -> str:
        if self.client is None:
            raise RuntimeError("OPENAI_API_KEY is required to transcribe audio")
        with Path(audio_path).open("rb") as audio:
            response = await self.client.audio.transcriptions.create(model="gpt-4o-mini-transcribe", file=audio)
        return response.text

    async def embed(self, content: str) -> list[float]:
        if self.client is None:
            raise RuntimeError("OPENAI_API_KEY is required to create embeddings")
        response = await self.client.embeddings.create(
            model="text-embedding-3-small", input=content[:24_000]
        )
        return response.data[0].embedding
