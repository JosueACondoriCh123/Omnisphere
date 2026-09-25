from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx
from websockets.asyncio.client import connect


def overlaps(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return int(left["t0_ms"]) < int(right["t1_ms"]) and int(right["t0_ms"]) < int(
        left["t1_ms"]
    )


def websocket_url(base_url: str, stage_id: str, lang: str) -> str:
    parsed = urlparse(base_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return f"{scheme}://{parsed.netloc}/ws/stages/{stage_id}/{lang}"


@dataclass(frozen=True)
class LanguageResult:
    lang: str
    draft: dict[str, Any]
    committed: dict[str, Any]
    draft_after_ms: int
    commit_after_ms: int


async def wait_for_transition(
    base_url: str,
    stage_id: str,
    lang: str,
    timeout: float,
    started_ms: int,
) -> LanguageResult:
    started = time.monotonic()
    draft: dict[str, Any] | None = None
    async with connect(
        websocket_url(base_url, stage_id, lang),
        open_timeout=10,
        ping_interval=20,
        proxy=None,
    ) as socket:
        while time.monotonic() - started < timeout:
            remaining = timeout - (time.monotonic() - started)
            raw = await asyncio.wait_for(socket.recv(), timeout=remaining)
            event = json.loads(raw)
            if event.get("type") != "caption":
                continue
            if str(event.get("stage_id")) != stage_id or event.get("lang") != lang:
                raise RuntimeError(f"partition leak on {lang}: {event}")
            if int(event.get("emitted_at_ms") or 0) < started_ms:
                continue
            if event.get("state") == "draft":
                draft = event
                draft_after_ms = round((time.monotonic() - started) * 1000)
                continue
            if event.get("state") == "committed" and draft and overlaps(draft, event):
                return LanguageResult(
                    lang=lang,
                    draft=draft,
                    committed=event,
                    draft_after_ms=draft_after_ms,
                    commit_after_ms=round((time.monotonic() - started) * 1000),
                )
    raise TimeoutError(f"no overlapping draft-to-commit received for {lang} in {timeout}s")


async def verify_snapshot(base_url: str, result: LanguageResult) -> None:
    async with connect(
        websocket_url(base_url, str(result.committed["stage_id"]), result.lang),
        open_timeout=10,
        proxy=None,
    ) as socket:
        raw = await asyncio.wait_for(socket.recv(), timeout=10)
        snapshot = json.loads(raw)
    if snapshot.get("type") != "snapshot":
        raise RuntimeError(f"expected snapshot for {result.lang}, got {snapshot.get('type')}")
    if not any(
        caption.get("state") == "committed"
        and int(caption.get("t0_ms", -1)) == int(result.committed["t0_ms"])
        and int(caption.get("t1_ms", -1)) == int(result.committed["t1_ms"])
        for caption in snapshot.get("captions", [])
    ):
        raise RuntimeError(f"reconnect snapshot is missing the {result.lang} commit")


async def run(args: argparse.Namespace) -> None:
    base_url = args.base_url.rstrip("/")
    async with httpx.AsyncClient(base_url=base_url, timeout=10) as client:
        ready = await client.get("/api/stages")
        ready.raise_for_status()
        metrics = await client.get(f"/api/metrics/stages/{args.stage}")
        metrics.raise_for_status()
        status = metrics.json()
        if not status.get("transcriber_up"):
            raise RuntimeError(
                f"Gemini/transcriber is not ready: {status.get('transcriber_error')}"
            )

    languages = [item.strip() for item in args.langs.split(",") if item.strip()]
    started_ms = int(time.time() * 1000)
    print(
        f"LISTENING stage={args.stage} langs={','.join(languages)} — "
        "hablá durante al menos 3 segundos y luego hacé una pausa"
    )
    results = await asyncio.gather(
        *(
            wait_for_transition(
                base_url, str(args.stage), lang, args.timeout, started_ms
            )
            for lang in languages
        )
    )
    await asyncio.gather(*(verify_snapshot(base_url, result) for result in results))
    for result in results:
        print(
            f"LANG_OK lang={result.lang} draft_ms={result.draft_after_ms} "
            f"commit_ms={result.commit_after_ms} overlap=1 snapshot=1"
        )
    print(
        f"LIVE_E2E_OK stage={args.stage} langs={','.join(languages)} "
        "draft=1 commit=1 overlap=1 snapshot=1"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate a real OBS -> Gemini -> WebSocket caption transition."
    )
    parser.add_argument("--base-url", default="http://localhost:8088")
    parser.add_argument("--stage", default="1")
    parser.add_argument("--langs", default="es,en")
    parser.add_argument("--timeout", type=float, default=90)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
