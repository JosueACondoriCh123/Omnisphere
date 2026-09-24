"""Concurrent RTMP load probe for Carril 3.

Feeds real audio files in real time, samples the public metrics API and writes a
small Markdown report. It intentionally uses only the Python standard library
so it can run from the host before the application image exists.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class LevelResult:
    rooms: int
    p95_ingest_fanout_ms: float | None = None
    max_vad_backlog_ms: float = 0
    max_redis_publish_ms: float = 0
    max_cpu_percent: float = 0
    max_memory_mib: float = 0
    max_active_rooms: int = 0
    reasons: set[str] = field(default_factory=set)

    @property
    def broken(self) -> bool:
        return bool(self.reasons)


def parse_room_levels(value: str) -> list[int]:
    levels = sorted({int(item.strip()) for item in value.split(",") if item.strip()})
    if not levels or levels[0] < 1:
        raise argparse.ArgumentTypeError("--rooms requires positive integers")
    return levels


def build_publish_command(audio: Path, stage_id: str, rtmp_base: str) -> list[str]:
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-re",
        "-stream_loop",
        "-1",
        "-i",
        str(audio),
        "-vn",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-ar",
        "48000",
        "-ac",
        "1",
        "-f",
        "flv",
        f"{rtmp_base.rstrip('/')}/live/stage-{stage_id}",
    ]


def _fetch_json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.load(response)


def _percent(value: str) -> float:
    try:
        return float(value.strip().removesuffix("%"))
    except ValueError:
        return 0.0


def _memory_mib(value: str) -> float:
    raw = value.split("/")[0].strip()
    units = (("GiB", 1024), ("MiB", 1), ("KiB", 1 / 1024), ("B", 1 / 1024**2))
    for suffix, multiplier in units:
        if raw.endswith(suffix):
            try:
                return float(raw[: -len(suffix)].strip()) * multiplier
            except ValueError:
                return 0.0
    return 0.0


def docker_usage() -> tuple[float, float]:
    if not shutil.which("docker"):
        return 0.0, 0.0
    try:
        result = subprocess.run(
            ["docker", "stats", "--no-stream", "--format", "{{json .}}"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 0.0, 0.0
    cpu = 0.0
    memory = 0.0
    for line in result.stdout.splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        name = str(row.get("Name", ""))
        if "nerdearla" not in name:
            continue
        cpu += _percent(str(row.get("CPUPerc", "0")))
        memory += _memory_mib(str(row.get("MemUsage", "0B")))
    return round(cpu, 2), round(memory, 2)


def observe_metrics(result: LevelResult, payload: dict[str, Any]) -> None:
    active = 0
    p95_values: list[float] = []
    for stage in payload.get("items", []):
        if not str(stage.get("stage_id", "")).startswith("load-"):
            continue
        active += int(bool(stage.get("stream_up")))
        result.max_vad_backlog_ms = max(
            result.max_vad_backlog_ms, float(stage.get("vad_backlog_ms") or 0)
        )
        result.max_redis_publish_ms = max(
            result.max_redis_publish_ms, float(stage.get("redis_publish_ms") or 0)
        )
        for hop in stage.get("hop_latencies", []):
            if (
                hop.get("from_hop") == "ingest"
                and hop.get("to_hop") == "fanout"
                and int(hop.get("n", 0)) > 0
            ):
                p95_values.append(float(hop.get("p95_ms", 0)))
    result.max_active_rooms = max(result.max_active_rooms, active)
    if p95_values:
        result.p95_ingest_fanout_ms = max(
            result.p95_ingest_fanout_ms or 0, max(p95_values)
        )


def evaluate_result(
    result: LevelResult,
    *,
    max_cpu: float,
    max_vad_backlog_ms: float,
    max_redis_publish_ms: float,
) -> None:
    if result.max_active_rooms < result.rooms:
        result.reasons.add(f"streams {result.max_active_rooms}/{result.rooms}")
    if result.p95_ingest_fanout_ms is None:
        result.reasons.add("sin muestras ingest→fanout")
    if result.max_cpu_percent > max_cpu:
        result.reasons.add(f"CPU > {max_cpu:g}%")
    if result.max_vad_backlog_ms > max_vad_backlog_ms:
        result.reasons.add(f"VAD > {max_vad_backlog_ms:g} ms")
    if result.max_redis_publish_ms > max_redis_publish_ms:
        result.reasons.add(f"Redis > {max_redis_publish_ms:g} ms")


async def run_level(args: argparse.Namespace, rooms: int, files: list[Path]) -> LevelResult:
    result = LevelResult(rooms=rooms)
    processes: list[asyncio.subprocess.Process] = []
    try:
        for index in range(rooms):
            command = build_publish_command(
                files[index % len(files)], f"load-{index + 1}", args.rtmp_base
            )
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            processes.append(process)

        deadline = time.monotonic() + args.duration
        while time.monotonic() < deadline:
            try:
                payload, usage = await asyncio.gather(
                    asyncio.to_thread(
                        _fetch_json, f"{args.api_base.rstrip('/')}/api/metrics/stages"
                    ),
                    asyncio.to_thread(docker_usage),
                )
                observe_metrics(result, payload)
                result.max_cpu_percent = max(result.max_cpu_percent, usage[0])
                result.max_memory_mib = max(result.max_memory_mib, usage[1])
            except (OSError, TimeoutError, json.JSONDecodeError) as exc:
                result.reasons.add(f"metrics: {type(exc).__name__}")
            await asyncio.sleep(args.sample_interval)
    finally:
        for process in processes:
            if process.returncode is None:
                process.terminate()
        if processes:
            await asyncio.gather(*(process.wait() for process in processes))

    evaluate_result(
        result,
        max_cpu=args.max_cpu,
        max_vad_backlog_ms=args.max_vad_backlog_ms,
        max_redis_publish_ms=args.max_redis_publish_ms,
    )
    return result


def render_report(results: list[LevelResult]) -> str:
    lines = [
        "# Carga Carril 3",
        "",
        "| Salas | Activas | p95 ingest→fanout | VAD backlog máx. | Redis máx. | CPU máx. | RAM máx. | Estado |",
        "|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for item in results:
        p95 = (
            f"{item.p95_ingest_fanout_ms:.1f} ms"
            if item.p95_ingest_fanout_ms is not None
            else "n/a"
        )
        state = "OK" if not item.broken else "QUIEBRE: " + ", ".join(sorted(item.reasons))
        lines.append(
            f"| {item.rooms} | {item.max_active_rooms} | {p95} | "
            f"{item.max_vad_backlog_ms:.1f} ms | {item.max_redis_publish_ms:.1f} ms | "
            f"{item.max_cpu_percent:.1f}% | {item.max_memory_mib:.1f} MiB | {state} |"
        )
    first_break = next((item.rooms for item in results if item.broken), None)
    lines.extend(
        [
            "",
            f"Número de salas donde se rompe: {first_break if first_break else 'no observado'}.",
            "",
        ]
    )
    return "\n".join(lines)


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--rooms", type=parse_room_levels, default=[6, 8, 10])
    command.add_argument(
        "--audio-dir", type=Path, default=Path("evaluation/corpus/audio")
    )
    command.add_argument("--rtmp-base", default="rtmp://127.0.0.1:1935")
    command.add_argument("--api-base", default="http://127.0.0.1:8080")
    command.add_argument("--duration", type=float, default=45)
    command.add_argument("--sample-interval", type=float, default=2)
    command.add_argument("--max-cpu", type=float, default=90)
    command.add_argument("--max-vad-backlog-ms", type=float, default=1_000)
    command.add_argument("--max-redis-publish-ms", type=float, default=100)
    command.add_argument("--report", type=Path, default=Path("loadtest-report.md"))
    command.add_argument("--dry-run", action="store_true")
    return command


async def async_main() -> int:
    args = parser().parse_args()
    files = sorted(args.audio_dir.glob("*.wav"))
    if not files:
        raise SystemExit(f"No .wav files found in {args.audio_dir}")

    if args.dry_run:
        for rooms in args.rooms:
            print(f"{rooms} rooms:")
            for index in range(rooms):
                print(
                    " ".join(
                        build_publish_command(
                            files[index % len(files)],
                            f"load-{index + 1}",
                            args.rtmp_base,
                        )
                    )
                )
        return 0

    if not shutil.which("ffmpeg"):
        raise SystemExit("ffmpeg is not available on PATH")

    results: list[LevelResult] = []
    for rooms in args.rooms:
        print(f"Running {rooms} rooms for {args.duration:g}s...")
        results.append(await run_level(args, rooms, files))
        await asyncio.sleep(3)

    report = render_report(results)
    args.report.write_text(report, encoding="utf-8")
    print(report)
    print(f"Report: {args.report.resolve()}")
    return int(any(item.broken for item in results))


if __name__ == "__main__":
    raise SystemExit(asyncio.run(async_main()))
