from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

from transcriber.audio import pcm_to_wav
from transcriber.config import TranscriberSettings
from transcriber.context import StageContext

logger = logging.getLogger("nerdearla.transcriber.engine")

# One structured call per segment covers transcription AND translation.
# This is only possible because Carril 3 hands us discrete VAD segments: the
# Live API would be needed for a continuous stream, and it does not support
# structured output. Discrete clips let us keep the schema.
RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "original": {
            "type": "string",
            "description": "Literal transcription in the language spoken.",
        },
        "source_language": {
            "type": "string",
            "description": "ISO code of the spoken language, or 'mixed'.",
        },
        "captions": {
            "type": "array",
            "description": "One entry per requested language.",
            "items": {
                "type": "object",
                "properties": {
                    "lang": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["lang", "text"],
            },
        },
        "preserved_terms": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Technical terms left untranslated on purpose.",
        },
    },
    "required": ["original", "source_language", "captions"],
}

SYSTEM_INSTRUCTION = """You produce live captions for a technology conference in Latin America.

Transcribe the audio literally, then render it in every requested language.

Rules, in priority order:

1. NEVER translate tool, product, language, command or project names. "Spring Boot"
   stays "Spring Boot", not "Bota de Primavera". "kubectl apply" stays as is. When in
   doubt, leave the original.
2. Technical Spanglish is correct usage, not an error. "vamos a deployar el pod" stays
   "vamos a deployar el pod". Do not sanitise it into formal Spanish.
3. Spanish output is neutral Latin American Spanish.
4. Do not add, summarise or explain. If the audio is cut mid-sentence, transcribe it
   cut mid-sentence and do not invent an ending.
5. Do not add final punctuation when the sentence clearly continues.
6. If the audio contains no intelligible speech, return empty strings rather than
   guessing."""


@dataclass(frozen=True)
class SegmentResult:
    original: str
    source_language: str
    captions: dict[str, str] = field(default_factory=dict)
    preserved_terms: tuple[str, ...] = ()

    @property
    def is_silent(self) -> bool:
        return not self.original.strip()


class TranscriptionEngine(Protocol):
    async def process(
        self, pcm: bytes, context: StageContext, is_clause_end: bool
    ) -> SegmentResult: ...


def build_prompt(context: StageContext, languages: list[str], is_clause_end: bool) -> str:
    parts: list[str] = []
    if context.name:
        parts.append(f"Stage: {context.name}")
    if context.session:
        parts.append(f"Talk: {context.session}")
    speakers = context.speaker_names
    if speakers:
        parts.append(f"Speakers (spell these names exactly): {', '.join(speakers)}")

    terms = context.protected_terms()
    if terms:
        # This is the whole point of reading the event agenda up front: the model
        # knows the jargon before the speaker says it.
        parts.append(
            "Terminology for this talk. Spell these exactly and never translate them: "
            + ", ".join(terms)
        )

    parts.append(f"Requested languages, one caption entry each: {', '.join(languages)}")
    if not is_clause_end:
        parts.append(
            "This segment was cut at the safety limit while the speaker was still "
            "talking. Expect it to start and end mid-sentence."
        )
    return "\n".join(parts)


class GeminiEngine:
    """Transcribes and translates one segment with a single structured call."""

    def __init__(self, settings: TranscriberSettings, client: Any | None = None) -> None:
        self._settings = settings
        self._client = client

    def _ensure_client(self) -> Any:
        if self._client is None:
            from google import genai

            if not self._settings.gemini_api_key:
                raise RuntimeError("GEMINI_API_KEY is not configured")
            self._client = genai.Client(api_key=self._settings.gemini_api_key)
        return self._client

    async def process(
        self, pcm: bytes, context: StageContext, is_clause_end: bool
    ) -> SegmentResult:
        languages = context.target_languages()
        last_error: Exception | None = None

        for attempt in range(1, self._settings.max_attempts + 1):
            try:
                return await asyncio.wait_for(
                    self._call(pcm, context, languages, is_clause_end),
                    timeout=self._settings.request_timeout_seconds,
                )
            except asyncio.TimeoutError as exc:
                last_error = exc
                logger.warning(
                    "Segment timed out after %.1fs (attempt %d/%d)",
                    self._settings.request_timeout_seconds,
                    attempt,
                    self._settings.max_attempts,
                )
            except Exception as exc:
                last_error = exc
                logger.warning("Segment failed (attempt %d): %s", attempt, exc)

        raise EngineUnavailable(str(last_error) if last_error else "unknown failure")

    async def _call(
        self,
        pcm: bytes,
        context: StageContext,
        languages: list[str],
        is_clause_end: bool,
    ) -> SegmentResult:
        from google.genai import types

        client = self._ensure_client()
        response = await client.aio.models.generate_content(
            model=self._settings.transcription_model,
            contents=[
                types.Part.from_bytes(data=pcm_to_wav(pcm), mime_type="audio/wav"),
                build_prompt(context, languages, is_clause_end),
            ],
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
                response_schema=RESPONSE_SCHEMA,
                # Captions must be reproducible; the evaluation harness in
                # evaluation/ scores this output against a fixed ground truth.
                temperature=0.0,
            ),
        )
        return parse_response(response.text, languages)


class EngineUnavailable(RuntimeError):
    """Raised when every attempt failed. Surfaces as 503 to the room worker,
    which degrades and fires the `transcriber_socket_down` alarm."""


def parse_response(raw: str | None, languages: list[str]) -> SegmentResult:
    data = json.loads(raw or "{}")
    captions: dict[str, str] = {}
    for entry in data.get("captions") or []:
        if not isinstance(entry, dict):
            continue
        lang = str(entry.get("lang") or "").strip().lower()
        if lang in languages:
            captions[lang] = str(entry.get("text") or "")

    original = str(data.get("original") or "")
    # A missing language is better filled with the original than dropped: the
    # audience sees untranslated text instead of a gap.
    for lang in languages:
        captions.setdefault(lang, original)

    return SegmentResult(
        original=original,
        source_language=str(data.get("source_language") or ""),
        captions=captions,
        preserved_terms=tuple(str(t) for t in (data.get("preserved_terms") or [])),
    )
