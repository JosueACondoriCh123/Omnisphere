"""Read-only audience origin for LAN and Cloudflare Tunnel."""

from __future__ import annotations

import os
from pathlib import Path
from time import time

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.responses import FileResponse

from app import main

public_app = FastAPI(
    title="OmniStage public captions",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@public_app.get("/api/stages")
async def public_stages():
    result = await main.stages()
    for item in result["items"]:
        session = main.store.current_session(item["stage_id"]) if main.store else None
        if session is not None and not session["permissions"].get("publish"):
            item["session"] = "Próxima charla"
            item["active_session_id"] = None
            item["stream_up"] = False
            item["audio_up"] = False
    return result


@public_app.websocket("/ws/stages/{stage_id}/{lang}")
async def public_captions(websocket: WebSocket, stage_id: str, lang: str) -> None:
    await main.stage_websocket(websocket, stage_id, lang)


@public_app.get("/healthz")
async def public_health() -> dict[str, str]:
    return {"status": "ok"}


@public_app.get("/api/time")
async def public_time() -> dict[str, int]:
    """Allow an audience-side pilot collector to estimate wall-clock offset."""
    return {"server_wall_ms": round(time() * 1000)}


@public_app.get("/{asset_path:path}")
async def public_asset(asset_path: str):
    if asset_path.startswith(("api/", "internal/", "admin", "archive", "operator", ".")):
        raise HTTPException(404, "not found")
    root = Path(os.environ.get("OMNISTAGE_WEB_DIST", "web/dist")).resolve()
    requested = (root / asset_path).resolve()
    if not requested.is_relative_to(root):
        raise HTTPException(404, "not found")
    if requested.is_file():
        return FileResponse(requested, headers={"X-Content-Type-Options": "nosniff"})
    if asset_path not in {"", "app", "captions/clean"} and not asset_path.startswith("overlay/"):
        raise HTTPException(404, "not found")
    index = root / "index.html"
    if not index.is_file():
        raise HTTPException(503, "web build is not installed")
    return FileResponse(index, headers={"X-Content-Type-Options": "nosniff"})
