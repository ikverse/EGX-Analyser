import base64
import hashlib
import io
import json
import mimetypes
from dataclasses import dataclass, field
import re
from pathlib import Path
from time import perf_counter
from typing import Any

from openai import AsyncOpenAI

from app.analysis_validation import normalize_consolidated_output
from app.channel_names import clean_channel_name
from app import source_date_gate
from app.config import Settings
from app.entry_points import normalize_entry_point
from app.prompt_customization import prompt_customization_block
from app.recommendation_notes import remove_unsupported_targets
from app.recommendation_signal import recommendation_signal
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


_CORE_ANALYSIS_PROTOCOL = """You are the EGX Intelligence consolidation engine.
Apply the canonical prompt gates in their numbered order. Do not repair, advance, infer, or borrow dates, identities, evidence, image references, or prices. Managed Include phrases extend recommendation wording only; they never override exclusions, date eligibility, or destination separation. Assign each Telegram ID to recommendations, inquiries, or exclusion, never more than one. Delete invalid rows before grouping or summarizing. Return only the canonical JSON object."""

_MAX_IMAGE_EDGE = 2_048
_OPTIMIZE_IMAGE_OVER_BYTES = 1_500_000


def _build_analysis_prompt(base_prompt: str, source_data: str) -> str:
    phrase_guidance = prompt_customization_block()
    managed_guidance = f"\n\n{phrase_guidance}" if phrase_guidance else ""
    return f"{base_prompt.rstrip()}{managed_guidance}\n\n## Runtime source data\n\n{source_data}"


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


def _write_provider_request_trace(
    directory: Path,
    prompt: str,
    prepared_images: list[tuple[str, int, int, bool]],
    prompt_metadata: dict[str, Any] | None = None,
) -> None:
    """Save the final text and optimized image bytes supplied to a provider."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "provider-prompt.txt").write_text(prompt, encoding="utf-8")
    if prompt_metadata is not None:
        (directory / "prompt-metadata.json").write_text(
            json.dumps(prompt_metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
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
                "rank": str(rank_item.get("rank") or ""),
                "mention_count": str(mention_count or ""), "stock_name_ar": str(rank_item.get("stock_name_ar") or ""),
                "data_points": json.dumps(data_points, ensure_ascii=False),
            },
            "confidence": _confidence(min(1.0, 0.5 + _number(mention_count or 0) / 10)),
        })
        signal = recommendation_signal(data_points)
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


_SCHEMA_MARKER = re.compile(r"<!--\s*EGX_PROMPT_SCHEMA:\s*(\d+)\s*-->")


# Small enough that the model keeps every reference in a request straight, large enough that the
# prompt is not repeated more often than it needs to be.
IMAGES_PER_CHUNK = 8


@dataclass
class _Chunk:
    """One extraction request: whole messages, and the image references they carry."""

    parts: list[tuple[str, str | None]] = field(default_factory=list)
    image_paths: list[str] = field(default_factory=list)
    references: list[int] = field(default_factory=list)


@dataclass
class _ChunkAnswer:
    extracted: list[dict[str, Any]] = field(default_factory=list)
    excluded: list[dict[str, Any]] = field(default_factory=list)
    inquiries: list[dict[str, Any]] = field(default_factory=list)
    cited: set[int] = field(default_factory=set)


@dataclass
class _Harvest:
    """What every extraction request together said."""

    extracted: list[dict[str, Any]] = field(default_factory=list)
    excluded: list[dict[str, Any]] = field(default_factory=list)
    inquiries: list[dict[str, Any]] = field(default_factory=list)
    unaccounted: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    request_count: int = 0
    request_milliseconds: int = 0
    retried: bool = False

    def adopt(self, answer: "_ChunkAnswer") -> None:
        self.extracted.extend(answer.extracted)
        self.excluded.extend(answer.excluded)
        self.inquiries.extend(answer.inquiries)


def _chunk_parts(
    interleaved_parts: list[tuple[str, str | None]],
    block_starts: list[int],
    part_references: dict[int, int],
    images_per_chunk: int = IMAGES_PER_CHUNK,
) -> list[_Chunk]:
    """
    Splits a run into requests small enough for the model to keep track of.

    A message is never split across two of them. Its caption sits in the same block as its photo and
    carries the one word that separates a new call from a follow-up on an old one, so the two have
    to be judged together. A single message holding more images than the limit gets its own
    oversized chunk for the same reason.
    """
    if not interleaved_parts:
        return []
    bounds = list(block_starts) or [0]
    blocks: list[list[int]] = []
    for position, first in enumerate(bounds):
        last = bounds[position + 1] if position + 1 < len(bounds) else len(interleaved_parts)
        blocks.append(list(range(first, last)))
    if bounds[0] > 0:
        blocks.insert(0, list(range(0, bounds[0])))

    chunks: list[_Chunk] = []
    current = _Chunk()
    for block in blocks:
        own = [part_references[index] for index in block if index in part_references]
        if current.parts and len(current.references) + len(own) > images_per_chunk:
            chunks.append(current)
            current = _Chunk()
        for index in block:
            part = interleaved_parts[index]
            current.parts.append(part)
            if index in part_references:
                current.references.append(part_references[index])
                if part[1]:
                    current.image_paths.append(part[1])
    if current.parts:
        chunks.append(current)
    return chunks


def _drop_sources_from_another_session(payload: dict[str, Any], target_trading_date: str) -> list[str]:
    """
    Removes occurrences whose printed date is not the session being analysed.

    The prompt says the same thing and has been ignored, so the check is arithmetic here. A stock
    left with no surviving occurrence goes with them: there is nothing left to recommend.
    """
    target = source_date_gate.parse(target_trading_date)
    if target is None:
        return []
    warnings: list[str] = []
    kept: list[dict[str, Any]] = []
    for stock in payload.get("top_consolidated_recommendations") or []:
        if not isinstance(stock, dict):
            continue
        points = [point for point in stock.get("data_points") or [] if isinstance(point, dict)]
        surviving = [
            point for point in points
            if source_date_gate.accepts(point.get("visible_source_date"), target)
        ]
        dropped = len(points) - len(surviving)
        if dropped:
            warnings.append(
                f"{stock.get('stock_code') or 'A stock'} lost {dropped} occurrence(s) printed with "
                f"another session's date."
            )
        if points and not surviving:
            continue
        stock["data_points"] = surviving
        stock["mention_count"] = len(surviving)
        kept.append(stock)
    for rank, stock in enumerate(kept, start=1):
        stock["rank"] = rank
    payload["top_consolidated_recommendations"] = kept
    return warnings


def _prompt_metadata(path: Path) -> dict[str, object]:
    """Identifies the prompt a run used, so a report can be traced back to a tag."""
    marker = _SCHEMA_MARKER.search(path.read_text(encoding="utf-8")[:512])
    return {
        "filename": path.name,
        "source": "bundled",
        "schema_version": int(marker.group(1)) if marker else None,
    }


class AIAnalysisService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        # Prompts ship with the build and only with the build. A downloaded pack meant the running
        # app could be using a prompt the repository had never seen, which is invisible in a bug
        # report and impossible to reproduce from a tag.
        prompt_directory = Path(__file__).parent / "prompts"
        single_path = prompt_directory / "recommendation.md"
        consolidated_path = prompt_directory / "consolidated_recommendation.md"
        self.prompt = single_path.read_text(encoding="utf-8")
        self.consolidated_prompt = consolidated_path.read_text(encoding="utf-8")
        consolidation_path = prompt_directory / "consolidation.md"
        self.consolidation_prompt = consolidation_path.read_text(encoding="utf-8")
        self.prompt_metadata = _prompt_metadata(single_path)
        self.consolidated_prompt_metadata = _prompt_metadata(consolidated_path)
        self.consolidation_prompt_metadata = _prompt_metadata(consolidation_path)
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
        parts = [
            "RUNTIME CONTEXT",
            f"ANALYSIS_PERIOD: {analysis_period}",
            f"TARGET_DATE: {target_trading_date}",
            "SOURCE ITEMS FOLLOW. Apply the canonical prompt independently to each item.",
        ]
        image_paths: list[str] = []
        image_references: dict[str, int] = {}
        source_image_references: dict[int, dict[str, str]] = {}
        image_visual_signatures: list[tuple[bytes, int]] = []
        text_references: dict[str, str] = {}
        transcript_references: dict[str, str] = {}
        interleaved_parts: list[tuple[str, str | None]] = []
        # Where each message begins, and the reference each image part carries. A chunk is cut
        # on message boundaries so a caption never travels without its photo.
        block_starts: list[int] = []
        part_references: dict[int, int] = {}
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
            block_starts.append(len(interleaved_parts))
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
                part_references[len(interleaved_parts)] = reference
                interleaved_parts.append((image_label, path))
                image_paths.append(path)
        chunks = _chunk_parts(interleaved_parts, block_starts, part_references)
        harvest = await self._extract_in_chunks(
            chunks, source_prelude, metrics, trace_directory, source_image_references,
        )
        payload = await self._consolidate(
            harvest, analysis_period, target_trading_date, metrics, trace_directory,
        )
        if trace_directory is not None:
            (trace_directory / "provider-ai-response.json").write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8",
            )
        warnings = list(harvest.warnings)
        warnings += normalize_consolidated_output(payload, messages, source_image_references)
        warnings += _drop_sources_from_another_session(payload, target_trading_date)
        normalized_response = json.dumps(payload, ensure_ascii=False)
        run_metrics = dict(metrics)
        run_metrics["prompt_assembly_ms"] = round((perf_counter() - prompt_assembly_started) * 1000)
        run_metrics["model_request_count"] = harvest.request_count
        run_metrics["model_requests_total_ms"] = harvest.request_milliseconds
        run_metrics["images_sent"] = len(image_paths)
        run_metrics["images_unaccounted"] = len(harvest.unaccounted)
        return AnalysisOutcome(
            result=_analysis_result_from_payload(payload),
            raw_response=normalized_response,
            input_metrics=run_metrics,
            validation_warnings=warnings,
            correction_attempted=harvest.retried,
            retry_audit={
                "attempted": harvest.retried,
                "status": "chunk_retried" if harvest.retried else "not_required",
                "excluded_rows": warnings,
                "final_validation_warnings": warnings,
                "final_response_path": "consolidated-ai-response.json",
                "unaccounted_images": harvest.unaccounted,
            },
            source_image_references=source_image_references,
        )

    async def _extract_in_chunks(
        self,
        chunks: list["_Chunk"],
        source_prelude: str,
        metrics: dict[str, int],
        trace_directory: Path | None,
        source_image_references: dict[int, dict[str, str]],
    ) -> "_Harvest":
        """
        Reads the sources a few images at a time.

        One request per run asked the model to keep every image straight at once, and it could not:
        over thirty images it cited IMAGE_REF 4 for a card that was image 15, so a report showed an
        excluded past-recommendations table beside a valid call while the card it had actually read
        appeared nowhere. References stay global rather than restarting at 1 in each request - the
        duplicate-image notices point at earlier references, and renumbering would leave them
        dangling - but a request now carries few enough images for the model to hold them.
        """
        harvest = _Harvest()
        for chunk in chunks:
            answer = await self._read_chunk(chunk, source_prelude, metrics, trace_directory, harvest)
            missing = [reference for reference in chunk.references if reference not in answer.cited]
            if missing:
                # Retry this chunk alone, not the run. Its second answer replaces the first, or a
                # chunk that merely forgot one image would contribute every other row twice.
                harvest.retried = True
                second = await self._read_chunk(
                    chunk, source_prelude, metrics, trace_directory, harvest,
                    correction=(
                        "Your previous response left IMAGE_REF "
                        + ", ".join(str(reference) for reference in missing)
                        + " out of both `extracted` and `excluded`. Return the full response again, "
                        "accounting for every IMAGE_REF supplied."
                    ),
                )
                if len(second.cited) > len(answer.cited):
                    answer = second
            harvest.adopt(answer)
            for reference in chunk.references:
                if reference not in answer.cited:
                    origin = source_image_references.get(reference) or {}
                    harvest.unaccounted.append({
                        "image_ref": reference,
                        "source": origin.get("source"),
                        "source_message_id": origin.get("source_message_id"),
                    })
        if harvest.unaccounted:
            harvest.warnings.append(
                f"{len(harvest.unaccounted)} image(s) were neither recommended nor excluded."
            )
        return harvest

    async def _read_chunk(
        self,
        chunk: "_Chunk",
        source_prelude: str,
        metrics: dict[str, int],
        trace_directory: Path | None,
        harvest: "_Harvest",
        correction: str | None = None,
    ) -> "_ChunkAnswer":
        prelude = source_prelude
        if chunk.references:
            prelude += (
                "\nIMAGE_REF values in this request are "
                + ", ".join(str(reference) for reference in chunk.references)
                + ". Cite only those numbers."
            )
        if correction:
            prelude += "\n" + correction
        outcome = await self._analyze_prompt(
            prelude,
            chunk.image_paths,
            dict(metrics),
            trace_directory,
            _CORE_ANALYSIS_PROTOCOL,
            interleaved_parts=chunk.parts,
            base_prompt=getattr(self, "consolidated_prompt", self.prompt),
            prompt_metadata=getattr(
                self, "consolidated_prompt_metadata", getattr(self, "prompt_metadata", None),
            ),
        )
        harvest.request_count += 1
        harvest.request_milliseconds += int(outcome.input_metrics.get("model_request_ms", 0))
        answer = _ChunkAnswer()
        try:
            payload = json.loads(outcome.raw_response)
        except (ValueError, TypeError):
            harvest.warnings.append("A source chunk returned no readable JSON.")
            return answer
        allowed = set(chunk.references)
        for key, destination in (
            ("extracted", answer.extracted),
            ("excluded", answer.excluded),
            ("client_inquiry_responses", answer.inquiries),
        ):
            for row in payload.get(key) or []:
                if not isinstance(row, dict):
                    continue
                reference = row.get("source_image_ref")
                if isinstance(reference, int):
                    if reference in allowed:
                        answer.cited.add(reference)
                    else:
                        # Names an image this request never carried, so it is dropped rather than
                        # read as whatever image happens to sit at that number.
                        harvest.warnings.append(
                            f"Dropped a citation of IMAGE_REF {reference}, which was not in that request."
                        )
                        row["source_image_ref"] = None
                destination.append(row)
        return answer

    async def _consolidate(
        self,
        harvest: "_Harvest",
        analysis_period: str,
        target_trading_date: str,
        metrics: dict[str, int],
        trace_directory: Path | None,
    ) -> dict[str, Any]:
        """
        Ranks what extraction found, then rebuilds the document the rest of the app already reads.

        No images are sent. Ranking is the one judgement that needs the whole run in view, which is
        exactly why it is separated from reading, where seeing everything is what caused the model
        to lose its place.
        """
        ranked: dict[str, Any] = {}
        if harvest.extracted:
            request = "\n".join([
                "RUNTIME CONTEXT",
                f"ANALYSIS_PERIOD: {analysis_period}",
                f"TARGET_DATE: {target_trading_date}",
                "",
                "EXTRACTED OCCURRENCES:",
                json.dumps(harvest.extracted, ensure_ascii=False),
            ])
            outcome = await self._analyze_prompt(
                request,
                [],
                dict(metrics),
                trace_directory,
                _CORE_ANALYSIS_PROTOCOL,
                base_prompt=self.consolidation_prompt,
                prompt_metadata=self.consolidation_prompt_metadata,
            )
            harvest.request_count += 1
            harvest.request_milliseconds += int(outcome.input_metrics.get("model_request_ms", 0))
            try:
                ranked = json.loads(outcome.raw_response)
            except (ValueError, TypeError):
                harvest.warnings.append("Consolidation returned no readable JSON.")
        return {
            "analysis_period": analysis_period,
            "top_consolidated_recommendations": ranked.get("top_consolidated_recommendations") or [],
            "achieved_targets": [],
            "excluded": harvest.excluded,
            "client_inquiry_responses": harvest.inquiries,
            "text_based_categories": ranked.get("text_based_categories") or {
                "most_important_stocks": [], "trading_stocks": [], "watchlist_stocks": [],
            },
            "daily_breakdown": {},
        }

    async def _analyze_prompt(self, source_data: str, image_paths: list[str], input_metrics: dict[str, int] | None = None,
                              trace_directory: Path | None = None, system_instruction: str | None = None,
                              interleaved_parts: list[tuple[str, str | None]] | None = None,
                              base_prompt: str | None = None,
                              prompt_metadata: dict[str, Any] | None = None) -> AnalysisOutcome:
        if self.client is None:
            raise RuntimeError("An API key is required for the selected AI provider")
        prompt = _build_analysis_prompt(base_prompt or self.prompt, source_data)
        selected_prompt_metadata = prompt_metadata or getattr(self, "prompt_metadata", None)
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
            _write_provider_request_trace(
                trace_directory, trace_prompt, prepared_images, selected_prompt_metadata,
            )
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
                # Reading a price off a card has one right answer, printed in the image. Sampling
                # only ever moves away from it, and it is what produced English company names that
                # changed between runs of the same source.
                temperature=0,
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
            temperature=0,
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
