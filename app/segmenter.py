from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class SegmentWindow:
    audio: bytes
    t0_ms: int
    t1_ms: int
    is_clause_end: bool
    reason: str


class UtteranceSegmenter:
    """Build overlapping speech snapshots without buffering leading silence."""

    def __init__(
        self,
        *,
        sample_rate: int,
        sample_bytes: int,
        frame_samples: int,
        pre_roll_ms: int,
        partial_seconds: float,
        max_seconds: float,
    ) -> None:
        self.sample_rate = sample_rate
        self.sample_bytes = sample_bytes
        self.partial_samples = max(1, round(partial_seconds * sample_rate))
        self.max_samples = max(1, round(max_seconds * sample_rate))
        pre_roll_frames = max(
            1,
            math.ceil(pre_roll_ms / (frame_samples / sample_rate * 1000)),
        )
        self._pre_roll: deque[bytes] = deque(maxlen=pre_roll_frames)
        self._audio = bytearray()
        self._t0_sample: int | None = None
        self._next_partial_sample: int | None = None

    @property
    def speech_active(self) -> bool:
        return self._t0_sample is not None

    def push(
        self,
        frame: bytes,
        *,
        stream_end_sample: int,
        speech_started: bool = False,
        speech_ended: bool = False,
    ) -> list[SegmentWindow]:
        if not self.speech_active:
            self._pre_roll.append(frame)
            if not speech_started:
                return []
            self._audio = bytearray(b"".join(self._pre_roll))
            self._pre_roll.clear()
            buffered_samples = len(self._audio) // self.sample_bytes
            self._t0_sample = max(0, stream_end_sample - buffered_samples)
            self._next_partial_sample = self._t0_sample + self.partial_samples
        else:
            self._audio.extend(frame)

        if speech_ended:
            return [self._finish(stream_end_sample, True, "silence")]

        assert self._t0_sample is not None
        if stream_end_sample - self._t0_sample >= self.max_samples:
            return [self._finish(stream_end_sample, False, "max_duration")]

        assert self._next_partial_sample is not None
        if stream_end_sample >= self._next_partial_sample:
            while self._next_partial_sample <= stream_end_sample:
                self._next_partial_sample += self.partial_samples
            return [self._snapshot(stream_end_sample, False, "partial")]
        return []

    def flush(self, stream_end_sample: int) -> list[SegmentWindow]:
        if not self.speech_active or not self._audio:
            return []
        return [self._finish(stream_end_sample, False, "stream_interrupted")]

    def _snapshot(
        self,
        stream_end_sample: int,
        is_clause_end: bool,
        reason: str,
    ) -> SegmentWindow:
        assert self._t0_sample is not None
        return SegmentWindow(
            audio=bytes(self._audio),
            t0_ms=round(self._t0_sample / self.sample_rate * 1000),
            t1_ms=round(stream_end_sample / self.sample_rate * 1000),
            is_clause_end=is_clause_end,
            reason=reason,
        )

    def _finish(
        self,
        stream_end_sample: int,
        is_clause_end: bool,
        reason: str,
    ) -> SegmentWindow:
        segment = self._snapshot(stream_end_sample, is_clause_end, reason)
        self._audio.clear()
        self._t0_sample = None
        self._next_partial_sample = None
        self._pre_roll.clear()
        return segment
