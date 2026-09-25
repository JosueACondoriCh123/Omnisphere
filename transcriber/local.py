"""Offline ASR plus mandatory Gemma 4 text translation/correction."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

import httpx

from transcriber.audio import pcm_to_wav


@dataclass(frozen=True)
class LocalResult:
    original: str
    source_language: str
    es: str
    en: str


class LocalModelUnavailable(RuntimeError):
    pass


class FasterWhisperASR:
    def __init__(self, model_path: str, device: str = "cuda") -> None:
        self.model_path = model_path
        self.device = device
        self._model: Any | None = None
        self._load_lock = asyncio.Lock()

    async def warm(self) -> None:
        async with self._load_lock:
            if self._model is not None:
                return
            if not self.model_path:
                raise LocalModelUnavailable("LOCAL_ASR_MODEL_PATH is not configured")
            try:
                from faster_whisper import WhisperModel

                self._model = await asyncio.to_thread(
                    WhisperModel,
                    self.model_path,
                    device=self.device,
                    compute_type="int8_float16" if self.device == "cuda" else "int8",
                    local_files_only=True,
                )
            except Exception as exc:
                raise LocalModelUnavailable(f"faster-whisper unavailable: {exc}") from exc

    async def transcribe(self, pcm: bytes, glossary: list[str]) -> tuple[str, str]:
        await self.warm()

        def run() -> tuple[str, str]:
            import io

            segments, info = self._model.transcribe(
                io.BytesIO(pcm_to_wav(pcm)),
                beam_size=1,
                best_of=1,
                initial_prompt="; ".join(glossary[:100]) or None,
                vad_filter=False,
                condition_on_previous_text=False,
            )
            return " ".join(item.text.strip() for item in segments).strip(), info.language

        try:
            return await asyncio.to_thread(run)
        except Exception as exc:
            raise LocalModelUnavailable(f"local ASR failed: {exc}") from exc


class Gemma4Translator:
    def __init__(self, url: str, model: str = "gemma-4-E2B-it") -> None:
        self.url = url.rstrip("/")
        self.model = model
        self._client = httpx.AsyncClient(timeout=12)

    async def close(self) -> None:
        await self._client.aclose()

    async def ready(self) -> bool:
        try:
            response = await self._client.get(f"{self.url}/health", timeout=2)
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def translate(self, text: str, source: str, target: str, glossary: list[str]) -> str:
        _, translated = await self.correct_and_translate(text, source, target, glossary)
        return translated

    async def correct_and_translate(
        self, text: str, source: str, target: str, glossary: list[str]
    ) -> tuple[str, str]:
        if not text.strip():
            return "", ""
        if source == target:
            return text, text
        prompt = (
            f"Keep the caption in {source}, correcting only clear speech-recognition errors; "
            f"translate it to {target}. Preserve technical names and Spanglish. "
            "Return compact JSON only: {\"corrected\":\"...\",\"translation\":\"...\"}. "
            "Do not explain.\n"
            f"Terms: {', '.join(glossary[:100])}\nCaption: {text}"
        )
        try:
            response = await self._client.post(
                f"{self.url}/v1/chat/completions",
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0,
                    "max_tokens": 256,
                },
            )
            response.raise_for_status()
            answer = response.json()["choices"][0]["message"]["content"]
            body = str(answer).strip()
            if body.startswith("```"):
                body = body.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            result = json.loads(body)
            corrected = str(result.get("corrected") or result.get("corrected_caption") or "").strip()
            translated = str(result["translation"]).strip()
            if not corrected or not translated:
                raise ValueError("Gemma returned incomplete caption")
            return corrected, translated
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise LocalModelUnavailable(f"Gemma 4 translation failed: {exc}") from exc


class LocalCaptionEngine:
    def __init__(self, asr: FasterWhisperASR, gemma: Gemma4Translator) -> None:
        self.asr = asr
        self.gemma = gemma

    async def process(self, pcm: bytes, glossary: list[str]) -> LocalResult:
        original, source = await self.asr.transcribe(pcm, glossary)
        if not original:
            return LocalResult("", source, "", "")
        if source not in {"es", "en"}:
            raise LocalModelUnavailable(f"unsupported detected language: {source}")
        target = "en" if source == "es" else "es"
        corrected, translated = await self.gemma.correct_and_translate(original, source, target, glossary)
        return LocalResult(
            original=corrected,
            source_language=source,
            es=corrected if source == "es" else translated,
            en=corrected if source == "en" else translated,
        )
