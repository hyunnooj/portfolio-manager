from celery import Celery

from app.core.config import Settings

settings = Settings()
celery_app = Celery(
    "portfolio",
    broker=settings.redis_url.get_secret_value(),
    backend=settings.redis_url.get_secret_value(),
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    result_expires=300,
    broker_connection_retry_on_startup=True,
    task_default_queue="foundation",
    worker_prefetch_multiplier=1,
    beat_schedule={},  # No production schedules before their corresponding feature STEP.
)


@celery_app.task(name="foundation.health")
def health_task() -> dict[str, str]:
    return {"status": "OK"}
