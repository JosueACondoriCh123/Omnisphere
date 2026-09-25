from __future__ import annotations

import base64
import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

HOPS = ("ingest", "vad", "tier1", "tier2a", "tier2b", "reconciler", "fanout", "render")


def now_ms() -> int:
    return int(time.time() * 1000)


@dataclass(frozen=True)
class TraceStamp:
    hop: str
    stage_id: str
    seq: int
    t_wall_ms: int

    def __post_init__(self) -> None:
        if self.hop not in HOPS:
            raise ValueError(f"unknown pipeline hop: {self.hop}")

    @staticmethod
    def make(hop: str, stage_id: str, seq: int) -> TraceStamp:
        return TraceStamp(hop=hop, stage_id=stage_id, seq=seq, t_wall_ms=now_ms())


@dataclass(frozen=True)
class AudioSegment:
    """Carril 3 output on Redis channel ``stage:{id}:audio``."""

    stage_id: str
    seq: int
    t0_ms: int
    t1_ms: int
    pcm_b64: str
    is_clause_end: bool
    rms_dbfs: float
    traces: list[dict[str, Any]] = field(default_factory=list)
    audio_end_wall_ms: int | None = None
    session_id: str | None = None

    def __post_init__(self) -> None:
        if self.t1_ms < self.t0_ms:
            raise ValueError("audio segment has an inverted time window")

    def pcm(self) -> bytes:
        return base64.b64decode(self.pcm_b64)

    @classmethod
    def from_pcm(
        cls,
        stage_id: str,
        seq: int,
        t0_ms: int,
        t1_ms: int,
        pcm: bytes,
        is_clause_end: bool,
        rms_dbfs: float,
        audio_end_wall_ms: int | None = None,
        session_id: str | None = None,
    ) -> AudioSegment:
        return cls(
            stage_id=stage_id,
            seq=seq,
            t0_ms=t0_ms,
            t1_ms=t1_ms,
            pcm_b64=base64.b64encode(pcm).decode("ascii"),
            is_clause_end=is_clause_end,
            rms_dbfs=rms_dbfs,
            audio_end_wall_ms=audio_end_wall_ms,
            session_id=session_id,
        )

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str | bytes) -> AudioSegment:
        return cls(**json.loads(raw))


@dataclass(frozen=True)
class CaptionText:
    original: str
    es: str = ""
    en: str = ""


@dataclass(frozen=True)
class CaptionEvent:
    """Carril 2 input consumed from ``stage:{id}:captions`` by Carril 3."""

    stage_id: str
    t0_ms: int
    t1_ms: int
    state: Literal["draft", "committed"]
    revision: int
    tier: int
    lang_detected: str
    text: CaptionText
    emitted_at_ms: int
    traces: list[dict[str, Any]] = field(default_factory=list)
    provider: str = "legacy"
    audio_end_wall_ms: int | None = None
    session_id: str | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str | bytes) -> CaptionEvent:
        data = json.loads(raw)
        data["text"] = CaptionText(**data["text"])
        return cls(**data)
