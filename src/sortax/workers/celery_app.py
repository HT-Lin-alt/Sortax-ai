from celery import Celery  # type: ignore[import-untyped]

from sortax.config import get_worker_settings
from sortax.observability.logging import configure_logging

settings = get_worker_settings()
configure_logging(settings.log_level)

celery_app = Celery(
    "sortax",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    enable_utc=True,
    timezone="UTC",
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)


@celery_app.task(name="sortax.health.ping")  # type: ignore[untyped-decorator]
def ping() -> str:
    return "pong"
