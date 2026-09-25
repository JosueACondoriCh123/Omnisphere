from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import os
import signal
import sys
import time
from dataclasses import asdict, replace
from datetime import UTC, datetime
from typing import Any

import httpx

from app.config import get_settings
from app.segmenter import SegmentWindow, UtteranceSegmenter
from contracts.events import AudioSegment, TraceStamp, now_ms

logger = logging.getLogger("nerdearla.room_worker")
PCM_SAMPLE_RATE = 16_000
PCM_CHANNELS = 1
PCM_SAMPLE_BYTES = 2
VAD_FRAME_SAMPLES = 512
VAD_FRAME_BYTES = VAD_FRAME_SAMPLES * PCM_SAMPLE_BYTES


def build_ffmpeg_command(stream_url: str) -> list[str]:
    """Build the invariant live normalization chain required by Carril 3."""
    return [
        os.environ.get("FFMPEG_BIN", "ffmpeg"),
        "-hide_banner",
        "-loglevel",
        "warning",
        "-nostdin",
        "-fflags",
        "nobuffer",
        "-flags",
        "low_delay",
        "-rtsp_transport",
        "tcp",
        "-i",
        stream_url,
        "-vn",
        "-af",
        "highpass=f=80,loudnorm=I=-16:TP=-1.5:LRA=11:linear=true",
        "-acodec",
        "pcm_s16le",
        "-ar",
        str(PCM_SAMPLE_RATE),
        "-ac",
        str(PCM_CHANNELS),
        "-f",
        "s16le",
        "pipe:1",
    ]


def load_context() -> dict[str, Any]:
    encoded = os.environ.get("NERDEARLA_STAGE_CONTEXT_B64", "")
    if not encoded:
        return {"languages": ["es"]}
    return json.loads(base64.urlsafe_b64decode(encoded).decode("utf-8"))


class RoomWorker:
    def __init__(self, stage_id: str, stream_url: str) -> None:
        self.stage_id = stage_id
        self.stream_url = stream_url
        self.settings = get_settings()
        self.context = load_context()
        self.languages: list[str] = self.context.get("languages") or ["es"]
        self.client = httpx.AsyncClient(timeout=10)
        self.ffmpeg: asyncio.subprocess.Process | None = None
        self.stop_event = asyncio.Event()
        self.state = "starting"
        self.audio_seen_at: str | None = None
        self.last_error: str | None = None
        self.inference_ms: float | None = None
        self.sequence = 0
        self.event_sequence = 0
        self.redis: Any | None = None
        self.stream_samples = 0
        self.vad_backlog_ms = 0.0
        self.redis_publish_ms: float | None = None
        self.segments_published = 0
        self.ffmpeg_launches = 0
        self.frame_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=240)
        self.frame_sender_task: asyncio.Task[None] | None = None
        self.live_pcm = bytearray()
        started_at = os.environ.get("OMNISTAGE_SESSION_STARTED_AT", "")
        try:
            self.timeline_offset_ms = max(
                0, round((datetime.now(UTC) - datetime.fromisoformat(started_at)).total_seconds() * 1000)
            ) if started_at else 0
        except ValueError:
            self.timeline_offset_ms = 0

    def request_stop(self) -> None:
        self.stop_event.set()
        if self.ffmpeg and self.ffmpeg.returncode is None:
            self.ffmpeg.terminate()

    async def run(self) -> int:
        heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        if self.settings.transport_mode == "local":
            self.frame_sender_task = asyncio.create_task(self._send_frames(), name="live-frame-sender")
        try:
            return await self._audio_loop()
        except asyncio.CancelledError:
            return 0
        except Exception as exc:
            self.state = "failed"
            self.last_error = str(exc)[:500]
            logger.exception("Stage %s worker failed", self.stage_id)
            await self._heartbeat()
            return 1
        finally:
            self.stop_event.set()
            heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)
            if self.frame_sender_task:
                self.frame_sender_task.cancel()
                await asyncio.gather(self.frame_sender_task, return_exceptions=True)
            if self.ffmpeg and self.ffmpeg.returncode is None:
                self.ffmpeg.terminate()
                try:
                    await asyncio.wait_for(self.ffmpeg.wait(), 3)
                except TimeoutError:
                    self.ffmpeg.kill()
            if self.redis is not None:
                await self.redis.aclose()
            await self.client.aclose()

    async def _audio_loop(self) -> int:
        import numpy as np
        import torch
        from silero_vad import VADIterator, load_silero_vad

        torch.set_num_threads(1)
        model = load_silero_vad(onnx=True)
        vad = VADIterator(
            model,
            threshold=self.settings.vad_threshold,
            sampling_rate=PCM_SAMPLE_RATE,
            min_silence_duration_ms=self.settings.vad_min_silence_ms,
            speech_pad_ms=self.settings.vad_speech_pad_ms,
        )
        while not self.stop_event.is_set():
            try:
                return_code = await self._consume_ffmpeg(vad, np, torch)
                if self.stop_event.is_set():
                    return 0
                self.state = "degraded"
                self.last_error = f"ffmpeg exited with code {return_code}; reconnecting"
                await self._heartbeat()
            except (OSError, RuntimeError) as exc:
                if self.stop_event.is_set():
                    return 0
                self.state = "degraded"
                self.last_error = f"ffmpeg: {exc}"[:500]
                logger.warning("Stage %s FFmpeg reconnect: %s", self.stage_id, exc)
                await self._heartbeat()

            vad.reset_states()
            self.ffmpeg = None
            try:
                await asyncio.wait_for(
                    self.stop_event.wait(), timeout=self.settings.ffmpeg_reconnect_seconds
                )
            except TimeoutError:
                pass
        return 0

    async def _consume_ffmpeg(self, vad: Any, np: Any, torch: Any) -> int:
        session_started = time.monotonic()
        session_start_sample = self.stream_samples
        self.ffmpeg = await asyncio.create_subprocess_exec(
            *build_ffmpeg_command(self.stream_url),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self.ffmpeg_launches += 1
        stderr_task = asyncio.create_task(self._drain_ffmpeg_stderr())
        self.state = "listening"
        self.last_error = None
        await self._heartbeat()

        if not self.ffmpeg.stdout:
            raise RuntimeError("FFmpeg stdout pipe was not created")

        pending = bytearray()
        segmenter = UtteranceSegmenter(
            sample_rate=PCM_SAMPLE_RATE,
            sample_bytes=PCM_SAMPLE_BYTES,
            frame_samples=VAD_FRAME_SAMPLES,
            pre_roll_ms=self.settings.vad_speech_pad_ms,
            partial_seconds=self.settings.partial_segment_seconds,
            max_seconds=self.settings.max_segment_seconds,
        )

        try:
            while not self.stop_event.is_set():
                chunk = await self.ffmpeg.stdout.read(VAD_FRAME_BYTES - len(pending))
                if not chunk:
                    break
                pending.extend(chunk)
                if len(pending) < VAD_FRAME_BYTES:
                    continue
                frame_bytes = bytes(pending[:VAD_FRAME_BYTES])
                del pending[:VAD_FRAME_BYTES]
                self.stream_samples += VAD_FRAME_SAMPLES
                if self.settings.transport_mode == "local":
                    self.live_pcm.extend(frame_bytes)
                    while len(self.live_pcm) >= 3_200:
                        live_chunk = bytes(self.live_pcm[:3_200])
                        del self.live_pcm[:3_200]
                        frame_time_ms = self.timeline_offset_ms + round(
                            (self.stream_samples - len(self.live_pcm) // PCM_SAMPLE_BYTES) / PCM_SAMPLE_RATE * 1000
                        )
                        frame = frame_time_ms.to_bytes(8, "big") + live_chunk
                        try:
                            self.frame_queue.put_nowait(frame)
                        except asyncio.QueueFull:
                            self.state = "degraded"
                            self.last_error = "cloud frame backlog exceeded 24 seconds"
                            while not self.frame_queue.empty():
                                self.frame_queue.get_nowait()
                            await self._notify_cloud_failure()
                self.audio_seen_at = datetime.now(UTC).isoformat()
                media_ms = (
                    (self.stream_samples - session_start_sample) / PCM_SAMPLE_RATE * 1000
                )
                wall_ms = (time.monotonic() - session_started) * 1000
                self.vad_backlog_ms = round(max(0.0, wall_ms - media_ms), 2)

                frame = np.frombuffer(frame_bytes, dtype=np.int16).astype(np.float32)
                frame /= 32768.0
                vad_event = vad(torch.from_numpy(frame), return_seconds=False)
                started = bool(vad_event and "start" in vad_event)
                ended = bool(vad_event and "end" in vad_event)
                if started and not segmenter.speech_active:
                    self.state = "speech"
                    await self._publish_source_event(
                        "vad_start", False, {"sample": vad_event["start"]}
                    )

                segments = segmenter.push(
                    frame_bytes,
                    stream_end_sample=self.stream_samples,
                    speech_started=started,
                    speech_ended=ended,
                )
                for segment in segments:
                    await self._finish_segment(segment)
                    if segment.reason != "partial":
                        self.state = "listening"
                    if segment.reason == "max_duration":
                        vad.reset_states()

            for segment in segmenter.flush(self.stream_samples):
                await self._finish_segment(segment)
            return await self.ffmpeg.wait()
        finally:
            stderr_task.cancel()
            await asyncio.gather(stderr_task, return_exceptions=True)

    async def _finish_segment(
        self,
        segment: SegmentWindow,
    ) -> None:
        import numpy as np

        audio = segment.audio
        t0_ms = segment.t0_ms + self.timeline_offset_ms
        t1_ms = segment.t1_ms + self.timeline_offset_ms
        is_clause_end = segment.is_clause_end
        reason = segment.reason
        duration_ms = round(len(audio) / PCM_SAMPLE_BYTES / PCM_SAMPLE_RATE * 1000)
        samples = np.frombuffer(audio, dtype=np.int16).astype(np.float64)
        rms = float(np.sqrt(np.mean(samples * samples))) if samples.size else 0.0
        rms_dbfs = float(20 * np.log10(max(rms / 32768.0, 1e-9)))
        payload = {
            "duration_ms": duration_ms,
            "bytes": len(audio),
            "reason": reason,
            "rms_dbfs": round(rms_dbfs, 2),
        }
        if reason != "partial":
            await self._publish_source_event("vad_end", is_clause_end, payload)

        self.sequence += 1
        current_media_ms = self.timeline_offset_ms + round(
            self.stream_samples / PCM_SAMPLE_RATE * 1000
        )
        # Backdate delayed PCM consumption so a slow VAD loop cannot make the
        # measured audio-to-paint latency look artificially short.
        audio_end_wall_ms = now_ms() - max(0, current_media_ms - t1_ms) - round(self.vad_backlog_ms)
        segment = AudioSegment.from_pcm(
            stage_id=self.stage_id,
            seq=self.sequence,
            t0_ms=t0_ms,
            t1_ms=t1_ms,
            pcm=audio,
            is_clause_end=is_clause_end,
            rms_dbfs=round(rms_dbfs, 2),
            audio_end_wall_ms=audio_end_wall_ms,
        )
        segment = replace(
            segment,
            traces=[
                asdict(
                    TraceStamp(
                        hop="ingest",
                        stage_id=self.stage_id,
                        seq=self.sequence,
                        t_wall_ms=now_ms() - duration_ms,
                    )
                ),
                asdict(TraceStamp.make("vad", self.stage_id, self.sequence)),
            ],
        )
        await self._publish_audio_segment(segment)

        if self.settings.transport_mode == "local" or not self.settings.transcriber_url:
            return

        started = time.perf_counter()
        try:
            response = await self.client.post(
                self.settings.transcriber_url,
                content=audio,
                headers={
                    "content-type": "audio/L16;rate=16000;channels=1",
                    "x-stage-id": self.stage_id,
                    "x-is-clause-end": str(is_clause_end).lower(),
                    "x-stage-context": base64.urlsafe_b64encode(
                        json.dumps(self.context, ensure_ascii=False).encode("utf-8")
                    ).decode("ascii"),
                },
            )
            response.raise_for_status()
            self.inference_ms = round((time.perf_counter() - started) * 1000, 2)
            body = response.json()
            for event in body.get("events", []):
                lang = str(event.pop("lang", self.languages[0]))
                event.setdefault("metrics", {})["inference_ms"] = self.inference_ms
                await self._post_event(lang, event)
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            self.state = "degraded"
            self.last_error = f"transcriber: {exc}"[:500]
            await self._publish_source_event(
                "worker_error", False, {"component": "transcriber", "error": str(exc)[:300]}
            )

    async def _publish_audio_segment(self, segment: AudioSegment) -> None:
        if self.settings.transport_mode == "local":
            started = time.perf_counter()
            response = await self.client.post(
                f"{self.settings.internal_api_base}/internal/audio/stages/{self.stage_id}/segments",
                content=segment.to_json(),
                headers={"x-internal-token": self.settings.internal_token, "content-type": "application/json"},
            )
            response.raise_for_status()
            self.redis_publish_ms = round((time.perf_counter() - started) * 1000, 2)
            self.segments_published += 1
            return
        if self.redis is None:
            import redis.asyncio as redis

            self.redis = redis.from_url(self.settings.redis_url)
        started = time.perf_counter()
        await self.redis.publish(f"stage:{self.stage_id}:audio", segment.to_json())
        self.redis_publish_ms = round((time.perf_counter() - started) * 1000, 2)
        self.segments_published += 1

    async def _send_frames(self) -> None:
        import websockets

        url = self.settings.internal_api_base.replace("http://", "ws://").replace("https://", "wss://")
        url += f"/internal/audio/stages/{self.stage_id}/frames"
        while not self.stop_event.is_set():
            try:
                async with websockets.connect(
                    url, additional_headers={"x-internal-token": self.settings.internal_token},
                    max_size=32_008,
                ) as socket:
                    while not self.stop_event.is_set():
                        frame = await self.frame_queue.get()
                        await socket.send(frame)
            except asyncio.CancelledError:
                raise
            except (OSError, RuntimeError, websockets.WebSocketException) as exc:
                self.last_error = f"frame socket: {exc}"[:300]
                await asyncio.sleep(0.5)

    async def _notify_cloud_failure(self) -> None:
        try:
            await self.client.post(
                f"{self.settings.internal_api_base}/internal/audio/stages/{self.stage_id}/cloud-failed",
                headers={"x-internal-token": self.settings.internal_token},
            )
        except httpx.HTTPError:
            pass

    async def _publish_source_event(
        self, event_type: str, is_clause_end: bool, payload: dict[str, Any]
    ) -> None:
        self.event_sequence += 1
        event = {
            "type": event_type,
            "seq": self.event_sequence,
            "is_clause_end": is_clause_end,
            "payload": payload,
        }
        for lang in self.languages:
            await self._post_event(lang, event)

    async def _post_event(self, lang: str, event: dict[str, Any]) -> None:
        response = await self.client.post(
            f"{self.settings.internal_api_base}/internal/stages/{self.stage_id}/{lang}/events",
            json=event,
            headers={"x-internal-token": self.settings.internal_token},
        )
        response.raise_for_status()

    async def _heartbeat_loop(self) -> None:
        while not self.stop_event.is_set():
            await self._heartbeat()
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=3)
            except TimeoutError:
                pass

    async def _heartbeat(self) -> None:
        try:
            await self.client.post(
                f"{self.settings.internal_api_base}/internal/workers/{self.stage_id}/heartbeat",
                json={
                    "pid": os.getpid(),
                    "state": self.state,
                    "audio_seen_at": self.audio_seen_at,
                    "ffmpeg_alive": bool(self.ffmpeg and self.ffmpeg.returncode is None),
                    "error": self.last_error,
                    "inference_ms": self.inference_ms,
                    "vad_backlog_ms": self.vad_backlog_ms,
                    "redis_publish_ms": self.redis_publish_ms,
                    "segments_published": self.segments_published,
                    "ffmpeg_restarts": max(0, self.ffmpeg_launches - 1),
                    "audio_samples": self.stream_samples,
                },
                headers={"x-internal-token": self.settings.internal_token},
            )
        except httpx.HTTPError as exc:
            logger.warning("Heartbeat failed: %s", exc)

    async def _drain_ffmpeg_stderr(self) -> None:
        if not self.ffmpeg or not self.ffmpeg.stderr:
            return
        while line := await self.ffmpeg.stderr.readline():
            logger.warning("ffmpeg: %s", line.decode(errors="replace").rstrip())


async def async_main() -> int:
    parser = argparse.ArgumentParser(description="Isolated Nerdearla stage worker")
    parser.add_argument("--stage", required=True)
    parser.add_argument("--stream-url", required=True)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format='{"level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
    )
    worker = RoomWorker(args.stage, args.stream_url)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, worker.request_stop)
        except NotImplementedError:
            signal.signal(sig, lambda *_: worker.request_stop())
    return await worker.run()


if __name__ == "__main__":
    sys.exit(asyncio.run(async_main()))
