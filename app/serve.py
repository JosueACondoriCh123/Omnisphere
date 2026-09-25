"""Run internal and public ASGI origins in one native Windows process."""

from __future__ import annotations

import asyncio
import os
import signal
from collections.abc import Iterator
from contextlib import contextmanager

import uvicorn

from app.main import app
from app.public import public_app


class ManagedServer(uvicorn.Server):
    @contextmanager
    def capture_signals(self) -> Iterator[None]:
        # One process owns both listeners; a shared handler shuts both down.
        yield


async def run() -> None:
    operator = ManagedServer(
        uvicorn.Config(app, host="127.0.0.1", port=int(os.environ.get("OMNISTAGE_OPERATOR_PORT", "8080")),
                       log_level="info", lifespan="on")
    )
    audience = ManagedServer(
        uvicorn.Config(public_app, host=os.environ.get("OMNISTAGE_PUBLIC_BIND", "0.0.0.0"),
                       port=int(os.environ.get("OMNISTAGE_PUBLIC_PORT", "8088")),
                       log_level="info", lifespan="off")
    )
    def stop(*_: object) -> None:
        operator.should_exit = True
        audience.should_exit = True

    previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    for sig in previous:
        signal.signal(sig, stop)
    try:
        await asyncio.gather(operator.serve(), audience.serve())
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    asyncio.run(run())
