"""Job handler modules. Each module has one owner and registers its own handlers."""

from app.worker.handlers import delivery, indexing
from app.worker.registry import JobRegistry


def load_handlers(registry: JobRegistry) -> None:
    indexing.register(registry)
    delivery.register(registry)
