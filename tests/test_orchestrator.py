import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.config import Settings
from app.context import ContextProvider
from app.orchestrator import StageOrchestrator
from app.state import RuntimeState, WebSocketHub


def test_only_ready_stage_paths_become_active() -> None:
    payload = {
        "items": [
            {"name": "live/stage-1", "ready": True},
            {"name": "live/stage-2", "ready": False},
            {"name": "unrelated", "ready": True},
        ]
    }
    assert StageOrchestrator._active_stages(payload) == {"1"}


@pytest.mark.asyncio
async def test_offline_stage_waits_for_grace_without_replacing_worker() -> None:
    settings = Settings(stream_grace_seconds=15)
    orchestrator = StageOrchestrator(
        settings,
        RuntimeState(),
        WebSocketHub(),
        ContextProvider(settings),
    )
    orchestrator.workers["1"] = SimpleNamespace(  # type: ignore[assignment]
        process=SimpleNamespace(returncode=None)
    )
    orchestrator.stop_worker = AsyncMock()  # type: ignore[method-assign]

    await orchestrator._reconcile(set())
    orchestrator.stop_worker.assert_not_awaited()
    assert "1" in orchestrator.workers

    orchestrator._offline_since["1"] = time.monotonic() - 16
    await orchestrator._reconcile(set())
    orchestrator.stop_worker.assert_awaited_once_with("1", "stream_stopped")
