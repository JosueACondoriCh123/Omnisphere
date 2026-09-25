import httpx
import pytest

from app.config import Settings
from app.state import RuntimeState
from app.transcriber_monitor import TranscriberMonitor


@pytest.mark.asyncio
async def test_transcriber_monitor_degrades_and_recovers() -> None:
    responses = [
        httpx.Response(
            503,
            json={
                "status": "not_ready",
                "model": "gemini-3.5-flash",
                "engine": {"last_error": "invalid key"},
            },
        ),
        httpx.Response(
            200,
            json={
                "status": "ready",
                "model": "gemini-3.5-flash",
                "engine": {"last_error": None},
            },
        ),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        response = responses.pop(0)
        response.request = request
        return response

    runtime = RuntimeState()
    monitor = TranscriberMonitor(Settings(), runtime)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await monitor.check_once(client)
        assert runtime.transcriber_up is False
        assert runtime.transcriber_error == "invalid key"
        await monitor.check_once(client)

    assert runtime.transcriber_up is True
    assert runtime.transcriber_error is None
    assert runtime.transcriber_model == "gemini-3.5-flash"
    assert runtime.transcriber_checked_at is not None
