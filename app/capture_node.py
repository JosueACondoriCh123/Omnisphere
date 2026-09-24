from __future__ import annotations

import argparse
import asyncio
import logging
import os
import platform
import socket
import sys
import time
import uuid

import httpx

logger = logging.getLogger("nerdearla.capture")


def build_capture_command(
    input_format: str, source: str, target: str, demo: bool = False
) -> list[str]:
    command = ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-nostdin"]
    if demo:
        command += [
            "-re",
            "-f",
            "lavfi",
            "-i",
            "anoisesrc=color=pink:amplitude=0.04:sample_rate=48000",
        ]
    else:
        command += ["-f", input_format, "-i", source]
    command += [
        "-vn",
        "-af",
        "aresample=async=1:first_pts=0",
        "-ac",
        "1",
        "-ar",
        "48000",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-progress",
        "pipe:1",
        "-nostats",
        "-f",
        "flv",
        target,
    ]
    return command


class CaptureNode:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.node_id = args.node_id or f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
        self.api_url = args.api_url.rstrip("/")
        self.rtmp_target = (
            ""
            if args.server == "auto"
            else f"{args.server.rstrip('/')}/live/stage-{args.stage}"
        )
        self.client = httpx.AsyncClient(timeout=5)
        self.process: asyncio.subprocess.Process | None = None
        self.last_rtt_ms: float | None = None
        self.bytes_sent: int | None = None

    async def run(self) -> int:
        await self._register_with_retry()
        command = build_capture_command(
            self.args.input_format, self.args.source, self.rtmp_target, self.args.demo
        )
        logger.info("Publishing stage %s to %s", self.args.stage, self.rtmp_target)
        self.process = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.PIPE
        )
        heartbeat = asyncio.create_task(self._heartbeat_loop())
        progress = asyncio.create_task(self._progress_loop())
        try:
            return await self.process.wait()
        finally:
            heartbeat.cancel()
            progress.cancel()
            await asyncio.gather(heartbeat, progress, return_exceptions=True)
            await self.client.aclose()

    async def _register_with_retry(self) -> None:
        payload = {
            "node_id": self.node_id,
            "stage_id": self.args.stage,
            "hostname": socket.gethostname(),
            "source": "lavfi:demo" if self.args.demo else f"{self.args.input_format}:{self.args.source}",
            "version": "1.0.0",
        }
        for attempt in range(1, 21):
            try:
                response = await self.client.post(
                    f"{self.api_url}/api/capture-nodes/register", json=payload
                )
                response.raise_for_status()
                advertised = response.json().get("rtmp_url")
                if (
                    self.args.server == "auto"
                    and isinstance(advertised, str)
                    and advertised.startswith("rtmp://")
                ):
                    self.rtmp_target = advertised
                if not self.rtmp_target:
                    raise RuntimeError("registration did not return a usable rtmp_url")
                logger.info("Capture node %s auto-registered", self.node_id)
                return
            except httpx.HTTPError as exc:
                logger.warning("Registration attempt %s failed: %s", attempt, exc)
                await asyncio.sleep(min(attempt, 5))
        raise RuntimeError("capture node could not register after 20 attempts")

    async def _heartbeat_loop(self) -> None:
        while True:
            started = time.perf_counter()
            try:
                response = await self.client.post(
                    f"{self.api_url}/api/capture-nodes/{self.node_id}/heartbeat",
                    json={
                        "stage_id": self.args.stage,
                        "rtt_ms": self.last_rtt_ms,
                        "ffmpeg_alive": bool(self.process and self.process.returncode is None),
                        "bytes_sent": self.bytes_sent,
                    },
                )
                response.raise_for_status()
                self.last_rtt_ms = round((time.perf_counter() - started) * 1000, 2)
            except httpx.HTTPError as exc:
                logger.warning("Heartbeat failed: %s", exc)
            await asyncio.sleep(5)

    async def _progress_loop(self) -> None:
        if not self.process or not self.process.stdout:
            return
        while line := await self.process.stdout.readline():
            key, separator, value = line.decode(errors="replace").strip().partition("=")
            if separator and key == "total_size":
                try:
                    self.bytes_sent = int(value)
                except ValueError:
                    pass


def default_input_format() -> str:
    return {"Windows": "dshow", "Darwin": "avfoundation"}.get(platform.system(), "alsa")


async def async_main() -> int:
    parser = argparse.ArgumentParser(
        description="One-command, self-registering Nerdearla capture node"
    )
    parser.add_argument("--stage", required=True, help="Stage identifier, e.g. 1")
    parser.add_argument(
        "--server",
        default=os.getenv("CAPTURE_RTMP_SERVER", "auto"),
        help="RTMP base URL or 'auto' to use the registration response",
    )
    parser.add_argument(
        "--api-url",
        default=os.getenv("CAPTURE_API_URL", "http://localhost:8080"),
    )
    parser.add_argument("--input-format", default=default_input_format())
    parser.add_argument("--source", default="default")
    parser.add_argument("--node-id")
    parser.add_argument("--demo", action="store_true", help="Publish synthetic audio")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return await CaptureNode(args).run()


if __name__ == "__main__":
    sys.exit(asyncio.run(async_main()))
