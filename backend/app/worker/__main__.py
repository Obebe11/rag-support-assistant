"""Worker entry point: `python -m app.worker`."""

import asyncio
import signal

from app.core.config import get_settings
from app.core.db import create_engine, create_session_factory
from app.core.logging import configure_logging
from app.providers.factory import build_providers
from app.worker.handlers import load_handlers
from app.worker.registry import JobRegistry
from app.worker.runner import Worker


async def main() -> None:
    configure_logging()
    settings = get_settings()
    engine = create_engine(settings.database_url)
    providers = build_providers(settings)
    registry = JobRegistry()
    load_handlers(registry)
    worker = Worker(
        session_factory=create_session_factory(engine),
        registry=registry,
        settings=settings,
        providers=providers,
    )
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_number in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signal_number, stop.set)
    try:
        await worker.run_forever(stop)
    finally:
        await providers.aclose()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
